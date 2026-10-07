# Build-host path hygiene (2026-10-03)

sol.5 pointed OpenSSL's module and engine roots at the inert `/nvat-openssl`
prefix. Other build-host paths were still in every published archive. This
note records what was left, which of it could be loaded, and the work sol.6
did about it (see [Done in sol.6](#done-in-sol6) at the end).

## What sol.5 still carries

Measured with `strings -a` over every member of the three published sol.5
archives:

| family | where | example |
|---|---|---|
| libxml2 default catalog | each library, once | `file:///src/build/release/libxml2-install/etc/xml/catalog` (Linux); `file:///Users/<build-account>/<build-dir>/build/release/libxml2-install/etc/xml/catalog` (macOS) |
| build root | each library, 24–65 strings | regorus panic locations under `<binary dir>/_deps/regorus-src/` |
| Cargo home | each library, 186–319 strings | panic locations under `<CARGO_HOME>/registry/src/` |
| source root | library and CLI, every target | `__FILE__` under `/src/nv-attestation-sdk-cpp/src/` (Linux) or the macOS checkout root |

The C/C++ source paths survive because the existing
`-ffile-prefix-map=${CMAKE_SOURCE_DIR}/src/=` does not strip them on any
target. Its compiler guard (`GNU` or `Clang`) also skips `AppleClang`.

## The catalog is not a load path today

libxml2 2.11.9 reads a catalog only from its external-entity loader, and only
for a resource that does not exist locally. The SDK has one XML parse,
`RimDocument::create_from_rim_data` with `XML_PARSE_PEDANTIC |
XML_PARSE_NONET`. xmlsec's default parse options are `XML_PARSE_NONET |
XML_PARSE_NODICT | XML_PARSE_HUGE`, and one site adds `XML_PARSE_RECOVER`.
None of these reaches that loader, and neither the SDK nor xmlsec 1.2.39 calls
a catalog API. We linked a harness against the vendored static libxml2 and
gave it a document with an external DTD, an external parameter entity and an
external general entity, all pointing at missing files. Under both parse modes
it touched none of them and no catalog, with or without `XML_CATALOG_FILES`.
The control mode (`+ XML_PARSE_DTDLOAD | XML_PARSE_NOENT`) read the compiled
default catalog, opened the environment catalog, and returned the catalog's
rewritten content.

**Tripwire.** The catalog becomes a read root if any parse here or in xmlsec
gains `DTDLOAD`, `NOENT`, `DTDVALID` or `DTDATTR`, or if anything calls a
libxml2 catalog function. At that point this is a security fix, not hygiene.
Item 1 below removes the tripwire.

The panic-location and `__FILE__` strings are formatted into messages and never
opened. They are fixed anyway, for two reasons. Item 3's gate then works as a
plain substring test, and the macOS bytes stop depending on the build account
and directory.

## Work for the next Sol revision

1. **libxml2 `--without-catalog`** in `ExternalProject_Add(libxml2_external …)`.
   Prove that xmlsec still configures and links on all three targets.
2. **Remap every build-host root at compile time.** For C and C++, map the
   source root and the binary dir with `-ffile-prefix-map`. Do it for every
   compiler ID, `AppleClang` included, in both the SDK and CLI CMake files.
   For Rust, add `--remap-path-prefix` for the binary dir and for `CARGO_HOME`
   (default `~/.cargo`) on the `regorus_ffi` Corrosion target. Then re-measure
   the vendored autoconf dependencies.
3. **A build-root gate.** The driver passes the gate this build's source root,
   binary dir, `CARGO_HOME` and `$HOME`, and the gate refuses any of them found
   as a substring of any archive member. The existing static denylists stay.
   Run it on the sol.5 archives with sol.5's roots and watch it fail before
   anyone cites it as coverage.
4. **An ELF RUNPATH gate.** Teach `release_rail/elf.py` to read `DT_RUNPATH`
   and `DT_RPATH`. `targets.toml` names the exact executable runpath
   (`$ORIGIN/../lib`), the way it names `macho_rpath`. The gate refuses any
   other value, including an empty entry, and refuses any runpath on a library.
   Run it on sol.3's `bin/nvattest`, whose runpath is
   `/src/build/release/nv-attestation-sdk-build:`, and watch it fail.
5. **Acceptance.** `strings -a` over every member of each new archive finds
   none of the build roots and no `etc/xml/catalog`. Use sol.5 as the positive
   control. Then run a live content-free appraisal on all three native hosts.
   The current confidential-processing image checks NVIDIA status online, and
   that path (curl, the CA configuration, OCSP) is built separately for each
   target.

## Done in sol.6 (2026-10-07)

sol.6 opened for the OpenSSL 3.6.4 and curl 8.22.0 security updates and carries
all five items.

1. libxml2 is configured `--without-catalog` on Linux and macOS; the Windows
   build already used `LIBXML2_WITH_CATALOG=OFF`. The tripwire above is gone
   with the code.
2. `nv-attestation-sdk-cpp/cmake/nvat_host_path_remap.cmake` maps the
   repository root and the CMake binary directory to `.` for every GNU, Clang
   and AppleClang C/C++ target, from both the CLI and the SDK CMake files, and
   adds `--remap-path-prefix` for the repository root, the binary directory and
   the Cargo home (to `cargo-home`) to the `regorus_ffi` RUSTFLAGS, which
   reach every crate in its graph. On macOS the linker also writes a debug map
   (N_OSO stabs) naming each linked object that carries debug information, the
   Rust standard-library objects in `libregorus_ffi.a`, by real absolute path;
   `-oso_prefix` strips the checkout from it. The build-root gate found those
   five entries on the first sol.6 macOS build. The vendored autoconf projects
   are left alone: OpenSSL records its CFLAGS in the library, so a remap flag
   there would embed the path it removes.
3. The build-root gate (`gate.gate_build_roots`) runs on the staged and the
   extracted archive. A root with fewer than two path components also matches
   ordinary relative paths (`regorus-src/src/...`), so the Linux build now runs
   under `/nvat-sol-release/src` with `HOME=/nvat-sol-release/home` and
   `CARGO_HOME=/nvat-sol-release/home/.cargo` instead of `/src` and `/root`;
   the host checkout, home and Cargo home are refused too. Falsified on the
   served sol.5 archives: red on `/src/build/release` in both Linux libraries
   (35 occurrences each) and on the macOS build directory in `bin/nvattest`.
4. `release_rail/elf.py` reads `DT_SONAME`, `DT_RPATH` and `DT_RUNPATH`. A
   library (it has a `DT_SONAME`) carries no loader path; the executable carries
   exactly `elf_runpath`; `DT_RPATH` and empty entries are refused. Falsified on
   sol.3's `bin/nvattest` (`/src/build/release/nv-attestation-sdk-build:`):
   red. `validate-set` applies it too.
5. Acceptance is recorded with the release, not here.
