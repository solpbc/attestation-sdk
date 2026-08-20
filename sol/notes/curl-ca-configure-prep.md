# nvattest vendored curl-config CA-configure prep

Research was captured on the Linux x86_64 lode `suze`
(`/home/jer/.hopper/worktrees/uybmbwbe`) on 2026-08-20. The repository tip
was exactly `d2675f8` (`sol: consume the installed libdir in the release
link-closure tests`), and `git status --porcelain --untracked-files=all` was
empty before this note. No production or test file was changed. `make ci`
and `make release` were not run. This hopper worktree has no `build/`
directory.

The live `curl-config` measurements below were taken from the same-commit
primary checkout `/home/jer/projects/attestation-sdk` (`git worktree list`
shows that path and this hopper worktree both at `d2675f8`). That tree has
a container-produced CI build at `build/` and no `build/release/`. The
installed script was copied into `/var/tmp/curl-ca-configure-prep-*` only
for the four failure-state probes; that scratch tree was removed after
this note.

Python was 3.13.13. `subprocess.run` on this interpreter goes through
`os.posix_spawn`.

## Required baseline

```text
$ git status --porcelain --untracked-files=all
$ python3 -m unittest discover -s sol/release/tests -p 'test_gate.py'
.......
----------------------------------------------------------------------
Ran 7 tests in 0.003s

OK
```

Seven tests, exit 0. Porcelain was empty.

## 1. Exact `curl-config` host paths

`CURL_INSTALL_DIR` is the top-level CMake binary dir, not the SDK
subdirectory binary dir:

```cmake
# nv-attestation-sdk-cpp/CMakeLists.txt:326
set(CURL_INSTALL_DIR "${CMAKE_BINARY_DIR}/curl-install")
```

The CLI is the CMake source (`-S nv-attestation-cli`). It adds the SDK as
a subdirectory whose *binary* dir is nested:

```cmake
# nv-attestation-cli/CMakeLists.txt:86-92
set(NVAT_SDK_BUILD_DIR "${CMAKE_CURRENT_BINARY_DIR}/nv-attestation-sdk-build")
set(NVAT_SDK_INCLUDE_DIR ${NVAT_SDK_BUILD_DIR}/include)

add_subdirectory(
    "${CMAKE_CURRENT_SOURCE_DIR}/../nv-attestation-sdk-cpp"  # Source directory
    "${NVAT_SDK_BUILD_DIR}"                                  # Binary directory
)
```

`add_subdirectory` does not change `CMAKE_BINARY_DIR`. Both invocations
therefore install curl next to the top-level `-B` directory:

| Invocation | `-B` | Host `curl-config` | Container prefix baked into the script |
| --- | --- | --- | --- |
| `make ci-container` (`Makefile:52-55`) | `build` | `<repo>/build/curl-install/bin/curl-config` | `/src/build/curl-install` |
| `driver._build` Linux (`driver.py:279-284`) and Darwin (`driver.py:294-300,584`) | `build/release` | `<repo>/build/release/curl-install/bin/curl-config` | Linux container: `/src/build/release/curl-install`; Darwin native: a host path (unobserved here) |

Configure flags that suppress a baked host CA path are already on the
ExternalProject (`CMakeLists.txt:342-344`):

```cmake
      --with-ca-fallback
      --without-ca-bundle
      --without-ca-path
```

Live CI tree evidence, same commit, not this hopper worktree:

- `CMAKE_CACHEFILE_DIR:INTERNAL=/src/build`
- `CMAKE_HOME_DIRECTORY:INTERNAL=/src/nv-attestation-cli`
- `USE_SYSTEM_DEPS:BOOL=OFF`
- `build/curl-install/` exists (`bin/`, `include/`, `lib/`, `share/`)
- `build/nv-attestation-sdk-build/curl-install` does **not** exist
- ExternalProject in-source residue also exists at
  `build/nv-attestation-sdk-build/curl_external-prefix/src/curl_external/curl-config`;
  that is not the installed prefix script

This hopper worktree: `stat build` → `No such file or directory`. No
mtime.

Live installed script
`/home/jer/projects/attestation-sdk/build/curl-install/bin/curl-config`:

```text
mtime=2026-08-01 14:08:57.474265432 -0600
mode=-rwxr-xr-x 755
size=5997
file: POSIX shell script, ASCII text executable, with very long lines (465)
SELinux: container_file_t
prefix="/src/build/curl-install"
```

It is executable and runnable from the host. `--ca` and `--configure`
only echo baked strings; they do not need the container `/src/...` prefix
to exist on the host.

No `build/release/curl-install` exists on either checkout.

## 2. Live `curl-config --ca` and `--configure`

Host path used:
`/home/jer/projects/attestation-sdk/build/curl-install/bin/curl-config`.
Invoked via `subprocess.run([path, flag], capture_output=True, text=True,
check=False)`.

`--ca` (exit 0):

```text
stdout_repr='\n'
stderr_repr=''
returncode=0
```

The script body is a bare `echo` (`curl-config:76-78`). Stripped stdout
is the empty string; it is not a host path.

`--configure` (exit 0):

```text
stdout_repr=" '--prefix=/src/build/curl-install' '--with-openssl=/src/build/openssl-install' '--without-libssh2' '--without-nghttp2' '--without-brotli' '--without-zstd' '--without-libidn2' '--without-librtmp' '--without-libpsl' '--with-ca-fallback' '--without-ca-bundle' '--without-ca-path' '--disable-ldap' '--disable-shared' '--enable-static' 'CC=/opt/rh/gcc-toolset-14/root/usr/bin/cc' 'CFLAGS= -fPIC' 'PKG_CONFIG_PATH=/src/build/openssl-install/lib/pkgconfig'\n"
stderr_repr=''
returncode=0
```

The configure line contains `--with-ca-fallback`, `--without-ca-bundle`,
and `--without-ca-path`. It does not contain `--with-ca-bundle=` or
`--with-ca-path=`.

A copied executable copy in scratch reproduced the same `--ca` stdout
(`'\n'`, exit 0).

## 3. Four absence/failure states

Probes used a scratch copy of the live script under
`/var/tmp/curl-ca-configure-prep-*`. Each case ran `os.access(path,
os.X_OK)` and `subprocess.run([path, '--ca'], capture_output=True,
text=True)` with both `check=False` and `check=True`.

`os.access(X_OK)` is `False` for (a), (b), and (c). It cannot tell those
three apart. `subprocess.run` of an argv list does **not** produce shell
exit 126.

### a. absent `curl-install/` tree

Path: `<scratch>/a/curl-install/bin/curl-config`

- `Path.exists` on the file, `bin/`, and `curl-install/`: all `False`
- `os.access(X_OK)`: `False`
- `stat`: `FileNotFoundError: [Errno 2] No such file or directory`
- `subprocess.run` (`check=False` and `check=True`): raises
  `builtins.FileNotFoundError` (`errno=2`, `strerror='No such file or
  directory'`, `filename=<path>`). `returncode` is `None`. MRO:
  `FileNotFoundError` → `OSError` → `Exception`.

### b. `curl-install/` present, `bin/curl-config` absent

Two layouts: `curl-install/bin/` present without the file, and
`curl-install/` present with `bin/` absent. Subprocess behavior was
identical.

- `curl-install.exists`: `True`
- file `Path.exists`: `False`
- `os.access(X_OK)`: `False`
- `subprocess.run`: same `FileNotFoundError` as (a)

(a) and (b) are indistinguishable from `os.access` and from the
subprocess exception type. The distinguisher is `Path(curl-install).is_dir()`
versus `Path(curl-config).exists()`.

### c. present, not executable (`chmod -x`)

Copied live script, then cleared owner/group/other execute bits → mode
`0o100644` (`-rw-r--r--`).

- `Path.exists`: `True`; `Path.is_file`: `True`
- `os.access(X_OK)`: **`False`**
- `os.access(R_OK)`: `True`
- `subprocess.run([path, '--ca'])` with `check=False` **raises**
  `builtins.PermissionError` (`errno=13`, `strerror='Permission denied'`,
  `filename=<path>`). It does **not** return a `CompletedProcess` with
  exit 126. `returncode` is `None`. MRO: `PermissionError` → `OSError` →
  `Exception`.
- `check=True`: the same `PermissionError`, not
  `subprocess.CalledProcessError`.

A `chmod 0` variant (`0o100000`) also raised `PermissionError`;
`os.access(X_OK)` was still `False` and `os.access(R_OK)` became `False`.

### d. present, executable, exits non-zero

Stub:

```sh
#!/bin/sh
echo 'curl-config boom' >&2
exit 7
```

mode `0o755`.

- `os.access(X_OK)`: **`True`**
- `check=False`: no exception. `CompletedProcess` with `returncode=7`,
  `stdout=''`, `stderr='curl-config boom\n'`
- `check=True`: `subprocess.CalledProcessError` (`returncode=7`,
  `stderr='curl-config boom\n'`). MRO: `CalledProcessError` →
  `SubprocessError` → `Exception`. This is **not** an `OSError`.

### How four messages can be told apart

| State | `curl-install/` dir | `curl-config` file | `os.access(X_OK)` | `subprocess.run([path, '--ca'])` |
| --- | --- | --- | --- | --- |
| a | missing | missing | `False` | `FileNotFoundError` (ENOENT=2) |
| b | present | missing | `False` | `FileNotFoundError` (ENOENT=2) |
| c | present | present, `-x` | `False` | `PermissionError` (EACCES=13); not exit 126 |
| d | present | present, `+x` | `True` | no spawn error; `returncode != 0` (`check=False`) or `CalledProcessError` (`check=True`) |

`apple._command` (`apple.py:41-68`) catches `OSError` with `check=False`.
Copied as-is, that merge would fold (a), (b), and (c) into one "cannot
invoke" path and leave only (d) on the `returncode` path. Four distinct
messages need an explicit existence check on the install dir and on the
script *before* `subprocess.run`.

`driver._run` (`driver.py:27-56`) uses `check=True` and catches
`(OSError, subprocess.CalledProcessError)`. That splits (c) from (d) in
the exception type / string, and still merges (a) with (b).

## 4. Whether existing rail tests observe new `sol/release/` code

### `sol/release/tests/test_ci_container.py`

It binds `MAKEFILE = ROOT / "Makefile"` at `test_ci_container.py:16` (the
import at line 15 is `from release_rail import runtime`). It does **not**
assert Makefile line 15. Makefile:15 is the `TEST_SERVICE_KEY` comment.

What it actually asserts about Makefile *recipe* text, via
`make_recipe()` (`:19-29`), which takes tab-indented lines after
`{target}:`:

- `ci-container` recipe contains exactly one `runtime run-args`, the
  `RUN_ARGS="$$( $(RAIL) runtime run-args "$$RUNTIME" )"` assignment
  ending in `&& \`, and `"$$RUNTIME" run --rm $$RUN_ARGS -v $(CURDIR):/src:Z`
  after that assignment; no `--platform` (`:62-76`)
- `rm -rf build` < `mkdir -p build/.ci-home` < `cmake -S $(CLI_DIR)`
  (`:95-101`)
- `clean` recipe is exactly `rm -rf build` (`:101`)

It also reads `sol/ci/Containerfile`. Adding a Python module under
`sol/release/` does not change those texts. Changing `Makefile` or
`Containerfile` would.

### `sol/release/tests/test_baseline_stability.py`

Frozen inputs:

| Constant | Path | What is asserted |
| --- | --- | --- |
| `TARGETS` | `sol/release/targets.toml` | byte-identical to baseline `b75e95ae` (`:135-136`) |
| `AUTHORITY` | `sol/release/release_rail/authority.py` | `TARGET_IDS` tuple only (`:138-144`), not the whole file |
| `SDK_CMAKE` | `nv-attestation-sdk-cpp/CMakeLists.txt` | `project()` identity, FetchContent/ExternalProject coordinates, `corrosion_import_crate` tokens, `nvat_exempt_compiled_third_party` function+calls |
| `CLI_CMAKE` | `nv-attestation-cli/CMakeLists.txt` | `project()` identity only |
| `LICENSE` | `LICENSE` | byte-identical |
| `HEADER_BOUNDARY` | `nv-attestation-sdk-cpp/cmake/nvat_header_consumer_boundary.cmake` | no dependency-coordinate tokens |
| `APPLE_LINK_CLOSURE` | `nv-attestation-sdk-cpp/cmake/nvat_apple_system_link_closure.cmake` | no dependency-coordinate tokens |
| `RUST_INVENTORY` | four `nv-attestation-sdk-rust/**/{Cargo.toml,build.rs}` paths | path tuple + no tracked `Cargo.lock` |

No frozen path is under `sol/release/release_rail/` other than
`authority.py`. `sol/release/README.md` and `sol/notes/` are not frozen.
`generate-dependencies.py` coordinate comparison walks SDK/CLI
`CMakeLists.txt` files, not `release_rail/`.

### Directory enumeration

Nothing lists `sol/release/release_rail/*.py` or `sol/release/tests/` as
a closed set. `release_rail/__init__.py` is a one-line docstring.
`make rail-test` / `unittest discover -p 'test_*.py'` will *run* a new
`test_*.py` file; that is discovery, not a count assertion.

Adding only a new module file is therefore invisible to these suites.

Wiring a live `curl-config` invocation into `driver.release` /
`builder()` **is** visible. Tests that execute the real `builder` after a
successful `_build` (mocked or via mocked `_run`) include:

- `test_release_threads_one_selection_through_every_container_command`
  (`test_driver.py:338-457`): temp `root` has no
  `build/release/curl-install`; `_build` is not patched; `_run` is. After
  `checkpoint("after-build")` it calls `_stage` (patched). A new
  `subprocess.run` of `root/build/release/curl-install/bin/curl-config`
  would hit state (a) unless also mocked.
- `test_macos_resolve_inconsistency_never_publishes`
  (`test_driver.py:1018-1071`): patches `_build` to succeed, then
  continues through `_stage` to `apple.resolve`. Same missing tree.

Tests that fail inside `_build` (`test_macos_build_failures_use_driver_build_seam_and_never_publish`,
`:736-918`) never reach `after-build`.

## 5. Shapes the design stage will need

### `sol/release/release_rail/apple.py`

- Exception: `class AppleToolchainError(RuntimeError): pass` (`:37-38`).
- `resolve(target, build_dir, runner=subprocess.run)` (`:249-319`) reads
  `build_dir/CMakeCache.txt` through `_cache()`, then compiler metadata,
  then re-observes the live toolchain and compares.
- `_cache(build_dir)` (`:175-207`) uses `path.read_text(...)` and
  converts `OSError` into `AppleToolchainError`.
- `_command` (`:41-68`) uses `check=False`, `stdout/stderr=PIPE`,
  `text=True`; `OSError` → "cannot invoke"; nonzero → "failed: {reason}";
  empty stdout is also an error.

Representative messages (verbatim templates):

```text
Apple toolchain evidence failed: cannot invoke {arguments[0]}: {error}; install Xcode Command Line Tools and verify the active developer directory with `xcode-select -p`, then retry
```

```text
Apple toolchain evidence failed: {' '.join(arguments)} failed: {reason}; select a valid Xcode developer directory with `xcode-select`, then retry
```

```text
Apple toolchain evidence failed: cannot read {path}: {error}; remove build/release and rerun the native configure
```

Pattern: prefix, what failed, recovery after a semicolon, "then retry".

`apple.resolve` is Darwin-only, after archive extraction, inside
`manifest.capture_build_tools` (`driver.py:634-638`), not at
`after-build`.

### `sol/release/rail.py` `main()`

```python
# rail.py:74-141
def main() -> int:
    arguments = _parser().parse_args()
    try:
        ...
    except (
        authority.AuthorityError,
        apple.AppleToolchainError,
        archive.ArchiveError,
        driver.ReleaseError,
        driver.SourceError,
        gate.GateError,
        manifest.ManifestError,
        runtime.RuntimeSelectionError,
        set_validator.SetValidationError,
        transaction.TransactionError,
        KeyError,
        ValueError,
    ) as error:
        print(f"release rail error: {error}", file=sys.stderr)
        return 2
```

A new exception type that is not in this tuple becomes an uncaught
traceback instead of `release rail error: ...` / exit 2.
`test_driver.py:259-277` covers the CLI form for
`ArchiveError`/`AppleToolchainError`/`ManifestError`/`SourceError` only;
adding to the tuple without extending that test does not fail it.

### `sol/release/release_rail/driver.py` `builder()` around 570-610

```python
570|def release(root: Path, target_id: str | None) -> dict[str, Path]:
571|    data, target, selection = _preflight(root, target_id)
572|    version = _version(root, data)
573|    names = set_validator.quartet_names(target, version)
574|    source = _source(root, data.release)
575|
576|    def builder(owned: Path, checkpoint: Any) -> dict[str, Path]:
577|        stage = owned / "stage"
578|        extracted = owned / "extracted"
579|        stage.mkdir()
580|        extracted.mkdir()
581|        ca = owned / "ca-bundle.pem"
582|        _acquire_ca(data.release, ca)
583|        checkpoint("after-dependency-acquisition")
584|        build_dir = root / "build/release"
585|        _build(root, target, build_dir, source["source_date_epoch"], selection)
586|        checkpoint("after-build")
587|        _stage(root, build_dir, stage, target, ca)
...
605|        _gate_binaries(stage, data, target)
606|        checkpoint("after-static-stage-gate")
```

`_gate_binaries` (`:379-383`) runs `gate.gate_file` on staged binary
members only. `gate.FORBIDDEN_CA_PATHS`
(`gate.py:12-15,39-42`) looks for compiled host CA *strings* in those
binaries (`/etc/ssl/certs/ca-certificates.crt`,
`/etc/pki/tls/certs/ca-bundle.crt`). That is a different surface from
reading `curl-config`. `runtime-gate.sh:59-84` probes the operator
`--ca-bundle` CLI, also a different surface.

Linux `_build` (`:258-287`) is a container `cmake -S nv-attestation-cli
-B build/release ... && cmake --build build/release`. Darwin `_build`
(`:288-319`) is host cmake against the same `build_dir`.

### `sol/release/tests/test_apple_cmake.py:195-215` stub pattern

```python
            def stub(name, body):
                path = root / name
                path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
                path.chmod(0o755)
                return path

            success, output = self.run_script(
                "Darwin", "macosx", xcrun=stub("success", f"printf '%s\\n' '{sdk}'")
            )
```

Local helper: `#!/bin/sh` body + `chmod 0o755`. Later cases reuse it for
nonzero (`exit 7`), empty stdout, and a missing path
(`"/missing/xcrun"`).

### `sol/release/README.md` § Verification responsibility

Quoted in full as of this commit:

```markdown
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
```

The section continues with `### R2 publication` after this quote
(`README.md:158-162`).

### `sol/release/release_rail/fixtures.py`

Synthetic ELF (`elf_fixture`) and Mach-O (`macho_fixture`) byte builders
plus `write_fixture(directory, name, payload)` that writes raw bytes.
Consumed by `test_gate.py` / `test_elf.py` / `test_macho.py`. It is not a
shell-script stub factory. A `curl-config` stub is the
`test_apple_cmake.py` `#!/bin/sh` + `chmod 0o755` kind of fixture, not
this module's current job.

## Adjacent consumers (not the target)

- `driver.py:581-582,368` ships `share/ca/ca-bundle.pem` as an operator
  bundle acquired after preflight; that is not curl's configure-time CA
  path.
- `gate.FORBIDDEN_CA_PATHS` / `_forbidden_strings` (`gate.py:12-15,39-42`)
  already fail closed on two compiled host CA strings in staged
  `nvattest` / `libnvat`.
- `sol/notes/design.md:128-131` already records the intended
  `--with-ca-fallback --without-ca-bundle --without-ca-path` configure
  triple; this prep measured that triple in a live `curl-config
  --configure` line.

## Unobserved here

- This hopper worktree has no `build/` or `build/release/`.
- No live `build/release/curl-install/bin/curl-config` exists on the
  primary checkout either; only the CI `-B build` tree was measured.
- Darwin-native `curl-config` prefix/output was not measured.
- `make ci` / `make release` were not run.
