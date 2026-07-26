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

The lode exercises synthesized ELF and Mach-O parsing/policy fixtures,
authority validation, deterministic archive/sidecar fixtures for every
authority target, schema-v2 manifests, transaction rollback injection, complete
set validation, ShellCheck, and rejected-target preflight behavior. It also
constructed a real native `linux-x86_64` release and passed its static gates,
both bare-container runtime gates, a same-commit byte-for-byte rebuild, and the
full C++ CI gate. It did not construct or run native `linux-aarch64` or
`macos-arm64` code. Docker selection and execution are authored from official
Docker documentation and were not exercised on this lode.

### Post-ship VPE native work

VPE must construct and smoke-test the aarch64 Linux release on a native
aarch64 Linux host and the macOS release on a native arm64 Mac. The macOS
operator must verify the dylib chain above before anything else. Each native
driver invocation runs the target's static gate and all runtime gates declared
by authority before promotion.

VPE must exercise the native Docker path directly on Spark, including
Unix-socket selection, ownership mapping, image construction, the C++ CI gate,
and a native release preflight. That Spark record is the Docker execution proof;
the lode does not claim it.

### R2 publication

R2 publication begins only after all three quartets have been collected and
the complete-set validator succeeds. Publication policy and credentials are
outside this rail; a successful local build is not publication evidence.
