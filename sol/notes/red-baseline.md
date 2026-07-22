# Portable nvattest red baseline

Captured from the unpatched tree with the vendored configuration used by
`make ci`:

```text
$ readelf -d build/libnvat.so.1.2.2 | grep NEEDED
 0x0000000000000001 (NEEDED)             Shared library: [libxml2.so.2]
 0x0000000000000001 (NEEDED)             Shared library: [libz.so.1]
 0x0000000000000001 (NEEDED)             Shared library: [libgcc_s.so.1]
 0x0000000000000001 (NEEDED)             Shared library: [libutil.so.1]
 0x0000000000000001 (NEEDED)             Shared library: [librt.so.1]
 0x0000000000000001 (NEEDED)             Shared library: [libpthread.so.0]
 0x0000000000000001 (NEEDED)             Shared library: [libdl.so.2]
 0x0000000000000001 (NEEDED)             Shared library: [libstdc++.so.6]
 0x0000000000000001 (NEEDED)             Shared library: [libm.so.6]
 0x0000000000000001 (NEEDED)             Shared library: [libc.so.6]
 0x0000000000000001 (NEEDED)             Shared library: [ld-linux-x86-64.so.2]

$ strings build/libnvat.so.1.2.2 | grep -E '/etc/pki|/etc/ssl'
/etc/pki/tls/certs/ca-bundle.crt
```

These facts falsify the desired self-contained-libxml2 and no-baked-CA-path
properties before their fixes exist. The third red fact will require an enabled,
offline unit test that supplies a missing CA path to the shared resolution
function and asserts the actionable error; that test belongs to implementation,
not this prep stage.

## Mutation proof: missing explicit path must not fall through

This is not a baseline result from the unpatched tree: the resolver and its test
do not exist there, so the test would not compile. Instead, after implementing
the resolver and obtaining a green test suite, the explicit-path error branch
was temporarily changed to continue down the ladder. The focused test then
failed as follows (the mutation was immediately reverted):

```text
$ NVAT_C_SDK_TEST_SERVICE_KEY=sol-unit-dummy ctest --test-dir build -R CaBundleResolutionTest.MissingAuthoritativePathsFailWithPathAndTier --output-on-failure
TEST_MODE: unit
[----------] 1 test from CaBundleResolutionTest
[ RUN      ] CaBundleResolutionTest.MissingAuthoritativePathsFailWithPathAndTier
2026-07-22 02:14:06.262 [nvat] [/src/nv-attestation-sdk-cpp/src/nv_http.cpp:80 use_authoritative_ca_bundle_path] [error] CA bundle path '/missing-explicit-ca' from --ca-bundle does not exist or is not readable; provide a readable file with --ca-bundle or NVAT_CA_BUNDLE.
/src/nv-attestation-sdk-cpp/unit-tests/ca_bundle_test.cpp:186: Failure
Expected equality of these values:
  resolve_ca_bundle_path(explicit_path, path, tier)
    Which is: Error code 0: Ok
  Error::InternalError
    Which is: Error code 2: Internal Error

/src/nv-attestation-sdk-cpp/unit-tests/ca_bundle_test.cpp:187: Failure
Expected equality of these values:
  path
    Which is: "/etc/pki/tls/certs/ca-bundle.crt"
  test_case.second
    Which is: "/missing-explicit-ca"

/src/nv-attestation-sdk-cpp/unit-tests/ca_bundle_test.cpp:188: Failure
Expected equality of these values:
  tier
    Which is: "system CA bundle probe"
  test_case.first
    Which is: "--ca-bundle"

[  FAILED  ] CaBundleResolutionTest.MissingAuthoritativePathsFailWithPathAndTier (0 ms)
[==========] 1 test from 1 test suite ran. (4 ms total)
[  PASSED  ] 0 tests.
[  FAILED  ] 1 test, listed below:
[  FAILED  ] CaBundleResolutionTest.MissingAuthoritativePathsFailWithPathAndTier

 1 FAILED TEST

0% tests passed, 1 tests failed out of 1
The following tests FAILED:
    118 - CaBundleResolutionTest.MissingAuthoritativePathsFailWithPathAndTier (Failed) unit
Errors while running CTest
```

The mutation command exited 8. This proves the test rejects the precise defect:
an invalid explicit path silently falling through to a system probe.
