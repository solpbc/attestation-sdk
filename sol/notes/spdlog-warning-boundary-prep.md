# spdlog compiled third-party warning-policy boundary prep

Research captured in the worktree
`/home/jer/.hopper/worktrees/6chf45lc`. Product CMake and tests were not
changed, and no test suite or CI gate was run. All generated projects,
downloads, configured trees, and probe sources were kept under
`/tmp/nvat-warning-research`.

## Q1 — Offline Linux reproduction and effective-command baseline

The production entry point is `nv-attestation-cli/CMakeLists.txt`. It enables
the warning-as-error variable at `nv-attestation-cli/CMakeLists.txt:12-13`,
creates `nvattest` at `:30-37`, and enters the SDK at `:79-86`. The SDK fetches
and creates fmt at `nv-attestation-sdk-cpp/CMakeLists.txt:113-127`, creates
spdlog at `:129-139`, adds its directory warning options at `:368-374`, and
creates `nvat` at `:388-419`.

I configured that production entry point with CMake 4.3.4 and GNU 15.3.0,
using the supplied `USE_SYSTEM_NVAT=OFF`, `USE_SYSTEM_DEPS=OFF`,
`BUILD_TESTING=OFF`, shared Release and compile-command arguments. Every
FetchContent source was an offline scratch stub. fmt and spdlog were real
one-source static targets. Corrosion modeled an imported static
`regorus_ffi` and a cargo utility target (see Q4). Configure completed without
network access.

The following are the exact `-W*` token sequences, in command order, extracted
from one representative real compile command for each target. This is the
before-image to preserve for unaffected commands:

| target | exact effective `-W*` sequence |
| --- | --- |
| `fmt` | *(none)* |
| `spdlog` | `-Werror` |
| `nvat` | `-Wall -Wextra -Wpedantic -Wno-unused -Wno-unused-parameter -Wno-c++17-extensions -Werror` |
| `nvattest` | `-Werror` |

`nvat` also has `-pedantic`, which is a warning-policy option but does not
match the requested literal `-W*` extraction. Its complete policy tail was
`-Wall -Wextra -Wpedantic -pedantic -Wno-unused -Wno-unused-parameter
-ffile-prefix-map=/home/jer/.hopper/worktrees/6chf45lc/nv-attestation-cli/src/=
-Wno-c++17-extensions -Werror`. The expected table is therefore confirmed
verbatim.

The mechanism on current CMake is target-property initialization:
`CMAKE_COMPILE_WARNING_AS_ERROR` is set in the CLI before `nvattest`, inherited
by the SDK, and set to the same value in the SDK cache at
`nv-attestation-sdk-cpp/CMakeLists.txt:10-13`. fmt is then explicitly opted
out at `:122-127`; spdlog is not.

**Observed on this lode:** a complete offline production configure and the
four generated GNU compile commands above. **Unobserved:** AppleClang 21
output and an actual spdlog 1.14.1 compilation; the stub deliberately models
the configured target-policy boundary, not third-party source diagnostics.

## Q2 — Legacy path below CMake 3.24

On legacy CMake, setting `CMAKE_COMPILE_WARNING_AS_ERROR` has no target-property
effect. The SDK compensates at
`nv-attestation-sdk-cpp/CMakeLists.txt:368-370`: it first adds the general SDK
warning options and then conditionally adds directory `-Werror`. Directory
compile options initialize targets created later in that directory and flow
to subdirectories added later.

The exact reachability is:

| target | legacy source of options | effective result |
| --- | --- | --- |
| `fmt` | Created by the subdirectory added at SDK `:121`, before SDK `:368-370` | no SDK general warnings and no `-Werror` |
| `spdlog` | Created by the subdirectory added at SDK `:139`, before SDK `:368-370` | no SDK general warnings and no `-Werror` |
| `nvat` | Created at SDK `:388`, after SDK `:368-374` | general SDK warnings, suppressions, and fallback `-Werror` |
| `nvattest` | Created in the parent at CLI `:30`, before the SDK is added at CLI `:83` | no legacy `-Werror` |

Thus `nvattest` currently receives **no warnings-as-errors on CMake 3.11**.
The child SDK cannot retroactively mutate the already-created parent target,
and directory properties do not flow upward.

Meeting the stated first-party invariant on the 3.11 fixture therefore
requires new legacy ownership in the CLI directory, before `nvattest` is
created. That is a permitted explicit-ownership-boundary change if it is
conditional on legacy CMake and the enabled policy, and scoped so it applies
to `nvattest` without flowing into the later SDK subdirectory. A target-local
legacy `target_compile_options(nvattest PRIVATE -Werror)` after target creation
is the narrowest expression. A CLI-directory `add_compile_options` before
`nvattest` would also reach later subdirectories and would leak to SDK
dependencies, so it does not satisfy the boundary.

**Observed on this lode:** source ordering and CMake 3.11.4 behavior in an
extracted fixture (Q3). **Unobserved:** the full production tree under 3.11,
which cannot configure because its FetchContent API use requires newer CMake.

## Q3 — Faithfully observing the legacy branch

Three candidate approaches were evaluated:

1. **Extract real production policy text into a fixture.** This follows the
   established source-coupled pattern in
   `sol/release/tests/test_apple_cmake.py:96-98,315-318`: tests derive fixture
   content from production text instead of maintaining a second policy
   implementation. It can preserve the significant directory/target ordering
   and run without any FetchContent APIs. Its limit is that extraction proves
   only the selected policy region and modeled target layout, not the full
   production configure.
2. **Shadow `CMAKE_VERSION` through `CMAKE_PROJECT_INCLUDE`.** The current
   helper already injects a file at
   `sol/release/tests/test_apple_cmake.py:270-358`. Empirically, CMake 4.3.4
   honored `set(CMAKE_VERSION 3.11.0)` for the source
   `if(CMAKE_VERSION VERSION_LESS 3.24.0)` branch: the fallback `-Werror`
   appeared. However, this does **not** emulate the old engine. The modern
   binary still implemented `COMPILE_WARNING_AS_ERROR`: a normal target got
   both property and fallback `-Werror`, while a target with the property
   `OFF` still got the directory fallback. Shadowing is useful for branch
   selection and ordering, but cannot prove that the property is unavailable
   on 3.11.
3. **Use a real old binary on an extracted fixture.** A real CMake 3.11.4
   Linux binary is obtainable here from the still-live official
   `cmake-3.11.4-Linux-x86_64.tar.gz` (34,439,437 bytes). I downloaded it only
   to scratch and ran the fixture. Both targets received the legacy directory
   `-Werror`; setting `COMPILE_WARNING_AS_ERROR OFF` did not cancel it, as
   expected because 3.11 has no such generator feature. The limit is
   portability: a release test must not download a tool during execution or
   assume this scratch binary exists.

Recommendation: use a **source-extracted fixture** as the committed,
deterministic test, retaining the existing `production_configure()` harness
infrastructure rather than creating another configure framework. Use a
test-controlled branch version in the extracted fixture for routine branch
classification, and document that it proves production text, ordering, and
fallback ownership—not execution by the 3.11 engine. The one-off real 3.11.4
fixture run supplies supporting floor evidence on this lode; it should not be
overclaimed as a full production configure. Shadowing the full production
configure is weaker evidence and should not be the sole floor proof.

**Observed on this lode:** modern shadow behavior and a real 3.11.4 extracted
fixture configure. **Unobserved:** the full repository under 3.11 and a
portable CI installation of that binary.

## Q4 — Criterion-1 target-graph extraction

I placed a `codemodel-v2` query in the Q1 build before configure and classified
the resulting target JSON by target `type` and sources having a non-null
`compileGroupIndex`. The relevant inventory was:

| target | File API type | compile-owning sources |
| --- | --- | ---: |
| `nvat` | `SHARED_LIBRARY` | 30 |
| `nvattest` | `EXECUTABLE` | 6 |
| `fmt` | `STATIC_LIBRARY` | 1 |
| `spdlog` | `STATIC_LIBRARY` | 1 |
| `regorus_ffi` | `STATIC_LIBRARY` (imported) | 0 |
| `cargo-build_regorus_ffi` | `UTILITY` | 0 |
| `openssl_external` | `UTILITY` | 0 |
| `libxml2_external` | `UTILITY` | 0 |
| `xmlsec_external` | `UTILITY` | 0 |
| `curl_external` | `UTILITY` | 0 |

The four ExternalProject utility JSON records contain ten generated
non-compile sources each, but zero compile-owning sources. INTERFACE targets
(`CLI11`, `nlohmann_json`, `own-jwt-cpp`) are present in this CMake 4.3.4 File
API response, contrary to the stated expectation that they are absent; they
also own zero compile sources. Several imported system/library targets are
present and likewise own zero compile sources.

The hand-free inclusion rule is: **classify every target with at least one
source assigned to a compile group**. Equivalently, exclude targets whose
type cannot compile (`UTILITY`, `INTERFACE_LIBRARY`) and imported library
records with zero compile-group sources; do not exclude by target name.
This yields exactly the four real compile owners.

The Corrosion stub must not define `regorus_ffi` as INTERFACE. Its
`corrosion_import_crate()` must create `add_library(regorus_ffi STATIC
IMPORTED GLOBAL)`, give it an `IMPORTED_LOCATION`, and create a separate
`add_custom_target(cargo-build_regorus_ffi)`. With precisely that faithful
shape, the imported static library and cargo utility both appeared in the
codemodel but neither owned compile sources, so the same structural rule
still selected exactly `nvat`, `nvattest`, `fmt`, and `spdlog`.

The phrase “plus four `*_external` UTILITY targets” is correct for the
ExternalProject set, but the total zero-compile utility count is five once
the faithful cargo target is included.

**Observed on this lode:** the real Q1 production codemodel with the faithful
Corrosion target shape. **Unobserved:** the exact target names emitted by the
pinned real Corrosion implementation; the model captures the relevant
imported-library/utility types and ownership.

## Q5 — Controlled-warning compile gate

I wrote exactly `int f() { }` and, for a representative source in each
target, took its effective `compile_commands.json` command, replaced only the
source path, and ran it from the command's recorded working directory. GNU
15.3.0 enables `-Wreturn-type` by default.

`nvattest` returned 1:

```text
/tmp/nvat-warning-research/warning.cpp: In function ‘int f()’:
/tmp/nvat-warning-research/warning.cpp:1:11: error: no return statement in function returning non-void [-Werror=return-type]
    1 | int f() { }
      |           ^
cc1plus: all warnings being treated as errors
```

`nvat` returned 1 with the identical diagnostic:

```text
/tmp/nvat-warning-research/warning.cpp: In function ‘int f()’:
/tmp/nvat-warning-research/warning.cpp:1:11: error: no return statement in function returning non-void [-Werror=return-type]
    1 | int f() { }
      |           ^
cc1plus: all warnings being treated as errors
```

`fmt` returned 0:

```text
/tmp/nvat-warning-research/warning.cpp: In function ‘int f()’:
/tmp/nvat-warning-research/warning.cpp:1:11: warning: no return statement in function returning non-void [-Wreturn-type]
    1 | int f() { }
      |           ^
```

This gate tests the effective generated command rather than merely inspecting
CMake source or a target property. A future test should run it for both
third-party compile owners; the requested empirical trio above is confirmed.

**Observed on this lode:** all three exact GNU invocations and return codes.
**Unobserved:** AppleClang wording; assertions should classify return status
and warning/error policy without depending on GNU-only prose.

## Q6 — Existing-test breakage and placement

The only existing release test that directly forbids the intended change is
`AppleCMakeTest.test_preproject_guards_and_fmt_exemption_are_exact` at
`sol/release/tests/test_apple_cmake.py:245-268`. Its
`assertNotIn("set_target_properties(spdlog PROPERTIES
COMPILE_WARNING_AS_ERROR OFF)")` at `:265-268` necessarily fails. The adjacent
fmt count assertion at `:258-264` remains valid. A repository-wide search
found no other Python release test asserting warning-policy text or `-Werror`.

The graph and compile-gate tests belong in a new warning-policy-focused module
under `sol/release/tests/`, not in Apple-specific
`test_apple_cmake.py`. The source assertion above should be updated in place
because it owns the preproject/exemption exactness already.

Do not build a second configure harness. Move `production_configure()` and
the small constants/support it needs from
`sol/release/tests/test_apple_cmake.py:270-358` into a shared helper module in
`sol/release/tests/`, import it into both test modules, and preserve its return
contract. Reusable pieces are temporary root/build creation (`:270-276`),
`CMAKE_PROJECT_INCLUDE` generation (`:277-298`), configure argument assembly
and optional external build path (`:299-313`), subprocess capture and trace
loading (`:350-358`). The current `nested` stub block at `:314-345` is too
Apple-test-specific: it creates INTERFACE fmt/spdlog and intentionally fails
at missing Corrosion, so the shared helper should accept a fixture/stub
preparation callback or additional arguments. The warning module should
supply the faithful compiled dependency stubs from Q1/Q4 while using the same
configure runner, trace handling, and lifetime management.

**Observed on this lode:** exhaustive `sol/release/tests/*.py` text search and
the current helper implementation. **Unobserved:** runtime failures, because
the constraints prohibit running tests in prep.

## Q7 — Criterion-5 dependency and Rust inputs

`generate-dependencies.py:56-64` reads the sorted recursive union of these
actual files, then appends the gtest helper:

```text
nv-attestation-cli/CMakeLists.txt
nv-attestation-cli/tests/CMakeLists.txt
nv-attestation-sdk-cpp/CMakeLists.txt
nv-attestation-sdk-cpp/examples/CMakeLists.txt
nv-attestation-sdk-cpp/examples/attest-minimal/CMakeLists.txt
nv-attestation-sdk-cpp/examples/attest/CMakeLists.txt
nv-attestation-sdk-cpp/examples/attest_local/CMakeLists.txt
nv-attestation-sdk-cpp/examples/attest_policy_custom/CMakeLists.txt
nv-attestation-sdk-cpp/examples/attest_policy_none/CMakeLists.txt
nv-attestation-sdk-cpp/examples/attest_remote/CMakeLists.txt
nv-attestation-sdk-cpp/examples/collect-gpu-evidence/CMakeLists.txt
nv-attestation-sdk-cpp/examples/common/CMakeLists.txt
nv-attestation-sdk-cpp/examples/custom-logger/CMakeLists.txt
nv-attestation-sdk-cpp/examples/json-gpu-evidence/CMakeLists.txt
nv-attestation-sdk-cpp/examples/parallel-verification/CMakeLists.txt
nv-attestation-sdk-cpp/unit-tests/CMakeLists.txt
nv-attestation-sdk-cpp/cmake/nvat_fetch_gtest.cmake
```

By contrast,
`test_baseline_stability.py:20-21,52-63` compares dependency coordinates and
project versions only in the two top-level CMakeLists. It does not cover
nested/example/test dependency declarations or any Cargo manifest.

For this release graph, “Rust inputs” means:

* Corrosion source coordinate
  `https://github.com/corrosion-rs/corrosion.git` at commit
  `6be991bb34c348dfb8344be22f3606288ea5c7fd`
  (`nv-attestation-sdk-cpp/CMakeLists.txt:49-56`). It is the Rust/CMake build
  integration pin, classified as a build dependency by
  `generate-dependencies.py:47-53`.
* regorus source coordinate `https://github.com/microsoft/regorus.git` at tag
  `regorus-v0.4.0` (`nv-attestation-sdk-cpp/CMakeLists.txt:58-63`). The tag
  dereferenced to commit `c7bf460bc160c96e38048296e5708943d2e43909`
  on this lode.
* The reachable manifests under that pin:
  `bindings/ffi/Cargo.toml`, selected explicitly by SDK `:65-71`, declares
  package `regorus-ffi` 0.2.2 and a path dependency `../..`; that reaches the
  repository-root `Cargo.toml`, package `regorus` 0.4.0. The import requests
  crate `regorus-ffi`, staticlib, Release, with feature `regorus/semver`.
  The other binding/test manifests in the repository are not reachable from
  this standalone ffi workspace/path-dependency graph. The pinned tree has no
  `Cargo.lock`, so dependency resolution is not lockfile-fixed.

The local `nv-attestation-sdk-rust/{Cargo.toml,
nv-attestation-sdk-sys/Cargo.toml,nv-attestation-sdk/Cargo.toml` manifests are
not reachable from the native release build driven by `targets.toml`; that
rail invokes cargo because CMake/Corrosion builds regorus. They therefore
should not be mislabeled as criterion-5 inputs for this graph.

Finally, `test_baseline_stability.py:17` still declares
`BASELINE = 31ff1fbe824dd2856ee217d2398176ef293f847b`. The task baseline is
`46c10e4808965d6c065d62dece0071a8ff1624da`; both commits exist locally, the
former is an ancestor of the latter, and both top-level CMakeLists changed
between them. The constant is therefore stale for this task and cannot
support a byte-identity claim against the requested baseline without update.

**Observed on this lode:** the exact parser glob, local release graph, both
Git commits, remote pinned regorus tag/commit and its manifests.
**Unobserved:** a Cargo resolution/build of regorus; no lockfile or Rust
compile was generated in this research.
