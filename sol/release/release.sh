#!/usr/bin/env bash
set -euo pipefail

root=$(git rev-parse --show-toplevel)
exec python3 "$root/sol/release/rail.py" release "${1-}"
