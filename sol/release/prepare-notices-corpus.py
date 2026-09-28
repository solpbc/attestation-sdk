#!/usr/bin/env python3
"""Snapshot the pinned regorus crate licence files for release notices.

Run after updating regorus-Cargo.lock, with the matching regorus checkout and a
Cargo cache populated by ``cargo fetch --locked``. Missing crate licence files
must be supplied under notices/overrides/<crate>-<version>/ first.
"""

import argparse
import hashlib
import json
import pathlib
import re
import subprocess
import tomllib


TARGETS = (
    "x86_64-unknown-linux-gnu",
    "aarch64-unknown-linux-gnu",
    "aarch64-apple-darwin",
)
FEATURES = "regorus/semver"
HERE = pathlib.Path(__file__).resolve().parent


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def reachable_packages(manifest):
    packages = set()
    for target in TARGETS:
        result = subprocess.run(
            [
                "cargo", "tree", "--locked", "--offline", "--target", target,
                "--edges", "normal,build", "--features", FEATURES,
                "--format", "{p}", "--prefix", "none",
            ],
            cwd=manifest.parent,
            check=True,
            capture_output=True,
            text=True,
        )
        for line in result.stdout.splitlines():
            match = re.match(r"^([^ ]+) v([^ ]+)", line)
            if match:
                packages.add(match.groups())
    return sorted(packages)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--regorus-ffi", type=pathlib.Path, required=True)
    parser.add_argument("--registry-src", type=pathlib.Path, required=True)
    args = parser.parse_args()
    manifest = args.regorus_ffi / "Cargo.toml"
    lock_bytes = (args.regorus_ffi / "Cargo.lock").read_bytes()
    assert lock_bytes == (HERE / "regorus-Cargo.lock").read_bytes(), "regorus lock differs from release pin"
    lock = tomllib.loads(lock_bytes.decode())
    locked = {(p["name"], p["version"]): p for p in lock["package"]}
    corpus = HERE / "notices"
    texts = corpus / "texts"
    texts.mkdir(parents=True, exist_ok=True)
    entries = []
    for name, version in reachable_packages(manifest):
        package = locked[(name, version)]
        if package.get("source", "").startswith("registry+"):
            source = args.registry_src / f"{name}-{version}"
            package_license = tomllib.loads((source / "Cargo.toml").read_text())["package"].get("license", "")
        else:
            source = args.regorus_ffi if name == "regorus-ffi" else args.regorus_ffi.parents[1]
            package_license = "MIT (regorus repository LICENSE)"
        files = sorted(
            path for path in source.iterdir()
            if path.is_file() and path.name.startswith(("LICENSE", "COPYING", "NOTICE", "Copyright"))
        )
        override = corpus / "overrides" / f"{name}-{version}"
        if override.exists():
            files.extend(sorted(path for path in override.iterdir() if path.is_file()))
        if name in {"regorus", "regorus-ffi"}:
            files = [args.regorus_ffi.parents[1] / "LICENSE"]
        assert files, f"no licence files for {name} {version}"
        records = []
        for path in files:
            data = path.read_bytes()
            assert data.strip(), path
            digest = sha256(data)
            destination = texts / f"{digest}.txt"
            if destination.exists():
                assert destination.read_bytes() == data
            else:
                destination.write_bytes(data)
            records.append({"name": path.name, "sha256": digest})
        entries.append({"name": name, "version": version, "license": package_license, "texts": records})
    index = {
        "cargo_lock_sha256": sha256(lock_bytes),
        "targets": list(TARGETS),
        "features": FEATURES,
        "cargo_tree_edges": "normal,build",
        "packages": entries,
    }
    (corpus / "regorus-sources.json").write_text(json.dumps(index, indent=2) + "\n")
    print(f"snapshotted {len(entries)} package versions and {len(list(texts.iterdir()))} distinct licence texts")


if __name__ == "__main__":
    main()
