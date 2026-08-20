# Three-target release operation

`targets.toml` is the sole authority for target IDs, native-host predicates,
image digests, archive members, ABI policy, runtime references, and required
tools. Inspect it before operating the rail:

```sh
python3 sol/release/rail.py authority host-target
```

## Native construction

Run exactly one target on its matching native host:

```sh
make release TARGET=linux-x86_64   # native x86_64 Linux
make release TARGET=linux-aarch64  # native aarch64 Linux
make release TARGET=macos-arm64    # native arm64 macOS
```

The target is mandatory. The driver rejects missing, misspelled, and
host-incompatible targets before creating or changing `dist/`.

Linux operation selects Podman first and falls back to Docker only when Podman
is unavailable or unusable and Docker exposes a usable local Unix-socket
engine. Preflight records normalized client/engine evidence and verifies with a
temporary bind-mounted file that image-default root maps back to the invoking
host UID. A rootful engine without a safe user-namespace mapping fails before
release staging; configure rootless Docker or userns-remap, or install Podman.

### macOS prerequisites

The native toolchain reported by Jer for this release work is macOS 26.5,
Xcode 26.5, AppleClang 21.0.0, the macOS 26.5 SDK, arm64, with deployment
floor 14.0. Xcode, SDK, and compiler versions are observed evidence recorded
in each Darwin manifest; they are not pinned requirements. Architecture and
the deployment floor are release authority in `targets.toml`.

The active `xcrun --sdk macosx --show-sdk-path` result must be an absolute,
existing SDK directory and the release must run natively on Apple Silicon.
CMake resolves the SDK, deployment floor, and requested arm64 architecture
before `project()` so compiler initialization receives the authored inputs.
Immediately after `project()`, it validates CMake's measured host processor,
configured system processor, single arm64 architecture, and native Darwin
status. A failed post-project validation leaves CMake cache and compiler-ID
diagnostics in the build directory; remove that failed build directory before
retrying natively on Apple Silicon.
The release driver passes the authority floor. A plain native CMake configure
has no macOS deployment-target default and must provide it explicitly:

```sh
cmake -S nv-attestation-cli -B <build-dir> \
  -DCMAKE_OSX_DEPLOYMENT_TARGET=14.0
```

If SDK resolution fails, repair the active developer directory with
`xcode-select`, verify it with `xcrun`, remove the failed build directory, and
retry. The rail fails rather than using an implicit compiler SDK or deployment
target.

**First verify the library chain produced by CMake.** The `macos-arm64`
inventory in `targets.toml` assumes CMake's Darwin `VERSION`/`SOVERSION`
handling produces:

```text
libnvat.dylib -> libnvat.1.dylib -> libnvat.1.2.2.dylib
```

That chain is authored from CMake documentation, not observed on this lode.
CMake may instead point both symlinks directly at the real library. If native
output differs, correct the member/link inventory in `targets.toml`, the one
authority location. Staging deliberately fails with the expected and actual
link target rather than shipping an assumption.

Install Xcode Command Line Tools, GNU tar, and xz:

```sh
xcode-select --install
brew install gnu-tar xz
```

Confirm every command listed in the target's `required_tools` array resolves
before releasing. The manifest records normalized versions of the tools
actually invoked.

## Complete-set validation

After the three native hosts return their quartets to one directory:

```sh
python3 sol/release/rail.py validate-set --dist dist
```

The default version is derived from the upstream CMake project version and the
authority's Sol revision, and the expected source defaults to this checkout's
`HEAD`. For a collection validated outside its source checkout, pass the
explicit expected identity with `--source-commit <40-hex-commit>`. Use
`--version` only to inspect a deliberately selected historical set. Validation
requires exactly one complete quartet for every authority target and rechecks
archive/manifest hashes, sidecars, member layout, archived binary policy, and
shared source/release identity.

## Reproducibility claim

> For the same target, on the same host, with the same pinned toolchain and
> complete pinned inputs, two builds produce byte-identical archives and
> sidecars; cross-host and cross-OS byte identity is not claimed.

## Verification responsibility

### Authored and checked on the lode

The lode exercises the real production pre-project Apple SDK-resolution
prefixes in script mode and the real production post-project architecture
validators through offline configure fixtures. Those fixtures prove
resolution, compiler-boundary ordering, fail-closed comparisons, and
process-local once-per-configure behavior; forcing Darwin variables on Linux
does not prove that native macOS CMake populates them. It also exercises
synthesized ELF and Mach-O parsing/policy fixtures, authority validation,
normalized Apple evidence validation, deterministic archive/sidecar fixtures
for every authority target, schema-v2 manifests, transaction rollback
injection, complete set validation, ShellCheck, and rejected-target preflight
behavior. It also
constructed a real native `linux-x86_64` release and passed its static gates,
both bare-container runtime gates, a same-commit byte-for-byte rebuild, and the
full C++ CI gate. It did not construct or run native `linux-aarch64` or
`macos-arm64` code. Docker selection and execution are authored from official
Docker documentation and were not exercised on this lode.
The vendored curl-config CA-configure assertion is unfalsified and must
not be cited as coverage until VPE has rebuilt the vendored curl with
the three flags removed and seen it go red.
The vendored OpenSSL openssldir gate is unfalsified and must
not be cited as coverage until VPE has rebuilt with the openssldir
pointed back into the build tree and seen it go red.

### Post-ship VPE native work

VPE must construct and smoke-test the aarch64 Linux release on a native
aarch64 Linux host and the macOS release on a native arm64 Mac. The macOS
operator must verify the dylib chain above, verbose
fmt/spdlog/nvat/nvattest warning flags, including ordinary
first-party/generated/installed roots and system-classified pinned fmt/spdlog
roots, all four external projects' effective SDK/architecture/floor inputs,
the genuine Apple toolchain evidence, and the final Mach-O architecture and
deployment floor. VPE must also rerun Pro5E on the native arm64 archive and
record both final link commands: `nvat` must contain the selected-SDK
CoreFoundation and iconv closure exactly once after their static owners, while
`nvattest` must contain neither as a direct link item. This Linux lode observed
only generated CMake link structure; it did not prove native Apple linkage.
Each native driver invocation
runs the target's static gate and all runtime gates declared by authority
before promotion.
VPE must additionally record the genuine post-`project()` values of
`CMAKE_HOST_SYSTEM_PROCESSOR`, `CMAKE_SYSTEM_PROCESSOR`,
`CMAKE_OSX_ARCHITECTURES`, `CMAKE_CROSSCOMPILING`, and `CMAKE_SYSTEM_NAME`,
and confirm that the architecture validator passes once in both standalone
SDK and CLI-with-SDK native configures.

VPE must exercise the native Docker path directly on Spark, including
Unix-socket selection, ownership mapping, image construction, the C++ CI gate,
and a native release preflight. That Spark record is the Docker execution proof;
the lode does not claim it.

### R2 publication

R2 publication begins only after all three quartets have been collected and
the complete-set validator succeeds. Publication policy and credentials are
outside this rail; a successful local build is not publication evidence.

## After rebasing the sol series onto a new upstream

The release authority pins the fork point. A rebase moves it, and nothing
updates the pin automatically, so two edits are required in this order:

1. Set `release.upstream_base_commit` in `targets.toml` to the new fork
   point: `git merge-base HEAD upstream/main`. Leaving it stale does not
   produce a subtly wrong artifact; `driver._source` refuses the release
   outright with `source series contains merge commit <sha>`, because the
   stale range then spans upstream merges.
2. Move `BASELINE` in `sol/release/tests/test_baseline_stability.py` to the
   commit made in step 1. `targets.toml` is frozen byte-for-byte against
   that commit, so step 1 alone leaves `make rail-test` red. The two changes
   cannot be combined into one commit for the same reason.

Verify with `driver._source`, not with the test suite alone — a baseline
move passes the suite whether or not the pin was actually corrected.

Keep the pre-rebase tip on a branch. The old `BASELINE` commit leaves the
series and stays reachable only there, along with any commit SHA cited in
design notes.
