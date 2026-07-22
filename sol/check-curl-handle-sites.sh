#!/usr/bin/env bash
set -euo pipefail

hits=$(grep -rnE 'curl_easy_init|curl_easy_setopt|curl_global_init|CURLOPT_' \
  --include='*.cpp' --include='*.h' \
  nv-attestation-sdk-cpp nv-attestation-cli nv-attestation-sdk-rust || true)

offending=$(printf '%s\n' "$hits" | awk 'NF && $0 !~ /^nv-attestation-sdk-cpp\/src\/nv_http\.cpp:/')
if [[ -n "$offending" ]]; then
  echo "curl easy-handle sites are only allowed in nv-attestation-sdk-cpp/src/nv_http.cpp:" >&2
  printf '%s\n' "$offending" >&2
  exit 1
fi

printf '%s\n' "$hits"
echo "curl easy-handle site guard passed"
