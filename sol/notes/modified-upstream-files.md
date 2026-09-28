# Modified upstream files in sol pbc nvattest releases

sol pbc maintains a modified fork of NVIDIA’s Attestation SDK. This record identifies the upstream files changed in each published `sol` revision. The source and upstream base commits below are the coordinates used by the release manifests.

| Revision | Source commit | Upstream comparison base | File list |
|---|---|---|---|
| `sol.1` | `e2dadc9d95bd0ed61fcc263ff753af8cb46625ea` | `73c032ebff680ca6d2ba06f4006b511491b71ce9` | [List A](#list-a) |
| `sol.2` | `1c95b1f5ae72b5f4282f7b6b96722f7c8d69f744` | `73c032ebff680ca6d2ba06f4006b511491b71ce9` | [List A](#list-a) |
| `sol.3` | `6a3079abd039b27a799ea4f01df827bf5ef4a2b4` | `73efa3ac1bec28ed7d7f0c0811a6c993e722dbd4` | [List B](#list-b) |
| `sol.4` | `a5a2967ee0c657569a058ba56ad288543775fe94` | `73efa3ac1bec28ed7d7f0c0811a6c993e722dbd4` | [List B](#list-b) |

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

The lists cover files present at each source commit and its upstream base, with differing contents. Files added by sol pbc are outside this comparison. NVIDIA’s existing copyright and licence notices remain in the source.
