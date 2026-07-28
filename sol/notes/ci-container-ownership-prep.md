# nvattest CI container ownership prep

Research was captured on the Linux x86_64 lode
`/home/extro/.hopper/worktrees/zqatxykw` on 2026-07-27. The repository tip
was exactly `1c95b1f` (`sol: normalize AppleClang compiler evidence in the
release resolver`), and `git status --porcelain --untracked-files=all` was
empty before this note. No production or test file was changed. `make ci`
and `make release` were not run.

The root-owned population is historical evidence, not a result reproduced
here: `req_xdy5i2d6` records approximately 26,800 files and 1.3 GB per
worktree across four worktrees. The removed trees cannot now be recounted.
The premise correction in
`/home/extro/projects/extro/vpe/workspace/nvattest-bare-metal-build-research-260727.md`
§ 1 is controlling: the affected path is `make ci` -> `ci-container`, not
upstream `dev-env.sh` or `dev/`.

## 1. Two-runtime asymmetry

Research § 5 gives the Docker half; § 11a supersedes its previously
unmeasured Podman prediction with a live result:

| Runtime and invocation | Bind-mount result |
| --- | --- |
| Rootful Docker, no `--user` | The image-default container uid 0 is host uid 0, so bind-mounted output is `root:root`. This is the contamination path. |
| Rootful Docker, `--user "$(id -u):$(id -g)"` | Bind-mounted output would be written as the operator, but the process cannot traverse `/root`; the current Rust proxies on `PATH` are therefore unreachable and the Rust part of the build cannot run. |
| Rootless Podman, no `--user` | Container uid 0 maps to the invoking host uid. The measured file was host-owned `jer:jer`, so this path is already correct. |
| Rootless Podman, `--user "$(id -u):$(id -g)"` | Container uid 1000 maps into Podman's subordinate-id range and cannot write the host-uid-1000 bind mount. The measured command failed `Permission denied` and created no file. |

The § 11a Podman output was:

```text
=== podman default (no --user) ===
=== podman WITH --user $(id -u):$(id -g) ===
sh: asuser: Permission denied
=== host ownership (invoking user is 1000:1000 = jer) ===
default  uid=1000 gid=1000  jer:jer
stat: cannot statx 'asuser': No such file or directory
```

The consequence is functional, not an optimization difference: one uniform
`--user` flag fixes Docker's bind-mount ownership but makes the rootless
Podman build unable to create output. Suze, the x86_64 release host, uses
that Podman behavior, so the uniform flag takes that host's build offline.

## 2. Docker shim check

The requested independent check did not find a shim:

```text
$ command -v docker
/usr/bin/docker
$ which -a docker
/usr/bin/docker
/bin/docker
$ type -a docker
docker is /usr/bin/docker
docker is /bin/docker
$ docker --version
Docker version 29.6.2, build dfc4efb
$ test -e /home/extro/.local/bin/docker || echo ABSENT
ABSENT
```

`/home/extro/.local/bin` occurs before `/usr/bin` on `PATH`, so an entry
there would have won resolution. Both `-e` and `-L` checks reported
`/home/extro/.local/bin/docker` absent. `/bin/docker` is the later system
alias, not an earlier shim.

## 3. All `attestation-sdk-ci` consumers

The tag is exported once as `runtime.LOCAL_IMAGE_TAG`
(`sol/release/release_rail/runtime.py:15-23`). `rail.py runtime image-tag`
prints that constant (`sol/release/rail.py:56-60,77-82`), which is how the
Makefile obtains it. `make image` builds the tag from the target's
digest-pinned base and `sol/ci/Containerfile`
(`Makefile:31-35`; `sol/release/targets.toml:10-19,38-47`). Repository search
finds exactly these three run consumers:

| Consumer | Current uid and ownership behavior | `/src` mount | Work performed |
| --- | --- | --- | --- |
| `ci-container` | No `--user`; the image declares no `USER`, so the process is container uid 0. On this rootful-Docker host that is host uid 0. | Read/write `$(CURDIR):/src:Z`. | Deletes root `build/`, configures with tests enabled, builds, and runs the offline unit label (`Makefile:45-54`). |
| `driver._build()` | No `--user`; container uid 0. The release preflight first requires its default runtime mapping to create host output as `os.getuid()`, so rootless Podman maps it to the operator and rootful Docker fails before this consumer runs (`driver.py:475-525,547-560`). | Read/write via `runtime.render_mount(root, "/src", False)`, hence suffix `Z` (`driver.py:251-287`; `runtime.py:310-316`). | Deletes and performs the release build in `/src/build/release`, including the Corrosion/Rust target. |
| `driver._tool_invoker()` | No `--user`; container uid 0. It is created only after the same ownership probe in preflight. | Read-only via `runtime.render_mount(root, "/src", True)`, hence suffix `ro,Z` (`driver.py:324-361,558-566`; `runtime.py:310-316`). | Runs `compiler`, `cmake`, `rustc`, and `cargo` with `--version`; nonzero status becomes `ManifestError`. Manifest capture routes the remaining tools to the host (`manifest.py:104-127`). |

All three depend on the same image environment, but their write
requirements differ:

* **`PATH`: all three break without it.** The two build consumers execute
  shell, CMake, compiler, and Rust commands by bare name. `_tool_invoker`
  likewise passes each bare command directly to `subprocess.run`
  (`driver.py:332-359`). Linux authority requires both `rustc` and `cargo`
  (`targets.toml:36,64`).
* **`RUSTUP_HOME`: every Rust invocation needs an effective readable,
  traversable Rustup home.** The current `cargo` and `rustc` entries are
  symlinks to the `rustup` proxy, not real toolchain binaries. The real
  executables are under
  `/root/.rustup/toolchains/1.88.0-x86_64-unknown-linux-gnu/bin/`.
  Consequently, moving only the proxy directory/Cargo home is insufficient:
  both full builds and `_tool_invoker`'s `--version` capture fail if the
  proxies cannot resolve the real toolchain.
* **`CARGO_HOME`: both full builds need an effective writable Cargo home;**
  it supplies Cargo's registry/git/cache/config state and is also the
  installation location whose `bin` directory holds the proxies. It is
  currently unset and defaults from `HOME`. `_tool_invoker` does not need a
  writable Cargo home for `--version`; it needs the proxy directory on
  `PATH` and the real toolchain through `RUSTUP_HOME`.
* **`HOME`: both full builds need an effective writable home, directly and
  as the fallback for unset Cargo/Rustup homes.** CMake fetches Corrosion and
  regorus before importing the Rust crate
  (`nv-attestation-sdk-cpp/CMakeLists.txt:51-73`), and the test-enabled CI
  path runs the certificate-generation shell through the test environment
  (`nv-attestation-sdk-cpp/unit-tests/include/environment.h:24-33`;
  `generate_test_certs.sh:242-250`). The current uid-0 paths work because
  `HOME=/root` is writable. In a live `--user 1001:1001` probe the
  manylinux entrypoint supplied `HOME=/`, which is not writable by that uid.
  `_tool_invoker` itself only reads version evidence and does not require a
  writable home once `PATH` and `RUSTUP_HOME` resolve.

The current image installation confirms the proxy/toolchain split:

```text
default HOME=</root> CARGO_HOME=<> RUSTUP_HOME=<>
drwxr-xr-x 3 root root 4096 Jul 27 01:28 /root/.cargo
drwxr-xr-x 2 root root 4096 Jul 27 01:28 /root/.cargo/bin
drwxr-xr-x 6 root root 4096 Jul 27 01:28 /root/.rustup
drwxr-xr-x 3 root root 4096 Jul 27 01:28 /root/.rustup/toolchains
8038181 lrwxrwxrwx 1 root root        6 Jul 27 01:28 /root/.cargo/bin/cargo -> rustup
8038191 lrwxrwxrwx 1 root root        6 Jul 27 01:28 /root/.cargo/bin/rustc -> rustup
8038194 -rwxr-xr-x 1 root root 20838840 Jul 27 01:28 /root/.cargo/bin/rustup
/root/.rustup/toolchains/1.88.0-x86_64-unknown-linux-gnu/bin/cargo
/root/.rustup/toolchains/1.88.0-x86_64-unknown-linux-gnu/bin/rustc
mapped HOME=</> CARGO_HOME=<> RUSTUP_HOME=<>
```

`Containerfile:11-12` explains the defaults: rustup is installed without
either home variable or a prefix, then `/root/.cargo/bin` is prepended to
`PATH`.

## 4. Ignored writable-HOME candidates

The directory-oriented generated/cache/output ignore classes are rooted
under the bind-mounted worktree, so their container forms are the
host-relative values below prefixed with `/src`. These are candidates only;
no selection is made here. Editor/OS/local-config rules and file-extension
artifact rules were not treated as HOME-directory classes. The destruction
columns follow the two literal `rm -rf build` commands at `Makefile:51` and
`Makefile:64-65`.

| Container-visible candidate | `git check-ignore -v` match | `ci-container` destroys it first? | `make clean` removes it? |
| --- | --- | --- | --- |
| `/src/build/.ci-home` | `.gitignore:8:build/` | Yes | Yes |
| `/src/component/env/.ci-home` | `.gitignore:2:*/env/*` | No | No |
| `/src/component/target/.ci-home` | `.gitignore:3:*/target/*` | No | No |
| `/src/component/build/.ci-home` | `.gitignore:8:build/` | No; only `/src/build` is removed | No |
| `/src/nv-attestation-sdk-rust/target/.ci-home` | `nv-attestation-sdk-rust/.gitignore:2:/target/` | No | No |
| `/src/ci_build_home` | `.gitignore:5:*_build*` | No | No |
| `/src/ci_repo/.ci-home` | `.gitignore:6:*_repo/` | No | No |
| `/src/build_docs/.ci-home` | `.gitignore:7:build_docs/` | No | No |
| `/src/node_modules/.ci-home` | `.gitignore:24:node_modules/` | No | No |
| `/src/.cache/attestation-sdk-ci-home` | `.gitignore:50:.cache/` | No | No |
| `/src/.cmake/.ci-home` | `.gitignore:28:.cmake/` | No | No |
| `/src/CMakeFiles/.ci-home` | `.gitignore:29:CMakeFiles/` | No | No |
| `/src/_obj/.ci-home` | `.gitignore:38:_obj` | No | No |
| `/src/out/.ci-home` | `.gitignore:41:out` | No | No |
| `/src/dist/.ci-home` | `.gitignore:42:dist` | No | No |
| `/src/generated/.ci-home` | `.gitignore:43:generated` | No | No |
| `/src/mocks/.ci-home` | `.gitignore:44:mocks` | No | No |
| `/src/reports/.ci-home` | `.gitignore:45:reports` | No | No |

The command output was:

```text
.gitignore:2:*/env/*	component/env/.ci-home/marker
.gitignore:3:*/target/*	component/target/.ci-home/marker
.gitignore:8:build/	component/build/.ci-home/marker
.gitignore:5:*_build*	ci_build_home/marker
.gitignore:6:*_repo/	ci_repo/.ci-home/marker
.gitignore:7:build_docs/	build_docs/.ci-home/marker
.gitignore:8:build/	build/.ci-home/marker
.gitignore:24:node_modules/	node_modules/.ci-home/marker
.gitignore:50:.cache/	.cache/attestation-sdk-ci-home/marker
.gitignore:28:.cmake/	.cmake/.ci-home/marker
.gitignore:29:CMakeFiles/	CMakeFiles/.ci-home/marker
.gitignore:38:_obj	_obj/.ci-home/marker
.gitignore:41:out	out/.ci-home/marker
.gitignore:42:dist	dist/.ci-home/marker
.gitignore:43:generated	generated/.ci-home/marker
.gitignore:44:mocks	mocks/.ci-home/marker
.gitignore:45:reports	reports/.ci-home/marker
```

The later unanchored `build/` rule at `.gitignore:8` is the effective match
for both root and nested `build` candidates; it supersedes the earlier
`*/build/*` match in `git check-ignore -v`. The duplicate `.cache/` rules at
lines 27 and 50 resolve to the later line 50. The Rust subtree has an
additional, more specific target rule:

```text
nv-attestation-sdk-rust/.gitignore:2:/target/	nv-attestation-sdk-rust/target/.ci-home/marker
```

Direct root paths `/src/.cargo` and `/src/.rustup` are not ignored:

```text
.cargo/marker: NOT IGNORED
.rustup/marker: NOT IGNORED
```

## 5. Live image environment and non-root probe

`docker image inspect attestation-sdk-ci` reported no configured `User`
(therefore image-default uid 0) and this exact `PATH`:

```text
PATH=/root/.cargo/bin:/opt/clang/bin:/opt/rh/gcc-toolset-14/root/usr/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
```

Its `Config.Env` contains neither `RUSTUP_HOME` nor `CARGO_HOME`.
`Containerfile:11-12` and the live proxy listing above agree with that
inspection.

The required read-only probe output, verbatim, was:

```text
$ docker run --rm --user "$(id -u):$(id -g)" attestation-sdk-ci sh -c 'id; ls -ld /root; command -v cargo rustc || echo UNREACHABLE'
uid=1001 gid=1001 groups=1001
dr-xr-x--- 1 root root 4096 Jul 27 01:28 /root
UNREACHABLE
```

This proves the current Docker `--user` path can start a process as the
operator uid but cannot discover either Rust proxy through `/root`.

## 6. Required baseline

The only build-related command run was the requested rail baseline through
`hop check`:

```text
$ hop check -n 500 -- make rail-test
hop check: `make rail-test` exited 0
python3 -m unittest discover -s sol/release/tests -p 'test_*.py'
...................................s.............................................-- The CXX compiler identification is GNU 13.3.0
-- Detecting CXX compiler ABI info
-- Detecting CXX compiler ABI info - done
-- Check for working CXX compiler: /usr/bin/c++ - skipped
-- Detecting CXX compile features
-- Detecting CXX compile features - done
-- ENGINE=3.31.10
-- Configuring incomplete, errors occurred!
..............................s.............................................
----------------------------------------------------------------------
Ran 157 tests in 18.616s

OK (skipped=2)
shellcheck $(find sol -type f -name '*.sh' -print | sort)
```

Exit status was 0; the baseline is green.

## 7. Test-surface conventions

* Runtime argument/mount tests use exported production constants in expected
  values. `test_mount_rendering_and_validation` builds its expected strings
  from `runtime.MOUNT_RW_SUFFIX` and `runtime.MOUNT_RO_SUFFIX`, rather than
  copying `"Z"` or `"ro,Z"` literals
  (`sol/release/tests/test_runtime.py:169-181`).
* CLI failures are tested through a real subprocess invocation of
  `sys.executable rail.py ...`, with `check=False`, followed by explicit
  assertions on exit status 2 and stderr
  (`sol/release/tests/test_authority.py:169-187`). This exercises
  `rail.main()`'s common exception-to-stderr/exit-2 path
  (`sol/release/rail.py:72-82,119-135`).
* Container command tests patch the subprocess runner, invoke the production
  closure, retrieve `run.call_args.args[0]`, and assert the selected runtime,
  platform, `runtime.LOCAL_IMAGE_TAG`, and
  `runtime.render_mount(...)` in the emitted argument vector
  (`sol/release/tests/test_driver.py:477-492`).
* Baseline stability names `targets.toml` and `authority.py` as guarded inputs
  (`sol/release/tests/test_baseline_stability.py:27-29`). The byte-identity
  assertion at lines 135-136 actually compares `targets.toml`; the following
  authority check preserves only the `TARGET_IDS` tuple
  (`test_baseline_stability.py:138-144`). Neither `Makefile` nor
  `sol/ci/Containerfile` is named or byte-guarded by this suite.
* The Cargo-lock assertion requires no tracked `Cargo.lock` and no untracked,
  non-ignored `Cargo.lock`
  (`sol/release/tests/test_baseline_stability.py:283-289`). Ignored locks are
  inventoried separately and are not required to be empty. `cargo_locks()`
  derives the three classes from Git and explicitly walks collapsed ignored
  directories (`sol/release/release_rail/inventory.py:35-86`). Therefore a
  Cargo lock beneath a genuinely ignored HOME is in the allowed `ignored`
  class; a root `.cargo/` home would instead violate the
  `untracked_non_ignored == ()` assertion.

## Additional observed blocker

The required rail tests pass, but the current stock-Docker host has a
separate live selector incompatibility:

```text
$ python3 sol/release/rail.py runtime select
release rail error: no usable OCI runtime: podman: command not found; install podman; docker: malformed response from docker version; recover by installing a working Podman or local Unix-socket Docker engine
```

`runtime.DOCKER_VERSION` uses literal tab characters in its format string
(`runtime.py:38-45`) and `_fields()` requires tab-separated fields
(`runtime.py:100-104`). With `/usr/bin/docker` 29.6.2, the captured value is
space-expanded instead:

```text
'Docker Engine - Community 29.6.2              Docker Engine - Community 29.6.2              linux               amd64'
```

`docker image inspect`, `docker run`, `docker info`, and
`docker context inspect` all succeeded, so this is selector parsing rather
than engine reachability. It was not modified or reproduced through
`make ci` because that command is explicitly prohibited in this prep stage.
