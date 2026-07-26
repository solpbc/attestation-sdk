"""Native OCI runtime selection and normalized evidence."""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


PODMAN = "podman"
DOCKER = "docker"
RUNTIME_NAMES = (PODMAN, DOCKER)
LOCAL_IMAGE_TAG = "attestation-sdk-ci"
EVIDENCE_KEY = "container_runtime"
PODMAN_PRODUCT = "Podman Engine"
DOCKER_PRODUCT = "Docker Engine"
MOUNT_RW_SUFFIX = "Z"
MOUNT_RO_SUFFIX = "ro,Z"

PODMAN_VERSION = (PODMAN, "version")
PODMAN_VERSION_FIELDS = (
    PODMAN,
    "version",
    "--format",
    "{{.Client.Version}}\t{{.Client.APIVersion}}\t{{.Client.Os}}\t{{.Client.OsArch}}",
)
PODMAN_INFO = (
    PODMAN,
    "info",
    "--format",
    "{{.Version.Version}}\t{{.Host.OS}}\t{{.Host.Arch}}\t{{.Host.Security.Rootless}}",
)
DOCKER_VERSION = (
    DOCKER,
    "version",
    "--format",
    "{{.Client.Platform.Name}}\t{{.Client.Version}}\t"
    "{{.Server.Platform.Name}}\t{{.Server.Version}}\t{{.Server.Os}}\t"
    "{{.Server.Arch}}",
)
DOCKER_INFO = (
    DOCKER,
    "info",
    "--format",
    "{{.ServerVersion}}\t{{.OSType}}\t{{.Architecture}}",
)
DOCKER_ENDPOINT = (
    DOCKER,
    "context",
    "inspect",
    "--format",
    "{{.Endpoints.docker.Host}}",
)

_VERSION = re.compile(r"^[0-9]+(?:\.[0-9]+){1,3}$")
_TOOL_KEYS = ("client", "engine")
_IDENTITY_KEYS = ("name", "version")
_ENGINE_KEYS = ("name", "version", "os", "architecture")


class RuntimeSelectionError(RuntimeError):
    pass


@dataclass(frozen=True)
class Selection:
    name: str
    evidence: dict[str, Any]


Runner = Callable[..., subprocess.CompletedProcess]


def _command(
    arguments: tuple[str, ...], runner: Runner = subprocess.run
) -> str:
    try:
        result = runner(
            list(arguments),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError as error:
        raise RuntimeSelectionError(f"{arguments[0]} is unusable: {error}") from error
    if result.returncode:
        reason = (result.stderr or result.stdout or f"exit {result.returncode}").strip()
        raise RuntimeSelectionError(
            f"{' '.join(arguments[:2])} failed: {reason}"
        )
    return result.stdout.strip()


def _fields(output: str, count: int, command: str) -> list[str]:
    values = output.split("\t")
    if len(values) != count or any(not value.strip() for value in values):
        raise RuntimeSelectionError(f"malformed response from {command}")
    return [value.strip() for value in values]


def _version(value: str, command: str) -> str:
    if not _VERSION.fullmatch(value):
        raise RuntimeSelectionError(f"malformed version from {command}: {value!r}")
    return value


def _architecture(value: str) -> str:
    normalized = {
        "amd64": "amd64",
        "x86_64": "amd64",
        "arm64": "arm64",
        "aarch64": "arm64",
    }.get(value.lower())
    if normalized is None:
        raise RuntimeSelectionError(f"unsupported engine architecture: {value}")
    return normalized


def _podman_identity(output: str) -> tuple[str, str]:
    lines = output.splitlines()
    clients = [index for index, line in enumerate(lines) if line.startswith("Client:")]
    if len(clients) != 1:
        raise RuntimeSelectionError("podman version did not identify one client")
    start = clients[0]
    if lines[start].partition(":")[2].strip() != PODMAN_PRODUCT:
        raise RuntimeSelectionError("podman version reported the wrong product")
    end = next(
        (
            index
            for index in range(start + 1, len(lines))
            if lines[index].startswith(("Client:", "Server:"))
        ),
        len(lines),
    )
    versions = [
        line.partition(":")[2].strip()
        for line in lines[start + 1 : end]
        if line.startswith("Version:")
    ]
    if len(versions) != 1:
        raise RuntimeSelectionError("podman version did not report one client version")
    return PODMAN_PRODUCT, _version(versions[0], PODMAN_VERSION[0])


def _docker_product(value: str) -> str:
    if "docker" not in value.lower():
        raise RuntimeSelectionError("docker version reported the wrong product")
    return DOCKER_PRODUCT


def validate_evidence(
    value: Any, target: dict[str, Any] | None = None
) -> dict[str, Any]:
    if not isinstance(value, dict) or tuple(value) != _TOOL_KEYS:
        raise RuntimeSelectionError("container runtime evidence has invalid fields")
    client = value.get("client")
    engine = value.get("engine")
    if not isinstance(client, dict) or tuple(client) != _IDENTITY_KEYS:
        raise RuntimeSelectionError("container runtime client evidence has invalid fields")
    if not isinstance(engine, dict) or tuple(engine) != _ENGINE_KEYS:
        raise RuntimeSelectionError("container runtime engine evidence has invalid fields")
    for section, fields in ((client, _IDENTITY_KEYS), (engine, _ENGINE_KEYS)):
        if any(not isinstance(section[key], str) or not section[key] for key in fields):
            raise RuntimeSelectionError("container runtime evidence must be normalized")
    products = (client["name"], engine["name"])
    if products not in (
        (PODMAN_PRODUCT, PODMAN_PRODUCT),
        (DOCKER_PRODUCT, DOCKER_PRODUCT),
    ):
        raise RuntimeSelectionError("container runtime evidence has invalid product identity")
    _version(client["version"], "container runtime evidence")
    _version(engine["version"], "container runtime evidence")
    if engine["os"] != "linux":
        raise RuntimeSelectionError("container runtime engine OS must be linux")
    if engine["architecture"] not in {"amd64", "arm64"}:
        raise RuntimeSelectionError(
            "container runtime evidence has invalid engine architecture"
        )
    if target is not None and engine["architecture"] != _target_architecture(target):
        raise RuntimeSelectionError(
            f"{target['id']}: engine architecture {engine['architecture']} is "
            "incompatible with target architecture"
        )
    return value


def _podman(runner: Runner) -> dict[str, Any]:
    client_name, client_version = _podman_identity(_command(PODMAN_VERSION, runner))
    version, api, client_os, os_arch = _fields(
        _command(PODMAN_VERSION_FIELDS, runner), 4, "podman version"
    )
    engine_version, engine_os, engine_arch, rootless = _fields(
        _command(PODMAN_INFO, runner), 4, "podman info"
    )
    _version(api, "podman version")
    if version != client_version or engine_version != client_version:
        raise RuntimeSelectionError("podman version and info evidence disagree")
    os_arch_parts = os_arch.split("/")
    if (
        len(os_arch_parts) != 2
        or client_os != engine_os
        or os_arch_parts != [client_os, engine_arch]
    ):
        raise RuntimeSelectionError("podman version and info platform evidence disagree")
    if rootless not in {"true", "false"}:
        raise RuntimeSelectionError("malformed rootless mode from podman info")
    return validate_evidence(
        {
            "client": {"name": client_name, "version": client_version},
            "engine": {
                "name": PODMAN_PRODUCT,
                "version": engine_version,
                "os": engine_os,
                "architecture": _architecture(engine_arch),
            },
        }
    )


def _docker(runner: Runner, environment: dict[str, str]) -> dict[str, Any]:
    client_name, client_version, engine_name, engine_version, engine_os, engine_arch = (
        _fields(_command(DOCKER_VERSION, runner), 6, "docker version")
    )
    info_version, info_os, info_arch = _fields(
        _command(DOCKER_INFO, runner), 3, "docker info"
    )
    if (engine_version, engine_os, _architecture(engine_arch)) != (
        info_version,
        info_os,
        _architecture(info_arch),
    ):
        raise RuntimeSelectionError("docker version and info evidence disagree")
    endpoint = environment.get("DOCKER_HOST") or _command(DOCKER_ENDPOINT, runner)
    if not endpoint.startswith("unix://") or not endpoint.removeprefix("unix://"):
        raise RuntimeSelectionError(
            f"docker endpoint is not local-unix compatible: {endpoint}"
        )
    return validate_evidence(
        {
            "client": {
                "name": _docker_product(client_name),
                "version": _version(client_version, "docker version"),
            },
            "engine": {
                "name": _docker_product(engine_name),
                "version": _version(engine_version, "docker version"),
                "os": engine_os,
                "architecture": _architecture(engine_arch),
            },
        }
    )


def _target_architecture(target: dict[str, Any] | None) -> str | None:
    if target is None:
        return _architecture(platform.machine())
    expected = {
        ("linux/amd64", "EM_X86_64"): "amd64",
        ("linux/arm64", "EM_AARCH64"): "arm64",
    }.get((target["container_platform"], target["expected_arch"]))
    if expected is None:
        raise RuntimeSelectionError(
            f"{target['id']}: container platform and architecture disagree"
        )
    return expected


def select(
    target: dict[str, Any] | None = None,
    *,
    which: Callable[[str], str | None] = shutil.which,
    runner: Runner = subprocess.run,
    environment: dict[str, str] | None = None,
) -> Selection:
    expected_arch = _target_architecture(target)
    environment = os.environ if environment is None else environment
    diagnostics = []
    for name in RUNTIME_NAMES:
        if which(name) is None:
            diagnostics.append(f"{name}: command not found; install {name}")
            continue
        try:
            evidence = (
                _podman(runner)
                if name == PODMAN
                else _docker(runner, environment)
            )
            actual_arch = evidence["engine"]["architecture"]
            if actual_arch != expected_arch:
                raise RuntimeSelectionError(
                    f"engine architecture {actual_arch} is incompatible with "
                    f"target architecture {expected_arch}"
                )
            return Selection(name=name, evidence=evidence)
        except RuntimeSelectionError as error:
            diagnostics.append(f"{name}: {error}")
    raise RuntimeSelectionError(
        "no usable OCI runtime: "
        + "; ".join(diagnostics)
        + "; recover by installing a working Podman or local Unix-socket Docker engine"
    )


def render_mount(source: Path | str, destination: Path | str, readonly: bool) -> str:
    source_path = Path(source)
    destination_path = Path(destination)
    if not source_path.is_absolute() or not destination_path.is_absolute():
        raise RuntimeSelectionError("container bind mount paths must be absolute")
    suffix = MOUNT_RO_SUFFIX if readonly else MOUNT_RW_SUFFIX
    return f"{source_path}:{destination_path}:{suffix}"
