#!/usr/bin/env python3
import argparse
import json
import pathlib
import subprocess


def git(root, *arguments):
    return subprocess.check_output(["git", "-C", str(root), *arguments], text=True).strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=pathlib.Path, required=True)
    parser.add_argument("--dependencies", type=pathlib.Path, required=True)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--artifact-sha256", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--ci-image", required=True)
    parser.add_argument("--ca-date", required=True)
    parser.add_argument("--ca-url", required=True)
    parser.add_argument("--ca-sha256", required=True)
    parser.add_argument("--source-date-epoch", type=int, required=True)
    parser.add_argument("--member", action="append", default=[])
    args = parser.parse_args()

    base = git(args.root, "merge-base", "main", "HEAD")
    log = git(args.root, "log", "--reverse", "--format=%H%x09%s", f"{base}..HEAD")
    commits = []
    if log:
        for line in log.splitlines():
            commit, subject = line.split("\t", 1)
            commits.append({"commit": commit, "subject": subject})

    manifest = {
        "schema_version": 1,
        "artifact": {
            "name": args.artifact,
            "sha256": args.artifact_sha256,
            "version": args.version,
        },
        "target": "linux-x86_64",
        "upstream_base_commit": base,
        "sol_series_commits": commits,
        "dependency_pins": json.loads(args.dependencies.read_text()),
        "ci_image": args.ci_image,
        "ca_snapshot": {
            "date": args.ca_date,
            "url": args.ca_url,
            "sha256": args.ca_sha256,
        },
        "source_date_epoch": args.source_date_epoch,
        "archive_members": args.member,
    }
    args.output.write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    main()
