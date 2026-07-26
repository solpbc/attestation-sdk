"""Native Apple toolchain discovery and normalized evidence."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any, Callable


EVIDENCE_KEY = "apple_toolchain"
APPLE_CLANG_NAME = "Apple clang"
SDK_NAME = "macosx"

_VERSION = re.compile(r"^[0-9]+(?:\.[0-9]+){1,3}$")
_BUILD = re.compile(r"^[A-Za-z0-9.]+$")
_OUTER_KEYS = (
    "apple_clang",
    "xcode",
    "sdk",
    "architecture",
    "deployment_target",
)
_CLANG_KEYS = ("name", "version")
_XCODE_KEYS = ("version", "build")
_SDK_KEYS = ("name", "version", "path")

Runner = Callable[..., subprocess.CompletedProcess]


class AppleToolchainError(RuntimeError):
    pass


def _command(arguments: tuple[str, ...], runner: Runner) -> str:
    try:
        result = runner(
            list(arguments),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError as error:
        raise AppleToolchainError(
            f"Apple toolchain evidence failed: cannot invoke {arguments[0]}: {error}; "
            "install Xcode Command Line Tools and verify the active developer "
            "directory with `xcode-select -p`, then retry"
        ) from error
    if result.returncode:
        reason = (result.stderr or result.stdout or f"exit {result.returncode}").strip()
        raise AppleToolchainError(
            f"Apple toolchain evidence failed: {' '.join(arguments)} failed: {reason}; "
            "select a valid Xcode developer directory with `xcode-select`, then retry"
        )
    value = result.stdout.strip()
    if not value:
        raise AppleToolchainError(
            f"Apple toolchain evidence failed: {' '.join(arguments)} returned empty "
            "output; verify the command and active Xcode selection, then retry"
        )
    return value


def _compiler(output: str) -> dict[str, str]:
    first = output.splitlines()[0].strip()
    match = re.search(r"\bApple clang version ([0-9]+(?:\.[0-9]+){1,3})\b", first)
    if match is None:
        raise AppleToolchainError(
            "Apple toolchain evidence failed: compiler is not normalized AppleClang: "
            f"{first!r}; select the Xcode AppleClang toolchain, then retry"
        )
    return {"name": APPLE_CLANG_NAME, "version": match.group(1)}


def _xcode(output: str) -> dict[str, str]:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if (
        len(lines) != 2
        or not lines[0].startswith("Xcode ")
        or not lines[1].startswith("Build version ")
    ):
        raise AppleToolchainError(
            "Apple toolchain evidence failed: malformed xcodebuild -version output; "
            "run `xcodebuild -version`, correct the active Xcode selection, then retry"
        )
    version = lines[0].removeprefix("Xcode ")
    build = lines[1].removeprefix("Build version ")
    if not _VERSION.fullmatch(version) or not _BUILD.fullmatch(build):
        raise AppleToolchainError(
            "Apple toolchain evidence failed: malformed Xcode version or build "
            "identifier; run `xcodebuild -version`, correct the active Xcode "
            "selection, then retry"
        )
    return {"version": version, "build": build}


def _target_values(target: dict[str, Any]) -> tuple[str, str]:
    floor = target.get("abi_floor", {}).get("macos")
    if not isinstance(floor, str) or not _VERSION.fullmatch(floor):
        raise AppleToolchainError(
            f"{target['id']}: Apple toolchain evidence failed: authority deployment "
            "target is invalid; correct sol/release/targets.toml, then retry"
        )
    if target.get("expected_arch") != "CPU_TYPE_ARM64":
        raise AppleToolchainError(
            f"{target['id']}: Apple toolchain evidence failed: authority architecture "
            "is not CPU_TYPE_ARM64; correct sol/release/targets.toml, then retry"
        )
    return "arm64", floor


def _observed(
    compiler_command: str, target: dict[str, Any], runner: Runner
) -> dict[str, Any]:
    architecture, floor = _target_values(target)
    compiler = _compiler(_command((compiler_command, "--version"), runner))
    xcode = _xcode(_command(("xcodebuild", "-version"), runner))
    sdk_path = _command(("xcrun", "--sdk", SDK_NAME, "--show-sdk-path"), runner)
    sdk_version = _command(
        ("xcrun", "--sdk", SDK_NAME, "--show-sdk-version"), runner
    )
    if not _VERSION.fullmatch(sdk_version):
        raise AppleToolchainError(
            "Apple toolchain evidence failed: malformed macOS SDK version "
            f"{sdk_version!r}; verify `xcrun --sdk macosx --show-sdk-version`, then retry"
        )
    path = Path(sdk_path)
    if not path.is_absolute() or not path.is_dir():
        raise AppleToolchainError(
            "Apple toolchain evidence failed: resolved SDK path is not an absolute "
            f"existing directory: {sdk_path!r}; select a valid Xcode SDK, then retry"
        )
    return validate_evidence(
        {
            "apple_clang": compiler,
            "xcode": xcode,
            "sdk": {"name": SDK_NAME, "version": sdk_version, "path": str(path)},
            "architecture": architecture,
            "deployment_target": floor,
        },
        target,
    )


def preflight(
    target: dict[str, Any], runner: Runner = subprocess.run
) -> dict[str, Any]:
    return _observed(target["required_tools"][0], target, runner)


def _cache(build_dir: Path) -> dict[str, str]:
    path = build_dir / "CMakeCache.txt"
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as error:
        raise AppleToolchainError(
            f"Apple toolchain evidence failed: cannot read {path}: {error}; remove "
            "build/release and rerun the native configure"
        ) from error
    wanted = {
        "CMAKE_CXX_COMPILER",
        "CMAKE_OSX_SYSROOT",
        "CMAKE_OSX_ARCHITECTURES",
        "CMAKE_OSX_DEPLOYMENT_TARGET",
    }
    values: dict[str, str] = {}
    for line in lines:
        name_type, separator, value = line.partition("=")
        name = name_type.partition(":")[0]
        if separator and name in wanted:
            if name in values:
                raise AppleToolchainError(
                    f"Apple toolchain evidence failed: duplicate {name} in "
                    f"{path}; remove build/release and rerun the native configure"
                )
            values[name] = value
    missing = sorted(wanted - values.keys())
    if missing:
        raise AppleToolchainError(
            "Apple toolchain evidence failed: CMake cache is missing "
            f"{', '.join(missing)}; remove build/release and rerun the native configure"
        )
    return values


def _compiler_metadata(build_dir: Path) -> tuple[str, str]:
    paths = sorted((build_dir / "CMakeFiles").glob("*/CMakeCXXCompiler.cmake"))
    if len(paths) != 1:
        raise AppleToolchainError(
            "Apple toolchain evidence failed: cannot read one configured C++ "
            f"compiler record under {build_dir / 'CMakeFiles'}; remove the build "
            "directory and rerun the native configure"
        )
    try:
        text = paths[0].read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        raise AppleToolchainError(
            f"Apple toolchain evidence failed: cannot read {paths[0]}: {error}; "
            "remove the build directory and rerun the native configure"
        ) from error

    def field(name: str) -> str:
        matches = re.findall(
            rf'^set\({re.escape(name)} "([^"]*)"\)$', text, re.MULTILINE
        )
        if len(matches) != 1 or not matches[0]:
            raise AppleToolchainError(
                "Apple toolchain evidence failed: configured C++ compiler record "
                f"has invalid {name}; remove the build directory and rerun the "
                "native configure"
            )
        return matches[0]

    return field("CMAKE_CXX_COMPILER_ID"), field("CMAKE_CXX_COMPILER_VERSION")


def resolve(
    target: dict[str, Any],
    build_dir: Path,
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    values = _cache(build_dir)
    evidence = _observed(values["CMAKE_CXX_COMPILER"], target, runner)
    compiler_id, compiler_version = _compiler_metadata(build_dir)
    if compiler_id != "AppleClang" or (
        compiler_version != evidence["apple_clang"]["version"]
    ):
        raise AppleToolchainError(
            "Apple toolchain evidence failed: compiler observation "
            f"{evidence['apple_clang']['version']} differs from CMake "
            f"{compiler_id} {compiler_version}; select one Xcode toolchain, remove "
            "build/release, and retry"
        )
    configured_sdk = Path(values["CMAKE_OSX_SYSROOT"])
    observed_sdk = Path(evidence["sdk"]["path"])
    if (
        not configured_sdk.is_absolute()
        or not configured_sdk.is_dir()
        or configured_sdk.resolve() != observed_sdk.resolve()
    ):
        raise AppleToolchainError(
            "Apple toolchain evidence failed: configured SDK sysroot "
            f"{str(configured_sdk)!r} differs from active SDK "
            f"{str(observed_sdk)!r}; remove build/release, select a valid Xcode "
            "SDK, and retry"
        )
    if values["CMAKE_OSX_ARCHITECTURES"] != evidence["architecture"]:
        raise AppleToolchainError(
            "Apple toolchain evidence failed: configured architecture "
            f"{values['CMAKE_OSX_ARCHITECTURES']!r} is not arm64; remove "
            "build/release and retry with a native arm64 toolchain"
        )
    if values["CMAKE_OSX_DEPLOYMENT_TARGET"] != evidence["deployment_target"]:
        raise AppleToolchainError(
            "Apple toolchain evidence failed: configured deployment target "
            f"{values['CMAKE_OSX_DEPLOYMENT_TARGET']!r} differs from authority "
            f"{evidence['deployment_target']!r}; remove build/release and retry "
            "make release TARGET=macos-arm64"
        )
    return evidence


def validate_evidence(
    value: Any, target: dict[str, Any] | None = None
) -> dict[str, Any]:
    if not isinstance(value, dict) or tuple(value) != _OUTER_KEYS:
        raise AppleToolchainError(
            "Apple toolchain evidence has invalid fields; rebuild the Darwin "
            "manifest with `make release TARGET=macos-arm64` on its native host"
        )
    clang = value.get("apple_clang")
    xcode = value.get("xcode")
    sdk = value.get("sdk")
    if not isinstance(clang, dict) or tuple(clang) != _CLANG_KEYS:
        raise AppleToolchainError(
            "Apple toolchain evidence has invalid AppleClang fields; rebuild the "
            "Darwin manifest with `make release TARGET=macos-arm64` on its native host"
        )
    if not isinstance(xcode, dict) or tuple(xcode) != _XCODE_KEYS:
        raise AppleToolchainError(
            "Apple toolchain evidence has invalid Xcode fields; rebuild the Darwin "
            "manifest with `make release TARGET=macos-arm64` on its native host"
        )
    if not isinstance(sdk, dict) or tuple(sdk) != _SDK_KEYS:
        raise AppleToolchainError(
            "Apple toolchain evidence has invalid SDK fields; rebuild the Darwin "
            "manifest with `make release TARGET=macos-arm64` on its native host"
        )
    scalar_fields = (
        clang["name"],
        clang["version"],
        xcode["version"],
        xcode["build"],
        sdk["name"],
        sdk["version"],
        sdk["path"],
        value["architecture"],
        value["deployment_target"],
    )
    if any(not isinstance(field, str) or not field for field in scalar_fields):
        raise AppleToolchainError(
            "Apple toolchain evidence must be normalized; rebuild the Darwin manifest "
            "with `make release TARGET=macos-arm64` on its native host"
        )
    if (
        clang["name"] != APPLE_CLANG_NAME
        or sdk["name"] != SDK_NAME
        or value["architecture"] != "arm64"
        or not _VERSION.fullmatch(clang["version"])
        or not _VERSION.fullmatch(xcode["version"])
        or not _BUILD.fullmatch(xcode["build"])
        or not _VERSION.fullmatch(sdk["version"])
        or not Path(sdk["path"]).is_absolute()
        or not _VERSION.fullmatch(value["deployment_target"])
    ):
        raise AppleToolchainError(
            "Apple toolchain evidence has invalid normalized values; rebuild the "
            "Darwin manifest with `make release TARGET=macos-arm64` on its native host"
        )
    if target is not None:
        architecture, floor = _target_values(target)
        if value["architecture"] != architecture:
            raise AppleToolchainError(
                f"{target['id']}: Apple toolchain architecture is incompatible "
                "with target architecture; rebuild the Darwin manifest with "
                "`make release TARGET=macos-arm64` on its native host"
            )
        if value["deployment_target"] != floor:
            raise AppleToolchainError(
                f"{target['id']}: Apple deployment target differs from authority; "
                "rebuild the Darwin manifest with "
                "`make release TARGET=macos-arm64` on its native host"
            )
    return value
