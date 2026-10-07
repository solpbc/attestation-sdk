"""Shared target policy for parsed ELF and Mach-O artifacts."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from . import elf, macho


FORBIDDEN_CA_PATHS = (
    b"/etc/ssl/certs/ca-certificates.crt",
    b"/etc/pki/tls/certs/ca-bundle.crt",
    b"/etc/ssl/cert.pem",
)
FORBIDDEN_OPENSSLDIR_PATHS = (
    b"openssl-install/certs",
    b"openssl-install/cert.pem",
    b"openssl-install/private",
    b"openssl-install/ct_log_list.cnf",
)
FORBIDDEN_OPENSSL_MODULE_PATHS = (
    b"openssl-install/lib/ossl-modules",
    b"openssl-install/lib/engines-3",
)
_VERSION = re.compile(r"^(GLIBC|GLIBCXX|CXXABI)_([0-9]+(?:\.[0-9]+)*)$")
_ELF_MACHINES = {"EM_X86_64": elf.EM_X86_64, "EM_AARCH64": elf.EM_AARCH64}


class GateError(ValueError):
    def __init__(self, message: str):
        super().__init__(
            f"{message}; rebuild the target artifact with the reported policy "
            "violation corrected, then retry"
        )


def is_binary_member(member: dict[str, Any]) -> bool:
    path = member["path"]
    return path == "bin/nvattest" or (
        path.startswith("lib/") and member["kind"] == "regular"
    )


def _version_tuple(value: str) -> tuple[int, ...]:
    return tuple(int(component) for component in value.split("."))


def _forbidden_strings(path: Path, data: bytes) -> None:
    for value in FORBIDDEN_CA_PATHS:
        if value in data:
            raise GateError(f"{path}: compiled host CA path found: {value.decode()}")
    for value in FORBIDDEN_OPENSSLDIR_PATHS:
        if value in data:
            raise GateError(f"{path}: build-tree openssldir path found: {value.decode()}")
    for value in FORBIDDEN_OPENSSL_MODULE_PATHS:
        if value in data:
            raise GateError(f"{path}: build-tree OpenSSL module or engine root found: {value.decode()}")


def gate_elf(path: Path, target: dict[str, Any], allowlist: list[str]) -> None:
    info = elf.read(path)
    expected = _ELF_MACHINES[target["expected_arch"]]
    if info.machine != expected:
        raise GateError(
            f"{path}: wrong ELF architecture: expected {target['expected_arch']} "
            f"({expected}), got e_machine={info.machine}"
        )
    if not info.needed:
        raise GateError(f"{path}: no DT_NEEDED entries found")
    allowed = set(allowlist)
    for needed in info.needed:
        if needed not in allowed:
            raise GateError(f"{path}: forbidden DT_NEEDED entry: {needed}")
    floor_keys = {"GLIBC": "glibc", "GLIBCXX": "glibcxx", "CXXABI": "cxxabi"}
    for version in info.versions:
        match = _VERSION.fullmatch(version)
        if not match:
            continue
        family, value = match.groups()
        limit = target["abi_floor"][floor_keys[family]]
        if _version_tuple(value) > _version_tuple(limit):
            raise GateError(
                f"{path}: {family} requirement {value} exceeds target floor {limit}"
            )
    _gate_elf_runpath(path, info, target)
    _forbidden_strings(path, info.data)


def _gate_elf_runpath(path: Path, info: elf.ElfInfo, target: dict[str, Any]) -> None:
    """A library carries no loader path; the executable names exactly one."""
    if info.rpaths:
        raise GateError(f"{path}: DT_RPATH is not permitted, got {list(info.rpaths)}")
    if info.soname:
        if info.runpaths:
            raise GateError(
                f"{path}: library must not contain DT_RUNPATH, got {list(info.runpaths)}"
            )
        return
    for runpath in info.runpaths:
        if any(not entry for entry in runpath.split(":")):
            raise GateError(f"{path}: DT_RUNPATH {runpath!r} has an empty entry")
    if info.runpaths != (target["elf_runpath"],):
        raise GateError(
            f"{path}: executable must contain exactly "
            f"DT_RUNPATH={target['elf_runpath']}, got {list(info.runpaths)}"
        )


def build_root_strings(roots: list[str] | tuple[str, ...]) -> tuple[bytes, ...]:
    """Validate this build's host roots for the build-root gate."""
    values: list[bytes] = []
    for root in roots:
        if not isinstance(root, str) or not root.startswith("/"):
            raise GateError(f"build root {root!r} is not an absolute path")
        normalized = root.rstrip("/")
        # A one-component root such as /src or /root also matches ordinary
        # relative paths (regorus-src/src/...), so it cannot be a plain
        # substring test. The Linux build therefore runs under distinctive
        # container roots.
        if normalized.count("/") < 2:
            raise GateError(
                f"build root {root!r} has fewer than two path components and "
                "cannot be tested as a plain substring"
            )
        encoded = normalized.encode()
        if encoded not in values:
            values.append(encoded)
    if not values:
        raise GateError("no build roots supplied to the build-root gate")
    return tuple(values)


def gate_build_root_files(paths: list[Path], roots: tuple[bytes, ...]) -> None:
    """Refuse any build root found as a substring of any of the files."""
    for path in paths:
        try:
            data = path.read_bytes()
        except OSError as error:
            raise GateError(f"{path}: cannot read archive member: {error}") from error
        for root in roots:
            if root in data:
                raise GateError(
                    f"{path}: build-host root found: {root.decode()} "
                    f"({data.count(root)} occurrence(s))"
                )


def gate_build_roots(tree: Path, members: list[dict[str, Any]], roots: tuple[bytes, ...]) -> None:
    """Refuse any build root found as a substring of any regular archive member."""
    gate_build_root_files(
        [tree / member["path"] for member in members if member["kind"] == "regular"],
        roots,
    )


def _allowed_macho_reference(reference: str, allowlist: list[str]) -> bool:
    for rule in allowlist:
        kind, separator, value = rule.partition(":")
        if not separator:
            continue
        if kind == "exact" and reference == value:
            return True
        if kind == "prefix" and reference.startswith(value):
            return True
    return False


def gate_macho(path: Path, target: dict[str, Any], allowlist: list[str]) -> None:
    info = macho.read(path)
    if info.cputype != macho.CPU_TYPE_ARM64:
        raise GateError(
            f"{path}: wrong Mach-O architecture: expected CPU_TYPE_ARM64 "
            f"(0x{macho.CPU_TYPE_ARM64:x}), got cputype=0x{info.cputype:x}"
        )
    if info.cpusubtype not in (0,):
        raise GateError(f"{path}: unsupported arm64 cpusubtype {info.cpusubtype}")
    if not info.deployments:
        raise GateError(
            f"{path}: missing LC_BUILD_VERSION and LC_VERSION_MIN_MACOSX"
        )
    if any(platform != 1 for platform in info.platforms):
        raise GateError(f"{path}: LC_BUILD_VERSION platform must be macOS (1)")
    expected = _version_tuple(target["abi_floor"]["macos"])
    expected = (*expected, *(0 for _ in range(3 - len(expected))))
    if any(value != expected for value in info.deployments):
        rendered = ", ".join(".".join(map(str, value)) for value in info.deployments)
        raise GateError(
            f"{path}: macOS deployment target must be "
            f"{'.'.join(map(str, expected))}, got {rendered}"
        )
    identities = [
        reference for command, reference in info.dylibs if command == macho.LC_ID_DYLIB
    ]
    loaded = [
        reference for command, reference in info.dylibs if command != macho.LC_ID_DYLIB
    ]
    if not loaded:
        raise GateError(f"{path}: no Mach-O load-dylib entries found")
    if identities:
        if identities != [target["macho_install_id"]]:
            raise GateError(
                f"{path}: LC_ID_DYLIB must be {target['macho_install_id']}, "
                f"got {identities}"
            )
        if info.rpaths:
            raise GateError(f"{path}: library must not contain LC_RPATH")
    elif info.rpaths != (target["macho_rpath"],):
        raise GateError(
            f"{path}: executable must contain exactly "
            f"LC_RPATH={target['macho_rpath']}"
        )
    for reference in loaded:
        if not _allowed_macho_reference(reference, allowlist):
            raise GateError(f"{path}: forbidden Mach-O runtime reference: {reference}")
    _forbidden_strings(path, info.data)


def gate_file(
    path: Path, target: dict[str, Any], allowlist: list[str]
) -> None:
    try:
        if target["binary_format"] == "elf64-le":
            gate_elf(path, target, allowlist)
        elif target["binary_format"] == "macho64-le":
            gate_macho(path, target, allowlist)
        else:
            raise GateError(f"{path}: unsupported binary format {target['binary_format']}")
    except (elf.ElfError, macho.MachOError) as error:
        raise GateError(str(error)) from error
