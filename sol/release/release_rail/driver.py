"""Native release orchestration."""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any

from . import archive, authority, gate, manifest, set_validator, transaction


class ReleaseError(RuntimeError):
    pass


def _run(arguments: list[str], *, cwd: Path, **kwargs: Any) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(arguments, cwd=cwd, check=True, **kwargs)
    except (OSError, subprocess.CalledProcessError) as error:
        raise ReleaseError(f"command failed: {' '.join(arguments)}: {error}") from error


def _git(root: Path, *arguments: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(root), *arguments], text=True
    ).strip()


def _version(root: Path, data: authority.Authority) -> str:
    return set_validator.release_version(root, data)


def _source(root: Path) -> dict[str, Any]:
    commit = _git(root, "rev-parse", "HEAD")
    base = _git(root, "merge-base", "main", "HEAD")
    log = _git(root, "log", "--reverse", "--format=%H%x09%s", f"{base}..HEAD")
    series = []
    for line in log.splitlines():
        revision, subject = line.split("\t", 1)
        series.append({"commit": revision, "subject": subject})
    return {
        "commit": commit,
        "upstream_base_commit": base,
        "sol_series_commits": series,
        "source_date_epoch": int(_git(root, "log", "-1", "--format=%ct")),
    }


def _download(url: str) -> bytes:
    try:
        with urllib.request.urlopen(url) as response:
            return response.read()
    except Exception as error:
        raise ReleaseError(
            f"pinned dependency unavailable: {url}; verify network access and retry"
        ) from error


def _acquire_ca(release: dict[str, Any], destination: Path) -> None:
    payload = _download(release["ca_bundle_url"])
    published = _download(f"{release['ca_bundle_url']}.sha256")
    destination.write_bytes(payload)
    downloaded_hash = archive.sha256(destination)
    published_hash = published.decode("utf-8").split()[0]
    expected = release["ca_bundle_sha256"]
    if downloaded_hash != expected or published_hash != expected:
        raise ReleaseError(
            "pinned dependency hash mismatch: CA bundle: "
            f"expected={expected} downloaded={downloaded_hash} "
            f"published={published_hash}"
        )


def _validate_layout(stage: Path, target: dict[str, Any]) -> None:
    for item in target["members"]:
        path = stage / item["path"]
        if item["kind"] == "regular":
            if not path.is_file() or path.is_symlink():
                raise ReleaseError(f"layout mismatch: expected regular file: {path}")
        else:
            if not path.is_symlink():
                raise ReleaseError(f"layout mismatch: expected symlink: {path}")
            if os.readlink(path) != item["link_target"]:
                raise ReleaseError(
                    f"layout mismatch: {path}: expected link "
                    f"{item['link_target']}, got {os.readlink(path)}"
                )
    for relative, expected in target["directory_counts"].items():
        directory = stage if relative == "." else stage / relative
        actual = sum(1 for _ in directory.iterdir())
        if actual != expected:
            raise ReleaseError(
                f"layout mismatch: {relative}: expected {expected} entries, got {actual}"
            )


def _copy_member(source: Path, destination: Path, item: dict[str, Any]) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if item["kind"] == "symlink":
        if not source.is_symlink():
            raise ReleaseError(f"layout mismatch: expected build symlink: {source}")
        actual = os.readlink(source)
        if actual != item["link_target"]:
            raise ReleaseError(
                f"layout mismatch: {source}: expected link "
                f"{item['link_target']}, got {actual}"
            )
        destination.symlink_to(actual)
    else:
        if not source.is_file() or source.is_symlink():
            raise ReleaseError(f"layout mismatch: expected build regular file: {source}")
        shutil.copy2(source, destination)


def _build(root: Path, target: dict[str, Any], build_dir: Path) -> None:
    if target["host_os"] == "Linux":
        common = _git(root, "rev-parse", "--path-format=absolute", "--git-common-dir")
        _run(
            [
                "podman",
                "run",
                "--rm",
                f"--platform={target['container_platform']}",
                "-v",
                f"{root}:/src:Z",
                "-v",
                f"{common}:{common}:ro,Z",
                "-w",
                "/src",
                "localhost/attestation-sdk-ci",
                "bash",
                "-ec",
                "rm -rf build/release && "
                "cmake -S nv-attestation-cli -B build/release "
                "-DUSE_SYSTEM_NVAT=OFF -DUSE_SYSTEM_DEPS=OFF "
                "-DBUILD_TESTING=OFF -DBUILD_SHARED_LIBS=ON "
                "-DCMAKE_BUILD_TYPE=Release && "
                "cmake --build build/release -j$(nproc)",
            ],
            cwd=root,
        )
    else:
        if build_dir.exists():
            shutil.rmtree(build_dir)
        _run(
            [
                "cmake",
                "-S",
                "nv-attestation-cli",
                "-B",
                str(build_dir),
                "-DUSE_SYSTEM_NVAT=OFF",
                "-DUSE_SYSTEM_DEPS=OFF",
                "-DBUILD_TESTING=OFF",
                "-DBUILD_SHARED_LIBS=ON",
                "-DCMAKE_BUILD_TYPE=Release",
                "-DCMAKE_OSX_DEPLOYMENT_TARGET=14.0",
            ],
            cwd=root,
        )
        _run(["cmake", "--build", str(build_dir), "-j"], cwd=root)


def _tool_invoker(root: Path, target: dict[str, Any]):
    if target["host_os"] != "Linux":
        return None

    def invoke(key: str, command: str) -> str | None:
        if key not in {"compiler", "cmake", "rustc", "cargo"}:
            return None
        result = subprocess.run(
            [
                "podman",
                "run",
                "--rm",
                f"--platform={target['container_platform']}",
                "-v",
                f"{root}:/src:ro,Z",
                "-w",
                "/src",
                "localhost/attestation-sdk-ci",
                command,
                "--version",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        if result.returncode:
            raise manifest.ManifestError(
                f"missing required build tool {command} in the build image; "
                f"rebuild it with `make image` and retry"
            )
        return result.stdout

    return invoke


def _stage(root: Path, build_dir: Path, stage: Path, target: dict[str, Any], ca: Path) -> None:
    sources = {
        "bin/nvattest": build_dir / "nvattest",
        "LICENSE": root / "LICENSE",
        "share/ca/ca-bundle.pem": ca,
    }
    if target["host_os"] == "Linux":
        library_dir = build_dir / "nv-attestation-sdk-build"
    else:
        library_dir = build_dir / "nv-attestation-sdk-build"
    for item in target["members"]:
        relative = item["path"]
        if relative == "share/THIRD_PARTY_NOTICES.md":
            continue
        source = sources.get(relative, library_dir / Path(relative).name)
        _copy_member(source, stage / relative, item)


def _gate_binaries(stage: Path, data: authority.Authority, target: dict[str, Any]) -> None:
    allowlist = authority.read_allowlist(data, target)
    for item in target["members"]:
        path = item["path"]
        if path == "bin/nvattest" or (
            path.startswith("lib/") and item["kind"] == "regular"
        ):
            gate.gate_file(stage / path, target, allowlist)


def _write_specs(owned: Path, target: dict[str, Any]) -> tuple[Path, Path]:
    layout = owned / "layout.tsv"
    counts = owned / "counts.tsv"
    layout.write_text(
        "".join(
            f"{item['kind']}\t{item['path']}\t{item.get('link_target', '')}\n"
            for item in target["members"]
        ),
        encoding="utf-8",
    )
    counts.write_text(
        "".join(
            f"{directory}\t{count}\n"
            for directory, count in target["directory_counts"].items()
        ),
        encoding="utf-8",
    )
    return layout, counts


def _runtime_gates(
    root: Path,
    owned: Path,
    extracted: Path,
    quartet: dict[str, Path],
    target: dict[str, Any],
    checkpoint: Any,
) -> None:
    layout, counts = _write_specs(owned, target)
    script = root / "sol/release/runtime-gate.sh"
    common_arguments = [
        "/artifact",
        f"/release/{quartet['archive'].name}",
        f"/release/{quartet['archive-sha256'].name}",
        f"/release/{quartet['manifest'].name}",
        f"/release/{quartet['manifest-sha256'].name}",
        "/gate/layout.tsv",
        "/gate/counts.tsv",
        "linux",
    ]
    if target["host_os"] == "Linux":
        for label, image in zip(
            ("fedora", "tumbleweed"), target["gate_images"], strict=True
        ):
            _run(
                [
                    "podman",
                    "run",
                    "--rm",
                    f"--platform={target['container_platform']}",
                    "-v",
                    f"{extracted}:/artifact:ro,Z",
                    "-v",
                    f"{owned}:/release:ro,Z",
                    "-v",
                    f"{script}:/gate/runtime-gate.sh:ro,Z",
                    "-v",
                    f"{layout}:/gate/layout.tsv:ro,Z",
                    "-v",
                    f"{counts}:/gate/counts.tsv:ro,Z",
                    image,
                    "sh",
                    "/gate/runtime-gate.sh",
                    *common_arguments,
                ],
                cwd=root,
            )
            checkpoint(f"after-runtime-gate:{label}")
    else:
        _run(
            [
                str(script),
                str(extracted),
                str(quartet["archive"]),
                str(quartet["archive-sha256"]),
                str(quartet["manifest"]),
                str(quartet["manifest-sha256"]),
                str(layout),
                str(counts),
                "macos",
            ],
            cwd=root,
        )
        checkpoint("after-runtime-gate:macos-native")


def _preflight(root: Path, target_id: str | None) -> tuple[authority.Authority, dict[str, Any]]:
    data = authority.load()
    compatible = data.compatible_target()
    if not target_id:
        valid = ", ".join(authority.TARGET_IDS)
        raise ReleaseError(
            f"release target is required; valid targets: {valid}; "
            f"compatible target: {compatible}; retry with "
            f"`make release TARGET={compatible}`"
        )
    try:
        target = data.require_compatible(target_id)
    except authority.AuthorityError as error:
        message = str(error).split("; retry with", 1)[0]
        raise ReleaseError(
            f"{message}; retry with `make release TARGET={compatible}`"
        ) from error
    dirty = _git(root, "status", "--porcelain", "--untracked-files=all")
    if dirty:
        raise ReleaseError(f"release requires a clean source tree:\n{dirty}")
    manifest.capture_build_tools(
        target,
        root / ".release-preflight-no-cmake-cache",
        _tool_invoker(root, target),
    )
    return data, target


def release(root: Path, target_id: str | None) -> dict[str, Path]:
    data, target = _preflight(root, target_id)
    version = _version(root, data)
    names = set_validator.quartet_names(target, version)
    source = _source(root)

    def builder(owned: Path, checkpoint: Any) -> dict[str, Path]:
        stage = owned / "stage"
        extracted = owned / "extracted"
        stage.mkdir()
        extracted.mkdir()
        ca = owned / "ca-bundle.pem"
        _acquire_ca(data.release, ca)
        checkpoint("after-dependency-acquisition")
        build_dir = root / "build/release"
        _build(root, target, build_dir)
        checkpoint("after-build")
        _stage(root, build_dir, stage, target, ca)
        dependencies_json = owned / "dependencies.json"
        notices = stage / "share/THIRD_PARTY_NOTICES.md"
        notices.parent.mkdir(parents=True, exist_ok=True)
        _run(
            [
                sys.executable,
                "sol/release/generate-dependencies.py",
                "--root",
                str(root),
                "--json",
                str(dependencies_json),
                "--notices",
                str(notices),
            ],
            cwd=root,
        )
        _validate_layout(stage, target)
        _gate_binaries(stage, data, target)
        checkpoint("after-static-stage-gate")
        quartet = {
            key: owned / name
            for key, name in names.items()
        }
        archive.construct(
            stage,
            quartet["archive"],
            target,
            data.release,
            source["source_date_epoch"],
        )
        archive.write_sidecar(quartet["archive-sha256"], quartet["archive"])
        checkpoint("after-archive-creation")
        tar_command = target["required_tools"][4]
        _run(
            [tar_command, "-C", str(extracted), "-xJf", str(quartet["archive"])],
            cwd=root,
        )
        _validate_layout(extracted, target)
        _gate_binaries(extracted, data, target)
        checkpoint("after-static-extracted-gate")
        dependencies = json.loads(dependencies_json.read_text(encoding="utf-8"))
        tools = manifest.capture_build_tools(
            target, build_dir, _tool_invoker(root, target)
        )
        value = manifest.build(
            release=data.release,
            target=target,
            version=version,
            source=source,
            artifact_path=quartet["archive"],
            dependencies=dependencies,
            build_tools=tools,
        )
        manifest.write(quartet["manifest"], value)
        checkpoint("after-manifest-creation")
        _runtime_gates(root, owned, extracted, quartet, target, checkpoint)
        return quartet

    return transaction.run(
        dist=root / "dist",
        target_id=target["id"],
        version=version,
        destination_names=names,
        builder=builder,
    )
