# Modified upstream files in sol pbc nvattest releases

sol pbc maintains a modified fork of NVIDIA’s Attestation SDK. This record identifies the upstream files changed in each published `sol` revision. The source and upstream base commits below are the coordinates used by the release manifests.

| Revision | Source commit | Upstream comparison base | File list |
|---|---|---|---|
| `sol.1` | `e2dadc9d95bd0ed61fcc263ff753af8cb46625ea` | `73c032ebff680ca6d2ba06f4006b511491b71ce9` | [List A](#list-a) |
| `sol.2` | `1c95b1f5ae72b5f4282f7b6b96722f7c8d69f744` | `73c032ebff680ca6d2ba06f4006b511491b71ce9` | [List A](#list-a) |
| `sol.3` | `6a3079abd039b27a799ea4f01df827bf5ef4a2b4` | `73efa3ac1bec28ed7d7f0c0811a6c993e722dbd4` | [List B](#list-b) |
| `sol.4` | `a5a2967ee0c657569a058ba56ad288543775fe94` | `73efa3ac1bec28ed7d7f0c0811a6c993e722dbd4` | [List B](#list-b) |
| `sol.5` | `873252c6f4f4e54d04b7db14922e8e46102467d3` | `73efa3ac1bec28ed7d7f0c0811a6c993e722dbd4` | [List C](#list-c) |
| `sol.6` | `fdc3c39958f12ba1055ae5beebc182577f7430b3` | `73efa3ac1bec28ed7d7f0c0811a6c993e722dbd4` | [List D](#list-d) |
| `sol.7` | `69a71c859ec02b6e5f10616b8b8a873c230941c9` | `73efa3ac1bec28ed7d7f0c0811a6c993e722dbd4` | [List D](#list-d) |

## List A: sol.1 and sol.2

These upstream files differ from the comparison base:

- `nv-attestation-cli/CMakeLists.txt`
- `nv-attestation-cli/src/attest.cpp`
- `nv-attestation-cli/src/nvattest_options.h`
- `nv-attestation-cli/src/nvattest_types.h`
- `nv-attestation-cli/src/utils.cpp`
- `nv-attestation-cli/src/utils.h`
- `nv-attestation-cli/tests/CMakeLists.txt`
- `nv-attestation-sdk-cpp/CMakeLists.txt`
- `nv-attestation-sdk-cpp/include/nv_attestation/nv_http.h`
- `nv-attestation-sdk-cpp/include/nvat.h.in`
- `nv-attestation-sdk-cpp/src/nv_http.cpp`
- `nv-attestation-sdk-cpp/src/nvat.cpp`
- `nv-attestation-sdk-cpp/unit-tests/CMakeLists.txt`
- `nv-attestation-sdk-cpp/unit-tests/testdata/x509_cert_chain/generate_test_certs.sh`

## List B: sol.3 and sol.4

These upstream files differ from the comparison base:

- `nv-attestation-cli/CMakeLists.txt`
- `nv-attestation-cli/src/attest.cpp`
- `nv-attestation-cli/src/nvattest_options.h`
- `nv-attestation-cli/src/nvattest_types.h`
- `nv-attestation-cli/src/utils.cpp`
- `nv-attestation-cli/src/utils.h`
- `nv-attestation-cli/tests/CMakeLists.txt`
- `nv-attestation-sdk-cpp/CMakeLists.txt`
- `nv-attestation-sdk-cpp/include/nv_attestation/nv_http.h`
- `nv-attestation-sdk-cpp/include/nvat.h.in`
- `nv-attestation-sdk-cpp/src/nv_http.cpp`
- `nv-attestation-sdk-cpp/src/nvat.cpp`
- `nv-attestation-sdk-cpp/unit-tests/CMakeLists.txt`

## List C: sol.5

These upstream files differ from the comparison base:

- `nv-attestation-cli/CMakeLists.txt`
- `nv-attestation-cli/src/attest.cpp`
- `nv-attestation-cli/src/nvattest_options.h`
- `nv-attestation-cli/src/nvattest_types.h`
- `nv-attestation-cli/src/utils.cpp`
- `nv-attestation-cli/src/utils.h`
- `nv-attestation-cli/tests/CMakeLists.txt`
- `nv-attestation-sdk-cpp/CMakeLists.txt`
- `nv-attestation-sdk-cpp/include/nvat.h.in`
- `nv-attestation-sdk-cpp/include/nv_attestation/claims.h`
- `nv-attestation-sdk-cpp/include/nv_attestation/nv_http.h`
- `nv-attestation-sdk-cpp/include/nv_attestation/nv_ocsp.h`
- `nv-attestation-sdk-cpp/include/nv_attestation/nv_x509.h`
- `nv-attestation-sdk-cpp/src/claims_evaluator.cpp`
- `nv-attestation-sdk-cpp/src/gpu/verify.cpp`
- `nv-attestation-sdk-cpp/src/nvat.cpp`
- `nv-attestation-sdk-cpp/src/nv_http.cpp`
- `nv-attestation-sdk-cpp/src/nv_ocsp.cpp`
- `nv-attestation-sdk-cpp/src/nv_x509.cpp`
- `nv-attestation-sdk-cpp/src/switch/verify.cpp`
- `nv-attestation-sdk-cpp/unit-tests/CMakeLists.txt`
- `nv-attestation-sdk-cpp/unit-tests/nv_x509_test.cpp`

Some sol.5 changes carry `sol:` comments in the code; not every modified file does, so this list is the complete record.

The lists cover files present at each source commit and its upstream base, with differing contents. Files added by sol pbc are outside this comparison. NVIDIA’s existing copyright and licence notices remain in the source.

## List D: sol.6 and sol.7

These upstream files differ from the comparison base:

- `README.md`
- `nv-attestation-cli/CMakeLists.txt`
- `nv-attestation-cli/src/attest.cpp`
- `nv-attestation-cli/src/main.cpp`
- `nv-attestation-cli/src/nvattest_options.h`
- `nv-attestation-cli/src/nvattest_types.h`
- `nv-attestation-cli/src/utils.cpp`
- `nv-attestation-cli/src/utils.h`
- `nv-attestation-cli/tests/CMakeLists.txt`
- `nv-attestation-sdk-cpp/CMakeLists.txt`
- `nv-attestation-sdk-cpp/include/nv_attestation/claims.h`
- `nv-attestation-sdk-cpp/include/nv_attestation/nv_http.h`
- `nv-attestation-sdk-cpp/include/nv_attestation/nv_ocsp.h`
- `nv-attestation-sdk-cpp/include/nv_attestation/nv_x509.h`
- `nv-attestation-sdk-cpp/include/nv_attestation/utils.h`
- `nv-attestation-sdk-cpp/include/nvat.h.in`
- `nv-attestation-sdk-cpp/src/claims_evaluator.cpp`
- `nv-attestation-sdk-cpp/src/gpu/corelib_client.cpp`
- `nv-attestation-sdk-cpp/src/gpu/nvml_client.cpp`
- `nv-attestation-sdk-cpp/src/gpu/verify.cpp`
- `nv-attestation-sdk-cpp/src/init.cpp`
- `nv-attestation-sdk-cpp/src/nv_http.cpp`
- `nv-attestation-sdk-cpp/src/nv_ocsp.cpp`
- `nv-attestation-sdk-cpp/src/nv_x509.cpp`
- `nv-attestation-sdk-cpp/src/nvat.cpp`
- `nv-attestation-sdk-cpp/src/rim.cpp`
- `nv-attestation-sdk-cpp/src/switch/nscq_client.cpp`
- `nv-attestation-sdk-cpp/src/switch/verify.cpp`
- `nv-attestation-sdk-cpp/unit-tests/CMakeLists.txt`
- `nv-attestation-sdk-cpp/unit-tests/nv_x509_test.cpp`

Each carries `Modified by sol pbc.` except `README.md`, whose opening paragraph is itself the fork notice.

The sol.6 Windows verifier (`nvattest.exe`, not a rail target) is built from `ff957aa1012781d18b68973e370a0188b8ef502d`. It differs from the POSIX release source only in `nv-attestation-sdk-cpp/cmake/nvat_windows_deps.cmake`, a sol pbc file outside this comparison, and in documentation, so List D also covers it.

## Since sol.5, on `main`

Every upstream file that differs from the upstream base now carries `Modified by sol pbc.` beside its licence identifier, including the sol.5 files listed above that lacked one and the files the native Windows build changed (`nv-attestation-cli/src/main.cpp`, `include/nv_attestation/utils.h`, `src/init.cpp`, `src/rim.cpp`, and the three collector sources). The next revision's list is taken from its own source commit.

