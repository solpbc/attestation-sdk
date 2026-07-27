# nvattest macOS native system-link closure design

**Authority.** This record is the implementation authority for the
`nvattest` macOS native system-link closure researched in
`sol/notes/mac-native-link-closure-prep.md`. It adds only the selected Apple
SDK's iconv stub and CoreFoundation framework to their static owners, keeps
both owners private to shared `nvat`, preserves `nvattest`'s direct link
surface, and makes a failed native configure identify both the canonical
release target and the CMake failure.

The prep results are settled inputs, not questions for implementation:

* Q1 proved that a `PRIVATE` dependency of shared `nvat` creates no
  `$<LINK_ONLY:...>` interface and does not reach either `nvattest`
  codemodel or `link.txt` surface.
* Q2 proved that interfaces added to imported `regorus_ffi` and
  `LibXml2::LibXml2` affect `nvat` but do not enter `nvatTargets.cmake`.
  It also identified the current clean-prefix package failure as pre-existing.
* Q3 measured one owner-relative framework item and one deduplicated iconv
  item despite the two paths to `LibXml2::LibXml2`.
* Q4 disqualified `find_package(Iconv)` and default-path framework/library
  search, and established selected-SDK-only lookup plus canonical containment.
* Q5 established the helper's real CMake 3.11 command boundary and the wider
  graph's unchanged post-3.11 incompatibilities.
* Q6 selected codemodel plus `link.txt` for structural evidence and a rule
  override only for the hostile-child transaction proof.
* Q7 located the release-driver configure seam and the required
  capture/replay/error-folding behavior.
* Q8 established scanner placement, baseline, Rust input, and dependency-token
  constraints.

## D1 — One closed Apple system-link helper

Add
`nv-attestation-sdk-cpp/cmake/nvat_apple_system_link_closure.cmake`.
It follows `nvat_apple_sdk.cmake:1-3` exactly: `include_guard(GLOBAL)`, one
public function, two-space indentation, lower-case `nvat_` function/local
names, and upper-case `NVAT_APPLE_*` selected-SDK/result names.

The sole public signature is
`nvat_configure_apple_system_link_closure()`. It takes no arguments. The
closed signature fixes `regorus_ffi`, `LibXml2::LibXml2`, `Iconv::Iconv`,
CoreFoundation, and their ownership relationship in one production truth
source; callers cannot substitute targets, paths, or platform edges.

The function is fail-closed and performs these steps in order:

1. Require `APPLE`; reaching the function with `APPLE` false is a wiring bug.
2. Require `NVAT_APPLE_SDKROOT` to name an absolute existing directory and
   canonicalize it with `get_filename_component(... REALPATH)`.
3. Require both static owner targets, `regorus_ffi` and
   `LibXml2::LibXml2`, to exist.
4. Reject any pre-existing `Iconv::Iconv`; such a target has not passed this
   helper's selected-SDK validation.
5. Clear the normal and cache forms of the dedicated
   `NVAT_APPLE_ICONV_LIBRARY` result, perform only D3's exact iconv lookup,
   require a result, canonicalize it, and require canonical containment under
   the canonical SDK root.
6. Clear the normal and cache forms of
   `NVAT_APPLE_COREFOUNDATION_FRAMEWORK`, perform only D3's exact
   CoreFoundation lookup, require a result, canonicalize it, and apply the same
   containment rule.
7. Only after both artifacts validate, create the imported
   `Iconv::Iconv`, set its imported location to the canonical iconv result,
   and append the two D2 owner interfaces. No graph mutation occurs before
   both discoveries succeed.
8. Remove the two lookup results from the cache after the target properties
   have consumed their canonical values. They are implementation results, not
   supported caller inputs.

Containment compares the canonical artifact path, with a trailing separator,
to the canonical SDK root with a trailing separator and requires index zero.
This rejects prefix siblings and an SDK-contained symlink whose real target is
outside the SDK. Empty, missing, relative, outside-SDK, and target-collision
states are fatal.

Unlike `nvat_resolve_apple_toolchain()` at
`nvat_apple_sdk.cmake:3-6`, this helper must not silently `return()` off
Darwin. The resolver is deliberately callable from shared pre-project setup
and treats a non-Darwin host as outside its responsibility. The new helper is
called only from a post-`project()` `if(APPLE)` block; reaching it elsewhere
means the Apple-only ownership closure has been omitted. Returning would fail
open with no edges and no diagnostic.

The helper contains no registry, loop, option, target-discovery framework,
fallback search, copied artifact, or dependency declaration. It uses none of
`list(PREPEND)`, `string(JOIN)`, `FetchContent_MakeAvailable`,
`target_link_options`, `file(REAL_PATH)`, or `cmake_path`. Prep Q5 proved the
chosen commands on the real 3.11.4 engine; this does not claim that the wider
production graph became CMake-3.11-compatible.

## D2 — Static-owner interfaces and one SDK call site

The two and only two platform-edge wiring statements are:

* append the validated canonical CoreFoundation framework path to
  `regorus_ffi`'s `INTERFACE_LINK_LIBRARIES`;
* append `Iconv::Iconv` to
  `LibXml2::LibXml2`'s `INTERFACE_LINK_LIBRARIES`.

Use `set_property(TARGET ... APPEND PROPERTY INTERFACE_LINK_LIBRARIES ...)`
so any existing owner interface is preserved and ownership remains explicit.
The first edge closes the Rust static archive; the second closes the LibXml2
static archive.

Make no change to `target_link_libraries(nvat)` at
`nv-attestation-sdk-cpp/CMakeLists.txt:479-497`. It already links
`LibXml2::LibXml2` at line 488 and `regorus_ffi` at line 496 as `PRIVATE`
dependencies of shared `nvat`. Those existing items carry the two owner
interfaces into `nvat`; Q1 proves that neither interface becomes a direct
`nvattest` item. This is why the implementation adds two owner-property lines,
not a new `nvat` or `nvattest` link item.

Add the module include beside the existing root includes at
`nv-attestation-sdk-cpp/CMakeLists.txt:2-3`. Add exactly one call block
immediately after `endif() # USE_SYSTEM_DEPS` at current line 371 and before
`find_package(ZLIB REQUIRED)` at line 373. At that point:

* Corrosion has created `regorus_ffi` at lines 66-72;
* either the system or vendored dependency branch has created
  `LibXml2::LibXml2`, with the vendored path completing at lines 365-369;
* `nvat` has not yet been created or linked, so both owner interfaces are
  complete before its link closure is evaluated.

The call is wrapped in one post-`project()` `if(APPLE)` block, matching the
style at current lines 253-256 and 433-439. Do not use the pre-project
`CMAKE_HOST_SYSTEM_NAME` form. The include merely defines a guarded function
on Linux, and the call block is false, so every new SDK statement is inert
there.

The direct and `xmlsec::xmlsec` interface paths to `LibXml2::LibXml2` remain
unchanged (`CMakeLists.txt:488`;
`cmake/Findxmlsec.cmake:38-45`). Prep Q3 measured zero-based owner indices
`[5, 11]` and one iconv item at index `12`, after the last owner. It measured
`regorus_ffi` at index `9` and the one framework pair at index `18`.
Therefore G6's two LibXml2 reach paths still produce one deduplicated iconv
occurrence in owner-relative order, and the CoreFoundation occurrence remains
after its one regorus owner.

## D3 — Exact selected-SDK discovery, imported Iconv, and diagnostics

**Implementation amendment after the required Step-0 probes.** Linux CMake
3.31.10 reported `CMAKE_FIND_LIBRARY_PREFIXES=lib` and
`CMAKE_FIND_LIBRARY_SUFFIXES=.so;.a`; with those values,
`find_library(... NAMES libiconv.tbd ...)` returned
`V-NOTFOUND`. A reduced-fixture-only Darwin search shim setting
`CMAKE_FIND_LIBRARY_SUFFIXES=.tbd;.dylib;.so;.a` made the same command resolve
the literal fake-SDK `usr/lib/libiconv.tbd`. Linux's empty/default
`CMAKE_FIND_FRAMEWORK` and `NEVER` both returned `V-NOTFOUND` for
CoreFoundation; `FIRST`, `ONLY`, and `LAST` each resolved the fake-SDK
`System/Library/Frameworks/CoreFoundation.framework`. Therefore D3's
production `NAMES`/`PATHS` remain unchanged, and D6.1's Linux reduced fixture
must set the Darwin suffix list and `CMAKE_FIND_FRAMEWORK=FIRST` after
`project()` with a comment that both are test-side Darwin search-behavior
shims. Generation on Linux additionally requires the fixture-only Darwin
`CMAKE_CXX_LINK_LIBRARY_USING_FRAMEWORK` form and support flag; those are
link-rule shims, not native-link evidence. None of these settings belongs in
the production helper.

The helper is the sole discovery point for both dependencies. It uses no
default search paths and no globs.

For iconv:

* result variable: `NVAT_APPLE_ICONV_LIBRARY`;
* `NAMES`: exactly `libiconv.tbd`;
* `PATHS`: exactly `${NVAT_APPLE_SDKROOT}/usr/lib`;
* mode: `NO_DEFAULT_PATH`;
* expected SDK layout:
  `${NVAT_APPLE_SDKROOT}/usr/lib/libiconv.tbd`.

For CoreFoundation:

* result variable: `NVAT_APPLE_COREFOUNDATION_FRAMEWORK`;
* `NAMES`: exactly `CoreFoundation`;
* `PATHS`: exactly
  `${NVAT_APPLE_SDKROOT}/System/Library/Frameworks`;
* mode: `NO_DEFAULT_PATH`;
* expected SDK layout:
  `${NVAT_APPLE_SDKROOT}/System/Library/Frameworks/CoreFoundation.framework`.

Both result variables are cleared before lookup so `-D` cache entries cannot
short-circuit `find_library`. `CMAKE_PREFIX_PATH`, `CMAKE_LIBRARY_PATH`,
`CMAKE_FRAMEWORK_PATH`, their environment variants, Darwin's Homebrew/system
prefixes, `CMAKE_FIND_ROOT_PATH`, `LIBRARY_PATH`, and `LDFLAGS` are outside
the two exact search domains. Canonical post-resolution containment remains
mandatory to reject symlink escape and any future search-behavior drift.

Create `Iconv::Iconv` as `UNKNOWN IMPORTED`, following the hand-authored
imported-target pattern used for `LibXml2::LibXml2`
(`cmake/FindLibXml2.cmake:43-49`) and OpenSSL/CURL
(`CMakeLists.txt:252-268,358-363`). Set only its `IMPORTED_LOCATION` to the
validated canonical `.tbd` path. Fail if the target already exists. This makes
the AC1 name real without trusting CMake's `FindIconv`.

`find_package(Iconv)` is rejected for the two concrete Q4 reasons: a
pre-seeded `Iconv_LIBRARY` is copied verbatim to the imported target, and a
pre-seeded `Iconv_IS_BUILT_IN=TRUE` can produce no library edge at all. No
post-hoc check can make an empty built-in edge satisfy the required selected
SDK artifact.

Do not create a CoreFoundation imported target. Attach the validated canonical
framework path directly to `regorus_ffi`. The asymmetry is deliberate:
`Iconv::Iconv` is an explicit acceptance-contract name and maps naturally to
one imported `.tbd` location, while CoreFoundation is a framework directory
whose full-path link-item treatment is platform-specific. Wrapping it in an
ordinary imported library would invent framework metadata or obscure the
validated path. CMake's conversion of a framework path to `-F`/`-framework`
is Darwin behavior that prep Q4 could not measure on Linux. The reduced
fixture asserts the validated path's property, generated ordering, and
cardinality as emitted on this lode; it does not label that emission a
successful Darwin framework conversion. Native VPE owns that proof.

The exact `FATAL_ERROR` strings are:

* off-Darwin call:
  `"Darwin/arm64 system-link closure failed: helper reached while APPLE is false; call it only from the post-project Apple-guarded SDK path, then retry"`;
* invalid SDK root:
  `"Darwin/arm64 system-link closure failed: NVAT_APPLE_SDKROOT is not an absolute existing directory: '${NVAT_APPLE_SDKROOT}'; select a valid macOS SDK with xcrun and remove the build directory, then retry"`;
* absent regorus owner:
  `"Darwin/arm64 CoreFoundation closure failed: static owner target regorus_ffi does not exist; create the pinned regorus_ffi target before the Apple closure call, then retry"`;
* absent LibXml2 owner:
  `"Darwin/arm64 iconv closure failed: static owner target LibXml2::LibXml2 does not exist; create the selected LibXml2::LibXml2 target before the Apple closure call, then retry"`;
* pre-existing Iconv target:
  `"Darwin/arm64 iconv discovery failed: target Iconv::Iconv already exists without selected-SDK validation; remove the pre-existing Iconv target and configure from a clean build directory, then retry"`;
* missing iconv:
  `"Darwin/arm64 iconv discovery failed: libiconv.tbd was not found in selected SDK '${NVAT_APPLE_SDKROOT}/usr/lib'; select a macOS SDK containing usr/lib/libiconv.tbd and remove the build directory, then retry"`;
* escaped iconv:
  `"Darwin/arm64 iconv discovery failed: resolved path '${_nvat_apple_iconv_real}' is outside selected SDK '${_nvat_apple_sdkroot_real}'; remove host or Homebrew cache inputs and select the macOS SDK, then retry"`;
* missing CoreFoundation:
  `"Darwin/arm64 CoreFoundation discovery failed: CoreFoundation.framework was not found in selected SDK '${NVAT_APPLE_SDKROOT}/System/Library/Frameworks'; select a macOS SDK containing System/Library/Frameworks/CoreFoundation.framework and remove the build directory, then retry"`;
* escaped CoreFoundation:
  `"Darwin/arm64 CoreFoundation discovery failed: resolved path '${_nvat_apple_corefoundation_real}' is outside selected SDK '${_nvat_apple_sdkroot_real}'; remove host or Homebrew cache inputs and select the macOS SDK, then retry"`.

Each follows the repository's
`"<subject> failed: <observation>; <recovery action>, then retry"` form and
identifies Darwin/arm64, the affected dependency, and selected-SDK recovery.

## D4 — Opt-in driver stderr capture and canonical target context

Modify only `_run` and the macOS configure call in
`sol/release/release_rail/driver.py`.

In `_run` at lines 27-31:

* recognize the new behavior only when the caller explicitly supplies
  `stderr=subprocess.PIPE`; do not infer it from `capture_output=True`;
* after a successful child, write any captured stderr to `sys.stderr` with no
  added bytes before returning the unchanged `CompletedProcess`;
* after `CalledProcessError`, write captured stderr to `sys.stderr` once, then
  include its stripped text in the raised `ReleaseError` as well as retaining
  the original exception as `__cause__`;
* retain the current `OSError` conversion and the current path for every call
  that did not explicitly request `stderr=subprocess.PIPE`.

At the macOS configure `_run` in `_build` at lines 268-284, opt in with
`text=True` and `stderr=subprocess.PIPE`; leave stdout inherited. Wrap only
that configure call in `try/except ReleaseError` and raise:
`"${target['id']} native CMake configure failed: ${error}"`, using Python
formatting to substitute the canonical authority ID and inner error. The
outer exception retains the inner `ReleaseError` as its cause.

The resulting operator path is deliberate: CMake stderr is replayed
immediately, and the final CLI error contains both
`macos-arm64 native CMake configure failed` and the helper's complete
`FATAL_ERROR`. Plain `capture_output=True` is not used, because it would hide
both streams unless both were replayed.

All Linux production `_run` sites remain byte-for-byte behaviorally
unchanged: none passes explicit `stderr=subprocess.PIPE`, and the macOS branch
is selected only for a Darwin authority target. The existing
`test_driver.py:717-759` call passes `capture_output=True`, not an explicit
stderr pipe. It therefore retains its current behavior, and
`configure_error.__cause__.stderr` remains the child's stderr.

The timing proof from prep Q7 remains:

1. `transaction.run()` creates the owned `.staging` directory at
   `transaction.py:65-74`.
2. The builder acquires the CA, passes
   `after-dependency-acquisition`, and enters `_build` at
   `driver.py:544-554`.
3. The captured configure runs at `driver.py:268-284`; compilation cannot
   begin until the separate build call at lines 285-289.
4. Product staging begins only after `checkpoint("after-build")` at
   `driver.py:554-555`.
5. Final paths are first mutated by `os.link` after the builder returns, at
   `transaction.py:74-90`.

Thus a helper configure failure occurs after transaction staging began, before
compilation, before product staging, and before every final-path mutation.

## D5 — Preserve the current install/export contract

Take prep Q2 branch (a): make no change to
`nv-attestation-sdk-cpp/cmake/Config.cmake.in`. Owner interfaces do not enter
`nvatTargets.cmake`; its exported `nvat::nvat` still carries only
`INTERFACE_INCLUDE_DIRECTORIES`.

The AC5 consumer fixture must not rely on packages installed on the lode. It
installs the hermetic configured SDK into an isolated prefix, supplies
isolated config stubs for all five packages already demanded by
`Config.cmake.in:7-11`—CURL, LibXml2, OpenSSL, spdlog, and xmlsec—and
configures a minimal `find_package(nvat CONFIG REQUIRED)` consumer against
only that prefix and the stub directory. It separately exercises
`USE_SYSTEM_NVAT=ON` using the installed `nvat` and proves that the CLI adds
neither platform item directly.

Without those stubs, clean-prefix consumption is already broken: CURL fails
first on this lode, and prep Q2 reached the uninstalled spdlog requirement
after stubbing the three preceding packages. That defect predates this
closure, is not caused by the new owner interfaces, and remains out of scope.
Record a future repair of `Config.cmake.in` beside the existing package-helper
removal todo at `nv-attestation-sdk-cpp/CMakeLists.txt:502`; do not combine it
with this implementation.

## D6 — Dedicated test topology

Create `sol/release/tests/test_apple_link_closure.py`. It owns platform-link
closure assertions rather than expanding warning, Apple-toolchain, or header
classification tests.

### D6.1 — Reduced Apple arm and one platform-edge truth source

Use an isolated reduced fixture, never a Darwin-forced full production
configure. A full SDK configure would enter the real pre-project resolver at
`nv-attestation-sdk-cpp/CMakeLists.txt:4-10`, then the post-project
architecture validator would correctly reject this Linux/x86_64 host.

Follow the extraction discipline at
`test_header_consumer_boundary.py:485-620` and the test-side Darwin shim
discipline at `test_apple_cmake.py:21-66`:

* set the Apple/Darwin guard values only inside the reduced test driver;
* add no production test option, environment hook, or bypass;
* include the complete real
  `nvat_apple_system_link_closure.cmake`;
* extract the one complete production `if(APPLE)` call block from
  `nv-attestation-sdk-cpp/CMakeLists.txt`, require exactly one match, and put
  it into the fixture verbatim;
* never retype either owner-interface edge or keep a Python/docs list of
  platform edges.

The new helper module is the single truth source for both platform edges.
The fixture supplies only target shapes and artifacts:

* an imported static `regorus_ffi` stand-in;
* an imported static `LibXml2::LibXml2` stand-in;
* an imported static xmlsec stand-in whose interface creates G6's second path
  to `LibXml2::LibXml2`;
* shared `nvat`, with both owners still private;
* executable `nvattest`, with only shared `nvat` private;
* an isolated fake SDK containing the exact iconv and CoreFoundation layout.

Test-side `APPLE`/Darwin shimming is equivalent in scope to the existing
`NVAT_TEST_HOST_SYSTEM_NAME` script driver: it selects a production guard in
the fixture without adding a product knob. The fixture does not execute
`nvat_resolve_apple_toolchain` or
`nvat_validate_apple_architecture`.

Load codemodel v2 and both generated `link.txt` files. Assert the canonical
iconv and CoreFoundation results occur once, after their final owner
occurrence on `nvat`, while `nvattest` contains neither. Also inspect the two
owner properties and imported `Iconv::Iconv` location. On Linux, accept and
name the literal generated framework-path form; do not assert that it became a
Darwin `-F`/`-framework` pair or that it linked.

### D6.2 — Real Linux negative arm

Use the real production CLI-to-SDK graph through
`warning_fixture_prepare` and `production_configure(query_codemodel=True)`.
Require:

* the new Apple helper call is not traced;
* neither canonical platform target/path/name appears in `nvat` or
  `nvattest` codemodel or `link.txt`;
* the normalized pre-change `nvat` and `nvattest` link vectors remain exact;
* `nv-attestation-cli/CMakeLists.txt`'s link list remains untouched.

This is the every-run proof that new production statements are inert on
Linux.

### D6.3 — Discovery rejection matrix

Each subcase starts from a fresh fixture and poisons one input only. For
default-path/environment cases, omit the corresponding selected-SDK artifact
while placing a plausible artifact at the poison location. Correct behavior
is the exact D3 selected-SDK-missing diagnostic, proving the poison was not
accepted. For an SDK-contained symlink to an external location, correct
behavior is the exact outside-SDK diagnostic.

| independent poison | fixture input | required observation |
| --- | --- | --- |
| `/opt/homebrew` | fake `libiconv.tbd` only under `/opt/homebrew/lib` | D3 missing-iconv diagnostic |
| `/usr/local` | fake `libiconv.tbd` only under `/usr/local/lib` | D3 missing-iconv diagnostic |
| arbitrary `/Library` | fake `CoreFoundation.framework` only under a temporary modeled `/Library/Frameworks` | D3 missing-CoreFoundation diagnostic |
| host `/usr/lib` | host-style iconv candidate exposed through one search input | D3 missing-iconv diagnostic |
| temp/build roots | both fake artifacts beneath the fixture build directory | the dependency-specific D3 missing diagnostic |
| pre-seeded result variables | independently set each dedicated `NVAT_APPLE_*` cache result outside the SDK | clearing defeats the seed; the dependency-specific D3 missing diagnostic |
| pre-existing `Iconv::Iconv` | define an imported target before the real helper | D3 pre-existing-target diagnostic |
| `Iconv_LIBRARY` | pre-seed a Homebrew dylib path | ignored because `FindIconv` is never called; D3 missing-iconv diagnostic |
| `Iconv_IS_BUILT_IN=TRUE` | pre-seed the built-in result | ignored because `FindIconv` is never called; D3 missing-iconv diagnostic |
| `CMAKE_PREFIX_PATH` | point only at a fake host prefix | dependency-specific D3 missing diagnostic |
| `CMAKE_LIBRARY_PATH` | point only at a fake host library directory | D3 missing-iconv diagnostic |
| `CMAKE_FRAMEWORK_PATH` | point only at a fake host framework directory | D3 missing-CoreFoundation diagnostic |
| `CMAKE_FIND_ROOT_PATH` | re-root to a fake host tree | dependency-specific D3 missing diagnostic |
| `LIBRARY_PATH` | environment points at fake host iconv | D3 missing-iconv diagnostic |
| `LDFLAGS` | environment injects host `-L`/`-F`, iconv, and framework tokens | dependency-specific D3 missing diagnostic |
| Homebrew prefix defaults | independently model `/opt/homebrew` and Intel Homebrew `/usr/local` through system-prefix variables | dependency-specific D3 missing diagnostic |
| SDK symlink escape | selected-SDK candidate resolves to each foreign root above | dependency-specific D3 outside-SDK diagnostic |

Also cover the D1 structural failures independently: `APPLE` false, missing
or relative SDK root, absent regorus owner, absent LibXml2 owner, missing
iconv, missing CoreFoundation, and both symlink escapes.

### D6.4 — AC4 policy rejection

Add
`test_policy_rejects_linker_escape_hatches_and_non_sdk_inputs`. It inspects
the helper, both product CMakeLists, generated target properties, codemodel,
and `link.txt` surfaces and rejects:

* `-undefined dynamic_lookup`, `-flat_namespace`, and any
  unresolved-symbol allowance;
* `file(GLOB...)`, wildcard artifact discovery, or other globs;
* copied/bundled iconv or CoreFoundation dylibs and copy/install commands for
  either platform dependency;
* Homebrew or `/usr/local` `-L`/`-F` prefixes;
* bare `-framework CoreFoundation` authored in production rather than the
  validated resolved framework path;
* direct CoreFoundation or iconv items on `nvattest`;
* any new direct platform item in
  `nv-attestation-cli/CMakeLists.txt`'s link list.

The test derives the two expected platform results from the real helper's
configured owner properties. It does not declare a duplicate platform-edge
list.

### D6.5 — CMake 3.11 arm

Run the same extracted helper and production call block in an isolated
fixture under the current CMake on every rail run and under real CMake 3.11
when available. Reuse the discovery behavior from
`test_header_consumer_boundary.py:588-620`:

1. accept `NVAT_TEST_CMAKE_311` only if `--version` identifies 3.11.x;
2. otherwise try `cmake3.11`, `cmake-3.11`, and `cmake` from PATH;
3. fail, rather than skip, if an explicit override is not a real 3.11;
4. when no engine is found, skip loudly with
   `"real CMake 3.11 not available; set NVAT_TEST_CMAKE_311 to a 3.11 executable"`;
5. invoke an old engine from its build directory with the positional source
   path, require fixture output `ENGINE=3.11.x`, and require
   `CMakeCache.txt`.

The provisioned value from prep Q5 is
`/home/extro/.local/opt/cmake-3.11.4/bin/cmake`. The fixture proves the helper,
imported `Iconv::Iconv`, guarded call, owner interfaces, and generated link
structure only. It explicitly does not run either full production tree or
claim that their `FetchContent_MakeAvailable`/`list(PREPEND)` incompatibility
was fixed.

### D6.6 — Install/export and installed CLI arms

Extend the test module with:

* `test_install_export_omits_private_platform_closure`;
* `test_config_stubbed_clean_prefix_consumer_configures`;
* `test_use_system_nvat_cli_has_no_direct_platform_edges`.

The first performs a real `cmake --install` from the hermetic configured
fixture and requires generated `nvatTargets.cmake` to contain neither platform
dependency or host/SDK path. The second supplies exactly the five D5 config
stubs and configures a minimal linked consumer. The third uses the installed
library through the existing `USE_SYSTEM_NVAT=ON` production path and proves
the CLI direct link remains only installed `nvat` plus its existing
non-platform dependencies.

### D6.7 — Shared support changes

Keep `sol/release/tests/cmake_support.py` assertion-free and minimal:

* add an optional `env=` argument to `production_configure` and pass it only
  to `subprocess.run`; existing callers and its return tuple remain unchanged;
* add one installer preparer that materializes only the configure-generated
  nvat install outputs needed by `cmake --install` and returns an isolated
  prefix;
* add one package-config-stub writer parameterized by package names, with no
  platform-edge names or acceptance assertions.

The new test supplies the five package names and all expected closure data.
Extend the existing configure/install harness; do not fork a second
production configure implementation.

### D6.8 — AC7 hostile child and driver integration

Add a direct driver test
`test_macos_configure_error_combines_target_and_helper_diagnostic`. It gives
the real `_build` macOS branch an isolated source fixture whose configure
includes the real helper and extracted call but lacks one selected-SDK
dependency. It requires replayed stderr and `str(ReleaseError)` both to
contain the exact helper diagnostic, and the latter also to contain canonical
`macos-arm64`.

Extend
`test_driver.py::test_macos_build_failures_use_driver_build_seam_and_never_publish`
and its existing
`assert_release_failure_preserves_quartet` helper at lines 275-321. The new
row:

* creates the reduced real-helper fixture after release has entered the owned
  staging transaction;
* overrides
  `CMAKE_CXX_CREATE_SHARED_LIBRARY`/`CMAKE_CXX_LINK_EXECUTABLE` only in that
  fixture;
* launches a real build subprocess;
* requires the hostile recorder itself to write and emit
  `NVAT_TEST_APPLE_LINK_RECORDER_REACHED`;
* requires that child to exit nonzero;
* propagates the resulting real `driver._run` `ReleaseError`;
* reuses the retained-quartet and absent-final-quartet assertions unchanged.

A Python mock marker is not evidence that the subprocess ran. The child's
file/stderr marker and nonzero status are the evidence. The passive
codemodel/`link.txt` mechanism remains the normal structural proof; the rule
override exists only for this failure path and never claims Apple linkage.

## D7 — Rebase and strengthen baseline stability

In `sol/release/tests/test_baseline_stability.py`, change `BASELINE` at line
26 from `22065d840cbcc8ff457ac224da0df299a4e23b3f` to
`b75e95ae0c08ac6eaa05673a0cf227b8723e2b58`.

Retain every existing target-authority, target-ID, dependency-input,
per-path/global coordinate, project-version, release-version, Rust wiring,
header-helper, and compiled-warning assertion. Add:

* an explicit extracted assertion that `regorus` remains
  `https://github.com/microsoft/regorus.git` at `regorus-v0.4.0`, in addition
  to the generic coordinate comparison;
* an exact baseline/current comparison of the native
  `corrosion_import_crate` wiring at
  `nv-attestation-sdk-cpp/CMakeLists.txt:66-72`, including external regorus
  manifest, Release profile, `regorus-ffi`, `regorus/semver`, and `staticlib`;
* a tracked local Rust inventory comparison for exactly
  `nv-attestation-sdk-rust/Cargo.toml`,
  `nv-attestation-sdk-rust/nv-attestation-sdk-sys/Cargo.toml`,
  `nv-attestation-sdk-rust/nv-attestation-sdk-sys/build.rs`, and
  `nv-attestation-sdk-rust/nv-attestation-sdk/Cargo.toml`;
* explicit absence of any `Cargo.lock` in both the baseline tree and current
  tree.

The four local Rust files are stability inventory, not inputs to this native
CLI→C++ SDK target. The native target consumes the separately pinned external
regorus manifest named by `corrosion_import_crate`; the test and diagnostic
must preserve that distinction from prep Q8.

Add one licensing-stability test that byte-compares root `LICENSE` against
the rebased baseline and compares the notices generator's ordered runtime
dependency inventory and rendered notices bytes between baseline and current
sources. This covers the same runtime dependency set plus the fixed Mozilla
CA notice at `generate-dependencies.py:133-156`.

Add
`test_apple_link_closure_helper_declares_no_dependency_coordinates`, mirroring
the token guard at current lines 184-195. It rejects
`FetchContent_Declare`, `ExternalProject_Add`, `GIT_REPOSITORY`, `GIT_TAG`,
`URL`, and `URL_HASH` in the new helper. Prep Q8 proves the helper's
`cmake/` placement is not scanned by the generator; the explicit guard
prevents that placement from hiding a coordinate.

Do not change `targets.toml`, dependency declarations, the four ExternalProject
bodies, `NVAT_EP_ENV_COMMAND`, `_EP_*`, warning policy, licensing files, or
the generator.

## D8 — Minimal README obligation

In `sol/release/README.md`, under `### Post-ship VPE native work`, add these
exact two sentences immediately after the current macOS operator sentence
ending at lines 138-139 and before
`Each native driver invocation`:

> VPE must also rerun Pro5E on the native arm64 archive and record both final
> link commands: `nvat` must contain the selected-SDK CoreFoundation and iconv
> closure exactly once after their static owners, while `nvattest` must
> contain neither as a direct link item. This Linux lode observed only
> generated CMake link structure; it did not prove native Apple linkage.

This records the observed system-link requirement, assigns the native proof
to VPE, and does not claim success. It leaves the existing text
`verbose fmt/spdlog/nvat/nvattest warning flags` byte-for-byte intact, so
`test_warning_policy.py:356-364` still derives the same four-owner set. It also
leaves both exact phrases required by
`test_header_consumer_boundary.py:706-714` intact:
`ordinary first-party/generated/installed roots` and
`system-classified pinned fmt/spdlog roots`.

Add
`test_apple_link_closure.py::test_readme_assigns_native_link_closure_to_vpe`
to require `Pro5E`, both final link commands, the owner-relative/direct-item
distinction, and the explicit no-native-proof sentence. Do not modify the two
existing README parsers.

## D9 — Requalification and allowlist disposition

No CSO or CLO requalification trigger is introduced:

* no dependency coordinate, license inventory, vendored artifact, target ID,
  architecture, deployment floor, package layout, install-name, RPATH, or
  external-root policy changes;
* iconv and CoreFoundation are selected from the already-authorized Apple SDK
  and remain Apple platform dependencies;
* no new runtime root is requested.

The current macOS allowlist already permits only Apple system libraries and
frameworks through `prefix:/usr/lib/` and
`prefix:/System/Library/Frameworks/`
(`sol/release/allowlists/macos-arm64.txt:6-8`). The expected iconv and
CoreFoundation runtime identities fall under those existing roots, so no
allowlist edit is needed.

Any Homebrew, `/usr/local`, arbitrary `/Library`, build-tree, or other
non-platform input is simultaneously:

1. a product failure—configure-time selected-SDK validation or the final
   Mach-O gate must reject it; and
2. a requalification trigger—dependency provenance or external-root closure
   has changed from the authorized platform-only contract.

Tests must never normalize such an input into an accepted result.

## D10 — Acceptance inventory, boundaries, and risks

### AC1–AC8 test map

| acceptance clause | named test inventory | required closure |
| --- | --- | --- |
| AC1 — shared `nvat` receives one CoreFoundation item after `regorus_ffi` and one `Iconv::Iconv` item after the final LibXml2 owner, while `nvattest` receives neither directly | `test_apple_link_closure.py::test_reduced_apple_fixture_orders_each_owner_edge_once`; `::test_linux_production_link_vectors_are_unchanged`; `::test_production_has_one_guarded_call_and_one_edge_truth_source` | Uses real helper, extracted real call, two LibXml2 paths, codemodel, both `link.txt` files, and Q1 private propagation. |
| AC2 — the closure is Apple-only, one-call, owner-attached, fail-closed, and leaves Linux/product link lists unchanged | `::test_helper_fails_closed_for_platform_sdk_target_and_artifact_errors`; `::test_linux_production_link_vectors_are_unchanged`; `::test_production_has_one_guarded_call_and_one_edge_truth_source` | Covers off-Darwin fatal behavior, exact owner/target diagnostics, one include/call, two owner properties, no direct `nvat`/`nvattest` additions, and real Linux inertness. |
| AC3 — both dependencies resolve only from the selected SDK despite every cache, prefix, environment, Homebrew, host, build-root, and symlink poison | `::test_selected_sdk_discovery_rejects_each_poison_independently`; `::test_iconv_target_collision_and_findiconv_inputs_fail_closed` | Runs every D6.3 row separately and requires the exact dependency-specific missing/outside/target diagnostic. |
| AC4 — no unresolved-symbol escape, flat namespace, glob, copied dylib, host `-L`/`-F`, bare authored framework token, or direct CLI platform item is introduced | `::test_policy_rejects_linker_escape_hatches_and_non_sdk_inputs` | Reads production source and generated link surfaces; derives expected edges only from the real helper-owned properties. |
| AC5 — private owner interfaces do not leak into exports; config-stubbed package consumption and `USE_SYSTEM_NVAT=ON` work without direct CLI platform links | `::test_install_export_omits_private_platform_closure`; `::test_config_stubbed_clean_prefix_consumer_configures`; `::test_use_system_nvat_cli_has_no_direct_platform_edges` | Performs real install/export/consumer configure, supplies exactly the five pre-existing package requirements, and keeps the current spdlog package defect explicitly out of scope. |
| AC6 — the exact extracted helper/call works under release CMake and a real 3.11 engine when provisioned, without claiming the wider graph is compatible | `::test_extracted_link_closure_with_release_cmake`; `::test_extracted_link_closure_with_real_cmake_311_when_available`; `::test_helper_avoids_post_311_commands` | Same extracted source and structural assertions in both engines; loud optional skip and invalid-override failure. |
| AC7 — native configure errors combine canonical target context with replayed helper text, and a real hostile child after staging cannot publish or damage a quartet | `test_driver.py::test_macos_configure_error_combines_target_and_helper_diagnostic`; extended `::test_macos_build_failures_use_driver_build_seam_and_never_publish` | Separates configure diagnostic composition from hostile-child execution, requires the child's own marker/nonzero exit, and reuses retained/absent quartet assertions. |
| AC8 — authority, pins, Rust/licensing inventory, scanner boundaries, VPE wording, requalification rules, and native proof obligations remain closed | retained and extended `test_baseline_stability.py`; `test_apple_link_closure.py::test_readme_assigns_native_link_closure_to_vpe`; existing Mach-O/allowlist tests | Rebases only to the authorized prep tip, explicitly pins regorus/Rust/Cargo.lock/licensing/helper inputs, preserves README parsers, and leaves native success to Pro5E/VPE. |

### Hard boundaries

* One helper, one public zero-argument function, one Apple-guarded call, and
  one production truth source for both edges.
* No product option, registry, loop, fallback, compatibility shim, production
  test hook, or target-discovery framework.
* No change to `nv-attestation-cli/CMakeLists.txt`, especially its link list.
* No change to `Config.cmake.in`, `targets.toml`, either allowlist, the four
  ExternalProject bodies, `NVAT_EP_ENV_COMMAND`, `_EP_*`, warning policy,
  install-name/RPATH policy, or the macOS 14.0 floor.
* No unresolved-symbol allowance, flat namespace, glob, copied platform
  library, or host/Homebrew search prefix.
* No claim that the wider graph is CMake-3.11-compatible.
* No native macOS link claim from a Linux fixture, codemodel, `link.txt`, or
  recording rule.

### Risks and settled questions

1. **Darwin framework conversion is unobserved here.** The reduced fixture can
   prove the canonical framework path, owner property, order, cardinality, and
   privacy, but only native CMake/AppleClang can prove the final
   `-F`/`-framework` form and successful resolution.
2. **SDK layout can change.** The exact `usr/lib/libiconv.tbd` and
   `System/Library/Frameworks/CoreFoundation.framework` contract intentionally
   fails closed on an SDK that changes layout. Such a change requires native
   investigation, not a fallback to Homebrew or default search.
3. **Deduplication is generator-sensitive.** Q3 measured the real graph on
   this CMake/Linux lode. The reduced test prevents local structural drift;
   Pro5E must confirm the native generator's final commands.
4. **Captured configure stderr appears twice in an eventual CLI failure.**
   Immediate replay preserves operator visibility and inclusion in
   `ReleaseError` makes the combined diagnostic assertable. This duplication
   is the required tradeoff and is Mac-configure-only.
5. **The installed package config is already incomplete.** Config stubs make
   the export-leak regression test meaningful without pretending the current
   spdlog defect is repaired.
6. **The real-3.11 fixture is deliberately reduced.** It proves only the
   extracted helper and wiring; full production still stops on
   `FetchContent_MakeAvailable` and `list(PREPEND)`.

No implementation choice remains open. These are proof obligations and
fail-closed risks, not reasons to widen scope.

### What this lode can and cannot prove

This Linux lode can prove:

* the helper is the only edge/discovery source and the SDK has one guarded
  call after both owners;
* exact lookup domains, cache clearing, realpath containment, independent
  poison rejection, and exact diagnostics;
* modeled owner-relative order/cardinality and `nvattest` privacy through
  codemodel and generated `link.txt`;
* the real Linux production graph and link vectors are unchanged;
* install/export non-leakage, a five-stub package consumer, and installed-nvat
  CLI privacy;
* real CMake 3.11 execution of the extracted closure when
  `NVAT_TEST_CMAKE_311` is supplied;
* driver stderr replay/error composition and transaction preservation after a
  real hostile subprocess failure;
* baseline, Rust, Cargo.lock, licensing, scanner, authority, documentation,
  and allowlist invariants.

The following remain VPE-owned and must all be recorded for the native
`macos-arm64` result:

* the Pro5E rerun;
* `nm` and link-map evidence assigning unresolved/fulfilled symbols to the
  correct static owners;
* both final native link commands, including exact selected-SDK paths,
  owner-relative order, cardinality, and absence from direct `nvattest`
  inputs;
* successful native CoreFoundation framework-path conversion and iconv stub
  linkage;
* final Mach-O architecture, deployment floor, relocatability, RPATH,
  install-name, and allowed dependency closure;
* an installed clean-prefix consumer using real required packages and the
  installed-nvat CLI smoke;
* archive/layout gates and hostile-CA gates;
* a byte-identical second clean rebuild;
* agreement of all three manifests and their sidecars.

Nothing produced on this lode substitutes for those native observations.

## File-by-file implementation plan, in dependency order

1. **`nv-attestation-sdk-cpp/cmake/nvat_apple_system_link_closure.cmake`
   (new).** Add D1's guarded zero-argument function, exact D3 discovery and
   diagnostics, imported `Iconv::Iconv`, and the two owner-property appends.
2. **`nv-attestation-sdk-cpp/CMakeLists.txt`.** Include the helper beside the
   existing modules and add the one post-owner `if(APPLE)` call. Do not alter
   `nvat` links, dependency acquisition, ExternalProjects, or Linux behavior.
3. **`sol/release/tests/cmake_support.py`.** Add optional environment plumbing
   and the minimal assertion-free install/config-stub utilities while
   preserving all existing callers and return contracts.
4. **`sol/release/tests/test_apple_link_closure.py` (new).** Add real-source
   extraction, the reduced Apple and real Linux arms, codemodel/`link.txt`
   assertions, failure and poison matrices, AC4 source policy, install/export
   and installed CLI coverage, modern/real-3.11 fixtures, and README assertion.
5. **`sol/release/release_rail/driver.py`.** Add explicit-stderr-only replay
   and error folding in `_run`; opt in and add canonical target context only
   at the macOS configure call.
6. **`sol/release/tests/test_driver.py`.** Add the combined configure
   diagnostic test and the real hostile recorder row through the shared
   quartet-preservation helper.
7. **`sol/release/tests/test_baseline_stability.py`.** Rebase to `b75e95a…`,
   retain existing comparisons, and add the exact regorus, Rust/Cargo.lock,
   licensing, and helper-coordinate guards from D7.
8. **`sol/release/README.md`.** Add only D8's two VPE sentences, preserving
   both existing parsed phrases.
9. **Implementation-stage verification.** Run only the directed focused
   modules and repository gates through `hop check`, with
   `NVAT_TEST_CMAKE_311=/home/extro/.local/opt/cmake-3.11.4/bin/cmake` for the
   non-skipped old-engine arm. Record Linux evidence as structural only; do
   not mark the work native-complete until VPE records every item above.
