"""Git-based source inventory."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


class InventoryError(RuntimeError):
    pass


@dataclass(frozen=True)
class CargoLockInventory:
    tracked: tuple[str, ...]
    untracked_non_ignored: tuple[str, ...]
    ignored: tuple[str, ...]


def _git(root: Path, *arguments: str) -> tuple[str, ...]:
    command = ["git", "-C", str(root), *arguments]
    try:
        output = subprocess.check_output(command, text=True, stderr=subprocess.PIPE)
    except OSError as error:
        reason = str(error)
    except subprocess.CalledProcessError as error:
        reason = (error.stderr or str(error)).strip()
    else:
        return tuple(path for path in output.split("\0") if path)
    raise InventoryError(f"git command failed: {' '.join(command)}: {reason}")


def _lock_paths(paths: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted({path for path in paths if Path(path).name == "Cargo.lock"}))


# nv-attestation-sdk-rust/.gitignore:3 has an unanchored Cargo.lock rule, so that
# subtree is structurally invisible to the untracked class. Untracked embedded
# repositories also collapse in `git ls-files -o --exclude-standard`.
def cargo_locks(root: Path) -> CargoLockInventory:
    repository = root.resolve()
    tracked = _lock_paths(_git(repository, "ls-files", "-z"))
    untracked_non_ignored = _lock_paths(
        _git(repository, "ls-files", "-z", "-o", "--exclude-standard")
    )
    ignored_paths = _git(
        repository,
        "ls-files",
        "-z",
        "-o",
        "-i",
        "--exclude-standard",
        "--directory",
    )
    ignored = {
        path
        for path in ignored_paths
        if not path.endswith("/") and Path(path).name == "Cargo.lock"
    }

    def walk_error(error: OSError) -> None:
        raise InventoryError(f"Cargo.lock inventory walk failed: {error}") from error

    for path in ignored_paths:
        if not path.endswith("/"):
            continue
        for directory, directories, files in os.walk(
            repository / path,
            topdown=True,
            onerror=walk_error,
            followlinks=False,
        ):
            directories[:] = [name for name in directories if name != ".git"]
            if "Cargo.lock" in files:
                ignored.add(
                    (Path(directory) / "Cargo.lock")
                    .relative_to(repository)
                    .as_posix()
                )

    return CargoLockInventory(
        tracked=tracked,
        untracked_non_ignored=untracked_non_ignored,
        ignored=tuple(sorted(ignored)),
    )
