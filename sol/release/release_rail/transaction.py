"""Owned staging and rollback-safe quartet promotion."""

from __future__ import annotations

import os
import shlex
import shutil
from pathlib import Path
from typing import Callable


FaultHook = Callable[[str], None]
QuartetBuilder = Callable[[Path, Callable[[str], None]], dict[str, Path]]
QUARTET_ORDER = ("archive", "archive-sha256", "manifest", "manifest-sha256")
CONSTRUCTION_CHECKPOINTS = (
    "after-dependency-acquisition",
    "after-build",
    "after-static-stage-gate",
    "after-archive-creation",
    "after-static-extracted-gate",
    "after-manifest-creation",
)


class TransactionError(RuntimeError):
    pass


def run(
    *,
    dist: Path,
    target_id: str,
    version: str,
    destination_names: dict[str, str],
    builder: QuartetBuilder,
    fault_hook: FaultHook | None = None,
) -> dict[str, Path]:
    if set(destination_names) != set(QUARTET_ORDER):
        raise TransactionError("destination names do not describe one quartet")
    destinations = {
        key: dist / destination_names[key] for key in QUARTET_ORDER
    }
    existing = [
        path
        for path in destinations.values()
        if path.exists() or path.is_symlink()
    ]
    if existing:
        template = dist / f"retained-{target_id}-{version}.XXXXXX"
        command = (
            f"retained=$(mktemp -d {shlex.quote(str(template))})"
            + " && "
            + shlex.join(["mv", *(str(path) for path in existing)])
            + ' "$retained"/'
        )
        raise TransactionError(
            f"promotion refuses to overwrite: {existing[0]}; "
            f"move the existing quartet aside with `{command}`, then retry"
        )

    def checkpoint(name: str) -> None:
        if fault_hook is not None:
            fault_hook(name)

    checkpoint("before-construction")
    staging_root = dist / ".staging"
    owned = staging_root / f"{target_id}-{version}"
    if owned.parent != staging_root or owned.name in ("", ".", ".."):
        raise TransactionError(f"unsafe owned staging path: {owned}")
    if owned.exists():
        shutil.rmtree(owned)
    owned.mkdir(parents=True)

    sources = builder(owned, checkpoint)
    if set(sources) != set(QUARTET_ORDER):
        raise TransactionError("builder did not produce one complete quartet")
    for key in QUARTET_ORDER:
        if not sources[key].is_file():
            raise TransactionError(f"builder output is missing: {sources[key]}")

    checkpoint("before-promotion")
    moved: list[Path] = []
    try:
        for key in QUARTET_ORDER:
            source = sources[key]
            destination = destinations[key]
            os.link(source, destination)
            moved.append(destination)
            source.unlink()
            checkpoint(f"after-promotion:{key}")
    except BaseException as error:
        for destination in reversed(moved):
            if destination in destinations.values():
                destination.unlink(missing_ok=True)
        if isinstance(error, FileExistsError):
            raise TransactionError(
                f"promotion destination appeared concurrently: {error.filename2}; "
                "move the conflicting file aside and retry"
            ) from error
        if isinstance(error, OSError):
            raise TransactionError(
                f"promotion failed at {destination}: {error}; inspect the destination "
                "filesystem, correct the reported condition, and retry"
            ) from error
        raise
    return destinations
