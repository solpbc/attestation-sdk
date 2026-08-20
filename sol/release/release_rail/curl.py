"""Vendored curl-config CA-configure evidence."""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path


REQUIRED_CONFIGURE_FLAGS = (
    "--with-ca-fallback",
    "--without-ca-bundle",
    "--without-ca-path",
)

# Bound at import so later `patch.object(subprocess, "run")` (used by
# driver tests for `_tool_invoker`) cannot intercept curl-config spawn.
_run = subprocess.run


class CurlConfigError(RuntimeError):
    pass


def _configure_tokens(output: str) -> tuple[str, ...]:
    return tuple(shlex.split(output))


def _output(script: Path, flag: str) -> str:
    try:
        result = _run(
            [str(script), flag],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError as error:
        raise CurlConfigError(
            f"vendored curl configure evidence failed: cannot invoke {script}: "
            f"{error}; remove build/release and rerun the release, then retry"
        ) from error
    if result.returncode:
        stderr = (result.stderr or "").strip()
        detail = f": {stderr}" if stderr else ""
        raise CurlConfigError(
            f"vendored curl configure evidence failed: {script} {flag} failed: "
            f"exit {result.returncode}{detail}; remove build/release and rerun "
            "the release, then retry"
        )
    return result.stdout


def check(build_dir: Path) -> None:
    install = build_dir / "curl-install"
    script = install / "bin" / "curl-config"
    if not install.is_dir():
        raise CurlConfigError(
            f"vendored curl configure evidence failed: {install} is not a "
            "directory; remove build/release and rerun the release so the "
            "vendored curl ExternalProject installs curl-config, then retry"
        )
    if not script.is_file():
        raise CurlConfigError(
            f"vendored curl configure evidence failed: {script} is absent; "
            "remove build/release and rerun the release so the vendored curl "
            "ExternalProject installs curl-config, then retry"
        )
    if not os.access(script, os.X_OK):
        raise CurlConfigError(
            f"vendored curl configure evidence failed: {script} is not "
            "executable; remove build/release and rerun the release so the "
            "installed curl-config is the ExternalProject install output, then "
            "retry"
        )
    ca = _output(script, "--ca").strip()
    if ca:
        raise CurlConfigError(
            f"vendored curl configure evidence failed: {script} --ca reported "
            f"a baked CA path {ca!r}; configure the vendored curl without a "
            "baked host CA path, remove build/release, and retry"
        )
    tokens = _configure_tokens(_output(script, "--configure"))
    for flag in REQUIRED_CONFIGURE_FLAGS:
        if flag not in tokens:
            raise CurlConfigError(
                f"vendored curl configure evidence failed: {script} "
                f"--configure is missing {flag}; configure the vendored curl "
                f"with {flag}, remove build/release, and retry"
            )
