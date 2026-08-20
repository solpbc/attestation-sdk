# nvattest vendored curl-config CA-configure design

**Authority.** This record is the implementation authority for a release-rail
assertion that the vendored curl was *configured* without a baked host CA
path, by reading `curl-config` out of the vendored curl build tree. It accepts
`sol/notes/curl-ca-configure-prep.md` as ground truth and does not re-derive
prep Q1–Q5.

The assertion is a release-rail check. It does not change how curl is
configured, does not scan binaries, and does not run during `make ci`.
`make ci` stays green on a clean checkout because `ci-container` never
enters `driver.builder()`, and `rail-test` exercises the new module against
constructed fixture trees only.

**Citation basis.** Repository line citations refer to integration tip
`d2675f8` (`sol: consume the installed libdir in the release link-closure
tests`).

## Change surface

One implementation commit changes:

* new `sol/release/release_rail/curl.py`;
* `sol/release/release_rail/driver.py`;
* `sol/release/rail.py`;
* new `sol/release/tests/test_curl.py`;
* `sol/release/tests/test_driver.py`;
* `sol/release/README.md`.

The prep note and this design note are the documentation records. There is
no change to `Makefile`, `nv-attestation-sdk-cpp/`, `nv-attestation-cli/`,
`gate.py`, `fixtures.py`, `targets.toml`, `authority.py`, Containerfile,
or any CMake ExternalProject.

The change surface stays inside `sol/release/` and `sol/notes/`. It does
not extend to the root `Makefile`.

## Part 1 — Run location

Call the assertion from `sol/release/release_rail/driver.py` `builder()`,
immediately after `checkpoint("after-build")` at line 586, using the
already-bound `build_dir = root / "build/release"` from line 584:

1. `_build(...)` at line 585;
2. `checkpoint("after-build")` at line 586;
3. `curl.check(build_dir)` (new);
4. `_stage(...)` at line 587.

That is the available answer: `build_dir` is the tree `_build` just
produced for every authority target (Linux container and Darwin native),
the call is entirely inside `sol/release/`, and `make ci` / `ci-container`
(`Makefile:45-56`, `-B build`) never reach it.

`curl.check` must invoke `curl-config` through its own `subprocess.run`
(`check=False`, `text=True`, `stdout`/`stderr=PIPE`), the same way
`apple._command` does. It must not go through `driver._run`. `_run` uses
`check=True` and collapses `OSError` with `CalledProcessError` into
`ReleaseError`, which cannot produce the four distinct messages in Part 4.

No new `rail.py` subcommand. The run location is inside `release`, which
already exists.

### Existing tests that execute this line

Prep named two tests that run the real `builder()` past a successful
`_build` fake. Neither currently plants `build/release/curl-install`.
A live `curl.check(build_dir)` with no escape hatch would raise Part 4
message 1 (unbuilt tree) and fail both tests. Pass-by-absence, env vars,
and feature flags are forbidden.

**`test_release_threads_one_selection_through_every_container_command`**
(`test_driver.py:337-475`). Temp `root` has no build tree. `_build` is
not patched; it calls `_run`, which is mocked to record the container
argv and return success without creating files. `_stage` is patched.
After line 586 the new call reads `root/build/release/curl-install` for
real (the new module's `subprocess.run` is *not* `driver._run` and is
*not* `driver.subprocess.run`, which this test patches only for
`_tool_invoker`).

Reaction without accommodation: `CurlConfigError` on the missing
`curl-install/` directory; the test never reaches its container-argv
assertions.

Minimal honest accommodation: extend this test's existing `_run` fake so
that when it stands in for the container build (the `bash -ec` body that
contains `cmake --build build/release`, `cwd=root`) it writes a green
`curl-config` tree at `cwd/build/release/curl-install/bin/curl-config`.
A successful `_build` in production always leaves that install prefix
(`prep` §1). The fake must stay coherent with that fact. Do not patch
`curl.check` out.

The planted script is a minimal green stub: empty `--ca`, and a
`--configure` line whose tokens include `REQUIRED_CONFIGURE_FLAGS`. It
is built from that one production constant so this test does not grow a
second copy of the three flag names. It does not need the verbatim live
`--configure` line; that line lives only in `test_curl.py` (Part 6).
Container-command counting (`len(container_commands) == 12`) is
unchanged: planting files does not add argv.

**`test_macos_resolve_inconsistency_never_publishes`**
(`test_driver.py:1018-1071`). `_build` is patched to a bare `MagicMock`
that succeeds and creates nothing. `builder()` then continues through
`_stage` (also patched) to `apple.resolve`. The test expects
`AppleToolchainError`.

Reaction without accommodation: `CurlConfigError` at line 586, so
`apple.resolve` is never called and
`assert_release_failure_preserves_quartet` fails.

Minimal honest accommodation: give the `_build` fake a `side_effect`
that plants the same kind of green tree at its `build_dir` argument
(the third positional, production `root / "build/release"`) and returns.
`_acquire_ca` / `_stage` / `_gate_binaries` stay patched. `apple.resolve`
still raises, and the quartet-preservation assertion is unchanged.

No other current `test_driver.py` path reaches line 586 with a successful
`_build`: `test_macos_build_failures_use_driver_build_seam_and_never_publish`
fails inside `_build`, and preflight-failure tests never start the
transaction.

## Part 2 — Module and error naming

New module `sol/release/release_rail/curl.py`, matching the lowercase
single-noun house (`gate`, `apple`, `elf`). Tests live at
`sol/release/tests/test_curl.py`.

Exported names:

* `REQUIRED_CONFIGURE_FLAGS` — the one three-flag constant (Part 5);
* `class CurlConfigError(RuntimeError)` — house `<Thing>Error`, named
  for the evidence source rather than the generic module noun, the same
  way `apple.py` exports `AppleToolchainError`;
* `check(build_dir: Path, runner: Runner = subprocess.run) -> None`.

`Runner` is the same `Callable[..., subprocess.CompletedProcess]` alias
`apple.py` uses. Production `builder()` calls `curl.check(build_dir)`
with the default runner. `test_curl.py` uses the default runner against
real stub scripts; it does not mock `subprocess`.

`rail.py` `main()`'s exception tuple (`rail.py:126-139`) must include
`curl.CurlConfigError`. An omitted type becomes an uncaught traceback
instead of `release rail error: ...` / exit 2 (`prep` §5). Insert it
alphabetically by module name in the current tuple: after
`archive.ArchiveError` and before `driver.ReleaseError`
(`archive` < `curl` < `driver`).

Add `from release_rail import curl` in `rail.py` immediately after the
`archive` import. Add `curl` to `driver.py:16`'s import list in
alphabetical order: `apple, archive, authority, curl, gate, ...`.

Extend `test_driver.py:259-277`
(`test_archive_and_manifest_errors_use_normal_cli_error_form`) with
`curl.CurlConfigError("curl-config broke")` so the new type is covered
by the existing CLI-form assertion. That is facade wiring, not a tenth
curl-config case.

No new `rail.py` subcommand.

## Part 3 — Parsing of `--configure`

Token-exact membership via `shlex.split`, not substring search.

curl-config's `--configure` writer prints one line of single-quoted argv
tokens with a leading space (`prep` §2). `shlex.split` recovers those
tokens. Required-flag checks are then `flag in tokens`.

Substring search on the raw line makes the per-flag negative controls
meaningless: the three flags share `--with-ca-` / `--without-ca-` /
`ca-bundle` / `ca-path` stems, and a loose `in` check can treat
`--with-ca-path=/x` (or a neighbor token) as satisfying a needle it is
not. Token membership of `--without-ca-path` is not satisfied by
`--with-ca-path=/x`.

Exact shape:

* `check(build_dir, runner=subprocess.run) -> None` is the only public
  entry. It performs the filesystem checks (Part 4), invokes
  `--ca` then `--configure`, then parses configure output.
* `_configure_tokens(output: str) -> tuple[str, ...]` is the private
  parse: `return tuple(shlex.split(output))`. No other parser is used.

`--ca` success is stripped stdout equal to `""` (live stdout is `'\n'`).
Any nonempty stripped `--ca` value is a baked CA path (Part 5).

## Part 4 — Four distinct absence/failure messages

`os.access` cannot tell states a/b/c apart, and `subprocess.run` raises
`FileNotFoundError` for both a and b (`prep` §3). `check()` therefore
inspects the filesystem *before* spawn, in this order. `{install}` is
`build_dir / "curl-install"`. `{script}` is
`build_dir / "curl-install" / "bin" / "curl-config"`.

Do not use `driver._run`. After the three filesystem checks, invoke with
`runner(..., check=False, text=True, stdout=PIPE, stderr=PIPE)`. Prep
measured that a non-executable script raises `PermissionError`, not exit
126; the executability check exists so message 3 is produced without
relying on that exception type. Nonzero status is a `CompletedProcess`,
not `CalledProcessError`.

Verbatim messages (only `{install}`, `{script}`, `{flag}`, `{returncode}`,
and `{stderr}` are interpolated; `{flag}` is `--ca` or `--configure`):

1. Unbuilt tree (`{install}` is missing or not a directory):

```text
vendored curl configure evidence failed: {install} is not a directory; remove build/release and rerun the release so the vendored curl ExternalProject installs curl-config, then retry
```

2. Missing binary (`{install}` is a directory, `{script}` is not a
   regular file):

```text
vendored curl configure evidence failed: {script} is absent; remove build/release and rerun the release so the vendored curl ExternalProject installs curl-config, then retry
```

3. Non-executable (`{script}` is a regular file and
   `os.access({script}, os.X_OK)` is false):

```text
vendored curl configure evidence failed: {script} is not executable; remove build/release and rerun the release so the installed curl-config is the ExternalProject install output, then retry
```

4. Non-zero exit (spawn succeeded, `returncode != 0`). `{stderr}` is
   `stderr.strip()`, or empty:

```text
vendored curl configure evidence failed: {script} {flag} failed: exit {returncode}: {stderr}; remove build/release and rerun the release, then retry
```

When stripped stderr is empty, the `: {stderr}` segment is omitted so
the text does not end in a hanging colon:

```text
vendored curl configure evidence failed: {script} {flag} failed: exit {returncode}; remove build/release and rerun the release, then retry
```

Fail-closed leftover: if spawn still raises `OSError` after message 3's
check (missing `/bin/sh`, `noexec` mount), raise `CurlConfigError` with
the apple-style cannot-invoke form, same recovery:

```text
vendored curl configure evidence failed: cannot invoke {script}: {error}; remove build/release and rerun the release, then retry
```

That leftover is not one of the four AC states; it is the closed
fallback so an unexpected spawn failure cannot pass.

## Part 5 — Four configure-evidence messages and the one flag constant

The three required configure flags live in exactly one module-level
constant in `curl.py`:

```text
REQUIRED_CONFIGURE_FLAGS = (
    "--with-ca-fallback",
    "--without-ca-bundle",
    "--without-ca-path",
)
```

`check()` iterates that tuple. `test_curl.py` and `test_driver.py` import
it. README names “the three flags” and does not restate the literals.
No test, comment, or doc carries a parallel list of the three names.

Verbatim evidence messages ( `{script}`, `{flag}`, and `{value}`
interpolated; `{flag}` is one member of `REQUIRED_CONFIGURE_FLAGS`;
`{value}` is `repr(stripped --ca stdout)`):

5. `--ca` nonempty:

```text
vendored curl configure evidence failed: {script} --ca reported a baked CA path {value}; configure the vendored curl without a baked host CA path, remove build/release, and retry
```

6. missing `--with-ca-fallback`:

```text
vendored curl configure evidence failed: {script} --configure is missing --with-ca-fallback; configure the vendored curl with --with-ca-fallback, remove build/release, and retry
```

7. missing `--without-ca-bundle`:

```text
vendored curl configure evidence failed: {script} --configure is missing --without-ca-bundle; configure the vendored curl with --without-ca-bundle, remove build/release, and retry
```

8. missing `--without-ca-path`:

```text
vendored curl configure evidence failed: {script} --configure is missing --without-ca-path; configure the vendored curl with --without-ca-path, remove build/release, and retry
```

Messages 6–8 are one format string filled from `REQUIRED_CONFIGURE_FLAGS`,
not three independently maintained literals. First missing flag in
constant order wins. Empty `--configure` output fails on
`--with-ca-fallback`.

## Part 6 — Tests

`fixtures.py` stays ELF/Mach-O bytes. It is not a home for a POSIX
`curl-config` stub. The stub builder is local to `test_curl.py`,
following `test_apple_cmake.py:201-205`: write `#!/bin/sh\n{body}\n`,
then `chmod 0o755`.

Helper, local to that file: given a `tempfile.TemporaryDirectory` root
treated as `build_dir`, create `curl-install/bin/curl-config` with a
supplied `--ca` stdout and `--configure` stdout. Absence/failure cases
deliberately skip pieces of that helper (no `curl-install/` dir; dir
without the script; script with execute bits cleared; script that
`exit 7` with stderr).

Green `--configure` stdout is the live line from prep §2, including the
leading space and single-quoting, without inventing tokens:

```text
 '--prefix=/src/build/curl-install' '--with-openssl=/src/build/openssl-install' '--without-libssh2' '--without-nghttp2' '--without-brotli' '--without-zstd' '--without-libidn2' '--without-librtmp' '--without-libpsl' '--with-ca-fallback' '--without-ca-bundle' '--without-ca-path' '--disable-ldap' '--disable-shared' '--enable-static' 'CC=/opt/rh/gcc-toolset-14/root/usr/bin/cc' 'CFLAGS= -fPIC' 'PKG_CONFIG_PATH=/src/build/openssl-install/lib/pkgconfig'
```

Green `--ca` stdout is empty (the stub `echo` with no arguments, matching
the live script). Tests call `curl.check(build_dir)` with the real
runner.

Nine cases, all fail-closed, no `skip`/`skipIf`:

1. **Green.** Full tree, live `--configure` line, empty `--ca`.
   `check()` returns `None`.
2. **Unbuilt tree.** No `curl-install/` directory. Message 1, path is
   the missing install dir.
3. **Missing binary.** `curl-install/` exists, `bin/curl-config` does
   not. Message 2.
4. **Non-executable.** Green script then `chmod -x`. Message 3.
   `os.access(X_OK)` is false; spawn is not reached.
5. **Non-zero exit.** Executable stub prints `curl-config boom` on
   stderr and `exit 7` for `--ca` (or any first invocation). Message 4
   with returncode `7` and stderr `curl-config boom`.
6. **`--ca` baked.** Empty-flag `--configure` line plus `--ca` stdout
   `baked.pem` (not a `gate.FORBIDDEN_CA_PATHS` literal). Message 5.
7. **`--with-ca-fallback` removed.** Start from the green configure
   tokens, drop that one member of `REQUIRED_CONFIGURE_FLAGS`, re-emit.
   Message 6.
8. **`--without-ca-bundle` removed.** Same, and keep a sibling token
   `--with-ca-bundle=/x` so a substring match cannot be mistaken for
   success. Message 7.
9. **`--without-ca-path` removed.** Same, sibling token
   `--with-ca-path=/x`. Message 8.

Cases 7–9 iterate `REQUIRED_CONFIGURE_FLAGS`; they do not spell a second
list of flag names. Cases 8 and 9 are the proof that token-exact parsing
is what makes those negative controls real.

`test_driver.py` accommodations are Part 1, not additional curl-config
cases. Their planted stubs import `REQUIRED_CONFIGURE_FLAGS` and do not
copy the live `--configure` line.

## Part 7 — README caveat

Add one sentence to `sol/release/README.md` § "Verification
responsibility", subsection **Authored and checked on the lode**. That
subsection is the lode's claim-limit list (no native aarch64, no native
macOS, Docker not exercised). The new sentence is the same kind of limit.

Place it after the existing Docker sentence (`README.md:127-128`), still
inside that subsection, before `### Post-ship VPE native work`.

Draft:

```text
The vendored curl-config CA-configure assertion is unfalsified and must
not be cited as coverage until VPE has rebuilt the vendored curl with
the three flags removed and seen it go red.
```

It names “the three flags” and does not restate
`REQUIRED_CONFIGURE_FLAGS`. It does not go in “Post-ship VPE native
work”: that subsection is the native reconstruction checklist, not the
lode coverage claim.

## Non-goals

* Change surface is `sol/release/` plus `sol/notes/` only. Nothing under
  `nv-attestation-sdk-cpp/` or `nv-attestation-cli/`. No build
  configuration changes. No root `Makefile` edit.
* Do not touch `gate.FORBIDDEN_CA_PATHS`, `gate._forbidden_strings`, the
  two CA string literals, or `--openssldir`.
* No byte-scan of any kind: not `libcurl.a`, not `nvattest`, not
  `libnvat`, not the `curl-config` script body. The only inputs are the
  filesystem shape of `curl-install/` and the stdout of `curl-config
  --ca` / `curl-config --configure`.
* No `unittest.skip` / `skipIf`. Fail closed.
* Do not change any existing `GateError` message string.
* Do not skip the assertion when the tree is absent. Do not hide it
  behind a flag or environment variable.
* Do not invoke through `driver._run`.
* Do not add a `rail.py` subcommand.
* Do not put a `curl-config` stub builder in `fixtures.py`.
* Do not duplicate `REQUIRED_CONFIGURE_FLAGS` as a parallel literal list
  in tests or docs.

## Implementation order

1. `curl.py` with the constant, `CurlConfigError`, `check()`, the four
   absence messages, the four evidence messages, and `_configure_tokens`.
2. `rail.py` import plus exception-tuple insert; `driver.py` import plus
   the line-586 call.
3. `test_curl.py` with the local stub helper and the nine cases.
4. `test_driver.py`: plant green trees in the two `builder()`-success
   fakes; add `CurlConfigError` to the CLI-form tuple.
5. README caveat sentence.

## Risks

* The live `--configure` line was measured from a CI `-B build` tree on
  the primary checkout, not from `build/release` and not from Darwin.
  `check()` asserts flag tokens and empty `--ca`, not the prefix path, so
  that gap does not change the assertion. Darwin `curl-config` was not
  observed; CMakeLists already passes the same three flags on every
  target (`prep` §1).
* `test_release_threads_one_selection...` patches `driver.subprocess.run`
  for `_tool_invoker`. That patch must not be broadened to the new
  module's `subprocess.run`, or the planted stub would never execute.
* A future `builder()` test that fakes `_build` success without planting
  `curl-install/` will fail closed. That is the intended coherence
  rule, not a defect.

## Reality bridge

Copied `/home/jer/projects/attestation-sdk/build/curl-install` into
`/var/tmp/curl-ca-configure-reality-*` and ran this worktree's
`curl.check()` against the copy. The primary checkout was not modified
(`-rwxr-xr-x`, mtime unchanged). Scratch trees were removed after the
probes.

(a) Pristine copy. `check()` returned `None`.

(b) `bin/curl-config` removed. Message 2:

```text
vendored curl configure evidence failed: .../curl-install/bin/curl-config is absent; remove build/release and rerun the release so the vendored curl ExternalProject installs curl-config, then retry
```

(c) Restored script, `chmod -x`. Message 3:

```text
vendored curl configure evidence failed: .../curl-install/bin/curl-config is not executable; remove build/release and rerun the release so the installed curl-config is the ExternalProject install output, then retry
```

(d) Restored script, then replaced it with a stub that kept empty `--ca`
and the live `--configure` tokens minus one member of
`REQUIRED_CONFIGURE_FLAGS`. Messages 6/7/8:

```text
vendored curl configure evidence failed: .../curl-install/bin/curl-config --configure is missing --with-ca-fallback; configure the vendored curl with --with-ca-fallback, remove build/release, and retry
vendored curl configure evidence failed: .../curl-install/bin/curl-config --configure is missing --without-ca-bundle; configure the vendored curl with --without-ca-bundle, remove build/release, and retry
vendored curl configure evidence failed: .../curl-install/bin/curl-config --configure is missing --without-ca-path; configure the vendored curl with --without-ca-path, remove build/release, and retry
```

The live `--configure` line contained all three required tokens before
stripping. `make release` was not run.
