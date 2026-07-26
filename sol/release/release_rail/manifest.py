"""Schema-v2 release manifest construction and tool evidence."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable

from . import archive, runtime


class ManifestError(RuntimeError):
    pass


_VERSION = re.compile(r"(?<![0-9])([0-9]+(?:\.[0-9]+){1,3})(?![0-9])")
BUILD_TOOL_KEYS = ("compiler", "cmake", "rustc", "cargo", "tar", "xz", "python")


def _compiler_from_cache(build_dir: Path, fallback: str) -> str:
    cache = build_dir / "CMakeCache.txt"
    try:
        for line in cache.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("CMAKE_CXX_COMPILER:FILEPATH="):
                value = line.partition("=")[2]
                if value:
                    return value
    except OSError:
        pass
    # A missing cache occurs before CMake config in fixture tests. In that case
    # this records the authority-named compiler, without claiming CMake chose it.
    return fallback


def _canonical_name(key: str, first_line: str) -> str:
    lowered = first_line.lower()
    if key == "compiler":
        if "apple clang" in lowered:
            return "Apple clang"
        if "clang" in lowered:
            return "clang"
        if "gcc" in lowered or "g++" in lowered:
            return "GCC"
        raise ManifestError(f"unrecognized compiler version output: {first_line}")
    required_tokens = {
        "cmake": "cmake",
        "rustc": "rustc",
        "cargo": "cargo",
        "tar": "gnu tar",
        "xz": "xz",
        "python": "python",
    }
    if required_tokens[key] not in lowered:
        raise ManifestError(f"unrecognized {key} version output: {first_line}")
    return {
        "cmake": "cmake",
        "rustc": "rustc",
        "cargo": "cargo",
        "tar": "GNU tar",
        "xz": "xz",
        "python": "CPython",
    }[key]


def normalize_tool_output(
    key: str, command: str, output: str, returncode: int = 0
) -> dict[str, str]:
    first_line = next((line.strip() for line in output.splitlines() if line.strip()), "")
    match = _VERSION.search(first_line)
    if returncode or not match:
        raise ManifestError(
            f"unparseable version output from required build tool {command}; "
            f"run `{command} --version` and install a working tool"
        )
    return {"name": _canonical_name(key, first_line), "version": match.group(1)}


def _capture(key: str, command: str) -> dict[str, str]:
    executable = shutil.which(command) if not Path(command).is_absolute() else command
    if not executable or not Path(executable).is_file():
        raise ManifestError(
            f"missing required build tool {command}; install it and verify with "
            f"`{command} --version`, then retry"
        )
    try:
        result = subprocess.run(
            [executable, "--version"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
    except OSError as error:
        raise ManifestError(
            f"cannot invoke required build tool {command}; verify with "
            f"`{command} --version`: {error}"
        ) from error
    return normalize_tool_output(key, command, result.stdout, result.returncode)


def capture_build_tools(
    target: dict[str, Any],
    build_dir: Path,
    invoker: Callable[[str, str], str | None] | None = None,
    *,
    runtime_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    commands = list(target["required_tools"])
    compiler_command = _compiler_from_cache(build_dir, commands[0])
    keys = BUILD_TOOL_KEYS
    if len(commands) != len(keys):
        raise ManifestError(
            f"{target['id']}: required_tools must contain exactly {len(keys)} entries"
        )
    commands[0] = compiler_command
    evidence = {}
    for key, command in zip(keys, commands, strict=True):
        output = invoker(key, command) if invoker is not None else None
        evidence[key] = (
            normalize_tool_output(key, command, output)
            if output is not None
            else _capture(key, command)
        )
    if target["host_os"] == "Linux":
        if runtime_evidence is None:
            raise ManifestError(f"{target['id']}: missing container runtime evidence")
        try:
            evidence[runtime.EVIDENCE_KEY] = runtime.validate_evidence(
                runtime_evidence, target
            )
        except runtime.RuntimeSelectionError as error:
            raise ManifestError(f"{target['id']}: {error}") from error
    elif runtime_evidence is not None:
        raise ManifestError(f"{target['id']}: container runtime evidence is not permitted")
    return evidence


def validate_build_tools(target: dict[str, Any], value: Any) -> None:
    if not isinstance(value, dict):
        raise ManifestError(f"{target['id']}: build_tools must be an object")
    expected = BUILD_TOOL_KEYS + (
        (runtime.EVIDENCE_KEY,) if target["host_os"] == "Linux" else ()
    )
    if tuple(value) != expected:
        raise ManifestError(f"{target['id']}: build_tools has invalid fields")
    for key in BUILD_TOOL_KEYS:
        tool = value[key]
        if (
            not isinstance(tool, dict)
            or tuple(tool) != ("name", "version")
            or any(not isinstance(tool[field], str) or not tool[field] for field in tool)
        ):
            raise ManifestError(f"{target['id']}: invalid build tool evidence: {key}")
    if target["host_os"] == "Linux":
        try:
            runtime.validate_evidence(value[runtime.EVIDENCE_KEY], target)
        except runtime.RuntimeSelectionError as error:
            raise ManifestError(f"{target['id']}: {error}") from error


def build(
    *,
    release: dict[str, Any],
    target: dict[str, Any],
    version: str,
    source: dict[str, Any],
    artifact_path: Path,
    dependencies: list[dict[str, Any]],
    build_tools: dict[str, Any],
) -> dict[str, Any]:
    validate_build_tools(target, build_tools)
    return {
        "schema_version": 2,
        "release": {
            "version": version,
            "sol_revision": release["sol_revision"],
        },
        "target": {
            "id": target["id"],
            "binary_format": target["binary_format"],
            "architecture": target["expected_arch"],
            "abi": {
                "kind": target["abi_kind"],
                "floor": target["abi_floor"],
            },
        },
        "source": {
            "commit": source["commit"],
            "upstream_base_commit": source["upstream_base_commit"],
            "sol_series_commits": source["sol_series_commits"],
            "source_date_epoch": source["source_date_epoch"],
        },
        "artifact": {
            "name": artifact_path.name,
            "size": artifact_path.stat().st_size,
            "sha256": archive.sha256(artifact_path),
        },
        "archive_members": [
            {
                "path": member["path"],
                "kind": member["kind"],
                "link_target": member.get("link_target"),
            }
            for member in target["members"]
        ],
        "dependency_pins": dependencies,
        "build_inputs": {
            "build_image": target["build_image"],
            "gate_images": target["gate_images"],
            "ca_snapshot": {
                "date": release["ca_snapshot_date"],
                "url": release["ca_bundle_url"],
                "sha256": release["ca_bundle_sha256"],
            },
            "archive": {
                "tar_format": "gnu",
                "xz_preset": release["archive_xz_preset"],
                "xz_threads": release["archive_xz_threads"],
            },
        },
        "build_tools": build_tools,
    }


def write(path: Path, value: dict[str, Any]) -> Path:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    sidecar = Path(f"{path}.sha256")
    archive.write_sidecar(sidecar, path)
    return sidecar
