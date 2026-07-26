"""Load and validate the release target authority."""

from __future__ import annotations

import platform
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


# Deliberate fail-closed schema guard: load() rejects both unknown authority
# targets and any member of this tuple missing from the authority.
TARGET_IDS = ("linux-x86_64", "linux-aarch64", "macos-arm64")
_ROOT_KEYS = {"release", "targets"}
_RELEASE_KEYS = {
    "sol_revision",
    "upstream_base_commit",
    "ca_snapshot_date",
    "ca_bundle_url",
    "ca_bundle_sha256",
    "archive_xz_preset",
    "archive_xz_threads",
}
_TARGET_KEYS = {
    "id",
    "host_os",
    "host_machines",
    "build_image",
    "gate_images",
    "container_platform",
    "archive_name",
    "binary_format",
    "expected_arch",
    "abi_kind",
    "abi_floor",
    "runtime_allowlist",
    "members",
    "directory_counts",
    "required_tools",
    "macho_install_id",
    "macho_rpath",
}
_DIGEST_REFERENCE = re.compile(r"^[^@\s]+@sha256:[0-9a-f]{64}$")


class AuthorityError(ValueError):
    """An invalid authority or incompatible selection."""


@dataclass(frozen=True)
class Authority:
    path: Path
    release: dict[str, Any]
    targets: dict[str, dict[str, Any]]

    def target(self, target_id: str) -> dict[str, Any]:
        try:
            return self.targets[target_id]
        except KeyError as error:
            valid = ", ".join(TARGET_IDS)
            raise AuthorityError(
                f"unknown target {target_id!r}; valid targets: {valid}"
            ) from error

    def compatible_target(
        self, os_name: str | None = None, machine: str | None = None
    ) -> str:
        os_name = os_name or platform.system()
        machine = machine or platform.machine()
        matches = [
            target_id
            for target_id, target in self.targets.items()
            if target["host_os"] == os_name and machine in target["host_machines"]
        ]
        if len(matches) != 1:
            raise AuthorityError(
                f"unsupported release host {os_name}/{machine}; "
                f"valid targets: {', '.join(TARGET_IDS)}"
            )
        return matches[0]

    def require_compatible(
        self,
        target_id: str,
        os_name: str | None = None,
        machine: str | None = None,
        recovery_variable: str = "TARGET",
    ) -> dict[str, Any]:
        target = self.target(target_id)
        os_name = os_name or platform.system()
        machine = machine or platform.machine()
        if target["host_os"] != os_name or machine not in target["host_machines"]:
            compatible = self.compatible_target(os_name, machine)
            raise AuthorityError(
                f"target {target_id} is incompatible with host {os_name}/{machine}; "
                f"compatible target: {compatible}; retry with "
                f"{recovery_variable}={compatible}"
            )
        return target


def _unknown_keys(name: str, value: dict[str, Any], allowed: set[str]) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise AuthorityError(f"{name} has unknown fields: {', '.join(unknown)}")


def _validate_member(target_id: str, member: object) -> None:
    if not isinstance(member, dict):
        raise AuthorityError(f"{target_id}: each member must be a table")
    allowed = {"path", "kind", "link_target"}
    _unknown_keys(f"{target_id} member", member, allowed)
    if member.get("kind") not in {"regular", "symlink"}:
        raise AuthorityError(f"{target_id}: invalid member kind for {member.get('path')}")
    if not isinstance(member.get("path"), str) or not member["path"]:
        raise AuthorityError(f"{target_id}: member path must be nonempty")
    if Path(member["path"]).is_absolute() or ".." in Path(member["path"]).parts:
        raise AuthorityError(f"{target_id}: unsafe member path {member['path']!r}")
    if member["kind"] == "symlink" and not member.get("link_target"):
        raise AuthorityError(f"{target_id}: symlink {member['path']} needs link_target")
    if member["kind"] == "regular" and "link_target" in member:
        raise AuthorityError(f"{target_id}: regular file {member['path']} has link_target")


def load(path: Path | None = None) -> Authority:
    path = path or Path(__file__).resolve().parents[1] / "targets.toml"
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise AuthorityError(f"cannot load release authority {path}: {error}") from error
    if not isinstance(data, dict):
        raise AuthorityError("release authority root must be a table")
    _unknown_keys("release authority", data, _ROOT_KEYS)
    release = data.get("release")
    targets = data.get("targets")
    if not isinstance(release, dict) or not isinstance(targets, list):
        raise AuthorityError("release authority requires [release] and [[targets]]")
    _unknown_keys("release", release, _RELEASE_KEYS)
    missing_release = sorted(_RELEASE_KEYS - set(release))
    if missing_release:
        raise AuthorityError(f"release is missing fields: {', '.join(missing_release)}")
    if not re.fullmatch(r"[0-9a-f]{64}", str(release["ca_bundle_sha256"])):
        raise AuthorityError("release.ca_bundle_sha256 must be 64 lowercase hex digits")
    if not isinstance(release["upstream_base_commit"], str) or not re.fullmatch(
        r"[0-9a-f]{40}", release["upstream_base_commit"]
    ):
        raise AuthorityError(
            "release.upstream_base_commit must be 40 lowercase hex digits"
        )

    indexed: dict[str, dict[str, Any]] = {}
    for target in targets:
        if not isinstance(target, dict):
            raise AuthorityError("each target must be a table")
        _unknown_keys("target", target, _TARGET_KEYS)
        required_target_keys = _TARGET_KEYS - {"macho_install_id", "macho_rpath"}
        missing = sorted(required_target_keys - set(target))
        if missing:
            raise AuthorityError(
                f"target {target.get('id', '<unknown>')} is missing fields: "
                f"{', '.join(missing)}"
            )
        target_id = target["id"]
        if target_id in indexed:
            raise AuthorityError(f"duplicate target: {target_id}")
        if target_id not in TARGET_IDS:
            raise AuthorityError(f"unknown target: {target_id}")
        if not isinstance(target["host_machines"], list) or not target["host_machines"]:
            raise AuthorityError(f"{target_id}: host_machines must be a nonempty list")
        images = [target["build_image"], *target["gate_images"]]
        for image in images:
            if image != "none" and not _DIGEST_REFERENCE.fullmatch(image):
                raise AuthorityError(f"{target_id}: image is not digest-pinned: {image}")
        if target["binary_format"] == "macho64-le":
            if target["build_image"] != "none" or target["gate_images"]:
                raise AuthorityError(
                    f"{target_id}: Mach-O targets must not declare container images"
                )
            for field in ("macho_install_id", "macho_rpath"):
                if not isinstance(target.get(field), str) or not target[field]:
                    raise AuthorityError(f"{target_id}: Mach-O target requires {field}")
        elif target["build_image"] == "none" or len(target["gate_images"]) != 2:
            raise AuthorityError(f"{target_id}: Linux targets need one build and two gate images")
        elif "macho_install_id" in target or "macho_rpath" in target:
            raise AuthorityError(f"{target_id}: Mach-O policy requires binary_format=macho64-le")
        if not isinstance(target["members"], list) or not target["members"]:
            raise AuthorityError(f"{target_id}: members must be a nonempty list")
        for member in target["members"]:
            _validate_member(target_id, member)
        member_paths = [member["path"] for member in target["members"]]
        if len(member_paths) != len(set(member_paths)):
            raise AuthorityError(f"{target_id}: duplicate archive member")
        if not isinstance(target["required_tools"], list) or not target["required_tools"]:
            raise AuthorityError(f"{target_id}: required_tools must be a nonempty list")
        if any(not isinstance(tool, str) or not tool for tool in target["required_tools"]):
            raise AuthorityError(f"{target_id}: required_tools contains an invalid tool")
        indexed[target_id] = target

    missing_targets = [target_id for target_id in TARGET_IDS if target_id not in indexed]
    if missing_targets:
        raise AuthorityError(f"missing targets: {', '.join(missing_targets)}")
    return Authority(path=path, release=release, targets=indexed)


def read_allowlist(authority: Authority, target: dict[str, Any]) -> list[str]:
    path = Path(target["runtime_allowlist"])
    if not path.is_absolute():
        path = authority.path.resolve().parents[2] / path
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise AuthorityError(
            f"cannot read runtime allowlist {path}: {error}; restore it with "
            f"`git restore -- {path}` and retry"
        ) from error
    values = [line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")]
    if not values:
        raise AuthorityError(
            f"runtime allowlist is empty: {path}; restore the reviewed file with "
            f"`git restore -- {path}` and retry"
        )
    return values
