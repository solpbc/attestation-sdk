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
    hash_output=$(sha256sum "$1")
  else
    hash_output=$(shasum -a 256 "$1")
  fi
  printf '%s\n' "${hash_output%% *}"
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
  actual=0
  for entry in "$checked"/* "$checked"/.[!.]* "$checked"/..?*; do
    if [ -e "$entry" ] || [ -L "$entry" ]; then
      actual=$((actual + 1))
    fi
  done
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
printf '%s\n' "$output"
printf '%s\n' "$output" | grep -F "/nonexistent/path" >/dev/null
printf '%s\n' "$output" | grep -F "from --ca-bundle" >/dev/null

archive_hash=$(hash_file "$archive")
read -r archive_sidecar_hash _ < "$archive_sidecar"
manifest_artifact_hash=$(sed -n \
  '/"artifact": {/,/}/ s/.*"sha256": "\([^"]*\)".*/\1/p' "$manifest")
test -n "$manifest_artifact_hash"
test "$archive_hash" = "$archive_sidecar_hash"
test "$archive_hash" = "$manifest_artifact_hash"

manifest_hash=$(hash_file "$manifest")
read -r manifest_sidecar_hash _ < "$manifest_sidecar"
test "$manifest_hash" = "$manifest_sidecar_hash"

echo "runtime, layout, and quartet hash gates passed"
