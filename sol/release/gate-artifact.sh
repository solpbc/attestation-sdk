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
  while read -r soname; do
    if ! grep -Fxq "$soname" "$allow_file"; then
      echo "forbidden DT_NEEDED entry in ${binary#$root/}: $soname" >&2
      exit 1
    fi
  done < <(readelf -d "$binary" | sed -n 's/.*Shared library: \[\([^]]*\)\].*/\1/p')

  versions=$(readelf --version-info "$binary" | grep -oE 'GLIBC_[0-9.]+|GLIBCXX_[0-9.]+|CXXABI_[0-9.]+' | sort -u || true)
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

  if strings "$binary" | grep -F -e '/etc/ssl/certs/ca-certificates.crt' -e '/etc/pki/tls/certs/ca-bundle.crt'; then
    echo "compiled host CA path found in ${binary#$root/}" >&2
    exit 1
  fi
done

echo "ELF dependency, ABI, and compiled CA path gates passed"
