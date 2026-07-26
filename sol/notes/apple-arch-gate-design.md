# Post-project Apple arm64 architecture gate design

**Authority.** This record is a focused amendment to
`sol/notes/mac-native-build-design.md`. It moves only the native-host arm64
claim out of pre-project resolution and validates it after CMake has measured
the host and configured system. SDK selection, deployment-floor validation,
architecture normalization, dependency delivery, release authority, pins, and
manifest evidence remain unchanged.

This design is authored on a Linux lode. Linux fixtures prove call order and
fail-closed behavior against the real production CMake entry points; they
never prove the macOS population fact. Native population and artifact proof
belongs to VPE.

## D1 — Validator identity, lifetime, and placement

Add the public, no-argument function
`nvat_validate_apple_architecture()` to
`nv-attestation-sdk-cpp/cmake/nvat_apple_sdk.cmake`.

Its first operation is the existing native-host predicate:

```text
if(NOT CMAKE_HOST_SYSTEM_NAME STREQUAL "Darwin")
  return()
endif()
```

After that gate it reads the GLOBAL property
`NVAT_APPLE_ARCHITECTURE_VALIDATED` and returns when it is already true. It
performs D2's checks in order and writes:

```text
set_property(GLOBAL PROPERTY NVAT_APPLE_ARCHITECTURE_VALIDATED TRUE)
```

only after all checks pass. The marker is process-local CMake state. It is
never a normal or INTERNAL cache variable, is never accepted as caller input,
and cannot survive a configure process.

Remove the `CMAKE_HOST_SYSTEM_PROCESSOR` check from
`nvat_resolve_apple_toolchain()`. All other resolver checks, normalization,
cache writes, and `NVAT_APPLE_TOOLCHAIN_RESOLVED` behavior remain unchanged.

In both production CMakeLists, include the module unconditionally before
`project()`, while retaining the resolver invocation inside its existing
`CMAKE_HOST_SYSTEM_NAME STREQUAL "Darwin"` block. Immediately after each
`project()` make one unconditional call to
`nvat_validate_apple_architecture()`. An unconditional include is inert on
Linux because the module only defines functions; the unconditional call is
safe because the validator self-gates.

`include_guard(GLOBAL)` means the CLI's first include defines the functions
once for the entire configure. With `USE_SYSTEM_NVAT=OFF`, execution is:

1. CLI include and pre-project resolver;
2. CLI `project(nvattest ...)`;
3. CLI validator, which validates and sets the GLOBAL marker;
4. CLI `add_subdirectory(...)`;
5. SDK include, suppressed by the GLOBAL include guard;
6. SDK pre-project resolver sentinel check;
7. SDK `project(nv-attestation ...)`;
8. SDK validator, which returns on the shared GLOBAL validated marker.

There are two `project()` calls and two authored call sites but exactly one
validation per configure process. A standalone SDK configure likewise
validates exactly once.

The existing structural assertions remain true verbatim: both pre-project
prefixes still exclude `if(APPLE`, still contain the exact native-host Darwin
guard, and the SDK prefix still reads
`NVAT_APPLE_TOOLCHAIN_RESOLVED`. Coverage is extended to require the
unconditional include and exactly one validator call immediately following
each first `project()`; the old assertions are not weakened.

## D2 — Comparison rules and diagnostics

All processor matches use the exact CMake regex `^(arm64|aarch64)$`.
`CMAKE_OSX_ARCHITECTURES` is treated as a CMake list: first reject empty,
then obtain `list(LENGTH CMAKE_OSX_ARCHITECTURES
_nvat_apple_architecture_count)`, reject any length other than one, and
finally require its sole value to be exactly `arm64`. `aarch64` is accepted
only for the measured host/system processor aliases, not as the authored
Apple architecture.

Cross-compilation needs both checks. `CMAKE_CROSSCOMPILING` detects an
explicit toolchain/system configuration even when its named system is Darwin;
`CMAKE_SYSTEM_NAME` detects a contradictory configured target. Neither
subsumes the other as a statement of the native-only policy, so each has its
own diagnostic.

Every failure follows `<what failed>: <specific detail>; <actionable
recovery>`:

| Check | Exact `FATAL_ERROR` text |
|---|---|
| Host processor empty | `Apple architecture validation failed: CMAKE_HOST_SYSTEM_PROCESSOR is empty after project(); run CMake natively on an Apple Silicon arm64 host, then retry` |
| Host processor wrong | `Apple architecture validation failed: CMAKE_HOST_SYSTEM_PROCESSOR '${CMAKE_HOST_SYSTEM_PROCESSOR}' is not arm64 or aarch64; run CMake natively on an Apple Silicon arm64 host, then retry` |
| System processor empty | `Apple architecture validation failed: CMAKE_SYSTEM_PROCESSOR is empty after project(); remove the build directory and configure natively for arm64 on Apple Silicon, then retry` |
| System processor wrong | `Apple architecture validation failed: CMAKE_SYSTEM_PROCESSOR '${CMAKE_SYSTEM_PROCESSOR}' is not arm64 or aarch64; remove the build directory and configure natively for arm64 on Apple Silicon, then retry` |
| Architecture empty | `Apple architecture validation failed: CMAKE_OSX_ARCHITECTURES is empty after project(); remove the build directory and configure natively with -DCMAKE_OSX_ARCHITECTURES=arm64, then retry` |
| Architecture has zero or multiple list elements | `Apple architecture validation failed: CMAKE_OSX_ARCHITECTURES '${CMAKE_OSX_ARCHITECTURES}' contains ${_nvat_apple_architecture_count} entries, expected exactly one; remove the build directory and configure natively with -DCMAKE_OSX_ARCHITECTURES=arm64, then retry` |
| Sole architecture wrong | `Apple architecture validation failed: CMAKE_OSX_ARCHITECTURES '${CMAKE_OSX_ARCHITECTURES}' is not exactly arm64; remove the build directory and configure natively with -DCMAKE_OSX_ARCHITECTURES=arm64, then retry` |
| Cross-compiling true | `Apple architecture validation failed: CMAKE_CROSSCOMPILING '${CMAKE_CROSSCOMPILING}' is not false for a native build; remove the build directory and configure natively on an Apple Silicon arm64 host, then retry` |
| Configured system is not Darwin | `Apple architecture validation failed: CMAKE_SYSTEM_NAME '${CMAKE_SYSTEM_NAME}' is not Darwin; remove the build directory and configure natively on an Apple Silicon arm64 host, then retry` |

The checks run independently in the table's order. Tests isolate each failure
by making every other input valid. Contradictory-combination tests establish
the deterministic first failure rather than allowing one bad field to mask
missing coverage of another.

## D3 — Host gate

The validator uses `CMAKE_HOST_SYSTEM_NAME STREQUAL "Darwin"`, not `APPLE`.
The claim is about the native host, and the same expression already controls
pre-project Apple resolution. `APPLE` is a target-platform variable
established by `project()` and would blur host validation with target
selection. The existing test banning `if(APPLE` in the pre-project prefix is
unchanged; an additional whole-function assertion fixes the validator's
self-gate to the native-host expression.

## D4 — Honest Linux observability

### D4.1 — Post-project production configure

Extend `sol/release/tests/test_apple_cmake.py` with a helper that configures
each real production source tree into a temporary build directory. It supplies
a test-owned `CMAKE_PROJECT_INCLUDE` file. On every invocation the fixture:

* sets `CMAKE_HOST_SYSTEM_NAME`, `CMAKE_HOST_SYSTEM_PROCESSOR`,
  `CMAKE_SYSTEM_NAME`, `CMAKE_SYSTEM_PROCESSOR`,
  `CMAKE_OSX_ARCHITECTURES`, and `CMAKE_CROSSCOMPILING` from test inputs;
* appends one project-boundary record containing `PROJECT_NAME`,
  `CMAKE_CXX_COMPILER_LOADED`, and `CMAKE_CXX_COMPILER` to a temporary data
  log.

Invoke CMake with `--trace-format=json-v1` and
`--trace-redirect=<temporary-event-log>`. The JSON trace is the observation
of the production validator: count command events whose file is the real
production CMakeLists and whose arguments are exactly
`nvat_validate_apple_architecture`. Order those trace events against the
fixture's `file(APPEND ...)` command events. This needs no production hook,
cache flag, logging variable, or bypass. The trace observes commands CMake
actually executes and cannot make a failed check pass.

For the standalone SDK, the fixture fires once and the trace contains one
validator call after the fixture boundary. For CLI with
`USE_SYSTEM_NVAT=OFF`, `CMAKE_PROJECT_INCLUDE` fires for both `project()`
calls. The fixture therefore emits two boundary records, one per project; it
does not count validation. The trace must show the CLI validator after the
first boundary and the SDK call after the second boundary, while success plus
the GLOBAL marker semantics show that only the first call performs checks.
Structural inspection of the function requires the marker read before any D2
check and the marker write after all checks.

Reaching the nested SDK offline requires test-owned FetchContent source
overrides. The declarations before the SDK `add_subdirectory` are exactly
CLI11, json, fmt, and spdlog, including the two declarations in the
`USE_SYSTEM_NVAT` branch. The test extracts that set from the real prefix and
requires exact equality with its stub set. Supply minimal local source
directories through `FETCHCONTENT_SOURCE_DIR_CLI11`,
`FETCHCONTENT_SOURCE_DIR_JSON`, `FETCHCONTENT_SOURCE_DIR_FMT`, and
`FETCHCONTENT_SOURCE_DIR_SPDLOG`; their CMakeLists define only the interface
targets the CLI names. Supply a
deliberately nonexistent `FETCHCONTENT_SOURCE_DIR_CORROSION` so the first SDK
population attempt becomes a controlled offline abort after the SDK
validator. Before the nested SDK project, the project-include fixture changes
the measured processor to an invalid value and records the GLOBAL validated
property. Reaching the Corrosion source-directory error, rather than the
architecture diagnostic, proves the nested validator short-circuited. The
trace proves both production call sites executed, and the fixture's property
observation proves the first call completed validation. These test-owned
source overrides neither edit the production lists nor contact a network, and
the controlled abort occurs strictly after both validator seams under test.

Each boundary record must show
`CMAKE_CXX_COMPILER_LOADED=1` and a nonempty compiler path. This proves the
test mutation and subsequent validator calls are after compiler measurement.
Failure cases terminate before any FetchContent population or SDK
`add_subdirectory`, so they remain offline.

Run the validation-successful standalone case twice as two successive CMake
configure processes using the same build directory, using the same controlled
offline Corrosion population abort after the validator. Each trace must
contain the expected call sequence and each process must perform one
validation before that expected abort. This proves the GLOBAL marker does not
persist across processes. Grep the resulting `CMakeCache.txt` for the absence of
`NVAT_APPLE_ARCHITECTURE_VALIDATED`; the existing resolver INTERNAL entries
remain expected.

The success fixture uses the already-authored absolute SDK/floor/architecture
cache inputs. Failure fixtures alter only the post-project observed values.
`test_postproject_host_processor_assertion_is_relocated_exactly` proves
“resolution succeeded but validation did not”: it supplies a real temporary
SDK, valid deployment floor, and pre-project arm64 architecture, then forces
an invalid post-project measured host and requires configure failure.
`test_each_postproject_architecture_check_fails_independently` covers every D2
field plus simultaneous contradictions in documented check order.
`test_standalone_sdk_validates_once_per_process_without_cache_marker` and
`test_cli_with_sdk_uses_all_pre_nesting_stubs_and_validates_once` assert in
the JSON trace that each boundary `file(APPEND ...)` precedes its production
validator call.

### D4.2 — Real pre-project prefix in script mode

For each production CMakeLists, read the file and split once on the first
literal `project(`. Write the exact prefix, without hand-copying or rewriting
it, into a temporary mirror of the production tree layout. Symlink the real
`nvat_apple_sdk.cmake` into the mirror path expected by that verbatim prefix.
Run the prefix with `cmake -P`, setting Darwin and supplying real temporary
SDK/floor inputs.

This proves that the authored production prefix invokes the real resolver and
normalizes an absent `CMAKE_OSX_ARCHITECTURES` to `arm64`. Script mode leaves
`CMAKE_HOST_SYSTEM_PROCESSOR` empty; after this change that is intentionally
irrelevant to resolution. It is the regression narrative: the old
pre-project claim used a value that CMake had not yet measured, while the new
validator checks it only after `project()`.

Linux fixtures prove call order only; they never prove the macOS population
fact. Real native proof belongs to VPE.

### D4.3 — Permitted filesystem assertions

A post-project failure necessarily leaves `CMakeCache.txt`, `CMakeFiles/`,
the versioned compiler metadata and CompilerId directories,
`CMakeConfigureLog.yaml`, `CMakeScratch`, `cmake.check_cache`, and
`pkgRedirects`. No test may claim a pristine or absent build directory.

Failure tests may assert that no FetchContent source/subbuild directories,
ExternalProject prefixes, configured project targets, CLI configured header,
SDK subdirectory build, release archive, manifest, sidecar, or promoted
quartet exists, according to the seam reached.

## D5 — AC6 baseline comparison

Add `sol/release/tests/test_baseline_stability.py`. It reads baseline blobs
with:

```text
git show 31ff1fbe824dd2856ee217d2398176ef293f847b:<path>
```

and never duplicates a baseline value in Python.

Extraction and assertions are:

1. `sol/release/targets.toml`: compare the complete working-tree bytes to the
   baseline blob bytes.
2. `authority.py`: extract `TARGET_IDS` from each source with
   `^TARGET_IDS\\s*=\\s*(\\([^\\n]*\\))$` under `re.MULTILINE`, parse the
   captured tuple with `ast.literal_eval`, and compare the tuples.
3. Each CMakeLists: first remove CMake line comments with
   `#[^\\n]*`, then extract ordered pin records with
   `(?:^|[\\s(])(GIT_REPOSITORY|GIT_TAG|URL_HASH|URL)[ \\t]+([^\\s)]+)` under
   `re.MULTILINE`. This includes fields in one-line
   `FetchContent_Declare(...)` calls while excluding comment prose. Compare the ordered
   `(field, value)` tuples from baseline and working tree. `GIT_TAG`,
   `URL_HASH`, and `URL` are each also counted so deletion of an entire class
   cannot collapse into a misleading comparison.
4. Each CMakeLists: extract project identity with
   `^project\\(([^\\s)]+)\\s+VERSION\\s+([^\\s)]+)\\)$` under
   `re.MULTILINE`, require exactly one match, and compare `(name, version)`.
5. Parse the baseline SDK project match, construct
   `<version>-sol.<current authority sol_revision>`, and assert
   `set_validator.release_version(ROOT, authority.load())` equals it.

The AC5 authored-versus-observed pairs are behavioral assertions, not
citations: `test_apple.py` writes an authored
`CMAKE_OSX_ARCHITECTURES=arm64` cache and requires
`Authority.require_compatible()` to reject an observed Darwin/x86_64 host;
`test_macho.py` writes the same authored cache value and requires the Mach-O
gate to reject an observed x86_64 cputype.

The test does not compare entire CMakeLists because their wiring intentionally
changes. It does compare every scoped dependency coordinate and both project
identity lines. `targets.toml`, `TARGET_IDS`, and the literal
`project(nv-attestation VERSION 1.2.2)` remain unchanged.

## D6 — Documentation text

Update `sol/release/README.md` under `### macOS prerequisites`, after the
paragraph ending “release must run natively on Apple Silicon,” with:

> CMake resolves the SDK, deployment floor, and requested arm64 architecture
> before `project()` so compiler initialization receives the authored inputs.
> Immediately after `project()`, it validates CMake's measured host processor,
> configured system processor, single arm64 architecture, and native Darwin
> status. A failed post-project validation leaves CMake cache and compiler-ID
> diagnostics in the build directory; remove that failed build directory
> before retrying natively on Apple Silicon.

Replace the opening lode-boundary sentence at lines 106–111 with:

> The lode exercises the real production pre-project Apple SDK-resolution
> prefixes in script mode and the real production post-project architecture
> validators through offline configure fixtures. Those fixtures prove
> resolution, compiler-boundary ordering, fail-closed comparisons, and
> process-local once-per-configure behavior; forcing Darwin variables on Linux
> does not prove that native macOS CMake populates them.

Retain the existing ELF/Mach-O, evidence, transaction, set-validation, Linux,
and Docker boundary statements that follow.

Extend the VPE macOS sentence at lines 120–126 with:

> VPE must additionally record the genuine post-`project()` values of
> `CMAKE_HOST_SYSTEM_PROCESSOR`, `CMAKE_SYSTEM_PROCESSOR`,
> `CMAKE_OSX_ARCHITECTURES`, `CMAKE_CROSSCOMPILING`, and
> `CMAKE_SYSTEM_NAME`, and confirm that the architecture validator passes once
> in both standalone SDK and CLI-with-SDK native configures.

## Test inventory and AC mapping

| AC | Actual test | Status and proof |
|---|---|---|
| AC1 | `test_apple_cmake.py::test_production_prefix_normalizes_absent_architecture` | New; executes both verbatim production prefixes and proves absent architecture normalizes to `arm64`. |
| AC1 | `test_apple_cmake.py::test_standalone_sdk_validates_once_per_process_without_cache_marker` | New; two successive real SDK configures each assert compiler-loaded boundary data, boundary-before-validator JSON-trace order, one performed validation, and no cache marker. |
| AC1 | `test_apple_cmake.py::test_cli_with_sdk_uses_all_pre_nesting_stubs_and_validates_once` | New; real CLI→SDK nesting asserts both compiler boundaries precede their validator calls, the complete pre-nesting stub set, two call sites, and one performed validation. |
| AC2 | `test_apple_cmake.py::test_postproject_host_processor_assertion_is_relocated_exactly` | Relocated from the former script-mode processor subcase; proves valid resolution followed by the exact post-project x86_64 host diagnostic. |
| AC2/AC3 | `test_apple_cmake.py::test_each_postproject_architecture_check_fails_independently` | New consolidated table; covers every empty/wrong/multi/cross field independently and both simultaneous-contradiction cases with deterministic first diagnostics. |
| AC3 | `test_apple_cmake.py::test_postproject_failure_precedes_dependency_population` | New; proves architecture failure leaves no `_deps` population or ExternalProject prefix while permitting unavoidable CMake/compiler state. |
| AC3 | `test_apple_cmake.py::test_preproject_guards_and_fmt_exemption_are_exact` | Modified; preserves all original prefix/fmt/spdlog assertions and adds exact immediate post-project validator wiring. |
| AC4 | `test_driver.py::test_macos_build_failures_use_driver_build_seam_and_never_publish` | Modified; adds `"Apple architecture validation failed"` to the existing `assert_release_failure_preserves_quartet` table, deliberately reusing its retained-quartet and empty-final-path closure instead of duplicating it. |
| AC5 | `test_apple.py::test_authored_arm64_cache_rejects_non_arm64_host_observation` | New; authored arm64 cache plus observed Darwin/x86_64 host is rejected by authority compatibility. |
| AC5 | `test_macho.py::test_authored_arm64_cache_rejects_non_arm64_macho_observation` | New; authored arm64 cache plus observed x86_64 Mach-O cputype is rejected by the Mach-O gate. |
| AC6 | `test_baseline_stability.py::test_targets_authority_is_byte_identical` | New; complete `targets.toml` byte comparison. |
| AC6 | `test_baseline_stability.py::test_target_ids_are_unchanged` | New; extracted baseline/current tuples, no hardcoded IDs. |
| AC6 | `test_baseline_stability.py::test_cmake_versions_and_dependency_coordinates_are_unchanged` | New; ordered extracted project identities and every `GIT_REPOSITORY`, `GIT_TAG`, `URL_HASH`, and `URL` in both CMakeLists. |
| AC6 | `test_baseline_stability.py::test_release_version_matches_baseline_sdk_version` | New; baseline SDK version plus current Sol revision equals `release_version()`. |
| AC7 | `test_apple_cmake.py::test_guard_skips_non_darwin_and_runs_for_darwin` | Existing, retained; real module guard remains inert for Linux and executes for forced Darwin script mode. |
| AC7 | `test_apple_cmake.py::test_all_external_projects_consume_shared_outputs` | Existing unchanged; guards Linux/Darwin shared dependency command structure. |

## File-by-file implementation plan

1. `nv-attestation-sdk-cpp/cmake/nvat_apple_sdk.cmake`
   - Remove only the pre-project host-processor assertion.
   - Add `nvat_validate_apple_architecture()` with the D1 lifetime and D2
     checks/messages.
   - Do not change SDK discovery, deployment validation, normalization,
     ExternalProject environment output, or cache the validation marker.
2. `nv-attestation-sdk-cpp/CMakeLists.txt`
   - Make the module include unconditional before `project()`.
   - Keep the resolver call and existing resolved sentinel in the Darwin guard.
   - Add one unconditional validator call immediately after `project()`.
   - Do not change the literal project line, pins, dependency declarations,
     warning policy, or Linux dependency behavior.
3. `nv-attestation-cli/CMakeLists.txt`
   - Make the module include unconditional before `project()`.
   - Keep the resolver call inside the Darwin guard.
   - Add one unconditional validator call immediately after `project()`.
   - Do not change the literal project line, pins, SDK nesting, or Linux
     behavior.
4. `sol/release/tests/test_apple_cmake.py`
   - Add production-prefix, real-configure, trace, nesting, successive-run,
     cache-absence, independent-failure, ordering, and unavoidable-write
     coverage described in D4 and the test inventory.
   - Relocate rather than delete the existing processor assertions.
   - Preserve existing resolver, ExternalProject, fmt, and pre-project
     structural assertions.
5. `sol/release/tests/test_driver.py`
   - Add the AC4 architecture-validation failure table through the existing
     release failure/retained-quartet helper pattern.
   - Do not add a production failure-injection flag or a transaction mode.
6. `sol/release/tests/test_baseline_stability.py`
   - Add D5's baseline extraction and comparisons.
7. `sol/release/README.md`
   - Apply D6's exact prerequisite and proof-boundary text.
8. `sol/notes/apple-arch-gate-design.md`
   - Retain this decision record as the implementation/audit authority.

`sol/release/targets.toml`, `TARGET_IDS`, `authority.py`, `apple.py`,
`macho.py`, `manifest.py`, `set_validator.py`, all dependency pins/notices,
and both literal project-version lines must not change. Linux must remain an
inert fast return, and no validation-success state may be stored in
`CMakeCache.txt`.

## Risks and settled constraints

* A GLOBAL property is shared by nested directories but reset between CMake
  processes. Tests must distinguish authored call sites from performed
  validation.
* `CMAKE_PROJECT_INCLUDE` runs for every nested `project()`; fixture records
  are boundary observations, never the validation count.
* Semicolon-separated architecture values are CMake lists. Diagnostics and
  tests must preserve the full quoted value while using `list(LENGTH)` for
  cardinality.
* Setting `CMAKE_HOST_SYSTEM_NAME` on Linux is only a forcing fixture. It is
  not evidence that Darwin populated any field.
* Post-project fatal errors cannot leave a pristine build directory.
* No hard contradiction was found with the codebase or the settled calls.
