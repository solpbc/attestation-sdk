# Native macOS arm64 build completion design

**Authority:** this record is a focused amendment to
`sol/notes/tri-target-design.md`. The accepted facts in
`sol/notes/mac-native-build-prep.md` are inputs and are not re-derived here.
The scope is limited to the fmt warning-policy defect, Apple inputs for the
four vendored external projects, and validated Darwin toolchain evidence.

This design is authored on a Linux lode. It distinguishes checks that can run
here from native Darwin observations. Nothing below claims that this lode
produced or verified a native macOS artifact.

## D1 — Exempt only fmt from warnings-as-errors

**Decision.** Immediately after `FetchContent_MakeAvailable(fmt)` at
`nv-attestation-sdk-cpp/CMakeLists.txt:107-115`, require `TARGET fmt`; otherwise
fail CMake configure with:

```text
fmt warning-policy exemption failed: expected compiled target fmt after
FetchContent_MakeAvailable; verify the pinned fmt 10.2.1 target layout
```

Then set only `fmt`'s `COMPILE_WARNING_AS_ERROR` property to `OFF`.

fmt 10.2.1 exposes one compiled library target, `fmt`, and the
`fmt-header-only` INTERFACE target. Only `fmt` has a compile line and needs the
property. Applying a compile-warning property to the interface-only alias
would not fix another compile surface and would obscure the exact exception.
The existence check makes a future pin/target-layout change fail instead of
silently losing the exemption.

CMake target names and target properties are globally visible after creation,
even though non-cache variables and directory properties are scoped. The SDK
therefore can set the property on the real fmt target it just populated, and
the setting remains effective when the SDK was entered from the CLI by
`add_subdirectory` (`nv-attestation-cli/CMakeLists.txt:78-87`). This is the
same target whose property CMake initialized from
`CMAKE_COMPILE_WARNING_AS_ERROR` at creation, as established in prep Q1.

The exemption is unconditional. The defect is a vendored-target ownership
boundary, not an Apple policy: first-party warnings remain errors, while fmt
is responsible for its own warning compatibility on every compiler. One
unconditional rule is smaller and avoids platform-dependent warning policy.
It changes fmt compiler flags on Linux, but scope §3.2's byte-identity
constraint is specifically the four external projects' configure argv and
environment. fmt is a FetchContent target, not one of those EP commands, so
that constraint does not apply.

No CLI change is required for the **fmt exemption**. D2 separately requires
the CLI to invoke the Apple-resolution module; that is unrelated to fmt.
spdlog remains under the existing warnings-as-errors policy and is not changed,
per scope §9.1. No global `-Wno-*` is added. Neither
`CMAKE_COMPILE_WARNING_AS_ERROR` assignment is lowered or removed. `nvat` and
`nvattest` continue to receive warnings-as-errors.

**Files:** `nv-attestation-sdk-cpp/CMakeLists.txt`; focused structural/behavior
coverage in the CMake test added by D5.

## D2 — One Apple resolution point, three deliberate delivery mechanisms

### D2.1 — Resolve in a wired SDK-owned CMake module

**Decision.** Add
`nv-attestation-sdk-cpp/cmake/nvat_apple_sdk.cmake`. It is the sole resolver
for the normalized Apple SDK path, architecture, and deployment floor.

The module is invoked before `project()`:

* `nv-attestation-cli/CMakeLists.txt` uses the exact include path
  `${CMAKE_CURRENT_LIST_DIR}/../nv-attestation-sdk-cpp/cmake/nvat_apple_sdk.cmake`
  and invokes it inside
  `if(CMAKE_HOST_SYSTEM_NAME STREQUAL "Darwin")` before the CLI's `project()`
  call.
* `nv-attestation-sdk-cpp/CMakeLists.txt` includes its local
  `${CMAKE_CURRENT_LIST_DIR}/cmake/nvat_apple_sdk.cmake` and invokes it inside
  the same host guard before its own `project()` only when the normalized
  outputs have not already been established by the CLI.

This placement is required because CMake documents that the OSX variables may
influence compiler/toolchain initialization and should be set before
`project()`:
`/usr/share/cmake/Help/variable/include/CMAKE_OSX_VARIABLE.rst:1-7`.
Darwin's initializer consumes existing architecture and sysroot values while
establishing the platform (`/usr/share/cmake/Modules/Platform/Darwin-Initialize.cmake:18-20,47-78`);
waiting until after `project()` would mean compiler identification and
`CMakeCXXCompiler.cmake` were produced before the resolved SDK/architecture
authority existed. Because scope §3.5 permits native builds only, the
pre-project host predicate is also the target predicate: cross-Darwin
configuration from a non-Darwin host is unsupported and must not activate this
path.

`APPLE` is deliberately not the guard. It is assigned by the Darwin platform
initializer (`/usr/share/cmake/Modules/Platform/Darwin-Initialize.cmake:1-2`),
which is loaded during system determination inside `project()`.
The requested scratch probe on this Linux lode observed:

```text
-- before: APPLE=[] CMAKE_SYSTEM_NAME=[] CMAKE_HOST_SYSTEM_NAME=[Linux]
-- The C compiler identification is GNU 15.3.0
-- The CXX compiler identification is GNU 15.3.0
-- after: APPLE=[] CMAKE_SYSTEM_NAME=[Linux] CMAKE_HOST_SYSTEM_NAME=[Linux]
-- Configuring done
-- Generating done
[exit 0]
```

Thus `CMAKE_HOST_SYSTEM_NAME` is populated before `project()`, while
`CMAKE_SYSTEM_NAME` and `APPLE` are not. CMake's system-determination module
then defaults the target system from the host
(`/usr/share/cmake/Modules/CMakeDetermineSystem.cmake:163-180`); on Darwin that
loads the initializer which sets `APPLE`.

It also makes a plain native
`cmake -S nv-attestation-cli ...` and a standalone SDK configure use the same
logic. The SDK owns the module because the four vendored projects are SDK
implementation details; the CLI only calls the public resolution entry point.
There is no unwired helper.

For the production configure `cmake -S nv-attestation-cli`, the exact sibling
path resolves from the CLI source directory to the SDK directory in this
repository, independent of the caller's working directory. It is also valid
under `USE_SYSTEM_NVAT=ON`: although that mode does not add the SDK
subdirectory (`nv-attestation-cli/CMakeLists.txt:47-84`), `nvattest` is still a
first-party target and must receive the explicit SDK/architecture/floor.
Moreover, system mode already requires the same sibling SDK tree for
`nvat_locate_installed.cmake` (`nv-attestation-cli/CMakeLists.txt:48-52`), so
the early include introduces no new source-layout assumption. A hypothetical
standalone copy of only the CLI directory is not a supported consumption mode
today. Duplicating the resolver into the CLI or deferring it until the SDK
subdirectory would be more fragile.

The module's real entry point takes these inputs:

* `CMAKE_OSX_SYSROOT`, optionally supplied by the caller as either an absolute
  path or an SDK selector such as `macosx`;
* `CMAKE_OSX_ARCHITECTURES`, optionally supplied by the caller;
* `CMAKE_OSX_DEPLOYMENT_TARGET`, required nonempty;
* `CMAKE_HOST_SYSTEM_PROCESSOR`, used by the native-only pre-project path;
* `NVAT_APPLE_XCRUN`, an optional test injection containing the executable
  path/name; production defaults it to `xcrun`.

The module produces and caches:

* `CMAKE_OSX_SYSROOT` as one absolute, existing directory;
* `CMAKE_OSX_ARCHITECTURES` as exactly `arm64`;
* the validated, nonempty `CMAKE_OSX_DEPLOYMENT_TARGET`;
* `NVAT_APPLE_SDKROOT`, equal to the normalized cache sysroot;
* `NVAT_APPLE_ARCHITECTURE`, exactly `arm64`;
* `NVAT_APPLE_DEPLOYMENT_TARGET`, equal to the cache floor;
* `NVAT_EP_ENV_COMMAND`, the CMake command list used by D2.2.

The normalized CMake OSX values are cache entries so the compiler setup,
first-party target generation, external-project construction, and later
manifest cross-check all see the same values. The CLI resolves first; successful
resolution sets a global CMake property that the SDK uses as its sentinel. The
SDK invokes the resolver only for a standalone SDK configure, so production
does not resolve twice and a caller-provided cache variable cannot bypass
validation.

Sysroot resolution is one rule with explicit-input precedence:

1. If the user supplied an absolute `CMAKE_OSX_SYSROOT`, validate that exact
   path.
2. If the user supplied a non-absolute SDK selector, ask the injected/default
   xcrun exactly once for that selector's `--show-sdk-path`.
3. If no sysroot was supplied, ask xcrun exactly once for
   `--sdk macosx --show-sdk-path`.

Honoring an explicit absolute path or selector is not a fallback ladder. It is
the caller's selected input. Each case has one resolution route and hard-fails;
the module never tries an implicit compiler default after a bad explicit value
or failed xcrun. The final value must be an absolute existing directory.
Because CMake list syntax uses semicolons and backslashes as structural
characters, the final normalized path must contain neither. Both explicit and
xcrun-resolved paths fail closed on those characters instead of relying on
fragile multi-layer escaping.

Architecture behaves similarly: absent architecture is normalized to
`arm64`; an explicit value is accepted only if it is the single value
`arm64`. Multi-arch lists, `aarch64`, x86_64, and empty list elements fail.
The pre-project `CMAKE_HOST_SYSTEM_PROCESSOR` must normalize to arm64/aarch64
and agree. Script-mode tests inject the host identity because no normal
configure/system determination occurs.

The floor must be a nonempty dotted numeric macOS version. CMake does not parse
`targets.toml`; therefore the module can validate shape and preserve explicit
input, while the rail performs the authority equality check in D4. Delete both
existing pre-project
`if(APPLE AND NOT DEFINED CMAKE_OSX_DEPLOYMENT_TARGET)` blocks: they are dead
on Darwin because `APPLE` is not set yet, and leaving them beside the live
resolver would retain contradictory policy. There is no CMake-side `14.0`
default after this change. `14.0` lives only in
`sol/release/targets.toml`'s `abi_floor.macos`; the release driver supplies
that value explicitly. A plain native CMake invocation must pass
`-DCMAKE_OSX_DEPLOYMENT_TARGET=<floor>` and otherwise fails closed. This is the
smallest single-truth behavior consistent with scope §2.1/§2.2 and §5.2.

The rejected alternative is resolving only in the Python release rail. That
would leave ordinary native CLI/SDK configurations with compiler defaults and
would violate the requirement that the external projects receive the enclosing
build's resolved sysroot outside `make release`.

### D2.2 — Deliver sysroot only through the environment

**Decision.** On Apple,
`NVAT_EP_ENV_COMMAND` is the list:

```text
${CMAKE_COMMAND};-E;env;SDKROOT=${NVAT_APPLE_SDKROOT}
```

It prefixes `CONFIGURE_COMMAND`, `BUILD_COMMAND`, and `INSTALL_COMMAND` for all
four external projects.

The prefix is required on all three steps. Configure probes compile and link;
the build step performs the real compilation; install steps are upstream
commands and are not assumed never to trigger a rebuild or relink. Supplying
the same one environment value to all three makes every compiler invocation
in the EP lifecycle deterministic.

`SDKROOT` is the sole sysroot delivery mechanism. No `-isysroot` is added to
`CFLAGS`, and no ambient parent `SDKROOT` is relied upon. Process argv preserves
the `SDKROOT=<absolute path>` element as one argument to `cmake -E env`; the
environment value then reaches Make and compiler processes without being
expanded as recipe text. A sysroot path containing spaces is therefore never
re-split by Perl, Make, or a recipe shell. This directly addresses prep Q3
without quote-escaping gymnastics. The resolver rejects semicolons and
backslashes before constructing this list, so the normalized SDK value cannot
change its argv structure.

### D2.3 — Deliver the floor in CFLAGS and arm64 once per build system

**Decision.** Preserve `_EP_CC` and every existing flag. Split the current
single flag variable into deliberate effective values:

* Base `_EP_CFLAGS` remains exactly `${CMAKE_C_FLAGS} -fPIC`.
* On Apple, `_EP_DARWIN_CFLAGS` adds the space-free token
  `-mmacosx-version-min=${NVAT_APPLE_DEPLOYMENT_TARGET}`.
* `_EP_OPENSSL_CFLAGS` is `_EP_DARWIN_CFLAGS` on Apple and `_EP_CFLAGS`
  elsewhere.
* `_EP_AUTOCONF_CFLAGS` is `_EP_DARWIN_CFLAGS` plus `-arch arm64` on Apple
  and `_EP_CFLAGS` elsewhere.

The deployment floor uses only CFLAGS. It is not also exported as
`MACOSX_DEPLOYMENT_TARGET`. For OpenSSL, the floor is observable in user
`CFLAGS`, while `darwin64-arm64-cc` supplies the effective `-arch arm64`
through its separate lower-case target `cflags`. Adding another `-arch arm64`
to OpenSSL user CFLAGS would duplicate the same fact and is unnecessary.

For libxml2, xmlsec, and curl, both
`-mmacosx-version-min=<floor>` and `-arch arm64` are observable in their
`CFLAGS=` configure argv, substituted Makefile variable, configure probes, and
effective compile recipes. Thus acceptance criterion 2 has a concrete
per-dependency surface:

| Dependency | SDK | Floor | arm64 |
|---|---|---|---|
| OpenSSL 3.6.1 | `SDKROOT` environment on configure/build/install | `_EP_OPENSSL_CFLAGS` | `darwin64-arm64-cc` lower-case target `cflags` |
| libxml2 2.11.9 | same | `_EP_AUTOCONF_CFLAGS` | `_EP_AUTOCONF_CFLAGS` |
| xmlsec 1.2.39 | same | `_EP_AUTOCONF_CFLAGS` | `_EP_AUTOCONF_CFLAGS` |
| curl 7.88.1 | same | `_EP_AUTOCONF_CFLAGS` | `_EP_AUTOCONF_CFLAGS` |

Prep Q3 established that OpenSSL's `CFLAGS=` replaces its uppercase target
`CFLAGS`, and that all three autoconf assignments replace rather than append.
That existing behavior already drops OpenSSL's target `-O3 -Wall` on Linux and
suppresses autoconf-chosen defaults. It is out of scope and remains unchanged.
OpenSSL's lower-case `-arch arm64` survives separately. `_EP_CFLAGS` retains
the existing C flags and literal ` -fPIC` construction; the Apple additions
append only the two required space-free tokens.

### D2.4 — Linux byte identity

On non-Apple platforms:

* `NVAT_EP_ENV_COMMAND` is unset, not set to `""`;
* `_EP_OPENSSL_CFLAGS` and `_EP_AUTOCONF_CFLAGS` resolve byte-for-byte to the
  existing `_EP_CFLAGS`;
* the four declaration bodies place `${NVAT_EP_ENV_COMMAND}` immediately
  before each existing configure/build/install executable.

In a CMake command argument list, expansion of an unset variable contributes
zero list elements. It does not create an empty argv element. Consequently
Linux `CONFIGURE_COMMAND`, `BUILD_COMMAND`, and `INSTALL_COMMAND` gain zero
tokens, and their existing argv and environment remain byte-identical. The
single prefix variable is used at every site; there are no per-dependency
Apple branches.

The changes are pin-neutral. `generate-dependencies.py` reads only the
declaration name plus URL/hash or repository/tag fields; prep Q5 established
that additional command elements and `${CMAKE_COMMAND} -E env` prefixes are
ignored. The dependency declarations stay syntactically flat; no `if(APPLE)`
block is inserted inside an `ExternalProject_Add` body.

**Files:** add `nv-attestation-sdk-cpp/cmake/nvat_apple_sdk.cmake`; update both
top-level CMakeLists and the four EP declarations in
`nv-attestation-sdk-cpp/CMakeLists.txt`.

## D3 — Fail closed at the earliest authoritative seam

All new diagnostics follow:

```text
<what failed>: <specific detail>; <actionable recovery>
```

The planned failures are:

| Failure | Where it fires | Diagnostic shape and recovery |
|---|---|---|
| xcrun missing | CMake configure, before `project()` | `Apple SDK resolution failed: cannot invoke xcrun: <OS detail>; install or select Xcode Command Line Tools with xcode-select, then retry` |
| xcrun nonzero | same | `Apple SDK resolution failed: xcrun --sdk <selector> --show-sdk-path exited <status>: <trimmed stderr>; select a valid Xcode developer directory with xcode-select, then retry` |
| empty xcrun output | same | `Apple SDK resolution failed: xcrun returned an empty path for SDK <selector>; verify xcrun --sdk <selector> --show-sdk-path, then retry` |
| non-absolute resolved sysroot | same | `Apple SDK resolution failed: resolved path is not absolute: <value>; pass -DCMAKE_OSX_SYSROOT=<absolute SDK directory> or repair xcrun, then retry` |
| nonexistent/non-directory sysroot | same | `Apple SDK resolution failed: SDK directory does not exist: <value>; install the selected macOS SDK or pass its absolute directory, then retry` |
| sysroot contains `;` or `\` | same | `Apple SDK resolution failed: resolved path contains a semicolon or backslash: <value>; pass -DCMAKE_OSX_SYSROOT=<absolute SDK directory> without those characters, then retry` |
| empty/malformed deployment floor | CMake configure | `Apple deployment target resolution failed: expected a dotted numeric version, got <repr>; pass -DCMAKE_OSX_DEPLOYMENT_TARGET=<version>, then retry` |
| explicit architecture is not exactly arm64 | CMake configure | `Apple architecture resolution failed: expected exactly arm64, got <value>; configure a native arm64 build with -DCMAKE_OSX_ARCHITECTURES=arm64, then retry` |
| system processor is not arm64/aarch64 | CMake configure | `Apple architecture resolution failed: native processor <value> is not arm64; run the release on an Apple Silicon host, then retry` |
| target authority floor empty/malformed | authority load / rail preflight | existing authority error prefix plus `macos-arm64: abi_floor.macos must be a dotted numeric version; correct sol/release/targets.toml, then retry` |
| target authority architecture disagrees | authority load / rail preflight | `macos-arm64: expected_arch must be CPU_TYPE_ARM64; correct sol/release/targets.toml, then retry` |
| driver floor differs from normalized CMake cache | final evidence capture | `Apple toolchain evidence failed: configured deployment target <actual> differs from authority <expected>; remove build/release and retry make release TARGET=macos-arm64` |
| cache sysroot missing, non-absolute, nonexistent, or differs from resolved SDK path | final evidence capture | `Apple toolchain evidence failed: configured SDK sysroot <detail>; remove build/release, select a valid Xcode SDK, and retry make release TARGET=macos-arm64` |
| cache architecture absent or not exactly arm64 | final evidence capture | `Apple toolchain evidence failed: configured architecture <detail>; remove build/release and retry with a native arm64 toolchain` |
| compiler metadata file absent/ambiguous/malformed or unreadable | final evidence capture | `Apple toolchain evidence failed: cannot read <compiler record/detail>; remove the build directory and rerun the native configure` |
| AppleClang executable output disagrees with configured ID/version | final evidence capture | `Apple toolchain evidence failed: compiler observation <observed> differs from CMake <configured>; select one Xcode toolchain, remove build/release, and retry` |
| xcodebuild/xcrun fields malformed or disagree | rail preflight or final capture | `Apple toolchain evidence failed: <field> observations disagree: <detail>; run xcode-select -p and xcrun --sdk macosx --show-sdk-path, correct the active Xcode selection, then retry` |
| evidence has missing, extra, reordered, stale, or malformed fields | manifest capture/validation | `macos-arm64: Apple toolchain evidence has invalid <section/field>; rebuild the manifest with make release TARGET=macos-arm64` |
| hand-edited/stale evidence reaches complete set | set validation through manifest validator | `quartet layout mismatch: macos-arm64: build_tools: <Apple validation detail>` |

The module reports no compiler-default fallback. A bad explicit selector/path
does not cause a second discovery attempt. The Python rail likewise never
silently normalizes a missing cache field from host observations.

Preflight validates authority and invokes the Apple observation commands before
transaction construction, so discovery/tool failures leave `dist` untouched.
The definitive CMake cross-check necessarily occurs after build, at manifest
capture, and therefore before manifest creation and promotion. Complete-set
validation repeats the closed evidence checks during promotion review.

## D4 — Darwin-only normalized toolchain evidence

### D4.1 — One Apple evidence module

**Decision.** Add `sol/release/release_rail/apple.py`, parallel to
`runtime.py`, rather than growing `manifest.py`.

The module owns Apple command argv, parsing, normalization, CMake cross-checks,
and its one evidence schema. `manifest.py` remains the aggregator of ordinary
tool evidence. This mirrors the existing runtime separation and prevents
Apple/Xcode parsing policy from becoming a second concern of generic manifest
serialization.

Exports:

* `EVIDENCE_KEY = "apple_toolchain"`;
* `AppleToolchainError`;
* a strict dotted `_VERSION` regex with the same one-to-four numeric component
  policy as runtime evidence;
* `preflight(target, runner=subprocess.run)`, which validates native host
  observations and authority before construction but authors no manifest;
* `resolve(target, build_dir, runner=subprocess.run)`, which repeats/captures
  observations, cross-checks the completed CMake configuration, and returns
  only validated normalized evidence;
* `validate_evidence(value, target=None)`.

There is no user-facing mode/flag and no evidence override. Runner injection is
the normal unit-test seam.

### D4.2 — Exact closed shape

The evidence key is appended after the seven ordinary build-tool keys only for
Darwin:

```text
"apple_toolchain": {
  "apple_clang": {
    "name": "Apple clang",
    "version": "<dotted numeric>"
  },
  "xcode": {
    "version": "<dotted numeric>",
    "build": "<nonempty normalized build identifier>"
  },
  "sdk": {
    "name": "macosx",
    "version": "<dotted numeric>",
    "path": "<absolute existing SDK directory>"
  },
  "architecture": "arm64",
  "deployment_target": "<dotted numeric>"
}
```

Exact ordered tuples are:

* outer:
  `("apple_clang", "xcode", "sdk", "architecture", "deployment_target")`;
* AppleClang: `("name", "version")`;
* Xcode: `("version", "build")`;
* SDK: `("name", "version", "path")`.

Unknown, missing, reordered, empty, non-string, path-like version, and
free-form output fields fail. AppleClang's name is the one canonical constant.
Xcode build identifiers are evidence, not versions; they accept only the
documented compact alphanumeric identifier shape and reject whitespace,
paths, and annotations. SDK name is exactly `macosx`. SDK path is deliberately
recorded because scope requires evidence of the resolved toolchain input,
despite manifests otherwise avoiding incidental paths; it must be absolute and
an existing directory at capture. Promotion validation can validate syntax and
cross-fields but must not require that another host has the same path.

No Xcode, SDK, or AppleClang version is pinned. In particular, Xcode 26.5,
macOS SDK 26.5, and AppleClang 21.0.0 are accepted observations, never equality
requirements.

### D4.3 — Resolution and CMake cross-check

Host observations come from:

* configured C++ compiler executable `--version` for AppleClang product and
  version;
* `xcodebuild -version` for Xcode version and build identifier;
* `xcrun --sdk macosx --show-sdk-path` for SDK path;
* `xcrun --sdk macosx --show-sdk-version` for SDK version;
* normalized CMake configuration for architecture and deployment target.

The configured compiler executable path still comes from
`CMAKE_CXX_COMPILER:FILEPATH` in `CMakeCache.txt`, extending
`manifest._compiler_from_cache`'s precedent. Compiler ID and version do **not**
reliably live in `CMakeCache.txt`; CMake writes them as
`CMAKE_CXX_COMPILER_ID` and `CMAKE_CXX_COMPILER_VERSION` assignments in the
generated
`<build>/CMakeFiles/<cmake-version>/CMakeCXXCompiler.cmake`. `apple.resolve`
requires exactly one applicable compiler metadata file under
`CMakeFiles/*/CMakeCXXCompiler.cmake`, parses only those exact `set(...)`
records, requires ID `AppleClang`, and compares its version to normalized
compiler `--version` output. It does not scrape arbitrary CMake logs.

The CMake module makes `CMAKE_OSX_SYSROOT`,
`CMAKE_OSX_ARCHITECTURES`, and `CMAKE_OSX_DEPLOYMENT_TARGET` explicit cache
entries. `apple.resolve` requires all three exact entries in `CMakeCache.txt`;
absence is a hard failure, never an invitation to infer a compiler default.
It requires:

* cached sysroot equals the normalized xcrun SDK path after path
  normalization, is absolute, and exists;
* cached architectures is exactly `arm64`;
* cached deployment target exactly equals authority
  `target["abi_floor"]["macos"]`;
* authority `expected_arch` is `CPU_TYPE_ARM64`;
* AppleClang ID/version agree between CMake metadata and compiler observation;
* SDK path/version/name are internally consistent xcrun observations from the
  same selected `macosx` SDK;
* Xcode output has one version and one build identifier.

An explicit absolute sysroot that is a valid SDK but is not the currently
selected `xcrun --sdk macosx` path presents a policy question. This design
settles it fail-closed: release evidence must be reproducible from the active
Xcode selection, so the explicit cache path and xcrun path must agree.
Ordinary non-release CMake may use another explicit SDK; `make release` will
reject it until the operator selects the matching developer directory.

No new `targets.toml` field is needed. `abi_floor.macos` already authorizes the
floor and `expected_arch` already authorizes arm64. Xcode, SDK, and AppleClang
versions are observations rather than target policy, so pinning them in
authority would contradict scope §8. `authority._TARGET_KEYS` is unchanged,
but its existing validation is strengthened for the macOS ABI-floor shape and
the exact Mach-O architecture pairing.

The driver replaces its literal
`-DCMAKE_OSX_DEPLOYMENT_TARGET=14.0` with the loaded target's
`abi_floor.macos`. This removes duplicated release truth. Plain native CMake
has no default and must provide the floor explicitly.

### D4.4 — Promotion and complete-set validation

`manifest.BUILD_TOOL_KEYS` remains the seven ordinary tools.
`capture_build_tools` gains an `apple_evidence` keyword parallel to
`runtime_evidence`:

* Linux requires validated runtime evidence and forbids Apple evidence.
* Darwin requires validated Apple evidence and forbids runtime evidence.

The expected exact build-tools tuple becomes seven keys plus the one
target-specific evidence key. `capture_build_tools`, `validate_build_tools`,
and `manifest.build` all delegate Apple shape/authority checks to
`apple.validate_evidence`.

At final capture the driver passes `apple.resolve(target, build_dir)`.
At preflight it calls `apple.preflight(target)` separately, then captures the
seven ordinary tools without attempting to author a pre-configure manifest.
This avoids weakening final resolution with an “optional cache” mode.

`set_validator._validate_one` continues to call
`manifest.validate_build_tools`; therefore missing, extra, malformed, or
target-incompatible Apple evidence fails complete-set validation too. It does
not re-run xcrun or require the recorded SDK path to exist on the validating
host. Host-vs-cache consistency is authoring-time proof; closed shape,
cross-field consistency, and target agreement remain portable validation
proof.

**Files:** add `sol/release/release_rail/apple.py`; update
`release_rail/{manifest,driver,authority}.py`, `release_rail/__init__.py` if
exports are enumerated, and the tests/fixtures in D5. No target-authority key
is added.

## D5 — Test strategy and honest proof boundaries

### D5.1 — Real CMake resolver in script mode

Add a Python unittest module
`sol/release/tests/test_apple_cmake.py`. It invokes the real installed `cmake`
with `-P` against a tiny test driver that includes
`nv-attestation-sdk-cpp/cmake/nvat_apple_sdk.cmake` and calls its public
function. The driver supplies script-mode inputs and prints/writes the
normalized outputs for exact assertion.

The tests create:

* an executable xcrun stub on a temporary PATH/injected
  `NVAT_APPLE_XCRUN`;
* a real temporary SDK directory whose name contains spaces;
* a non-Darwin host-driver case proving the top-level guard does not include or
  invoke the resolver;
* an injected Darwin-host driver case proving the same real guarded path does
  invoke it before `project()`;
* success cases for absent sysroot, explicit SDK selector, and explicit
  absolute sysroot;
* a spaced SDK path containing shell metacharacters, proving the complete
  `SDKROOT=<value>` remains inert data in one list/argv element;
* existing SDK paths containing a semicolon or backslash, proving both are
  rejected before construction of the command list;
* failures for missing/nonzero/empty xcrun, relative result, nonexistent
  result, malformed/empty floor, wrong/multi architecture, and processor
  disagreement;
* an assertion that `NVAT_EP_ENV_COMMAND` has exactly four elements and the
  final `SDKROOT=<path with spaces>` element remains one CMake list element.

This adds a hard `cmake` dependency to `make rail-test`. It must not silently
skip: if `cmake` is absent, the unittest fails with an actionable message to
install CMake. That is acceptable because release authority already requires
CMake, the current lode has it, and the resolver itself is CMake code. The
tests are offline and do not enable a language or contact a network.

### D5.2 — Structural coverage of all four declarations and fmt

The same test module reads the real SDK CMakeLists and uses a narrow
parenthesis-aware extractor (reusing the dependency generator's declaration
matching behavior rather than a broad regex) to assert:

* exactly the four named `ExternalProject_Add` declarations exist;
* every configure/build/install command begins with the same
  `${NVAT_EP_ENV_COMMAND}` expansion;
* OpenSSL uses `${_EP_OPENSSL_CFLAGS}`;
* libxml2, xmlsec, and curl use `${_EP_AUTOCONF_CFLAGS}`;
* no EP command contains literal `SDKROOT`, `-isysroot`, or
  `MACOSX_DEPLOYMENT_TARGET`;
* fmt population is immediately followed by the hard target-existence check
  and the one `COMPILE_WARNING_AS_ERROR OFF` property assignment;
* no spdlog exemption or global warning-policy lowering is introduced.
* neither top-level CMakeLists contains an `if(APPLE)` guard before its first
  `project()`; both use the exact native-host guard and invoke the real module
  before compiler identification;
* the SDK uses the resolver's global success property as a sentinel so
  CLI-driven configuration does not invoke the resolver twice or trust an
  unvalidated caller-provided cache variable.

This seam catches a future declaration dropping a shared output. It cannot
prove upstream configure/Make interpretation, generated Darwin argv, or
AppleClang behavior. Those require the native proof in D5.6.

Do not create a new general CMake parser library. A test-local extractor is
enough, and the production dependency generator remains unchanged.

### D5.3 — Linux configure-command byte comparison

Implementation must record a before/after configure-only proof from the real
tree, never `build/release` or `dist`:

```text
cmake -S nv-attestation-cli -B <scratch-before-or-after> \
  -DUSE_SYSTEM_NVAT=OFF -DUSE_SYSTEM_DEPS=OFF \
  -DBUILD_TESTING=OFF -DBUILD_SHARED_LIBS=ON \
  -DCMAKE_BUILD_TYPE=Release
```

Run it once against the pre-change commit/worktree and once after the change.
Do not run `cmake --build`. Capture the four
`nv-attestation-sdk-build/<dep>_external-prefix/tmp/<dep>_external-cfgcmd.txt`
files and the matching configure recipes in
`CMakeFiles/<dep>_external.dir/build.make`; compare bytes for exact equality.

Prep Q4 established that this real configure needs network unless all
FetchContent sources are already cached. Corrosion also configures/imports the
regorus Rust crate during parent configure, so `rustc` and `cargo` are needed.
This lode has:

```text
rustc 1.97.1 (8bab26f4f 2026-07-14)
cargo 1.97.1 (c980f4866 2026-06-30)
```

The host therefore has the Rust tools, but network/cache success is not
guaranteed. If host configure cannot complete, use the existing Podman CI image
after `make image`, mount two scratch build locations, and run the same
configure-only command against pre-change and post-change source checkouts.
The comparison remains real-tree and configure-only. Container image creation
and uncached FetchContent still require network; there is no offline fake
harness.

The before and after cfgcmd/build.make copies and hashes are planned
implementation artifacts to be summarized in the eventual implementation
report or proof note. They are not produced in this design stage.

### D5.4 — Rail evidence and validator tests

Add `sol/release/tests/test_apple.py` for:

* xcodebuild, xcrun, and compiler-output normalization;
* exact closed tuples and version/build/path validation;
* authority floor and architecture cross-checks;
* parsing exactly one CMake compiler metadata file;
* cache absence, duplicate keys, non-absolute/nonexistent sysroot,
  architecture/floor mismatch, AppleClang ID/version mismatch, SDK path
  mismatch, and inconsistent command observations;
* actionable `AppleToolchainError` diagnostics;
* preflight observation without a cache and final resolution requiring it.

Extend `test_manifest.py` for target-specific exact build-tool tuples,
required/forbidden Apple evidence, capture plumbing, and final
cross-check-against-build-directory. Extend `test_driver.py` for authority
floor argv, one Apple preflight, one final resolve, no runtime evidence on
Darwin, and error propagation through the normal CLI form. Extend
`test_set_validator.py` with missing, extra, reordered, malformed, stale-floor,
and wrong-architecture Apple mutations.

`sol/release/tests/support.py` keeps `TOOLS` as the seven-tool base.
`tools_for(target)` adds:

* `runtime.EVIDENCE_KEY` only for Linux;
* `apple.EVIDENCE_KEY` only for Darwin.

This one helper keeps `test_manifest.py`, `test_set_validator.py`,
`test_driver.py`, `test_archive.py`, and quartet construction coherent.
Fixtures use neutral valid observed values, not Xcode 26.5/SDK 26.5/AppleClang
21 literals, unless a parser case specifically tests that input as accepted
evidence.

### D5.5 — Failure injection and transaction safety

No production failure-injection flag or new transaction mode is needed.
Existing seams are sufficient:

* fmt compiler failure and OpenSSL configure/build failure are injected by
  mocking `driver._build` to raise `ReleaseError` before
  `after-build` (`driver.py:548-550`). A companion transaction test injects
  `after-build` through `transaction.CONSTRUCTION_CHECKPOINTS`
  (`transaction.py:15-22`) to preserve the general checkpoint proof.
* empty/nonexistent SDK discovery is injected through `apple.preflight`;
  inconsistent configured SDK evidence is injected through `apple.resolve`;
  missing/malformed floors use the real `_target_values` trigger reached from
  preflight. Preflight failures happen before transaction construction; final
  cache inconsistencies happen during the builder before manifest creation.
* `test_transaction.py` retains exhaustive construction and promotion fault
  injection through `fault_hook` (`test_transaction.py:57-79`).

Each named failure has two release-level assertions:

1. With a valid quartet already at the four authoritative final paths, release
   refuses overwrite before construction and all four files remain
   byte-identical.
2. With empty final paths, failure leaves none of archive,
   archive-sidecar, manifest, or manifest-sidecar at final destinations.

The first assertion does not pretend the injected compiler failure ran after
overwrite refusal; it proves the stronger retained-quartet invariant at the
actual ordering. Owned staging may remain for diagnosis after a construction
failure, but final paths remain absent.

### D5.6 — Native post-ship proof

A native Apple Silicon run is the only proof for:

* actual fmt AppleClang compile command has no `-Werror`, while nvat and
  nvattest retain it;
* all four generated Darwin cfgcmd/build.make commands contain the designed
  SDK/floor/architecture delivery;
* configure, build, and install succeed with an SDK fixture/path containing
  spaces where practicable, or at minimum the real selected SDK;
* OpenSSL effective flags combine target `-arch arm64` with user floor flags;
* libxml2/xmlsec/curl effective commands contain both tokens;
* genuine Xcode/SDK/AppleClang evidence agrees with CMake and is promoted;
* the final Mach-O archive remains arm64 with exact deployment floor.

This is a post-ship VPE native step, not evidence available on this lode.

## Acceptance criteria and proof matrix

The numbering below matches assignment §7 exactly; implementation and audit
must use these numbers without translation.

| §7 AC | Required result | Direct check | Authored vs observed |
|---|---|---|---|
| 1 | fmt alone builds without warnings-as-errors; nvat/nvattest retain policy; spdlog is unchanged | D5.2 structural test plus native verbose compile inspection | Structure observable on lode; effective Apple flags require D5.6 |
| 2 | every vendored dependency effectively receives the enclosing absolute SDK, arm64 target, and exact deployment floor | D5.1 resolver tests, D5.2 four-declaration coverage, `apple.resolve` cache checks, and native cfgcmd/effective-build inspection | Resolution/list safety observable on lode; real Darwin EP argv/effective flags require D5.6 |
| 3 | delivery uses structured argv/environment, safely preserves a sysroot path containing spaces, and introduces no word-splitting or command-injection regression | D5.1 real-module spaced-path and exact-list-element tests; D5.2 asserts `SDKROOT` is only a `cmake -E env` element and never CFLAGS; hostile metacharacter fixture proves it remains data | Structured CMake behavior observable offline on lode; downstream Apple tools require D5.6 |
| 4 | Linux EP configure argv and environment remain byte-identical | D5.3 before/after four cfgcmd and build.make byte comparison | Observable on lode only with network/cache or Podman fallback; not run in design |
| 5 | fmt/build/SDK/floor failures cannot damage retained output or partially promote a quartet | D5.5 release-level retained/empty cases plus existing exhaustive transaction checkpoints | Fully unit-testable on lode; a real native build failure may additionally be exercised post-ship |
| 6 | Darwin manifests record closed, normalized Apple toolchain evidence cross-checked against CMake and authority, without pinning observed tool versions | `test_apple.py`, `test_manifest.py`, `test_set_validator.py`, and genuine native manifest inspection | Schema/cross-check logic observable on lode; genuine values require D5.6 |
| 7 | dependency pins/notices remain unchanged and release floor/architecture have one authority with fail-closed disagreement | generator before/after comparison, D5.2 declaration test, driver/authority tests, and `test_apple.py` cache/authority cases | Observable on lode without native Apple tools |
| 8 | the settled tree passes `make rail-test` and the full `make ci` gate, including shellcheck | explicit implementation-stage `make rail-test` and `make ci`; `make rail-test` itself runs shellcheck at `Makefile:37-39`, with a separately recorded shellcheck result if the full-gate transcript does not expose it | Proves Linux rail/container behavior only; native Darwin remains D5.6 |
| 9 | operator docs record reported prerequisites and the authored-vs-observed boundary; native VPE proof is recorded later | README wording review plus D5.6 proof record | README authorship observable on lode; native success explicitly unobserved until VPE run |

## D6 — Documentation changes

Update `sol/release/README.md` under `### macOS prerequisites` to state:

```text
The native toolchain reported by Jer for this release work is macOS 26.5,
Xcode 26.5, AppleClang 21.0.0, the macOS 26.5 SDK, arm64, with deployment
floor 14.0. These are observed toolchain evidence except for the authority
floor and architecture: Xcode, SDK, and compiler versions are recorded in each
Darwin manifest and are not pinned requirements.
```

The prerequisites also explain that the active `xcrun` SDK must resolve to an
absolute existing directory, the release must run natively on arm64,
`targets.toml` supplies the deployment floor, and plain native CMake callers
must explicitly pass a deployment target because there is no CMake-side
default. Recovery text names `xcode-select`/`xcrun` and removal of the failed
`build/release` cache.

Retain and sharpen the document boundary:

* Under `### Authored and checked on the lode`, list only Linux-executable
  facts: offline CMake module tests, schema/validation/failure tests, pin
  stability, and (when actually run) Linux cfgcmd byte comparison. State that
  no native macOS configure, build, archive, or manifest was produced here.
* Under `### Post-ship VPE native work`, require the D5.6 Apple Silicon
  configure/build/verbose-command/evidence/archive proof and recording of its
  results. Jer's reported versions are context, not proof that this source
  revision passed.

No other doc or historical note is rewritten. Historical design records remain
historical.

## Implementation sequence

1. Add and wire `nvat_apple_sdk.cmake` under the exact native-host guard before
   both projects; delete the two dead `if(APPLE)` floor defaults; add its
   offline script-mode tests first so guard behavior, path-with-spaces,
   explicit-input, architecture, and failure contracts are fixed.
2. Add the unconditional fmt target check/property and structural coverage.
3. Refactor the shared EP inputs, prefix all configure/build/install commands,
   and add the four-declaration structural assertions. Keep non-Apple
   expansions token-free.
4. Capture the pre-change and post-change real Linux cfgcmd/build.make
   artifacts using D5.3, then compare bytes before proceeding.
5. Add `apple.py` with host parsing, cache/compiler-metadata cross-check, one
   validator, and focused tests.
6. Thread authority floor and Apple evidence through driver, manifest,
   support fixtures, and set validation; strengthen existing authority
   macOS-field validation.
7. Add release-level failure injections and retain the existing transaction
   checkpoint matrix.
8. Update the README with the authored-vs-observed wording in D6.
9. Run the pin/notices before-after comparison, the scoped checks through
   `hop check`, `make rail-test`, and the assignment-authorized full
   `make ci` gate on the settled tree. Record shellcheck explicitly (it is part
   of `make rail-test`) and record exact counts/runtime/status. `make ci`
   proves only the Linux path. Native Darwin proof remains the explicit
   post-ship VPE step.

Steps 1–3 establish the build contract before the evidence layer attempts to
describe it. Step 4 guards Linux before rail/schema edits add noise. Steps 5–7
then make the configured facts promotion-blocking. Documentation follows the
implemented behavior.

D5.3's before/after configure-only capture is separate from `make ci`.
It needs two source states and preserves four generated cfgcmd/build.make
surfaces for byte comparison; `make ci` configures only the settled source and
then builds/tests it. The captures may reuse the same already-built CI image
and may be performed within one explicitly scripted Podman invocation with two
mounted source states, but they remain a separate recorded operation from the
full gate. Both build directories must be beneath the session scratchpad
(one pre-change and one post-change), never beneath repository `build/` and
never under `dist/`.

## Files changed by the implementation

**CMake/build:**

* add `nv-attestation-sdk-cpp/cmake/nvat_apple_sdk.cmake`;
* update `nv-attestation-sdk-cpp/CMakeLists.txt`;
* update `nv-attestation-cli/CMakeLists.txt`.

**Release rail:**

* add `sol/release/release_rail/apple.py`;
* update `sol/release/release_rail/manifest.py`;
* update `sol/release/release_rail/driver.py`;
* update `sol/release/release_rail/authority.py`;
* update `sol/release/release_rail/__init__.py` only if it maintains explicit
  exports.

**Tests:**

* add `sol/release/tests/test_apple_cmake.py`;
* add `sol/release/tests/test_apple.py`;
* update `sol/release/tests/test_manifest.py`;
* update `sol/release/tests/test_driver.py`;
* update `sol/release/tests/test_set_validator.py`;
* update `sol/release/tests/test_transaction.py`;
* update `sol/release/tests/support.py`;
* update `sol/release/tests/test_archive.py` only where exact build-tools
  fixtures require it.

**Documentation:** update `sol/release/README.md`.

`sol/release/targets.toml`, dependency pins, notices, spdlog policy, product
source, Mach-O gates, and archive schema do not change.

## Risks and settled questions

* **Native proof remains unavailable here.** Tests can prove resolution,
  quoting/list preservation, declaration wiring, evidence validation, and
  rollback. They cannot prove AppleClang/upstream Make behavior; D5.6 owns it.
* **Explicit SDK selection is intentionally strict for releases.** Plain CMake
  honors an explicit valid SDK. Release evidence additionally requires it to
  match active xcrun selection, preventing an unrepeatable cache/host mixture.
* **SDK paths in manifests are host-specific evidence.** Complete-set
  validation checks normalized absolute shape but not local existence; only
  authoring-time capture checks existence and cache equality.
* **CMake script tests increase the rail-test prerequisite surface.** Absence
  is a visible failure, never a skip.
* **Real Linux byte comparison remains network-sensitive.** There is no valid
  declaration-only substitute; use the real tree and existing container
  fallback.
* **OpenSSL optimization/warning replacement is pre-existing.** Fixing it
  would alter Linux argv and is explicitly outside this assignment.
* **No extra authority key is justified.** Existing floor and architecture
  fields contain all policy; observed version fields belong only in evidence.
* **No helper mode or release flag is added.** Function/runner injection and
  existing driver/transaction seams satisfy every automated criterion.
