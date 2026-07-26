"""Owned staging and rollback-safe quartet promotion."""

from __future__ import annotations

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
    for destination in destinations.values():
        if destination.exists() or destination.is_symlink():
            retained = destination.with_name(f"{destination.name}.retained")
            command = shlex.join(["mv", str(destination), str(retained)])
            raise TransactionError(
                f"promotion refuses to overwrite: {destination}; "
                f"move it aside with `{command}`, then retry"
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
            source.replace(destination)
            moved.append(destination)
            checkpoint(f"after-promotion:{key}")
    except BaseException:
        for destination in reversed(moved):
            if destination in destinations.values():
                destination.unlink(missing_ok=True)
        raise
    return destinations
