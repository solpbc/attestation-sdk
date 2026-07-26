"""Deterministic archive and checksum-sidecar construction."""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path
from typing import Any


class ArchiveError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_sidecar(path: Path, payload: Path) -> None:
    path.write_text(f"{sha256(payload)}  {payload.name}\n", encoding="utf-8")


def construct(
    stage: Path,
    output: Path,
    target: dict[str, Any],
    release: dict[str, Any],
    source_date_epoch: int,
) -> None:
    tar_command = target["required_tools"][4]
    xz_command = target["required_tools"][5]
    members = [member["path"] for member in target["members"]]
    tar_arguments = [
        tar_command,
        "--format=gnu",
        "--sort=name",
        f"--mtime=@{source_date_epoch}",
        "--owner=0",
        "--group=0",
        "--numeric-owner",
        "-C",
        str(stage),
        "-cf",
        "-",
        *members,
    ]
    xz_arguments = [
        xz_command,
        f"-{release['archive_xz_preset']}",
        f"-T{release['archive_xz_threads']}",
        "-c",
    ]
    environment = os.environ.copy()
    environment.pop("XZ_OPT", None)
    environment.pop("XZ_DEFAULTS", None)
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with output.open("wb") as destination:
            tar_process = subprocess.Popen(
                tar_arguments,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=environment,
            )
            assert tar_process.stdout is not None
            xz_process = subprocess.Popen(
                xz_arguments,
                stdin=tar_process.stdout,
                stdout=destination,
                stderr=subprocess.PIPE,
                env=environment,
            )
            tar_process.stdout.close()
            _, xz_error = xz_process.communicate()
            _, tar_error = tar_process.communicate()
        if tar_process.returncode:
            raise ArchiveError(
                f"GNU tar failed with exit {tar_process.returncode}: "
                f"{tar_error.decode(errors='replace').strip()}"
            )
        if xz_process.returncode:
            raise ArchiveError(
                f"xz failed with exit {xz_process.returncode}: "
                f"{xz_error.decode(errors='replace').strip()}"
            )
    except OSError as error:
        raise ArchiveError(f"archive construction failed: {error}") from error
    except BaseException:
        output.unlink(missing_ok=True)
        raise
