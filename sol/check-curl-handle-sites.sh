#!/usr/bin/env bash
set -euo pipefail

search_roots=(nv-attestation-sdk-cpp nv-attestation-cli nv-attestation-sdk-rust)
for search_root in "${search_roots[@]}"; do
  if [[ ! -d "$search_root" ]]; then
    echo "curl easy-handle guard search root is missing: $search_root" >&2
    exit 1
  fi
done

set +e
hits=$(grep -rnE 'curl_easy_init|curl_easy_setopt|curl_global_init|CURLOPT_' \
  --include='*.cpp' --include='*.h' \
  "${search_roots[@]}")
grep_status=$?
set -e
if ((grep_status > 1)); then
  echo "curl easy-handle guard grep failed with exit $grep_status" >&2
  exit "$grep_status"
fi

if ! grep -qE '^nv-attestation-sdk-cpp/src/nv_http\.cpp:.*curl_easy_init' <<< "$hits" \
   || ! grep -qE '^nv-attestation-sdk-cpp/src/nv_http\.cpp:.*curl_easy_setopt' <<< "$hits"; then
  echo "curl easy-handle guard did not find the known nv_http.cpp handle sites" >&2
  exit 1
fi

offending=$(printf '%s\n' "$hits" | awk 'NF && $0 !~ /^nv-attestation-sdk-cpp\/src\/nv_http\.cpp:/')
if [[ -n "$offending" ]]; then
  echo "curl easy-handle sites are only allowed in nv-attestation-sdk-cpp/src/nv_http.cpp:" >&2
  printf '%s\n' "$offending" >&2
  exit 1
fi

printf '%s\n' "$hits"
echo "curl easy-handle site guard passed"
