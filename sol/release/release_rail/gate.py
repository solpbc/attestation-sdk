"""Shared target policy for parsed ELF and Mach-O artifacts."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from . import elf, macho


FORBIDDEN_CA_PATHS = (
    b"/etc/ssl/certs/ca-certificates.crt",
    b"/etc/pki/tls/certs/ca-bundle.crt",
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
    _forbidden_strings(path, info.data)


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
