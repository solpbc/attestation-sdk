"""Validation of a complete, internally consistent three-target release set."""

from __future__ import annotations

import json
import re
import tarfile
import tempfile
from pathlib import Path
from typing import Any

from . import archive, authority, gate, manifest


class SetValidationError(ValueError):
    pass


def release_version(root: Path, data: authority.Authority) -> str:
    cmake = root / "nv-attestation-sdk-cpp" / "CMakeLists.txt"
    match = re.search(
        r"^project\(nv-attestation VERSION ([0-9.]+)\)$",
        cmake.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    if not match:
        raise SetValidationError("cannot derive upstream version")
    return f"{match.group(1)}-sol.{data.release['sol_revision']}"


def quartet_names(target: dict[str, Any], version: str) -> dict[str, str]:
    archive_name = target["archive_name"].format(
        target=target["id"], version=version
    )
    manifest_name = archive_name.removesuffix(".tar.xz") + ".manifest.json"
    return {
        "archive": archive_name,
        "archive-sha256": f"{archive_name}.sha256",
        "manifest": manifest_name,
        "manifest-sha256": f"{manifest_name}.sha256",
    }


def _sidecar(path: Path, payload: Path, target_id: str, label: str) -> None:
    expected = f"{archive.sha256(payload)}  {payload.name}\n"
    actual = path.read_text(encoding="utf-8")
    if actual != expected:
        raise SetValidationError(
            f"quartet hash mismatch: {target_id}: {label}: "
            f"expected {expected.strip()}, got {actual.strip()}"
        )


def _json_value(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _field(value: dict[str, Any], dotted: str) -> Any:
    current: Any = value
    for component in dotted.split("."):
        current = current[component]
    return current


def _validate_one(
    dist: Path,
    data: authority.Authority,
    target: dict[str, Any],
    version: str,
    manifest_path: Path,
) -> dict[str, Any]:
    target_id = target["id"]
    names = quartet_names(target, version)
    paths = {key: dist / name for key, name in names.items()}
    missing = [
        path.name
        for path in paths.values()
        if not path.is_file() or path.is_symlink()
    ]
    if missing:
        raise SetValidationError(
            f"incomplete quartet: {target_id}: missing {', '.join(missing)}"
        )
    try:
        value = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SetValidationError(f"invalid manifest: {manifest_path}: {error}") from error
    try:
        manifest.validate_build_tools(target, value["build_tools"])
    except (KeyError, manifest.ManifestError) as error:
        raise SetValidationError(
            f"quartet layout mismatch: {target_id}: build_tools: {error}"
        ) from error
    expected_identity = {
        "schema_version": 2,
        "release.version": version,
        "target.id": target_id,
        "target.binary_format": target["binary_format"],
        "target.architecture": target["expected_arch"],
    }
    for field, expected in expected_identity.items():
        actual = value["schema_version"] if field == "schema_version" else _field(value, field)
        if actual != expected:
            raise SetValidationError(
                f"quartet layout mismatch: {target_id}: {field}: "
                f"expected {_json_value(expected)}, got {_json_value(actual)}"
            )
    artifact = value["artifact"]
    archive_path = paths["archive"]
    if artifact["name"] != archive_path.name:
        raise SetValidationError(
            f"quartet layout mismatch: {target_id}: artifact.name: "
            f"expected {_json_value(archive_path.name)}, got {_json_value(artifact['name'])}"
        )
    actual_hash = archive.sha256(archive_path)
    if artifact["sha256"] != actual_hash:
        raise SetValidationError(
            f"quartet hash mismatch: {target_id}: archive: "
            f"expected {artifact['sha256']}, got {actual_hash}"
        )
    if artifact["size"] != archive_path.stat().st_size:
        raise SetValidationError(
            f"quartet layout mismatch: {target_id}: artifact.size: "
            f"expected {artifact['size']}, got {archive_path.stat().st_size}"
        )
    _sidecar(paths["archive-sha256"], archive_path, target_id, "archive sidecar")
    _sidecar(paths["manifest-sha256"], manifest_path, target_id, "manifest sidecar")
    expected_members = [
        {
            "path": item["path"],
            "kind": item["kind"],
            "link_target": item.get("link_target"),
        }
        for item in target["members"]
    ]
    if value["archive_members"] != expected_members:
        raise SetValidationError(
            f"quartet layout mismatch: {target_id}: archive_members: "
            f"expected {_json_value(expected_members)}, "
            f"got {_json_value(value['archive_members'])}"
        )
    try:
        with tarfile.open(archive_path, "r:xz") as tar:
            members = tar.getmembers()
    except (OSError, tarfile.TarError) as error:
        raise SetValidationError(
            f"invalid archive: {target_id}: {archive_path}: {error}; "
            f"rebuild with `make release TARGET={target_id}` on its native host"
        ) from error
    actual_members = [
        {
            "path": item.name,
            "kind": "symlink" if item.issym() else "regular",
            "link_target": item.linkname if item.issym() else None,
        }
        for item in members
    ]
    if actual_members != expected_members:
        raise SetValidationError(
            f"quartet layout mismatch: {target_id}: archive_members: "
            f"expected {_json_value(expected_members)}, got {_json_value(actual_members)}"
        )
    allowlist = authority.read_allowlist(data, target)
    try:
        with tempfile.TemporaryDirectory() as directory:
            extracted = Path(directory)
            with tarfile.open(archive_path, "r:xz") as tar:
                tar.extractall(extracted, filter="data")
            for member in target["members"]:
                if gate.is_binary_member(member):
                    gate.gate_file(extracted / member["path"], target, allowlist)
    except (OSError, tarfile.TarError, gate.GateError) as error:
        raise SetValidationError(
            f"static archive gate failed: {target_id}: {error}"
        ) from error
    return value


def validate(
    dist: Path,
    data: authority.Authority,
    version: str,
    *,
    expected_source_commit: str,
) -> dict[str, dict[str, Any]]:
    if not re.fullmatch(r"[0-9a-f]{40}", expected_source_commit):
        raise SetValidationError(
            f"invalid expected source commit: {expected_source_commit!r}; resolve one "
            "with `git rev-parse HEAD` and retry with `--source-commit <commit>`"
        )
    if not dist.is_dir():
        raise SetValidationError(f"release set directory does not exist: {dist}")
    expected_names = {
        target_id: quartet_names(target, version)["manifest"]
        for target_id, target in data.targets.items()
    }
    allowed_release_files = {
        name
        for target in data.targets.values()
        for name in quartet_names(target, version).values()
    }
    for path in sorted(dist.iterdir()):
        if (
            (path.is_file() or path.is_symlink())
            and path.name.startswith("libnvat-")
            and version in path.name
            and path.name not in allowed_release_files
        ):
            raise SetValidationError(f"extra release file: {path}")
    candidates = sorted(dist.glob("*.manifest.json"))
    by_target: dict[str, list[Path]] = {}
    for path in candidates:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            target_id = value["target"]["id"]
        except (OSError, json.JSONDecodeError, KeyError, TypeError) as error:
            raise SetValidationError(f"invalid manifest: {path}: {error}") from error
        if target_id not in data.targets:
            raise SetValidationError(f"unknown target: {target_id}: {path}")
        by_target.setdefault(target_id, []).append(path)
    missing_targets = [
        target_id
        for target_id in authority.TARGET_IDS
        if not by_target.get(target_id)
    ]
    if missing_targets:
        recovery = "; ".join(
            f"on its native host run `make release TARGET={target_id}`"
            for target_id in missing_targets
        )
        raise SetValidationError(
            "; ".join(f"missing target: {target_id}" for target_id in missing_targets)
            + f"; recover by collecting each missing quartet: {recovery}"
        )
    for target_id in authority.TARGET_IDS:
        paths = by_target.get(target_id, [])
        if len(paths) > 1:
            raise SetValidationError(
                f"duplicate target: {target_id}: {', '.join(map(str, paths))}"
            )
        if paths[0].name != expected_names[target_id]:
            raise SetValidationError(f"extra release file: {paths[0]}")

    manifests = {
        target_id: _validate_one(
            dist, data, data.target(target_id), version, by_target[target_id][0]
        )
        for target_id in authority.TARGET_IDS
    }
    compared = (
        "schema_version",
        "release.version",
        "release.sol_revision",
        "source.commit",
        "source.upstream_base_commit",
        "source.sol_series_commits",
        "source.source_date_epoch",
        "dependency_pins",
        "build_inputs.ca_snapshot",
        "build_inputs.archive",
    )
    for field in compared:
        values = {
            target_id: (
                manifest_value["schema_version"]
                if field == "schema_version"
                else _field(manifest_value, field)
            )
            for target_id, manifest_value in manifests.items()
        }
        first = next(iter(values.values()))
        if any(value != first for value in values.values()):
            rendered = ", ".join(
                f"{target_id}={_json_value(value)}"
                for target_id, value in values.items()
            )
            raise SetValidationError(f"cross-target mismatch: {field}: {rendered}")
    source_commit = manifests[authority.TARGET_IDS[0]]["source"]["commit"]
    if source_commit != expected_source_commit:
        raise SetValidationError(
            "source identity mismatch: source.commit: "
            f"expected {_json_value(expected_source_commit)}, "
            f"all targets={_json_value(source_commit)}; check out "
            f"`git switch --detach {source_commit}` to validate that source, or rerun "
            f"with `--source-commit {source_commit}` for an out-of-checkout collection"
        )
    revision = manifests[authority.TARGET_IDS[0]]["release"]["sol_revision"]
    if revision != data.release["sol_revision"]:
        raise SetValidationError(
            f"quartet layout mismatch: all targets: release.sol_revision: "
            f"expected {_json_value(data.release['sol_revision'])}, "
            f"got {_json_value(revision)}"
        )
    return manifests
