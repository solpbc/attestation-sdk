# nvattest macOS native system-link closure prep

Research captured on the Linux x86_64 lode
`/home/extro/.hopper/worktrees/d54akj4f` on 2026-07-26. The repository tip was
`b75e95ae0c08ac6eaa05673a0cf227b8723e2b58`. No native macOS link was
attempted. No product CMake, product source, test, README, authority, or
allowlist file was changed. The sole repository file created is this note.
Measurement scratch was confined to `/tmp/nvat-mac-link-research` and removed
after capture.

The current production path is:

* The CLI resolves the Apple toolchain before `project()`, validates the
  architecture immediately afterward, creates `nvattest`, and either imports
  installed nvat or nests the SDK (`nv-attestation-cli/CMakeLists.txt:1-8,31-42,54-107`).
  Embedded mode aliases real target `nvat` as `nvat::nvat`; `nvattest` then
  links it `PRIVATE` with json and CLI11 (`:89-95,109-113`).
* The SDK creates imported targets for the vendored static OpenSSL, curl,
  LibXml2, and xmlsec artifacts (`nv-attestation-sdk-cpp/CMakeLists.txt:252-268,322-369`;
  `nv-attestation-sdk-cpp/cmake/Findxmlsec.cmake:22-56`). `xmlsec::xmlsec`
  has an interface edge to `LibXml2::LibXml2`
  (`Findxmlsec.cmake:38-45`), while `nvat` also links
  `LibXml2::LibXml2` directly (`CMakeLists.txt:479-497`).
* Shared target `nvat` links all dependencies `PRIVATE`; fmt and spdlog are
  linked by `$<TARGET_FILE:...>`, while `regorus_ffi` is the imported static
  target created by Corrosion (`CMakeLists.txt:479-500`;
  `sol/release/tests/cmake_support.py:59-74`).
* Installation exports only `nvat`, installs two find modules, and generates
  `nvatConfig.cmake` (`nv-attestation-sdk-cpp/CMakeLists.txt:503-554`).
  The config nevertheless eagerly calls `find_dependency` for CURL, LibXml2,
  OpenSSL, spdlog, and xmlsec before loading the export
  (`nv-attestation-sdk-cpp/cmake/Config.cmake.in:1-13`).
* The hermetic graph used below is the existing
  `warning_fixture_prepare()`/`production_configure()` path. It supplies real
  target shapes without network access, supports a project include, requests
  File API codemodel v2, and returns the generated build
  (`sol/release/tests/cmake_support.py:59-137,194-240,253-272`).

## Provisioned lode and baseline

The three successful downloads and stable installations were:

| tool/archive | source | SHA256 | installed/resolved paths |
| --- | --- | --- | --- |
| CMake 3.31.10, `cmake-3.31.10-linux-x86_64.tar.gz` | `https://cmake.org/files/v3.31/cmake-3.31.10-linux-x86_64.tar.gz` | `3cb3dd247b6a1de2d0f4b20c6fd4326c9024e894cebc9dc8699758887e566ca7` | prefix `/home/extro/.local/opt/cmake-3.31.10`; `/home/extro/.local/bin/cmake` resolves to `/home/extro/.local/opt/cmake-3.31.10/bin/cmake`; `/home/extro/.local/bin/ctest` resolves to `/home/extro/.local/opt/cmake-3.31.10/bin/ctest` |
| ShellCheck 0.10.0, `shellcheck-v0.10.0.linux.x86_64.tar.xz` | `https://github.com/koalaman/shellcheck/releases/download/v0.10.0/shellcheck-v0.10.0.linux.x86_64.tar.xz` | `6c881ab0698e4e6ea235245f22832860544f17ba386442fe7e9d629f8cbedf87` | prefix `/home/extro/.local/opt/shellcheck-v0.10.0`; `/home/extro/.local/bin/shellcheck` resolves to `/home/extro/.local/opt/shellcheck-v0.10.0/shellcheck` |
| isolated CMake 3.11.4, `cmake-3.11.4-Linux-x86_64.tar.gz` | `https://cmake.org/files/v3.11/cmake-3.11.4-Linux-x86_64.tar.gz` | `6dab016a6b82082b8bcd0f4d1e53418d6372015dd983d29367b9153f1a376435` | prefix `/home/extro/.local/opt/cmake-3.11.4`; `NVAT_TEST_CMAKE_311=/home/extro/.local/opt/cmake-3.11.4/bin/cmake` |

The archives were downloaded only to
`/tmp/nvat-mac-link-research` for verification and extraction. Exact version
output:

```text
$ cmake --version
cmake version 3.31.10

CMake suite maintained and supported by Kitware (kitware.com/cmake).

$ shellcheck --version
ShellCheck - shell script analysis tool
version: 0.10.0
license: GNU General Public License, version 3
website: https://www.shellcheck.net

$ /home/extro/.local/opt/cmake-3.11.4/bin/cmake --version
cmake version 3.11.4

CMake suite maintained and supported by Kitware (kitware.com/cmake).

$ docker --version
Docker version 29.6.2, build dfc4efb

$ python3 sol/release/rail.py runtime select
docker
```

The explicitly requested full rail-test tail was:

```text
$ hop check -n 300 -- make rail-test
hop check: `make rail-test` exited 0
python3 -m unittest discover -s sol/release/tests -p 'test_*.py'
..........................................................................s.............................................
----------------------------------------------------------------------
Ran 120 tests in 12.018s

OK (skipped=1)
shellcheck $(find sol -type f -name '*.sh' -print | sort)
```

This exactly reconciles with the provisioned result in commit
`b75e95a…` (120 passed, one optional 3.11 skip). The scope's unprovisioned
106-run/27-`FileNotFoundError: cmake` result describes the missing-tool state
before Step 0; provisioning removed those missing-CMake failures. The optional
3.11 arm still skipped in `make rail-test` because that invocation did not set
`NVAT_TEST_CMAKE_311`; Q5 invokes the isolated engine directly.

The dependency before-side was:

```text
$ python3 sol/release/generate-dependencies.py --root . \
    --json /tmp/nvat-mac-link-research/baseline/pins-before.json \
    --notices /tmp/nvat-mac-link-research/baseline/notices-before.md
generated 12 dependency pins
$ sha256sum /tmp/nvat-mac-link-research/baseline/pins-before.json
88af736d64debbf044e4d7a69f78412ea5f611f116d57e19027de5f66cbf128b  /tmp/nvat-mac-link-research/baseline/pins-before.json
```

The complete ordered pin content is:

```text
CLI11 git https://github.com/CLIUtils/CLI11.git v2.6.1
Corrosion git https://github.com/corrosion-rs/corrosion.git 6be991bb34c348dfb8344be22f3606288ea5c7fd
curl_external archive https://github.com/curl/curl/releases/download/curl-7_88_1/curl-7.88.1.tar.gz sha256:cdb38b72e36bc5d33d5b8810f8018ece1baa29a8f215b4495e495ded82bbf3c7
fmt git https://github.com/fmtlib/fmt.git 10.2.1
googletest git https://github.com/google/googletest.git v1.16.0
json archive https://github.com/nlohmann/json/releases/download/v3.12.0/json.tar.xz sha256:42f6e95cad6ec532fd372391373363b62a14af6d771056dbfc86160e6dfff7aa
jwt-cpp git https://github.com/Thalhammer/jwt-cpp.git v0.7.1
libxml2_external archive https://download.gnome.org/sources/libxml2/2.11/libxml2-2.11.9.tar.xz sha256:780157a1efdb57188ec474dca87acaee67a3a839c2525b2214d318228451809f
openssl_external archive https://github.com/openssl/openssl/releases/download/openssl-3.6.1/openssl-3.6.1.tar.gz sha256:b1bfedcd5b289ff22aee87c9d600f515767ebf45f77168cb6d64f231f518a82e
regorus git https://github.com/microsoft/regorus.git regorus-v0.4.0
spdlog git https://github.com/gabime/spdlog.git v1.14.1
xmlsec_external archive https://github.com/lsh123/xmlsec/releases/download/xmlsec-1_2_39/xmlsec1-1.2.39.tar.gz sha256:15f2f55ea5968e578fcd24b3b427e553876c86c147dc7f03923e98fc2768a1fa
```

## Q1 — `PRIVATE` propagation from shared `nvat`

The real hermetic CLI→SDK configure requested a codemodel and used a
`CMAKE_PROJECT_INCLUDE` scratch injection. At the end of the SDK directory it
added imported static archive `nvat_q1_marker` as a `PRIVATE` item on real
shared target `nvat`. No repository copy was edited. Recorded target
properties:

```text
LINK_LIBRARIES=xmlsec::xmlsec;xmlsec::xmlsec-openssl;OpenSSL::SSL;OpenSSL::Crypto;CURL::libcurl;LibXml2::LibXml2;ZLIB::ZLIB;$<TARGET_FILE:spdlog>;$<TARGET_FILE:fmt>;own-jwt-cpp;nlohmann_json::nlohmann_json;regorus_ffi;nvat_q1_marker
INTERFACE_LINK_LIBRARIES=_q1_interface-NOTFOUND
```

Thus a `PRIVATE` item on this shared library creates no
`$<LINK_ONLY:nvat_q1_marker>` interface entry. That agrees with the installed
CMake contract: `PRIVATE` items are linked to the target but are not made part
of its link interface
(`/home/extro/.local/opt/cmake-3.31.10/share/cmake-3.31/Help/command/target_link_libraries.rst:150-168`).
An actual `INTERFACE_LINK_LIBRARIES` entry, including an explicitly authored
`$<LINK_ONLY:...>`, would be part of the transitive closure
(`/home/extro/.local/opt/cmake-3.31.10/share/cmake-3.31/Help/prop_tgt/INTERFACE_LINK_LIBRARIES.rst:4-24`;
`Help/manual/cmake-generator-expressions.7.rst:1782-1796`); the `PRIVATE`
call did not create one here.

The actual flattened codemodel `link.commandFragments` vectors were:

```text
nvat:
[
  "../xmlsec-install/lib/libxmlsec1.a",
  "../xmlsec-install/lib/libxmlsec1-openssl.a",
  "../openssl-install/lib/libssl.a",
  "../openssl-install/lib/libcrypto.a",
  "../curl-install/lib/libcurl.a",
  "../libxml2-install/lib/libxml2.a",
  "/usr/lib/x86_64-linux-gnu/libz.so",
  "../_deps/spdlog-build/libspdlog.a",
  "../_deps/fmt-build/libfmt.a",
  "libregorus_ffi.a",
  "/tmp/tmpluzppmxu/marker/libnvat_q1_marker.a",
  "../xmlsec-install/lib/libxmlsec1.a",
  "../libxml2-install/lib/libxml2.a",
  "../openssl-install/lib/libssl.a",
  "../openssl-install/lib/libcrypto.a",
  "-ldl",
  "-lz",
  "-lpthread"
]

nvattest:
[
  "-O3",
  "-DNDEBUG",
  "-Wl,-rpath,/tmp/tmpluzppmxu/build/nv-attestation-sdk-build:",
  "nv-attestation-sdk-build/libnvat.so.1.2.2"
]
```

The corresponding generated executable link file was:

```text
$ cat build/CMakeFiles/nvattest.dir/link.txt
/usr/bin/c++ -O3 -DNDEBUG -Wl,--dependency-file=CMakeFiles/nvattest.dir/link.d CMakeFiles/nvattest.dir/src/main.cpp.o CMakeFiles/nvattest.dir/src/version.cpp.o CMakeFiles/nvattest.dir/src/attest.cpp.o CMakeFiles/nvattest.dir/src/collect_evidence.cpp.o CMakeFiles/nvattest.dir/src/utils.cpp.o CMakeFiles/nvattest.dir/src/logging.cpp.o -o nvattest  -Wl,-rpath,/tmp/tmpluzppmxu/build/nv-attestation-sdk-build: nv-attestation-sdk-build/libnvat.so.1.2.2
```

The marker is present on `nvat` and absent from both independent
`nvattest` surfaces. AC1's “nvattest contains neither as a direct link item”
is therefore satisfied by `PRIVATE` shared-library linkage alone. For the
additional static-owner ordering requirement, Q3 shows that the system item
belongs on the imported static owner's `INTERFACE_LINK_LIBRARIES`; because
that owner remains a private dependency of shared `nvat`, the item reaches
`nvat` without reaching `nvattest`.

**Observed on this lode:** successful real hermetic configure; raw target
properties; both codemodel vectors; generated `nvattest` `link.txt`; marker
containment. **Unobserved on this lode:** Apple generator/linker treatment and
a successful native macOS link.

## Q2 — Install/export leakage and current clean-prefix baseline

First, the unmodified hermetic SDK build was installed with real
`cmake --install` after supplying only the configure-generated shared-library
paths that the install script requires. The exact install completed:

```text
install.returncode=0
-- Install configuration: "Release"
-- Installing: /tmp/tmp0fbyrcze/clean-prefix/lib/libnvat.so.1.2.2
-- Installing: /tmp/tmp0fbyrcze/clean-prefix/lib/libnvat.so.1
-- Installing: /tmp/tmp0fbyrcze/clean-prefix/lib/libnvat.so
-- Installing: /tmp/tmp0fbyrcze/clean-prefix/include/nvat.h
-- Installing: /tmp/tmp0fbyrcze/clean-prefix/share/cmake/nvat/nvatTargets.cmake
-- Installing: /tmp/tmp0fbyrcze/clean-prefix/share/cmake/nvat/nvatTargets-release.cmake
-- Installing: /tmp/tmp0fbyrcze/clean-prefix/share/cmake/nvat/Modules/FindLibXml2.cmake
-- Installing: /tmp/tmp0fbyrcze/clean-prefix/share/cmake/nvat/Modules/Findxmlsec.cmake
-- Installing: /tmp/tmp0fbyrcze/clean-prefix/share/cmake/nvat/nvatConfig.cmake
-- Installing: /tmp/tmp0fbyrcze/clean-prefix/share/cmake/nvat/nvatConfigVersion.cmake
```

The generated export has only the include interface:

```cmake
add_library(nvat::nvat SHARED IMPORTED)

set_target_properties(nvat::nvat PROPERTIES
  INTERFACE_INCLUDE_DIRECTORIES "${_IMPORT_PREFIX}/include"
)
```

Its release fragment points only at
`${_IMPORT_PREFIX}/lib/libnvat.so.1.2.2`. In contrast, generated
`nvatConfig.cmake` exactly preserves the five eager dependencies from
`Config.cmake.in:7-11`:

```cmake
find_dependency(CURL REQUIRED)
find_dependency(LibXml2 REQUIRED)
find_dependency(OpenSSL REQUIRED)
find_dependency(spdlog REQUIRED)
find_dependency(xmlsec REQUIRED)

include("${CMAKE_CURRENT_LIST_DIR}/nvatTargets.cmake")
```

A minimal clean-prefix consumer failed before it could load the otherwise
self-contained export:

```text
consumer.configure.returncode=1
CMake Error at /home/extro/.local/opt/cmake-3.31.10/share/cmake-3.31/Modules/FindPackageHandleStandardArgs.cmake:233 (message):
  Could NOT find CURL (missing: CURL_LIBRARY CURL_INCLUDE_DIR)
Call Stack (most recent call first):
  /home/extro/.local/opt/cmake-3.31.10/share/cmake-3.31/Modules/FindCURL.cmake:203 (find_package_handle_standard_args)
  /home/extro/.local/opt/cmake-3.31.10/share/cmake-3.31/Modules/CMakeFindDependencyMacro.cmake:76 (find_package)
  /tmp/tmp0fbyrcze/clean-prefix/share/cmake/nvat/nvatConfig.cmake:14 (find_dependency)
  CMakeLists.txt:3 (find_package)
```

To prove the spdlog-specific defect rather than stopping at the lode's first
missing package, a second consumer supplied scratch config stubs for only
CURL, LibXml2, and OpenSSL. It then failed at the next dependency:

```text
consumer.with_first_three_stubbed.returncode=1
CMake Error at /home/extro/.local/opt/cmake-3.31.10/share/cmake-3.31/Modules/CMakeFindDependencyMacro.cmake:76 (find_package):
  By not providing "Findspdlog.cmake" in CMAKE_MODULE_PATH this project has
  asked CMake to find a package configuration file provided by "spdlog", but
  CMake did not find one.

  Could not find a package configuration file provided by "spdlog" with any
  of the following names:

    spdlogConfig.cmake
    spdlog-config.cmake
```

This is inherent in today's package: fmt/spdlog installation is disabled
(`nv-attestation-sdk-cpp/CMakeLists.txt:124-146`), their archive files are
linked directly (`:490-493`), and no spdlog package is installed by
`:503-554`, yet the config requires it.

For the change-side leakage probe, a scratch project include appended distinct
sentinel items to imported `regorus_ffi` and
`LibXml2::LibXml2.INTERFACE_LINK_LIBRARIES`, then repeated the real install:

```text
fixture.configure.returncode=0
install.returncode=0
nvat link sentinel tail:
-lnvat_q2_libxml_system -lnvat_q2_regorus_system
nvatTargets.contains_regorus_sentinel=False
nvatTargets.contains_libxml_sentinel=False
exported nvat property block:
set_target_properties(nvat::nvat PROPERTIES
  INTERFACE_INCLUDE_DIRECTORIES "${_IMPORT_PREFIX}/include"
)
```

Therefore: (a) today, clean-prefix `find_package(nvat CONFIG REQUIRED)` already
fails on dependencies that the exported shared target does not expose, first
CURL on this host and demonstrably spdlog once the preceding three are
available; (b) adding system-link interfaces to imported static owners makes
them effective on `nvat` but does **not** newly leak them into
`nvatTargets.cmake`, so it creates no new package-consumer failure. D5 should
take the “no new export leak” branch and keep any repair of the already-broken
config separate from this closure change.

**Observed on this lode:** real install, complete relevant generated config
and export content, clean-prefix failure, controlled spdlog reachability, and
mutated-interface non-leakage. **Unobserved on this lode:** a consumer with
real installations of all five requested packages or an installed macOS
package.

## Q3 — Order and cardinality

The real graph has two paths to `LibXml2::LibXml2`: direct from `nvat`
(`nv-attestation-sdk-cpp/CMakeLists.txt:488`) and through
`xmlsec::xmlsec` (`nv-attestation-sdk-cpp/cmake/Findxmlsec.cmake:44`).
The scratch measurement attached `"-framework Foo"` to imported static
`regorus_ffi` and an imported `Iconv::Iconv`-shaped archive to
`LibXml2::LibXml2`. Actual codemodel library fragments:

```text
1: ../xmlsec-install/lib/libxmlsec1.a
2: ../xmlsec-install/lib/libxmlsec1-openssl.a
3: ../openssl-install/lib/libssl.a
4: ../openssl-install/lib/libcrypto.a
5: ../curl-install/lib/libcurl.a
6: ../libxml2-install/lib/libxml2.a
7: /usr/lib/x86_64-linux-gnu/libz.so
8: ../_deps/spdlog-build/libspdlog.a
9: ../_deps/fmt-build/libfmt.a
10: libregorus_ffi.a
11: ../xmlsec-install/lib/libxmlsec1.a
12: ../libxml2-install/lib/libxml2.a
13: /tmp/tmp8__a9mt4/q3/libq3-iconv.a
14: ../openssl-install/lib/libssl.a
15: ../openssl-install/lib/libcrypto.a
16: -ldl
17: -lz
18: -lpthread
19: -framework Foo
```

Flattened measurement:

```text
framework_pair_indices=[18]
iconv_indices=[12]
regorus_owner_indices=[9]
libxml_owner_indices=[5, 11]
framework_count=1
iconv_count=1
framework_after_owner=True
iconv_after_last_owner=True
```

The generated `nvat` link tail agreed byte-for-token:

```text
../xmlsec-install/lib/libxmlsec1.a ../xmlsec-install/lib/libxmlsec1-openssl.a ../openssl-install/lib/libssl.a ../openssl-install/lib/libcrypto.a ../curl-install/lib/libcurl.a ../libxml2-install/lib/libxml2.a /usr/lib/x86_64-linux-gnu/libz.so ../_deps/spdlog-build/libspdlog.a ../_deps/fmt-build/libfmt.a libregorus_ffi.a ../xmlsec-install/lib/libxmlsec1.a ../libxml2-install/lib/libxml2.a /tmp/tmp8__a9mt4/q3/libq3-iconv.a ../openssl-install/lib/libssl.a ../openssl-install/lib/libcrypto.a -ldl -lz -lpthread -framework Foo
```

CMake retains the LibXml owner archive twice, but deduplicates the imported
Iconv interface item to exactly one occurrence after the final LibXml archive.
It emits the framework pair exactly once and after its regorus owner archive.
Static-owner interfaces therefore provide both required order and cardinality
on this graph; a flat `nvat PRIVATE` append would not encode owner-relative
placement.

**Observed on this lode:** exact Linux codemodel and `link.txt` ordering,
counts, two LibXml owner occurrences, and one occurrence of each interface
item. **Unobserved on this lode:** whether AppleClang accepts those tokens or
links the corresponding native artifacts.

## Q4 — Discovery form and poisoning

The installed CMake implementation makes `find_package(Iconv)` unsuitable for
an exclusive selected-SDK boundary:

* `FindIconv` was added in 3.11, may select libc or an external library, and
  publishes `Iconv::Iconv`
  (`/home/extro/.local/opt/cmake-3.31.10/share/cmake-3.31/Modules/FindIconv.cmake:8-12,46-70`).
* If either cache input is already defined it skips the implicit-libc probe
  (`:91-126`), then ordinary `find_path`/`find_library` use all default search
  classes (`:128-148`). The resulting target copies the found/cached path
  verbatim into its interface (`:174-186`).
* `find_*` results are cached and skip later searches, and even a built-in
  `VALIDATOR` is skipped for cached results
  (`/home/extro/.local/opt/cmake-3.31.10/share/cmake-3.31/Help/command/FIND_XXX.txt:34-39,70-93,98-107`).

Measured Linux poisoning:

```text
-- Found Iconv: /tmp/nvat-mac-link-research/q4/opt/homebrew/lib/libiconv.dylib
-- Iconv_LIBRARY=/tmp/nvat-mac-link-research/q4/opt/homebrew/lib/libiconv.dylib
-- Iconv_INCLUDE_DIR=/tmp/nvat-mac-link-research/q4/opt/homebrew/include
-- Iconv::Iconv.INTERFACE_LINK_LIBRARIES=/tmp/nvat-mac-link-research/q4/opt/homebrew/lib/libiconv.dylib
-- explicit.preseeded=/tmp/nvat-mac-link-research/q4/opt/homebrew/lib/libiconv.dylib
-- explicit.after_clear=/tmp/nvat-mac-link-research/q4/Selected SDK/usr/lib/libiconv.so
```

This proves both critical cases: `-DIconv_LIBRARY=/opt/homebrew/...` is honored
verbatim by `FindIconv`, and an explicitly named `find_library` variable is
also bypassed if pre-seeded. After clearing that result and using only:

```cmake
find_library(
  NVAT_EXPLICIT_ICONV
  NAMES iconv libiconv
  NO_DEFAULT_PATH
  PATHS "${NVAT_APPLE_SDKROOT}/usr/lib"
)
```

the selected-SDK artifact won. `NO_DEFAULT_PATH` adds no other paths
(`Help/command/FIND_XXX.txt:121-123`), whereas default search includes
`CMAKE_PREFIX_PATH`, `CMAKE_LIBRARY_PATH`, `CMAKE_FRAMEWORK_PATH`, their
environment forms, system environment paths, platform paths, and final
`PATHS` (`:183-235`). `CMAKE_FIND_ROOT_PATH` otherwise re-roots all search
directories but searches non-rooted directories too by default
(`Help/command/FIND_XXX_ROOT.txt:1-29`).

Post-resolution containment is still mandatory because any `find_library`
result variable can be pre-seeded. The measured realpath/prefix check rejected
the poisoned result:

```text
-- resolved=/tmp/nvat-mac-link-research/q4/opt/homebrew/lib/libiconv.dylib
-- sdk=/tmp/nvat-mac-link-research/q4/Selected SDK
-- inside-index=-1
CMake Error at CMakeLists.txt:11 (message):
  selected-SDK validation rejected
  /tmp/nvat-mac-link-research/q4/opt/homebrew/lib/libiconv.dylib
```

On Darwin, `CMAKE_OSX_SYSROOT` both supplies `-isysroot` and helps `find_*`
locate SDK files
(`/home/extro/.local/opt/cmake-3.31.10/share/cmake-3.31/Help/variable/CMAKE_OSX_SYSROOT.rst:1-11`).
The platform module resolves it to an absolute path
(`/home/extro/.local/opt/cmake-3.31.10/share/cmake-3.31/Modules/Platform/Darwin-Initialize.cmake:305-325`)
and adds SDK framework and library locations, but it also retains user,
system, `/opt/homebrew`, MacPorts, and other prefixes
(`/home/extro/.local/opt/cmake-3.31.10/share/cmake-3.31/Modules/Platform/Darwin.cmake:144-206,249-274`).
`CMAKE_FRAMEWORK_PATH` is explicitly user/environment-controlled, while
`CMAKE_SYSTEM_FRAMEWORK_PATH` contains platform defaults
(`Help/variable/CMAKE_FRAMEWORK_PATH.rst:1-10`;
`Help/variable/CMAKE_SYSTEM_FRAMEWORK_PATH.rst:1-10`).

For CoreFoundation, unqualified `find_library(CoreFoundation)` is therefore
resolvable and returns a full `CoreFoundation.framework` path, which CMake
turns into `-framework CoreFoundation` plus an appropriate `-F` path
(`Help/command/find_library.rst:48-63`), but its default search can be poisoned.
A bare `"-framework CoreFoundation"` does no configure-time artifact
resolution at all; installed guidance confirms it delegates selection to the
linker (`Help/manual/cmake-toolchains.7.rst:692-705`). It therefore supplies
no resolved path to validate.

`LIBRARY_PATH` may alter compiler-discovered implicit link directories
(`Help/variable/CMAKE_LANG_IMPLICIT_LINK_DIRECTORIES.rst:29-37`), while
`LDFLAGS` seeds cached linker flags on the first configure
(`Help/envvar/LDFLAGS.rst:1-12`). Neither is an input to a
`NO_DEFAULT_PATH PATHS <selected-sdk>` lookup, though both reinforce why a
bare linker token is not an exclusive binding.

The form that survives all named AC3 poisoning vectors is therefore a
dedicated, cleared/local result variable for each artifact, an explicit
`find_library(... NO_DEFAULT_PATH PATHS
"${NVAT_APPLE_SDKROOT}/...")`, and a fail-closed canonical containment check
against `NVAT_APPLE_SDKROOT` before constructing/augmenting the imported
owner. It ignores `CMAKE_PREFIX_PATH`, Homebrew defaults, and environment
search paths; `LIBRARY_PATH`/`LDFLAGS` cannot choose its result; and a
pre-seeded cache value is rejected by the post-check. Use the resolved
CoreFoundation framework path rather than a bare framework token.

**Observed on this lode:** installed module/source behavior, generic
`NO_DEFAULT_PATH` selection, cache poisoning, and containment rejection on
Linux. **Unobserved on this lode:** actual `.tbd`/framework discovery inside a
macOS SDK, Darwin's generated `-F`/`-framework` command, and Apple linker
selection.

## Q5 — Real CMake 3.11 command inventory

The smallest plausible helper can remain within the declared 3.11 floor:

| command/feature | introduction/floor evidence |
| --- | --- |
| `include_guard(GLOBAL)` | 3.10 (`/home/extro/.local/opt/cmake-3.31.10/share/cmake-3.31/Help/command/include_guard.rst:1-36`) |
| `find_package(Iconv)` and `Iconv::Iconv` | module added in 3.11 (`Help/release/3.11.rst:150-163`); the installed 3.11.4 module creates the imported target (`/home/extro/.local/opt/cmake-3.11.4/share/cmake-3.11/Modules/FindIconv.cmake:101-132`) |
| setting `INTERFACE_LINK_LIBRARIES` on an imported target through `target_link_libraries` | 3.11 (`Help/release/3.11.rst:55-74`); direct `set_property` also ran in the fixture |
| optional `cmake_parse_arguments` | native command since 3.5 (`Help/release/3.5.rst:40-45`); not needed by the measured minimal helper |
| `$<LINK_ONLY:...>` if inspected but not authored | 3.1 (`Help/manual/cmake-generator-expressions.7.rst:1782-1796`) |
| `function`/`endfunction`, `if` (`DEFINED`, `TARGET`, `EXISTS`, `MATCHES`, numeric comparison), `set`/`unset`, `message(FATAL_ERROR)`, `find_library(NAMES/PATHS/NO_DEFAULT_PATH)`, `get_filename_component(REALPATH)`, `string(FIND)`, `list(APPEND/REMOVE_DUPLICATES/LENGTH/GET)`, `foreach(IN LISTS)`, `add_library(... IMPORTED GLOBAL)`, `set_property`, `get_target_property`, and `target_link_libraries(... PRIVATE ...)` | all predate the 3.11 floor and are present in the real 3.11.4 command manuals; every one used by the reduced fixture below executed successfully |

The isolated project included one guarded helper twice, ran
`find_package(Iconv REQUIRED)`, required the target, found a scratch
CoreFoundation archive only under a path containing a space with
`NO_DEFAULT_PATH`, canonicalized/validated it, put `Iconv::Iconv` on an
imported static owner's interface, linked that owner privately to a shared
library, and exercised the listed list/string/property operations. Real engine
output:

```text
$ /home/extro/.local/opt/cmake-3.11.4/bin/cmake \
    /tmp/nvat-mac-link-research/q5/source \
    "-DNVAT_APPLE_SDKROOT=/tmp/nvat-mac-link-research/q5/Selected SDK"
-- Performing Test Iconv_IS_BUILT_IN
-- Performing Test Iconv_IS_BUILT_IN - Success
-- Found Iconv: /usr/lib/x86_64-linux-gnu/libc.so
-- inventory.item=CoreFoundation
-- inventory.item=Iconv::Iconv
-- ENGINE=3.11.4
-- include_guard.count=1
-- Iconv_FOUND=TRUE
-- Iconv.target=TRUE
-- Iconv_LIBRARY=/usr/lib/x86_64-linux-gnu/libc.so
-- CoreFoundation=/tmp/nvat-mac-link-research/q5/Selected SDK/usr/lib/libCoreFoundation.a
-- owner.interface=Iconv::Iconv
-- inventory.length=2
-- inventory.first=CoreFoundation
-- Configuring done
-- Generating done

$ cat CMakeFiles/nvat.dir/link.txt
/usr/bin/cc -fPIC   -shared -Wl,-soname,libnvat.so -o libnvat.so CMakeFiles/nvat.dir/nvat.c.o "/tmp/nvat-mac-link-research/q5/Selected SDK/usr/lib/libCoreFoundation.a" -lc
```

The helper must avoid these verified post-floor traps:

```text
$ cmake-3.11.4 -P trap-list-prepend.cmake
CMake Error ... (list):
  list does not recognize sub-command PREPEND
returncode=1

$ cmake-3.11.4 -P trap-string-join.cmake
CMake Error ... (string):
  string does not recognize sub-command JOIN
returncode=1

$ cmake-3.11.4 -P trap-fetchcontent.cmake
CMake Error ... (FetchContent_MakeAvailable):
  Unknown CMake command "FetchContent_MakeAvailable".
returncode=1
```

The docs place `string(JOIN)` and `list(JOIN)` at 3.12 and
`list(PREPEND)` at 3.15
(`/home/extro/.local/opt/cmake-3.31.10/share/cmake-3.31/Help/command/string.rst:204-216`;
`Help/command/list.rst:85-89,163-170`). Also avoid
`target_link_options` (3.13), `file(REAL_PATH)` (3.19), `cmake_path` (3.20),
and `cmake_language(DEFER)` (3.19)
(`Help/command/target_link_options.rst:1-17`;
`Help/command/file.rst:668-681`; `Help/command/cmake_path.rst:1-10`;
`Help/command/cmake_language.rst:106-109`). Use
`list(INSERT value 0 ...)` if prepend behavior is needed,
`get_filename_component(... REALPATH)` for canonicalization, and ordinary
list iteration instead.

This does not repair the wider production graph. The CLI and SDK both call
unavailable `FetchContent_MakeAvailable`
(`nv-attestation-cli/CMakeLists.txt:22-29`;
`nv-attestation-sdk-cpp/CMakeLists.txt:50-64`), and the SDK also uses the
3.15-only `list(PREPEND)` at
`nv-attestation-sdk-cpp/CMakeLists.txt:252-256`. The real 3.11 trap above
confirms the first incompatibility; its `list(PREPEND)` trap confirms the
second. The helper can be 3.11-compatible without making a full production
configure 3.11-compatible.

**Observed on this lode:** a real 3.11.4 configure/generate/link-rule fixture,
`FindIconv`, `Iconv::Iconv`, global include guard, all listed helper
operations, and three expected incompatibility failures. **Unobserved on this lode:**
full production configure under 3.11 or any Darwin behavior under 3.11.

## Q6 — Recording-linker mechanism

Available proof mechanisms:

| mechanism | finding |
| --- | --- |
| stub linker binary | Fragile when CMake drives linking through the compiler: replacing `CMAKE_LINKER` alone does not necessarily replace `/usr/bin/c++` as the link driver. A fake compiler also contaminates compiler identification. |
| `CMAKE_<LANG>_LINK_EXECUTABLE` / `CMAKE_<LANG>_CREATE_SHARED_LIBRARY` | Deterministically owns the generated executable/shared rule and can place `<LINK_LIBRARIES>` in an observable argv. The variables are documented as link rule templates (`/home/extro/.local/opt/cmake-3.31.10/share/cmake-3.31/Help/variable/CMAKE_LANG_LINK_EXECUTABLE.rst:1-6`; `Help/variable/CMAKE_LANG_CREATE_SHARED_LIBRARY.rst:1-8`). It is intentionally synthetic linkage. |
| compiler launcher | `CMAKE_<LANG>_COMPILER_LAUNCHER` is a compile launcher, not the 3.11-compatible link seam (`Help/prop_tgt/LANG_COMPILER_LAUNCHER.rst:1-16`). The dedicated linker launcher was added only in 3.21 (`Help/variable/CMAKE_LANG_LINKER_LAUNCHER.rst:1-10`). |
| generated `link.txt` plus codemodel | Non-invasive and generator-authored. File API `commandFragments` are explicitly ordered and distinguish libraries/framework paths/flags (`Help/manual/cmake-file-api.7.rst:1035-1060`). Q1/Q3 prove presence, order, cardinality, and private reachability without executing a linker. |

The direct rule-override probe also worked. Its generated files were:

```text
nvat link.txt:
/tmp/nvat-mac-link-research/q6/hostile-link-recorder.sh  /tmp/nvat-mac-link-research/q6/libowner.a -framework Foo /tmp/nvat-mac-link-research/q6/libiconv.a

nvattest link.txt:
/usr/bin/c++ ... -o nvattest  -Wl,-rpath,/tmp/nvat-mac-link-research/q6/build libnvat.so
```

Building `nvat` invoked the hostile subprocess:

```text
build.returncode=2
[100%] Linking CXX shared library libnvat.so
NVAT_Q6_HOSTILE_LINKER_REACHED
gmake[3]: *** [CMakeFiles/nvat.dir/build.make:103: libnvat.so] Error 73

recorded argv:
/tmp/nvat-mac-link-research/q6/libowner.a
-framework
Foo
/tmp/nvat-mac-link-research/q6/libiconv.a
```

Recommendation: use both real production codemodel and `link.txt` as the
acceptance proof for tokens/order/private reachability. They prove generated
commands, not Apple linkage. Reserve a
`CMAKE_CXX_CREATE_SHARED_LIBRARY`/`CMAKE_CXX_LINK_EXECUTABLE` scratch override
for AC7 fault injection: unlike passive file reading, that option launches a
real hostile child which can emit its **own** unique marker and exit nonzero.
The release build occurs after transaction-owned staging exists
(`sol/release/release_rail/transaction.py:65-74`;
`sol/release/release_rail/driver.py:544-554`), so driving that recorder through
the patched `_build` seam proves the required transaction timing without
claiming an Apple link.

**Observed on this lode:** real generated link surfaces, deterministic rule
override, ordered argv capture, child-owned marker, and nonzero exit.
**Unobserved on this lode:** invocation by an Apple toolchain or successful
linkage of any Apple artifact.

## Q7 — Release-driver seam and combined diagnostic

`_preflight()` loads the sole authority, converts the requested ID to the
canonical compatible target dictionary, rejects dirty state, and captures
Apple evidence before returning that dictionary
(`sol/release/release_rail/driver.py:496-535`). The authority's closed IDs
include `macos-arm64` (`sol/release/release_rail/authority.py:13-15`), whose
record is Darwin/arm64 (`sol/release/targets.toml:66-91`).

The exact context seam is the first macOS `_run()` call inside `_build()`,
around the configure argv at `driver.py:263-284`. Wrap that call's
`ReleaseError` with canonical `target["id"]`, e.g.
`macos-arm64 native CMake configure failed`, while preserving the helper's
`FATAL_ERROR` as the cause/detail. This is preferable to `_preflight`: helper
CMake has not run there. It is also preferable to the second `_run()`:
successful configure would already have lost the configure-specific failure.

The ordering is proved directly:

1. `transaction.run()` creates only
   `dist/.staging/<target>-<version>` at
   `transaction.py:65-74`.
2. The builder acquires the CA, passes
   `after-dependency-acquisition`, and calls `_build`
   (`driver.py:544-554`).
3. `_build` runs configure at `:268-284`; only after success does it invoke
   `cmake --build` at `:285-289`. A helper `FATAL_ERROR` therefore precedes
   compilation.
4. Staging the products begins only after `checkpoint("after-build")`
   (`driver.py:554-555`).
5. Final artifact paths are first mutated by `os.link` during promotion only
   after the whole builder returns (`transaction.py:74-90`). A configure
   failure therefore precedes every final-path mutation, while still occurring
   after transaction staging began.

Today `_run()` calls `subprocess.run(check=True)` without output capture and
converts `CalledProcessError` to only
`command failed: <argv>: <error>` (`driver.py:27-31`). Consequently CMake's
`FATAL_ERROR` reaches the operator's terminal through inherited stderr but is
not in `str(ReleaseError)`. The current driver test demonstrates the gap by
passing `capture_output=True` and reading
`configure_error.__cause__.stderr`, not the exception text
(`sol/release/tests/test_driver.py:717-759`). The CLI prints only
`str(error)` as `release rail error: ...`
(`sol/release/rail.py:119-134`).

The minimum assertable change without hiding output is opt-in capture on this
configure call: pass `text=True, stderr=subprocess.PIPE`; in `_run`, echo a
nonempty captured stderr back to `sys.stderr` and also include it in the
raised `ReleaseError`. Stdout remains inherited/operator-visible. The
configure-specific `_build` wrapper then prepends `target["id"]`. This yields
one assertable error containing both canonical driver context and the exact
helper diagnostic while replaying the child's diagnostic to the terminal.
Capturing both streams is also viable only if `_run` replays each to its
original stream; plain `capture_output=True` alone would swallow them.

**Observed on this lode:** the complete source ordering, current exception
construction, current test's cause-only access, and final promotion boundary.
**Unobserved on this lode:** an actual release-driver invocation on a
`macos-arm64` host or its future combined diagnostic.

## Q8 — Scanner and baseline sensitivity

`declaration_records()` recognizes only literal
`ExternalProject_Add`/`FetchContent_Declare` followed by optional whitespace
and `(`. It balances unquoted parentheses, tracks double quotes and quoted
backslash escapes, strips `#` through newline without regard to quoting, then
uses POSIX `shlex.split`
(`sol/release/generate-dependencies.py:10-36`). It reads the first literal
`URL`, `URL_HASH`, `GIT_REPOSITORY`, and `GIT_TAG` token/value in each body
and rejects incomplete/mixed/unpinned forms
(`generate-dependencies.py:44-48,89-129`).

The path selector accepts every file named exactly `CMakeLists.txt` anywhere
under top-level `nv-attestation-sdk-cpp` or `nv-attestation-cli`, plus exactly
`nv-attestation-sdk-cpp/cmake/nvat_fetch_gtest.cmake`
(`generate-dependencies.py:60-86`). Current scanned inventory:

```text
nv-attestation-cli/CMakeLists.txt
nv-attestation-cli/tests/CMakeLists.txt
nv-attestation-sdk-cpp/CMakeLists.txt
nv-attestation-sdk-cpp/examples/CMakeLists.txt
nv-attestation-sdk-cpp/examples/attest-minimal/CMakeLists.txt
nv-attestation-sdk-cpp/examples/attest/CMakeLists.txt
nv-attestation-sdk-cpp/examples/attest_local/CMakeLists.txt
nv-attestation-sdk-cpp/examples/attest_policy_custom/CMakeLists.txt
nv-attestation-sdk-cpp/examples/attest_policy_none/CMakeLists.txt
nv-attestation-sdk-cpp/examples/attest_remote/CMakeLists.txt
nv-attestation-sdk-cpp/examples/collect-gpu-evidence/CMakeLists.txt
nv-attestation-sdk-cpp/examples/common/CMakeLists.txt
nv-attestation-sdk-cpp/examples/custom-logger/CMakeLists.txt
nv-attestation-sdk-cpp/examples/json-gpu-evidence/CMakeLists.txt
nv-attestation-sdk-cpp/examples/parallel-verification/CMakeLists.txt
nv-attestation-sdk-cpp/unit-tests/CMakeLists.txt
nv-attestation-sdk-cpp/cmake/nvat_fetch_gtest.cmake
```

A new helper such as
`nv-attestation-sdk-cpp/cmake/nvat_apple_system_link_closure.cmake` is **not**
scanned; nor is any non-`CMakeLists.txt` under the CLI/SDK, or anything under
`sol/`. Any new nested `CMakeLists.txt` under either product tree **is**
scanned automatically. Baseline stability independently obtains the baseline
tree listing, applies this same selector to baseline/current inventories, and
compares per-path and global coordinate multisets
(`sol/release/tests/test_baseline_stability.py:40-100,140-175`), so adding or
removing a scanned path is visible.

Inside a recognized declaration body, the forbidden hazards are:

* stray literal `URL`, `URL_HASH`, `GIT_REPOSITORY`, or `GIT_TAG` tokens,
  because `value_after()` treats the first as a coordinate field;
* unbalanced unquoted parentheses, which raise the explicit line-31 error;
* an unmatched double quote, which makes `shlex.split` fail;
* `#` inside a quoted value, because comment stripping happens before shlex
  and truncates the quote/value;
* a second recognized coordinate token before the intended value, which wins
  the first-token lookup.

Parentheses inside balanced double quotes are ignored by the depth counter.
Ordinary helper text outside a recognized declaration body is not parsed, but
the existing header-helper guard shows the convention: new helper modules
should also be asserted to contain no dependency-declaration or coordinate
tokens (`test_baseline_stability.py:184-195`).

There is no `Cargo.lock` anywhere in the working tree or tracked file list.
The native release's tracked Rust wiring is all in
`nv-attestation-sdk-cpp/CMakeLists.txt`: immutable Corrosion and regorus
coordinates (`:50-64`), then
`${regorus_SOURCE_DIR}/bindings/ffi/Cargo.toml`, Release profile, crate
`regorus-ffi`, feature `regorus/semver`, and `staticlib`
(`:66-72`), plus the optional sccache environment at `:74-76`.
`test_baseline_stability.py:170-175` currently pins the complete
`corrosion_import_crate` token sequence, while dependency coordinate
comparison pins the Corrosion commit and regorus tag.

The separately tracked local Rust workspace inventory is:

```text
nv-attestation-sdk-rust/Cargo.toml
nv-attestation-sdk-rust/nv-attestation-sdk-sys/Cargo.toml
nv-attestation-sdk-rust/nv-attestation-sdk-sys/build.rs
nv-attestation-sdk-rust/nv-attestation-sdk/Cargo.toml
```

Those files describe the local Rust SDK workspace and its nvat FFI build
(`nv-attestation-sdk-rust/Cargo.toml:1-15`;
`nv-attestation-sdk-rust/nv-attestation-sdk-sys/Cargo.toml:1-18`;
`nv-attestation-sdk-rust/nv-attestation-sdk-sys/build.rs:21-93`), but the
native CLI→SDK release CMake path selects the external pinned regorus manifest
instead. D7 should pin the native CMake wiring/inventory and record the
lockfile absence without misclassifying the local Rust SDK manifests as
inputs to this native target.

Finally, the current baseline constant is
`22065d840cbcc8ff457ac224da0df299a4e23b3f`
(`sol/release/tests/test_baseline_stability.py:26`), and the measured current
tip is exactly `b75e95ae0c08ac6eaa05673a0cf227b8723e2b58`.

**Observed on this lode:** exact scanner/parser source, current scanned path
inventory, no tracked or untracked `Cargo.lock`, tracked Rust wiring files,
baseline constant, and Git tip. **Unobserved on this lode:** resolution of the
external regorus Cargo graph or any Rust compilation for this research.

## Patterns the design should preserve

* Keep system closure on the imported static owner interfaces and keep those
  owners private to shared `nvat`; this gives owner-relative ordering without
  direct `nvattest` or export leakage.
* Discover Iconv and CoreFoundation through selected-SDK-only, no-default-path
  lookups and independently validate every canonical result; neither
  `FindIconv` nor a bare framework token is an exclusive binding.
* Keep the production helper at the real 3.11 language floor; do not imply
  that it repairs the rest of the post-3.11 graph.
* Use codemodel plus generated `link.txt` for Linux structural proof, and a
  rule-override hostile child only for transaction failure evidence. Neither
  is a native Apple-link proof.
* Add canonical target context at the macOS configure call, capture/replay the
  helper stderr into the raised error, and retain the existing staging-before-
  build/final-promotion-after-builder transaction boundary.
* Place a new helper in the unscanned SDK `cmake/` area, keep coordinate-like
  tokens out of it, and preserve the shared scanner/baseline inventory and
  native Rust wiring assertions.
