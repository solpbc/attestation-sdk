# nvattest AppleClang normalization design

**Authority.** This record is the implementation authority for AppleClang
evidence normalization in `apple.resolve()`, based on the established findings
in `sol/notes/appleclang-normalization-prep.md`. The closure accepts CMake's
build-qualified `21.0.0.21000101` record as the same configured AppleClang as
the public `21.0.0` observation, keeps malformed evidence fail-closed, enriches
only resolve-time compiler-evidence diagnostics, and leaves manifest evidence
and preflight behavior unchanged.

**Citation basis.** Repository line citations refer to the pre-change
integration tip `90bbda68de49cee3afa5972fd5cd6be9aa371339`. Prep Q1-Q4 are
accepted inputs and are not re-derived here.

The implementation budget is two production/test files:

* `sol/release/release_rail/apple.py`;
* `sol/release/tests/test_apple.py`.

The prep and this design note are the only documentation records. No driver,
manifest, set-validator, shared support fixture, target authority, README, or
manifest-schema change is needed.

## D1 — Two closed grammars and one normalized comparison

Add exactly two module-level compiled expressions next to the existing
`_VERSION` and `_BUILD` definitions at
`sol/release/release_rail/apple.py:15-16`:

```python
_APPLE_CLANG_OBSERVATION = re.compile(
    r"^Apple clang version ([0-9]+\.[0-9]+\.[0-9]+)(?: \([^()\s]+\))?$"
)
_APPLE_CLANG_CMAKE_VERSION = re.compile(
    r"^([0-9]+\.[0-9]+\.[0-9]+)(?:\.[0-9]+)?$"
)
```

`_compiler()` continues to strip and inspect only the first output line, but
replaces the current `re.search()` with:

```python
match = _APPLE_CLANG_OBSERVATION.fullmatch(first)
```

(`sol/release/release_rail/apple.py:65-73`).

The public pattern is anchored at line start, full-matched, and terminates the
three-component capture with either end of line or one literal space followed
by one nonempty parenthesized token. It deliberately chooses the explicit
optional parenthesized-token tail over `(?:\s.*)?$`:

* it accepts both known producer forms exactly:
  `Apple clang version 21.0.0 (clang-2100.1.1.101)` and the bare
  `Apple clang version 1.2.3`;
* it accepts the opaque build token without capturing, parsing, or assigning
  identity to it;
* it rejects arbitrary annotations, paths, empty parentheses, nested
  parentheses, whitespace inside the token, and text after the closing
  parenthesis instead of silently broadening public evidence;
* it uses no `\b`, so a letter or dot immediately after the third component
  cannot force a shorter prefix match.

The CMake pattern full-matches exactly `X.Y.Z` or `X.Y.Z.B`, where every
component is one or more unsigned decimal digits. Group 1 is already the
normalized public identity `X.Y.Z`; no split, numeric conversion, or
split-and-rejoin operation is permitted. Leading zeros remain literal because
the records are compared as captured strings, not integers.

Add one and only one new helper:

```python
def _compiler_observation(
    compiler_command: str, runner: Runner
) -> dict[str, str]:
```

It returns `_compiler(_command((compiler_command, "--version"), runner))`.
This helper does not catch or rewrite errors. It gives `preflight()` and
`resolve()` one shared compiler-only boundary for D3 without changing
`_command()` or `_compiler()` semantics.

After a valid public compiler observation and nonempty CMake metadata have
both been obtained, the comparison is exactly this one expression:

```python
if (
    (compiler_match := _APPLE_CLANG_CMAKE_VERSION.fullmatch(compiler_version))
    is None
    or compiler_id != "AppleClang"
    or compiler_match.group(1) != compiler["version"]
):
```

The expression first proves the CMake version grammar, then requires the
case- and whitespace-sensitive ID `AppleClang`, then compares group 1 directly
to the public three-component version. The optional fourth CMake component is
accepted evidence but contributes no public identity.

### D1.1 — Accepted pairs

| public observation | CMake ID | CMake version | outcome and reason |
| --- | --- | --- | --- |
| `Apple clang version 21.0.0 (clang-2100.1.1.101)` | `AppleClang` | `21.0.0.21000101` | Accept. Both sides are valid; CMake group 1 is `21.0.0`, equal to the public capture. |
| `Apple clang version 21.0.0 (clang-2100.1.1.101)` | `AppleClang` | `21.0.0` | Accept. Both sides are valid and already have the same three-component identity. |

Both cases return evidence with:

```python
{"name": "Apple clang", "version": "21.0.0"}
```

The fourth CMake component is never copied into public evidence.

### D1.2 — Rejected CMake IDs

Every row below supplies the valid public observation
`Apple clang version 21.0.0 (clang-2100.1.1.101)` and the valid CMake version
`21.0.0.21000101`. The other side is therefore valid in every case; only the
ID causes rejection.

| CMake ID | outcome and reason |
| --- | --- |
| `Clang` | Reject: not the exact configured `AppleClang` product ID. |
| `GNU` | Reject: not AppleClang. |
| `appleclang` | Reject: ID comparison is case-sensitive. |
| `AppleClang ` | Reject: trailing whitespace is not normalized away. |
| empty | Reject in `_compiler_metadata()` as an invalid `CMAKE_CXX_COMPILER_ID`; the valid public input is configured but intentionally not invoked after the record fails closed. |

### D1.3 — Rejected CMake versions

Every row below supplies exact ID `AppleClang` and the valid public
observation `Apple clang version 21.0.0 (clang-2100.1.1.101)`. Thus a valid
public side never rescues the rejected CMake side.

| CMake version | outcome and reason |
| --- | --- |
| `20.0.0` | Reject: valid three-component grammar, but major identity differs. |
| `21.1.0` | Reject: valid grammar, but minor identity differs. |
| `21.0.1` | Reject: valid grammar, but patch identity differs. |
| `21` | Reject: fewer than three components. |
| `21.0` | Reject: fewer than three components. |
| `21.0.0.1.2` | Reject: more than one build component. |
| `21.0.0.` | Reject: empty fourth component. |
| `.21.0.0` | Reject: leading dot/empty first component. |
| `21.0.0.21000101.1` | Reject: five components. |
| `+21.0.0` | Reject: sign/prefix is outside the unsigned-decimal grammar. |
| `-21.0.0` | Reject: sign/prefix is outside the unsigned-decimal grammar. |
| `21.0.0 ` | Reject: trailing whitespace is not stripped from a CMake record. |
| ` 21.0.0` | Reject: leading whitespace is not stripped from a CMake record. |
| `21.0.0rc1` | Reject: nondecimal suffix and no prefix matching. |
| `v21.0.0` | Reject: product-style prefix is not a CMake version. |
| empty | Reject in `_compiler_metadata()` as invalid `CMAKE_CXX_COMPILER_VERSION`; the valid public input is configured but not invoked after the record fails closed. |
| absent | Reject in `_compiler_metadata()` with an explicit invalid/missing `CMAKE_CXX_COMPILER_VERSION` record statement; the valid public input is configured but not invoked. |

### D1.4 — Rejected public observations

Every row below supplies the exact valid CMake pair
`AppleClang` / `21.0.0.21000101`. The CMake side is valid in every case, so it
cannot rescue a bad or unavailable public observation.

| public observation/input outcome | outcome and reason |
| --- | --- |
| `Apple clang version 21.0` | Reject: only two public components. |
| `Apple clang version 21.0.0.21000101 (x)` | Reject: four public components; the dot cannot terminate group 1. |
| `Apple clang version 21.0.0rc1` | Reject: the letter suffix cannot terminate group 1. |
| `Apple clang version 21.0.0.1.2 (x)` | Reject: five public components; no prefix match. |
| `prefixed Apple clang version 21.0.0 (x)` | Reject: the product phrase is not at line start. |
| `Apple LLVM version 21.0.0` | Reject: wrong public product phrase. |
| `Apple clang version 21.0.0 arbitrary` | Reject: arbitrary whitespace tail is not a parenthesized token. |
| `Apple clang version 21.0.0 (clang-2100) extra` | Reject: text follows the one allowed token. |
| stderr-only with return code zero and empty stdout | Reject in `_command()` as empty public output; stderr does not become compiler evidence. |
| empty stdout and stderr with return code zero | Reject in `_command()` as empty public output. |

The existing nonzero-return path remains a separate rejection regardless of
stdout/stderr contents (`sol/release/release_rail/apple.py:50-55`).

## D2 — Tightening is shared with preflight, without contract drift

The stricter `_compiler()` grammar intentionally applies to both entry points:

* preflight observes the authority-selected PATH-relative compiler before a
  transaction (`sol/release/release_rail/apple.py:146-149`;
  `sol/release/release_rail/driver.py:528-567`);
* resolve observes the compiler path selected by CMake after the native build
  (`sol/release/release_rail/apple.py:218-234`;
  `sol/release/release_rail/driver.py:629-639`).

Allowing a malformed public product/version in preflight but rejecting it in
resolve would make the two evidence gates disagree. Prep Q2 established that
the two shipped `test_apple.py` observations already satisfy the chosen
grammar, the generic manifest compiler fixture uses a separate parser, and no
other shipped fixture reaches `_compiler()`
(`sol/notes/appleclang-normalization-prep.md:109-150`). Tightening both paths
is therefore intended.

Prep Q1 established the complete asserted diagnostic surface
(`sol/notes/appleclang-normalization-prep.md:59-107`). The design preserves it
as follows:

| asserted fragment | decision |
| --- | --- |
| `authority deployment target is invalid` | Keep the complete `_target_values()` message verbatim. This is the one `apple.py` diagnostic asserted outside `test_apple.py`. |
| `configured SDK sysroot` | Keep the complete resolve SDK-sysroot message verbatim. |
| `configured architecture` | Keep the complete resolve architecture message verbatim. |
| `configured deployment target` | Keep the complete resolve deployment message verbatim. |
| `compiler observation` | Keep this exact substring in D3's enriched mismatch message. The surrounding message intentionally changes to include all four compiler-evidence elements. |
| `cannot read` | Keep `_cache()` messages verbatim. Enriched metadata messages also retain the substring. |
| `one configured` | Keep this exact substring in the enriched missing/ambiguous metadata message. |
| `cannot read <metadata>: permission denied; remove the build directory` | Keep this entire contiguous substring verbatim inside the enriched unreadable-metadata message. |
| `failed: not selected.*then retry` | Keep `_command()` and preflight propagation verbatim, so the existing regex remains valid. Resolve composition removes only the repeated domain prefix and retains the one existing recovery tail. |

No listed fragment changes silently. Only the complete resolve-time
compiler-metadata and mismatch messages are enriched. The authority, command,
compiler-parser, Xcode, SDK, cache, configured SDK, architecture, deployment,
and manifest-validation message templates otherwise remain unchanged
(`sol/release/release_rail/apple.py:35-143,152-184,235-335`).

## D3 — Metadata first, compiler-only composition, and unchanged preflight

### D3.1 — Contract scope

The four-element diagnostic contract applies exactly to these resolve-time
compiler-evidence rejections:

1. missing, unreadable, or non-executable configured compiler path;
2. configured compiler invocation returning nonzero;
3. configured compiler invocation returning empty stdout, including
   stderr-only output;
4. public compiler output failing `_compiler()` grammar;
5. missing, ambiguous, unreadable, absent-field, empty-field, or otherwise
   malformed CMake compiler ID/version record;
6. valid public observation and CMake record that fail the D1 identity
   comparison.

These are the rejection classes enumerated by criterion 3. `_cache()` failures
that occur before a configured compiler path can be obtained retain their
existing messages: element (a) does not exist yet. Authority target, Xcode,
xcrun SDK, configured SDK sysroot, architecture, and deployment-floor
rejections are not compiler-evidence rejections and retain their shipped
diagnostics. This pin follows the criterion's compiler-evidence wording and
avoids mislabeling unrelated Apple failures.

In particular, there is no blanket catch around `_observed()`. Once refactored,
`_observed()` owns only Xcode/SDK observation plus final evidence validation.
An authority-floor, Xcode, or xcrun error can never be rewritten as a compiler
observation error.

### D3.2 — Exact signatures

The exact new or changed internal signatures are:

```python
def _compiler_observation(
    compiler_command: str, runner: Runner
) -> dict[str, str]:
```

```python
def _observed(
    compiler: dict[str, str],
    target: dict[str, Any],
    runner: Runner,
    *,
    architecture: str,
    floor: str,
) -> dict[str, Any]:
```

```python
def _compiler_metadata(
    build_dir: Path, compiler_command: str
) -> tuple[str, str]:
```

The following signatures do not change:

```python
def _compiler(output: str) -> dict[str, str]:
```

```python
def preflight(
    target: dict[str, Any], runner: Runner = subprocess.run
) -> dict[str, Any]:
```

```python
def resolve(
    target: dict[str, Any],
    build_dir: Path,
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
```

`_observed()` receives an already-parsed compiler dict and already-validated
architecture/floor values. It no longer calls the compiler command or derives
target values itself. It retains the current xcodebuild/xcrun sequence, SDK
checks, evidence object, and `validate_evidence(..., target)` call
(`sol/release/release_rail/apple.py:113-143`).

### D3.3 — Exact order

`preflight()` preserves its current semantic order:

1. call `_target_values(target)`;
2. call `_compiler_observation(target["required_tools"][0], runner)`;
3. pass the parsed compiler and target values to `_observed()`.

That order is necessary for the real invalid-floor driver test to retain
`authority deployment target is invalid` before any PATH lookup
(`sol/release/tests/test_driver.py:1073-1126`). It also leaves every preflight
`_command()` and `_compiler()` message byte-for-byte unchanged.

`resolve()` uses this order:

1. read `_cache(build_dir)` and retain the exact
   `values["CMAKE_CXX_COMPILER"]` string as `compiler_command`;
2. call `_target_values(target)` so authority errors retain precedence and
   wording;
3. call `_compiler_metadata(build_dir, compiler_command)`;
4. call `_compiler_observation(compiler_command, runner)` inside a catch scoped
   to that helper only;
5. apply D1's one comparison expression;
6. pass the valid compiler and target values to `_observed()` for Xcode/SDK
   evidence;
7. retain the current configured SDK, architecture, and deployment checks.

Reading metadata before public observation guarantees that any compiler
invocation/parser rejection can name the CMake ID/version. When metadata
cannot provide a record, `_compiler_metadata()` names the configured compiler
path and explicitly records `public observation not attempted`; it does not
invoke the compiler after the prerequisite record has failed closed.

### D3.4 — Exact message templates

Change `_compiler_metadata()` only enough to accept `compiler_command` and emit
these exact templates.

Missing or ambiguous metadata file:

```text
Apple toolchain evidence failed: configured compiler {compiler_command!r}; public observation not attempted; CMake ID/version record is missing or ambiguous: cannot read one configured C++ compiler record under {build_dir / 'CMakeFiles'}; remove the build directory and rerun the native configure
```

Unreadable metadata file:

```text
Apple toolchain evidence failed: configured compiler {compiler_command!r}; public observation not attempted; CMake ID/version record is unreadable: cannot read {paths[0]}: {error}; remove the build directory and rerun the native configure
```

Absent, empty, duplicated, or otherwise invalid exact field:

```text
Apple toolchain evidence failed: configured compiler {compiler_command!r}; public observation not attempted; CMake ID/version record is malformed: configured C++ compiler record has invalid {name}; remove the build directory and rerun the native configure
```

The existing `field()` logic already maps missing, duplicate, empty, or
malformed exact `set(...)` fields into its invalid-field branch
(`sol/release/release_rail/apple.py:203-215`). No looser metadata parsing is
introduced.

For a failure from `_compiler_observation()`, `resolve()` computes:

```python
detail = str(error).removeprefix("Apple toolchain evidence failed: ")
```

and emits:

```text
Apple toolchain evidence failed: configured compiler {compiler_command!r}; CMake ID/version record is {compiler_id!r} {compiler_version!r}; public observation {detail}
```

It adds no recovery tail. Every possible `detail` from `_command()` or
`_compiler()` already ends in exactly one concrete recovery action, so the
rendered composition has one domain prefix and one terminal recovery.
Preflight receives the original exception directly and is untouched.

For a D1 comparison failure after both sides parse, emit:

```text
Apple toolchain evidence failed: configured compiler {compiler_command!r}; compiler observation is {compiler['name']!r} {compiler['version']!r}; CMake ID/version record is {compiler_id!r} {compiler_version!r}; records do not identify the same normalized AppleClang; select one Xcode toolchain, remove build/release, and retry
```

This preserves `compiler observation` while distinguishing grammar, ID, and
identity rejection through the displayed exact records.

### D3.5 — Literal rendered compositions

With configured path `/tmp/missing-clang++` and valid build-qualified metadata:

```text
Apple toolchain evidence failed: configured compiler '/tmp/missing-clang++'; CMake ID/version record is 'AppleClang' '21.0.0.21000101'; public observation cannot invoke /tmp/missing-clang++: [Errno 2] No such file or directory: '/tmp/missing-clang++'; install Xcode Command Line Tools and verify the active developer directory with `xcode-select -p`, then retry
```

With configured path `/tools/clang++` returning status 1 and stderr
`not selected`:

```text
Apple toolchain evidence failed: configured compiler '/tools/clang++'; CMake ID/version record is 'AppleClang' '21.0.0.21000101'; public observation /tools/clang++ --version failed: not selected; select a valid Xcode developer directory with `xcode-select`, then retry
```

With configured path `/tools/clang++` returning unparseable stdout
`clang version 21.0.0`:

```text
Apple toolchain evidence failed: configured compiler '/tools/clang++'; CMake ID/version record is 'AppleClang' '21.0.0.21000101'; public observation compiler is not normalized AppleClang: 'clang version 21.0.0'; select the Xcode AppleClang toolchain, then retry
```

With an absent CMake version field:

```text
Apple toolchain evidence failed: configured compiler '/tools/clang++'; public observation not attempted; CMake ID/version record is malformed: configured C++ compiler record has invalid CMAKE_CXX_COMPILER_VERSION; remove the build directory and rerun the native configure
```

With a valid public observation and mismatched CMake version:

```text
Apple toolchain evidence failed: configured compiler '/tools/clang++'; compiler observation is 'Apple clang' '21.0.0'; CMake ID/version record is 'AppleClang' '20.0.0'; records do not identify the same normalized AppleClang; select one Xcode toolchain, remove build/release, and retry
```

Each message names the configured path, gives an explicit public outcome,
gives the CMake record or explicit missing/malformed statement, and ends with
one recovery action.

## D4 — No resolve-only compiler-path precheck

Ratify prep Q4: add no existence, readability, or executable-bit precheck.
Real `subprocess.run` raised `FileNotFoundError` for a missing path and
`PermissionError` for mode-`000` and mode-`0644` files; all are `OSError`
subclasses already closed by `_command()`, whose message names
`arguments[0]` (`sol/notes/appleclang-normalization-prep.md:251-307`;
`sol/release/release_rail/apple.py:35-49`).

The regression test will use real temporary filesystem entries and call
`apple.resolve(target, build_dir)` without a runner argument:

* missing: leave the exact cached compiler path absent;
* unreadable: create a script fixture and set mode `000`;
* non-executable: create the same script fixture and set mode `0644`.

`write_build()` will create otherwise-valid cache and build-qualified metadata
first. Because metadata is read before invocation and the compiler is the
first live command, real `subprocess.run` fails before xcodebuild/xcrun are
needed. Each subtest asserts the exact configured path, explicit public
failure, valid CMake ID/version, and `_command()`'s one recovery tail.

The prep measurement ran as UID 1001, not root. The test records that caveat
without adding a UID-dependent skip: lack of every execute bit remains
non-executable for UID 0, while the test's mode-`000` file also lacks execute
permission. The fixture proves the OS boundary rather than mocking an
`OSError`.

A shared precheck would be wrong because preflight intentionally passes
PATH-relative `"clang++"` (`sol/release/release_rail/apple.py:146-149`;
`sol/release/targets.toml:66-89`). A resolve-only precheck would duplicate
`execve` behavior without improving closure or diagnostics.

## D5 — Manifest evidence remains historical, exact, and unnormalized

Criterion 4 is pinned exactly as directed:

* `validate_evidence()` does not change;
* shared `_VERSION` does not change;
* the exact Apple evidence shape remains
  `{"apple_clang": {"name": "Apple clang", "version": <record>}, ...}`;
* no normalizer is called from manifest capture, construction, serialization,
  or validation.

Prep Q3 proved every on-disk and in-memory manifest path terminates at
`apple.validate_evidence()` and cannot transit `resolve()` or `preflight()`
(`sol/notes/appleclang-normalization-prep.md:152-249`). D1's CMake pattern and
comparison expression live only on `resolve()`'s local CMake/public
cross-check.

Consequently:

1. Manifest Apple evidence containing `21.0.0.21000101` remains valid under
   unchanged `_VERSION`, remains exactly `21.0.0.21000101` after validation
   and JSON round-trip, and is not equal to historical public `21.0.0`.
2. Historical public evidence containing `21.0.0` remains valid and
   round-trips with `apple_clang` exactly
   `{"name": "Apple clang", "version": "21.0.0"}` and exactly ordered keys
   `("name", "version")`.
3. Resolve emits only the public three-component capture for new evidence. It
   does not rewrite already-authored manifest data.

Two `test_apple.py` tests establish the boundary:

* `test_manifest_validation_does_not_normalize_build_qualified_appleclang_version`
  creates a real temporary artifact and shared Darwin `build_tools`, changes
  only `apple_toolchain.apple_clang.version` to `21.0.0.21000101`, constructs
  a complete in-memory manifest with `manifest.build()`, JSON-round-trips it,
  validates its `build_tools` again, and asserts the value remains
  build-qualified and distinct from `21.0.0`.
* `test_historical_public_appleclang_evidence_round_trips` sets the same field
  to `21.0.0`, constructs and JSON-round-trips the same complete manifest,
  validates it, then asserts the exact `apple_clang` dict and key order.

Both use `self.root / "artifact.tar.xz"` with fixed bytes,
`authority.load().release`, `self.target`, version `1.2.2-sol.2`,
`support.SOURCE`, an empty dependency list, and `support.tools_for(self.target)`
as the exact `manifest.build()` fixture shape.

These tests require `json`, `manifest`, and the existing `support.SOURCE` and
`support.tools_for` fixtures in `test_apple.py`; they require no production
manifest change. Prep does not contradict this interpretation.

## D6 — One extended fixture and complete regression matrix

All regression work stays in
`sol/release/tests/test_apple.py:16-200`. Extend the existing harness rather
than creating a second runner or build fixture.

### D6.1 — Existing fixture changes

In `setUp()`, add:

* `self.commands`, initially empty, to capture every exact argv tuple;
* `self.command_results`, mapping the existing compiler, xcodebuild, SDK-path,
  and SDK-version argv tuples to `(returncode, stdout, stderr)`.

Keep the current default outputs byte-for-byte, including both public compiler
forms at `sol/release/tests/test_apple.py:27-45`. Change `runner()` to append
`tuple(arguments)` to `self.commands`, read the matching mutable result tuple,
and return `subprocess.CompletedProcess`. Existing tests keep using
`self.runner`; individual table cases mutate only the compiler result.

Change the test helper signature to:

```python
def write_build(
    self,
    *,
    compiler_id="AppleClang",
    compiler_version="1.2.3",
    compiler_metadata=None,
    **overrides,
):
```

When `compiler_metadata is None`, render the current two exact `set(...)`
lines from `compiler_id` and `compiler_version`. Otherwise write the supplied
raw metadata text, enabling absent/duplicate/empty field cases through the
same helper. Cache overrides continue to work exactly as today
(`sol/release/tests/test_apple.py:50-68`).

### D6.2 — New tests

1. `test_resolve_normalizes_native_build_qualified_appleclang_identity`

   Set both compiler argv results to the exact native public line
   `Apple clang version 21.0.0 (clang-2100.1.1.101)\n`; write CMake metadata
   `AppleClang` / `21.0.0.21000101`; call resolve through the existing runner.
   Assert `apple_clang` is exactly
   `{"name": "Apple clang", "version": "21.0.0"}` and the complete evidence
   equals `self.evidence()`, proving Xcode, SDK, architecture, deployment, and
   key order are otherwise unchanged.

2. `test_resolve_accepts_exact_three_component_cmake_version`

   Use the same exact native public line and CMake metadata
   `AppleClang` / `21.0.0`. Assert the same exact normalized compiler dict and
   otherwise unchanged full evidence.

3. `test_resolve_rejects_invalid_cmake_appleclang_records`

   Use one table with `subTest` for every D1.2 ID and D1.3 version row. Supply
   the valid native public observation and vary only ID/version/raw metadata.
   Assert `AppleToolchainError`, exact configured path, either the displayed
   invalid CMake record or explicit missing/malformed statement, the public
   outcome (`'Apple clang' '21.0.0'` or `not attempted`), and one concrete
   recovery tail. This proves a valid public input never rescues bad CMake
   evidence.

4. `test_resolve_rejects_invalid_public_appleclang_observations`

   Use one table with `subTest` for every D1.4 row. Keep CMake fixed at
   `AppleClang` / `21.0.0.21000101`; vary compiler stdout/stderr/return code
   through `self.command_results`. Assert rejection, the exact configured
   path, the valid CMake record, the public failure detail, and exactly one
   `then retry`. This proves a valid CMake record never rescues bad public
   evidence and proves the explicit-tail grammar.

5. `test_resolve_invokes_exact_cache_compiler_path`

   Set `CMAKE_CXX_COMPILER` to a distinctive string containing directory
   spaces, add that exact argv tuple to `self.command_results`, and call
   resolve. Assert the first captured command is exactly
   `(configured_compiler, "--version")`, with no `Path.resolve()`, basename,
   PATH lookup, trimming, or authority fallback. The mutable runner captures
   arguments before returning its fixture output.

6. `test_resolve_real_subprocess_compiler_path_failures_are_closed`

   Table the missing, mode-`000`, and mode-`0644` compiler paths described in
   D4. Write valid build-qualified metadata and call `apple.resolve()` with no
   runner. Assert all four diagnostic elements and the one terminal recovery
   for each real `FileNotFoundError`/`PermissionError` boundary.

7. `test_resolve_compiler_observation_failures_compose_one_recovery`

   Table a nonzero invocation with stderr `not selected`, zero-status empty
   stdout, and zero-status unparseable stdout using the injected runner. Assert
   the exact rendered D3 composition, configured path, valid CMake record,
   public outcome, and one occurrence of `then retry`. This directly guards
   prefix removal and prevents a nested/double recovery tail.

8. `test_resolve_missing_and_malformed_metadata_name_compiler_context`

   Table absent ID, absent version, empty ID, empty version, duplicate field,
   and ambiguous metadata-file cases through `write_build()`. Assert configured
   compiler path, `public observation not attempted`, an explicit CMake
   missing/ambiguous/malformed statement, the relevant field name, and the
   recovery action. Assert the runner captured no compiler invocation.

9. `test_manifest_validation_does_not_normalize_build_qualified_appleclang_version`

   Use D5's complete in-memory manifest and assertions before and after JSON
   round-trip.

10. `test_historical_public_appleclang_evidence_round_trips`

    Use D5's complete manifest with public three-component evidence and assert
    the exact dict, value, and key order after JSON round-trip and validation.

The two D1 accept cases may be implemented as a two-row `subTest` table shared
by tests 1 and 2 only if both named acceptance assertions remain explicit.
The rejection tables must preserve each listed value as a separate subtest so
one malformed case cannot stand in for another.

### D6.3 — Existing test changes and unchanged tests

Strengthen these existing tests without changing their purpose:

* `test_cache_and_compiler_disagreements_fail_closed`
  keeps the SDK, architecture, deployment, and compiler-mismatch cases. Its
  compiler case additionally asserts the configured path, both evidence
  outcomes, and recovery while retaining `compiler observation`
  (`sol/release/tests/test_apple.py:94-128`).
* `test_missing_cache_and_ambiguous_metadata_fail_closed` retains the
  verbatim cache `cannot read` assertion. Its ambiguous-metadata assertion is
  strengthened for D3's four elements while retaining `one configured`
  (`sol/release/tests/test_apple.py:143-155`).
* `test_unreadable_compiler_metadata_is_normalized` retains its current exact
  contiguous `cannot read <metadata>: permission denied; remove the build
  directory` regex and adds configured path plus `public observation not
  attempted` assertions (`sol/release/tests/test_apple.py:157-175`).

These existing tests remain behaviorally unchanged:

* preflight's closed normalized-evidence assertion;
* resolve's cache/metadata cross-check happy path;
* non-arm64 host-authority rejection;
* malformed/target-inconsistent `validate_evidence()` rejection;
* preflight `_command()`'s
  `failed: not selected.*then retry` contract
  (`sol/release/tests/test_apple.py:70-92,130-142,177-200`).

`sol/release/tests/support.py` does not change. Its Apple compiler version
`1.2.3`, exact `("name", "version")` shape, and separate generic compiler
record already satisfy D1 and D5
(`sol/release/tests/support.py:15-18,21-49`).

## Acceptance map and implementation order

| order | implementation unit | acceptance owned |
| --- | --- | --- |
| 1 | Add both D1 compiled patterns and change `_compiler()` to full-match the public expression. | Exact public grammar and no prefix matches. |
| 2 | Add `_compiler_observation()` and change `_observed()` to accept parsed compiler plus target values. Update preflight first so its target/compiler/Xcode/SDK order remains unchanged. | Shared grammar with unchanged preflight behavior and diagnostics. |
| 3 | Change `_compiler_metadata()` to accept the configured compiler path and emit D3 metadata templates. | Missing/malformed metadata names path, public outcome, CMake outcome, and recovery. |
| 4 | Reorder resolve, add the scoped helper catch/prefix removal, apply the one D1 comparison expression, and retain SDK/architecture/deployment checks. | Native build-qualified normalization, comparison rejection, single recovery, and no semantic smearing. |
| 5 | Extend the existing test runner and `write_build()` fixtures. | One reusable harness for all cases and exact configured argv capture. |
| 6 | Add D1-D4 resolve tests and strengthen the three existing diagnostic tests. | Full accept/reject matrix, four-element diagnostics, real-subprocess closure, and preserved strings. |
| 7 | Add the two D5 manifest/validator tests. | Historical records remain exact, distinct, and unnormalized. |

Only after steps 1-4 are complete should the table tests be added, because
their expected diagnostics depend on metadata-first ordering and the final
composition templates. Manifest tests are independent of production changes
and intentionally confirm no validator edit occurred.

## Risks and open questions

* The explicit parenthesized-token tail will reject a future legitimate Apple
  first-line suffix that is not one opaque token. This is deliberate
  fail-closed behavior; such a producer change requires new observed evidence
  and a grammar decision rather than a permissive tail today.
* Resolve diagnostic composition depends on every
  `_compiler_observation()` error retaining the established
  `Apple toolchain evidence failed: ` prefix. The exact rendered-message tests
  pin that invariant and the one-recovery rule.
* Metadata-first ordering deliberately does not invoke a compiler when the
  CMake ID/version record is missing or structurally invalid. The explicit
  `public observation not attempted` outcome satisfies the diagnostic contract
  without running untrusted/unanchored evidence after a prerequisite failure.
* The real permission measurement was UID 1001 rather than UID 0. D4's modes
  remove all execute bits, so the test has no root-only success path; the note
  must not claim a locally observed UID-0 run.
* `_VERSION` continuing to accept build-qualified historical manifest evidence
  is intentional. Tightening it would violate criterion 4 and broaden the
  implementation beyond resolve-time comparison.

There are no unresolved design questions. Any pressure to accept arbitrary
public tails, normalize manifest evidence, add a path precheck, wrap all of
`_observed()`, or change driver/support fixtures is outside this closure.
