# Build-host path hygiene (2026-10-03)

sol.5 pointed OpenSSL's module and engine roots at the inert `/nvat-openssl`
prefix. Other build-host paths are still in every published archive. This note
records what is left, which of it can be loaded, and the work the next Sol
revision carries. **Whatever the reason a revision is opened, it carries this
work.**

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
