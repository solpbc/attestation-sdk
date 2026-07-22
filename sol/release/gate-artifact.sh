#!/usr/bin/env bash
set -euo pipefail

root=${1:?extracted artifact root is required}
allow_file=${2:?DT_NEEDED allowlist is required}

binaries=(
  "$root/bin/nvattest"
  "$root/lib/libnvat.so"
  "$root/lib/libnvat.so.1"
  "$root/lib/libnvat.so.1.2.2"
)
for binary in "${binaries[@]}"; do
  readelf -h "$binary" >/dev/null
  if ! dynamic_info=$(readelf -d "$binary"); then
    echo "failed to read dynamic section from ${binary#$root/}" >&2
    exit 1
  fi
  needed=$(sed -n 's/.*Shared library: \[\([^]]*\)\].*/\1/p' <<< "$dynamic_info")
  if [[ -z "$needed" ]]; then
    echo "no DT_NEEDED entries found in ${binary#$root/}" >&2
    exit 1
  fi
  while read -r soname; do
    if ! grep -Fxq "$soname" "$allow_file"; then
      echo "forbidden DT_NEEDED entry in ${binary#$root/}: $soname" >&2
      exit 1
    fi
  done <<< "$needed"

  if ! version_info=$(readelf --version-info "$binary"); then
    echo "failed to read symbol versions from ${binary#$root/}" >&2
    exit 1
  fi
  set +e
  versions=$(grep -oE 'GLIBC_[0-9.]+|GLIBCXX_[0-9.]+|CXXABI_[0-9.]+' <<< "$version_info")
  grep_status=$?
  set -e
  if ((grep_status > 1)); then
    echo "failed to parse symbol versions from ${binary#$root/}" >&2
    exit 1
  fi
  if [[ -n "$versions" ]]; then
    versions=$(sort -u <<< "$versions")
  fi
  while read -r version; do
    [[ -z "$version" ]] && continue
    case "$version" in
      GLIBC_*) limit=GLIBC_2.28 ;;
      GLIBCXX_*) limit=GLIBCXX_3.4.25 ;;
      CXXABI_*) limit=CXXABI_1.3.11 ;;
    esac
    if [[ $(printf '%s\n%s\n' "$version" "$limit" | sort -V | tail -1) != "$limit" ]]; then
      echo "ABI requirement above manylinux_2_28 floor in ${binary#$root/}: $version" >&2
      exit 1
    fi
  done <<< "$versions"

  if ! binary_strings=$(strings "$binary"); then
    echo "failed to extract strings from ${binary#$root/}" >&2
    exit 1
  fi
  if grep -F -e '/etc/ssl/certs/ca-certificates.crt' -e '/etc/pki/tls/certs/ca-bundle.crt' <<< "$binary_strings"; then
    echo "compiled host CA path found in ${binary#$root/}" >&2
    exit 1
  fi
done

echo "ELF dependency, ABI, and compiled CA path gates passed"
