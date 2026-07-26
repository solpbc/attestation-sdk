"""Native release orchestration."""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

from . import apple, archive, authority, gate, manifest, runtime, set_validator, transaction


class ReleaseError(RuntimeError):
    pass


class SourceError(RuntimeError):
    pass


def _run(arguments: list[str], *, cwd: Path, **kwargs: Any) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(arguments, cwd=cwd, check=True, **kwargs)
    except (OSError, subprocess.CalledProcessError) as error:
        raise ReleaseError(f"command failed: {' '.join(arguments)}: {error}") from error


def _git(root: Path, *arguments: str) -> str:
    command = ["git", "-C", str(root), *arguments]
    try:
        return subprocess.check_output(
            command, text=True, stderr=subprocess.PIPE
        ).strip()
    except OSError as error:
        reason = str(error)
    except subprocess.CalledProcessError as error:
        reason = (error.stderr or str(error)).strip()
    raise SourceError(f"git command failed: {' '.join(command)}: {reason}")


def _version(root: Path, data: authority.Authority) -> str:
    return set_validator.release_version(root, data)


def _git_result(root: Path, *arguments: str) -> subprocess.CompletedProcess:
    command = ["git", "-C", str(root), *arguments]
    try:
        return subprocess.run(
            command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False
        )
    except OSError as error:
        raise SourceError(
            f"git command failed: {' '.join(command)}: {error}"
        ) from error


def _source(root: Path, release: dict[str, Any]) -> dict[str, Any]:
    try:
        commit = _git(root, "rev-parse", "HEAD^{commit}")
    except SourceError as error:
        raise SourceError(
            "source commit is missing or is not a commit: HEAD; "
            "restore the checkout and retry"
        ) from error

    base = release["upstream_base_commit"]
    if _git_result(root, "cat-file", "-e", f"{base}^{{commit}}").returncode:
        raise SourceError(
            f"pinned upstream base is missing or is not a commit: {base}; "
            "fetch the repository history containing that commit and retry"
        )
    if _git_result(root, "merge-base", "--is-ancestor", base, commit).returncode:
        raise SourceError(
            "pinned upstream base is not an ancestor of source.commit: "
            f"base={base} source={commit}; check out the intended sol release "
            "history and retry"
        )

    revision_range = f"{base}..{commit}"
    log = _git(root, "log", "--reverse", "--format=%H%x09%s", revision_range)
    lines = log.splitlines()
    if not lines:
        raise SourceError(
            "source series is empty: upstream base equals source.commit; "
            "check out the sol release commits and retry"
        )
    series = []
    for line in lines:
        try:
            revision, subject = line.split("\t", 1)
        except ValueError as error:
            raise SourceError(
                f"source series is incomplete: expected valid commit records in "
                f"{revision_range}; fetch the complete repository history and retry"
            ) from error
        series.append({"commit": revision, "subject": subject})

    count_output = _git(root, "rev-list", "--count", revision_range)
    try:
        count = int(count_output)
    except ValueError as error:
        raise SourceError(
            f"source series is incomplete: invalid commit count {count_output!r} for "
            f"{revision_range}; fetch the complete repository history and retry"
        ) from error
    if len(series) != count:
        raise SourceError(
            f"source series is incomplete: expected {count} commits in "
            f"{revision_range}, parsed {len(series)}; fetch the complete repository "
            "history and retry"
        )
    merges = _git(root, "rev-list", "--merges", revision_range)
    if merges:
        merge = merges.splitlines()[0]
        raise SourceError(
            f"source series contains merge commit {merge}; rebase the sol series "
            "to a linear history and retry"
        )
    if series[-1]["commit"] != commit:
        raise SourceError(
            "source series does not end at source.commit: "
            f"expected={commit} got={series[-1]['commit']}; restore the complete "
            "ordered range and retry"
        )
    first = series[0]["commit"]
    try:
        parent = _git(root, "rev-parse", f"{first}^")
    except SourceError:
        parent = "<unavailable>"
    if parent != base:
        raise SourceError(
            "source series does not begin immediately after the pinned upstream "
            f"base: base={base} first={first} parent={parent}; fetch or restore "
            "the complete base-exclusive series and retry"
        )
    return {
        "commit": commit,
        "upstream_base_commit": base,
        "sol_series_commits": series,
        "source_date_epoch": int(
            _git(root, "log", "-1", "--format=%ct", commit)
        ),
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
            f"published={published_hash}; run `sha256sum {destination}` on Linux or "
            f"`shasum -a 256 {destination}` on macOS and compare it with "
            "release.ca_bundle_sha256 in sol/release/targets.toml, then retry"
        )


def _validate_layout(stage: Path, target: dict[str, Any]) -> None:
    for item in target["members"]:
        path = stage / item["path"]
        if item["kind"] == "regular":
            if not path.is_file() or path.is_symlink():
                raise ReleaseError(
                    f"layout mismatch: expected regular file: {path}; rebuild the "
                    "target and retry the release"
                )
        else:
            if not path.is_symlink():
                raise ReleaseError(
                    f"layout mismatch: expected symlink: {path}; rebuild the target "
                    "and retry the release"
                )
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


def _build(
    root: Path,
    target: dict[str, Any],
    build_dir: Path,
    source_date_epoch: int,
    selection: runtime.Selection | None,
) -> None:
    if target["host_os"] == "Linux":
        if selection is None:
            raise ReleaseError("Linux build requires a selected container runtime")
        common = _git(root, "rev-parse", "--path-format=absolute", "--git-common-dir")
        _run(
            [
                selection.name,
                "run",
                "--rm",
                f"--platform={target['container_platform']}",
                "-e",
                f"SOURCE_DATE_EPOCH={source_date_epoch}",
                "-v",
                runtime.render_mount(root, "/src", False),
                "-v",
                runtime.render_mount(common, common, True),
                "-w",
                "/src",
                runtime.LOCAL_IMAGE_TAG,
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
        environment = os.environ.copy()
        environment["SOURCE_DATE_EPOCH"] = str(source_date_epoch)
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
                f"-DCMAKE_OSX_DEPLOYMENT_TARGET={target['abi_floor']['macos']}",
            ],
            cwd=root,
            env=environment,
        )
        _run(
            ["cmake", "--build", str(build_dir), "-j"],
            cwd=root,
            env=environment,
        )


def _tool_invoker(
    root: Path, target: dict[str, Any], selection: runtime.Selection | None
):
    if target["host_os"] != "Linux":
        return None
    if selection is None:
        raise ReleaseError("Linux tool capture requires a selected container runtime")

    def invoke(key: str, command: str) -> str | None:
        if key not in {"compiler", "cmake", "rustc", "cargo"}:
            return None
        result = subprocess.run(
            [
                selection.name,
                "run",
                "--rm",
                f"--platform={target['container_platform']}",
                "-v",
                runtime.render_mount(root, "/src", True),
                "-w",
                "/src",
                runtime.LOCAL_IMAGE_TAG,
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
        if gate.is_binary_member(item):
            gate.gate_file(stage / item["path"], target, allowlist)


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
    selection: runtime.Selection | None,
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
        if selection is None:
            raise ReleaseError("Linux runtime gates require a selected container runtime")
        for label, image in zip(
            ("fedora", "tumbleweed"), target["gate_images"], strict=True
        ):
            _run(
                [
                    selection.name,
                    "run",
                    "--rm",
                    f"--platform={target['container_platform']}",
                    "-v",
                    runtime.render_mount(extracted, "/artifact", True),
                    "-v",
                    runtime.render_mount(owned, "/release", True),
                    "-v",
                    runtime.render_mount(script, "/gate/runtime-gate.sh", True),
                    "-v",
                    runtime.render_mount(layout, "/gate/layout.tsv", True),
                    "-v",
                    runtime.render_mount(counts, "/gate/counts.tsv", True),
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


def _ownership_probe(selection: runtime.Selection, target: dict[str, Any]) -> None:
    with tempfile.TemporaryDirectory() as directory:
        host_directory = Path(directory)
        probe = host_directory / "probe"
        try:
            _run(
                [
                    selection.name,
                    "run",
                    "--rm",
                    f"--platform={target['container_platform']}",
                    "-v",
                    runtime.render_mount(host_directory, "/ownership", False),
                    target["gate_images"][0],
                    "sh",
                    "-c",
                    "umask 077; : > /ownership/probe",
                ],
                cwd=host_directory,
            )
        except ReleaseError as error:
            raise runtime.RuntimeSelectionError(
                f"container ownership probe failed for {selection.name} with "
                f"{target['gate_images'][0]}: {error}"
            ) from error
        expected = os.getuid()
        recovery = (
            "configure rootless Docker or userns-remap, or install Podman, then retry"
        )
        if probe.is_symlink():
            raise runtime.RuntimeSelectionError(
                "container ownership mapping failed: probe path is a symlink; "
                f"{recovery}"
            )
        if not probe.exists():
            raise runtime.RuntimeSelectionError(
                "container ownership mapping failed: probe file is absent; "
                f"{recovery}"
            )
        if not probe.is_file():
            raise runtime.RuntimeSelectionError(
                "container ownership mapping failed: probe path is not a regular file; "
                f"{recovery}"
            )
        actual = probe.stat().st_uid
        if actual != expected:
            raise runtime.RuntimeSelectionError(
                f"container ownership mapping failed: {selection.name} created the "
                f"host probe as uid {actual}, expected invoking uid {expected}; "
                f"{recovery}"
            )


def _preflight(
    root: Path, target_id: str | None
) -> tuple[authority.Authority, dict[str, Any], runtime.Selection | None]:
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
        raise ReleaseError(
            "release requires a clean source tree; inspect with `git status --short`, "
            "then commit the intended changes or run `git stash push --include-untracked` "
            f"before retrying:\n{dirty}"
        )
    selection = runtime.select(target) if target["host_os"] == "Linux" else None
    apple_evidence = (
        apple.preflight(target) if target["host_os"] == "Darwin" else None
    )
    if selection is not None:
        _ownership_probe(selection, target)
    manifest.capture_build_tools(
        target,
        root / ".release-preflight-no-cmake-cache",
        _tool_invoker(root, target, selection),
        runtime_evidence=selection.evidence if selection is not None else None,
        apple_evidence=apple_evidence,
    )
    return data, target, selection


def release(root: Path, target_id: str | None) -> dict[str, Path]:
    data, target, selection = _preflight(root, target_id)
    version = _version(root, data)
    names = set_validator.quartet_names(target, version)
    source = _source(root, data.release)

    def builder(owned: Path, checkpoint: Any) -> dict[str, Path]:
        stage = owned / "stage"
        extracted = owned / "extracted"
        stage.mkdir()
        extracted.mkdir()
        ca = owned / "ca-bundle.pem"
        _acquire_ca(data.release, ca)
        checkpoint("after-dependency-acquisition")
        build_dir = root / "build/release"
        _build(root, target, build_dir, source["source_date_epoch"], selection)
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
            target,
            build_dir,
            _tool_invoker(root, target, selection),
            runtime_evidence=selection.evidence if selection is not None else None,
            apple_evidence=(
                apple.resolve(target, build_dir)
                if target["host_os"] == "Darwin"
                else None
            ),
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
        _runtime_gates(
            root, owned, extracted, quartet, target, checkpoint, selection
        )
        return quartet

    return transaction.run(
        dist=root / "dist",
        target_id=target["id"],
        version=version,
        destination_names=names,
        builder=builder,
    )
