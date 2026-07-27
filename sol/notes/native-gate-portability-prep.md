# nvattest native-gate portability closure prep

Research captured on the Linux x86_64 lode
`/home/extro/.hopper/worktrees/pqzizkwa` on 2026-07-26. The repository tip was
exactly `a17e2c14f2e62003a9e2f668d9f8089ebf4ef29c`, and the tree was clean
before this note. No product or test file was changed. The sole repository
file created is this note. The forced-host shim and CMake measurement were
confined to
`/home/extro/.local/share/hopper/lodes/pqzizkwa/scratchpad`; their temporary
files were removed after capture.

The current production path is:

* The SDK fetches pinned Corrosion at
  `6be991bb34c348dfb8344be22f3606288ea5c7fd`, imports only the
  `regorus-ffi` `staticlib`, and receives CMake target `regorus_ffi`
  (`nv-attestation-sdk-cpp/CMakeLists.txt:51-73`). On Apple, the system-link
  helper runs after Corrosion and the vendored LibXml2/xmlsec targets exist,
  but before `nvat` is created
  (`nv-attestation-sdk-cpp/CMakeLists.txt:356-378,400-431`).
* The helper validates the selected SDK, resolves selected-SDK iconv and
  CoreFoundation, appends those artifacts to `LibXml2::LibXml2` and
  `regorus_ffi`, and never currently reads a link-directory property
  (`nv-attestation-sdk-cpp/cmake/nvat_apple_system_link_closure.cmake:3-127`).
  Shared `nvat` then links both owners `PRIVATE`
  (`nv-attestation-sdk-cpp/CMakeLists.txt:484-502`).
* `xmlsec::xmlsec` has its own interface edge to `LibXml2::LibXml2`
  (`nv-attestation-sdk-cpp/cmake/Findxmlsec.cmake:22-56`). The CLI embeds the
  SDK, aliases real `nvat` as `nvat::nvat`, and links only that shared target,
  json, and CLI11 into `nvattest`
  (`nv-attestation-cli/CMakeLists.txt:54-113`).
* Apple `nvat` authors its install-name directory but no rpath
  (`nv-attestation-sdk-cpp/CMakeLists.txt:433-444`). `nvattest` alone authors
  `INSTALL_RPATH "@executable_path/../lib"`
  (`nv-attestation-cli/CMakeLists.txt:114-120`). The release driver configures
  and builds those targets natively, stages the target-table members, and
  invokes the binary gate before and after archive extraction
  (`sol/release/release_rail/driver.py:251-321,370-383,570-627`).
* `gate_macho()` rejects any library `LC_RPATH`, requires an executable to
  have exactly the target-table rpath, and compares deployment and install-ID
  values to the same target record
  (`sol/release/release_rail/gate.py:85-132`). That is why the observed
  Corrosion-derived rpath is a real policy failure, not a gate defect.

## Baselines

The explicitly requested canonical baseline was:

```text
$ hop check -n 300 -- make rail-test
hop check: `make rail-test` exited 0
python3 -m unittest discover -s sol/release/tests -p 'test_*.py'
.......................s...........................................-- The CXX compiler identification is GNU 13.3.0
-- Detecting CXX compiler ABI info
-- Detecting CXX compiler ABI info - done
-- Check for working CXX compiler: /usr/bin/c++ - skipped
-- Detecting CXX compile features
-- Detecting CXX compile features - done
-- ENGINE=3.31.10
-- Configuring incomplete, errors occurred!
..............................s.............................................
----------------------------------------------------------------------
Ran 143 tests in 16.215s

OK (skipped=2)
shellcheck $(find sol -type f -name '*.sh' -print | sort)
```

This exactly matches the requested 143-test, two-skip baseline.

For the forced Linux aarch64 observation, scratch
`sitecustomize.py` replaced `platform.machine` with a function returning
`"aarch64"`, and its directory was the first and only `PYTHONPATH` element.
The command and exact final output tail were:

```text
$ hop check -n 500 -- env \
    PYTHONPATH=/home/extro/.local/share/hopper/lodes/pqzizkwa/scratchpad/forced-aarch64 \
    make rail-test
----------------------------------------------------------------------
Ran 143 tests in 16.717s

FAILED (failures=3, errors=2, skipped=2)
make: *** [Makefile:38: rail-test] Error 1
```

The five emitted case headers, exactly, were:

```text
ERROR: test_ownership_failure_precedes_dist_creation (test_driver.DriverRuntimeTest.test_ownership_failure_precedes_dist_creation)
ERROR: test_release_threads_one_selection_through_every_container_command (test_driver.DriverRuntimeTest.test_release_threads_one_selection_through_every_container_command)
FAIL: test_accessor_reports_incompatible_forced_target (test_authority.AuthorityTest.test_accessor_reports_incompatible_forced_target)
FAIL: test_dirty_source_tree_fails_before_dist_exists (test_driver.DriverPreflightTest.test_dirty_source_tree_fails_before_dist_exists)
FAIL: test_missing_target_fails_before_dist_exists (test_driver.DriverPreflightTest.test_missing_target_fails_before_dist_exists)
```

There was no additional or missing case. The nested `rail.py` process in the
authority case reported `host Linux/aarch64` and recovery
`HOST_TARGET=linux-aarch64`, proving that its `sys.executable` child inherited
the scratch `PYTHONPATH` host predicate.

Without `NVAT_TEST_CMAKE_311`, the two optional tests skip exactly:

```text
test_extracted_link_closure_with_real_cmake_311_when_available (test_apple_link_closure.AppleLinkClosureTest.test_extracted_link_closure_with_real_cmake_311_when_available) ... skipped 'real CMake 3.11 not available; set NVAT_TEST_CMAKE_311 to a 3.11 executable'
test_extracted_boundary_fixture_with_real_cmake_311_when_available (test_header_consumer_boundary.HeaderConsumerBoundaryTest.test_extracted_boundary_fixture_with_real_cmake_311_when_available) ... skipped 'real CMake 3.11 not available; set NVAT_TEST_CMAKE_311 to a 3.11 executable'

----------------------------------------------------------------------
Ran 2 tests in 1.253s

OK (skipped=2)
```

With
`NVAT_TEST_CMAKE_311=/home/extro/.local/opt/cmake-3.11.4/bin/cmake`, both pass:

```text
test_extracted_link_closure_with_real_cmake_311_when_available (test_apple_link_closure.AppleLinkClosureTest.test_extracted_link_closure_with_real_cmake_311_when_available) ... ok
test_extracted_boundary_fixture_with_real_cmake_311_when_available (test_header_consumer_boundary.HeaderConsumerBoundaryTest.test_extracted_boundary_fixture_with_real_cmake_311_when_available) ... ok

----------------------------------------------------------------------
Ran 2 tests in 1.799s

OK
```

## P1 — Corrosion ownership

Corrosion source is reachable offline in two neighboring FetchContent caches:

```text
/home/extro/.hopper/worktrees/d54akj4f/build/_deps/corrosion-src
/home/extro/.hopper/worktrees/gas3tyru/build/_deps/corrosion-src
```

Both are clean checkouts at exactly
`6be991bb34c348dfb8344be22f3606288ea5c7fd`. The pinned source is conclusive:

1. Corrosion changes Cargo target name `regorus-ffi` to
   `regorus_ffi`, creates `regorus_ffi` as an `INTERFACE` library, and passes
   it to `_corrosion_add_library_target`
   (`/home/extro/.hopper/worktrees/gas3tyru/build/_deps/corrosion-src/cmake/CorrosionGenerator.cmake:130-151`).
2. For `staticlib`, Corrosion creates imported GLOBAL STATIC target
   `regorus_ffi-static`. On macOS, because this SDK import does not pass
   `NO_STD`, it directly sets:

   ```cmake
   set_property(TARGET regorus_ffi-static
     PROPERTY INTERFACE_LINK_DIRECTORIES
       "/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/usr/lib")
   ```

   The generic source is at
   `/home/extro/.hopper/worktrees/gas3tyru/build/_deps/corrosion-src/cmake/Corrosion.cmake:445-469`.
3. Because this import requests only `staticlib`, the `regorus_ffi`
   `INTERFACE` facade links `regorus_ffi-static` at
   `Corrosion.cmake:501-511`. No alias is involved. The property therefore
   has interface visibility on the imported static owner/intermediate,
   **not** on `regorus_ffi` itself.

Corrosion contains equivalent generic setters for shared-library and binary
targets (`Corrosion.cmake:472-499,514-544`), but neither applies to this
staticlib-only import. The other Command Line Tools occurrence is a
conditional Cargo/build-script `LIBRARY_PATH` environment value for older
Darwin system versions (`Corrosion.cmake:706-719`), not a target property or
consumer edge. `LibXml2::LibXml2` and `xmlsec::xmlsec` are never targets of
any Corrosion setter. They are created by the SDK and Find module instead
(`nv-attestation-sdk-cpp/CMakeLists.txt:356-370`;
`nv-attestation-sdk-cpp/cmake/Findxmlsec.cmake:22-56`). The current product
helper changes only their `INTERFACE_LINK_LIBRARIES`, never their link
directories
(`nv-attestation-sdk-cpp/cmake/nvat_apple_system_link_closure.cmake:116-123`).

This reveals a material fixture mismatch: current
`ReducedAppleFixture` creates `regorus_ffi` directly as imported STATIC
(`sol/release/tests/test_apple_link_closure.py:166-169`), while pinned
Corrosion creates an INTERFACE facade over imported
`regorus_ffi-static`. The regression must model or reach the real owner chain;
injecting and clearing only the current fixture target would not protect
production.

Before this new note was added, repository grep found no exact
`INTERFACE_LINK_DIRECTORIES`, `CommandLineTools`, or standalone-word
`LINK_DIRECTORIES` in tracked production, tests, or notes. A raw substring
search for `LINK_DIRECTORIES` did have one unrelated hit inside the longer
documentation symbol
`CMAKE_LANG_IMPLICIT_LINK_DIRECTORIES` in
`sol/notes/mac-native-link-closure-prep.md:465`; therefore the scope's
“nowhere” claim is true for the standalone property/token, but not literally
true for an unbounded substring grep.

The source finding agrees with the authoritative Pro5E observation supplied
to this prep: the Rust static owner carried the property, and the `nvat` link
contained exactly:

```text
-L/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/usr/lib
-Wl,-rpath,/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/usr/lib
```

**Observed on this lode:** two clean offline checkouts of the exact pin,
target construction and property source, repository grep, and the real
reduced-harness propagation in P3. **Accepted native input:** the supplied
Pro5E target-property and link-command observation. **Unobserved on this
lode:** generated target properties or a native link on macOS.

## P2 — Discriminating directory cases

> **Superseded by design D1.** The two-value recognizer proposed below was
> narrowed before implementation. The shipped helper recognizes only
> `/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/usr/lib`; it does not
> recognize `${NVAT_APPLE_SDKROOT}/usr/lib`.

The safe rule is exact allowlisting followed by all-or-nothing clearing. Read
the imported static owner's raw `INTERFACE_LINK_DIRECTORIES`; validate every
list element without normalizing malformed or unknown input into a known
value; only then set that property to the empty string. The two and only two
recognized nonempty strings are:

```text
/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/usr/lib
${NVAT_APPLE_SDKROOT}/usr/lib
```

The first is the exact pinned-Corrosion metadata proven in P1. The second is
the exact selected-SDK system-library directory already controlled by the
helper. Both are metadata, not artifacts: the selected Apple libraries are
linked by validated absolute artifact paths
(`nvat_apple_system_link_closure.cmake:44-75,78-113`). Retaining either
directory is unnecessary and can become both `-L` and a build rpath, so a
fully known property is neutralized.

The complete disposition is:

| property state or element | disposition | reason |
| --- | --- | --- |
| property unset (`<var>-NOTFOUND`) | succeed after the intended owner exists and the property was actually read | there is no directory usage requirement to propagate |
| whole property exactly empty | succeed/leave empty after inspection | this is a verified empty property, not a malformed list element |
| exact observed Command Line Tools path | neutralize | exact metadata emitted by the pinned Corrosion source |
| exact `${NVAT_APPLE_SDKROOT}/usr/lib` | neutralize | exact selected-SDK metadata; absolute selected artifacts remain authoritative |
| a list containing only the two known strings, in either order or with repeats | neutralize the entire property | every element is independently known; clearing avoids both `-L` and rpath |
| `/opt/homebrew/lib` or any other arbitrary absolute path | `FATAL_ERROR` naming the exact entry | silently clearing arbitrary user or host search policy would hide contamination |
| any unrecognized `*.sdk/usr/lib` | `FATAL_ERROR` | SDK-shaped is not identity; broad suffix acceptance would silently bless a different SDK |
| a list mixing one known and one unknown entry | `FATAL_ERROR`, clear nothing | all-or-nothing validation prevents laundering the unknown entry through a known one |
| leading, trailing, or doubled separators producing an empty element | `FATAL_ERROR` | an empty list member is malformed even though a wholly empty property is safe |
| any relative entry | `FATAL_ERROR` | it is neither exact known metadata nor a stable SDK identity |
| an entry with an embedded/escaped `;` | `FATAL_ERROR` | semicolon is CMake's list boundary; it must not be normalized into apparent known entries |
| generator expression, whitespace variation, trailing slash, or other spelling | `FATAL_ERROR` | exact identity is intentionally narrow; no speculative equivalent forms are accepted |

The selected SDK path may contain spaces because equality and property access
remain quoted. A selected SDK path containing a semicolon is deliberately not
recognized by this rule. The known Command Line Tools string need not exist on
the Linux fixture: as verified in the scope and P3, it is a target-property
string.

This read/validate/clear operation belongs before the helper appends the
selected-SDK system libraries, but after both the `regorus_ffi` facade and its
`regorus_ffi-static` owner have been verified. No directory should be cleared
on the first bad entry.

**Observed on this lode:** exact pinned producer string, exact selected-SDK
variable, CMake list/property propagation, and mixed-surface behavior in P3.
**Design requirement rather than native observation:** the fail-closed
dispositions for hostile and malformed values.

## P3 — Propagation on the real reduced harness

The requested probe used `ReducedAppleFixture.before_call`
(`sol/release/tests/test_apple_link_closure.py:108-199`) to inject:

```cmake
set_property(TARGET regorus_ffi PROPERTY
  INTERFACE_LINK_DIRECTORIES
  "/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/usr/lib")
```

It requested File API codemodel v2 through the fixture's real `configure()`
path (`test_apple_link_closure.py:201-227`) and configured successfully with
CMake 3.31.10. This measures the existing reduced target shape described in
P1; it does not replace the requirement to make that shape faithful during
implementation.

The exact `nvat.commandFragments` entries attributable to the directory were:

```json
[
  {
    "backtrace": 2,
    "fragment": "-L/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/usr/lib",
    "role": "libraryPath"
  },
  {
    "fragment": "-Wl,-rpath,/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/usr/lib:/home/extro/.local/share/hopper/lodes/pqzizkwa/scratchpad/tmpyz1bppsr/MacOSX.sdk/System/Library/Frameworks",
    "role": "libraries"
  }
]
```

Consequently `library_fragments(nvat)` contains the combined literal rpath
but not the `-L` fragment, because that helper selects only role
`"libraries"` (`test_apple_link_closure.py:70-75`). The broader
`all_link_fragments(nvat)` contains both:

```text
-L/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/usr/lib
-Wl,-rpath,/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/usr/lib:/home/extro/.local/share/hopper/lodes/pqzizkwa/scratchpad/tmpyz1bppsr/MacOSX.sdk/System/Library/Frameworks
```

The exact raw `nvat` link file also contains both:

```text
/usr/bin/c++ -fPIC -Wl,--dependency-file=CMakeFiles/nvat.dir/link.d -shared -Wl,-soname,libnvat.so -o libnvat.so CMakeFiles/nvat.dir/nvat.cpp.o   -L/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/usr/lib  -Wl,-rpath,/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/usr/lib:/home/extro/.local/share/hopper/lodes/pqzizkwa/scratchpad/tmpyz1bppsr/MacOSX.sdk/System/Library/Frameworks /home/extro/.local/share/hopper/lodes/pqzizkwa/scratchpad/tmpyz1bppsr/libxmlsec1.a /home/extro/.local/share/hopper/lodes/pqzizkwa/scratchpad/tmpyz1bppsr/libxml2.a /home/extro/.local/share/hopper/lodes/pqzizkwa/scratchpad/tmpyz1bppsr/libregorus_ffi.a /home/extro/.local/share/hopper/lodes/pqzizkwa/scratchpad/tmpyz1bppsr/MacOSX.sdk/usr/lib/libiconv.tbd -framework CoreFoundation
```

Neither `nvattest` codemodel surface contains the injected directory:

```json
{
  "library_fragments": [
    "-Wl,-rpath,/home/extro/.local/share/hopper/lodes/pqzizkwa/scratchpad/tmpyz1bppsr/build",
    "libnvat.so"
  ],
  "all_link_fragments": [
    "",
    "-Wl,-rpath,/home/extro/.local/share/hopper/lodes/pqzizkwa/scratchpad/tmpyz1bppsr/build",
    "libnvat.so"
  ]
}
```

Its exact raw link file is likewise clean:

```text
/usr/bin/c++ -Wl,--dependency-file=CMakeFiles/nvattest.dir/link.d CMakeFiles/nvattest.dir/main.cpp.o -o nvattest  -Wl,-rpath,/home/extro/.local/share/hopper/lodes/pqzizkwa/scratchpad/tmpyz1bppsr/build libnvat.so
```

The implementation regression therefore needs all three checks:

* `all_link_fragments(nvat)` and raw `nvat/link.txt` exclude the exact
  `-L/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/usr/lib`;
* `library_fragments(nvat)`, `all_link_fragments(nvat)`, and raw link text
  exclude the exact Command Line Tools path and any rpath containing it;
* both `nvattest` surfaces remain limited to the shared `nvat` dependency and
  their own fixture/authored rpath, with no owner directory, owner archive,
  iconv, or CoreFoundation direct edge.

`library_fragments` alone is insufficient because it deliberately omits the
`libraryPath` role that carries `-L`.

**Observed on this lode:** real `ReducedAppleFixture`, its `before_call`
seam, successful generation, complete codemodel roles and fragments, and both
raw link files. **Unobserved on this lode:** Mach-O generation or a native
Apple link.

## P4 — Full host-sensitivity sweep

Production host selection is centralized in
`Authority.compatible_target()` and `Authority.require_compatible()`, whose
omitted arguments call `platform.system()` and `platform.machine()`
(`sol/release/release_rail/authority.py:67-101`). Driver `_preflight()` calls
both without arguments before dirty-tree, runtime, or Apple checks
(`sol/release/release_rail/driver.py:528-567`). The authority CLI does the
same for `host-target` and `build-image`
(`sol/release/rail.py:23-36`).

The complete test sweep found exactly these five process-host-sensitive
tests:

| test | classification | current live-host path | hermetic recommendation |
| --- | --- | --- | --- |
| `test_authority.AuthorityTest.test_accessor_reports_incompatible_forced_target` (`test_authority.py:144-161`) | real-host-selection test | spawned `sys.executable rail.py authority build-image macos-arm64` reaches real `platform.machine()` and hard-codes x86 recovery | derive the expected compatible ID with `authority.load().compatible_target()` for the selected fixture host; keep the subprocess and assert its recovery uses that ID |
| `test_driver.DriverPreflightTest.test_missing_target_fails_before_dist_exists` (`test_driver.py:174-182`) | real-host-selection test | `driver.release(root, None)` intentionally asks `_preflight()` for this host's recommendation, but the regex hard-codes target zero | derive the compatible ID from authority and interpolate it in the expected diagnostic |
| `test_driver.DriverPreflightTest.test_dirty_source_tree_fails_before_dist_exists` (`test_driver.py:184-198`) | fixed-target data test | selects fixed `linux-x86_64`, then live compatibility can preempt the intended dirty-tree branch | patch `Authority.compatible_target` to that fixture ID and `Authority.require_compatible` to that fixture target |
| `test_driver.DriverRuntimeTest.test_release_threads_one_selection_through_every_container_command` (`test_driver.py:324-449`) | fixed-target data test | `setUp()` fixes target zero, but `driver.release()` performs live compatibility before the mocked runtime path | patch both authority methods to the fixed target so the test remains about threading one selected runtime |
| `test_driver.DriverRuntimeTest.test_ownership_failure_precedes_dist_creation` (`test_driver.py:580-594`) | fixed-target data test | same fixed target and live preflight preemption | patch both authority methods so the ownership failure remains the first intended failure |

The fixed-target patch precedent already exists in
`test_macos_preflight_captures_apple_evidence_before_dist`:

```python
with mock.patch.object(
    authority.Authority, "compatible_target", return_value=target["id"]
):
    with mock.patch.object(
        authority.Authority, "require_compatible", return_value=target
    ):
```

(`sol/release/tests/test_driver.py:642-648`). Use the same seam, rather than
changing `authority.py` or `driver.py`.

The subprocess case needs no production test hook. It omits `env=`, so it
inherits the full-suite fixture `PYTHONPATH`; Python imports the same
scratchpad `sitecustomize.py` in the child. The forced-aarch64 baseline
empirically proved that child reported `Linux/aarch64`. Its expected recovery
must be derived rather than positional. The host shim remains scratch-only
and must never be committed under `sol/release/tests/`.

The explicit data-test pattern at
`test_authority.py:40-48` already survives unchanged: it passes
`("Linux", "x86_64")`, `("Linux", "aarch64")`, and `("Darwin", "arm64")`
directly to authority, including explicit incompatible arguments. Likewise,
`test_apple.py:130-140` supplies explicit Darwin/x86_64 arguments, runtime
tests pass a target so `runtime._target_architecture()` does not consult
`platform.machine()` (`runtime.py:260-281`), and the remaining
`driver.release()` tests either patch `_preflight()` or both authority
methods. They are not process-host-sensitive.

No test should be skipped, deleted, or xfailed. Under forced x86_64 and
aarch64 predicates the same 143 IDs and the same two optional CMake skips
must execute; only expected recovery text varies in the two
real-host-selection cases.

**Observed on this lode:** exhaustive test grep and call trace, all
`driver.release()` sites, exact five forced-aarch64 failures, and inherited
child predicate. **Unobserved on this lode:** a native aarch64 process; the
predicate was the authorized scratch shim.

## P5 — Structural guards on the helper

The new read/validate/clear step fits all current source guards.

`test_production_has_one_guarded_call_and_one_edge_truth_source` extracts only
APPEND calls on `INTERFACE_LINK_LIBRARIES`:

```python
property_calls = re.findall(
    r"set_property\(TARGET ([^\s]+) APPEND PROPERTY\s+"
    r"INTERFACE_LINK_LIBRARIES ([^)]+)\)",
    helper,
    re.MULTILINE,
)
self.assertEqual(len(property_calls), 2)
```

(`sol/release/tests/test_apple_link_closure.py:286-292`). A direct regex probe
returned `True` for the existing APPEND form and `False` for:

```cmake
set_property(TARGET regorus_ffi-static PROPERTY
  INTERFACE_LINK_DIRECTORIES "")
```

Therefore the required non-APPEND clear does not change the exactly-two
count.

`test_policy_rejects_linker_escape_hatches_and_non_sdk_inputs` asserts:

```python
for token in (
    *forbidden_link_tokens,
    "file(GLOB",
    "file(GLOB_RECURSE",
    "-L/opt/homebrew",
    "-F/opt/homebrew",
    "-L/usr/local",
    "-F/usr/local",
):
    self.assertNotIn(token, product)
...
self.assertNotRegex(source, copied_platform_dependency)
...
self.assertNotIn("-framework CoreFoundation", product_sources[HELPER])
...
self.assertNotIn(token, surface)
```

(`test_apple_link_closure.py:906-973`). Property inspection and clearing add
no linker escape, host-prefix flag, copied artifact, or bare framework. The
future hostile fixtures must continue checking both source and all generated
surfaces.

`test_helper_avoids_post_311_commands` is exactly:

```python
for token in (
    "list(PREPEND",
    "string(JOIN",
    "FetchContent_MakeAvailable",
    "target_link_options",
    "file(REAL_PATH",
    "cmake_path",
):
    self.assertNotIn(token, helper)
```

(`test_apple_link_closure.py:1052-1063`). The verified 3.11.4 behavior from
the scope is sufficient: `get_target_property` returns a falsey
`<var>-NOTFOUND` when unset, arbitrary property set/re-read works, and 3.11
ignores this property during generation. Use ordinary `set`, `if`, `foreach`,
`get_target_property`, and `set_property`; no forbidden post-floor command is
needed.

`test_linux_production_link_vectors_are_unchanged` asserts that the helper is
never called on Linux:

```python
self.assertEqual(calls, [])
```

and compares the entire normalized `nvat` and `nvattest` vectors to literal
lists before asserting:

```python
self.assertNotIn("CoreFoundation", link)
self.assertNotIn("Iconv", link)
self.assertNotIn("libiconv", link)
```

(`test_apple_link_closure.py:357-404`). The SDK call remains guarded by
`if(APPLE)` (`nv-attestation-sdk-cpp/CMakeLists.txt:374-376`), so helper-only
Apple property handling leaves those vectors unchanged.

Finally, baseline stability pins:

```python
BASELINE = "b75e95ae0c08ac6eaa05673a0cf227b8723e2b58"
...
self.assertEqual(self.source(TARGETS), self.baseline(TARGETS))
```

(`sol/release/tests/test_baseline_stability.py:27,135-136`) and applies this
exact helper assertion:

```python
for token in (
    "FetchContent_Declare",
    "ExternalProject_Add",
    "GIT_REPOSITORY",
    "GIT_TAG",
    "URL",
    "URL_HASH",
):
    self.assertNotIn(token, source)
```

(`test_baseline_stability.py:241-252`). `URL` is an unbounded, case-sensitive
substring check: it would also reject a longer uppercase word containing
those three letters. New diagnostics, comments, and variable names in the
helper must contain no uppercase `URL` substring at all.

**Observed on this lode:** every assertion above, direct regex
discrimination, both CMake 3.11 tests, and unchanged Linux baseline.

## P6 — Mach-O oracle binding

The accepted target record is currently:

```text
lib/libnvat.dylib       -> libnvat.1.dylib
lib/libnvat.1.dylib     -> libnvat.1.2.2.dylib
lib/libnvat.1.2.2.dylib    regular
macho_install_id = "@rpath/libnvat.1.dylib"
macho_rpath = "@executable_path/../lib"
abi_floor.macos = "14.0"
```

(`sol/release/targets.toml:66-91`).

The current accepted-value fixtures mostly read those values back from the
same record they pass to the gate:

* `test_valid_macho_executable_and_library` builds its executable rpath from
  `target["macho_rpath"]` and its library identity from
  `target["macho_install_id"]`
  (`sol/release/tests/test_gate.py:121-140`).
* `test_invalid_macho_identity_and_rpath_fail` supplies bad literal values,
  but the accepted comparison still comes from the target passed to
  `gate.gate_file` (`test_gate.py:183-207`;
  `sol/release/release_rail/gate.py:117-128`).
* Shared `make_stage()` constructs every Mach-O executable with
  `target["macho_rpath"]`, every library with
  `target["macho_install_id"]`, and the member/symlink chain from
  `target["members"]` (`sol/release/tests/support.py:52-81`). All archive,
  manifest, and set-validator consumers built on `make_stage()` therefore
  remain intentionally data-driven rather than independent accepted-value
  oracles.

The two current literal authority bindings are:

```python
self.assertEqual(
    data.targets["macos-arm64"]["macho_install_id"],
    "@rpath/libnvat.1.dylib",
)
```

(`sol/release/tests/test_authority.py:34-38`), and the fail-closed mutation
anchored to the literal current floor and architecture:

```python
source.replace(
    'abi_floor = { macos = "14.0" }',
    'abi_floor = { macos = "latest" }',
)
...
source.replace(
    'expected_arch = "CPU_TYPE_ARM64"',
    'expected_arch = "EM_AARCH64"',
)
```

(`test_authority.py:120-135`). The latter indirectly pins `"14.0"` because a
changed source string would make the mutation a no-op and the expected
validation failure would not occur. There is no equivalent literal binding
today for the member chain or accepted rpath.

“Bound to accepted values” should concretely mean:

1. Add one literal authority assertion for the exact three-member dylib chain
   and kinds, exact install ID, exact executable rpath, and exact
   `{"macos": "14.0"}` floor. Do not derive any right-hand side from the
   loaded target.
2. Make the valid gate fixtures explicit literals:
   `deployment_version=(14, 0, 0)`,
   `dylib_id="@rpath/libnvat.1.dylib"`, library `rpaths=()`, and executable
   `rpaths=("@executable_path/../lib",)`, then pass the real target record to
   `gate.gate_file`. This independently proves the gate accepts exactly the
   shipped values and rejects the existing bad literals.
3. Keep `support.make_stage()` data-driven. It is a general target fixture
   constructor and consumer, not the place to duplicate policy. The literal
   authority and gate tests provide the independent oracle it currently
   lacks.

`test_baseline_stability.py` pins
`BASELINE = b75e95ae0c08ac6eaa05673a0cf227b8723e2b58` and requires
`targets.toml` byte-identical (`test_baseline_stability.py:27,135-136`), so
the table cannot move in this closure. Literal fixture values are still a
real oracle: they are independent inputs to `gate.gate_file`, not values
copied from the record under test. The byte guard prevents a self-consistent
table rewrite now; the literal tests prevent a future intentional baseline
advance from silently teaching both fixture and gate the same wrong values.
The two protections are complementary rather than tautological.

**Observed on this lode:** every target-derived fixture site, both current
literal bindings, target bytes, gate comparisons, support construction, and
the baseline byte assertion. **Unobserved on this lode:** a native Mach-O
artifact carrying the accepted values; Pro5E supplies that post-ship
evidence.

## Patterns the design should preserve

* The production change fits the declared budget:
  `nv-attestation-sdk-cpp/cmake/nvat_apple_system_link_closure.cmake` only.
  The helper is already included and called after the pinned Corrosion owner
  exists. Regression changes fit under `sol/release/tests/`; no broader
  production file is needed.
* Inspect the real imported static owner `regorus_ffi-static`, validate every
  raw directory entry against only the two exact known strings, then clear
  all or fail before mutation. Preserve selected-SDK iconv/CoreFoundation
  ownership and ordering.
* Prove both propagation forms: `all_link_fragments` and raw link text for
  `-L`, and all codemodel/raw surfaces for the build rpath. Keep `nvattest`
  free of direct static-owner inputs.
* Keep fixed-target tests fixed with the existing authority-method patch
  seam. Let real-host-selection tests derive the compatible target and
  recovery text. The scratch host predicate must reach nested Python
  processes through inherited `PYTHONPATH`.
* Preserve the exactly-two APPEND edge setters, 3.11 command vocabulary,
  Linux link vectors, linker-escape policy, and the helper's unusually broad
  uppercase-`URL` substring ban.
* Bind the member chain, install ID, executable rpath, and exact 14.0 floor to
  literal test inputs while leaving the byte-identical authority and generic
  fixture constructors unchanged.
