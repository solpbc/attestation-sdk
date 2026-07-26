# Three-target release rail prep

Research captured in the worktree
`/home/jer/.hopper/worktrees/6gey4qmd`. No product file was changed and no
build was run.

## Q0 — Workspace reality check

```text
$ pwd
/home/jer/.hopper/worktrees/6gey4qmd
$ git rev-parse --show-toplevel
/home/jer/.hopper/worktrees/6gey4qmd
$ git rev-parse --git-common-dir
/home/jer/projects/attestation-sdk/.git
$ test -e dist; echo $?
1
```

This proves that `dist/` is absent from this checkout and that the checkout
shares Git metadata, not ignored output, with the main checkout.

```text
$ ls -la /home/jer/projects/attestation-sdk/dist
total 7500
drwxr-xr-x. 1 jer jer     310 Jul 21 21:46 .
drwxr-xr-x. 1 jer jer     424 Jul 21 21:46 ..
-rw-r--r--. 1 jer jer    5631 Jul 21 21:46 libnvat-linux-x86_64-1.2.2-sol.1-archive.manifest.json
-rw-r--r--. 1 jer jer 7664136 Jul 21 21:46 libnvat-linux-x86_64-1.2.2-sol.1-archive.tar.xz
-rw-r--r--. 1 jer jer     114 Jul 21 21:46 libnvat-linux-x86_64-1.2.2-sol.1-archive.tar.xz.sha256

$ sha256sum /home/jer/projects/attestation-sdk/dist/*1.2.2-sol.1*
91d74edd1fd163670fe138353fc5b9ff7a540a9052c2453d6440c0917f4bc38d  /home/jer/projects/attestation-sdk/dist/libnvat-linux-x86_64-1.2.2-sol.1-archive.manifest.json
60ef75d1873e7129f03ea80d107d92b2ef216d2a8815958617b30d9c721d474a  /home/jer/projects/attestation-sdk/dist/libnvat-linux-x86_64-1.2.2-sol.1-archive.tar.xz
3c6a82975e5590fd410d382561c7b23f0493c997b9ebc71d5f4b3e576b6bd37d  /home/jer/projects/attestation-sdk/dist/libnvat-linux-x86_64-1.2.2-sol.1-archive.tar.xz.sha256
```

These are the untouched accepted baseline hashes for audit.

The stronger proposed statement that nothing in the rail writes outside
`$(git rev-parse --show-toplevel)` is **false**. The release driver obtains an
unqualified `mktemp -d` at `sol/release/release-linux-x86_64.sh:32`, then writes
its stage, extracted tree, copied gate tools, CA downloads, and dependency JSON
under that external temporary directory (`:37-55`, `:69-74`). It removes that
directory through its EXIT trap (`:33-36`). The only persistent outputs are
inside the worktree: the container build tree through the writable root mount
(`:26-30`) and `dist/` (`:39`, `:87-103`). The Git common directory is mounted
read-only (`:28`).

Therefore “do not overwrite `dist/*sol.1*`” is automatically satisfied by
running validation in this worktree: validation steps 3–5 will create a fresh
worktree-local `dist/`; the accepted `sol.1` files are in another checkout and
are neither mounted nor addressed. The design should describe the scope as
“no persistent release outputs outside the worktree,” not claim that the
driver performs no temporary writes outside it.

## Q1 — Image pins for aarch64

`skopeo` is not installed, while Podman is:

```text
$ command -v skopeo; echo skopeo_exit=$?
skopeo_exit=1
$ command -v podman; echo podman_exit=$?
/usr/bin/podman
podman_exit=0
$ podman --version
podman version 5.8.3
```

The working host command is `podman manifest inspect IMAGE`. Network access is
required: it reads remote registry manifests. All six manifest inspections
below exited 0, so resolution worked on this host.

The existing pins are not all the same object kind:

```text
$ podman manifest inspect \
    quay.io/pypa/manylinux_2_28_x86_64@sha256:a61875a2f84cab7df8de222ff12cabc08ff86eb4ad402ac90ba7bdaed9600cca
WARN[0000] The manifest type application/vnd.docker.distribution.manifest.v2+json is not a manifest list but a single image.
{
    "schemaVersion": 2,
    "mediaType": "application/vnd.docker.distribution.manifest.v2+json",
    "manifests": null
}
[exit 0]

$ podman manifest inspect \
    docker.io/library/fedora@sha256:6c75d5bf57cb0fa5aa4b92c6a83c86c791644496d9ac230de7711f5b8ec3b898
mediaType=application/vnd.oci.image.index.v1+json
manifests=8
[exit 0]

$ podman manifest inspect \
    docker.io/opensuse/tumbleweed@sha256:18a8c2a41252a0100ae4a7dae0a0e925fb522971645b97b05c57f9b6e73c3b4f
mediaType=application/vnd.docker.distribution.manifest.list.v2+json
manifests=8
[exit 0]
```

The manylinux pin is a single Docker v2 image manifest. Fetching its config
blob through the Quay v2 API reports `architecture=amd64`, `os=linux`, proving
it resolves to one architecture. The Fedora pin is an OCI index and the
Tumbleweed pin is a Docker manifest list; neither pin itself has an
architecture.

At capture time, inspecting the three requested tags produced these genuine
arm64 platform manifests:

```text
$ podman manifest inspect quay.io/pypa/manylinux_2_28_aarch64:latest
mediaType=application/vnd.docker.distribution.manifest.v2+json
[exit 0]

$ curl -sS -D headers -o manifest \
    -H 'Accept: application/vnd.docker.distribution.manifest.v2+json' \
    https://quay.io/v2/pypa/manylinux_2_28_aarch64/manifests/latest
docker-content-digest: sha256:e7035406e58d96b7407246af1f6514a3cbd753a0025b42b9adfbeadd3b29ba80
[exit 0]
$ # Fetch manifest["config"]["digest"] from /blobs/... and inspect the JSON.
architecture=arm64
os=linux
[exit 0]

$ podman manifest inspect docker.io/library/fedora:latest
mediaType=application/vnd.oci.image.index.v1+json
arm64 v8 sha256:a471bd8bf8e7e99812fd2f29fc950685d860b3d528b9f090443dbc1a0d2bad62 application/vnd.oci.image.manifest.v1+json
[exit 0]

$ podman manifest inspect docker.io/opensuse/tumbleweed:latest
mediaType=application/vnd.docker.distribution.manifest.list.v2+json
arm64 v8 sha256:dc90443ab117e6887a4184d772259b84b3e9e54f6333c3331a42c97fdefd601d application/vnd.docker.distribution.manifest.v2+json
[exit 0]
```

Directly fetching each Docker Hub child manifest and its config blob with a
registry bearer token independently proved:

```text
library/fedora manifest_exit=0
mediaType=application/vnd.oci.image.manifest.v1+json
library/fedora config_exit=0
architecture=arm64
os=linux
opensuse/tumbleweed manifest_exit=0
mediaType=application/vnd.docker.distribution.manifest.v2+json
opensuse/tumbleweed config_exit=0
architecture=arm64
os=linux
```

Resolved per-architecture candidates are therefore:

* manylinux aarch64:
  `sha256:e7035406e58d96b7407246af1f6514a3cbd753a0025b42b9adfbeadd3b29ba80`
* Fedora arm64:
  `sha256:a471bd8bf8e7e99812fd2f29fc950685d860b3d528b9f090443dbc1a0d2bad62`
* Tumbleweed arm64:
  `sha256:dc90443ab117e6887a4184d772259b84b3e9e54f6333c3331a42c97fdefd601d`

There is a design contradiction to resolve: the manylinux aarch64 candidate is
the same kind as its existing pin (single platform manifest), but the Fedora
and Tumbleweed arm64 candidates are necessarily child manifests and therefore
not the same kind as their existing multi-arch index pins. Keeping the bare
pins' current kind means pinning the same architecture-neutral index for both
targets and relying on `--platform`; it does not yield a per-architecture
digest. The clean uniform convention is to migrate **both** x86_64 and arm64
bare-image pins to their platform child digests. Tags are mutable, so the three
captured candidates must be re-resolved/reconfirmed immediately before design
locks them.

## Q2 — Reading foreign binaries and gating Mach-O

The host GNU binutils read a real Ubuntu arm64 glibc loader downloaded from
`ports.ubuntu.com`:

```text
$ readelf --version | head -1
GNU readelf (GNU Binutils; openSUSE Tumbleweed) 2.45.0.20251103-4
$ readelf -h /tmp/tri-libc6-root/usr/lib/ld-linux-aarch64.so.1 |
    grep -E 'Class:|Data:|Machine:'
  Class:                             ELF64
  Data:                              2's complement, little endian
  Machine:                           AArch64
[exit 0]
$ strings /tmp/tri-libc6-root/usr/lib/ld-linux-aarch64.so.1 > strings.txt
[exit 0]
$ readelf -d /tmp/tri-libc6-root/usr/lib/ld-linux-aarch64.so.1 |
    grep 'SONAME'
 0x000000000000000e (SONAME)             Library soname: [ld-linux-aarch64.so.1]
[exit 0]
$ readelf -h /bin/ls | grep 'Machine:'
  Machine:                           Advanced Micro Devices X86-64
[exit 0]
```

Thus ELF architecture identity is the `Machine:` field: GNU readelf prints
`Advanced Micro Devices X86-64` for x86-64 and `AArch64` for arm64. The
aarch64 glibc loader's verified DT_SONAME is `ld-linux-aarch64.so.1`.
`strings` is architecture-independent byte scanning and exited 0 on that file.

No Apple binary tools are installed:

```text
$ command -v otool; echo "otool exit=$?"
otool exit=1
$ command -v lipo; echo "lipo exit=$?"
lipo exit=1
$ command -v llvm-objdump; echo "llvm-objdump exit=$?"
llvm-objdump exit=1
$ command -v codesign; echo "codesign exit=$?"
codesign exit=1
$ command -v install_name_tool; echo "install_name_tool exit=$?"
install_name_tool exit=1
```

A pure-Python Mach-O gate must parse the following, bounds-checking every
header, slice, command, `cmdsize`, and NUL-terminated string:

* Thin 64-bit header: `MH_MAGIC_64=0xfeedfacf` (and byte-swapped
  `MH_CIGAM_64=0xcffaedfe`). `mach_header_64` is 32 bytes: `magic` offset 0,
  `cputype` 4, `cpusubtype` 8, `filetype` 12, `ncmds` 16, `sizeofcmds` 20,
  `flags` 24, `reserved` 28. Require
  `CPU_TYPE_ARM64=0x0100000c`; compare the low 24 subtype bits after masking
  capability bits. `CPU_SUBTYPE_ARM64_ALL=0`; `CPU_SUBTYPE_ARM64E=2` should be
  an explicit policy choice, not accidentally accepted.
* Universal input: `FAT_MAGIC=0xcafebabe`, `FAT_CIGAM=0xbebafeca`,
  `FAT_MAGIC_64=0xcafebabf`, `FAT_CIGAM_64=0xbfbafeca`; `fat_header` is
  big-endian `magic,nfat_arch`. Each 32-bit `fat_arch` is 20 bytes
  (`cputype,cpusubtype,offset,size,align` at 0,4,8,12,16); `fat_arch_64` is 32
  bytes (`cputype,cpusubtype` at 0,4, 64-bit `offset,size` at 8,16, then
  `align,reserved` at 24,28). A target-specific artifact should reject a fat
  binary explicitly. If universal binaries are permitted instead, the parser
  must locate and fully validate the arm64 slice; treating a fat header as a
  thin header is never valid.
* Deployment target: `LC_BUILD_VERSION=0x32`; its fields after
  `cmd,cmdsize` are `platform` offset 8, `minos` 12, `sdk` 16, `ntools` 20.
  Decode packed versions as major=`v>>16`, minor=`(v>>8)&0xff`,
  patch=`v&0xff`. Also support legacy
  `LC_VERSION_MIN_MACOSX=0x24` (`version` offset 8, `sdk` 12), because valid
  older-build-tool Mach-O files may omit `LC_BUILD_VERSION`; the gate must
  reject a binary with neither command.
* Runtime references: `LC_LOAD_DYLIB=0x0c`, `LC_ID_DYLIB=0x0d`, and
  `LC_RPATH=LC_REQ_DYLD|0x1c=0x8000001c`. In `dylib_command`,
  `dylib.name.offset` is at command offset 8 (then timestamp/current/
  compatibility versions at 12/16/20). In `rpath_command`,
  `path.offset` is likewise at 8. `lc_str` is an offset from the start of its
  containing load command, not a file-global offset. For a complete runtime
  allowlist, also treat `LC_LOAD_WEAK_DYLIB=0x80000018`,
  `LC_REEXPORT_DYLIB=0x8000001f`, `LC_LAZY_LOAD_DYLIB=0x20`, and
  `LC_LOAD_UPWARD_DYLIB=0x80000023` as dependency-bearing commands.

Python's standard-library `struct` module can decode all of these fixed-width,
endian-aware fields; normal `bytes` operations can bound and terminate the
strings. No third-party package is implied. Signature validation or mutation
would require more, but neither is part of the proposed read-only gate.

## Q3 — macOS/aarch64 build portability risks

### Blocking for native build

* **OpenSSL target selection.** The vendored branch invokes
  `<SOURCE_DIR>/Configure` with `CC=...` and flags but passes no OpenSSL target
  string (`nv-attestation-sdk-cpp/CMakeLists.txt:185-201`). A controlled arm64
  build needs `darwin64-arm64-cc` on macOS or `linux-aarch64` on Linux. Native
  auto-detection may work, but it is not an explicit/pinned target and
  cross-compilation cannot rely on it.
* **Autoconf cross/native assumptions.** libxml2 (`:226-245`), xmlsec
  (`:250-273`), and curl (`:280-306`) pass `CC`/`CFLAGS` but no
  `--build`/`--host`. This blocks a Linux-hosted Apple or aarch64 Linux cross
  build when configure tests try to execute target programs. For Apple clang,
  the design must use a real Apple SDK/sysroot and a coherent
  `--host=aarch64-apple-darwin`; `--with-openssl`/`--with-libxml` and the
  hand-built `PKG_CONFIG_PATH` must be verified against Darwin static archives.
  The curl `--with-ca-fallback` plus `--without-ca-bundle`/
  `--without-ca-path` combination (`:284-302`) is also platform-sensitive.
* **Linux library/link assumptions.** Vendored OpenSSL advertises
  `"dl;pthread"` (`:209-220`) and curl advertises
  `"OpenSSL::SSL;OpenSSL::Crypto;z;pthread"` (`:311-316`). Darwin has pthread
  APIs but no separate Linux `libdl`; blindly emitting `-ldl` is a native link
  blocker. The repository contains no explicit `-Wl,--exclude-libs`,
  `-Wl,-soname`, or version-script flag, but generated dependency build systems
  still need checking for GNU-ld-only output.
* **Rust target propagation.** Corrosion is fetched and imports regorus as a
  Rust staticlib (`:40-62`), but the project sets no Rust/Cargo target triple;
  only an optional `RUSTC_WRAPPER` is set (`:64-66`). The required triples are
  `aarch64-apple-darwin` and `aarch64-unknown-linux-gnu`. Corrosion currently
  infers the target from CMake/toolchain state, so each toolchain must prove
  that mapping and have the Rust target installed.
* **No Apple toolchain on this host.** Q2 proves the host lacks even inspection
  utilities, and there is no Apple SDK/toolchain in the inspected build
  configuration. Consequently an `aarch64-apple-darwin` native artifact cannot
  be produced on this Linux host by the current rail.

### Informational, but must be verified

* Warning flags are `-Wall -Wextra -Wpedantic -pedantic`, with `-Werror` when
  CMake is older than 3.24 and warning-as-error is enabled
  (`nv-attestation-sdk-cpp/CMakeLists.txt:328-334`);
  `nv-attestation-cli/CMakeLists.txt:7-8` enables the CMake warning-as-error
  property. The GoogleTest helper has a Clang-specific exemption
  (`nv-attestation-sdk-cpp/cmake/nvat_fetch_gtest.cmake:17-22`).
  `-ffile-prefix-map` is enabled for both GNU and Clang
  (`nv-attestation-sdk-cpp/CMakeLists.txt:341-344`) and is accepted by modern
  Apple clang, but the selected Apple clang version must confirm it.
* `VERSION=1.2.2` and `SOVERSION=1` are properties on `nvat`
  (`nv-attestation-sdk-cpp/CMakeLists.txt:381-385`). CMake's Darwin shared
  library rules automatically produce the platform spelling and symlink chain
  `libnvat.1.2.2.dylib`, `libnvat.1.dylib`, `libnvat.dylib` rather than
  Linux's `libnvat.so.1.2.2`, `.so.1`, `.so`; the release staging member names,
  not these properties, need target-specific handling.
* NVML, corelib, and NSCQ dynamically open Linux names
  `libnvidia-ml.so.1`, `libcorelib.so.1`, and `libnvidia-nscq.so.2`
  (`nv-attestation-sdk-cpp/src/gpu/nvml_client.cpp:191-194`,
  `gpu/corelib_client.cpp:197-200`,
  `switch/nscq_client.cpp:172-175`). Those opens fail on Darwin if hardware
  collection is selected. They are lazy: JSON file sources deserialize and
  return evidence without initializing those clients
  (`gpu/evidence.cpp:648-699`, `switch/evidence.cpp:475-525`), while hardware
  collectors initialize them only in their `get_evidence` paths
  (`gpu/evidence.cpp:177-205`, `switch/evidence.cpp:174-182`). SDK init itself
  initializes logging/xmlsec, not the device clients (`src/init.cpp:121-140`).
  Thus the file-evidence + local-verifier product path is genuinely isolated
  from these `dlopen`s, although hardware collection is unsupported on Darwin.
* `find_package(ZLIB REQUIRED)` is unconditional
  (`nv-attestation-sdk-cpp/CMakeLists.txt:326`), and `nvat` links
  `ZLIB::ZLIB` (`:425-442`). macOS SDKs provide libz, so it need not be
  vendored, but a Mach-O runtime allowlist must permit the SDK's recorded
  install name (normally `/usr/lib/libz.1.dylib`), not the Linux `libz.so.1`
  spelling.

For `aarch64-unknown-linux-gnu`, the same explicit OpenSSL target,
Autoconf `--build/--host`, and Corrosion target propagation are blocking when
cross-building; they become verification items for a native aarch64 container.
The warning and prefix-map flags are portable to GCC/Clang, CMake retains the
ELF `VERSION`/`SOVERSION` naming, and the existing Linux device-library names
remain appropriate.

## Q4 — Determinism

The driver uses:

```text
tar --sort=name --mtime="@$source_date_epoch" --owner=0 --group=0 --numeric-owner \
  -C "$stage" -cJf "$archive" "${members[@]}"
sha256sum "$archive"
```

GNU tar's `--sort=name` has no BSD/Apple tar equivalent. Apple/BSD tar also
does not provide GNU tar's exact `--mtime=@EPOCH`, `--owner=0`, `--group=0`,
and `--numeric-owner` creation semantics/flag set; analogous bsdtar options do
not make this command byte-compatible because header format, metadata
normalization, and traversal differ. `-c`, `-f`, and `-C` are portable; `-J`
depends on xz support in the tar build and is not a safe Apple-base-userland
assumption. `sha256sum` is GNU coreutils and is absent from stock macOS, whose
usual command is `shasum -a 256` (or `openssl dgst -sha256`); the digest
algorithm is identical, but sidecar formatting differs unless the rail writes
it itself. `xz` is also not a stock macOS command.

Acceptance criterion 7 narrowly requires two fixture builds from identical
source and complete pinned inputs, for each target, to produce byte-identical
archives and sidecars. It does **not** require Linux and macOS archive
implementations, or two different host operating systems, to emit identical
bytes. The defensible claim is **same target, same controlled host/tool image,
twice**. The rail should not claim cross-host byte identity without pinning one
archive implementation and compression implementation across hosts.

xz output can vary with compression level and threading; in particular `-T0`
or another multithread setting may choose block boundaries based on available
resources, changing bytes. The present `tar -cJf` supplies no xz options and
GNU tar's xz filter defaults to single-threaded compression, so it is not
currently exposed to `-T` variability. The future driver should keep that
explicit (for example fixed xz level and `-T1`) rather than inherit
environmental `XZ_OPT`.

## Q5 — Test placement and `make ci`

Host Python is usable, but Python 3.13's discover command returns 5 when the
fixture contains no tests:

```text
$ python3 --version
Python 3.13.13
$ python3 -m unittest discover -s /tmp/tri-empty-tests

----------------------------------------------------------------------
Ran 0 tests in 0.000s

NO TESTS RAN
unittest_exit=5
```

This proves the unittest runner/discovery path works and also forecloses using
an empty directory as a green smoke check. Real rail tests containing at least
one `unittest.TestCase` are required.

Today `ci: image` (`Makefile:35`), so any recipe added directly under `ci`
cannot run before its prerequisite image build. The smallest wiring is a
standalone phony `rail-test` target running
`python3 -m unittest discover ...`, followed by `ci: rail-test image` (or an
explicit recursive/recipe ordering if strict sequencing before `image` is
required). `rail-test` remains directly runnable without Podman; `ci` retains
the existing container phase (`Makefile:35-41`). GNU make does not guarantee
left-to-right prerequisite execution under parallel make, so “before” should
not rely solely on prerequisite spelling if that ordering is a requirement.

The requested shellcheck baseline is **not clean**:

```text
$ shellcheck --version
ShellCheck - shell script analysis tool
version: 0.11.0
[exit 0]
$ shellcheck sol/release/*.sh sol/*.sh
sol/release/gate-artifact.sh:16:56: info: Expansions inside ${..} need to be quoted separately [SC2295]
...same SC2295 at lines 21, 26, 32, 40, 54, 60, and 64...
sol/release/release-linux-x86_64.sh:12:8: info: Not following: sol/release/release.env was not specified as input [SC1091]
sol/release/release-linux-x86_64.sh:169:4: warning: You probably wanted && here, otherwise it's always true [SC2055]
shellcheck_exit=1
```

SC2055 is material: it flags the multiline `[[ ... || ... ]]` consistency
condition at `release-linux-x86_64.sh:168-172`. Design must include resolving
the existing baseline or narrowly configuring the lint invocation; it cannot
claim current cleanliness.

Podman and Quay registry reachability are available without performing a build:

```text
$ podman --version
podman version 5.8.3
$ podman manifest inspect quay.io/pypa/manylinux_2_28_aarch64:latest
[exit 0]
$ curl -sS -o /dev/null -w 'quay_http=%{http_code}\n' https://quay.io/v2/
quay_http=401
quay_curl_exit=0
```

The expected unauthenticated v2 challenge plus successful manifest inspection
proves DNS/TLS/registry reachability needed by `make image`. It does not prove
that every Containerfile download will remain available or that a full image
build succeeds; no image build was run.

## Q6 — Existing-guarantee inventory

The x86_64 preserve-everything contract is:

* clean Git worktree including untracked files
  (`sol/release/release-linux-x86_64.sh:4-10`);
* version derived from the SDK project version and suffixed with the configured
  Sol revision (`:14-21`);
* commit timestamp captured as `SOURCE_DATE_EPOCH` input and absolute shared
  Git directory mounted read-only (`:21-30`);
* curl easy-handle site guard before building (`:24`);
* clean release build, vendored dependencies, tests off, shared `nvat`, Release
  mode, inside the pinned CI image (`:26-30`; image pin is supplied by
  `Makefile:32-33`);
* host-independent gate tools copied from the CI image together with their
  non-baseline runtime libraries (`:41-52`);
* both the downloaded CA payload hash **and** curl's published sidecar hash
  equal the pinned hash; either mismatch fails (`:54-62`);
* staged executable, two symlinks, versioned regular library, license, CA
  snapshot, and generated third-party notices (`:64-74`);
* every listed binary is readable ELF; inability to read its dynamic section
  fails (`sol/release/gate-artifact.sh:7-18`);
* an empty DT_NEEDED set fails, and every needed SONAME must be an exact member
  of the allowlist (`gate-artifact.sh:19-29`);
* symbol-version parsing errors fail and GLIBC, GLIBCXX, and CXXABI requirements
  may not exceed 2.28, 3.4.25, and 1.3.11 respectively (`:31-57`);
* strings extraction errors fail, as do compiled-in Debian or Fedora host CA
  paths (`:59-66`);
* one ordered `members` array is the archive input (`release-linux-x86_64.sh:
  78-89`) and is also passed, in order, to the manifest generator (`:96-112`);
* GNU tar sorts names and normalizes mtime, uid, gid, and numeric-owner output
  before xz compression; the produced archive is extracted afresh for gates
  (`:87-90`);
* archive SHA-256 drives both the checksum sidecar and manifest artifact hash
  (`:92-112`);
* both pinned bare images rerun the ELF gate, execute `nvattest --help`, and
  require a missing authoritative CA path to fail while naming the path and
  `--ca-bundle` tier (`:114-135`);
* bare-image layout asserts regular files for LICENSE, executable, CA, notices,
  and the fully versioned library, but symlinks specifically for
  `lib/libnvat.so` and `lib/libnvat.so.1` (`:136-142`);
* exact per-directory entry counts are root=4, bin=1, lib=3, share=2,
  share/ca=1 (`:143-147`);
* each bare image independently recomputes the archive hash and requires it to
  equal both sidecar and manifest hashes (`:149-155`);
* the manifest generator records `git merge-base main HEAD`, the ordered commit
  series from that base, dependency pins, CI image, CA provenance,
  `SOURCE_DATE_EPOCH`, and ordered members
  (`sol/release/generate-manifest.py:28-56`);
* the final host gate recomputes `git merge-base main HEAD` and the ordered
  commit series, and compares artifact, sidecar, manifest base, manifest series,
  and ordered members (`release-linux-x86_64.sh:161-175`).

### Open questions for design

* Should all Fedora/Tumbleweed pins migrate from index digests to platform-child
  digests, or should “per-architecture digest” be relaxed for bare images?
* Are target-specific macOS archives required to reject universal Mach-O files,
  or may they contain a validated arm64 slice plus other architectures?
* Which controlled macOS builder supplies the licensed Apple SDK/toolchain?
* Is arm64 Linux built natively in an aarch64 container/runner or crossed from
  x86_64? That decides whether explicit Autoconf and Rust cross plumbing is
  mandatory in the first implementation.
* Should current ShellCheck findings be fixed as part of the rail rewrite or
  recorded as an accepted, narrowly suppressed baseline?

## Mutation proof: aarch64 policy must reject x86_64 ELF

After the static-gate suite was green, the `EM_AARCH64` policy mapping was
temporarily changed from `elf.EM_AARCH64` to `elf.EM_X86_64`. The complete
focused suite then produced:

```text
$ hop check -n 120 -- python3 -m unittest discover -s sol/release/tests -p 'test_*.py'
hop check: `python3 -m unittest discover -s sol/release/tests -p test_*.py` exited 1
...........EF............
======================================================================
ERROR: test_each_elf_architecture_accepts_its_own_and_rejects_the_other (test_gate.GateTest.test_each_elf_architecture_accepts_its_own_and_rejects_the_other) (target='linux-aarch64', state='native')
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/home/jer/.hopper/worktrees/6gey4qmd/sol/release/tests/test_gate.py", line 41, in test_each_elf_architecture_accepts_its_own_and_rejects_the_other
    gate.gate_file(
    ~~~~~~~~~~~~~~^
        self.write(target_id, fixtures.elf_fixture(native)),
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
        target,
        ^^^^^^^
        allowlist,
        ^^^^^^^^^^
    )
    ^
  File "/home/jer/.hopper/worktrees/6gey4qmd/sol/release/release_rail/gate.py", line 126, in gate_file
    gate_elf(path, target, allowlist)
    ~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/jer/.hopper/worktrees/6gey4qmd/sol/release/release_rail/gate.py", line 38, in gate_elf
    raise GateError(
    ...<2 lines>...
    )
release_rail.gate.GateError: /tmp/tmpllcdy58a/linux-aarch64: wrong ELF architecture: expected EM_AARCH64 (62), got e_machine=183

======================================================================
FAIL: test_each_elf_architecture_accepts_its_own_and_rejects_the_other (test_gate.GateTest.test_each_elf_architecture_accepts_its_own_and_rejects_the_other) (target='linux-aarch64', state='foreign')
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/home/jer/.hopper/worktrees/6gey4qmd/sol/release/tests/test_gate.py", line 47, in test_each_elf_architecture_accepts_its_own_and_rejects_the_other
    with self.assertRaisesRegex(gate.GateError, "wrong ELF architecture"):
         ~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
AssertionError: GateError not raised

----------------------------------------------------------------------
Ran 24 tests in 0.044s

FAILED (failures=1, errors=1)
mutation_exit=1
```

The mutation command exited 1. The mutation was immediately reverted. This
proves the suite rejects the precise architecture defect: an aarch64 gate that
accepts an x86_64 ELF (and, as the paired assertion shows, rejects its native
AArch64 ELF).

## Native validation

This validation ran on the lode's native Linux x86_64 host. It does not provide
native execution evidence for Linux aarch64 or macOS arm64.

### Image and real release

```text
$ hop check -n 120 -- make image
Successfully tagged localhost/attestation-sdk-ci:latest
hop check: `make image` exited 0

$ hop check -n 260 -- make release TARGET=linux-x86_64
--ca-bundle: CA bundle path '/nonexistent/path' from --ca-bundle does not exist or is not readable; provide a readable file with --ca-bundle or NVAT_CA_BUNDLE.
Run with --help for more information.
runtime, layout, and quartet hash gates passed
--ca-bundle: CA bundle path '/nonexistent/path' from --ca-bundle does not exist or is not readable; provide a readable file with --ca-bundle or NVAT_CA_BUNDLE.
Run with --help for more information.
runtime, layout, and quartet hash gates passed
/home/jer/.hopper/worktrees/6gey4qmd/dist/libnvat-linux-x86_64-1.2.2-sol.2-archive.tar.xz
/home/jer/.hopper/worktrees/6gey4qmd/dist/libnvat-linux-x86_64-1.2.2-sol.2-archive.tar.xz.sha256
/home/jer/.hopper/worktrees/6gey4qmd/dist/libnvat-linux-x86_64-1.2.2-sol.2-archive.manifest.json
/home/jer/.hopper/worktrees/6gey4qmd/dist/libnvat-linux-x86_64-1.2.2-sol.2-archive.manifest.json.sha256
hop check: `make release TARGET=linux-x86_64` exited 0
```

This proves both child-digest bare images executed the runtime, layout, eager
CA failure, and independent quartet-hash gates. The first attempts exposed that
the runtime gate assumed `find`, then `awk`, existed in the minimal Tumbleweed
image. Commits `d4a0344` and `1780d28` removed those assumptions.

The real schema-v2 manifest reported:

```text
schema_version=2
release.version=1.2.2-sol.2
release.sol_revision=2
source.commit=1780d281c24bd0d7d0450157c2e6cb321807a2ba
source.upstream_base_commit=73c032ebff680ca6d2ba06f4006b511491b71ce9
source.source_date_epoch=1785090113
artifact.name=libnvat-linux-x86_64-1.2.2-sol.2-archive.tar.xz
artifact.size=7655164
artifact.sha256=3ba6b614730edb1b21872cbb31c461d2af7c5ed413629e144bc546461487058f
build_tools.compiler=GCC 14.2.1
build_tools.cmake=cmake 4.4.0
build_tools.rustc=rustc 1.88.0
build_tools.cargo=cargo 1.88.0
build_tools.tar=GNU tar 1.35
build_tools.xz=xz 5.8.3
build_tools.python=CPython 3.13.13
```

The full manifest also contained the ordered archive-member inventory, twelve
dependency pins, the exact build and gate image references, CA snapshot, xz
settings, and ordered Sol commit series. No normalized tool value contained an
absolute path, host name, build date, or Rust commit hash. This proves real
construction populated every schema-v2 section without host-specific tool
evidence.

### Overwrite refusal and reproducibility

The original overwrite error had a traceback and no recovery command. After
that defect was fixed, the retained quartet failed closed with:

```text
$ hop check -n 60 -- make release TARGET=linux-x86_64
hop check: `make release TARGET=linux-x86_64` exited 2
release rail error: promotion refuses to overwrite: /home/jer/.hopper/worktrees/6gey4qmd/dist/libnvat-linux-x86_64-1.2.2-sol.2-archive.tar.xz; move the existing quartet aside with `mkdir -p /home/jer/.hopper/worktrees/6gey4qmd/dist/retained-linux-x86_64-1.2.2-sol.2 && mv /home/jer/.hopper/worktrees/6gey4qmd/dist/libnvat-linux-x86_64-1.2.2-sol.2-archive.tar.xz /home/jer/.hopper/worktrees/6gey4qmd/dist/libnvat-linux-x86_64-1.2.2-sol.2-archive.tar.xz.sha256 /home/jer/.hopper/worktrees/6gey4qmd/dist/libnvat-linux-x86_64-1.2.2-sol.2-archive.manifest.json /home/jer/.hopper/worktrees/6gey4qmd/dist/libnvat-linux-x86_64-1.2.2-sol.2-archive.manifest.json.sha256 /home/jer/.hopper/worktrees/6gey4qmd/dist/retained-linux-x86_64-1.2.2-sol.2`, then retry
```

The first real double construction then exposed OpenSSL's wall-clock
`built on:` string in `libnvat.so`. The source-epoch fix exports the commit
epoch as `SOURCE_DATE_EPOCH`. Two subsequent full builds from that identical
clean commit produced:

```text
$ sha256sum run-a/* run-b/*
2563ec704332eddfd37cc6565b9ab2b7e9549e6f03ecee5b5e57a7219b84eda7  run-a/libnvat-linux-x86_64-1.2.2-sol.2-archive.manifest.json
d605a30502f193bcb72e00a9f36f859b33c6edd9f517fff12fa8f2cfe54b85d9  run-a/libnvat-linux-x86_64-1.2.2-sol.2-archive.manifest.json.sha256
df1589ef2edfe9ba4061e86b2381c67d89f16efc38ddd9b137ac94d232d07f37  run-a/libnvat-linux-x86_64-1.2.2-sol.2-archive.tar.xz
158e9aa68a61e39a25d6403a3cb5c904c8c9597c1035e5f6722cddc4017b5dc2  run-a/libnvat-linux-x86_64-1.2.2-sol.2-archive.tar.xz.sha256
2563ec704332eddfd37cc6565b9ab2b7e9549e6f03ecee5b5e57a7219b84eda7  run-b/libnvat-linux-x86_64-1.2.2-sol.2-archive.manifest.json
d605a30502f193bcb72e00a9f36f859b33c6edd9f517fff12fa8f2cfe54b85d9  run-b/libnvat-linux-x86_64-1.2.2-sol.2-archive.manifest.json.sha256
df1589ef2edfe9ba4061e86b2381c67d89f16efc38ddd9b137ac94d232d07f37  run-b/libnvat-linux-x86_64-1.2.2-sol.2-archive.tar.xz
158e9aa68a61e39a25d6403a3cb5c904c8c9597c1035e5f6722cddc4017b5dc2  run-b/libnvat-linux-x86_64-1.2.2-sol.2-archive.tar.xz.sha256
all four quartet files are byte-identical
```

This proves the narrow same-target, same-host, same-pinned-toolchain
reproducibility claim for the only native target available here.

### Complete-set validator

With only the real x86_64 quartet present:

```text
$ hop check -n 60 -- python3 sol/release/rail.py validate-set
hop check: `python3 sol/release/rail.py validate-set` exited 2
release rail error: missing target: linux-aarch64; missing target: macos-arm64
```

Synthesized aarch64 and macOS fixture quartets completed the set. The validator
accepted it, then rejected each rehashed manifest mutation:

```text
$ python3 sol/release/rail.py validate-set
complete release set validated: 1.2.2-sol.2

$ hop check -n 60 -- python3 sol/release/rail.py validate-set
hop check: `python3 sol/release/rail.py validate-set` exited 2
release rail error: cross-target mismatch: release.sol_revision: linux-x86_64=2, linux-aarch64=99, macos-arm64=2

$ hop check -n 60 -- python3 sol/release/rail.py validate-set
hop check: `python3 sol/release/rail.py validate-set` exited 2
release rail error: cross-target mismatch: source.upstream_base_commit: linux-x86_64="73c032ebff680ca6d2ba06f4006b511491b71ce9", linux-aarch64="73c032ebff680ca6d2ba06f4006b511491b71ce9", macos-arm64="ffffffffffffffffffffffffffffffffffffffff"

$ hop check -n 60 -- python3 sol/release/rail.py validate-set
hop check: `python3 sol/release/rail.py validate-set` exited 2
release rail error: cross-target mismatch: source.source_date_epoch: linux-x86_64=1785090636, linux-aarch64=1785090637, macos-arm64=1785090636
```

This proves complete-set discovery and the three required shared-identity
comparisons fail closed. The synthesized foreign-target fixtures were removed
afterward.

### Full gate and retained baseline

```text
$ hop check -n 240 -- make ci
100% tests passed out of 64
hop check: `make ci` exited 0
```

The full gate passed all 64 enabled C++ tests (four network tests remained
disabled by the existing CI subset) and all release-rail tests. Static
ShellCheck also exited 0.

Finally, the accepted `sol.1` files in the separate checkout remained
byte-identical to the Q0 baseline:

```text
$ sha256sum /home/jer/projects/attestation-sdk/dist/libnvat-linux-x86_64-1.2.2-sol.1-archive.manifest.json /home/jer/projects/attestation-sdk/dist/libnvat-linux-x86_64-1.2.2-sol.1-archive.tar.xz /home/jer/projects/attestation-sdk/dist/libnvat-linux-x86_64-1.2.2-sol.1-archive.tar.xz.sha256
91d74edd1fd163670fe138353fc5b9ff7a540a9052c2453d6440c0917f4bc38d  /home/jer/projects/attestation-sdk/dist/libnvat-linux-x86_64-1.2.2-sol.1-archive.manifest.json
60ef75d1873e7129f03ea80d107d92b2ef216d2a8815958617b30d9c721d474a  /home/jer/projects/attestation-sdk/dist/libnvat-linux-x86_64-1.2.2-sol.1-archive.tar.xz
3c6a82975e5590fd410d382561c7b23f0493c997b9ebc71d5f4b3e576b6bd37d  /home/jer/projects/attestation-sdk/dist/libnvat-linux-x86_64-1.2.2-sol.1-archive.tar.xz.sha256
```

This proves the validation did not change the accepted baseline in the other
checkout.

### Post-remediation native x86_64 re-run

The audit remediation changed the runtime directory counter and quartet
promotion primitive. Both paths were exercised again from clean commit
`89029eae58fbb474375ea3a373681d32cf1cee55`.

```text
$ hop check -n 260 -- make release TARGET=linux-x86_64
--ca-bundle: CA bundle path '/nonexistent/path' from --ca-bundle does not exist or is not readable; provide a readable file with --ca-bundle or NVAT_CA_BUNDLE.
Run with --help for more information.
runtime, layout, and quartet hash gates passed
--ca-bundle: CA bundle path '/nonexistent/path' from --ca-bundle does not exist or is not readable; provide a readable file with --ca-bundle or NVAT_CA_BUNDLE.
Run with --help for more information.
runtime, layout, and quartet hash gates passed
/home/jer/.hopper/worktrees/6gey4qmd/dist/libnvat-linux-x86_64-1.2.2-sol.2-archive.tar.xz
/home/jer/.hopper/worktrees/6gey4qmd/dist/libnvat-linux-x86_64-1.2.2-sol.2-archive.tar.xz.sha256
/home/jer/.hopper/worktrees/6gey4qmd/dist/libnvat-linux-x86_64-1.2.2-sol.2-archive.manifest.json
/home/jer/.hopper/worktrees/6gey4qmd/dist/libnvat-linux-x86_64-1.2.2-sol.2-archive.manifest.json.sha256
hop check: `make release TARGET=linux-x86_64` exited 0, showing last 260 of 2859 lines
```

The two identical success blocks are the Fedora and Tumbleweed child-digest
runtime gates. Each ran the new hidden-aware count loop before printing its
success line. This proves the exact visible layout still passes in both minimal
images and the preserved eager CA-path evidence still names both the path and
the `--ca-bundle` tier.

The promoted quartet consisted only of ordinary files with link count one, and
no file with link count greater than one remained under owned staging:

```text
$ stat -c '%h %F %n' dist/libnvat-linux-x86_64-1.2.2-sol.2-*
1 regular file dist/libnvat-linux-x86_64-1.2.2-sol.2-archive.manifest.json
1 regular file dist/libnvat-linux-x86_64-1.2.2-sol.2-archive.manifest.json.sha256
1 regular file dist/libnvat-linux-x86_64-1.2.2-sol.2-archive.tar.xz
1 regular file dist/libnvat-linux-x86_64-1.2.2-sol.2-archive.tar.xz.sha256

$ find dist/.staging -maxdepth 3 -type f -links +1 -printf '%n %p\n'
[no output]
```

This proves `os.link()` created each destination without clobbering and the
transaction then unlinked every staging-side quartet entry, leaving no stray
hardlink.

A scratch copy of the extracted tree was given one otherwise-unlisted dotfile:

```text
$ ls -la /tmp/tri-target-hidden-proof.kd5cBQ
total 12
drwxr-xr-x.   5 jer  jer    140 Jul 26 12:57 .
drwxrwxrwt. 391 root root  9480 Jul 26 12:57 ..
-rw-r--r--.   1 jer  jer      0 Jul 26 12:57 .unexpected
-rw-r--r--.   1 jer  jer  11348 Jul 26 12:53 LICENSE
drwxr-xr-x.   2 jer  jer     60 Jul 26 12:57 bin
drwxr-xr-x.   2 jer  jer    100 Jul 26 12:57 lib
drwxr-xr-x.   3 jer  jer     80 Jul 26 12:57 share

$ hop check -n 80 -- sol/release/runtime-gate.sh /tmp/tri-target-hidden-proof.kd5cBQ dist/libnvat-linux-x86_64-1.2.2-sol.2-archive.tar.xz dist/libnvat-linux-x86_64-1.2.2-sol.2-archive.tar.xz.sha256 dist/libnvat-linux-x86_64-1.2.2-sol.2-archive.manifest.json dist/libnvat-linux-x86_64-1.2.2-sol.2-archive.manifest.json.sha256 dist/.staging/linux-x86_64-1.2.2-sol.2/layout.tsv dist/.staging/linux-x86_64-1.2.2-sol.2/counts.tsv linux
hop check: `sol/release/runtime-gate.sh /tmp/tri-target-hidden-proof.kd5cBQ dist/libnvat-linux-x86_64-1.2.2-sol.2-archive.tar.xz dist/libnvat-linux-x86_64-1.2.2-sol.2-archive.tar.xz.sha256 dist/libnvat-linux-x86_64-1.2.2-sol.2-archive.manifest.json dist/libnvat-linux-x86_64-1.2.2-sol.2-archive.manifest.json.sha256 dist/.staging/linux-x86_64-1.2.2-sol.2/layout.tsv dist/.staging/linux-x86_64-1.2.2-sol.2/counts.tsv linux` exited 1
```

The gate exited at the root-directory count before launching `nvattest`. This
proves `.unexpected` is now counted; the former `"$checked"/*` expansion would
have ignored it. The scratch tree was removed after this proof.

The new quartet hashes were:

```text
$ sha256sum dist/libnvat-linux-x86_64-1.2.2-sol.2-*
2b5fdc29dd5d70cf5943ecc7ed2fe32cc6b213b81454e24794ee60bef792efbc  dist/libnvat-linux-x86_64-1.2.2-sol.2-archive.manifest.json
36f8e23b20e9e32ba9bdaeb07beefa69a3d06e760e397ca4d19f101b60dd9a73  dist/libnvat-linux-x86_64-1.2.2-sol.2-archive.manifest.json.sha256
5f2e664b6cbbb4fc22c89d274c7952d3a32415da0561aa7729443a6d05efced9  dist/libnvat-linux-x86_64-1.2.2-sol.2-archive.tar.xz
026600927a81c08439ea85c3398a81e5b908da43fe548a9ba585260f10295a5e  dist/libnvat-linux-x86_64-1.2.2-sol.2-archive.tar.xz.sha256
```

These do not equal the earlier archive `df1589ef…` quartet because the
reproducibility inputs are intentionally different: the earlier run was at a
different source commit, while this run binds commit `89029ea…` and
`SOURCE_DATE_EPOCH=1785092033`. The changed epoch affects both normalized tar
headers and the vendored OpenSSL build string:

```text
$ tar -xOf dist/libnvat-linux-x86_64-1.2.2-sol.2-archive.tar.xz lib/libnvat.so.1.2.2 | strings | grep '^built on:'
built on: Sun Jul 26 18:53:53 2026 UTC

$ date -u -d @1785092033 '+SOURCE_DATE_EPOCH_UTC=%a %b %d %H:%M:%S %Y UTC'
SOURCE_DATE_EPOCH_UTC=Sun Jul 26 18:53:53 2026 UTC

$ python3 -c 'import json; value=json.load(open("dist/libnvat-linux-x86_64-1.2.2-sol.2-archive.manifest.json")); print("source.commit="+value["source"]["commit"]); print("source.source_date_epoch="+str(value["source"]["source_date_epoch"]))'
source.commit=89029eae58fbb474375ea3a373681d32cf1cee55
source.source_date_epoch=1785092033
```

The manifest and its sidecar must additionally change because they bind the
new source commit, rewritten commit series, new artifact hash, and size. This
is not a same-input reproducibility regression; it is the expected result of
the deliberately changed source identity and source epoch.

Finally, the remediated set validator reported the two genuinely absent native
targets:

```text
$ hop check -n 80 -- python3 sol/release/rail.py validate-set --dist dist
hop check: `python3 sol/release/rail.py validate-set --dist dist` exited 2
release rail error: missing target: linux-aarch64; missing target: macos-arm64; recover by collecting each missing quartet: on its native host run `make release TARGET=linux-aarch64`; on its native host run `make release TARGET=macos-arm64`
```

This proves single-quartet discovery still fails closed with both missing
targets named after the validator gained independent archive static gates.

### Runtime selection and pinned provenance native re-run (2026-07-26)

All commands in this subsection ran in
`/home/jer/.hopper/worktrees/ogw2thlw`. Nothing under
`/home/jer/projects/attestation-sdk/dist/` was read, written, moved, or
deleted.

Before construction, a PATH-first executable named `podman` reported a wrong
product:

```text
$ hop check env PATH=/tmp/nvattest-wrong-runtime:/usr/local/bin:/usr/bin:/bin make release TARGET=linux-x86_64
hop check: `env PATH=/tmp/nvattest-wrong-runtime:/usr/local/bin:/usr/bin:/bin make release TARGET=linux-x86_64` exited 2
./sol/release/release.sh "linux-x86_64"
release rail error: no usable OCI runtime: podman: podman version reported the wrong product; docker: command not found; install docker; recover by installing a working Podman or local Unix-socket Docker engine
make: *** [Makefile:59: release] Error 2

$ ls -la
total 52
drwxr-xr-x. 1 jer jer   416 Jul 26 13:53 .
drwxr-xr-x. 1 jer jer    32 Jul 26 13:20 ..
-rw-r--r--. 1 jer jer    67 Jul 26 13:20 .git
drwxr-xr-x. 1 jer jer    46 Jul 26 13:20 .github
-rw-r--r--. 1 jer jer   464 Jul 26 13:20 .gitignore
-rw-r--r--. 1 jer jer  3499 Jul 26 13:20 CODE_OF_CONDUCT.md
-rw-r--r--. 1 jer jer  7020 Jul 26 13:20 CONTRIBUTING.md
-rw-r--r--. 1 jer jer 11348 Jul 26 13:20 LICENSE
-rw-r--r--. 1 jer jer  2818 Jul 26 13:43 Makefile
-rw-r--r--. 1 jer jer  4723 Jul 26 13:20 README.md
-rw-r--r--. 1 jer jer   913 Jul 26 13:20 SECURITY.md
drwxr-xr-x. 1 jer jer   568 Jul 26 13:55 build
drwxr-xr-x. 1 jer jer   162 Jul 26 13:20 common-test-data
drwxr-xr-x. 1 jer jer    50 Jul 26 13:20 dev
drwxr-xr-x. 1 jer jer    60 Jul 26 13:20 nv-attestation-cli
drwxr-xr-x. 1 jer jer   202 Jul 26 13:20 nv-attestation-sdk-cpp
drwxr-xr-x. 1 jer jer   138 Jul 26 13:20 nv-attestation-sdk-rust
drwxr-xr-x. 1 jer jer   372 Jul 26 13:20 relying_party_policy_examples
drwxr-xr-x. 1 jer jer    80 Jul 26 13:20 sol

$ test ! -e dist; echo "dist_absent_status=$?"
dist_absent_status=0
```

A minimal PATH containing non-executable `podman` and `docker` stubs, plus
only the commands needed to launch the rail, exercised the neither-present
case:

```text
$ hop check env PATH=/tmp/nvattest-no-runtimes make release TARGET=linux-x86_64
hop check: `env PATH=/tmp/nvattest-no-runtimes make release TARGET=linux-x86_64` exited 2
./sol/release/release.sh "linux-x86_64"
release rail error: no usable OCI runtime: podman: command not found; install podman; docker: command not found; install docker; recover by installing a working Podman or local Unix-socket Docker engine
make: *** [Makefile:59: release] Error 2

$ test ! -e dist; echo "dist_absent_status=$?"
dist_absent_status=0
```

The worktree then built its own image. The pre-existing host-global image was
not treated as build proof:

```text
$ hop check make image
hop check: `make image` exited 0
RUNTIME="$( python3 sol/release/rail.py runtime select )" && \
	IMAGE="$( python3 sol/release/rail.py runtime image-tag )" && \
	CI_IMAGE="$( python3 sol/release/rail.py authority build-image "" )" && \
	"$RUNTIME" build --build-arg CI_IMAGE="$CI_IMAGE" -t "$IMAGE" -f sol/ci/Containerfile sol/ci
STEP 1/4: FROM quay.io/pypa/manylinux_2_28_x86_64@sha256:a61875a2f84cab7df8de222ff12cabc08ff86eb4ad402ac90ba7bdaed9600cca
STEP 2/4: RUN dnf install -y     openssl-devel libcurl-devel libxml2-devel xmlsec1-devel xmlsec1-openssl-devel     zlib-devel xz git patch perl-core   && dnf clean all
--> Using cache 3bcae635fe39e81593813adb67c8107c7459aade1a929d592ab369ef19852c7e
--> 3bcae635fe39
STEP 3/4: RUN curl -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal --default-toolchain 1.88.0
--> Using cache 31b17784fab7a9bf0afde67542fd5db6751f0d66f50c63254576c6fa28eb97c3
--> 31b17784fab7
STEP 4/4: ENV PATH="/root/.cargo/bin:${PATH}"
--> Using cache 3fdc1e574941633de67d8abcf7a08daa6bad804d8e95f612abdacb12b5d349ed
COMMIT attestation-sdk-ci
--> 3fdc1e574941
Successfully tagged localhost/attestation-sdk-ci:latest
3fdc1e574941633de67d8abcf7a08daa6bad804d8e95f612abdacb12b5d349ed
```

The native release completed both digest-pinned runtime gates:

```text
$ hop check make release TARGET=linux-x86_64
generated 12 dependency pins
--ca-bundle: CA bundle path '/nonexistent/path' from --ca-bundle does not exist or is not readable; provide a readable file with --ca-bundle or NVAT_CA_BUNDLE.
Run with --help for more information.
runtime, layout, and quartet hash gates passed
--ca-bundle: CA bundle path '/nonexistent/path' from --ca-bundle does not exist or is not readable; provide a readable file with --ca-bundle or NVAT_CA_BUNDLE.
Run with --help for more information.
runtime, layout, and quartet hash gates passed
/home/jer/.hopper/worktrees/ogw2thlw/dist/libnvat-linux-x86_64-1.2.2-sol.2-archive.tar.xz
/home/jer/.hopper/worktrees/ogw2thlw/dist/libnvat-linux-x86_64-1.2.2-sol.2-archive.tar.xz.sha256
/home/jer/.hopper/worktrees/ogw2thlw/dist/libnvat-linux-x86_64-1.2.2-sol.2-archive.manifest.json
/home/jer/.hopper/worktrees/ogw2thlw/dist/libnvat-linux-x86_64-1.2.2-sol.2-archive.manifest.json.sha256
hop check: `make release TARGET=linux-x86_64` exited 0, showing last 50 of 2859 lines
```

The manifest and live Git range agreed exactly:

```text
$ python3 - "$manifest_path"
source.commit=786fe9060d552d0262e58bc67666b1a698e65ec5
source.upstream_base_commit=73c032ebff680ca6d2ba06f4006b511491b71ce9
source.sol_series_length=27
source.sol_series_first=9f15d44aa65c6603b7458cb343fa68d67c34634d
source.sol_series_last=786fe9060d552d0262e58bc67666b1a698e65ec5
build_tools.container_runtime={"client":{"name":"Podman Engine","version":"5.8.3"},"engine":{"name":"Podman Engine","version":"5.8.3","os":"linux","architecture":"amd64"}}

$ git rev-parse HEAD
786fe9060d552d0262e58bc67666b1a698e65ec5

$ git rev-list --count 73c032ebff680ca6d2ba06f4006b511491b71ce9..HEAD
27

$ git rev-list --merges --count 73c032ebff680ca6d2ba06f4006b511491b71ce9..HEAD
0

$ python3 - "$manifest_path"
manifest_series_order_matches=true
```

Ownership and cleanup were observed on the host:

```text
$ ls -ld build dist
drwxr-xr-x. 1 jer jer 582 Jul 26 14:05 build
drwxr-xr-x. 1 jer jer 448 Jul 26 14:06 dist

$ stat -c '%n mode=%A(%a) owner=%U(%u) group=%G(%g)' build dist
build mode=drwxr-xr-x(755) owner=jer(1000) group=jer(1000)
dist mode=drwxr-xr-x(755) owner=jer(1000) group=jer(1000)

$ hop check make clean
hop check: `make clean` exited 0
rm -rf build

$ ls -ld build
ls: cannot access 'build': No such file or directory
[exit 2]

$ stat -c '%n mode=%A(%a) owner=%U(%u) group=%G(%g)' dist
dist mode=drwxr-xr-x(755) owner=jer(1000) group=jer(1000)
```

Before the retained-quartet failure, the quartet hashes and successful-run
staging-tree fingerprint were:

```text
$ sha256sum dist/libnvat-linux-x86_64-1.2.2-sol.2-* | sort
ace1dd494dc7f4e308ed85b903c86fc05bd1d384f5682a0e4888ba3e9c65bf47  dist/libnvat-linux-x86_64-1.2.2-sol.2-archive.manifest.json.sha256
b78108872d5417e7724d0dc1eddaff6314a2173c74ed255a37f84099eb47d882  dist/libnvat-linux-x86_64-1.2.2-sol.2-archive.manifest.json
d80bf4226442559d0765a201ad94120dcd34b46a9d05cc337832bb1cef01019d  dist/libnvat-linux-x86_64-1.2.2-sol.2-archive.tar.xz
e5c0e86dd10880f12deafe7b9cd76bf452acbdd679dd124574ebef90f65dd3c2  dist/libnvat-linux-x86_64-1.2.2-sol.2-archive.tar.xz.sha256

$ find dist/.staging -printf '%y %m %u %g %s %T@ %p %l\n' | sort | sha256sum
1ad82e035777381c8cd7e5abfd0870b6dec988703411f96835f89debf8e04f28  -
```

The real wrong-product identity probe then failed in preflight, before any
container was run:

```text
$ hop check env PATH=/tmp/nvattest-wrong-runtime:/usr/local/bin:/usr/bin:/bin make release TARGET=linux-x86_64
hop check: `env PATH=/tmp/nvattest-wrong-runtime:/usr/local/bin:/usr/bin:/bin make release TARGET=linux-x86_64` exited 2
./sol/release/release.sh "linux-x86_64"
release rail error: no usable OCI runtime: podman: podman version reported the wrong product; docker: command not found; install docker; recover by installing a working Podman or local Unix-socket Docker engine
make: *** [Makefile:59: release] Error 2
```

Afterward the four hashes, staging fingerprint, and exact top-level quartet
were unchanged:

```text
$ sha256sum dist/libnvat-linux-x86_64-1.2.2-sol.2-* | sort
ace1dd494dc7f4e308ed85b903c86fc05bd1d384f5682a0e4888ba3e9c65bf47  dist/libnvat-linux-x86_64-1.2.2-sol.2-archive.manifest.json.sha256
b78108872d5417e7724d0dc1eddaff6314a2173c74ed255a37f84099eb47d882  dist/libnvat-linux-x86_64-1.2.2-sol.2-archive.manifest.json
d80bf4226442559d0765a201ad94120dcd34b46a9d05cc337832bb1cef01019d  dist/libnvat-linux-x86_64-1.2.2-sol.2-archive.tar.xz
e5c0e86dd10880f12deafe7b9cd76bf452acbdd679dd124574ebef90f65dd3c2  dist/libnvat-linux-x86_64-1.2.2-sol.2-archive.tar.xz.sha256

$ find dist/.staging -printf '%y %m %u %g %s %T@ %p %l\n' | sort | sha256sum
1ad82e035777381c8cd7e5abfd0870b6dec988703411f96835f89debf8e04f28  -

$ find dist -maxdepth 1 -type f -printf '%f\n' | sort
libnvat-linux-x86_64-1.2.2-sol.2-archive.manifest.json
libnvat-linux-x86_64-1.2.2-sol.2-archive.manifest.json.sha256
libnvat-linux-x86_64-1.2.2-sol.2-archive.tar.xz
libnvat-linux-x86_64-1.2.2-sol.2-archive.tar.xz.sha256
```

The `.staging` tree shown here belongs to the successful release. Its identical
before/after fingerprint proves the failed preflight created no new staging
residue. A post-staging failure was not fabricated: with the retained quartet
at its authoritative destinations, overwrite refusal precedes construction,
and construction failures deliberately retain owned staging for diagnosis.

The complete-set validator still named both genuinely absent native targets:

```text
$ hop check python3 sol/release/rail.py validate-set --dist dist
hop check: `python3 sol/release/rail.py validate-set --dist dist` exited 2
release rail error: missing target: linux-aarch64; missing target: macos-arm64; recover by collecting each missing quartet: on its native host run `make release TARGET=linux-aarch64`; on its native host run `make release TARGET=macos-arm64`
```

Finally, the promoted archive was extracted only to `/tmp` for the F5 string
counts:

```text
$ scratch_dir=$(mktemp -d /tmp/runtime-provenance-f5.XXXXXX)
$ tar -C "$scratch_dir" -xJf dist/libnvat-linux-x86_64-1.2.2-sol.2-archive.tar.xz
$ printf '/root/.cargo/registry/ count='; strings "$scratch_dir/lib/libnvat.so.1.2.2" | grep -F -c '/root/.cargo/registry/'
/root/.cargo/registry/ count=226
$ printf '/src/build/release/ count='; strings "$scratch_dir/lib/libnvat.so.1.2.2" | grep -F -c '/src/build/release/'
/src/build/release/ count=36
$ ls -l "$scratch_dir/lib/libnvat.so.1.2.2"
-rwxr-xr-x. 1 jer jer 33256784 Jul 26 14:02 /tmp/runtime-provenance-f5.rZcpwW/lib/libnvat.so.1.2.2
```

Docker was not executed on this lode. Docker and native aarch64 proof remain
VPE-direct work on Spark; no simulated Docker output is recorded here.

After the audit follow-up settled, the release-rail gate passed:

```text
$ hop check make rail-test
hop check: `make rail-test` exited 0
python3 -m unittest discover -s sol/release/tests -p 'test_*.py'
.......................................................................
----------------------------------------------------------------------
Ran 71 tests in 0.370s

OK
shellcheck $(find sol -type f -name '*.sh' -print | sort)
```

The canonical C++ gate then passed once on the same settled tree:

```text
$ hop check make ci
hop check: `make ci` exited 0, showing last 50 of 3117 lines
      Start 51: NvHttpClient.PostAsStruct
51/68 Test #51: NvHttpClient.PostAsStruct .......................................................***Not Run (Disabled)   0.00 sec
      Start 52: CaBundleResolutionTest.ExplicitPathBeatsEveryEnvironmentTier
52/68 Test #52: CaBundleResolutionTest.ExplicitPathBeatsEveryEnvironmentTier ....................   Passed    0.01 sec
      Start 53: CaBundleResolutionTest.NvatEnvironmentBeatsLowerEnvironmentTiers
53/68 Test #53: CaBundleResolutionTest.NvatEnvironmentBeatsLowerEnvironmentTiers ................   Passed    0.01 sec
      Start 54: CaBundleResolutionTest.CurlEnvironmentBeatsSslEnvironment
54/68 Test #54: CaBundleResolutionTest.CurlEnvironmentBeatsSslEnvironment .......................   Passed    0.01 sec
      Start 55: CaBundleResolutionTest.SslEnvironmentBeatsDefaultsAndProbes
55/68 Test #55: CaBundleResolutionTest.SslEnvironmentBeatsDefaultsAndProbes .....................   Passed    0.01 sec
      Start 56: CaBundleResolutionTest.EmptyValuesAreSkippedAtEveryExplicitAndEnvironmentTier
56/68 Test #56: CaBundleResolutionTest.EmptyValuesAreSkippedAtEveryExplicitAndEnvironmentTier ...   Passed    0.01 sec
      Start 57: CaBundleResolutionTest.SystemProbeRunsWhenNoHigherTierResolves
57/68 Test #57: CaBundleResolutionTest.SystemProbeRunsWhenNoHigherTierResolves ..................   Passed    0.01 sec
      Start 58: CaBundleResolutionTest.CompiledDefaultBeatsSystemProbe
58/68 Test #58: CaBundleResolutionTest.CompiledDefaultBeatsSystemProbe ..........................   Passed    0.01 sec
      Start 59: CaBundleResolutionTest.MissingAuthoritativePathsFailWithPathAndTier
59/68 Test #59: CaBundleResolutionTest.MissingAuthoritativePathsFailWithPathAndTier .............   Passed    0.01 sec
      Start 60: CaBundleResolutionTest.MissingFullChainReturnsActionableError
60/68 Test #60: CaBundleResolutionTest.MissingFullChainReturnsActionableError ...................   Passed    0.01 sec
      Start 61: DetachedEatTest.CreateAndVerify
61/68 Test #61: DetachedEatTest.CreateAndVerify .................................................   Passed    0.01 sec
      Start 62: DetachedEatTest.CreateReturnsOverallResultFalse
62/68 Test #62: DetachedEatTest.CreateReturnsOverallResultFalse .................................   Passed    0.01 sec
      Start 63: NvCacheTest.TestPutAndGet
63/68 Test #63: NvCacheTest.TestPutAndGet .......................................................   Passed    0.01 sec
      Start 64: NvCacheTest.TestPutKeyExists
64/68 Test #64: NvCacheTest.TestPutKeyExists ....................................................   Passed    0.01 sec
      Start 65: NvCacheTest.TestPutAndRemove
65/68 Test #65: NvCacheTest.TestPutAndRemove ....................................................   Passed    0.01 sec
      Start 66: NvCacheTest.TestLruEviction
66/68 Test #66: NvCacheTest.TestLruEviction .....................................................   Passed    0.01 sec
      Start 67: NvCacheTest.MultipleThreads
67/68 Test #67: NvCacheTest.MultipleThreads .....................................................   Passed    0.11 sec
      Start 68: NvShortExpiryCacheTest.TestExpiryEviction
68/68 Test #68: NvShortExpiryCacheTest.TestExpiryEviction .......................................   Passed    3.01 sec

100% tests passed out of 64

Label Time Summary:
unit    =   3.95 sec*proc (68 tests)

Total Test time (real) =   3.96 sec

The following tests did not run:
	 48 - NvHttpClient.GetAsString (Disabled)
	 49 - NvHttpClient.GetAsStruct (Disabled)
	 50 - NvHttpClient.PostAsString (Disabled)
	 51 - NvHttpClient.PostAsStruct (Disabled)
make[1]: Leaving directory '/home/jer/.hopper/worktrees/ogw2thlw'
```
