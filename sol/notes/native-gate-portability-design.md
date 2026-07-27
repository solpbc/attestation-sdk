# nvattest native-gate portability closure design

**Authority.** This record is the implementation authority for the
`nvattest` native-gate portability closure researched in
`sol/notes/native-gate-portability-prep.md`. It removes the one pinned
Corrosion SDK link-directory value from both named targets on the Rust owner
chain, keeps every unexpected value fail-closed, makes the reduced Apple
fixture faithful to Corrosion, removes all five Linux-process architecture
assumptions from the rail tests, and binds the Mach-O gate to literal accepted
values.

**Citation basis.** Repository line citations refer to the pre-change
integration tip `a17e2c14f2e62003a9e2f668d9f8089ebf4ef29c`. Corrosion
citations refer to the clean offline checkout at the pinned commit
`6be991bb34c348dfb8344be22f3606288ea5c7fd` under
`/home/extro/.hopper/worktrees/gas3tyru/build/_deps/corrosion-src`.

The accepted prep findings remain inputs, with these corrections now
settled:

* Corrosion emits one hardcoded consumer-edge directory:
  `/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/usr/lib`.
  `${NVAT_APPLE_SDKROOT}/usr/lib` is not a second accepted spelling.
* Real Corrosion creates `regorus_ffi` as an INTERFACE facade over imported
  STATIC `regorus_ffi-static`
  (`CorrosionGenerator.cmake:130-151`; `Corrosion.cmake:445-470,508-511`).
  Both targets are propagation points and both are inspected.
* Clearing `INTERFACE_LINK_DIRECTORIES` removes both the generated `-L` and
  the build rpath. It deliberately does not change Corrosion's
  `INTERFACE_LINK_LIBRARIES` or `INTERFACE_LINK_OPTIONS`
  (`Corrosion.cmake:454-467`).
* The current reduced fixture's direct imported-STATIC `regorus_ffi` is not
  faithful and must be replaced with the real facade/static-owner shape
  (`sol/release/tests/test_apple_link_closure.py:108-199`).

## D1 — One literal recognizer truth

Inside `nvat_configure_apple_system_link_closure()`, define one function-local
variable named `_nvat_apple_corrosion_sdk_link_directory` whose value is
exactly:

`/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/usr/lib`.

Use a plain local `set()`, not a pinned record block. The header-boundary
markers at
`nv-attestation-sdk-cpp/cmake/nvat_header_consumer_boundary.cmake:3-11`
serve a multi-record inventory parsed by tests; one scalar producer literal
does not justify a record format or marker protocol. A structural regression
will require the literal to occur exactly once in the helper, so the local
assignment is both the recognizer and its only production truth.

Compare each nonempty directory element by exact `STREQUAL` to that variable.
Do not use a glob, regular expression, suffix match, realpath normalization,
or selected-SDK substitution. A property containing one or more repetitions
of the one literal is known and can be cleared; any different element fails.
Repeated identical entries do not widen the accepted path.

The apparent selected-SDK case needs no second recognizer:

* If VPE selects the Command Line Tools SDK at
  `/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk`, its
  `${NVAT_APPLE_SDKROOT}/usr/lib` is already byte-for-byte the one Corrosion
  literal.
* If VPE selects an Xcode SDK, Corrosion still emits the hardcoded Command
  Line Tools literal. The helper clears that literal; it must not silently
  accept the unrelated Xcode `${NVAT_APPLE_SDKROOT}/usr/lib` spelling because
  no proved producer emits it.

A future Corrosion pin that changes the literal is expected to fail closed
and require a new provenance decision. This closure does not guess future SDK
layouts.

## D2 — Validate first, clear in the existing mutation tail

Preserve the helper's current rule that no target graph mutation occurs until
all discovery and validation succeeds
(`nv-attestation-sdk-cpp/cmake/nvat_apple_system_link_closure.cmake:3-114`).
The function's settled order is:

1. Retain the existing `APPLE` and selected-SDK root validation and
   canonicalization.
2. Require both Rust owner-chain targets from D3, then retain the existing
   `LibXml2::LibXml2` existence and `Iconv::Iconv` collision checks.
3. Read and validate `INTERFACE_LINK_DIRECTORIES` on both Rust targets using
   D1's one recognizer. Reading and local iteration do not mutate the graph.
4. Retain the exact selected-SDK iconv and CoreFoundation discovery,
   canonicalization, and containment checks.
5. Only after both Rust properties and both selected-SDK artifacts validate,
   enter the existing mutation tail at current lines 116-123. Clear
   `INTERFACE_LINK_DIRECTORIES` on both Rust targets first, then create
   `Iconv::Iconv`, set its imported location, and retain the exactly two
   APPEND operations on `INTERFACE_LINK_LIBRARIES`.
6. Retain the final cache cleanup.

The clears use non-APPEND `set_property(TARGET ... PROPERTY
INTERFACE_LINK_DIRECTORIES "")`. They replace the complete usage requirement,
so neither the directory's `libraryPath` `-L` fragment nor an rpath derived
from it can survive. They do not match the existing structural regex that
requires literal `APPEND PROPERTY INTERFACE_LINK_LIBRARIES`
(`sol/release/tests/test_apple_link_closure.py:286-292`).

Both target properties are validated in one shared loop, and both are cleared
in one shared tail loop over the same two-name list. Every target and every
property entry validates before the first clear. A mixed known/unknown list
therefore clears nothing; the first unsupported element stops configure while
the graph is untouched.

Express this with the permitted CMake 3.11 vocabulary: `set`, `if`,
`foreach`, `get_target_property`, and `set_property`. The change needs none
of `list(PREPEND`, `string(JOIN`, `target_link_options`, `file(REAL_PATH`,
`cmake_path`, or `FetchContent_MakeAvailable`.

## D3 — Inspect exactly the two named Rust-chain targets

Define one local two-element target list containing the literal names
`regorus_ffi` and `regorus_ffi-static`. Iterate that list for both existence
and property inspection, and reuse it for the delayed clears. Do not discover
the static target through `INTERFACE_LINK_LIBRARIES`, maintain a registry,
accept caller-supplied names, or sweep CMake targets.

This scope is deliberately one step wider than the known producer:

* Pinned Corrosion currently sets the directory on
  `regorus_ffi-static` (`Corrosion.cmake:445-468`).
* `regorus_ffi` is the INTERFACE facade linked directly by `nvat`; a directory
  on it would reach `nvat` just as directly
  (`Corrosion.cmake:508-511`;
  `nv-attestation-sdk-cpp/CMakeLists.txt:484-502`).
* Inspecting both states the invariant that no directory reaches `nvat` from
  this named Rust owner chain. It also closes a future within-pin fixture or
  generator drift without adding a generic framework.

Both targets are mandatory. In particular, `regorus_ffi-static` cannot be
skipped: the SDK imports only `CRATE_TYPES "staticlib"`, so pinned Corrosion
always creates it before the Apple helper call
(`nv-attestation-sdk-cpp/CMakeLists.txt:51-73,374-376`). Absence of either
target is a wiring failure.

An unset property is the falsey `<variable>-NOTFOUND` state observed on CMake
3.11.4; a wholly empty property is also safe. Each is accepted only after the
named target exists and `get_target_property` was actually called. A nonempty
property is iterated as a CMake list:

* each exact D1 literal is accepted;
* a relative path, arbitrary absolute path, unrecognized `*.sdk/usr/lib`,
  generator expression, or embedded-semicolon element is rejected;
* leading, trailing, or doubled separators expose an empty list element and
  are rejected;
* a known/unknown mixture is rejected before any clear.

The whole-empty property is distinct from an empty element inside a nonempty
list. No value is canonicalized, trimmed, collapsed, or reconstructed before
recognition.

`LibXml2::LibXml2` and `xmlsec::xmlsec` are explicitly outside this
inspection list. Corrosion never sets their link directories, the SDK/Find
module owns them, and the existing selected-SDK iconv edge already closes
their relevant static dependency
(`nv-attestation-sdk-cpp/CMakeLists.txt:356-370`;
`nv-attestation-sdk-cpp/cmake/Findxmlsec.cmake:22-56`).

## D4 — Two exact shared diagnostics

Use the existing wrapped `message(FATAL_ERROR ...)` house style. The two new
parameterized diagnostics are:

* Missing either owner-chain target:
  `"Darwin/arm64 Rust link-directory closure failed: required owner-chain target '${_nvat_apple_rust_owner_target}' does not exist; recreate the pinned Corrosion regorus_ffi staticlib targets in a clean build directory, then retry"`.
* Any unsupported list entry:
  `"Darwin/arm64 Rust link-directory closure failed: target '${_nvat_apple_rust_owner_target}' has unsupported INTERFACE_LINK_DIRECTORIES entry '${_nvat_apple_rust_link_directory}'; remove the unexpected link-directory entry and configure from a clean build directory, then retry"`.

The existence diagnostic is shared by the two literal target names. The entry
diagnostic is shared by both targets and every hostile shape; it names the
exact target and offending element. An empty element is rendered as `''`.
The embedded-semicolon fixture uses an escaped semicolon so CMake presents one
literal offending element; an unescaped semicolon remains the ordinary list
separator and is covered by the mixed/empty cases.

No diagnostic is added for unset, wholly empty, or known values. All existing
platform, SDK, LibXml2, Iconv, and CoreFoundation diagnostics remain
byte-for-byte unchanged except that the old regorus-only absence expectation
is replaced by the shared owner-chain diagnostic.

The helper will contain no uppercase `URL` substring in any identifier,
comment, or diagnostic; the baseline guard rejects that bare substring
(`sol/release/tests/test_baseline_stability.py:241-252`). It also contains no
literal `-L/opt/homebrew` or `-L/usr/local`
(`sol/release/tests/test_apple_link_closure.py:906-937`). Hostile test paths
are substituted test data, never hardcoded production diagnostics.

## D5 — Faithful Apple fixture and complete directory matrix

Change `ReducedAppleFixture` in
`sol/release/tests/test_apple_link_closure.py:108-227` to model pinned
Corrosion exactly:

* create `regorus_ffi` as a non-imported INTERFACE facade;
* create `regorus_ffi-static` as imported GLOBAL STATIC with the existing
  `libregorus_ffi.a` location;
* put `regorus_ffi-static` first on the facade's
  `INTERFACE_LINK_LIBRARIES`, matching `Corrosion.cmake:508-511`;
* give the imported static target D1's known
  `INTERFACE_LINK_DIRECTORIES` value by default, matching
  `Corrosion.cmake:445-468`;
* retain `before_call=` after all owner targets exist and immediately before
  the extracted real helper call.

Expand the property record to capture the facade's link interface, the
static target's imported location, and both targets'
`INTERFACE_LINK_DIRECTORIES` after the helper. Also capture target types so
the test proves `INTERFACE_LIBRARY` facade plus `STATIC_LIBRARY` imported
owner rather than merely reproducing the target names.

The expected `nvat` ordering is relational and exact:

* `libregorus_ffi.a` occurs once and CoreFoundation occurs once after that
  archive, because the facade interface contains `regorus_ffi-static` before
  the helper's appended CoreFoundation path;
* every `libxml2.a` owner occurrence remains ahead of the one selected-SDK
  iconv path;
* the facade has no link artifact of its own;
* no cross-owner-chain interleaving is prescribed beyond those two partial
  orders.

This continues to satisfy “each selected-SDK artifact reaches `nvat` exactly
once, after its static owner.” The exact index of the now-transitive regorus
archive may move relative to the independent LibXml2 closure; that
generator-owned interleaving is not an acceptance value.

The three required fixture shapes all use the existing `before_call=` seam:

### D5.1 — Known-shape happy path

Run the faithful default with the known value on `regorus_ffi-static`, then a
second subcase that puts the same known value on the `regorus_ffi` facade.
The helper must leave both post-call directory properties empty in both
subcases.

For `nvat`, require:

* no exact `-L` fragment for the known directory in
  `all_link_fragments`;
* no occurrence of the known directory in any
  `library_fragments` rpath, any `all_link_fragments` entry, or raw
  `CMakeFiles/nvat.dir/link.txt`;
* one selected-SDK iconv and one CoreFoundation item in D5's owner-relative
  order.

For `nvattest`, retain the exact reduced-fixture vector of its build rpath
plus `libnvat.so`, and require no direct regorus archive, iconv,
CoreFoundation, known directory, or `-L` fragment. Product source and the
literal Mach-O tests separately preserve the authored
`@executable_path/../lib`.

The rpath assertion must search every fragment for the known directory as a
substring. CMake emits a colon-joined composite rpath on this Linux fixture,
so equality against a standalone `-Wl,-rpath,<known>` token would miss the
defect. Do not reject all fixture rpaths; its fake framework and build
directories legitimately create unrelated modeled rpath text.

### D5.2 — Hostile and malformed shapes

For each of `regorus_ffi` and `regorus_ffi-static`, use `before_call=` to
replace its directory property independently with:

* an arbitrary non-SDK absolute directory;
* an unrecognized `*.sdk/usr/lib` directory;
* a list with a leading, trailing, or doubled separator and therefore an
  empty element;
* a relative directory;
* one escaped-semicolon path element;
* a mixed list containing the exact known literal and one unknown directory.

Each fresh fixture must fail with D4's exact target and exact offending entry.
The known/unknown case proves one recognized element cannot launder another.
Extend the helper source-order assertion to require all property reads and
recognizer checks before either clear; combined with the fatal fixture, this
proves the failing set is not partially neutralized.

No hostile case may be normalized into the known literal, skipped, or
converted into a warning.

### D5.3 — Verified empty and unset shapes

Use `before_call=` to exercise an explicitly empty property and a truly unset
property on each owner-chain target. Both named targets remain present. Each
fixture configures, records both post-call properties empty, and preserves
the selected-SDK owner edges.

The structural test requires one shared `get_target_property` body over the
two-name list, so success cannot be implemented as an unconditional skip for
falsey values. The separate missing-target cases remove first the facade and
then the static owner and require D4's existence diagnostic, proving
empty/not-set is safe only for an existing inspected target.

### D5.4 — Existing expectation changes

Every current `ReducedAppleFixture` consumer was traced. These expectations
change:

* `test_reduced_apple_fixture_orders_each_owner_edge_once`
  (`test_apple_link_closure.py:305-355`) no longer treats the complete
  `REGORUS` property as the CoreFoundation path. It requires the facade
  interface to begin with `regorus_ffi-static`, obtains CoreFoundation from
  that interface, checks both cleared directory properties, and retains the
  two owner-relative index assertions.
* `test_helper_fails_closed_for_platform_sdk_target_and_artifact_errors`
  (`test_apple_link_closure.py:496-601`) updates its source removal for the
  facade/static pair, replaces the old missing-regorus text with D4, and adds
  an independent missing-`regorus_ffi-static` case.
* `test_policy_rejects_linker_escape_hatches_and_non_sdk_inputs`
  (`test_apple_link_closure.py:906-994`) derives CoreFoundation from the
  facade list instead of treating `REGORUS` as one path, includes both
  post-clear directory properties in generated surfaces, and adds the known
  directory, `-L`, rpath-composite, and no-direct-static-owner assertions.
* The shared `assert_extracted_fixture()` used by
  `test_extracted_link_closure_with_release_cmake` and
  `test_extracted_link_closure_with_real_cmake_311_when_available`
  (`test_apple_link_closure.py:1026-1050`) consumes the expanded property
  dump and requires both directories empty and both target types faithful.
  Its iconv/CoreFoundation and `nvattest` link expectations remain.
* `test_production_has_one_guarded_call_and_one_edge_truth_source`
  (`test_apple_link_closure.py:264-303`) retains the exactly-two APPEND count
  and adds the one-literal, two-target, shared-read, validate-before-clear,
  and shared-clear structural assertions.

The invalid-SDK, discovery-poison, Iconv-collision, symlink-escape, install,
consumer, and driver uses of `ReducedAppleFixture` keep their current
diagnostics and outcomes. They inherit the faithful default owner chain but
do not parse its changed property record.

`test_linux_production_link_vectors_are_unchanged` is separate. Its
`setUpClass` uses `production_configure(...,
fixture_prepare=warning_fixture_prepare(), query_codemodel=True)`
(`test_apple_link_closure.py:233-251,357-404`), and
`warning_fixture_prepare()` still creates its Linux-only imported-static
stand-in (`sol/release/tests/cmake_support.py:59-74`). It never instantiates
`ReducedAppleFixture`, the Apple helper call remains untraced, and its exact
`nvat`/`nvattest` vectors remain untouched. Do not modify
`cmake_support.py`.

## D6 — Make all five host-sensitive tests hermetic

Production host selection remains unchanged in
`Authority.compatible_target()`, `Authority.require_compatible()`, and driver
`_preflight()` (`sol/release/release_rail/authority.py:67-101`;
`sol/release/release_rail/driver.py:528-567`). Only tests change.

### D6.1 — Two real-host-selection tests

In
`test_authority.AuthorityTest.test_accessor_reports_incompatible_forced_target`
(`sol/release/tests/test_authority.py:144-161`), derive the expected compatible
ID with `authority.load().compatible_target()` in the parent process. Keep the
real `sys.executable rail.py authority build-image macos-arm64` child and
assert recovery `HOST_TARGET=<derived ID>`, never `TARGET_IDS[0]`.

The child receives the selected fixture predicate because `subprocess.run`
does not replace its environment. During the two implementation-stage
full-suite runs, the scratch-only `sitecustomize.py` directory is inherited
through `PYTHONPATH` and automatically imported by the child; prep's
aarch64 run observed the child report `Linux/aarch64`. No shim or
auto-imported module is committed under `sol/release/tests/`.

In
`test_driver.DriverPreflightTest.test_missing_target_fails_before_dist_exists`
(`test_driver.py:174-182`), derive the compatible ID from the same production
authority and use it in the expected `make release TARGET=<derived ID>`
diagnostic. This case intentionally tests the real recommendation for the
selected fixture host.

Do not create a shared helper for these two derivations. They live in
different modules and share only the single production call
`authority.load().compatible_target()`; a test-support wrapper would add a
third truth source and obscure the behavior under test. There is no duplicated
host mapping, positional target choice, or fixture predicate.

### D6.2 — Three fixed-target data tests

For each fixed `linux-x86_64` test, patch
`authority.Authority.compatible_target` to return the selected target ID and
`authority.Authority.require_compatible` to return that exact target,
following the existing macOS precedent at
`sol/release/tests/test_driver.py:642-648`:

* `DriverPreflightTest.test_dirty_source_tree_fails_before_dist_exists`
  (`test_driver.py:184-198`);
* `DriverRuntimeTest.test_release_threads_one_selection_through_every_container_command`
  (`test_driver.py:324-449`);
* `DriverRuntimeTest.test_ownership_failure_precedes_dist_creation`
  (`test_driver.py:580-594`).

These tests are about dirty-tree ordering, one runtime selection, and
ownership-preflight ordering, not host selection. The patches prevent live
compatibility from preempting those fixed-target branches while leaving
production authority behavior covered by the explicit host-argument test at
`test_authority.py:40-48`.

Use the direct two-patch form in each test. A new fixed-host abstraction would
save only two clear statements while hiding which production methods are
bypassed. The audit concern is duplicated host fixture truth; these patches
contain no machine mapping or recovery constant.

No test is renamed, skipped, deleted, or xfailed. Under fixture Linux x86_64
and Linux aarch64 predicates, the same complete collected test-ID set,
including the new link-directory cases, must execute with the same optional
CMake skip disposition and pass.

## D7 — Literal Mach-O acceptance oracle

Keep `sol/release/targets.toml` byte-identical to baseline
`b75e95ae0c08ac6eaa05673a0cf227b8723e2b58`
(`sol/release/tests/test_baseline_stability.py:27,135-136`). Strengthen two
existing test modules instead of changing the policy table or production
gate.

In `test_authority.py`, extend the landed-authority test with literal
right-hand sides for:

* the exact library member chain:
  `lib/libnvat.dylib` symlink to `libnvat.1.dylib`,
  `lib/libnvat.1.dylib` symlink to `libnvat.1.2.2.dylib`, and
  regular `lib/libnvat.1.2.2.dylib`;
* `macho_install_id` exactly `@rpath/libnvat.1.dylib`;
* `macho_rpath` exactly `@executable_path/../lib`;
* `abi_floor` exactly `{"macos": "14.0"}`.

Do not derive any expected member, link target, rpath, install ID, or floor
from the loaded target.

In `test_gate.py::test_valid_macho_executable_and_library`
(`sol/release/tests/test_gate.py:121-140`), construct the executable fixture
with literal deployment `(14, 0, 0)` and literal rpath
`@executable_path/../lib`. Construct the library fixture with literal
deployment `(14, 0, 0)`, literal ID `@rpath/libnvat.1.dylib`, and an empty
rpath tuple. Pass both fixtures to `gate.gate_file` with the real
`macos-arm64` target and allowlist. Retain the existing bad literal identity
and rpath cases at `test_gate.py:188-207`.

These fixtures remain a real oracle while the table is frozen because their
accepted bytes are independent inputs, not values read back from the target
given to the gate. A self-consistent wrong target-table edit is stopped by
the byte guard; a future deliberate baseline advance is stopped by the
literal authority and fixture expectations unless it explicitly requalifies
all accepted values.

Keep `sol/release/tests/support.py::make_stage()` data-driven
(`support.py:52-81`). It constructs general target quartets and should
continue reading `members`, `macho_install_id`, and `macho_rpath` from its
target argument. The independent authority/gate tests, not duplicated policy
inside shared fixture support, provide the binding.

## D8 — Closed path budget

The design fits the mandatory budget; no gate is required. The complete
implementation changed-path set is:

1. **`nv-attestation-sdk-cpp/cmake/nvat_apple_system_link_closure.cmake`
   (production).** Add D1-D4's one literal, two-target existence/read
   validation, and delayed two-target clear. Preserve all discovery and the
   exactly two platform-library APPEND operations.
2. **`sol/release/tests/test_apple_link_closure.py` (regression).** Make
   `ReducedAppleFixture` faithful, add D5's known/hostile/empty matrices,
   strengthen every affected property/vector/structural assertion, and
   preserve the Linux production vector arm.
3. **`sol/release/tests/test_authority.py` (regression).** Derive the
   subprocess recovery target and add D7's literal member/install/rpath/floor
   authority bindings.
4. **`sol/release/tests/test_driver.py` (regression).** Derive the missing-
   target recovery and patch both authority methods in the three fixed-target
   tests.
5. **`sol/release/tests/test_gate.py` (regression).** Replace target-derived
   valid Mach-O inputs with D7's literal accepted values.
6. **`sol/notes/native-gate-portability-design.md` (record).** This decision
   record.

No change is needed to either product `CMakeLists.txt`: the helper is already
included and called after Corrosion and LibXml2 creation
(`nv-attestation-sdk-cpp/CMakeLists.txt:1-13,356-378`). No change is needed
to `cmake_support.py`, `support.py`, baseline stability, production Python,
the target table, README, allowlists, Makefile, container definition, or any
new shipped module.

The README guard at
`test_apple_link_closure.py:1194-1205` continues to pin the existing Pro5E
native-proof text. This design adds a Pro5E link-risk obligation below but
does not require new shipped README wording, so a README gate is not
triggered.

## Acceptance map and dependency order

| implementation group | dependent proof |
| --- | --- |
| D1-D4 helper logic | one literal occurrence; two literal target names; both targets required and read; every entry exact or fatal; both clears after all validations; exactly two APPEND link-library edges retained |
| D5 faithful fixture | known directory produces neither `-L` nor a composite rpath on `nvat`; both properties end empty; iconv/CoreFoundation remain once after owners; `nvattest` remains direct-owner-free |
| D5 hostile/empty fixtures | arbitrary, SDK-shaped, relative, empty-element, semicolon, and mixed values fail per target with exact diagnostics; wholly empty/unset succeeds only with both targets |
| D6 authority/driver tests | exact five cases execute under both Linux host predicates with derived recovery for real selection and fixed predicates for fixed-target data |
| D7 authority/gate literals | member chain, install ID, executable rpath, library no-rpath, and exact 14.0 deployment remain independent accepted inputs |
| retained structural arms | Linux production vectors, install/export behavior, real CMake 3.11 fixture, linker-escape policy, dependency-token guard, README VPE text, and target-table bytes remain unchanged |

Implement in this order:

1. Update the helper's local constants, owner validation, recognizer, and
   delayed clears.
2. Make the reduced fixture faithful and update all Apple-link assertions;
   this is the direct regression for the production change.
3. Repair the two real-host-selection and three fixed-target tests.
4. Bind authority and gate tests to literal Mach-O values.
5. Run the directed focused and full-suite verification only in the
   implementation stage, including both scratch host predicates and the real
   CMake 3.11 arm. This design stage runs none.

## Risks and native proof boundary

1. **Bare native library resolution remains a native risk.** Corrosion sets
   `INTERFACE_LINK_LIBRARIES` from
   `Rust_CARGO_TARGET_LINK_NATIVE_LIBS` on `regorus_ffi-static`
   (`Corrosion.cmake:454-459`). Clearing only
   `INTERFACE_LINK_DIRECTORIES` preserves every bare `-l` item and link
   option but removes the extra Command Line Tools `-L`.

   The risk is low because the removed directory names only the system
   library directory inside an Apple SDK, not a third-party prefix. The
   resulting expectation that any bare native name resolved there is an SDK
   system library is an inference, not a native proof. The Apple toolchain
   resolver sets
   `CMAKE_OSX_SYSROOT` to the selected absolute SDK before `project()`
   (`nv-attestation-sdk-cpp/cmake/nvat_apple_sdk.cmake:27-100`); the compiler
   driver consequently supplies the selected SDK through `-isysroot`, whose
   system-library search resolves ordinary SDK `-l` names without the
   Corrosion host-directory usage requirement. The helper also retains its
   validated absolute selected-SDK iconv path and CoreFoundation path.

   This Linux lode cannot prove that native resolution. Pro5E must rerun the
   native arm64 link, confirm every Corrosion bare native library resolves,
   record the final `nvat` command with no Command Line Tools `-L`, and verify
   `libnvat.1.2.2.dylib` has no `LC_RPATH`. There is no fallback,
   retain-on-doubt mode, or alternate search directory.
2. **CMake list spelling is intentionally strict.** An escaped semicolon,
   empty member, relative entry, or changed SDK literal fails even if a human
   could normalize it. This is the required provenance boundary, not a
   compatibility defect.
3. **The reduced fixture proves structure, not Apple linkage.** Linux
   codemodel and `link.txt` prove removal of `-L`/rpath propagation and
   owner-relative edges. Only Pro5E proves AppleClang framework conversion,
   bare-native-library resolution, final install names, deployment floor,
   and Mach-O load commands.
4. **Independent owner chains may interleave differently.** Tests require
   each selected artifact after its own static archive and exactly once; they
   do not freeze an unrelated cross-chain index that CMake does not promise.
5. **The single literal is pinned behavior.** If Corrosion changes it, the
   helper fails rather than silently widening recognition. Updating that
   literal requires new source evidence and review.

No implementation choice remains open. The native-link item is a Pro5E proof
obligation, not a reason to widen the helper or path budget.

## Landed test locations

The citations above retain their declared pre-change basis. Test code moved
materially during implementation; the corresponding landed locations are:

| pre-change reference | landed location |
| --- | --- |
| `test_apple_link_closure.py:108-227` reduced fixture | `test_apple_link_closure.py:111-249` |
| `test_apple_link_closure.py:264-303` structural guard | `test_apple_link_closure.py:323-405` |
| `test_apple_link_closure.py:305-355` owner-order test | `test_apple_link_closure.py:406-478` |
| `test_apple_link_closure.py:357-404` Linux-vector test | `test_apple_link_closure.py:611-659` |
| `test_apple_link_closure.py:496-601` helper-failure test | `test_apple_link_closure.py:750-865` |
| `test_apple_link_closure.py:906-994` policy test | `test_apple_link_closure.py:1169-1268` |
| `test_apple_link_closure.py:1026-1050` extracted fixture | `test_apple_link_closure.py:1300-1336` |
| `test_apple_link_closure.py:1194-1205` README guard | `test_apple_link_closure.py:1485-1496` |
| `test_authority.py:144-161` subprocess host test | `test_authority.py:169-187` |
| `test_driver.py:324-449` runtime-selection test | `test_driver.py:337-476` |
| `test_driver.py:580-594` ownership-order test | `test_driver.py:607-638` |
| `test_driver.py:642-648` authority-patch precedent | `test_driver.py:681-704` |
