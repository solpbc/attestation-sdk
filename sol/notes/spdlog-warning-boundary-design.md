# spdlog compiled third-party warning-policy boundary design

**Authority.** This record is the implementation authority for completing the
compiled third-party warning-policy boundary established by
`sol/notes/spdlog-warning-boundary-prep.md`. It changes only ownership and
proof of warnings-as-errors: first-party `nvat` and `nvattest` retain the
policy, while compiled third-party `fmt` and `spdlog` do not. Dependency
coordinates, build topology, release authority, Apple architecture policy,
ExternalProject wiring, and all other compiler options remain unchanged.

This design is authored on a Linux lode. The lode can prove the real configured
target graph, effective GNU commands, controlled warning behavior, legacy
policy text/order in a source-extracted fixture, and transaction preservation
after reaching a real stub spdlog compile. It cannot prove a native
AppleClang 21 command or execute the complete production tree with CMake 3.11.
Those boundaries remain VPE-owned.

## D1 — One target-local exemption mechanism

Define one small CMake function,
`nvat_exempt_compiled_third_party(<target> <pin>)`, immediately before the fmt
fetch block in `nv-attestation-sdk-cpp/CMakeLists.txt`. It performs exactly
two operations:

1. fail closed when the named compiled target does not exist, using the
   existing diagnostic shape:
   `"<target> warning-policy exemption failed: expected compiled target
   <target> after FetchContent_MakeAvailable; verify the pinned <pin> target
   layout"`;
2. set only that target's `COMPILE_WARNING_AS_ERROR` property to `OFF`.

Replace the inline fmt-only check/property block with a call immediately after
`FetchContent_MakeAvailable(fmt)`, passing target `fmt` and display pin
`fmt 10.2.1`. Add the corresponding call immediately after
`FetchContent_MakeAvailable(spdlog)`, passing target `spdlog` and display pin
`spdlog 1.14.1`. The current fmt wording is preserved verbatim in shape, while
substitution makes fmt and spdlog failures distinguishable.

The call sites are the single parseable truth source for the exempt
compiled-third-party target set. Tests parse the arguments from calls outside
the function definition; no second constant or hardcoded four-target registry
is introduced.

Rejected alternatives:

* Duplicating the fmt block for spdlog would preserve two independent
  implementations and deny tests a single declaration form.
* A new CMake module is disproportionate to a two-operation function used in
  one file.
* A registry, loop, target-discovery framework, global
  `CMAKE_COMPILE_WARNING_AS_ERROR` toggle, or directory-wide suppression would
  obscure adjacency and could relax unrelated targets.
* Header-only aliases are not accepted: absence of the expected compiled
  target remains fatal because the pinned target layout is part of the
  boundary.

## D2 — Preserve the SDK legacy fallback and add CLI ownership

Leave the SDK warning region at
`nv-attestation-sdk-cpp/CMakeLists.txt:368-374` unchanged. In particular,
retain its directory-wide legacy `add_compile_options(-Werror)` guard. That
fallback covers `nvat` and SDK targets created later, including examples and
unit tests when enabled. Converting it to a target-local option on `nvat`
would silently remove legacy warnings-as-errors from those other first-party
targets and is outside this task.

Make the existing ordering dependency explicit and tested:
both `FetchContent_MakeAvailable(fmt)` and
`FetchContent_MakeAvailable(spdlog)` plus their exemption calls must occur
strictly before the SDK legacy `add_compile_options(-Werror)` guard. The test
derives textual positions from the production file and never hardcodes line
numbers. This converts the legacy non-leakage from an undocumented ordering
accident into a fail-closed invariant.

Immediately after the complete `add_executable(nvattest ...)` declaration in
`nv-attestation-cli/CMakeLists.txt`, add the same legacy condition used by the
SDK and apply `-Werror` to `nvattest` with
`target_compile_options(... PRIVATE ...)`. This is an addition of explicit
first-party ownership on CMake below 3.24, where `nvattest` currently lacks
the policy. It is not a relaxation and changes nothing on CMake 3.24 or newer.
Target scope prevents the option from flowing into the SDK subdirectory and
therefore into fmt or spdlog.

Retain both existing `CMAKE_COMPILE_WARNING_AS_ERROR ON` assignments. On
modern CMake they remain the first-party default; D1 supplies the two explicit
exceptions.

Rejected alternatives:

* Moving the SDK fallback before dependency fetches would leak `-Werror` into
  compiled third-party targets on legacy CMake.
* Adding a CLI-directory option before `nvattest` would also be inherited by
  the later SDK subdirectory.
* Replacing the SDK fallback with only `nvat` coverage would weaken examples
  and unit tests.
* Pretending a shadowed `CMAKE_VERSION` is a real 3.11 engine would overstate
  evidence; modern CMake still implements the target property.

## D3 — Derive the configured compile-owner boundary

Add a CMake File API `codemodel-v2` query before a real offline production
configure through the CLI entry point. A target is compile-owning if and only
if at least one of its File API sources has a non-null compile-group
assignment. Target name and target type alone are not inclusion criteria.
This admits the four real compile owners and structurally excludes utilities,
interfaces, and imported targets that own no compile sources.

Classify each compile owner by source location:

* first-party when every compile-owning source resolves beneath either
  production repository source directory (`nv-attestation-cli` or
  `nv-attestation-sdk-cpp`);
* compiled third-party when every compile-owning source resolves beneath one
  of the configure's test-owned FetchContent source directories;
* fail when sources cross classes, resolve outside both roots, or otherwise
  cannot be classified.

Cross-check the derived third-party target set against the target names parsed
from D1's production call sites. Cross-check the derived first-party set
against the compile owners whose effective commands carry warnings-as-errors.
The test requires full set equality, so an added, removed, renamed, duplicated,
mixed-source, or unclassified compile owner fails rather than being silently
omitted.

The Corrosion fixture must model the production shape: its import function
creates an imported STATIC `regorus_ffi` with an imported location and a
separate `cargo-build_regorus_ffi` custom target. It must not substitute an
INTERFACE `regorus_ffi`. Both records therefore appear without compile-group
sources and are excluded by ownership, as are the four ExternalProject utility
targets. INTERFACE targets are expected to appear under current CMake and are
excluded because they own zero compile sources, not by name.

Rejected alternatives:

* A four-name inventory proves only what the test author remembered.
* Filtering utilities, interfaces, Corrosion, or ExternalProject targets by
  name makes stub absence masquerade as correct classification.
* `compile_commands.json` alone does not enumerate zero-compile graph records
  and cannot prove the exclusion rule.

## D4 — Effective commands in modern and legacy regimes

Create `sol/release/tests/test_warning_policy.py` for the warning boundary.
Its modern fixture uses the real CLI production configure, compiled one-source
fmt/spdlog stubs, and the faithful Corrosion shape from D3. It enables
`CMAKE_EXPORT_COMPILE_COMMANDS` and queries the File API in the same configure.

For one representative effective command per derived compile owner, parse
warning-policy options in command order. Define the accepted first-party
warning demotions once as
`{-Wno-unused, -Wno-unused-parameter, -Wno-c++17-extensions}` and reuse that
constant across command inspection. Assertions are:

* `nvat` has the exact baseline sequence
  `-Wall`, `-Wextra`, `-Wpedantic`, `-pedantic`, `-Wno-unused`,
  `-Wno-unused-parameter`, `-Wno-c++17-extensions`, `-Werror`;
* `nvattest` has the exact baseline sequence `-Werror`;
* every first-party command excludes `-w`, `-Wno-error`, every
  `-Wno-error=*`, and every `-Wno-*` option outside the single accepted set;
* fmt and spdlog commands contain no warning-as-error option, including
  `-Werror` and `-Werror=*`;
* commands for every source owned by a target agree on the target's classified
  policy, preventing a representative source from hiding a per-source
  override.

The parser includes `-pedantic` explicitly; it does not rely on the prep
stage's intentionally narrower `-W*` extraction.

The legacy fixture extracts the real policy regions and significant ordering
from the production CMakeLists into a minimal project. It includes modeled
fmt/spdlog targets and calls/exemptions before the verbatim SDK legacy guard,
modeled `nvat` after that guard, and modeled `nvattest` plus its verbatim
target-local CLI guard. A test-controlled legacy branch value selects the
fallback without requiring FetchContent or downloading an old CMake binary.
It asserts first-party `-Werror`, third-party absence of warnings-as-errors,
and strict production ordering.

This fixture proves the production policy text, target/directory ordering,
and legacy fallback ownership. It does not prove execution by a CMake 3.11
engine, nor can it prove the full production tree configures under 3.11. No
committed test downloads CMake or depends on the scratch 3.11.4 artifact.

Rejected alternatives:

* Property/source inspection cannot detect generator behavior, inherited
  options, duplicate options, or command-level demotions.
* Shadowing `CMAKE_VERSION` in the full modern configure is not faithful to
  the old engine's lack of `COMPILE_WARNING_AS_ERROR`.
* Maintaining copied policy text in the fixture would let production and test
  diverge.
* Comparing unordered flag sets would miss ordering and duplicates and would
  weaken the prep baseline's byte/effective-command intent.

## D5 — Compile a controlled warning through real commands

From `compile_commands.json`, select a real source command for each of
`nvat`, `nvattest`, fmt, and spdlog. Replace only the source path with a
test-owned source containing a non-void function with no return, preserve all
other command arguments, and execute from the recorded working directory.

The two first-party commands must return nonzero. The two compiled
third-party commands must return zero while producing a diagnostic. Tests
classify the return status and confirm that diagnostic output is nonempty;
they do not assert GNU-specific phrases such as “all warnings being treated
as errors.” This keeps the gate meaningful across GNU and Clang diagnostics.

Property assertions, D1 parsing, and command inspection are necessary but not
sufficient: only compilation proves the selected compiler interprets the
effective command as warning-versus-error at the source seam.

Rejected alternatives:

* Compiling a hand-authored command would bypass the configured graph.
* Adding a special compiler flag solely for the test would cease to test the
  production effective command.
* Matching exact diagnostic prose would make a policy test compiler-specific.

## D6 — Reach the spdlog compile seam before transaction failure proof

Extend, rather than clone,
`test_driver.py::assert_release_failure_preserves_quartet`
(`sol/release/tests/test_driver.py:268-306`) and the macOS build-failure case
at `:646-684`.

Add one spdlog-specific case whose patched `_build` implementation performs
the following before raising the supplied `driver.ReleaseError`:

1. create the same offline production configure fixture used by the warning
   tests, with the real production CLI/SDK CMakeLists and faithful dependency
   target shapes;
2. make the test-owned spdlog `stub.cpp` emit the unique marker
   `NVAT_TEST_SPDLOG_COMPILE_REACHED` as a compiler diagnostic and then issue
   an unconditional compile error;
3. configure and invoke `cmake --build <build> --target spdlog`, capturing
   output;
4. require a failed build and require the unique marker in captured output;
5. only after both assertions, raise `driver.ReleaseError("spdlog compile
   failed")`.

The injection is gated solely by
`FETCHCONTENT_SOURCE_DIR_SPDLOG` pointing to the temporary test source. There
is no production environment variable, CMake option, hook, or source edit.
Because the marker resides in spdlog's compiled source and is emitted by the
compiler before its deliberate error, observing it proves the configured
build reached the production spdlog target's compile seam. A marker from
configure, a mocked subprocess, or an exception string is insufficient.

The existing quartet helper still runs retained and absent-final-artifact
subcases. When a quartet already exists, transaction overwrite refusal occurs
before `_build`, so the seam callback must remain uncalled and retained bytes
must remain identical. When no quartet exists, the callback must reach the
marker, fail, raise through the `_build` seam, and leave every final quartet
path absent. Extend the helper with an optional post-call observation callback
or returned observation record so this marker condition is asserted without
duplicating its transaction matrix.

The offline configure is approximately subsecond and the one-source spdlog
build should keep this case within a few seconds on the lode. It runs only in
the no-retained-artifact subcase; the retained subcase refuses before build.
If a supported generator makes it exceed a few seconds, retain the honest
compile because criterion 4 requires seam execution, and record measured time
in implementation/audit rather than replacing it with a mock.

Keep the existing OpenSSL configure/build and Apple architecture failure
strings as ordinary `_build` seam cases. Replace the current string-only fmt
case with the spdlog reached-marker case required here; do not claim fmt seam
execution from a string.

Rejected alternatives:

* Merely adding `"spdlog compile failed"` to the current error table repeats
  the existing string-only weakness.
* Emitting a marker during configure proves target creation, not compilation.
* A production failure-injection switch enlarges product behavior for a test.
* Duplicating the quartet helper risks different rollback assertions.

## D7 — Baseline coordinates and Rust release inputs

Update `test_baseline_stability.py::BASELINE` to
`46c10e4808965d6c065d62dece0071a8ff1624da`. Preserve the complete
byte-identical comparison of `sol/release/targets.toml`.

Refactor `sol/release/generate-dependencies.py` minimally so the exact
dependency-declaring input-path discovery and declaration parsing can operate
over either filesystem text or caller-supplied text. The generator's
production `parse(root)` remains the consumer of that shared logic. The
baseline test imports this module by path, as needed for its hyphenated
filename, and uses the same path inventory for:

* working-tree content read normally;
* baseline content obtained with `git show BASELINE:<path>`.

Normalize every parsed declaration to a coordinate record containing its
declaration kind/name and immutable coordinate fields
(`GIT_REPOSITORY`/`GIT_TAG` or `URL`/`URL_HASH`). Compare
`collections.Counter` multisets rather than ordered lists. This catches
additions, removals, duplicates, renames, changed pins, and declarations moved
between files while avoiding irrelevant formatting/order differences. Also
compare the path-to-coordinate multiset mapping so a declaration cannot move
outside its intended declaring file unnoticed.

The shared path inventory includes both top-level CMakeLists, CLI tests, SDK
unit tests and examples, and `nvat_fetch_gtest.cmake`; the design does not
retype that list. At the task baseline, the following discovered files declare
no FetchContent or ExternalProject dependency and are still supplied as empty
entries in the path mapping, so a future declaration is caught:

* `nv-attestation-cli/tests/CMakeLists.txt`;
* `nv-attestation-sdk-cpp/examples/CMakeLists.txt`;
* each SDK example subdirectory `CMakeLists.txt`, including
  `examples/common/CMakeLists.txt`;
* `nv-attestation-sdk-cpp/unit-tests/CMakeLists.txt`.

The two top-level CMakeLists and
`nv-attestation-sdk-cpp/cmake/nvat_fetch_gtest.cmake` are the current
nonempty declaration inputs.

The normalized comparison necessarily covers the Corrosion commit and regorus
tag because both are declarations in the SDK top-level file. Add explicit
assertions that the baseline and current release graph each select
`regorus_SOURCE_DIR/bindings/ffi/Cargo.toml`, crate `regorus-ffi`, staticlib,
Release profile, and `regorus/semver`; compare those extracted wiring tokens
between baseline and current source rather than hardcoding their coordinate
values a second time. Document in the test that the selected external ffi
manifest reaches the pinned regorus root manifest through its path dependency
and that the pin, not an in-tree Cargo lock, fixes the source tree. The local
`nv-attestation-sdk-rust` manifests are not inputs to this native release
graph and are not added to this criterion.

Do not invoke `generate-dependencies.parse()` directly against a synthetic
baseline directory assembled by a second file-list implementation. Share the
input discovery and parser seams so the generator and stability test have one
truth source.

Rejected alternatives:

* Retaining baseline `31ff1fb…` compares against the wrong task authority.
* Comparing only the two top-level CMakeLists misses future declarations in
  already-scanned empty files and the gtest helper.
* Comparing sets loses duplicate coordinates; comparing raw declaration order
  makes harmless movement/formatting fail.
* Copying the prep file list or regex into the test creates a second authority.
* Treating the unrelated local Rust SDK workspace as a release input expands
  criterion 5 beyond the actual native graph.

## D8 — Documentation and proof boundary

Make the minimum observed-fact update in `sol/release/README.md:134`: change
the VPE checklist phrase from `fmt/nvat/nvattest warning flags` to
`fmt/spdlog/nvat/nvattest warning flags`.

Do not add prose claiming that this Linux lode compiled real spdlog 1.14.1
sources under AppleClang, that it observed native macOS commands, or that the
source-extracted legacy fixture is a full CMake 3.11 production configure.
The lode proof is limited to the configured offline target graph and stub
commands/compiles under GNU plus source/order legacy proof. VPE must record
the genuine native AppleClang commands for all four compile owners and verify
that `nvat`/`nvattest` retain warnings-as-errors while fmt/spdlog do not.

Rejected alternatives:

* Broadly rewriting the release proof narrative would mix this narrow boundary
  with unrelated native claims.
* Removing AppleClang verification from VPE would turn Linux proxy evidence
  into a native assertion.

## Test inventory and acceptance-criterion mapping

| Acceptance criterion | Actual test | Status and proof |
|---|---|---|
| AC1 — complete configured graph is classified | `test_warning_policy.py::test_production_codemodel_classifies_every_compile_owner` | New; File API compile-group ownership plus source roots derives first/third-party sets, includes faithful Corrosion/imported/utility records, and cross-checks D1 call sites and effective first-party policy. |
| AC1 — exemption declarations fail closed | `test_warning_policy.py::test_compiled_third_party_exemption_calls_are_adjacent_and_fail_closed` | New; parses the single D1 form, proves each call follows its matching fetch, verifies the legacy guard follows both, and configures missing-target subcases for target/pin-specific diagnostics. |
| AC2 — modern effective commands preserve the boundary and baseline | `test_warning_policy.py::test_modern_effective_warning_commands_are_exact_and_undemoted` | New; exact ordered `nvat`/`nvattest` sequences, all-source agreement, accepted-demotion constant, and no warning-as-error on derived third-party owners. |
| AC2 — declared CMake floor preserves the boundary | `test_warning_policy.py::test_extracted_legacy_policy_owns_only_first_party_targets` | New; source-extracted real policy/order proves SDK fallback, target-local CLI addition, and fmt/spdlog exclusion, with the documented non-3.11-engine fidelity limit. |
| AC3 — compiler behavior matches command classification | `test_warning_policy.py::test_effective_commands_classify_controlled_warning` | New; swaps only source paths in all four real commands and asserts first-party failure versus third-party warning success without compiler-specific prose. |
| AC4 — spdlog compile failure cannot publish | `test_driver.py::test_macos_build_failures_use_driver_build_seam_and_never_publish` | Modified; the spdlog row executes the offline production configure/build, observes the source-emitted compile marker before `_build` raises, and reuses retained/absent quartet assertions. |
| AC5 — dependency coordinates and Rust release wiring are unchanged | `test_baseline_stability.py::test_all_dependency_coordinates_and_rust_wiring_are_unchanged` | Modified/replaced; shared generator inventory, normalized coordinate multisets and per-file empty entries compare baseline/current, including Corrosion/regorus and selected ffi wiring. |
| AC5 — target authority is unchanged | `test_baseline_stability.py::test_targets_authority_is_byte_identical` | Existing retained; rebased baseline and full `targets.toml` bytes. |
| AC5 — target IDs and release version remain stable | `test_baseline_stability.py::test_target_ids_are_unchanged`; `test_release_version_matches_baseline_sdk_version` | Existing retained against the rebased baseline. |
| AC6 — documentation states the complete native proof obligation | `test_warning_policy.py::test_readme_names_all_derived_compile_owners_for_vpe` | New; derives the four owner names through shared fixture/parser data and requires the VPE phrase, avoiding a second hardcoded four-name list. |

The former
`test_apple_cmake.py::test_preproject_guards_and_fmt_exemption_are_exact`
becomes `test_preproject_guards_and_compiled_third_party_exemption_form_are_exact`.
Its Apple preproject assertions remain unchanged. Its warning-policy portion
no longer counts fmt or forbids spdlog. Instead it imports the D1 call parser
from the warning-policy test support, requires that every parsed call uses the
single helper form and is immediately after its matching
`FetchContent_MakeAvailable`, and delegates set/classification truth to the
new codemodel test. It therefore contains no second hardcoded four-name list.

## Shared test-support layout

Add `sol/release/tests/cmake_support.py`, not new configure machinery inside
the warning module and not unrelated CMake behavior in the existing
artifact-oriented `support.py`.

`cmake_support.py` owns only generic mechanics:

* temporary root/build lifetime;
* project-include file creation from caller-provided content;
* trace and File API query setup;
* common configure arguments, extra cache/source arguments, subprocess
  capture, trace loading, codemodel loading, and compile-command loading;
* a fixture-preparation callback that receives the temporary root and returns
  additional configure arguments plus optional project-include content;
* the faithful offline dependency-stub preparer shared by the warning-policy
  and driver tests.

Move `production_configure()` from
`test_apple_cmake.py:270-358` into this module while preserving its returned
temporary owner, completed process, event log, records, and build path so
existing Apple callers change minimally. Do not carry the current `nested`
boolean into the generic API. `test_apple_cmake.py` supplies an
Apple-specific callback implementing its INTERFACE pre-nesting stubs,
project-boundary mutations, and intentional missing-Corrosion abort.
`test_warning_policy.py` imports the shared preparer implementing compiled
fmt/spdlog, faithful Corrosion, and the remaining dependency stubs, then adds
its compile-command and codemodel assertions. The driver spdlog case imports
the same preparer directly from `cmake_support.py`; it changes only spdlog's
stub source to the reached-marker failure variant.

Keep the D1 call-site parser and warning-option parser in
`test_warning_policy.py`. The offline fixture preparer remains dependency
source-shape machinery in `cmake_support.py`; it contains no warning-policy
constants or assertions.

## File-by-file implementation plan

1. `nv-attestation-sdk-cpp/CMakeLists.txt`
   - Add D1's local helper immediately before fmt, replace the inline fmt
     block with its call, and add the adjacent spdlog call.
   - Leave the SDK legacy/general warning region exactly unchanged.
   - Make no dependency declaration, pin, ExternalProject, Corrosion, or
     Apple change.
2. `nv-attestation-cli/CMakeLists.txt`
   - Add D2's target-local, guarded legacy `nvattest` option immediately after
     target creation.
   - Retain the modern variable assignment and SDK nesting unchanged.
3. `sol/release/tests/cmake_support.py`
   - Extract the existing production configure mechanics and add callback,
     File API, and compile-command loading seams described above.
4. `sol/release/tests/test_apple_cmake.py`
   - Import the shared configure helper, replace `nested` with its local
     fixture callback, and preserve existing return/assertion behavior.
   - Rename/rework the structural exemption test without a second target list.
5. `sol/release/tests/test_warning_policy.py`
   - Add D1–D5 graph, source classification, modern command, legacy extraction,
     fail-closed, ordering, and controlled compile tests.
   - Own the compiled offline fixture and single accepted-demotion constant.
6. `sol/release/tests/test_driver.py`
   - Extend the existing quartet helper with a minimal observation seam.
   - Replace the string-only fmt row with D6's real marked spdlog compile
     failure while retaining other failure rows.
7. `sol/release/generate-dependencies.py`
   - Expose shared dependency-input discovery and parsing over supplied text
     without changing generated dependency semantics or output.
8. `sol/release/tests/test_baseline_stability.py`
   - Rebase `BASELINE`, consume the shared dependency inventory/parser,
     compare normalized global and per-file coordinate multisets, cover empty
     scanned files, and compare regorus/Corrosion Rust wiring.
9. `sol/release/README.md`
   - Apply only D8's spdlog addition to the VPE warning-flag checklist.
10. `sol/notes/spdlog-warning-boundary-design.md`
    - Retain this decision record as implementation and audit authority.

Implementation order follows those dependencies: first production ownership
(files 1–2), then shared configure support (3), warning/Apple fixtures (4–5),
transaction proof (6), shared coordinate authority before its consumer
(7–8), and finally the documentation wording (9). Narrow checks should follow
those groupings during implementation through the repository-required
`hop check` interface; this design stage runs none.

## Hard boundaries, risks, and open questions

Hard boundaries:

* No `add_compile_options(-Wno-*)`, `-w`, `-Wno-error`, or
  `-Wno-error=*`.
* Do not weaken or remove `-Wall -Wextra -Wpedantic -pedantic`; do not remove
  either `CMAKE_COMPILE_WARNING_AS_ERROR ON` assignment.
* Do not change any pin, hash, URL, `GIT_TAG`,
  `sol/release/targets.toml`, or `sol/ci/Containerfile`.
* Do not touch the four `ExternalProject_Add` declarations,
  `nvat_apple_sdk.cmake`, the architecture gate, or Corrosion/regorus wiring.
* Do not relocate or replace the SDK legacy fallback.
* Do not add a production test hook, warning suppression, compatibility shim,
  or downloaded CMake dependency.

Risks and settled responses:

* Legacy third-party safety depends on source ordering. D2 deliberately keeps
  that behavior but turns it into an explicit structural and effective-command
  test.
* File API target presence varies by CMake version. Compile-group source
  ownership, not assumptions about INTERFACE/UTILITY visibility, is the
  stable classifier.
* Source-root classification must canonicalize paths before containment checks
  and reject mixed/outside roots; string-prefix matching is unsafe.
* Some compile databases expose a shell `command`, others an `arguments`
  array. Shared support must normalize both without changing token order.
* The legacy fixture is proxy evidence. Audit must not label it a real 3.11
  production configure.
* Diagnostic presence for the controlled warning is portable at the supported
  GNU/Clang level, but exact text is not.
* The deliberate spdlog source failure may format the marker differently
  across compilers; substring observation of the unique token is sufficient.
* Moving the configure helper can accidentally alter Apple test lifetimes or
  trace paths. Preserve its return contract and let the caller-specific
  callback own only fixture policy.
* Importing a hyphenated generator module requires an explicit importlib path
  loader or a small import-safe rename. Prefer the loader to avoid renaming
  the release entry point.
* The pinned external regorus manifests are not baseline blobs in this
  repository. Criterion 5 can prove their selecting pin and production wiring
  here; inspecting their contents remains provenance evidence from prep, not
  a byte comparison performed by the baseline test.

No design-blocking open question remains. The only proof deferred by
environment is VPE's native AppleClang 21 command and compile evidence.
