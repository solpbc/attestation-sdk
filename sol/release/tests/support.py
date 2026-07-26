import json
import os
import shutil
from pathlib import Path

from release_rail import archive, elf, fixtures, manifest, runtime, set_validator


SOURCE = {
    "commit": "1" * 40,
    "upstream_base_commit": "2" * 40,
    "sol_series_commits": [{"commit": "3" * 40, "subject": "fixture"}],
    "source_date_epoch": 1_700_000_000,
}
TOOLS = {
    key: {"name": key, "version": "1.2.3"}
    for key in ("compiler", "cmake", "rustc", "cargo", "tar", "xz", "python")
}


def tools_for(target):
    tools = dict(TOOLS)
    if target["host_os"] == "Linux":
        architecture = {
            "EM_X86_64": "amd64",
            "EM_AARCH64": "arm64",
        }[target["expected_arch"]]
        tools[runtime.EVIDENCE_KEY] = {
            "client": {"name": runtime.PODMAN_PRODUCT, "version": "5.8.3"},
            "engine": {
                "name": runtime.PODMAN_PRODUCT,
                "version": "5.8.3",
                "os": "linux",
                "architecture": architecture,
            },
        }
    return tools


def make_stage(stage: Path, target):
    for item in target["members"]:
        path = stage / item["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        if item["kind"] == "symlink":
            path.symlink_to(item["link_target"])
        elif item["path"] == "bin/nvattest":
            if target["binary_format"] == "elf64-le":
                machine = {
                    "EM_X86_64": elf.EM_X86_64,
                    "EM_AARCH64": elf.EM_AARCH64,
                }[target["expected_arch"]]
                path.write_bytes(fixtures.elf_fixture(machine))
            else:
                path.write_bytes(
                    fixtures.macho_fixture(rpaths=(target["macho_rpath"],))
                )
        elif item["path"].startswith("lib/"):
            if target["binary_format"] == "elf64-le":
                machine = {
                    "EM_X86_64": elf.EM_X86_64,
                    "EM_AARCH64": elf.EM_AARCH64,
                }[target["expected_arch"]]
                path.write_bytes(fixtures.elf_fixture(machine))
            else:
                path.write_bytes(
                    fixtures.macho_fixture(
                        dylib_id=target["macho_install_id"], rpaths=()
                    )
                )
        else:
            path.write_bytes(f"fixture:{item['path']}\n".encode())


def host_archive_target(target):
    value = dict(target)
    tools = list(value["required_tools"])
    tools[4] = "tar"
    value["required_tools"] = tools
    return value


def make_quartet(dist: Path, data, target, version: str):
    names = set_validator.quartet_names(target, version)
    paths = {key: dist / name for key, name in names.items()}
    stage = dist / f"stage-{target['id']}"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir()
    make_stage(stage, target)
    archive.construct(
        stage,
        paths["archive"],
        host_archive_target(target),
        data.release,
        SOURCE["source_date_epoch"],
    )
    archive.write_sidecar(paths["archive-sha256"], paths["archive"])
    value = manifest.build(
        release=data.release,
        target=target,
        version=version,
        source=SOURCE,
        artifact_path=paths["archive"],
        dependencies=[],
        build_tools=tools_for(target),
    )
    manifest.write(paths["manifest"], value)
    return paths


def rewrite_manifest(path: Path, mutator):
    value = json.loads(path.read_text(encoding="utf-8"))
    mutator(value)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    archive.write_sidecar(Path(f"{path}.sha256"), path)
