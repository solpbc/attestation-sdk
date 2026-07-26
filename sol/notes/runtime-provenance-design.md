# Native runtime and source-provenance design

**Authority:** this note is a separate work item from
`sol/notes/tri-target-design.md`. Its D1–D6 identifiers are local to this note.
The accepted facts in the runtime/provenance prep are inputs and are not
re-derived here.

The change has two fail-closed goals: select one usable native OCI runtime once
for a Linux release and record its normalized identity, and derive source
provenance from a pinned upstream commit rather than the operator's mutable
local `main`.

## D1 — One runtime authority and one selection

**Decision.** Add `sol/release/release_rail/runtime.py` as the only definition
of:

* the ordered runtime names `podman`, then `docker`;
* the bare local build tag `attestation-sdk-ci`;
* the manifest evidence key `container_runtime`;
* version, info, and Docker-endpoint probe argv;
* identity parsing and evidence validation;
* runtime selection and target-platform compatibility;
* bind-mount rendering.

`driver.py`, `manifest.py`, and `rail.py` import these definitions. The
Makefile asks `rail.py` for selection and the tag; D3 records why its distinct
CI-container contract retains runtime-invariant literal mount suffixes.
Historical command transcripts in `sol/notes/` remain historical and are not
configuration.

Selection applies only to Linux targets. It examines candidates in the fixed
order above, requires executable discovery, parses identity, then runs the
candidate's info probe. A missing, wrong-product, malformed, or unusable
candidate is retained as a named diagnostic and selection continues. The first
fully valid candidate wins. If neither wins,
`runtime.RuntimeSelectionError`, a `RuntimeError` subclass like
`driver.ReleaseError` and `manifest.ManifestError`, names both candidates and
their individual recovery conditions. A present-but-broken Podman therefore
does not hide a usable Docker, while the stable ordering prevents
environment-dependent preference. `rail.main` adds
`RuntimeSelectionError` to its exception tuple alongside D6's
`driver.SourceError`.

Podman identity is anchored in plain `podman version`, not a Docker-shaped
template. Prep observed:

```text
Client:       Podman Engine
Version:      5.8.3
API Version:  5.8.3
OS/Arch:      linux/amd64
```

The parser requires exactly one top-level `Client:` line whose trimmed value
is exactly `Podman Engine`, followed within that client block by exactly one
`Version:` value matching a dotted-numeric version. It rejects duplicate
identity/version lines, an absent client block, additional product text, and
values such as `Docker Engine`, `docker`, or `Podman-compatible`. This is the
same observed-identity/normalized-version rule used by
`manifest.normalize_tool_output`: store only canonical `Podman Engine` and the
numeric version, never the free-form output. The separate template probes
`.Client.Version`, `.Client.APIVersion`, `.Client.Os`, and `.Client.OsArch`
must agree with the parsed version/OS-architecture values. This prevents a
wrong-product shim from satisfying only Docker-compatible templates. Prep
observed that `{{.Client.Name}}` fails with status 125 and `.Server` aliases
the same object, so neither is an identity source.

Podman's usability probe is one `podman info --format` call that emits the
fixed fields `.Version.Version`, `.Host.OS`, `.Host.Arch`, and
`.Host.Security.Rootless` with unambiguous separators. Prep observed all four
on Podman 5.8.3 and timed plain `podman info` at approximately 0.04 seconds.
The returned engine version must agree with the version probe.

For Docker, all facts in this paragraph are **authored from Docker
documentation and unobserved on this lode**. Identity comes from one
`docker version --format` record containing
`.Client.Platform.Name`, `.Client.Version`, `.Server.Platform.Name`,
`.Server.Version`, `.Server.Os`, and `.Server.Arch`. Following
`manifest._canonical_name`, the parser requires the case-insensitive token
`docker` in both platform-name values and normalizes both to the single
canonical constant `Docker Engine`. Empty, absent, or tokenless values fail;
version-bearing and build-bearing product text is never copied into the
manifest. Usability is one `docker info --format` record containing
`.ServerVersion`, `.OSType`, and `.Architecture`; its values must agree with
the server version record. The documented field paths come from the Docker
`docker version`, `docker system info`, Engine version API, and contexts
references used in prep.

Docker locality is checked separately with
`docker context inspect --format '{{.Endpoints.docker.Host}}'` after accounting
for endpoint precedence. `DOCKER_HOST` takes precedence when set; otherwise
`docker context inspect` resolves the current context, including
`DOCKER_CONTEXT`. This is also **unobserved on this lode**. A `unix://` endpoint is accepted;
`tcp://`, `ssh://`, empty, and every other scheme are rejected because bind
sources are paths on the daemon host, not the client. There is no
Docker-Desktop special case: Desktop on Linux presents a Unix socket and is
covered by the general rule, while D4's empirical mapping probe remains
decisive for every accepted endpoint.

`runtime.render_mount(source, destination, readonly)` validates
absolute nonempty paths and returns one `-v` value. It emits
`SOURCE:DEST:Z` for read-write and `SOURCE:DEST:ro,Z` for read-only for both
runtimes. The runtime name is not a parameter because it would be unused:
there is no runtime branch because prep established that Docker
`run -v` and Podman accept the same independent `ro` and SELinux `Z` options;
the Docker Swarm-service exception is irrelevant. All mounts pass through this
function: the two `_build` mounts, `_tool_invoker`, all five mounts in each of
the two runtime-gate invocations, and D4's ownership probe.

`_preflight` checks target compatibility and the clean tree before selecting a
runtime. For Linux it then selects and probes exactly once, completes D4 and
tool capture, and returns `(authority, target, selected_runtime)`. For macOS it
returns no runtime and performs no runtime probe. `release()` threads the
immutable selection explicitly into `_build`, `_tool_invoker`, and
`_runtime_gates`; it is not a module global because tests and concurrent
library callers must not share mutable selection state. Selection and all
preflight checks finish before `transaction.run()` first creates
`dist/.staging/<target>-<version>`, so failure leaves `dist` untouched. No
stage re-resolves or silently switches engines.

## D2 — Normalized engine evidence and rejection

**Decision.** Linux manifests add an eighth `build_tools` member under the
single exported key `runtime.CONTAINER_RUNTIME_EVIDENCE_KEY`, whose value has
this exact normalized shape:

```text
{
  "client": {"name": "<canonical product>", "version": "<dotted numeric>"},
  "engine": {
    "name": "<canonical product>",
    "version": "<dotted numeric>",
    "os": "linux",
    "architecture": "amd64|arm64"
  }
}
```

Podman uses the observed `Podman Engine` anchor for both names, the normalized
plain-output client version, and the agreeing info version/OS/architecture.
Docker binds the documented client identity/version and the distinct server
identity/version/OS/architecture; all Docker claims remain **unobserved on
this lode**. Rootless state and raw endpoint are selection/preflight facts, not
portable product identity, and are deliberately not authored into the
manifest.

`runtime.validate_evidence(value)` is the one shape definition. It rejects
unknown or missing keys, wrong JSON types, booleans in string positions,
noncanonical product names, non-dotted versions, OS other than `linux`,
architecture outside `amd64|arm64`, client/engine product combinations not
produced by a supported runtime, control characters, paths, annotations, raw
command output, and any value not directly populated by successful probes.
Probe parsers construct through the same validator, so malformed,
free-form, or inferred evidence cannot be authored.

Runtime selection also rejects:

* an inaccessible info endpoint or inconsistent version/info results;
* Docker non-Unix endpoints incompatible with local bind mounts;
* an engine OS other than Linux;
* an engine architecture that does not equal the normalized architecture from
  `target["container_platform"]` and `target["expected_arch"]`
  (`linux/amd64`/`EM_X86_64` or `linux/arm64`/`EM_AARCH64`);
* a target whose two authority representations disagree.

The explicit `--platform` remains on every container invocation as an
additional assertion. Same-architecture Docker behavior and Docker failure
when a requested manifest is absent are **authored from documentation and
unobserved on this lode**.

`manifest.capture_build_tools` continues to require exactly seven authority
`required_tools`. It captures those seven normalized tools, then adds
`container_runtime` only when a Linux runtime invoker supplies validated
evidence. It does not turn `required_tools` into an eight-entry authority list.
`test_tool_evidence_has_exact_keys_and_normalized_versions` becomes a
target-parametrized assertion: Linux has the existing seven ordered keys plus
the imported runtime evidence key; macOS has exactly the existing seven.
Tests reference the exported constant and never repeat the literal evidence
key or engine names.

## D3 — Makefile and driver reach

**Decision.** Extend `rail.py` with a `runtime` command group:

* `runtime select` prints exactly `podman` or `docker` plus one newline;
* `runtime image-tag` prints exactly the shared bare tag plus one newline.

`runtime select` performs the same identity, info, endpoint, and native
architecture checks as package selection, but not the D4 container-write
probe because `make image` must work before the local image exists and is not
a release preflight. On failure it prints no stdout value, prints exactly the
normal `release rail error: <diagnostic>` form to stderr, and returns 2 through
`rail.main` on `RuntimeSelectionError`. The Make recipes use recipe-time shell
command substitution in an `&&` chain, following the existing
`CI_IMAGE="$$(...)"` pattern. Shell assignment receives the substitution's
nonzero status, so the `&&` chain aborts the recipe at that assignment; it does
not continue with an empty runtime value. This status propagation is the
required property of the Makefile approach.

The Makefile's `IMAGE` value is removed as an independent truth source and
resolved through `runtime image-tag`. `PODMAN_RUN` is renamed
`CONTAINER_RUN`. In each applicable recipe, `RUNTIME` and `IMAGE` are resolved
once into shell variables through the two accessors, then `CONTAINER_RUN` is
assembled from those values. `image:` resolves the authority build image as it
does today and invokes `"$RUNTIME" build` with the shared bare tag.
`ci-container` invokes `"$RUNTIME" run`.

The Makefile CI container keeps its literal
`-v $(CURDIR):/src:Z` and
`-v $(GIT_COMMON_DIR):$(GIT_COMMON_DIR):ro,Z` mounts. `ci-container` is a
different contract from the release rail's five mount sites: it exposes the
checkout and git-common directory for the C++ gate, not release inputs. D1
establishes that these suffixes are runtime-invariant, so a `runtime mount`
pass-through would add four Python launches and shell plumbing without a
policy branch. If the runtimes later require different rendering, that is when
the accessor earns its place. The one-renderer requirement applies to all five
`driver.py` release sites, where `runtime.render_mount` remains mandatory; the
Makefile exception is the simpler correct use of the “if avoidable” clause.

The Make image and CI recipes are separate process invocations and each
selects once; the stronger no-re-resolution guarantee applies within one
release invocation, where the selected runtime object is threaded from
`_preflight`. Changing runtime availability between separate Make invocations
is an external-state change and fails or selects anew visibly.

In `driver.py`, the bare shared tag replaces both
`localhost/attestation-sdk-ci` references. `_build`, `_tool_invoker`, and both
Linux `_runtime_gates` use the selected runtime name, its target platform, and
the shared mount renderer. The macOS native branches accept no runtime
parameter use and retain their existing CMake, native tool, and direct
runtime-gate argv.

## D4 — Empirical ownership mapping

**Decision.** A Linux release proves host ownership mapping empirically for
both Podman and Docker; it never infers safety from `SecurityOptions`,
`DockerRootDir`, or a rootless label. Prep observed that the existing Podman
image has `/root` mode `0550`, rustup under `/root/.cargo`, and the build runs
as image-default root against writable `/src`. Rootful Docker would therefore
leave host-root-owned `build/` and break unprivileged `make clean`.

After runtime selection and the clean-tree check, `_preflight` creates a
`tempfile.TemporaryDirectory` outside the repository. It mounts that directory
read-write through `runtime.render_mount`, runs a minimal POSIX `sh` command as
image-default user to create exactly one probe file, and then verifies on the
host that the path is a regular non-symlink file and
`path.stat().st_uid == os.getuid()`. The temporary parent is host-owned, so it
can remove a mismatched root-owned file by directory authority; cleanup runs
on success and failure. No source-tree path is touched, and the earlier dirty
check remains meaningful.

The probe uses the first digest-pinned gate image for the selected target.
That image is already a mandatory release input, has the shell needed by the
runtime gates, is architecture-matched, and is independent of the not-yet-built
local tag. A first release may need to pull it, so network/download latency is
possible, but the actual probe is one file creation and is computationally
cheap; pinning prevents a mutable helper image from becoming new authority.
Failure to obtain the already-required pinned image is an ordinary actionable
preflight failure.

This is a separate invocation from tool evidence. Tool probes require the
local build image and execute read-only version commands, whereas ownership
must run before that image may exist and needs a controlled writable mount.
Combining them would either reintroduce a dependency on `make image` or fail to
test the actual bind ownership proposition. The same standalone rule and
renderer apply to Podman and Docker.

If the file UID differs, is missing, or has the wrong type, preflight fails
closed with:

```text
container ownership mapping failed: <runtime> created the host probe as uid
<actual>, expected invoking uid <expected>; configure rootless Docker or
userns-remap, or install Podman, then retry
```

Invocation/image failures name the runtime and pinned image separately. The
rail does not attempt `--user`, chown cleanup of build outputs, or a fallback
build, because those approaches do not prove `/root/.cargo` remains usable and
can leave partial root-owned residue. No image or base-image change is
required, so the gate condition is not met.

## D5 — One authoring point, promotion-blocking validation

**Decision.** `manifest.build` remains the sole manifest authoring point. It
accepts the completed build-tools mapping and requires validated runtime
evidence for Linux targets and its absence for `macos-arm64`.
`set_validator._validate_one` calls the same exported
`runtime.validate_evidence`; it adds only target-sensitive presence/absence
and shape enforcement:

* each Linux manifest must contain exactly one valid `container_runtime`
  member;
* a macOS manifest must not contain that member;
* the other seven build-tool members retain their exact shape.

This is not a second schema definition: both construction and set validation
delegate to one validator and one evidence-key constant. The check is required
because a hand-edited manifest plus rewritten sidecar otherwise passes hash
agreement. It makes bad or misplaced evidence promotion/set-validation
blocking while leaving `build_tools` deliberately target-specific and outside
the cross-target comparison tuple.

Test fixtures become target-aware. `support.py` keeps a seven-tool base mapping
and exposes a helper that copies it and adds imported, normalized runtime
evidence only for Linux targets. `test_archive.py` requests the mapping for
its target; `make_quartet` does the same for each target, so
`test_set_validator.py` never attaches Linux evidence to `macos-arm64`.
Mutation tests cover missing Linux evidence, malformed evidence, unknown
fields, and forbidden macOS evidence.

Regression preservation is explicit:

* rollback-set cleanup and unrelated-sentinel preservation remain proven by
  `test_every_construction_and_promotion_checkpoint_rolls_back`;
* owned-staging isolation remains proven by
  `test_clean_rerun_replaces_only_owned_staging`;
* existing-quartet and concurrent-file preservation remain proven by
  `test_existing_complete_quartet_is_never_overwritten` and
  `test_concurrent_destination_creation_does_not_clobber`;
* complete-set names, fields, hashes, and members retain all existing
  `SetValidatorTest` structural cases;
* static ABI/architecture gates are unchanged and retain `GateTest` plus
  `test_foreign_archived_binary_fails_with_consistent_hashes`;
* a new driver argv test asserts all eight positional arguments passed after
  `runtime-gate.sh`, for both Linux gate images and the native macOS branch;
* new macOS driver tests assert `_build` uses native CMake, `_tool_invoker`
  returns `None`, and `_runtime_gates` invokes the script directly without
  selection, container argv, mounts, or engine evidence.

The last two close prep's directly implicated coverage gaps rather than relying
only on the shell script's existing eight-argument test.

## D6 — Pinned provenance and implementation order

**Decision.** Add
`upstream_base_commit =
"73c032ebff680ca6d2ba06f4006b511491b71ce9"` to `[release]` in
`sol/release/targets.toml`. Add it to `authority._RELEASE_KEYS`, require it, and
validate exactly 40 lowercase hexadecimal characters using the same
fail-closed pattern as `ca_bundle_sha256`.

`driver._source(root, release)` uses the pinned value and exact source commit,
never `main`. It executes and checks this sequence:

1. Resolve `HEAD^{commit}`. Failure is
   `source commit is missing or is not a commit: HEAD; restore the checkout and
   retry`.
2. Verify the pinned object with
   `git cat-file -e <base>^{commit}`. Failure is
   `pinned upstream base is missing or is not a commit: <base>; fetch the
   repository history containing that commit and retry`.
3. Run `git merge-base --is-ancestor <base> <source>`. Nonzero is
   `pinned upstream base is not an ancestor of source.commit: base=<base>
   source=<source>; check out the intended sol release history and retry`.
4. Obtain the ordered series with
   `git log --reverse --format=%H%x09%s <base>..<source>`. Parse each line with
   `split("\t", 1)`: `%H` is a fixed 40-lowercase-hex field, so the first tab
   is an unambiguous delimiter even when the free-form subject contains later
   tabs. Zero entries is
   `source series is empty: upstream base equals source.commit; check out the
   sol release commits and retry`.
5. Run `git rev-list --count <base>..<source>` and require that value to equal
   the parsed log-entry count. Mismatch is
   `source series is incomplete: expected <count> commits in <base>..<source>,
   parsed <actual>; fetch the complete repository history and retry`.
6. Run `git rev-list --merges <base>..<source>`. Any output is
   `source series contains merge commit <hash>; rebase the sol series to a
   linear history and retry`.
7. Require the final parsed hash to equal the resolved source commit.
   Failure is `source series does not end at source.commit: expected=<source>
   got=<last>; restore the complete ordered range and retry`.
8. Resolve the first entry's parent with `git rev-parse <first>^` and require
   it to equal the pinned base. Failure is
   `source series does not begin immediately after the pinned upstream base:
   base=<base> first=<first> parent=<parent>; fetch or restore the complete
   base-exclusive series and retry`.

These checks explicitly reject missing/non-commit objects, non-ancestor pins,
empty ranges, count-incomplete/shallow output, merges, a wrong terminus, and an
omitted or disconnected head of the base-exclusive series. A per-commit
`git show` subject fetch is rejected because the existing first-tab parsing is
already delimiter-safe and 25 extra subprocesses add no evidence. A second
`rev-list` ordering comparison is also rejected: both lists would be ordered
by Git, so comparing Git's order with itself cannot detect a meaningful
failure. Count, terminus, and first-parent-to-base checks instead prove the
range properties that can fail for a wrong pin or damaged/shallow checkout.
Prep observed this pin as a commit and ancestor, with 25 total commits, 25
first-parent commits, zero merges, and terminus equal to
`47c352c8c5bb1dd5b7c696df2827097273a9e977`. Prep also observed the bug:
`git merge-base main HEAD` returns that same HEAD because local `main` is 25
commits ahead of `origin/main`.

Wrap `_git` failures in a new `driver.SourceError`, explicitly a
`RuntimeError` subclass like `driver.ReleaseError`,
`manifest.ManifestError`, and `runtime.RuntimeSelectionError`, preserving argv
and a concise stderr reason without a raw traceback. It catches `OSError` and
`subprocess.CalledProcessError`; commands that intentionally interpret status,
such as `--is-ancestor`, use `subprocess.run(check=False)` and convert status
to the invariant-specific message above. `rail.main` adds `SourceError` to its
exception tuple alongside `RuntimeSelectionError`, so CLI failure remains
`release rail error: ...` with status 2.

`set_validator` keeps all four source fields in its cross-target tuple. Extend
`test_cross_target_mismatches_name_field_targets_and_values` with an explicit
`source.sol_series_commits` mutation, closing the prep gap and proving AC7
rather than relying on tuple inspection.

Implementation is grouped into the scope's three independently reviewable
commits:

1. **`sol: pin upstream base and derive sol source series`** — add the
   authority pin and its schema guard; replace mutable-`main` provenance with
   the D6 command/invariant sequence; add `SourceError` and CLI handling; add
   authority, source-range rejection, terminus/first-parent/count, and
   cross-target `sol_series_commits` tests. This is the former provenance part
   of step 2 plus the series-mutation portion of step 6.
2. **`sol: select native runtime and record engine evidence`** — add
   `runtime.py` with constants, parsing, validation, selection, endpoint policy,
   and mount rendering; thread one selection through driver preflight, build,
   tool capture, ownership probe, and runtime gates; add target-sensitive
   manifest/set validation and fixtures; add the two `rail.py` accessors;
   update the Makefile and README; add runtime, exact-argv, mount, ownership,
   evidence, macOS-untouched, and retained-quartet regression tests. This
   combines former steps 1, 3, 4, and 5 with the runtime-related portions of
   step 6.
3. **`sol: record native runtime and provenance re-run proof`** — add only the
   resulting native proof under `sol/notes/`, including worktree-local retained
   quartet/failure evidence and the validation outcomes required by AC8. This
   is the real-data/native-acceptance portion of former step 6; it does not mix
   product changes into the proof commit.

### Acceptance criteria and test matrix

| Criterion | Direct proof |
|---|---|
| AC1: deterministic native runtime selection and fail-closed identity/usability/endpoint handling | new `test_runtime.py` table for missing, wrong-product, malformed, unusable, Podman-first, Docker fallback, Unix/non-Unix endpoint, environment/context precedence, and architecture cases |
| AC2: every container command in one release uses the one selected runtime | expanded `test_driver.py` exact argv tests for `_build`, `_tool_invoker`, both runtime gates, and ownership probe, including one threaded selection, bare tag, platform, and full eight-argument gate contract; macOS tests prove no container command is introduced |
| AC3: Linux manifests carry normalized engine evidence and macOS gains no field | updated `test_manifest.py`, target-aware support fixtures, and `test_set_validator.py` missing/malformed/extra evidence mutations; macOS `_tool_invoker` and manifest tests prove absence |
| AC4: mount forms remain `rw :Z`/`ro :ro,Z` and release output is removable without sudo | `test_runtime.py` mount-rendering cases; exact driver argv tests for all five sites; temporary-directory ownership tests for matching UID, mismatched UID, wrong type, cleanup, and no `dist` creation |
| AC5: rollback and retained quartet are never damaged | existing transaction checkpoint/race/overwrite tests plus the worktree-local injected-failure validation below |
| AC6: README states the runtime/ownership rule and does not claim Docker was exercised | review of the commit-2 README change plus an assertion/documentation check that Docker statements are explicitly documentation-authored and unobserved on this lode |
| AC7: provenance uses the authority pin and rejects every invalid range; all source fields compare cross-target | mocked git-command sequence/rejection tests plus explicit `sol_series_commits` cross-target mutation |
| AC8: `make rail-test` and `make ci` pass with native end-to-end and real retained-data failure evidence | commit 3 records both required Make gates and the worktree-local validation sequence below; Docker remains explicitly unexercised because it is absent here |

No test asserts a literal engine name, evidence key, runtime order, local image
tag, or mount suffix that duplicates `runtime.py`; tests import constants or
compare behavior derived from them, following commit `d278793`.

### Later validation plan

Validation must operate only in this Hopper worktree,
`/home/jer/.hopper/worktrees/ogw2thlw`. Its current `build/` and `dist/` are
absent. The operator's main checkout at
`/home/jer/projects/attestation-sdk` is out of scope: do not read, write, move,
or use anything under its `dist/`.

After implementation and unit-level checks, first build a fresh native
linux-x86_64 quartet into this worktree's own `dist/`. Move that complete
quartet only by the rail's documented retained-quartet procedure into a
worktree-local retained directory when a rerun needs clear destinations.
Then exercise every construction and promotion fault injection against a newly
constructed worktree-local quartet, asserting that the pre-existing retained
quartet remains byte-for-byte present and that no partial new quartet remains.
This produces AC5's real-data proof without borrowing the main checkout's
artifacts.

Use the host-global existing Podman image only as an input to this worktree's
run; do not treat its existence as proof that this worktree has built an image.
Record the two requested retained-library embedded-path string counts only from
the freshly built/extracted worktree artifact. Docker selection, Docker
identity fields, endpoint behavior, ownership mapping, mounts, platform
selection, and the same native rail path require a later Docker-host run and
remain unverified here.

## Authored, not natively verified

This design stage runs no validation. The following require later execution:

* all Docker CLI field paths, token-based identity normalization, info
  behavior, context endpoint handling, Unix-socket treatment, SELinux mount behavior, and
  platform failure modes; Docker is absent on this lode and every Docker fact
  above is authored from official documentation;
* rootless Docker/userns-remap ownership success and rootful Docker ownership
  rejection;
* Docker and Podman parity for the centrally rendered read-write and read-only
  mounts;
* native aarch64 selection, ownership, build, and gate behavior;
* native macOS proof that runtime selection and evidence are never reached;
* the new pinned provenance range and rejection diagnostics after
  implementation;
* construction of a fresh quartet and real-data injected rollback proof in
  this worktree's previously absent `dist/`.

Podman facts cited above are from prep's real Podman 5.8.3 output on this host:
plain identity/version, working version/info fields, rootless mode, Linux/amd64
architecture, approximately 0.04-second info cost, and the existing
host-global local build image. They are observed facts, not Docker
extrapolations.

## Risks and open questions

There is no ownership gate blocker requiring an image or base-image change.
The principal implementation risks are Docker platform-name output lacking the
required product token, endpoint classification without accepting an arbitrary
remote daemon, cleanup after an intentionally failed UID probe, and keeping
Make recipe-time selection failures visible. Each is fail-closed and has a
direct test seam above.

One operational cost is settled rather than open: a first ownership probe may
pull the target's first digest-pinned gate image. That is acceptable because
the same image is already mandatory for the release and avoids a new mutable
or unpinned helper image.
