# nvattest AppleClang normalization prep

Research captured on the Linux x86_64 lode
`/home/extro/.hopper/worktrees/7qkl5xk2` on 2026-07-27. The repository tip was
`90bbda68de49cee3afa5972fd5cd6be9aa371339`, and the tree was clean before this
note. No production or test file was changed. The current checkout contains
335 lines in `apple.py` and 204 lines in `test_apple.py`; both were read end to
end despite the directions' 336/205 line-count labels.

The current implementation has three deliberately separate boundaries:

* `_command()` invokes one command through an injectable runner, normalizes
  `OSError`, nonzero status, and empty stdout into actionable
  `AppleToolchainError` diagnostics, and returns stripped stdout
  (`sol/release/release_rail/apple.py:28-62`).
* `_compiler()`, `_xcode()`, and `_observed()` turn live compiler, Xcode, xcrun
  SDK, target architecture, and deployment-floor observations into one closed
  evidence object (`sol/release/release_rail/apple.py:65-143`). `preflight()`
  supplies the authority's PATH-relative first required tool to that path
  (`sol/release/release_rail/apple.py:146-149`;
  `sol/release/targets.toml:66-89`).
* `resolve()` reads exact CMake cache fields, observes the compiler executable
  selected by CMake, reads the single generated compiler metadata record, and
  byte-compares its ID/version with the public compiler observation before
  checking SDK, architecture, and deployment target
  (`sol/release/release_rail/apple.py:152-261`). The failing comparison is
  specifically `compiler_version != evidence["apple_clang"]["version"]`
  (`sol/release/release_rail/apple.py:223-234`).
* `validate_evidence()` is a schema/value validator. It requires exact ordered
  field tuples, nonempty strings, canonical names, numeric versions, an
  absolute SDK path, and optional target consistency; it performs no command
  invocation or CMake resolution (`sol/release/release_rail/apple.py:264-335`).

## Baseline

The requested baseline was run through `hop check` so its real exit status was
preserved:

```text
$ hop check -n 300 -- python3 -m unittest discover -s sol/release/tests -p 'test_*.py'
hop check: `python3 -m unittest discover -s sol/release/tests -p test_*.py` exited 0
........................s.............................................-- The CXX compiler identification is GNU 13.3.0
-- Detecting CXX compiler ABI info
-- Detecting CXX compiler ABI info - done
-- Check for working CXX compiler: /usr/bin/c++ - skipped
-- Detecting CXX compile features
-- Detecting CXX compile features - done
-- ENGINE=3.31.10
-- Configuring incomplete, errors occurred!
..............................s.............................................
----------------------------------------------------------------------
Ran 146 tests in 18.662s

OK (skipped=2)
```

The exact baseline is therefore 146 tests, green, with two skips.

## Q1 — Message contracts outside `test_apple.py`

An exhaustive grep for `Apple toolchain evidence` and distinctive fragments
from every `AppleToolchainError` in `apple.py` found exactly one production
`apple.py` diagnostic asserted outside `test_apple.py`:
`authority deployment target is invalid`.

For completeness, this table records that outside contract and every
message-fragment assertion in `test_apple.py` that directly reaches a matching
`apple.py` emitter:

| message fragment or regex | asserting test | `apple.py` emitter |
| --- | --- | --- |
| `authority deployment target is invalid` | `test_driver.DriverRuntimeTest.test_macos_floor_failures_fire_in_real_preflight_before_transaction` (`sol/release/tests/test_driver.py:1073-1126`) — **outside `test_apple.py`** | `_target_values()` (`sol/release/release_rail/apple.py:98-104`) |
| `configured SDK sysroot` | `test_apple.AppleToolchainTest.test_cache_and_compiler_disagreements_fail_closed` (`sol/release/tests/test_apple.py:94-128`) | `resolve()` (`sol/release/release_rail/apple.py:235-247`) |
| `configured architecture` | same test (`sol/release/tests/test_apple.py:94-128`) | `resolve()` (`sol/release/release_rail/apple.py:248-253`) |
| `configured deployment target` | same test (`sol/release/tests/test_apple.py:94-128`) | `resolve()` (`sol/release/release_rail/apple.py:254-260`) |
| `compiler observation` | same test (`sol/release/tests/test_apple.py:94-128`) | `resolve()` (`sol/release/release_rail/apple.py:225-234`) |
| `cannot read` for the absent cache | `test_apple.AppleToolchainTest.test_missing_cache_and_ambiguous_metadata_fail_closed` (`sol/release/tests/test_apple.py:143-155`) | `_cache()` (`sol/release/release_rail/apple.py:152-160`) |
| `one configured` | same test (`sol/release/tests/test_apple.py:143-155`) | `_compiler_metadata()` (`sol/release/release_rail/apple.py:187-194`) |
| `cannot read <metadata>: permission denied; remove the build directory` | `test_apple.AppleToolchainTest.test_unreadable_compiler_metadata_is_normalized` (`sol/release/tests/test_apple.py:157-175`) | `_compiler_metadata()` (`sol/release/release_rail/apple.py:195-201`) |
| `failed: not selected.*then retry` | `test_apple.AppleToolchainTest.test_command_and_output_failures_are_actionable` (`sol/release/tests/test_apple.py:193-200`) | `_command()` nonzero branch (`sol/release/release_rail/apple.py:50-55`) |

The specifically named driver sites do not add hidden message contracts:

* `test_macos_preflight_captures_apple_evidence_before_dist` asserts that
  `driver._preflight()` calls `apple.preflight(target)` and threads its returned
  object into `manifest.capture_build_tools()`; it asserts no diagnostic text
  (`sol/release/tests/test_driver.py:681-704`).
* `test_macos_resolve_inconsistency_never_publishes` mocks `apple.resolve()` to
  raise the synthetic literal `configured SDK differs from active SDK` and
  checks propagation and transaction behavior
  (`sol/release/tests/test_driver.py:1018-1071`). No `apple.py` line emits that
  exact contiguous string. The real closest diagnostic inserts the configured
  sysroot and both paths (`sol/release/release_rail/apple.py:242-247`).
* The two `Apple SDK discovery returned ...` strings are likewise synthetic
  mocked `apple.preflight()` exceptions, not `apple.py` output
  (`sol/release/tests/test_driver.py:955-1016`). `Apple tools broke` only checks
  the CLI's generic exception presentation
  (`sol/release/tests/test_driver.py:258-277`).
* The grep hit `cannot invoke xcrun` belongs to a standalone CMake SDK test and
  does not call `apple._command()` (`sol/release/tests/test_apple_cmake.py:195-225`).
  Set validation asserts its own wrapping prefix rather than an inner Apple
  diagnostic (`sol/release/tests/test_set_validator.py:225-234`).

Thus the outside production-string contract to preserve is the
`_target_values()` authority-floor literal. The local `test_apple.py`
contracts in the table, especially `_command()`'s nonzero recovery wording,
must also remain intact.

## Q2 — `_compiler()` grammar and fixture blast radius

Before this note was created, the exhaustive fixed-string search under `sol/`
had five hits:

| hit | role | survives an exactly-three-component public-observation grammar? |
| --- | --- | --- |
| `sol/release/release_rail/apple.py:67` | The current `re.search` implementation itself. | This is the production expression to be tightened, not input data; it will be replaced rather than parsed. |
| `sol/release/tests/test_apple.py:29` | Preflight fixture, `Apple clang version 1.2.3 (clang-123)`. | Yes. It begins with the required product/version form and has exactly three numeric components plus the canonical parenthesized build suffix. |
| `sol/release/tests/test_apple.py:30` | Resolve fixture, `Apple clang version 1.2.3`. | Yes. It is the bare required product/version form with exactly three components. |
| `sol/release/tests/test_manifest.py:33` | Generic `build_tools.compiler` fixture, `Apple clang version 16.0.0 /host/path`. | Its test behavior survives because it is parsed only by `manifest.normalize_tool_output()`, not `apple._compiler()` (`sol/release/release_rail/manifest.py:68-78`; `sol/release/tests/test_manifest.py:16-57`). It would not be evidence about the tightened `apple._compiler()` grammar. |
| `sol/notes/tri-target-prep.md:305` | Prose. | Unaffected; it is never parsed. |

This report necessarily quotes the searched literal below; those self-hits are
not pre-existing fixtures or production touch points.

The current expression is
`\bApple clang version ([0-9]+(?:\.[0-9]+){1,3})\b` and is applied with
`re.search()` to the stripped first output line
(`sol/release/release_rail/apple.py:65-73`). A throwaway `python3 -c` using that
exact expression produced:

```text
'Apple clang version 21.0.0 (clang-2100.1.1.101)' -> '21.0.0'
'Apple clang version 21.0.0.21000101 (clang-x)' -> '21.0.0.21000101'
'Apple clang version 21.0 (x)' -> '21.0'
'Apple clang version 21.0.0rc1' -> '21.0'
'Apple clang version 21.0.0.1.2 (x)' -> '21.0.0.1'
'prefixed Apple clang version 21.0.0 (x)' -> '21.0.0'
```

The claim about `21.0.0rc1` is correct, with an important precision: the
current match backtracks to and returns `21.0`, not `21.0.0`. The boundary
between the second component's final `0` and the following `.` succeeds after
the greedy repeated group gives up `.0`; the boundary after `21.0.0` would
fail because `0` and `r` are both word characters. The same combination of a
bounded repetition, `\b`, and unanchored search admits a four-component prefix
of the five-component input and accepts a prefixed product string. Under the
stated tightened public grammar, only the first observation is valid among
the six canonical edge cases; the other five are rejected for four
components, two components, a nonnumeric suffix, five components, and a
prefixed line respectively.

## Q3 — Manifest reachability

There are four manifest/build-tools validation paths into `apple.py`, and all
terminate at `apple.validate_evidence()`:

```text
in-memory Apple evidence
  -> manifest.capture_build_tools()
  -> apple.validate_evidence()

in-memory build_tools
  -> manifest.validate_build_tools()
  -> apple.validate_evidence()

in-memory manifest construction
  -> manifest.build()
  -> manifest.validate_build_tools()
  -> apple.validate_evidence()

on-disk *.manifest.json
  -> rail.py validate-set
  -> set_validator.validate()
  -> set_validator._validate_one()
  -> json.loads()
  -> manifest.validate_build_tools()
  -> apple.validate_evidence()
```

The first path is the Darwin branch at
`sol/release/release_rail/manifest.py:104-160`. The second is the Darwin branch
at `sol/release/release_rail/manifest.py:163-190`. `manifest.build()` invokes
that second path before assembling the manifest
(`sol/release/release_rail/manifest.py:193-254`). The on-disk CLI entry point is
`sol/release/rail.py:100-117`; set validation locates and parses manifests at
`sol/release/release_rail/set_validator.py:179-220`, then `_validate_one()`
parses the selected file and validates `value["build_tools"]`
(`sol/release/release_rail/set_validator.py:65-93,244-249`).

Those paths account for both production manifest call sites of
`apple.validate_evidence()`. The only other production call is internal to
`apple._observed()`, where newly captured live evidence is closed before it is
returned (`sol/release/release_rail/apple.py:113-143`). The remaining direct
call is test-only (`sol/release/tests/test_apple.py:177-191`).

Test construction uses the same in-memory path. `support.tools_for()` supplies
the closed Apple evidence fixture (`sol/release/tests/support.py:21-49`), and
`support.make_quartet()` passes it through `manifest.build()` before writing
the manifest (`sol/release/tests/support.py:94-120`). `test_archive` also calls
`manifest.build()` and `manifest.write()` directly
(`sol/release/tests/test_archive.py:25-55`). On-disk mutation coverage then
re-enters through `set_validator.validate()`
(`sol/release/tests/test_set_validator.py:21-47,180-234`).

Neither manifest validation nor construction can transit `resolve()` or
`preflight()`:

* The only production caller of `apple.preflight()` is
  `driver._preflight()` (`sol/release/release_rail/driver.py:528-567`).
  The CLI release path calls `_preflight()` before starting the transaction
  (`sol/release/release_rail/driver.py:570-576`).
* The only production caller of `apple.resolve()` is the post-build release
  builder (`sol/release/release_rail/driver.py:584-639`). Its return value then
  flows forward into `manifest.capture_build_tools()`, `manifest.build()`, and
  `manifest.write()` (`sol/release/release_rail/driver.py:629-650`). That edge
  is `resolve -> manifest`, never `manifest -> resolve`.
* `apple.validate_evidence()` only validates its argument and target; it calls
  `_target_values()` but not either live-observation entry point
  (`sol/release/release_rail/apple.py:264-335`). The manifest module has no call
  to `resolve()` or `preflight()` (`sol/release/release_rail/manifest.py:12-261`).
  `manifest.write()` is a serialization/sidecar leaf and performs no validation
  or Apple call (`sol/release/release_rail/manifest.py:257-261`).

Therefore a normalizer called only by `resolve()` is unreachable from every
on-disk and in-memory manifest validation path.

`build_tools.compiler.version` is a second, independent record:

* `manifest._VERSION` is its own search expression
  (`sol/release/release_rail/manifest.py:19-20`).
  `_compiler_from_cache()` derives only which command to invoke from
  `CMAKE_CXX_COMPILER`, with an authority fallback; it never derives a version
  and never calls `apple.py` (`sol/release/release_rail/manifest.py:23-35`).
* `capture_build_tools()` places that command in the generic seven-tool loop
  (`sol/release/release_rail/manifest.py:104-127`).
  `normalize_tool_output()` independently searches the command's first
  nonempty output line and returns its canonical name and matched version
  (`sol/release/release_rail/manifest.py:38-78`).
* Apple evidence is a separate eighth `apple_toolchain` key, added only after
  all seven generic records and validated independently
  (`sol/release/release_rail/manifest.py:128-160`). Structural validation
  likewise validates every generic `name`/`version` record and then separately
  calls `apple.validate_evidence()` on the Apple key; it performs no comparison
  between the two records (`sol/release/release_rail/manifest.py:163-190`).

The shared test fixture happens to assign version `1.2.3` to both the generic
compiler and Apple evidence, but it constructs them as distinct dictionaries
and keys (`sol/release/tests/support.py:15-18,21-49`). No generic compiler
version derivation consults `apple.py`.

## Q4 — Resolve-only compiler-path precheck

### Real `subprocess.run` measurement

The measurement ran as UID `1001` (`id -u`), not root. A throwaway script in
`/home/extro/.local/share/hopper/lodes/7qkl5xk2/scratchpad` created a missing
path, a mode-`000` unreadable file, and a mode-`0644` non-executable file, then
passed each exact path to real `subprocess.run([path, "--version"], ...)`.
Its actual output was:

```text
missing: FileNotFoundError: [Errno 2] No such file or directory: '/tmp/tmpejle30pd/missing-clang++'; path='/tmp/tmpejle30pd/missing-clang++'; mode=absent
unreadable: PermissionError: [Errno 13] Permission denied: '/tmp/tmpejle30pd/unreadable-clang++'; path='/tmp/tmpejle30pd/unreadable-clang++'; mode=0o0
non-executable: PermissionError: [Errno 13] Permission denied: '/tmp/tmpejle30pd/non-executable-clang++'; path='/tmp/tmpejle30pd/non-executable-clang++'; mode=0o644
```

This lode could not directly measure a UID-0 process. Root can bypass ordinary
read-permission checks, but the non-executable fixture has no execute bit at
all; root does not turn a mode-`0644` regular file into an executable, so the
non-executable `execve` result remains permission denied. That root statement
is not an additional local UID-0 observation.

### Existing closure

`FileNotFoundError` and `PermissionError` are both `OSError` subclasses, so all
three measured outcomes enter `_command()`'s existing exception branch. Its
diagnostic explicitly interpolates `arguments[0]`:

```python
f"Apple toolchain evidence failed: cannot invoke {arguments[0]}: {error}; "
```

(`sol/release/release_rail/apple.py:35-49`).

For `resolve()`, `arguments[0]` is exactly the configured path:
`_cache()` preserves the `CMAKE_CXX_COMPILER` value
(`sol/release/release_rail/apple.py:152-184`), `resolve()` passes that value to
`_observed()` (`sol/release/release_rail/apple.py:218-224`), and `_observed()`
uses it as the compiler command before attempting Xcode or SDK discovery
(`sol/release/release_rail/apple.py:113-121`). The default runner for
`resolve()` is real `subprocess.run`
(`sol/release/release_rail/apple.py:218-222`).

A new resolve-only precheck is therefore not needed. The existing invocation
and `OSError` normalization already fail closed for missing, unreadable, and
non-executable configured compiler paths and name the configured path. A
real-subprocess resolve fixture can prove those three cases without changing
production behavior; a mocked runner would not prove the OS exception
boundary.

Any generic precheck in `_command()` or `_observed()` would also be incorrect
for preflight: `preflight()` deliberately passes the PATH-relative
`target["required_tools"][0]` (`sol/release/release_rail/apple.py:146-149`),
which is `"clang++"` for the Darwin authority record
(`sol/release/targets.toml:66-89`). If a precheck were nevertheless introduced,
that constraint makes it resolve-only, but the measured default-runner path
provides the required closure without one.

## Relevant touch points and patterns to preserve

* `sol/release/release_rail/apple.py:35-143` owns command normalization and live
  public observations; `apple.py:146-261` owns preflight/CMake resolution; and
  `apple.py:264-335` owns closed manifest-safe validation.
* `sol/release/release_rail/driver.py:528-567,570-650` is the sole production
  owner of the preflight and resolve entry points and establishes their order
  relative to build and manifest creation.
* `sol/release/release_rail/manifest.py:19-35,38-190,193-254` owns the separate
  generic compiler record, Apple-evidence admission, and in-memory manifest
  validation. `sol/release/release_rail/set_validator.py:65-93,179-249` owns
  on-disk reachability.
* `sol/release/tests/test_apple.py:16-200` is the direct unit seam. It uses an
  injected runner and synthetic CMake cache/metadata, while
  `sol/release/tests/support.py:21-49` provides shared manifest evidence.
  `sol/release/tests/test_driver.py:681-704,955-1126` covers ordering,
  propagation, transaction isolation, and the one outside diagnostic string.
* Existing code consistently fails closed with one domain exception and
  recovery text, preserves the configured command/path in diagnostics, uses
  injectable runners for narrow unit tests, requires exact ordered evidence
  keys, validates normalized scalar values with full matches, rejects duplicate
  or ambiguous CMake records, and keeps live host discovery out of manifest
  validation. AppleClang normalization must retain those boundaries.
