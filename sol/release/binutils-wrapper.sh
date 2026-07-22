#!/usr/bin/env bash
set -euo pipefail

tool_dir=$(cd "$(dirname "$0")" && pwd)
tool_name=$(basename "$0")
exec env LD_LIBRARY_PATH="$tool_dir/lib" "$tool_dir/${tool_name}.real" "$@"
