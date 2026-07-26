# Three-target release rail design

**Authority:** this document supersedes the x86_64-era planning in
`sol/notes/design.md` for everything under `sol/release/`.
`sol/notes/design.md` §1–§2 (CA resolution and vendored dependencies) remain
current. The accepted facts in `sol/notes/tri-target-prep.md` are inputs to this
design and are not re-derived here.

The rail has exactly three native targets: `linux-x86_64`,
`linux-aarch64`, and `macos-arm64`. Cross-compilation is unsupported and is a
hard preflight failure.

## Fresh image resolution

The new arm64 references were resolved from their platform manifests. The
accepted x86_64 build image remains pinned unchanged; it was not re-resolved
from a mutable tag. The x86_64 bare images were selected specifically from the
two previously accepted index digests. `skopeo` remains absent, so the working
discovery command was Podman plus the registry v2 API for the config-blob
architecture check:

```text
$ podman manifest inspect IMAGE@PINNED_INDEX_DIGEST
$ curl -fsS -D headers -o manifest \
    -H 'Accept: <index and manifest media types>' \
    REGISTRY/v2/REPOSITORY/manifests/latest
$ # Select linux/amd64 and linux/arm64 descriptors from an index, then:
$ curl -fsS -o child-manifest \
    -H "Authorization: Bearer $token" REGISTRY/v2/REPOSITORY/manifests/$digest
$ curl -fsS -o config \
    -H "Authorization: Bearer $token" REGISTRY/v2/REPOSITORY/blobs/$config_digest
```

The actual normalized result was:

```text
$ podman manifest inspect docker.io/library/fedora@sha256:6c75d5bf57cb0fa5aa4b92c6a83c86c791644496d9ac230de7711f5b8ec3b898
linux/amd64 child=sha256:89f61a124414261868224666aa7fb8df1b78397a53623774bdfb105d1612b48b
[exit 0]
$ podman manifest inspect docker.io/opensuse/tumbleweed@sha256:18a8c2a41252a0100ae4a7dae0a0e925fb522971645b97b05c57f9b6e73c3b4f
linux/amd64 child=sha256:cdc11dd58d01acfde221f1b6fba21b64acbed561ef18ab086f78571dff4a4d17
[exit 0]
manylinux_2_28_x86_64 accepted digest=sha256:a61875a2f84cab7df8de222ff12cabc08ff86eb4ad402ac90ba7bdaed9600cca mediaType=application/vnd.docker.distribution.manifest.v2+json architecture=amd64
manylinux_2_28_aarch64 digest=sha256:e7035406e58d96b7407246af1f6514a3cbd753a0025b42b9adfbeadd3b29ba80 mediaType=application/vnd.docker.distribution.manifest.v2+json architecture=arm64 manifest_exit=0 config_exit=0
library/fedora@sha256:89f61a124414261868224666aa7fb8df1b78397a53623774bdfb105d1612b48b expected=amd64 architecture=amd64 manifest_exit=0 config_exit=0
library/fedora@sha256:a471bd8bf8e7e99812fd2f29fc950685d860b3d528b9f090443dbc1a0d2bad62 expected=arm64 architecture=arm64 manifest_exit=0 config_exit=0
opensuse/tumbleweed@sha256:cdc11dd58d01acfde221f1b6fba21b64acbed561ef18ab086f78571dff4a4d17 expected=amd64 architecture=amd64 manifest_exit=0 config_exit=0
opensuse/tumbleweed@sha256:dc90443ab117e6887a4184d772259b84b3e9e54f6333c3331a42c97fdefd601d expected=arm64 architecture=arm64 manifest_exit=0 config_exit=0
```

These six platform-manifest pins become authority:

| Purpose | Digest-pinned reference |
|---|---|
| x86_64 build | `quay.io/pypa/manylinux_2_28_x86_64@sha256:a61875a2f84cab7df8de222ff12cabc08ff86eb4ad402ac90ba7bdaed9600cca` |
| aarch64 build | `quay.io/pypa/manylinux_2_28_aarch64@sha256:e7035406e58d96b7407246af1f6514a3cbd753a0025b42b9adfbeadd3b29ba80` |
| x86_64 Fedora gate | `docker.io/library/fedora@sha256:89f61a124414261868224666aa7fb8df1b78397a53623774bdfb105d1612b48b` |
| aarch64 Fedora gate | `docker.io/library/fedora@sha256:a471bd8bf8e7e99812fd2f29fc950685d860b3d528b9f090443dbc1a0d2bad62` |
| x86_64 Tumbleweed gate | `docker.io/opensuse/tumbleweed@sha256:cdc11dd58d01acfde221f1b6fba21b64acbed561ef18ab086f78571dff4a4d17` |
| aarch64 Tumbleweed gate | `docker.io/opensuse/tumbleweed@sha256:dc90443ab117e6887a4184d772259b84b3e9e54f6333c3331a42c97fdefd601d` |

Each reference is directly usable by digest. On a native matching host Podman
must not need `--platform`; the driver nevertheless passes
`--platform=linux/amd64` or `--platform=linux/arm64` as a fail-closed assertion,
not as index selection. A disagreement between the manifest config and the
explicit platform fails before execution.

## D1 — One Python static-gate implementation

**Decision.** Adopt the proposal. Create the pure-stdlib package
`sol/release/release_rail/` with:

* `authority.py` — TOML loading, validation, host matching, and accessor CLI;
* `elf.py` and `macho.py` — bounded binary readers;
* `gate.py` — shared policy over a target record;
* `fixtures.py` — test-only minimal byte emitters;
* `archive.py`, `manifest.py`, `transaction.py`, and `set_validator.py` —
  deterministic construction, quartet handling, and set validation.

`sol/release/rail.py` is the single small command facade used by shell and
Make. It imports the package; it does not duplicate policy.

Static gates run on the native host after staging and again on the extracted
archive. Unit tests run both ELF and Mach-O readers on Linux, so `make ci` can
exercise macOS byte policy without Apple tools. `struct`, `hashlib`, `json`,
`tomllib`, and normal byte/string operations are sufficient.

Delete `sol/release/gate-artifact.sh` and
`sol/release/binutils-wrapper.sh`. Delete the gate-tool extraction block rather
than replacing it. Bare images need only their existing shell/coreutils runtime
surface and the shared runtime script described in D10.

The Q6 static guarantees move as follows:

* ELF readability and architecture, nonempty DT_NEEDED, exact dependency
  closure, symbol-version floors, and forbidden CA strings move from
  `gate-artifact.sh` in each bare container to `release_rail.elf` plus
  `release_rail.gate` on the host.
* The same host gate is run against staged bytes and re-extracted archive bytes.
  Architecture, headers, dynamic entries, symbol versions, and strings are
  intrinsic byte properties; changing the process or distro that reads them
  cannot change the proposition proved.
* The two bare containers retain only what is environment-dependent: actual
  dynamic resolution and process startup, eager CA-path behavior, extracted
  layout/type/count checks, and independently computed quartet hash agreement.

This avoids two gate languages and makes every format/policy mutation directly
unit-testable.

**Files touched:** add `sol/release/rail.py`,
`sol/release/release_rail/{__init__,authority,elf,macho,gate,archive,manifest,transaction,set_validator,fixtures}.py`
and tests under `sol/release/tests/`; delete
`sol/release/gate-artifact.sh` and `sol/release/binutils-wrapper.sh`; replace
the existing driver as described in D6/D9.

## D2 — TOML target authority

**Decision.** Replace `sol/release/release.env` with
`sol/release/targets.toml`. TOML is structured, reviewable, and parsed natively
by supported Python (`tomllib`); Bash and Make access it only through
`python3 sol/release/rail.py authority ...`.

Exact schema:

```text
[release]
sol_revision = 2
ca_snapshot_date = "YYYY-MM-DD"
ca_bundle_url = "https://..."
ca_bundle_sha256 = "<64 lowercase hex>"
archive_xz_preset = 6
archive_xz_threads = 1
source_date_epoch_source = "git-head"

[[targets]]
id = "linux-x86_64" | "linux-aarch64" | "macos-arm64"
host_os = "Linux" | "Darwin"
host_machines = ["x86_64", "amd64"] | ["aarch64", "arm64"] | ["arm64"]
build_image = "<digest reference>" | "none"
gate_images = ["<fedora child digest>", "<tumbleweed child digest>"] | []
container_platform = "linux/amd64" | "linux/arm64" | "none"
archive_name = "libnvat-{target}-{version}-archive.tar.xz"
binary_format = "elf64-le" | "macho64-le"
expected_arch = "EM_X86_64" | "EM_AARCH64" | "CPU_TYPE_ARM64"
abi_kind = "gnu-symbol-max" | "macos-deployment-exact"
abi_floor = { glibc = "2.28", glibcxx = "3.4.25", cxxabi = "1.3.11" }
          | { macos = "14.0" }
runtime_allowlist = "sol/release/allowlists/<target>.txt"
members = [
  { path = "...", kind = "regular" | "symlink", link_target = "..." }
]
directory_counts = { "." = 4, "bin" = 1, "lib" = 3, "share" = 2,
                     "share/ca" = 1 }
required_tools = ["<compiler>", "cmake", "rustc", "cargo",
                  "<tar command>", "xz", "python3"]
macho_install_id = "@rpath/libnvat.1.dylib" # macos-arm64 only
macho_rpath = "@executable_path/../lib"     # macos-arm64 only
```

The Linux member arrays contain `bin/nvattest`, `lib/libnvat.so`,
`lib/libnvat.so.1`, `lib/libnvat.so.1.2.2`, `LICENSE`,
`share/ca/ca-bundle.pem`, and `share/THIRD_PARTY_NOTICES.md`, with the first
two library aliases marked symlink and the fully versioned library regular.
The macOS member array substitutes the three names decided in D4 and their
types. Ordered `members` remains the single input to staging checks, tar
creation, manifest `archive_members`, and runtime layout checks.

There are three referenced allowlist files:

* `allowlists/linux-x86_64.txt`;
* `allowlists/linux-aarch64.txt`;
* `allowlists/macos-arm64.txt`.

The two ELF lists are intentionally separate because their loader SONAMEs
differ; sharing a base plus overrides would make the effective policy harder
to audit. The Mach-O list contains exact permitted install names/prefix rules,
not ELF SONAMEs. `targets.toml` is the sole map from target to policy, and the
allowlist contents exist only in their files, so there is no parallel truth
source. Delete `sol/release/dt-needed.allow`.

The Makefile does not resolve failure-capable authority values through
`$(shell ...)`. Its image recipe resolves the host-compatible build image in
the shell so a nonzero accessor status propagates:

```text
RAIL := python3 sol/release/rail.py
HOST_TARGET ?=

image:
	CI_IMAGE="$$( $(RAIL) authority build-image "$(HOST_TARGET)" )" && ...
```

`make image` and `make ci` remain zero-argument commands on this x86_64 Linux
host and select the x86_64 build manifest inside the recipe. Authority loading
rejects malformed TOML, duplicate IDs, unknown keys, incomplete target records,
non-digest image references, unsupported host aliases, and a selected target
whose host predicate does not match `platform.system()`/`platform.machine()`.
`build_image="none"` is valid only for macOS, where `make image` reports that
no container image applies.

**Files touched:** add `sol/release/targets.toml` and three files under
`sol/release/allowlists/`; add authority code/tests; delete
`sol/release/release.env` and `sol/release/dt-needed.allow`; update `Makefile`,
`sol/ci/Containerfile` input wiring, driver, manifest code, and operator docs.

## D3 — Synthesized fixtures

**Decision.** Commit no binary blobs. `release_rail.fixtures` exposes only
test helpers:

* `elf_fixture(machine, needed, versions, strings, *, truncated_at=None) -> bytes`;
* `macho_fixture(cputype, cpusubtype, deployment_command, deployment_version,
  dylibs, dylib_id, rpaths, strings, *, declared_ncmds=None,
  fat_magic=None, truncated_at=None) -> bytes`;
* `write_fixture(temp_dir, name, payload) -> pathlib.Path`.

Builders emit only the ELF header/program-independent section records or Mach-O
header/load-command bytes read by the gate. They are not executable or
linkable, contain no real code, and use deterministic zero padding. Tests write
them only into a test-owned temporary directory.

Required fixtures and mutations are:

* valid x86_64 ELF and valid aarch64 ELF;
* both foreign-architecture directions: x86_64 policy rejects AArch64 and
  aarch64 policy rejects X86-64;
* valid arm64 thin Mach-O;
* allowed ELF closure and forbidden DSO;
* allowed Mach-O references and forbidden dylib;
* each external Mach-O runtime prefix independently:
  `/opt/homebrew`, `/usr/local`, and a synthetic absolute build-directory path;
* each GNU version family at its floor and one above-floor symbol version;
* macOS 14.0 through `LC_BUILD_VERSION`, macOS 14.0 through legacy
  `LC_VERSION_MIN_MACOSX`, a below-14.0 mutation, and input missing both;
* each fat magic (`FAT_MAGIC`, `FAT_CIGAM`, `FAT_MAGIC_64`,
  `FAT_CIGAM_64`) hard-failing with “universal Mach-O is not permitted”;
* truncated ELF and Mach-O at header, table/command, and string boundaries;
* a Mach-O header whose `ncmds` claims more commands than the file contains;
* an invalid/overflowing load-command size or string offset;
* empty ELF DT_NEEDED;
* baked `/etc/ssl/certs/ca-certificates.crt` and
  `/etc/pki/tls/certs/ca-bundle.crt` strings.

Archive/transaction tests synthesize regular files and relative symlinks around
these bytes, covering exact counts/types, ordered membership, deterministic
double construction, quartet agreement, and every D6 failure point.

**Files touched:** add `release_rail/fixtures.py` and
`sol/release/tests/test_{elf,macho,gate,archive,transaction}.py`; no fixture
files.

## D4 — Native macOS runtime resolution

**Decision.** Encode runtime resolution in CMake, where it is created and can be
verified on both a native Mac and later by the Linux Mach-O parser. Do not call
`install_name_tool`.

For Apple builds:

* pass `-DCMAKE_OSX_DEPLOYMENT_TARGET=14.0` at initial configure, and reject a
  cache/toolchain that does not preserve it;
* set `nvat` `INSTALL_NAME_DIR` to `@rpath` and
  `BUILD_WITH_INSTALL_NAME_DIR` to `TRUE`;
* set `nvattest` `INSTALL_RPATH` to `@executable_path/../lib` and
  `BUILD_WITH_INSTALL_RPATH` to `TRUE`;
* leave `nvat` without an artifact-relative RPATH because its permitted dynamic
  dependencies are Apple SDK/system install names.

The gate requires:

* `libnvat.1.2.2.dylib` has
  `LC_ID_DYLIB=@rpath/libnvat.1.dylib`;
* `nvattest` loads `@rpath/libnvat.1.dylib`;
* `nvattest` has exactly the artifact-local
  `LC_RPATH=@executable_path/../lib`;
* no load command contains `/opt/homebrew`, `/usr/local`, the build root, or
  another unapproved absolute prefix;
* the deployment command encodes exactly `14.0.0`. Both
  `LC_BUILD_VERSION` and legacy `LC_VERSION_MIN_MACOSX` are understood, but a
  binary with both must agree.

CMake's Darwin `VERSION=1.2.2` and `SOVERSION=1` behavior produces:

* regular `lib/libnvat.1.2.2.dylib`;
* symlink `lib/libnvat.1.dylib -> libnvat.1.2.2.dylib`;
* symlink `lib/libnvat.dylib -> libnvat.1.dylib`.

Those are the macOS authority members. Staging verifies exact relative link
targets rather than merely testing `-L`.

Linux is unchanged: `LD_LIBRARY_PATH=lib ./bin/nvattest ...`, with no RPATH,
as required by `sol/notes/design.md` §3.5. This preserves the accepted x86_64
runtime contract.

Native portability changes make CMake itself select the explicit OpenSSL target
from `CMAKE_SYSTEM_NAME` and `CMAKE_SYSTEM_PROCESSOR`: `linux-x86_64`,
`linux-aarch64`, or `darwin64-arm64-cc`; every other combination fails closed.
This mapping is not duplicated in target authority, so ordinary in-container
CMake builds remain self-sufficient. The changes also condition the separate
`dl` link dependency away on Apple and condition only flags that native Apple
clang/linker reject. There are no Autoconf host/build flags and no Rust
cross-target settings.

Post-ship VPE hand-off, unchanged from prep: investigate cross Autoconf
`--build/--host` behavior and Corrosion target propagation only if the
native-only ruling is revisited; assess Linux-only NVML/corelib/NSCQ hardware
collection on Darwin (file evidence plus local verification remains isolated);
retain/verify SDK zlib and `/usr/lib/libz.1.dylib` allowlisting; and monitor
Apple-clang warning/prefix-map behavior and generated third-party linker flags.

**Files touched:** `nv-attestation-sdk-cpp/CMakeLists.txt`,
`nv-attestation-cli/CMakeLists.txt`, `targets.toml`, Mach-O gate/tests, staging
driver, and operator docs.

## D5 — Manifest schema v2

**Decision.** Each target emits JSON with this exact field shape:

```text
{
  "schema_version": 2,
  "release": {
    "version": "<upstream>-sol.<revision>",
    "sol_revision": <integer>
  },
  "target": {
    "id": "<target ID>",
    "binary_format": "<authority value>",
    "architecture": "<authority expected_arch>",
    "abi": { ...exact authority abi_kind/floor object... }
  },
  "source": {
    "commit": "<git HEAD>",
    "upstream_base_commit": "<git merge-base main HEAD>",
    "sol_series_commits": [
      { "commit": "<hash>", "subject": "<subject>" }
    ],
    "source_date_epoch": <integer>
  },
  "artifact": {
    "name": "<archive basename>",
    "size": <bytes>,
    "sha256": "<64 lowercase hex>"
  },
  "archive_members": [
    { "path": "<ordered path>", "kind": "regular|symlink",
      "link_target": "<relative target or null>" }
  ],
  "dependency_pins": [ ...existing generated dependency records... ],
  "build_inputs": {
    "build_image": "<digest ref or none>",
    "gate_images": ["<ordered digest refs>"],
    "ca_snapshot": {
      "date": "YYYY-MM-DD", "url": "https://...", "sha256": "<hex>"
    },
    "archive": {
      "tar_format": "gnu", "xz_preset": 6, "xz_threads": 1
    }
  },
  "build_tools": {
    "compiler": { "name": "<canonical vendor>", "version": "<numeric>" },
    "cmake": { "name": "cmake", "version": "<numeric>" },
    "rustc": { "name": "rustc", "version": "<numeric>" },
    "cargo": { "name": "cargo", "version": "<numeric>" },
    "tar": { "name": "GNU tar", "version": "<numeric>" },
    "xz": { "name": "xz", "version": "<numeric>" },
    "python": { "name": "CPython", "version": "<numeric>" }
  }
}
```

`size` is the archive's exact `stat().st_size`. No generation timestamp or
hostname is recorded.

Each tool is invoked, not inferred from package metadata: the configured C++
compiler with `--version`, `cmake --version`, `rustc --version`,
`cargo --version`, authority-selected GNU `tar --version`, `xz --version`, and
`python3 --version`. The parser recognizes an allowlisted vendor-specific first
line and stores only a canonical product name and dotted numeric version. It
discards executable paths, parenthesized distribution/build annotations, Rust
commit hashes/dates, Apple build IDs, and subsequent lines. Unknown output or a
missing tool fails preflight, naming the tool and a concrete
installation/recovery command. Versions are evidence recorded in the manifest,
not equality constraints in authority. This prevents absolute paths, build
dates, and host names from entering the manifest while retaining auditable
tool versions.

The archive is made with authority-selected GNU tar using explicit
`--format=gnu --sort=name --mtime=@EPOCH --owner=0 --group=0 --numeric-owner`
and the ordered member list, piped to authority-selected xz with preset `-6`
and `-T1`. The driver removes `XZ_OPT` and `XZ_DEFAULTS` from the subprocess
environment. macOS therefore requires pinned GNU tar (`gtar`) and xz in
addition to Xcode CLT; stock BSD tar is not used.

JSON is serialized as UTF-8 with `indent=2`, insertion order defined above,
Unix newlines, and one final newline. After the final manifest bytes exist,
SHA-256 is computed over those exact bytes. The manifest sidecar is exactly:

```text
<manifest-sha256><two ASCII spaces><manifest basename><newline>
```

This matches the archive sidecar convention. Internal quartet verification
recomputes archive and manifest hashes after construction, after archive
extraction, inside every applicable runtime gate, and immediately before
promotion. The set validator repeats both checks from promoted files.

**Files touched:** replace `sol/release/generate-manifest.py` with package
manifest generation/tests; update authority, driver, runtime gate, set
validator, and operator docs.

## D6 — Transaction model and failure injection

**Decision.** The driver derives a target/version-specific owned directory
`dist/.staging/<target>-<version>/`. After validating that the resolved path is
strictly below `dist/.staging`, a rerun may delete and recreate only that
directory. It may not glob-delete or clean any other `dist` path.

Construction order inside staging is:

1. preflight clean tree, native host, authority, tool versions, destination
   nonexistence, and dependency inputs;
2. acquire pinned dependencies/CA and verify both CA hashes;
3. clean native build;
4. stage ordered members and verify paths, kinds, link targets, and counts;
5. host static gate over staged binaries;
6. deterministic archive construction and re-extraction;
7. host static gate over extracted binaries;
8. target runtime gates in authority order;
9. archive sidecar;
10. complete schema-v2 manifest using final archive size/hash;
11. manifest sidecar;
12. full quartet internal verification;
13. promotion.

The four final paths are archive, archive `.sha256`, manifest, and manifest
`.sha256`. Existing destinations always fail, even when byte-identical: an
accepted no-op would hide whether this invocation built and verified the
quartet and would weaken source-identity auditability.

Promotion first confirms all four destinations are absent, then moves in fixed
order: archive, archive sidecar, manifest, manifest sidecar. It records only
successfully moved paths. On any move failure it unlinks those recorded paths
in reverse order, after confirming each path is one of the four exact
destinations, leaving no members of the new quartet in `dist/`. Staging remains
for diagnosis; the next run owns and may replace it.

Failure injection is an internal Python test seam, not an environment variable
or CLI option. `transaction.run_release(..., fault_hook=None)` calls
`fault_hook(checkpoint)` only when a test directly supplies a callable.
Production `rail.py` always calls it with the default and exposes no way to set
it. This follows commit `60b6031`'s precedent: test seams remain internal and
never enter installed/public C++ headers or operator interfaces.

Named checkpoints are:

* `before-construction`;
* `after-dependency-acquisition`;
* `after-build`;
* `after-static-stage-gate`;
* `after-archive-creation`;
* `after-static-extracted-gate`;
* `after-runtime-gate:<gate-name>` for each Fedora, Tumbleweed, or native-macOS
  gate;
* `after-manifest-creation`;
* `before-promotion`;
* `after-promotion:<archive|archive-sha256|manifest|manifest-sha256>`.

Tests inject a dedicated exception at every checkpoint and a move failure for
each promotion position, then assert destination absence, unrelated sentinel
preservation, and staging ownership.

**Files touched:** add `release_rail/transaction.py` and tests; replace
`release-linux-x86_64.sh` with D9's driver; update authority and docs.

## D7 — Three-target set validator

**Decision.** `rail.py validate-set --dist PATH --version VERSION` takes one
directory and one exact release version. It discovers only regular manifest
files matching the authority-derived three manifest basenames for that
version; it then derives the other three quartet paths from each manifest
basename. Symlinks are rejected for all quartet files.

Before cross-target comparison it:

* rejects any matching release artifact/sidecar whose target/basename is not
  one of the three authority targets;
* requires exactly one manifest and one complete quartet per target;
* verifies manifest schema/target/filename/member inventory against authority;
* recomputes archive and manifest hashes, verifies both sidecars' complete
  two-space format and basenames, checks manifest artifact hash/size, and
  verifies archive members, types, links, and ordering.

It compares these fields across all three manifests:

* `schema_version`;
* `release.version` and `release.sol_revision`;
* `source.commit`, `source.upstream_base_commit`,
  `source.sol_series_commits`, and `source.source_date_epoch`;
* the complete `dependency_pins` value;
* `build_inputs.ca_snapshot`;
* `build_inputs.archive` (format, xz preset, threads).

Target identity, architecture/ABI, member inventory, build/gate images, artifact
name/hash/size, and native tool versions are intentionally target-specific and
are checked against authority rather than compared for equality.

Exact error vocabulary:

* `missing target: <target>`;
* `duplicate target: <target>: <manifest-a>, <manifest-b>`;
* `unknown target: <target>: <path>`;
* `extra release file: <path>`;
* `incomplete quartet: <target>: missing <comma-separated basenames>`;
* `quartet hash mismatch: <target>: <archive|archive sidecar|manifest|manifest sidecar>: expected <value>, got <value>`;
* `quartet layout mismatch: <target>: <field>: expected <value>, got <value>`;
* `cross-target mismatch: <field>: <target-a>=<JSON value>, <target-b>=<JSON value>[, ...]`.

Every cross-field error names the full dotted field and all disagreeing targets
and JSON-rendered values. Discovery accumulates deterministic, target-sorted
structural errors before returning nonzero; corrupt JSON is
`invalid manifest: <path>: <reason>`.

**Files touched:** add `release_rail/set_validator.py`,
`sol/release/tests/test_set_validator.py`; update CLI and operator docs.

## D8 — Commit grouping

The implementation is split into reviewable commits in dependency order:

1. **`build: support native arm64 Linux and macOS builds`**
   — `nv-attestation-sdk-cpp/CMakeLists.txt`,
   `nv-attestation-cli/CMakeLists.txt`. Explicit native OpenSSL targets,
   Darwin-only link/install-name/rpath/deployment settings, and necessary
   Apple-clang conditions. No `sol` naming or files.
2. **`sol: add three-target release authority and binary gates`**
   — `sol/release/targets.toml`, three `allowlists/*.txt`,
   `sol/release/rail.py`, package authority/ELF/Mach-O/gate/fixture modules and
   their tests; delete `release.env`, `dt-needed.allow`, `gate-artifact.sh`, and
   `binutils-wrapper.sh`.
3. **`sol: add deterministic transactional release construction`**
   — package archive/manifest/transaction modules and tests,
   `sol/release/release.sh`, `sol/release/runtime-gate.sh`; delete
   `release-linux-x86_64.sh` and `generate-manifest.py`.
4. **`sol: validate complete three-target release sets`**
   — package set-validator module/CLI and tests.
5. **`sol: wire release-rail tests into ci`**
   — `Makefile`, `sol/ci/Containerfile` only if its authority input changes,
   and any test-discovery glue.
6. **`sol: document three-target release operation`**
   — this design record, the operator document, and any supersession pointer in
   `sol/notes/design.md`.

Generated artifacts and binary fixtures are in no commit.

## D9 — Ordered `make ci` and operator entry point

**Decision.** The documented entry point is:

```text
make release TARGET=linux-aarch64
```

`TARGET` is mandatory. Both `make release` without `TARGET` and
`./sol/release/release.sh` without its positional target fail before mutation,
list all three valid IDs, name the host-compatible ID, and give the concrete
recovery command `make release TARGET=<compatible-id>`. `release` is a thin
passthrough to `./sol/release/release.sh "$(TARGET)"`; the script remains
directly usable for diagnostics and validates the native host predicate before
mutation. `release-linux-x86_64` is deleted.

The relevant Makefile shape is exactly:

```text
.PHONY: image rail-test ci ci-container test release

RAIL := python3 sol/release/rail.py
HOST_TARGET ?=

rail-test:
	python3 -m unittest discover -s sol/release/tests -p 'test_*.py'
	shellcheck $$(find sol -type f -name '*.sh' -print | sort)

ci:
	$(MAKE) rail-test
	$(MAKE) ci-container TARGET="$(TARGET)"

ci-container: image
	<the existing curl-handle guard and container build/test recipe>

test: ci

release:
	@test -n "$(TARGET)" || { \
		$(RAIL) authority missing-release-target; exit $$?; \
	}
	./sol/release/release.sh "$(TARGET)"
```

The two recursive Make invocations are separate recipe lines run sequentially;
the second cannot begin until `rail-test` succeeds, including under `make -j`.
`rail-test` is standalone and uses neither Podman nor an image build.
ShellCheck covers every `sol/**/*.sh` at default severity. The obsolete
`release-linux-x86_64.sh` is deleted. The only permitted directive is
`# shellcheck source=<actual sourced file>` where static source resolution
genuinely needs it; there are no severity suppressions.

`make image` remains the existing pinned-container build for Linux. On macOS,
`make ci` is not the lode CI path and `make image` reports “no build image for
macos-arm64”; native macOS operators use `make release`.

**Files touched:** `Makefile`, new `sol/release/release.sh`, delete
`sol/release/release-linux-x86_64.sh`, package CLI/authority, tests, and
operator docs.

## D10 — Per-target runtime gates

**Decision.** `sol/release/runtime-gate.sh` is one POSIX-shell implementation
used directly on macOS and bind-mounted unchanged into Linux gate containers.
The Python driver supplies the target, extracted root, exact quartet paths, and
authority-expanded member/type/count arguments; the shell does not parse TOML.
Common functions check layout, symlink targets, archive/sidecar/manifest hashes,
`nvattest --help`, and the eager invalid `--ca-bundle` failure with both path
and tier text. A small target switch changes only process launch:

* Linux: `LD_LIBRARY_PATH=lib ./bin/nvattest`;
* macOS: `./bin/nvattest`, relying on the asserted
  `@executable_path/../lib` RPATH.

The hash helper uses `sha256sum` when available and `shasum -a 256` on macOS,
normalizing to the first lowercase hash token before comparison. Sidecar
format itself remains authority-independent and is validated byte-for-byte.

Per target:

* `linux-x86_64` runs static gates on the x86_64 host, then runtime/layout/hash
  gates in both x86_64 Fedora and Tumbleweed child-manifest containers.
* `linux-aarch64` runs the same static and two container gates with arm64 child
  manifests, on a native aarch64 Linux operator host. It is never run on this
  x86_64 lode.
* `macos-arm64` runs static gates, `--help`, eager bad-CA, exact layout/link
  counts, and quartet hash checks directly on its native arm64 Mac. It has no
  container gates.

Operator-doc sentence:

> The lode runs format-independent rail tests and synthesized ELF/Mach-O gates,
> and may run the native linux-x86_64 release; it does not build or runtime-test
> linux-aarch64 or macos-arm64 artifacts, which must be released and gated on
> their matching native hosts.

Release reports record the names of gates actually completed. A target cannot
promote unless every runtime gate in its authority record completed.

**Files touched:** add `sol/release/runtime-gate.sh` and shell/Python tests;
update transaction driver, authority, Makefile, and operator docs.

## Reproducibility claim

> For the same target, on the same host, with the same pinned toolchain and
> complete pinned inputs, two builds produce byte-identical archives and
> sidecars; cross-host and cross-OS byte identity is not claimed.

The double-construction fixture test covers every target authority record using
fixed GNU tar, xz preset 6, and one xz thread.

## Authored, not natively verified

This design stage runs no builds or validation. The following require later
native execution:

* the aarch64 manylinux build and its two arm64 bare-container gates;
* the macOS arm64 CMake build, exact dylib/symlink chain, load commands, and
  native smoke gates;
* Apple clang/OpenSSL `darwin64-arm64-cc`, SDK zlib, GNU tar, and xz tool-version
  preflight;
* same-host double-build archive/quartet identity for aarch64 Linux and macOS;
* atomic rollback behavior under real filesystem move failures.

Part 3 completed the native x86_64 end-to-end build, both bare-container gates,
and same-host byte-identical double construction. The remaining entries above
are still authored and statically gated only.

## Risks and settled-ruling assessment

No ruling is technically wrong. Two consequences must remain visible:

* “arm64 macOS with Xcode CLT” is not by itself sufficient for the selected
  deterministic archive implementation; the native host also needs
  authority-pinned GNU tar and xz.
* Native-only construction deliberately gives up cross-host build flexibility.
  Autoconf/Rust cross plumbing must not leak into this scope, and the driver
  must fail rather than silently cross.

The main implementation risks are CMake's exact Darwin install-name/symlink
behavior, compiler/tool version-output normalization, Podman's foreign-child
handling despite the native-host rule, and rollback under unusual filesystem
errors. Each has an explicit native or injected test above.
