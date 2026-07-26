#!/bin/sh
set -eu

root=${1:?artifact root is required}
archive=${2:?archive is required}
archive_sidecar=${3:?archive sidecar is required}
manifest=${4:?manifest is required}
manifest_sidecar=${5:?manifest sidecar is required}
layout=${6:?layout specification is required}
counts=${7:?count specification is required}
launch_mode=${8:?launch mode is required}

hash_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}

while IFS="$(printf '\t')" read -r kind path link_target; do
  [ -n "$kind" ] || continue
  case "$kind" in
    regular)
      test -f "$root/$path"
      test ! -L "$root/$path"
      ;;
    symlink)
      test -L "$root/$path"
      test "$(readlink "$root/$path")" = "$link_target"
      ;;
    *)
      echo "unknown layout kind: $kind" >&2
      exit 1
      ;;
  esac
done < "$layout"

while IFS="$(printf '\t')" read -r directory expected; do
  [ -n "$directory" ] || continue
  if [ "$directory" = "." ]; then
    checked=$root
  else
    checked=$root/$directory
  fi
  actual=$(find "$checked" -mindepth 1 -maxdepth 1 | wc -l | tr -d ' ')
  test "$actual" = "$expected"
done < "$counts"

case "$launch_mode" in
  linux)
    LD_LIBRARY_PATH="$root/lib" "$root/bin/nvattest" --help >/dev/null
    if output=$(LD_LIBRARY_PATH="$root/lib" "$root/bin/nvattest" attest \
      --device gpu --gpu-evidence-source file --gpu-evidence-file /dev/null \
      --verifier local --rim-store remote \
      --ca-bundle /nonexistent/path 2>&1); then
      echo "missing CA path unexpectedly succeeded" >&2
      exit 1
    fi
    ;;
  macos)
    "$root/bin/nvattest" --help >/dev/null
    if output=$("$root/bin/nvattest" attest \
      --device gpu --gpu-evidence-source file --gpu-evidence-file /dev/null \
      --verifier local --rim-store remote \
      --ca-bundle /nonexistent/path 2>&1); then
      echo "missing CA path unexpectedly succeeded" >&2
      exit 1
    fi
    ;;
  *)
    echo "unknown launch mode: $launch_mode" >&2
    exit 1
    ;;
esac
printf '%s\n' "$output" | grep -F "/nonexistent/path" >/dev/null
printf '%s\n' "$output" | grep -F "from --ca-bundle" >/dev/null

archive_hash=$(hash_file "$archive")
archive_sidecar_hash=$(awk 'NR == 1 {print $1}' "$archive_sidecar")
manifest_artifact_hash=$(sed -n \
  '/"artifact": {/,/}/ s/.*"sha256": "\([^"]*\)".*/\1/p' "$manifest")
test -n "$manifest_artifact_hash"
test "$archive_hash" = "$archive_sidecar_hash"
test "$archive_hash" = "$manifest_artifact_hash"

manifest_hash=$(hash_file "$manifest")
manifest_sidecar_hash=$(awk 'NR == 1 {print $1}' "$manifest_sidecar")
test "$manifest_hash" = "$manifest_sidecar_hash"

echo "runtime, layout, and quartet hash gates passed"
