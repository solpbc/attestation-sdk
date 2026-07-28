#!/usr/bin/env python3
"""Command facade for release-rail authority and gates."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from release_rail import authority
from release_rail import apple
from release_rail import archive
from release_rail import driver
from release_rail import gate
from release_rail import manifest
from release_rail import runtime
from release_rail import set_validator
from release_rail import transaction


def _authority_command(arguments: argparse.Namespace) -> int:
    data = authority.load()
    if arguments.action == "host-target":
        print(data.compatible_target())
        return 0
    if arguments.action == "build-image":
        target_id = arguments.target or data.compatible_target()
        target = data.require_compatible(
            target_id, recovery_variable="HOST_TARGET"
        )
        if target["build_image"] == "none":
            raise authority.AuthorityError(f"target {target_id} has no build image")
        print(target["build_image"])
        return 0
    if arguments.action == "get":
        target = data.target(arguments.target)
        value = target[arguments.field]
        print(value if isinstance(value, str) else json.dumps(value, separators=(",", ":")))
        return 0
    raise AssertionError(arguments.action)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    authority_parser = commands.add_parser("authority")
    actions = authority_parser.add_subparsers(dest="action", required=True)
    actions.add_parser("host-target")
    build_image = actions.add_parser("build-image")
    build_image.add_argument("target", nargs="?")
    get = actions.add_parser("get")
    get.add_argument("target", choices=authority.TARGET_IDS)
    get.add_argument("field")
    runtime_parser = commands.add_parser("runtime")
    runtime_actions = runtime_parser.add_subparsers(dest="action", required=True)
    runtime_actions.add_parser("select")
    runtime_actions.add_parser("image-tag")
    run_args = runtime_actions.add_parser("run-args")
    run_args.add_argument("runtime_name")
    gate_parser = commands.add_parser("gate")
    gate_parser.add_argument("target", choices=authority.TARGET_IDS)
    gate_parser.add_argument("files", nargs="+", type=Path)
    release_parser = commands.add_parser("release")
    release_parser.add_argument("target", nargs="?")
    validate = commands.add_parser("validate-set")
    validate.add_argument("--dist", type=Path, default=Path("dist"))
    validate.add_argument("--version")
    validate.add_argument("--source-commit")
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    try:
        if arguments.command == "authority":
            return _authority_command(arguments)
        if arguments.command == "runtime":
            if arguments.action == "select":
                print(runtime.select().name)
            elif arguments.action == "image-tag":
                print(runtime.LOCAL_IMAGE_TAG)
            elif arguments.action == "run-args":
                for value in runtime.run_args(arguments.runtime_name):
                    print(value)
            else:
                raise AssertionError(arguments.action)
            return 0
        if arguments.command == "gate":
            data = authority.load()
            target = data.target(arguments.target)
            allowlist = authority.read_allowlist(data, target)
            for path in arguments.files:
                gate.gate_file(path, target, allowlist)
            return 0
        if arguments.command == "release":
            root = Path(
                subprocess.check_output(
                    ["git", "rev-parse", "--show-toplevel"], text=True
                ).strip()
            )
            destinations = driver.release(root, arguments.target or None)
            for destination in destinations.values():
                print(destination)
            return 0
        if arguments.command == "validate-set":
            data = authority.load()
            root = Path(
                subprocess.check_output(
                    ["git", "rev-parse", "--show-toplevel"], text=True
                ).strip()
            )
            version = arguments.version or set_validator.release_version(root, data)
            expected_source_commit = arguments.source_commit or subprocess.check_output(
                ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
            ).strip()
            set_validator.validate(
                arguments.dist,
                data,
                version,
                expected_source_commit=expected_source_commit,
            )
            print(f"complete release set validated: {version}")
            return 0
    except (
        authority.AuthorityError,
        apple.AppleToolchainError,
        archive.ArchiveError,
        driver.ReleaseError,
        driver.SourceError,
        gate.GateError,
        manifest.ManifestError,
        runtime.RuntimeSelectionError,
        set_validator.SetValidationError,
        transaction.TransactionError,
        KeyError,
        ValueError,
    ) as error:
        print(f"release rail error: {error}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
