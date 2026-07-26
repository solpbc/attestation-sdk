# Portable nvattest design

> **Superseded release-rail scope:** `sol/notes/tri-target-design.md` is the
> current authority for everything under `sol/release/`. Sections 1–2 below
> remain current for CA resolution and vendored dependencies; x86_64-era
> release packaging and gating text is historical.

> Non-authoritative planning record. `sol/release/release.env` is the sole
> authority for the release revision, CA snapshot, and container image pins.

## Decisions and dependency order

### 1. One CA-resolution implementation (D1-D5)

1. Declare `resolve_ca_bundle_path(explicit_path, out_path, out_tier)` in
   `nv-attestation-sdk-cpp/include/nv_attestation/nv_http.h` beside
   `HttpOptions` (`nv_http.h:75-107`), returning the SDK `Error` type. Implement
   it only in `nv-attestation-sdk-cpp/src/nv_http.cpp`; this preserves the
   easy-handle invariant whose sole current construction is `nv_http.cpp:62`.
   The tier is returned as a stable human-readable string so callers do not
   duplicate tier-to-message mapping.
2. Resolve in this exact order: nonempty explicit argument (`--ca-bundle`),
   `NVAT_CA_BUNDLE`, `CURL_CA_BUNDLE`, `SSL_CERT_FILE`, curl's compiled default,
   then the probe list. Read each environment variable through
   `get_env_or_default` (`utils.h:466`), preserving its empty-is-unset behavior.
   Explicit and environment paths are authoritative: if selected but not a
   readable regular file, return an error rather than falling through.
3. Query the compiled default with a temporary easy handle and
   `CURLINFO_CAINFO` under `#if LIBCURL_VERSION_NUM >= 0x075400`. Both null and
   empty mean absent. Validate a nonempty compiled default for readability; if
   it is stale or missing, continue to probes rather than failing, because it
   is build metadata rather than an operator choice. This avoids recreating the
   baked-path failure under a system curl build.
4. Declare this ordered probe list exactly once as a file-scope constant in
   `nv_http.cpp`:
   - `/etc/ssl/certs/ca-certificates.crt` (Debian/Ubuntu; also common on Alpine)
   - `/etc/pki/tls/certs/ca-bundle.crt` (RHEL/Fedora)
   - `/etc/ssl/ca-bundle.pem` (openSUSE)
   - `/etc/ca-certificates/extracted/tls-ca-bundle.pem` (Arch)
   - `/etc/ssl/cert.pem` (Alpine fallback)
   A probe is returned only when it is already a readable regular file. If none
   resolves, return `Error::InternalError` and log an actionable instruction to
   provide `--ca-bundle` or `NVAT_CA_BUNDLE`.
5. Add `ca_bundle_path` and its supplying-tier metadata to `HttpOptions`. Both
   constructors (`nv_http.h:88-100`) call the resolver leniently and retain an
   empty path plus failure state when resolution fails, since constructors
   cannot return `Error`. Add `HttpOptions::set_ca_bundle_path()` following the
   existing `set_*` vocabulary (`nv_http.h:102-106`); it re-runs the same
   resolver with its argument as tier 1 and returns `Error`.
6. Before any transfer, `NvHttpClient::do_request_as_string()`
   (`nv_http.cpp:49-165`) rejects unresolved options with the same actionable
   error. When resolved, it applies `CURLOPT_CAINFO` at the sole handle site.
   This covers all five consumers and, crucially, all four null-option C API
   paths because each begins with `HttpOptions cpp_http_options{}` at
   `nvat.cpp:303,351,1317,1342`.
7. The CLI currently links `nvat::nvat` (`nv-attestation-cli/CMakeLists.txt:98-102`)
   but its include surface is the generated C header: its private include list
   (`CMakeLists.txt:104-110`) does not expose the SDK C++ headers, and CLI
   `utils.h` includes `nvat.h` (`utils.h:20-24`). Keep that boundary instead of
   adding a private-header dependency. Add a minimal C wrapper for the shared
   resolver that accepts an explicit string and returns allocated resolved-path
   and tier strings, plus C wrappers matching the C++ option/context vocabulary:
   `nvat_http_options_set_ca_bundle_path()` and
   `nvat_attestation_ctx_set_default_http_options()`. The latter exposes the
   already-existing C++ context method (`attestation.cpp:154-156`); no global
   state or environment mutation is introduced.
8. Add `ca_bundle_path` to `EvidenceVerificationOptions`
   (`nvattest_options.h:46-55`). Register `--ca-bundle PATH` in
   `add_evidence_verification_options()` beside the existing environment-backed
   URL options (`utils.cpp:122-147`) with `->envname("NVAT_CA_BUNDLE")` and no
   default.
9. Extend the existing collection-options parse-complete callback
   (`utils.cpp:83-109`) into the single eager validation point used by the
   attest subcommand. It calls the C wrapper for the same resolver and throws
   `CLI::ValidationError("--ca-bundle", message)` on failure. Exact message:
   `CA bundle path '<path>' from <tier> does not exist or is not readable; provide a readable file with --ca-bundle or NVAT_CA_BUNDLE.`
   For the gate input this becomes unambiguously:
   `CA bundle path '/nonexistent/path' from --ca-bundle ...`.
   With no selected bad tier, use:
   `No readable CA bundle was found; provide one with --ca-bundle or NVAT_CA_BUNDLE.`
   This callback runs before dispatch (`main.cpp:48-57`) and therefore before
   eager evidence deserialization (`attestation.cpp:208-215`,
   `gpu/evidence.cpp:673-693`).
10. In `attest.cpp`, create one `nvat_http_options_t`, apply the already-resolved
    explicit CLI value through `nvat_http_options_set_ca_bundle_path`, pass it
    instead of null to remote RIM (`attest.cpp:216`) and OCSP (`attest.cpp:242`),
    and install it on the attestation context for lazily created NRAS/JWKS HTTP
    clients. The CLI-owned handle remains alive through `nvat_attest_device` and
    is freed through the existing ownership helper. If the value came from
    `NVAT_CA_BUNDLE`, default construction would already cover it, but using the
    same resolved option for every path also preserves the explicit flag without
    extending the `setenv` shortcut at `attest.cpp:253-257`.
11. Update `nvat.h.in` around the HTTP option declarations (`nvat.h.in:394-405`),
    OCSP/RIM/NRAS `http_options` comments, and the attestation environment list
    (`nvat.h.in:1359-1363`). Mirror the existing `NVAT_OCSP_BASE_URL` prose at
    `nvat.h.in:430`: state that `NVAT_CA_BUNDLE` selects the CA bundle unless an
    explicit option was supplied. Document ownership of resolver output strings.
12. Unit tests are offline and table-driven: explicit precedence; each env tier;
    empty-tier skipping; authoritative missing explicit/environment paths;
    compiled-default/probe continuation through injectable filesystem/curl seams
    kept local to the resolver; and total failure. Add the test source to the
    explicit unit-test list (`unit-tests/CMakeLists.txt:51-75`). No duplicate CLI
    resolution logic is tested or introduced.

### 2. Self-contained vendored dependencies (D6-D7)

1. In the `USE_SYSTEM_DEPS=OFF` branch (`CMakeLists.txt:175-292`), add
   `libxml2_external` pinned to libxml2 2.11.9 at
   `https://download.gnome.org/sources/libxml2/2.11/libxml2-2.11.9.tar.xz`, SHA256
   `780157a1efdb57188ec474dca87acaee67a3a839c2525b2214d318228451809f`.
   Configure with `--disable-shared --enable-static --without-python
   --without-zlib --without-lzma --without-http --without-ftp` and an explicit
   `--libdir=<install>/lib`, plus the existing compiler/PIC settings. The lzma
   exclusion prevents a forbidden `liblzma` dependency.
2. Make `xmlsec_external` depend on both OpenSSL and libxml2 instead of only
   OpenSSL (`CMakeLists.txt:225-247`). Add `--with-libxml=<install>` and prepend
   libxml2's `lib/pkgconfig` to the existing OpenSSL `PKG_CONFIG_PATH`, so xmlsec
   compiles against the same archive ultimately linked into nvat.
3. Use the existing `FindLibXml2.cmake` root-hint seam rather than defining a
   second imported target inline: set `LibXml2_ROOT` to the install prefix and
   set the expected include/archive cache entries before the vendored
   `find_package` call (`CMakeLists.txt:289`). Tighten the finder if necessary so
   a supplied root is searched with `NO_DEFAULT_PATH`; otherwise its initial
   recursive system lookup (`FindLibXml2.cmake:7-9`) could win. Its existing
   imported target creation remains authoritative (`FindLibXml2.cmake:43-48`).
   All changes stay inside root-hint handling or the vendored branch, leaving
   `USE_SYSTEM_DEPS=ON` (`CMakeLists.txt:132-174`) unchanged and configurable.
4. Add `--with-ca-fallback --without-ca-bundle --without-ca-path` to
   `curl_external` (`CMakeLists.txt:254-276`). In the shipped build,
   `CURLINFO_CAINFO` therefore returns null: resolution skips tier 5, probes the
   runtime distro, then errors actionably if no probe exists.

### 3. Release and gate authority (D8-D11)

1. Add `sol/release/dt-needed.allow` as the sole, comment-annotated DT_NEEDED
   authority. Allow the glibc/runtime set observed in the red baseline and
   explicitly allow:
   - `libz.so.1`, because the SDK deliberately retains its existing system zlib
     dependency (`CMakeLists.txt:294`) and zlib is baseline ABI on all gate
     distributions.
   - `libutil.so.1`, because it is introduced by the regorus static library and
     is a glibc compatibility DSO on the supported distributions. Its practical
     availability is proved by running `nvattest --help` in bare Fedora and
     Tumbleweed images, not merely by allowlisting it.
   Reject every unlisted DSO; specifically `libcurl`, `libssl`, `libcrypto`,
   `libxml2`, and `liblzma` are hard failures.
2. Add `sol/release/release.env` as the single sol-owned pin authority. It holds
   `SOL_REVISION=1`, the dated CA URL/hash, CI and gate image digest references,
   and no duplicate upstream version. Scripts parse SDK `project(... VERSION
   ...)` (`CMakeLists.txt:1-2`) and combine it with `SOL_REVISION` to produce
   `1.2.2-sol.1`.
3. Select curl's dated `cacert-2026-07-16.pem` snapshot, the current dated
   revision published by curl's CA extract service as of this design. The URL is
   `https://curl.se/ca/cacert-2026-07-16.pem`. The exact SHA256 must be copied
   from curl's adjacent immutable `.sha256` record into `release.env` and
   independently checked against the downloaded bytes during implementation;
   it is intentionally left as the only design-time open datum rather than
   inventing a hash. Packaging fails before mutation if either check disagrees.
4. Add a release driver and small helpers under `sol/release/`, invoked by new
   `make release-linux-x86_64`. The driver performs the CLI-root vendored build,
   static guard, CA fetch/hash verification, staged install, ELF/string gates,
   deterministic tar creation, cross-distro runtime gates, and manifest/hash
   emission. The exact archive layout is:
   `bin/nvattest`; `lib/libnvat.so`, `lib/libnvat.so.1`, and
   `lib/libnvat.so.1.2.2` only; `LICENSE`; `share/ca/ca-bundle.pem`; and
   `share/THIRD_PARTY_NOTICES.md`.
5. Do not add RPATH. Gates and documented invocation use
   `LD_LIBRARY_PATH=lib`, avoiding a packaging-only linker policy. The shipped
   `share/ca/ca-bundle.pem` is deliberately not a resolution tier: operators
   select it through `--ca-bundle` or `NVAT_CA_BUNDLE`, keeping the runtime
   ladder independent of installation layout.
6. Generate `THIRD_PARTY_NOTICES.md`, dependency pins, and manifest dependency
   data from CMake rather than a second component table. A parser reads complete
   `ExternalProject_Add` and `FetchContent_Declare` blocks, extracting immutable
   `URL` + `URL_HASH` or `GIT_REPOSITORY` + `GIT_TAG`, and fails on an unpinned
   block. It scans the SDK CMake file for OpenSSL, libxml2, xmlsec, curl,
   Corrosion, regorus, jwt-cpp, json, fmt, and spdlog, and the CLI CMake file for
   CLI11 (CLI11 does not occur in the SDK file: `nv-attestation-cli/CMakeLists.txt:16-23`).
   Test-only gtest and build-only tooling are recorded in manifest dependency
   pins but excluded from shipped notices unless their code is present in the
   artifact; the generator encodes that classification, not a handwritten
   notice list.
7. Emit a machine-readable JSON manifest containing schema/version, artifact
   version and SHA256, target, upstream base commit, the ordered sol-series
   commit list as a separate array, generated dependency pins, CI image digest,
   CA snapshot date/URL/SHA256, build timestamp/source-date epoch, and archive
   member inventory. Emit the conventional adjacent tarball `.sha256` from the
   same computed artifact digest.
8. Add `sol/check-curl-handle-sites.sh` using prep's exact grep shape and compare
   its output file set to the sole allowed `nv-attestation-sdk-cpp/src/nv_http.cpp`.
   Invoke it from both `make ci` and the release target. Falsify it during
   implementation by adding a scratch easy-handle violation, observing failure,
   then reverting the scratch change.
9. Change `make ci` (`Makefile:33-37`) to one
   `cmake -S nv-attestation-cli -B build` configuration with
   `USE_SYSTEM_NVAT=OFF`, vendored dependencies, tests, and shared nvat. Select
   tests with both `-L unit` and the existing `-E "$(NETWORK_TESTS)"`: the label
   chooses SDK tests (`unit-tests/CMakeLists.txt:201-205`) while the exclusion
   still removes live-endpoint SDK suites. CLI integration tests remain excluded
   through their distinct `cli` label (`nv-attestation-cli/tests/CMakeLists.txt:99-102`).
10. Pin images to prep's resolved references and remove the stale TODO at
    `sol/ci/Containerfile:3`:
    - `quay.io/pypa/manylinux_2_28_x86_64@sha256:a61875a2f84cab7df8de222ff12cabc08ff86eb4ad402ac90ba7bdaed9600cca`
    - `docker.io/library/fedora@sha256:6c75d5bf57cb0fa5aa4b92c6a83c86c791644496d9ac230de7711f5b8ec3b898`
    - `docker.io/opensuse/tumbleweed@sha256:18a8c2a41252a0100ae4a7dae0a0e925fb522971645b97b05c57f9b6e73c3b4f`

## Commit grouping (D12)

### G1 — upstream-clean CA behavior

Subject: `fix: resolve CA bundle paths at runtime`

Files: `nv-attestation-sdk-cpp/include/nv_attestation/nv_http.h`,
`nv-attestation-sdk-cpp/src/nv_http.cpp`,
`nv-attestation-sdk-cpp/include/nvat.h.in`,
`nv-attestation-sdk-cpp/src/nvat.cpp`,
`nv-attestation-sdk-cpp/unit-tests/CMakeLists.txt`, the new CA-resolution unit
test, `nv-attestation-cli/src/nvattest_options.h`,
`nv-attestation-cli/src/utils.cpp`, and `nv-attestation-cli/src/attest.cpp`.
Content and paths contain zero sol-specific naming.

### G2 — upstream-clean vendored dependency correction

Subject: `build: make vendored TLS dependencies portable`

Files: `nv-attestation-sdk-cpp/CMakeLists.txt` and, only if required to enforce
root precedence, `nv-attestation-sdk-cpp/cmake/FindLibXml2.cmake`. The commit
adds static libxml2 and removes curl's compiled host CA paths. Content and paths
contain zero sol-specific naming. Its message cites the binary red facts in
`sol/notes/red-baseline.md`, but does not add that sol file to the commit.

### G3 — release rail and repository gates

Subject: `build: add gated linux-x86_64 release rail`

Files: `Makefile`, `sol/ci/Containerfile`, `sol/check-curl-handle-sites.sh`, all
new `sol/release/*` authority/scripts, `sol/notes/red-baseline.md`, and this
design record if project history retains planning notes. This commit owns image
pins, the CI-root switch, artifact packaging, cross-distro gates, manifests,
notices, and release documentation.

## Risks and open question

- The CA snapshot SHA256 is the sole unresolved design datum. The selected dated
  object exists, but its official adjacent hash was not exposed by the browsing
  result. Implementation must obtain and record that official value before any
  release code is accepted; no floating `cacert.pem` fallback is permitted.
- CMake block extraction must parse complete balanced calls rather than line
  grep, because declarations are multiline and CLI11 lives in the CLI project.
  The generator must fail closed on unknown/unpinned declarations.
- `LibXml2_ROOT` can be defeated by the current finder's initial system search;
  G2 must prove root precedence without changing the system-dependency branch.
- The resolver's temporary easy handle is inside the one allowed file, but the
  guard checks files rather than handle counts. Review must ensure both resolver
  and request handles remain localized and correctly cleaned up.
- `libutil.so.1` is intentionally allowed based on the current regorus output;
  the bare Fedora/Tumbleweed execution gates remain the authoritative portability
  proof and must fail loudly if a future image drops the compatibility DSO.
