# nvattest macOS spdlog/fmt header-consumer boundary design

**Authority.** This record is the implementation authority for the pinned
fmt/spdlog public-header consumer boundary researched in
`sol/notes/header-consumer-boundary-prep.md`. It classifies only the pinned
fmt 10.2.1 and spdlog 1.14.1 include roots as system headers for the four
first-party consumers, restores installed `nvat.h` to ordinary classification
for `nvattest`, validates the three measured pinned identities, and proves the
boundary at configured-command and compiler seams.

This design accepts the resolutions in the task as decisions. In particular,
prep Q6 proved that the literal full-production CMake 3.11 acceptance wording
is unsatisfiable: both production modes stop at
`nv-attestation-cli/CMakeLists.txt:28` because CMake 3.11 has no
`FetchContent_MakeAvailable`. Raising the declared minimum or making the
production acquisition path truly 3.11-compatible is outside scope. The real
3.11 gate below therefore proves only the extracted classification mechanism.

## D1 — One shared, complete private-include boundary helper

Add `nv-attestation-sdk-cpp/cmake/nvat_header_consumer_boundary.cmake`, using
the established `include_guard(GLOBAL)` module form shown by
`nvat_apple_sdk.cmake:1-3` and `nvat_locate_installed.cmake:1,24`.

Its single public function is exactly:

```cmake
nvat_target_include_pinned_logging_headers(
  <target>
  ORDINARY
    <ordinary-root>...
)
```

The implementation function is named
`nvat_target_include_pinned_logging_headers`; it uses
`cmake_parse_arguments` to require the `ORDINARY` keyword, at least one
ordinary root, no unknown arguments, and an existing target. It performs, in
order:

1. resolve and validate the pinned-boundary registry from D2;
2. canonicalize every pinned and ordinary root and reject equality or an
   ordinary root nested within a pinned root;
3. call `target_include_directories(<target> PRIVATE ...)` once for the
   ordinary roots;
4. call `target_include_directories(<target> SYSTEM PRIVATE ...)` once for
   exactly `${spdlog_SOURCE_DIR}/include` and `${fmt_SOURCE_DIR}/include`.

The helper fully replaces each current mixed private call, so a consumer cannot
adopt validation without classification or classification without validation.
It never accepts caller-supplied system roots. That closed signature makes the
two production-controlled pinned roots the only possible system output.

`fmt_SOURCE_DIR` and `spdlog_SOURCE_DIR` remain directory-scoped FetchContent
variables. CMake functions inherit the caller's visible variable scope, so
the helper reads their values at the call, after the installed branch has
populated them or after the embedded SDK has made them available
(`nv-attestation-cli/CMakeLists.txt:53-105`; prep Q1). The module must not
capture either variable when included, because the CLI includes helpers before
population.

The containment algorithm is strict:

* an absolute plain entry is canonicalized directly;
* a relative plain entry such as `src` is made absolute against the caller's
  `CMAKE_CURRENT_SOURCE_DIR`, then canonicalized;
* the one supported generator expression form,
  `$<BUILD_INTERFACE:<path>>`, is parsed, its payload is resolved using the
  same absolute/relative rule, and the original expression is retained for
  the eventual include call;
* an empty entry, nonexistent path, malformed expression, or any other
  generator expression is fatal rather than silently excluded from AC1;
* each ordinary root is compared against both canonical pinned roots.
  Equality and ordinary-within-pinned fail. A broader ordinary build root may
  contain FetchContent's `_deps` roots: classification attaches to exact
  compiler include roots, and the real production build places both pinned
  trees beneath `${CMAKE_CURRENT_BINARY_DIR}`.

The current four sites supply only existing source directories, existing
build directories, relative source directories, and the one supported
`BUILD_INTERFACE` form (prep appendix). No
`INSTALL_INTERFACE` entry enters the helper.

The SDK's current PUBLIC section remains a separate, unchanged ordinary call:

```cmake
target_include_directories(nvat
  PUBLIC
    $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>
    $<BUILD_INTERFACE:${CMAKE_CURRENT_BINARY_DIR}/include>
)
nvat_target_include_pinned_logging_headers(
  nvat
  ORDINARY
    src
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    ${regorus_SOURCE_DIR}/bindings/ffi
)
```

The helper uses only `PRIVATE` and `SYSTEM PRIVATE`; neither pinned root enters
`PUBLIC` or `INTERFACE`, so system classification cannot propagate from
`nvat` to its consumers. The installed public include remains represented by
the existing `INSTALL_INTERFACE`, not by this helper.

The other exact resulting call sites are:

```cmake
# nv-attestation-cli/CMakeLists.txt
nvat_target_include_pinned_logging_headers(
  nvattest
  ORDINARY
    ${CMAKE_CURRENT_SOURCE_DIR}/src
    ${CMAKE_CURRENT_BINARY_DIR}
)

# nv-attestation-cli/tests/CMakeLists.txt
nvat_target_include_pinned_logging_headers(
  nv-attestation-cli-tests
  ORDINARY
    ${CMAKE_CURRENT_SOURCE_DIR}/../src
)

# nv-attestation-sdk-cpp/unit-tests/CMakeLists.txt
nvat_target_include_pinned_logging_headers(
  nv-attestation-unit-tests
  ORDINARY
    ${CMAKE_CURRENT_SOURCE_DIR}/../include
)
```

All four files explicitly include the helper. The SDK root and CLI root use a
direct path adjacent to their existing early helper idiom:

* SDK:
  `include("${CMAKE_CURRENT_LIST_DIR}/cmake/nvat_header_consumer_boundary.cmake")`;
* CLI:
  `include("${CMAKE_CURRENT_LIST_DIR}/../nv-attestation-sdk-cpp/cmake/nvat_header_consumer_boundary.cmake")`,
  next to its line-2 Apple helper include;
* CLI tests use their existing module path established at
  `nv-attestation-cli/tests/CMakeLists.txt:4`, then
  `include(nvat_header_consumer_boundary)`;
* SDK unit tests use their existing module path established at
  `nv-attestation-sdk-cpp/unit-tests/CMakeLists.txt:7-10`, then
  `include(nvat_header_consumer_boundary)`.

The global include guard makes repeated inclusion from the CLI, SDK, and both
test subdirectories idempotent. Each call still evaluates caller-scoped
FetchContent variables.

Rejected alternatives:

* Four pairs of raw ordinary/SYSTEM calls would duplicate policy and permit
  partial adoption.
* A helper that accepts arbitrary system roots would weaken the closed pinned
  set.
* Keeping the SDK PUBLIC and PRIVATE clauses in one call would prevent the
  helper from fully owning the private split.
* Silently skipping generator expressions or relative paths would make AC1
  incomplete.
* Classifying pinned roots `PUBLIC` would leak the boundary to downstream
  consumers.

## D2 — One production truth source and fail-closed pinned validation

Inside the new helper module, define one sentinel-delimited registry:

```cmake
# NVAT_PINNED_HEADER_BOUNDARIES_BEGIN
set(_NVAT_PINNED_HEADER_BOUNDARIES
  "fmt_SOURCE_DIR|fmt 10.2.1|fmt/core.h|#define FMT_VERSION 100201"
  "spdlog_SOURCE_DIR|spdlog 1.14.1|spdlog/version.h|#define SPDLOG_VER_MAJOR 1"
  "spdlog_SOURCE_DIR|spdlog 1.14.1|spdlog/version.h|#define SPDLOG_VER_MINOR 14"
  "spdlog_SOURCE_DIR|spdlog 1.14.1|spdlog/version.h|#define SPDLOG_VER_PATCH 1"
  "spdlog_SOURCE_DIR|spdlog 1.14.1|spdlog/fmt/bundled/core.h|#define FMT_VERSION 100201"
)
# NVAT_PINNED_HEADER_BOUNDARIES_END
```

This is the sole declaration of boundary root variables, pins, relative
headers, and identity text. Each record has exactly four pipe-delimited fields
and exactly one identity line; any other field count is fatal. The
implementation dereferences the named root variable at function-call time,
appends `include`, and checks:

1. the root variable is defined and nonempty;
2. its `<source-root>/include` directory exists;
3. the named relative public header exists beneath that include root;
4. the file contains every exact identity line recorded for the pin.

The same spdlog root intentionally has two records. Prep Q2 measured
`spdlog/version.h` as the spdlog 1.14.1 identity and
`spdlog/fmt/bundled/core.h` as fmt 10.2.1. The bundled identity is required
because first-party TUs link spdlog through `$<TARGET_FILE:spdlog>` rather than
receiving its usage requirements, so `SPDLOG_FMT_EXTERNAL` is absent and
`spdlog/fmt/fmt.h` selects bundled fmt (prep Q2;
`nv-attestation-sdk-cpp/CMakeLists.txt:478-495`).

The exact failure diagnostics are:

* missing/empty source variable:
  `"<target> pinned-header boundary failed: expected populated <pin> source variable <variable>; verify the pinned <pin> acquisition"`;
* absent include root:
  `"<target> pinned-header boundary failed: expected <pin> include root '<root>/include'; verify the pinned <pin> target layout"`;
* absent boundary header:
  `"<target> pinned-header boundary failed: expected <pin> public header '<relative>' under '<root>/include'; verify the pinned <pin> target layout"`;
* identity mismatch:
  `"<target> pinned-header boundary failed: expected '<relative>' to identify <pin>; verify the pinned <pin> public-header layout"`;
* ordinary/pinned overlap:
  `"<target> pinned-header boundary failed: ordinary root '<ordinary>' overlaps pinned <pin> root '<pinned>'; only the pinned fmt/spdlog roots may be SYSTEM"`.

This follows the target/pin/failure/recovery shape of
`nvat_exempt_compiled_third_party`
(`nv-attestation-sdk-cpp/CMakeLists.txt:113-121`) while making each seam
distinguishable.

Every helper call validates before issuing either include call. In embedded
mode, the SDK's `nvat` call runs after both FetchContent populations and the
CLI/test calls run after the SDK returns
(`nv-attestation-cli/CMakeLists.txt:83-105`). In installed mode, the CLI call
runs after both explicit `FetchContent_Populate` blocks (`:54-82`). Standalone
test calls run after their own population blocks
(`nv-attestation-cli/tests/CMakeLists.txt:38-59`;
`nv-attestation-sdk-cpp/unit-tests/CMakeLists.txt:97-118`). Therefore an
invalid exact boundary stops configure before a compile command is accepted.

Tests extract the text strictly between the two sentinels, require exactly one
block, reject every record whose field count is not four, require both root
variables to be represented, and derive the complete record set from the
block. Every derived record's header and identity is exercised. Tests do not declare
`fmt/core.h`, `spdlog/version.h`, bundled fmt, or either pin independently.
The extracted block is also inserted verbatim into the reduced D5 fixture.

Rejected alternatives:

* A Python boundary list would create a second truth source.
* Checking only directory existence would accept a wrong populated tag or a
  changed public layout.
* Checking only external fmt would miss the headers first-party TUs actually
  compile through spdlog.
* Running validation once near FetchContent would not prove that every
  consumer adopted the same split.

## D3 — Installed-only `NO_SYSTEM_FROM_IMPORTED`

Set:

```cmake
set_property(TARGET nvattest PROPERTY NO_SYSTEM_FROM_IMPORTED ON)
```

inside `if(USE_SYSTEM_NVAT)`, immediately after
`nvat_locate_installed()` creates imported `nvat::nvat` and before the branch
continues with header population (`nv-attestation-cli/CMakeLists.txt:54-82`).
This is installed-only.

Prep Q3 measured that SYSTEM wins an ordinary/SYSTEM collision in either
order, so adding a direct ordinary `NVAT_INCLUDE_DIR` cannot restore the
installed first-party header. It also measured that
`NO_SYSTEM_FROM_IMPORTED` changes the installed `nvat::nvat` interface from
`-isystem` to `-I`, while the current FetchContent CLI11/json aliases remain
`-I`.

The property is target-wide, not dependency-specific. Prep Q3 separately
proved that if CLI11 or json becomes an actual imported target, its interface
root would also be de-systemized. Scoping the property to
`USE_SYSTEM_NVAT=ON` avoids exposing embedded mode to that future collateral
and makes the reason for the property adjacent to the imported nvat creation.
Installed mode retains the known future risk; command tests must inventory all
linked interface roots so such an acquisition change is visible.

Rejected alternatives:

* An unconditional property has no benefit in embedded mode and widens future
  imported-dependency collateral.
* An extra ordinary include cannot beat the imported SYSTEM classification
  (prep Q3).
* `IMPORTED_NO_SYSTEM`, `SYSTEM`, or mutation of `nvat::nvat` would alter the
  producer/imported target rather than the one consumer that owns the
  first-party classification.

## D4 — All four first-party consumer sites adopt the same split

Apply D1 to `nvat`, `nvattest`, `nv-attestation-cli-tests`, and
`nv-attestation-unit-tests`. Prep Q1 establishes the two production consumers;
its appendix records the two test consumers and proves `make ci` reaches both
through `BUILD_TESTING=ON` (`Makefile:41-54`).

The two test targets are genuine first-party TUs consuming the same pinned
roots. Leaving them ordinary would preserve a latent AppleClang warnings-as-
errors failure whenever macOS CI enables tests. Their inclusion is therefore
part of the product boundary, even though AC2/AC3 effective production-command
assertions remain scoped to `nvat` and `nvattest`.

No other dependency root changes classification. Existing ordinary test roots
and other dependency usage requirements remain as they are.

Rejected alternatives:

* Updating only production targets would leave identical headers classified
  differently in first-party test compilation.
* Broadly converting all third-party roots would exceed the measured problem
  and obscure ownership.

## D5 — Dedicated test topology and extracted real-3.11 fixture

Create `sol/release/tests/test_header_consumer_boundary.py`. Do not overload
`test_warning_policy.py`: compiled-target warning ownership and public-header
consumer classification are related but independent boundaries with different
fixtures, failure seams, and acceptance criteria.

Extend `sol/release/tests/cmake_support.py` with:

* a reusable primitive that creates offline CLI11/json stubs with observable
  interface include directories;
* `installed_header_fixture_prepare(state)`, which
  creates fake installed `nvat.h`/`libnvat.so`, offline populated fmt/spdlog
  header trees matching the extracted production registry, and arguments for
  `USE_SYSTEM_NVAT=ON`;
* an embedded header fixture wrapper that reuses
  `warning_fixture_prepare` but supplies observable CLI11/json interface roots
  and exact boundary headers.

The support module contains no boundary filenames, pins, expected
classifications, or assertions. The test passes registry-derived data into
the preparers. Keep `production_configure`'s return tuple and arguments
unchanged and keep `warning_fixture_prepare` behavior unchanged.
`test_apple_cmake.py:1-17` and current warning/driver tests continue importing
those contracts.

In the new test module, express path canonicalization once in
`canonical_include_root(path, command_directory)`. Express the
equal/ordinary-within-pinned relation once in
`ordinary_conflicts_with_pinned(left, right)`.
Every command-level assertion uses those functions; no test implements
ad-hoc string-prefix containment. Production CMake has its one corresponding
implementation inside the D1 helper—language duplication is unavoidable, but
neither production nor tests duplicate it internally.

The module has one production-configure class fixture per mode and derives
include vectors from `compile_commands.json`. It asserts:

* for every command owned by `nvat` and embedded/installed `nvattest`, the two
  registry-derived pinned roots occur exactly once and are system-classified;
* all direct ordinary roots are exactly the call-site-derived expected roots,
  are `-I`, and have no overlap with pinned roots;
* installed `NVAT_INCLUDE_DIR` is `-I`;
* CLI11/json roots remain `-I` in both current modes;
* no unlisted root flips classification;
* both test call sites use the same helper and contain no raw pinned include
  roots outside it.

The reduced classification fixture extracts, never retypes:

1. the helper function and sentinel registry from the new module;
2. the installed-only `NO_SYSTEM_FROM_IMPORTED` statement from the production
   CLI;
3. one complete production helper call using representative ordinary roots.

It supplies modeled real/imported targets and minimal files, configures once
under the current release CMake unconditionally, and applies the same include
vector/overlap assertions as the optional 3.11 arm.

The 3.11 discovery order is:

1. explicit test-only `NVAT_TEST_CMAKE_311` path, if set;
2. PATH candidates `cmake3.11`, `cmake-3.11`, then `cmake`, accepting only a
   `--version` result whose parsed version is `3.11.x`.

An invalid explicit override fails with a precise test error; it never alters
product behavior and cannot make an assertion pass. If no candidate identifies
as 3.11, the 3.11 test calls `skipTest` with:
`"real CMake 3.11 not available; set NVAT_TEST_CMAKE_311 to a 3.11 executable"`.
No download occurs and no binary is committed.

When present, the old engine is invoked with a positional source path from the
build directory, not unsupported `-S/-B` (prep Q6). The test requires:

* `<candidate> --version` parses as 3.11.x;
* configure output contains a fixture-emitted `ENGINE=3.11.x`;
* `CMakeCache.txt` exists;
* both embedded-shaped and installed-shaped reduced variants generate
  commands satisfying the shared assertions.

The current-CMake arm gives every-run assertion coverage. The optional arm
proves the same extracted statements on a real 3.11 engine when provisioned.
The implementation commit body and this record must state that the 3.11 arm
skips when unavailable.

Prep Q7 measured `make rail-test` at 6.07 seconds and the current warning suite
at 1.36 seconds. Two additional modern offline configures, compiler probes,
and small failure configures are estimated to add 1.5–2.5 seconds; a present
3.11 binary adds approximately 0.5–1.0 second. A projected 7.5–9.5 second
rail-test remains acceptable. If implementation exceeds 12 seconds, share
configured class fixtures before considering any reduction in assertions.

Rejected alternatives:

* Extending `test_warning_policy.py` would conflate compiled dependency policy
  with header consumer policy.
* Retyping classification statements into the legacy fixture violates R2.
* Downloading CMake or committing a Linux-only binary violates R3.
* Failing when 3.11 is absent would break routine `make rail-test`; skipping
  the modern arm would leave assertions uncovered.
* Shadowing `CMAKE_VERSION` does not prove an old engine ran (prep Q5).

## D6 — AC6 compiler-observed behavior through production warning arguments

Add three compiler proofs to the new module. Select an actual configured
first-party compile command, preserve its warning options and all other
compiler arguments except source/output/include-root substitutions needed for
the controlled file, and require `-Werror`. Before executing any proof, assert
that `-Wsystem-headers` is absent from the selected production vector; do not
assume it from source text.

The three exact proofs are:

1. a header containing a non-void inline function with no return, under a
   registry-derived `-isystem` root, compiles successfully with no fatal
   diagnostic;
2. the byte-identical header, changing only its classification to `-I`, fails
   with the same first-party warning vector;
3. a `__attribute__((deprecated))` declaration in a system-classified header
   fails when the first-party TU calls it, proving use-site diagnostics remain
   fatal.

The tests assert return status and nonempty diagnostic where a diagnostic is
expected, not GCC-specific prose. Prep Q4 measured all three behaviors with
GCC 15.3.0 and the unchanged nvat warning tail. The implementation must use
the configured compiler recorded in the selected command, allowing the same
proof to run with Clang when available.

Rejected alternatives:

* Hand-authored warning flags could drift from production.
* Adding `-Wsystem-headers` would negate the boundary being proved.
* Exact diagnostic text would be compiler-specific.
* A deprecated declaration-only probe would miss the required use-site seam.

## D7 — AC9 separates validator failure from release transaction propagation

In `test_header_consumer_boundary.py`, add
`test_invalid_exact_pinned_boundary_fails_at_production_cmake_seam`. It uses
the installed production configure fixture, removes or corrupts one exact
registry-derived identity at a time, and requires configure to fail with the
corresponding D2 `FATAL_ERROR`. This is the validator's own failure, not a
Python marker, mocked result, or product injection hook. Cases cover missing
root, missing public header, identity mismatch, and ordinary/pinned overlap;
case names and expectations derive from the production registry.

Separately extend
`test_driver.py::test_macos_build_failures_use_driver_build_seam_and_never_publish`
using the existing `assert_release_failure_preserves_quartet` contract
(`test_driver.py:275-317`) and spdlog failure pattern (`:655-729`). Add a
`"pinned header boundary configure failed"` row. Its patched `_build` side
effect creates the invalid production fixture, then invokes the real
`driver._run` with the real CMake configure command. The nonzero CMake process
is converted by `driver._run` to `driver.ReleaseError`
(`release_rail/driver.py:27-31`) and propagates through the real
`driver.release` transaction. The retained and initially absent quartet cases
remain supplied by the shared helper.

The driver test requires the propagated exception chain/output to contain the
seam-specific D2 diagnostic before transaction assertions. It does not repeat
the full validator matrix; that belongs to the new module. No product-only
failure flag, environment hook, source marker, or mock success/failure result
connects the two proofs.

Rejected alternatives:

* A Python-raised marker would not prove CMake rejected the boundary.
* Putting a test injection option in product CMake would expand the product
  interface.
* Repeating quartet transaction assertions in the new module would duplicate
  the existing driver seam.

## D8 — Baseline rebase and invariant preservation

Rebase `test_baseline_stability.py::BASELINE` from
`46c10e4808965d6c065d62dece0071a8ff1624da` to
`22065d840cbcc8ff457ac224da0df299a4e23b3f`.

Retain unchanged:

* complete `targets.toml` byte identity
  (`test_baseline_stability.py:121-122`);
* target ID tuple comparison (`:124-130`);
* dependency input inventory, per-path coordinate multisets, and global
  coordinate multiset (`:137-158`);
* SDK/CLI project name and version comparison (`:160-165`);
* exact `corrosion_import_crate` tokens (`:167-171`);
* release version derived from the baseline SDK version (`:174-179`).

Do not add a parallel coordinate comparison for the four consumer files:
the existing input-inventory and per-path/global coordinate machinery already
covers them without byte-comparing CMakeLists. Add exactly two targeted
assertions: the new helper module contains no `FetchContent_Declare`,
`ExternalProject_Add`, repository, tag, URL, or hash token; and the compiled-
warning exemption function body plus its two call sites remain byte-identical
to the rebased baseline, so this task cannot change
`nvat_exempt_compiled_third_party`.

Do not weaken `test_targets_authority_is_byte_identical` or exclude modified
CMakeLists from dependency discovery.

Rejected alternatives:

* Removing modified files from baseline comparison would hide coordinate
  drift.
* Rebaselining to the implementation commit would bless the changes under
  test.
* Comparing only global coordinates would allow a dependency to migrate
  between owners.

## D9 — Minimal VPE documentation update

Change only the macOS warning phrase in
`sol/release/README.md:132-137`.

Before:

> The macOS operator must verify the dylib chain above, verbose
> fmt/spdlog/nvat/nvattest warning flags, all four external projects' effective
> SDK/architecture/floor inputs, the genuine Apple toolchain evidence, and the
> final Mach-O architecture and deployment floor.

After:

> The macOS operator must verify the dylib chain above, verbose
> fmt/spdlog/nvat/nvattest warning flags, including ordinary
> first-party/generated/installed roots and system-classified pinned fmt/spdlog
> roots, all four external projects' effective SDK/architecture/floor inputs,
> the genuine Apple toolchain evidence, and the final Mach-O architecture and
> deployment floor.

This preserves the exact substring matched by
`test_warning_policy.py::test_readme_names_all_derived_compile_owners_for_vpe`:
the regex at `:360-364` still captures
`fmt/spdlog/nvat/nvattest` between `verbose` and `warning flags`, and its
derived owner-set equality remains unchanged. Extend the new header-boundary
test to require the added ordinary/system classification words; do not alter
the existing owner parser.

Rejected alternatives:

* Replacing the owner phrase would break the derived warning-owner test.
* Claiming native AppleClang proof occurred would contradict prep Q4.
* Expanding the section into implementation detail would obscure the VPE
  obligation.

## D10 — Acceptance criteria and test inventory

| acceptance criterion | test inventory | closure |
| --- | --- | --- |
| AC1 — all four first-party consumers use one closed split and only exact pinned fmt/spdlog roots become system-classified | `test_header_consumer_boundary.py::test_helper_registry_and_all_four_calls_are_closed`; embedded/installed vector tests | Extracts the sole five-record registry, inventories all four call sites, applies one canonical conflict relation, and rejects extra/missing/conflicting roots. |
| AC2 — embedded `nvat` and `nvattest` preserve every first-party/generated root as `-I` and classify both pins as system | `::test_embedded_production_include_vectors` | Inspects real offline production commands for both compile owners. |
| AC3 — installed `nvattest` has pinned roots system, installed nvat/CLI11/json ordinary, and no embedded or ambient contamination | `::test_installed_production_include_vectors_are_isolated` | Requires no embedded build directory, no SDK/nvat compile command, exactly six CLI commands, and every include root beneath the CLI source or isolated fixture. |
| AC4 — the extracted classification mechanism works at the declared floor | `::test_extracted_boundary_fixture_with_release_cmake`; `::test_extracted_boundary_fixture_with_real_cmake_311_when_available` | The same extracted statements/assertions always run under release CMake; real 3.11 is no-network and explicitly skips when absent. It is not represented as a full production configure. |
| AC5 — every measured pinned public identity fails closed from one truth source | `::test_helper_registry_and_all_four_calls_are_closed`; `::test_invalid_exact_pinned_boundary_fails_at_production_cmake_seam` | Rejects non-four-field records, requires both root variables, and corrupts every record's declared identity in turn. |
| AC6 — system classification suppresses header-origin warnings but not ordinary headers or use-site deprecations | `::test_compiler_observes_header_boundary_and_use_site` | Runs all three proofs through a configured first-party command and asserts `-Wsystem-headers` is absent. |
| AC7 — warning vectors and demotion policy are preserved exactly | unchanged `test_warning_policy.py::test_modern_effective_warning_commands_are_exact_and_undemoted` plus its `EXPECTED_FIRST_PARTY_WARNINGS`/`ACCEPTED_DEMOTIONS` | Continues to cover `nvat` and `nvattest`, exact order/loss, `-w`, `-Wno-error*`, and any newly added `-Wno-*`; no parallel vector truth source is added. |
| AC8 — authority, coordinates, target IDs, versions, compiled-warning exemptions, and hard boundaries do not drift | retained `test_baseline_stability.py` comparisons plus the two D8 targeted assertions | Rebases to the authorized baseline without duplicating dependency-coordinate machinery or touching `targets.toml`. |
| AC9 — invalid boundary fails at production CMake and can never publish a quartet | production-seam identity test; extended `test_driver.py::test_macos_build_failures_use_driver_build_seam_and_never_publish` | Separates validator correctness from real `driver._run` subprocess-to-`ReleaseError` transaction propagation. |
| AC10 — focused suites, shellcheck/rail gate, real command spot checks, and full C++ CI pass | required implementation validation sequence: focused unittest modules, `make rail-test`, both-mode compile-command capture, and one `make ci` | Records every exit status and new rail wall-clock against prep Q7's 6.07 seconds; `make ci` exercises both test consumers. |
| AC11 — documentation records only observed facts and native obligations | existing warning-owner README parser; `::test_readme_records_header_classification_for_vpe`; design evidence/fidelity sections | Preserves the derived owner phrase, names the ordinary/system boundary, and leaves unobserved AppleClang proof VPE-owned. |

## Hard boundaries

* Add no `-w`, new `-Wno-*`, `-Wno-error`, `-Wno-error=*`, pragma, or global
  warning-policy change.
* Do not touch `nvat_exempt_compiled_third_party`, its fmt/spdlog calls, or
  their ordering (`nv-attestation-sdk-cpp/CMakeLists.txt:113-145`).
* Change no dependency coordinate, `sol/release/targets.toml`, or
  `sol/ci/Containerfile`.
* Use no `SYSTEM` target property, `IMPORTED_NO_SYSTEM`, or
  `add_subdirectory(... SYSTEM)`.
* Only `${fmt_SOURCE_DIR}/include` and `${spdlog_SOURCE_DIR}/include` become
  system-classified.
* Do not change the aspirational CMake minimum or production acquisition
  compatibility.
* Commit no CMake 3.11 binary and add no rail-test network access.
* Add no product-only failure-injection hook.

## Risks and open questions

1. **Installed target-wide collateral.** `NO_SYSTEM_FROM_IMPORTED` will
   de-systemize every future imported dependency linked to installed
   `nvattest`, not just nvat. Installed command inventory makes that drift
   visible, but CMake provides no dependency-specific equivalent (prep Q3).
2. **Pinned layout churn.** A legitimate fmt/spdlog pin upgrade will fail at
   the registry identity until the production truth source is intentionally
   updated. This is desired fail-closed behavior, but the pin and registry must
   change in one reviewed unit.
3. **CMake list parsing.** The implementation must treat `|` as the sole
   registry delimiter and preserve each quoted record as one list element on
   CMake 3.11. The extraction test rejects every record whose field count is
   not four and exercises the complete set declared by the block.
4. **Compiler argument rewriting.** AC6 must change only controlled
   source/output/include arguments. Response files or a future non-GNU command
   form may require parser extension; failure must be explicit rather than
   falling back to a hand-built command.
5. **3.11 availability.** Routine rail runs may skip the real-3.11 arm.
   Provisioned release/VPE environments should set `NVAT_TEST_CMAKE_311` and
   record the non-skipped result, but the mandatory modern fixture remains the
   every-run regression gate.
6. **Standalone test modes.** Both test CMakeLists can run standalone and have
   additional imported dependencies. D1 changes only their direct pinned roots;
   it must not apply `NO_SYSTEM_FROM_IMPORTED` to either test target.

No user choice remains open for implementation. The risks above are
constraints to test, not reasons to broaden scope.

## File-by-file implementation plan, in execution order

1. **`nv-attestation-sdk-cpp/cmake/nvat_header_consumer_boundary.cmake`
   (new).** Add the guarded helper, sole sentinel registry, exact identity and
   containment validation, and closed ordinary/SYSTEM calls.
2. **`nv-attestation-sdk-cpp/CMakeLists.txt`.** Include the helper; split the
   untouched PUBLIC include call from the helper-owned private call. Do not
   alter dependency acquisition, warning exemptions, links, or coordinates.
3. **`nv-attestation-cli/CMakeLists.txt`.** Include the helper; set
   `NO_SYSTEM_FROM_IMPORTED` only after installed nvat creation; replace the
   mixed private include call with the exact D1 helper call.
4. **`nv-attestation-cli/tests/CMakeLists.txt`.** Include the helper through
   the existing module path and replace its pinned/ordinary mixed call.
5. **`nv-attestation-sdk-cpp/unit-tests/CMakeLists.txt`.** Include the helper
   through the existing module path and replace its pinned/ordinary mixed call.
6. **`sol/release/tests/cmake_support.py`.** Add assertion-free observable
   interface-stub primitives and installed/embedded header fixture preparers;
   preserve existing public contracts.
7. **`sol/release/tests/test_header_consumer_boundary.py` (new).** Add registry
   extraction, single canonicalization/overlap utilities, real production
   include-vector assertions, all-four-site adoption, modern and optional real
   3.11 reduced fixtures, compiler proofs, seam-specific validator failures,
   and README classification assertion.
8. **`sol/release/tests/test_driver.py`.** Add the actual invalid configure
   subprocess propagation row through `driver._run` and reuse quartet
   preservation assertions.
9. **`sol/release/tests/test_baseline_stability.py`.** Rebase `BASELINE`,
   retain every current authority/coordinate/version comparison unchanged,
   and add only the two D8 targeted assertions.
10. **`sol/release/README.md`.** Make only the D9 macOS VPE wording change,
    preserving the warning-owner phrase parsed by the existing test.
11. **Implementation commit body.** State that full production CMake 3.11 is
    currently impossible at `FetchContent_MakeAvailable`, the reduced fixture
    loses full-tree fidelity, and the real-3.11 arm skips unless an executable
    is provisioned.

## What this lode can and cannot prove

This Linux lode can prove:

* all four production source sites use the one helper and registry;
* real offline embedded and installed production configurations emit the
  intended GNU include classifications;
* installed nvat becomes ordinary without current CLI11/json collateral;
* the exact pinned validator fails at its own CMake seam;
* GCC observes system-header suppression, ordinary-header fatality, and fatal
  deprecation at the first-party use site with production warning arguments;
* the release transaction preserves or withholds the quartet after the real
  configure subprocess fails;
* the extracted reduced fixture works under release CMake and, when
  provisioned, under an actual CMake 3.11 engine.

It cannot prove native AppleClang command emission or diagnostics. Prep Q4
measured that no `clang++` exists here. Native arm64 macOS/AppleClang evidence
remains VPE-owned under scope §8 and the README obligation.

The real-3.11 fixture's fidelity limit is explicit: it executes the exact
extracted classification helper/call/property statements with modeled targets
and roots, but it does not execute either production CMakeLists as a whole,
FetchContent, Corrosion, regorus, ExternalProject, Apple helpers, production
target ordering, or either actual production mode. Prep Q6 proves those trees
cannot reach the boundary on CMake 3.11 today. A passing reduced fixture must
never be reported as a full production 3.11 configure.

## Implementation evidence

The first real embedded configure exposed that the required ordinary
`${CMAKE_CURRENT_BINARY_DIR}` contains FetchContent's `_deps` directories.
The originally designed symmetric containment rejection therefore failed
before generation. D1 and the implementation were corrected to reject equality
and ordinary-within-pinned only; a broader ordinary root does not change the
classification attached to the exact pinned compiler roots.

After that correction, the requested real embedded configure generated these
actual commands:

```text
/usr/bin/c++  -I/home/jer/.hopper/worktrees/dvid4m3p/nv-attestation-cli/src -I/home/jer/.hopper/worktrees/dvid4m3p/build/boundary-embedded -I/home/jer/.hopper/worktrees/dvid4m3p/build/boundary-embedded/nv-attestation-sdk-build/include -I/home/jer/.hopper/worktrees/dvid4m3p/build/boundary-embedded/_deps/json-src/include -isystem /home/jer/.hopper/worktrees/dvid4m3p/build/boundary-embedded/_deps/fmt-src/include -isystem /home/jer/.hopper/worktrees/dvid4m3p/build/boundary-embedded/_deps/spdlog-src/include -isystem /home/jer/.hopper/worktrees/dvid4m3p/build/boundary-embedded/_deps/cli11-src/include -O3 -DNDEBUG -std=gnu++14 -Werror -o CMakeFiles/nvattest.dir/src/main.cpp.o -c /home/jer/.hopper/worktrees/dvid4m3p/nv-attestation-cli/src/main.cpp

/usr/bin/c++ -DXMLSEC_CRYPTO_OPENSSL=1 -DXMLSEC_NO_CRYPTO_DYNAMIC_LOADING=1 -DXMLSEC_NO_FTP=1 -DXMLSEC_NO_GOST2012=1 -DXMLSEC_NO_GOST=1 -DXMLSEC_NO_MD5=1 -DXMLSEC_NO_SIZE_T -DXMLSEC_NO_XSLT=1 -D__XMLSEC_FUNCTION__=__func__ -Dnvat_EXPORTS -I/home/jer/.hopper/worktrees/dvid4m3p/build/boundary-embedded/nv-attestation-sdk-build/include -I/home/jer/.hopper/worktrees/dvid4m3p/nv-attestation-sdk-cpp/src -I/home/jer/.hopper/worktrees/dvid4m3p/nv-attestation-sdk-cpp/include -I/home/jer/.hopper/worktrees/dvid4m3p/build/boundary-embedded/_deps/regorus-src/bindings/ffi -I/home/jer/.hopper/worktrees/dvid4m3p/build/boundary-embedded/_deps/jwt-cpp-src/include -I/home/jer/.hopper/worktrees/dvid4m3p/build/boundary-embedded/_deps/json-src/include -isystem /home/jer/.hopper/worktrees/dvid4m3p/build/boundary-embedded/_deps/fmt-src/include -isystem /home/jer/.hopper/worktrees/dvid4m3p/build/boundary-embedded/_deps/spdlog-src/include -isystem /home/jer/.hopper/worktrees/dvid4m3p/build/boundary-embedded/xmlsec-install/include/xmlsec1 -isystem /home/jer/.hopper/worktrees/dvid4m3p/build/boundary-embedded/libxml2-install/include/libxml2 -isystem /home/jer/.hopper/worktrees/dvid4m3p/build/boundary-embedded/openssl-install/include -isystem /home/jer/.hopper/worktrees/dvid4m3p/build/boundary-embedded/curl-install/include -O3 -DNDEBUG -std=gnu++14 -fPIC -Wall -Wextra -Wpedantic -pedantic -Wno-unused -Wno-unused-parameter -ffile-prefix-map=/home/jer/.hopper/worktrees/dvid4m3p/nv-attestation-cli/src/= -Wno-c++17-extensions -Werror -o CMakeFiles/nvat.dir/src/nvat.cpp.o -c /home/jer/.hopper/worktrees/dvid4m3p/nv-attestation-sdk-cpp/src/nvat.cpp
```

An isolated installed configure using the real offline-populated fmt, spdlog,
json, and CLI11 source trees generated:

```text
/usr/bin/c++  -I/home/jer/.hopper/worktrees/dvid4m3p/nv-attestation-cli/src -I/home/jer/.hopper/worktrees/dvid4m3p/build/boundary-installed-real -I/home/jer/.hopper/worktrees/dvid4m3p/build/boundary-installed-fixture/installed/include -I/home/jer/.hopper/worktrees/dvid4m3p/build/boundary-embedded/_deps/json-src/include -isystem /home/jer/.hopper/worktrees/dvid4m3p/build/boundary-embedded/_deps/fmt-src/include -isystem /home/jer/.hopper/worktrees/dvid4m3p/build/boundary-embedded/_deps/spdlog-src/include -isystem /home/jer/.hopper/worktrees/dvid4m3p/build/boundary-embedded/_deps/cli11-src/include -O3 -DNDEBUG -std=gnu++14 -Werror -o CMakeFiles/nvattest.dir/src/main.cpp.o -c /home/jer/.hopper/worktrees/dvid4m3p/nv-attestation-cli/src/main.cpp
```

Installed mode intentionally has no `nvat` compile command: it imports the
fake installed library and generated only the six `nvattest` commands. In all
three commands, every first-party source/generated/installed root is `-I` and
both pinned roots are `-isystem`. Real CLI11 independently publishes a system
include; json remains ordinary. Those are other-dependency classifications,
not additions to the helper's closed pinned-root set.

The settled validation observed:

* the warning-policy suite passed all 6 tests unchanged, including the exact
  `nvat`/`nvattest` warning vectors and demotion rejection;
* the header-boundary suite passed all 8 tests; its normal rail invocation
  explicitly skipped only the unavailable-by-default real-3.11 arm;
* Apple CMake passed 14 tests, driver passed 23, and baseline stability passed
  6;
* `make rail-test` passed 120 tests with one explicit optional-3.11 skip plus
  ShellCheck in 8.70 seconds wall clock, versus prep Q7's 6.07 seconds;
* the explicitly provisioned
  `/tmp/nvat-warning-research/cmake-3.11.4-Linux-x86_64/bin/cmake` arm passed
  all 8 header-boundary tests with no skip;
* the one authorized `make ci` invocation built `nvat`, `nvattest`, both
  first-party test consumers, and reported `100% tests passed out of 64`
  (four separately disabled HTTP tests were not run).

These are Linux/GNU observations only. They do not alter the AppleClang/VPE
boundary above.
