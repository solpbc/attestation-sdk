# nvattest CI container ownership design

**Authority.** This record is the implementation authority for the
`ci-container` ownership correction and its prerequisite Docker 29 selector
unblock. It accepts `sol/notes/ci-container-ownership-prep.md`, the live
rootful-Docker reproduction, the session proxy's non-involvement in uid
mapping, and the Docker 29 tabwriter diagnosis as settled inputs.

The implementation is deliberately split into two commits. The first restores
runtime selection on Docker 29 without changing any runtime evidence. The
second changes only the CI container invocation and the shared image layout.
No release-driver container argv is changed.

## Change surface

The first commit changes:

* `sol/release/release_rail/runtime.py`;
* `sol/release/tests/test_runtime.py`.

The second commit changes:

* `sol/release/release_rail/runtime.py`;
* `sol/release/rail.py`;
* `Makefile`;
* `sol/ci/Containerfile`;
* `sol/release/tests/test_runtime.py`;
* new `sol/release/tests/test_ci_container.py`;
* `sol/notes/runtime-provenance-design.md`.

The prep and this design note are the documentation records. There is no
change to `driver.py`, `.gitignore`, `sol/release/targets.toml`,
`release_rail/authority.py`, manifest or authority schemas, release versions,
or generated certificate modes.

## Part A — commit 1: Docker 29 selector unblock

### A1 — One non-tab probe separator

Add exported module constant `FIELD_SEPARATOR = "|"` beside the runtime
identity constants in `runtime.py`. Construct every multi-field
`--format` body from that constant:

* `PODMAN_VERSION_FIELDS`;
* `PODMAN_INFO`;
* `DOCKER_VERSION`;
* `DOCKER_INFO`.

Although the direction names the first three, `DOCKER_INFO` must change too.
Leaving its currently functional tab delimiter would contradict both settled
invariants: there is one delimiter/one truth source, and the rail never uses a
tab as a probe field separator. Docker 29 currently preserves tabs for
`docker info`, but that implementation detail is not retained as a future
trap.

Change `_fields()` to split on `FIELD_SEPARATOR`. Its count and nonempty-field
checks remain unchanged. A `|` unexpectedly present inside an engine-provided
field creates too many fields and fails closed as malformed evidence.

The rationale is durability: Docker's `version` formatter sends literal tabs
through a tabwriter and turns them into aligned spaces. A rail-wide “never use
tab for structured probe output” rule is simpler than a command-specific
exception and protects future Docker format probes automatically.

### A2 — Durable invariant test

Add
`RuntimeTest.test_format_strings_never_contain_tabs_and_use_field_separator`
in `test_runtime.py`. It inspects the format argument following `--format` in
all four exported probe tuples, asserts `FIELD_SEPARATOR` is `"|"`, asserts
the format contains no tab character, and asserts the expected number of
separator occurrences for each command's field count.

No mangled-space fixture is added. Once the producer format contains no tab,
tabwriter expansion is structurally impossible; a fixture containing the old
mangled output would only retest `_fields()`'s existing malformed-count
behavior.

### A3 — Fixtures

Update `RuntimeTest.outputs()` so the synthetic stdout for
`PODMAN_VERSION_FIELDS`, `PODMAN_INFO`, `DOCKER_VERSION`, and `DOCKER_INFO` is
built by joining field values with `runtime.FIELD_SEPARATOR`. The plain
human-readable `PODMAN_VERSION` fixture is unchanged.

This follows the existing convention in
`test_mount_rendering_and_validation`: tests use exported production
constants for shared syntax instead of copying separator literals.

### A4 — Contract limits

This commit changes only the private wire representation returned by four
runtime `--format` probes. It does not change:

* `Selection` or normalized evidence dictionaries;
* `validate_evidence()` field names, ordering, or validation;
* `container_runtime` or any manifest key;
* `targets.toml` or a recorded image/runtime value;
* `driver.py` or any container invocation.

## Part B — commit 2: CI ownership

### B1 — Rail verb and output contract

Add verb `runtime run-args` with one unrestricted positional runtime-name
argument. The supported shape is `rail.py runtime run-args docker`; argparse
must not use `choices`, because unknown names need the rail's normal
`RuntimeSelectionError` diagnostic path rather than argparse's separate error
surface.

The verb emits each argv token on its own line. Docker emits six tokens in
this exact order:

1. `--user`;
2. `<uid>:<gid>`;
3. `-e`;
4. `HOME=/src/build/.ci-home`;
5. `-e`;
6. `CARGO_HOME=/src/build/.ci-home/.cargo`.

Podman emits zero tokens and no newline. Every emitted token is
whitespace-free. This is a required API property because Make expands the
captured value unquoted for intentional shell word splitting; the verb does
not emit quoting syntax and the Makefile does not use `eval`.

An unknown runtime raises `RuntimeSelectionError` with a diagnostic containing
the rejected value and the complete supported set `podman, docker`. It never
returns an empty tuple for an unknown value; empty is a valid result only for
known Podman.

### B2 — Mapping owner and exact function boundary

Put exported path constants `CI_HOME` and `CI_CARGO_HOME`, plus function
`run_args()`, in `release_rail/runtime.py` next to `render_mount()`. The exact
function boundary is `run_args(runtime_name, *, getuid=None, getgid=None) ->
tuple[str, ...]`, with the optional providers typed as zero-argument
integer-returning callables.

`runtime.py` already owns `PODMAN`, `DOCKER`, `RUNTIME_NAMES`, uid-mapping
selection errors, and container argument rendering. Keeping the mapping there
allows `rail.py` to remain a thin printing facade and gives unit tests a
side-effect-free function.

`run_args()` returns immediately for Podman without resolving or consulting
uid or gid. For Docker it resolves an omitted provider to `os.getuid` or
`os.getgid`, calls each once, and renders their decimal results. Resolving
defaults inside the function, rather than binding them in the signature,
lets a no-host-identity test patch the module functions reliably. Function
tests always pass fixed providers; they never observe the test host's
identity. No new numeric validation layer is added around
`os.getuid()`/`os.getgid()`.

### B3 — Makefile consumption and failure propagation

In `ci-container`, immediately after resolving `RUNTIME` and `IMAGE`, assign
the output of `$(RAIL) runtime run-args "$$RUNTIME"` to recipe-local
`RUN_ARGS` in the existing `&&` chain. Insert unquoted `$$RUN_ARGS` between
`run --rm` and the existing volume arguments.

This preserves the status property recorded at
`runtime-provenance-design.md:194-199`: a command substitution's nonzero
status becomes the shell assignment's status, so an invalid runtime aborts
the `&&` chain before the container command. The recipe cannot silently
continue with empty arguments after a failed verb. A successful Podman
substitution is genuinely empty, so its runtime argument vector remains
byte-for-byte the current one.

The recipe continues to call `runtime select` exactly once and passes that
selected name into `run-args`; `run-args` never calls `select()` or probes
runtime availability again.

### B4 — Writable HOME and recipe order

Use `/src/build/.ci-home`, corresponding to ignored host path
`build/.ci-home` (`.gitignore:8`). After `rm -rf build`, insert
`mkdir -p build/.ci-home`, then run the existing first CMake command. The
required order is therefore cleanup, HOME creation, configure, build, test.

This path is self-cleaning: the recipe's next cold cleanup and `make clean`
both remove it. The accepted cost is that Cargo refetches registry/cache data
on each `make ci`; the recipe already discards the entire build tree, so it
already defines a cold build.

The rejected `/src/.cache/...` alternative would preserve Cargo downloads,
but neither the recipe nor `make clean` removes it. That would create
unbounded, non-obvious residue in the operator's worktree, a milder form of
the complaint this change closes.

The Docker vector explicitly carries both `HOME` and `CARGO_HOME`; neither is
left to the manylinux entrypoint or an absent passwd record. The Podman vector
carries neither variable and remains unchanged.

### B5 — Containerfile instruction sequence

Keep the base image and package-install instructions unchanged, including all
current `-devel` packages. Replace only the Rust installation/environment
sequence, in this order:

1. Declare `ENV RUSTUP_HOME="/usr/local/rustup"` before the rustup install
   instruction.
2. In the one logical rustup `RUN`, export
   `CARGO_HOME="/usr/local/cargo"` before the existing curl-to-shell install
   pipeline. After the installer succeeds, in the same shell, apply
   `chmod -R a+rX` to both `$CARGO_HOME` and `$RUSTUP_HOME`.
3. Declare `ENV PATH="/usr/local/cargo/bin:${PATH}"` after the install.

The `export` precedes the pipeline so both the curl process and, critically,
the installer shell inherit `CARGO_HOME`. A prefix assignment applied only to
the left side of the pipeline is forbidden because the rustup installer would
not receive it.

`RUSTUP_HOME` is a persistent `ENV` because every consumer invokes rustup
proxies from the Cargo bin directory, and those proxies resolve the real
toolchain through `$RUSTUP_HOME/toolchains/...`. Placing the ENV before the
install RUN provides one literal source and proves the installer itself
received the same value later consumers receive.

`CARGO_HOME` is deliberately not an `ENV`. It controls the installation
location only within the image-build RUN. The release `_build` path remains
free to use root's default writable Cargo state, while Docker `ci-container`
redirects Cargo writes into its bind-mounted HOME explicitly.

`a+rX` grants read access to files and traversal to directories while
preserving non-executable data as non-executable. `a+rx` is rejected because
it would mark every registry and toolchain data file executable.

### B6 — Rail facade

Add a `run-args` action and positional runtime-name argument under the
existing runtime parser in `rail.py`. In `main()`, handle `select`,
`image-tag`, and `run-args` as explicit branches rather than retaining the
current catch-all `else` for the image tag. The new branch iterates
`runtime.run_args()` and prints one token per call; iterating an empty Podman
tuple prints nothing.

`RuntimeSelectionError` already reaches the common stderr prefix and exit
status 2, so no new exception handling is introduced.

### B7 — Tests and acceptance mapping

No existing test reads either `Makefile` or `sol/ci/Containerfile`. Add the
focused `test_ci_container.py` with helpers that:

* extract only the `ci-container` and `clean` recipes from the Makefile;
* join backslash-continued Containerfile lines into logical instructions;
* track preceding `ENV` assignments and ordered inline `RUN` exports up to
  the rustup installer, rather than searching the whole file for convenient
  literals.

The tests are:

* `test_run_args_are_distinct_for_docker_and_podman`
  (`test_runtime.py`) spells out Docker's six-token expected tuple with fixed
  injected uid/gid and separately asserts Podman's result is `()`. Exported
  `CI_HOME`/`CI_CARGO_HOME` may supply path values, but there is no shared
  expected-vector fixture: identical fixtures would pass even if the runtime
  branch were not wired.
* `test_podman_run_args_contain_no_user_or_home_environment`
  (`test_runtime.py`) explicitly rejects `--user` and any token containing
  `HOME=` or `CARGO_HOME=`.
* `test_run_args_reject_unknown_runtime`
  (`test_runtime.py`) exercises the Python function and asserts the rejected
  value and both exported supported runtime names.
* `test_run_args_cli_rejects_unknown_runtime`
  (`test_runtime.py`) follows the real-subprocess pattern from
  `test_authority.py:169-187`, invoking `rail.py runtime run-args nerdctl`
  and asserting exit 2, empty stdout, and the normal stderr diagnostic naming
  `nerdctl`, Podman, and Docker.
* `test_run_args_do_not_select_or_spawn_for_either_runtime`
  (`test_runtime.py`) patches both `runtime.select` and
  `runtime.subprocess.run` to raise, then calls `run_args()` for Docker with
  injected uid/gid and for Podman with forbidden uid/gid providers. Both
  succeed, proving neither branch selects or spawns and Podman's empty branch
  does not read host identity.
* `test_run_args_use_injected_uid_and_gid`
  (`test_runtime.py`) supplies distinctive fixed providers and asserts those
  exact values in Docker's user token. This is the host-portability guard.
* `test_run_arg_tokens_are_whitespace_free`
  (`test_runtime.py`) checks both per-runtime results token by token.
* `test_ci_container_consumes_run_args_with_status_guard`
  (`test_ci_container.py`) asserts the assignment calls `runtime run-args`
  with `$$RUNTIME`, is an element of the `&&` chain, precedes the runtime
  invocation, and expands `$$RUN_ARGS` unquoted in that invocation.
* `test_ci_home_is_ignored_and_created_between_cleanup_and_configure`
  (`test_ci_container.py`) ties `runtime.CI_HOME` to the relative Makefile
  path, asks Git's ignore machinery to classify it, asserts `rm -rf build`
  precedes `mkdir -p build/.ci-home`, asserts the mkdir precedes CMake, and
  confirms the `clean` recipe removes root `build`.
* `test_rustup_install_uses_non_root_readable_homes`
  (`test_ci_container.py`) locates the unique rustup install RUN, computes the
  ENV-plus-prior-export environment in effect at the installer, asserts both
  effective homes are absolute and outside `/root`, and asserts a later
  `chmod -R a+rX` in that instruction names both homes. It does not accept the
  PATH line as proof.
* `test_containerfile_limits_persistent_home_environment`
  (`test_ci_container.py`) asserts the Containerfile has persistent
  `RUSTUP_HOME`, has no `ENV HOME` or `ENV CARGO_HOME`, and prepends the new
  Cargo bin directory to PATH only after the install.

Acceptance coverage is:

| Acceptance criterion | Automated guard and remaining observation |
| --- | --- |
| AC1, AC3 | `test_run_args_are_distinct_for_docker_and_podman`; distinct literal vectors prevent a vacuous branch test. |
| AC2 | Both unknown-runtime tests cover function and CLI error contracts. |
| AC4 | `test_podman_run_args_contain_no_user_or_home_environment`. |
| AC5 | `test_run_args_do_not_select_or_spawn_for_either_runtime` plus `test_ci_container_consumes_run_args_with_status_guard`. |
| AC6 | Both Containerfile tests model the install environment, PATH, and traversal chmod. |
| AC7 | The runtime vector test, Makefile consumption/order test, and persistent-environment test jointly prove both Docker variables are invocation-only and Podman receives neither. |
| AC8 | The injected-uid vector and Makefile wiring are unit guards; only the required live Docker `make ci` can prove zero root-owned files and a build population above 20,000. No fixture is represented as a substitute for that observation. |
| AC9 | The ignored-path/order test guards the mechanism; the post-build clean Git status remains a required live observation. |
| AC10 | The Containerfile install-environment test and existing `DriverRuntimeTest.test_tool_invoker_uses_selected_runtime_mount_platform_and_bare_tag` guard the static contract; live uid-0 `rustc --version` and `cargo --version` against read-only `/src` remain required image observations. |
| AC11 | Existing `BaselineStabilityTest.test_targets_authority_is_byte_identical` guards `targets.toml`; its byte comparison and the whole rail suite remain required. |
| AC12 | `test_run_args_use_injected_uid_and_gid` and the no-select test never read the host uid. The full rail suite on the implementation host and existing non-x86_64 post-ship coverage remain required. |

### B8 — Documentation

At `runtime-provenance-design.md:186-187`, append a third verb to the existing
enumeration: `runtime run-args <runtime>` emits zero or more
whitespace-free argv tokens, one per line, for the already-selected runtime.
State there that known Podman emits nothing and unknown names fail through the
normal rail error path. The shipped verb name and prose must match exactly.

The existing status-propagation discussion at lines 194-199 remains accurate;
the new Makefile assignment follows that same pattern.

### B9 — Accepted duplication

The four inline release container-argument sites in `driver.py:262-287`,
`:333-353`, `:433-453`, and `:480-494` are deliberately not unified with
`runtime run-args`. The release path has different mount/write contracts and
is guarded by `_ownership_probe`; it has no ownership defect to repair here.

The new verb is therefore a second authority for runtime-to-invocation
mapping, scoped to `ci-container`, not a refactor of release orchestration.
This duplication is accepted so a future cleanup does not apply Docker's CI
user mapping to Podman or to release invocations whose safety is established
empirically.

## Implementation order

1. Land commit 1's separator constant, all four producer formats,
   `_fields()` consumer, fixture updates, and invariant test together. This
   restores `runtime select`, which is prerequisite to image and CI
   acceptance.
2. In commit 2, add the pure runtime argument function/constants and its
   function-level tests first.
3. Expose the rail verb and add its CLI/no-reselection tests.
4. Change the Containerfile Rust homes and add the logical-instruction
   contract tests.
5. Wire the Makefile argument substitution and ordered HOME creation, then
   add its recipe/ignore tests.
6. Update the runtime-provenance design enumeration in the same second
   commit.
7. Only after implementation, perform the narrow rail tests, image probes,
   required live Docker CI ownership/population/status measurements, and the
   separately owned Podman post-ship verification.

## Risks and out-of-scope follow-ups

* The Makefile intentionally depends on shell word splitting. The one-token
  output format, whitespace-free invariant, fixed numeric/path values, and
  lack of `eval` bound that risk.
* `/src/build/.ci-home` does not exist when the container starts. The explicit
  mkdir after cleanup and before CMake is load-bearing; moving it before
  cleanup silently deletes it.
* The Rust install uses a pipeline. `CARGO_HOME` must be exported in the
  logical RUN before that pipeline, not scoped only to its left-hand command.
* The image makes Rust toolchain content world-readable. It contains tools
  and registry metadata, not credentials; `a+rX` avoids broad executable-bit
  changes.
* Podman must continue to receive an empty vector. Its live verification is
  owned by the Podman host because this lode has Docker only.
* Removal of the existing `-devel` packages is a separate follow-up.
* Consolidating Makefile's inline `:Z`/`:ro,Z` suffixes with
  `runtime.py:22-23` is a separate follow-up.
* A Docker-side remedy for `_ownership_probe` is a separate follow-up; this
  design does not make rootful-Docker release execution valid.
* No `--platform` is added to `ci-container`, and the runtime-agnostic
  `Makefile:31-35` image recipe remains untouched.
* No shell helper, wrapper, shim, sudo/package-install step, recursive chown,
  certificate-mode change, or bare-metal build work is introduced.
