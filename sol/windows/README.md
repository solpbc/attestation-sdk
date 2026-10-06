# Native Windows verifier

`build.ps1` builds `nvattest.exe` for Windows x64 as a **verification-only** tool. It appraises GPU evidence files with the local verifier, against online NVIDIA OCSP/RIM services or an offline status-proof bundle. It refuses hardware evidence collection, NVML/Corelib/NSCQ evidence sources and the remote verifier with result code 6 (`NVAT_RC_FEATURE_NOT_ENABLED`) before reaching them. The CMake option `NVAT_VERIFICATION_ONLY` is on by default for Windows, and a Windows build refuses to configure without it.

Windows is not yet a release-rail target. `sol/release/targets.toml` lists the published targets, and this build is not one of them.

## Build

On Windows 10 or 11 x64, with Visual Studio 2022 C++ build tools, CMake, Git and the Rust MSVC toolchain:

```powershell
powershell -ExecutionPolicy Bypass -File sol\windows\build.ps1 -Root C:\nvb
```

The script:

1. Fetches every source in `inputs.json` and checks its SHA-256. The OpenSSL, libxml2, xmlsec and curl archives are the same coordinates the POSIX build declares; `sol/release/tests/test_windows_inputs.py` holds them equal. Strawberry Perl is a build-only tool for OpenSSL's `Configure` and is not shipped.
2. Builds static OpenSSL, zlib, libxml2 (without its catalog), xmlsec and curl (no compiled-in CA path) with the dynamic Microsoft C++ runtime (`/MD`).
3. Configures `nv-attestation-cli` with `NVAT_WINDOWS_DEPS_DIR` and builds `nvattest.exe` and the UTC self-test, then runs the self-test.
4. Stages `dist\nvattest\` and writes `build-report.json` (tools, input digests, output digests, imported DLLs).

`-ReuseDependencies` skips step 2 when its output is already present.

## Payload

```
bin\nvattest.exe
bin\msvcp140.dll
bin\vcruntime140.dll
bin\vcruntime140_1.dll
share\ca\ca-bundle.pem
LICENSE
```

The C++ runtime DLLs are copied from the build machine's Visual C++ redistributable directory and load from beside the executable. The Universal C runtime and Windows system DLLs come from the operating system.

## Windows-specific behaviour

- **OpenSSL configuration and modules.** OpenSSL is configured with `-DOSSL_WINCTX=nvat-sol`. Its default configuration, engine and provider-module directories come only from the administrator-owned registry key `HKLM\SOFTWARE\WOW6432Node\OpenSSL-3.6-nvat-sol`, which the build does not create. When that key is absent, those defaults are unset. Callers must clear `OPENSSL_CONF` and `OPENSSL_MODULES` from the child environment to prevent environment-selected configuration or modules.
- **xmlsec's trusted-certificate folder.** With no OpenSSL default certificate directory, xmlsec's default X509 store cannot initialize. At SDK initialization the Windows build therefore points xmlsec at `nvat-no-default-certs` beside the executable. The payload never creates that folder. Its contents do not decide RIM trust: the RIM signature path sets `XMLSEC_KEYINFO_FLAGS_X509DATA_DONT_VERIFY_CERTS`, and RIM certificate chains are checked separately against the pinned NVIDIA root. On Linux and macOS the same lookup names a root-owned path that does not exist.
- **Paths.** Command-line arguments are converted to UTF-8 from the UTF-16 command line. Files are opened through their UTF-16 path, so non-ASCII paths and spaces work under any code page. The CA bundle is read that way and handed to curl as a blob (`CURLOPT_CAINFO_BLOB`).
- **Time.** The MSVC runtime's UTC conversions stop at the year 3000, and NVIDIA's signing certificates expire in 9999. The SDK's `gmtime_r` and `timegm` are therefore proleptic Gregorian arithmetic on Windows (`include/nv_attestation/windows_compat.h`). `tests/utc_test.cpp` checks them against `tests/utc-vectors.json`.
- **Exit status.** The process exit status is the result code modulo 256, as on POSIX (for example 504 → 248). The full code is in the JSON output.
- **No hardware collection.** `dlopen` always fails on Windows, and the command-line tool refuses collection before it.
