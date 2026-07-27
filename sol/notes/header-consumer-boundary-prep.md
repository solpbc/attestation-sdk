# nvattest macOS spdlog/fmt header-consumer boundary prep

Research captured on the Linux lode
`/home/jer/.hopper/worktrees/dvid4m3p` on 2026-07-26. No product CMake,
product source, or test file was changed. The only repository file created is
this note. Scratch material was created under
`/tmp/nvat-header-consumer-research` and removed after the measurements.

The production entry point creates `nvattest` before selecting installed or
embedded nvat (`nv-attestation-cli/CMakeLists.txt:30-41,53-105`), links
`nvat::nvat`, json, and CLI11 (`:107-111`), then adds its own source,
generated, spdlog, and fmt include roots as ordinary private directories
(`:120-126`). Embedded mode creates `nvat::nvat` as an alias of the real
`nvat` target (`:87-93`); installed mode creates it as an imported shared
target whose interface include is `NVAT_INCLUDE_DIR`
(`nv-attestation-sdk-cpp/cmake/nvat_locate_installed.cmake:112-141`).

## Q1 — Effective include vectors before a change

The embedded configure used the exact requested values:
`USE_SYSTEM_NVAT=OFF`, `USE_SYSTEM_DEPS=OFF`, `BUILD_TESTING=OFF`,
`BUILD_SHARED_LIBS=ON`, `Release`, and
`CMAKE_EXPORT_COMPILE_COMMANDS=ON`. It used
`cmake_support.py::production_configure` and
`warning_fixture_prepare` (`sol/release/tests/cmake_support.py:13-85,88-134`);
that fixture supplies offline Corrosion, regorus, jwt, json, CLI11, fmt, and
spdlog source directories (`:17-81`). The actual selected commands from
`compile_commands.json` were:

```text
=== embedded configure rc=0
--- main.cpp
/usr/bin/c++  -I/home/jer/.hopper/worktrees/dvid4m3p/nv-attestation-cli/src -I/tmp/tmp2gwpcm0i/build -I/tmp/tmp2gwpcm0i/spdlog/include -I/tmp/tmp2gwpcm0i/fmt/include -I/tmp/tmp2gwpcm0i/build/nv-attestation-sdk-build/include -O3 -DNDEBUG -std=gnu++14 -Werror -o CMakeFiles/nvattest.dir/src/main.cpp.o -c /home/jer/.hopper/worktrees/dvid4m3p/nv-attestation-cli/src/main.cpp
--- nvat.cpp
/usr/bin/c++ -DXMLSEC_CRYPTO_OPENSSL=1 -DXMLSEC_NO_CRYPTO_DYNAMIC_LOADING=1 -DXMLSEC_NO_FTP=1 -DXMLSEC_NO_GOST2012=1 -DXMLSEC_NO_GOST=1 -DXMLSEC_NO_MD5=1 -DXMLSEC_NO_SIZE_T -DXMLSEC_NO_XSLT=1 -D__XMLSEC_FUNCTION__=__func__ -Dnvat_EXPORTS -I/tmp/tmp2gwpcm0i/build/nv-attestation-sdk-build/include -I/home/jer/.hopper/worktrees/dvid4m3p/nv-attestation-sdk-cpp/src -I/home/jer/.hopper/worktrees/dvid4m3p/nv-attestation-sdk-cpp/include -I/tmp/tmp2gwpcm0i/regorus/bindings/ffi -I/tmp/tmp2gwpcm0i/spdlog/include -I/tmp/tmp2gwpcm0i/fmt/include -I/tmp/tmp2gwpcm0i/jwt-cpp/include -isystem /tmp/tmp2gwpcm0i/build/xmlsec-install/include/xmlsec1 -isystem /tmp/tmp2gwpcm0i/build/libxml2-install/include/libxml2 -isystem /tmp/tmp2gwpcm0i/build/openssl-install/include -isystem /tmp/tmp2gwpcm0i/build/curl-install/include -O3 -DNDEBUG -std=gnu++14 -fPIC -Wall -Wextra -Wpedantic -pedantic -Wno-unused -Wno-unused-parameter -ffile-prefix-map=/home/jer/.hopper/worktrees/dvid4m3p/nv-attestation-cli/src/= -Wno-c++17-extensions -Werror -o CMakeFiles/nvat.dir/src/nvat.cpp.o -c /home/jer/.hopper/worktrees/dvid4m3p/nv-attestation-sdk-cpp/src/nvat.cpp
```

The roots in those commands classify as follows:

| target | exact root (scratch prefix retained from command) | emitted | owner |
| --- | --- | --- | --- |
| `nvattest` | `.../nv-attestation-cli/src` | `-I` | first-party src |
| `nvattest` | `/tmp/tmp2gwpcm0i/build` | `-I` | first-party generated |
| `nvattest` | `/tmp/tmp2gwpcm0i/spdlog/include` | `-I` | third-party pinned/stubbed |
| `nvattest` | `/tmp/tmp2gwpcm0i/fmt/include` | `-I` | third-party pinned/stubbed |
| `nvattest` | `.../build/nv-attestation-sdk-build/include` | `-I` | first-party generated |
| `nvat` | `.../nv-attestation-sdk-build/include` | `-I` | first-party generated |
| `nvat` | `.../nv-attestation-sdk-cpp/src` | `-I` | first-party src |
| `nvat` | `.../nv-attestation-sdk-cpp/include` | `-I` | first-party src |
| `nvat` | `.../regorus/bindings/ffi` | `-I` | other dependency |
| `nvat` | `.../spdlog/include` | `-I` | third-party pinned/stubbed |
| `nvat` | `.../fmt/include` | `-I` | third-party pinned/stubbed |
| `nvat` | `.../jwt-cpp/include` | `-I` | other dependency |
| `nvat` | `.../xmlsec-install/include/xmlsec1` | `-isystem` | other dependency |
| `nvat` | `.../libxml2-install/include/libxml2` | `-isystem` | other dependency |
| `nvat` | `.../openssl-install/include` | `-isystem` | other dependency |
| `nvat` | `.../curl-install/include` | `-isystem` | other dependency |

The installed configure used real offline-populated fmt 10.2.1 and spdlog
1.14.1 checkouts plus scratch CLI11/json interface targets with observable
include roots, a fake `nvat.h`, and a fake `libnvat.so`. This is the part that
the existing helper does not fit: its CLI11/json targets have no interface
include (`cmake_support.py:36-49`), and it has no `USE_SYSTEM_NVAT=ON`
fixture. Actual output:

```text
=== installed configure rc=0
--- main.cpp
/usr/bin/c++  -I/home/jer/.hopper/worktrees/dvid4m3p/nv-attestation-cli/src -I/tmp/tmpdx0w1abo/build -I/tmp/nvat-header-consumer-research/spdlog-1.14.1/include -I/tmp/nvat-header-consumer-research/fmt-10.2.1/include -I/tmp/tmpdx0w1abo/json/include -I/tmp/tmpdx0w1abo/cli11/include -isystem /tmp/tmpdx0w1abo/installed/include -O3 -DNDEBUG -std=gnu++14 -Werror -o CMakeFiles/nvattest.dir/src/main.cpp.o -c /home/jer/.hopper/worktrees/dvid4m3p/nv-attestation-cli/src/main.cpp
```

| installed `nvattest` root | emitted | owner |
| --- | --- | --- |
| `.../nv-attestation-cli/src` | `-I` | first-party src |
| `.../build` | `-I` | first-party generated |
| `.../spdlog-1.14.1/include` | `-I` | third-party pinned |
| `.../fmt-10.2.1/include` | `-I` | third-party pinned |
| `.../json/include` | `-I` | other dependency |
| `.../cli11/include` | `-I` | other dependency |
| `.../installed/include` | `-isystem` | first-party installed |

Thus the prior scope measurement that installed `NVAT_INCLUDE_DIR` is
`-isystem` is confirmed. It comes from an imported target's interface
(`nvat_locate_installed.cmake:134-140`), not from the ordinary direct include
call, which does not name `NVAT_INCLUDE_DIR`
(`nv-attestation-cli/CMakeLists.txt:120-126`).

## Q2 — Pinned public-header boundary

The coordinates are fmt `10.2.1` and spdlog `v1.14.1`
(`nv-attestation-sdk-cpp/CMakeLists.txt:123-145` and
`nv-attestation-cli/CMakeLists.txt:63-82`). Real shallow tag checkouts resolved
to fmt commit `e69e5f977d458f2650bb346dadf2ad30c5320281` and spdlog commit
`27cb4c76708608465c413f6d0e6b8d99a4d84302`.

Measured identity files:

```text
=== fmt identity
rg: .../fmt-10.2.1/include/fmt/base.h: No such file or directory (os error 2)
.../fmt-10.2.1/include/fmt/core.h:21:#define FMT_VERSION 100201
=== spdlog identity
6  #define SPDLOG_VER_MAJOR 1
7  #define SPDLOG_VER_MINOR 14
8  #define SPDLOG_VER_PATCH 1
11 #define SPDLOG_VERSION SPDLOG_TO_VERSION(SPDLOG_VER_MAJOR, SPDLOG_VER_MINOR, SPDLOG_VER_PATCH)
=== bundled fmt identity
rg: .../spdlog-1.14.1/include/spdlog/fmt/bundled/base.h: No such file or directory (os error 2)
.../spdlog-1.14.1/include/spdlog/fmt/bundled/core.h:21:#define FMT_VERSION 100201
```

The exact candidate boundary files are therefore:

| populated root | candidate that exists and identifies it |
| --- | --- |
| `${fmt_SOURCE_DIR}/include` | `fmt/core.h` (`FMT_VERSION == 100201`) |
| `${spdlog_SOURCE_DIR}/include` | `spdlog/version.h` (`1.14.1` macros) |
| `${spdlog_SOURCE_DIR}/include` bundled fmt | `spdlog/fmt/bundled/core.h` (`FMT_VERSION == 100201`) |

First-party TUs do not receive spdlog target usage requirements: `nvat` links
the files, not the targets (`nv-attestation-sdk-cpp/CMakeLists.txt:478-495`),
and `nvattest` links only nvat/json/CLI11
(`nv-attestation-cli/CMakeLists.txt:107-111`). In the real spdlog tree,
`spdlog/fmt/fmt.h` defaults to bundled fmt and includes
`spdlog/fmt/bundled/core.h` and `format.h` when
`SPDLOG_FMT_EXTERNAL` is absent (real populated
`include/spdlog/fmt/fmt.h:9-29`). The production spdlog target would publish
that definition, but only through its usage requirements; the real populated
tree sets it on `spdlog` and `spdlog_header_only`
(`CMakeLists.txt:209-214`). This is why the first-party include boundary must
validate the bundled `core.h` too.

Recommended single truth source: define a production CMake list of
root-variable/relative-header pairs once in the validator, and have the test
extract that exact list block from production (the existing source-extracted
fixture pattern is described and used in
`spdlog-warning-boundary-design.md:D4` and
`test_warning_policy.py:179-238`). The validator iterates the pairs and
`if(NOT EXISTS ...) message(FATAL_ERROR ...)`; the test extracts the same
block, runs it against real/offline populated trees, and derives expected
names from the extracted pairs. Do not maintain a Python list of the three
headers.

## Q3 — Collision behavior and `NO_SYSTEM_FROM_IMPORTED`

A CMake 4.3.4 two-target scratch project called
`target_include_directories` once ordinary and once `SYSTEM` for the identical
directory, in both orders. Actual output:

```text
=== ordinary-first rc=0
/usr/bin/c++  -isystem /tmp/nvat-header-consumer-research/collision/ordinary-first/../include  -o ... -c .../main.cpp
=== system-first rc=0
/usr/bin/c++  -isystem /tmp/nvat-header-consumer-research/collision/system-first/../include  -o ... -c .../main.cpp
```

`SYSTEM` wins the collision and call ordering does not change that result.
Consequently, adding an ordinary direct `NVAT_INCLUDE_DIR` cannot override the
same system-classified imported interface root.

The production-shape CMake 4.3.4 measurements used observable interface roots
for all three linked targets. Results:

| mode / linked target | default | with `NO_SYSTEM_FROM_IMPORTED ON` | flip |
| --- | --- | --- | --- |
| embedded `CLI11::CLI11` (alias of real target) | `-I` | `-I` | none |
| embedded `nlohmann_json::nlohmann_json` (alias of real target) | `-I` | `-I` | none |
| embedded `nvat::nvat` (alias of real target) | `-I` | `-I` | none |
| installed CLI11 (alias of real target) | `-I` | `-I` | none |
| installed json (alias of real target) | `-I` | `-I` | none |
| installed `nvat::nvat` (IMPORTED) | `-isystem` | `-I` | yes |

The installed commands proving the only production-shape flip were:

```text
default:
... -I.../json/include -I.../cli11/include -isystem .../installed/include ...
NO_SYSTEM_FROM_IMPORTED:
... -I.../installed/include -I.../json/include -I.../cli11/include ...
```

A separate reduced fixture in which CLI11 and json themselves were IMPORTED
showed the collateral rule: all three imported roots flip, not just nvat:

```text
default:
/usr/bin/c++ -I.../spdlog -I.../fmt -isystem .../nvat -isystem .../json -isystem .../cli ...
NO_SYSTEM_FROM_IMPORTED:
/usr/bin/c++ -I.../spdlog -I.../fmt -I.../nvat -I.../json -I.../cli ...
```

Therefore target-wide `NO_SYSTEM_FROM_IMPORTED` is safe from CLI11/json
collateral only for the current FetchContent topology, where they are aliases
of real targets. It would de-systemize them if their acquisition changes to
actual imported targets.

## Q4 — Compiler behavior for AC6

Available compilers:

```text
cmake version 4.3.4
gcc (SUSE Linux) 15.3.0
g++ (SUSE Linux) 15.3.0
/bin/bash: clang++: command not found
```

The probes used the production nvat warning tail shown in Q1 unchanged:
`-O3 -DNDEBUG -std=gnu++14 -Wall -Wextra -Wpedantic -pedantic
-Wno-unused -Wno-unused-parameter -Wno-c++17-extensions -Werror`.
The header was byte-identical between the two classification runs:
`inline int header_warning() { }`. Commands and output:

```text
=== system header warning
$ /usr/bin/c++ -isystem .../include -O3 -DNDEBUG -std=gnu++14 -Wall -Wextra -Wpedantic -pedantic -Wno-unused -Wno-unused-parameter -Wno-c++17-extensions -Werror -c use.cpp -o system.o
rc=0
=== ordinary header warning
$ /usr/bin/c++ -I .../include -O3 -DNDEBUG -std=gnu++14 -Wall -Wextra -Wpedantic -pedantic -Wno-unused -Wno-unused-parameter -Wno-c++17-extensions -Werror -c use.cpp -o ordinary.o
In file included from .../use.cpp:1:
.../include/probe.h:1:31: error: no return statement in function returning non-void [-Werror=return-type]
    1 | inline int header_warning() { }
      |                               ^
cc1plus: all warnings being treated as errors
rc=1
```

The use-site proof put
`__attribute__((deprecated("boundary proof"))) inline int old_api()` in a
system header:

```text
$ /usr/bin/c++ -isystem .../include -O3 -DNDEBUG -std=gnu++14 -Wall -Wextra -Wpedantic -pedantic -Wno-unused -Wno-unused-parameter -Wno-c++17-extensions -Werror -c deprecated-use.cpp -o deprecated.o
.../deprecated-use.cpp:2:28: error: ‘int old_api()’ is deprecated: boundary proof [-Werror=deprecated-declarations]
    2 | int main() { return old_api(); }
      |                     ~~~~~~~^~
.../include/deprecated.h:2:58: note: declared here
cc1plus: all warnings being treated as errors
rc=1
```

`-Wsystem-headers` must remain absent for the first proof; it is absent from
both actual Q1 production commands. Clang/AppleClang behavior is unobserved
because no `clang++` exists here. Native AppleClang plus the generated macOS
commands are needed to close that platform proof.

## Q5 — A real CMake 3.11 acquisition for AC4

The host has `/usr/bin/cmake` 4.3.4. The ephemeral binary explicitly named in
the scope still exists:

```text
$ /tmp/nvat-warning-research/cmake-3.11.4-Linux-x86_64/bin/cmake --version
cmake version 3.11.4

CMake suite maintained and supported by Kitware (kitware.com/cmake).
```

It is outside the repository and is x86_64 Linux-only. The CI image does not
install CMake at all in its project layer; it installs development libraries,
git, patch, and build tools (`sol/ci/Containerfile:1-12`). Its base is supplied
externally through `ARG CI_IMAGE` (`:3-4`), so this repository does not prove
that base contains 3.11.

For a committed no-network `make rail-test`, the executable must be supplied
by the host/CI image or committed as platform-specific artifacts. Committing
the scratch binary is inappropriate and a single Linux x86_64 artifact would
not cover macOS/arm64. Under AC4's exact wording—“A real CMake 3.11 executable
... configure both production modes”—absence should fail, not skip: a skip
does not establish the acceptance criterion. The practical design choices are
to provision 3.11 in each gate image/runner and pass an explicit executable
path, or revise AC4 to permit an optional local proof. Current source does
neither.

The gate should execute the candidate binary with `--version`, require a
parsed `3.11.x`, and have the configured fixture emit
`message(STATUS "ENGINE=${CMAKE_VERSION}")`; then require both output and
generated `CMakeCache.txt` to report 3.11. The reduced run here produced:

```text
-- ENGINE=3.11.4
-- Configuring done
-- Generating done
```

This resists a shadowed `CMAKE_VERSION` only when the independently executed
`<candidate> --version` is also checked. It resists a bare
`cmake_minimum_required(VERSION 3.11)` and source-string inspection because it
requires configure artifacts from that executable. Honest limit: these checks
prove that a binary identifying as 3.11 executed the fixture; they do not
cryptographically authenticate Kitware's binary, and a reduced fixture does
not prove the production trees.

## Q6 — Does real 3.11 configure both production modes today?

No. CMake 3.11 does not accept the modern `-S/-B` invocation, so the measured
commands ran from the build directory with the source as the positional
argument. Both real production modes fail at the same first CLI call
(`nv-attestation-cli/CMakeLists.txt:27-28`):

```text
=== embedded
$ .../cmake-3.11.4-Linux-x86_64/bin/cmake /home/jer/.hopper/worktrees/dvid4m3p/nv-attestation-cli ... -DUSE_SYSTEM_NVAT=OFF ...
CMake Error at CMakeLists.txt:28 (FetchContent_MakeAvailable):
  Unknown CMake command "FetchContent_MakeAvailable".
rc=1

=== installed
$ .../cmake-3.11.4-Linux-x86_64/bin/cmake /home/jer/.hopper/worktrees/dvid4m3p/nv-attestation-cli ... -DUSE_SYSTEM_NVAT=ON ...
CMake Error at CMakeLists.txt:28 (FetchContent_MakeAvailable):
  Unknown CMake command "FetchContent_MakeAvailable".
rc=1
```

Thus `FetchContent_MakeAvailable` does not exist in this real 3.11 engine.
Neither mode reaches installed nvat discovery, SDK FetchContent,
Corrosion/regorus, ExternalProject stubs, or the SDK `add_compile_options`
region; no claim about their 3.11 runtime interaction can be made from the
full-tree attempt. The existing harness also cannot drive 3.11 unchanged
because it uses `--trace-format=json-v1` and `-S/-B`
(`cmake_support.py:110-121`).

The minimal gate that actually configured was a reduced CMakeLists with the
real boundary shapes: ordinary direct spdlog/fmt roots, linked imported nvat,
linked CLI11/json targets, and optional
`NO_SYSTEM_FROM_IMPORTED`. Its actual 3.11 commands are pasted in Q3. For
maximum source coupling, a committed version should extract the precise
production classification call/property block, as the warning test already
extracts policy text rather than copying it
(`test_warning_policy.py:179-238`). Lost fidelity is substantial: it does not
execute either production CMakeLists as a whole, FetchContent, Corrosion,
ExternalProject, Apple helpers, or production target creation/order. Given
today's source, AC4's literal “configure both production modes” is not
satisfiable by real CMake 3.11 without first changing acquisition compatibility
or redefining the gate as a reduced boundary fixture.

## Q7 — Runtime baseline

All timings used `/usr/bin/time -p` inside `hop check`. No `make ci` was run.
Actual results:

```text
$ hop check -n 80 -- /usr/bin/time -p make rail-test
Ran 110 tests in 5.948s
OK
real 6.07
user 4.96
sys 1.15

$ hop check -n 40 -- /usr/bin/time -p python3 -m unittest discover -s sol/release/tests -p test_warning_policy.py
Ran 6 tests in 1.327s
OK
real 1.36
user 1.12
sys 0.24

$ hop check -n 40 -- /usr/bin/time -p python3 -m unittest discover -s sol/release/tests -p test_baseline_stability.py
Ran 4 tests in 0.023s
OK
real 0.05
user 0.04
sys 0.01

$ hop check -n 40 -- /usr/bin/time -p python3 -m unittest discover -s sol/release/tests -p test_driver.py
Ran 23 tests in 0.692s
OK
real 0.74
user 0.62
sys 0.12
```

An initial module-name invocation of `test_warning_policy` and `test_driver`
failed because those files import top-level `cmake_support`; the corrected
discover invocations above match `make rail-test`
(`Makefile:37-39`). The baseline-stability module invocation happened to pass,
but its corrected discover timing is the recorded comparable value.

## Factual appendix — all four consumer sites and CI reachability

The four current sites are:

```cmake
# nv-attestation-sdk-cpp/CMakeLists.txt:440-451
target_include_directories(nvat
  PUBLIC
    $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>
    $<BUILD_INTERFACE:${CMAKE_CURRENT_BINARY_DIR}/include>
  PRIVATE
    src
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    ${regorus_SOURCE_DIR}/bindings/ffi
    # spdlog and fmt include dirs (linked statically via TARGET_FILE below)
    ${spdlog_SOURCE_DIR}/include
    ${fmt_SOURCE_DIR}/include
)

# nv-attestation-cli/CMakeLists.txt:121-126
target_include_directories(nvattest PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/src
    ${CMAKE_CURRENT_BINARY_DIR}
    ${spdlog_SOURCE_DIR}/include
    ${fmt_SOURCE_DIR}/include
)

# nv-attestation-cli/tests/CMakeLists.txt:69-72
target_include_directories(nv-attestation-cli-tests PRIVATE
    ${spdlog_SOURCE_DIR}/include
    ${fmt_SOURCE_DIR}/include
    ${CMAKE_CURRENT_SOURCE_DIR}/../src
)

# nv-attestation-sdk-cpp/unit-tests/CMakeLists.txt:179-182
target_include_directories(nv-attestation-unit-tests PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/../include
    ${spdlog_SOURCE_DIR}/include
    ${fmt_SOURCE_DIR}/include
)
```

Both test sites are reached by `make ci`: its production configure passes
`-DBUILD_TESTING=ON` (`Makefile:41-54`); the CLI adds `tests`
(`nv-attestation-cli/CMakeLists.txt:128-131`), and embedded mode adds the SDK,
whose `BUILD_TESTING` branch adds `unit-tests`
(`nv-attestation-sdk-cpp/CMakeLists.txt:459-466`).

## Patterns and design constraints established

* Direct consumer roots are currently ordinary; imported target interfaces
  are system-classified by default. Evidence is Q1 plus the owning calls at
  `nv-attestation-cli/CMakeLists.txt:107-126`.
* Duplicate ordinary/SYSTEM calls cannot “win back” ordinary classification;
  Q3 measured SYSTEM winning in either order.
* `NO_SYSTEM_FROM_IMPORTED` operates target-wide. It precisely fixes installed
  nvat today, but will affect every imported dependency interface on that
  consumer; Q3 records both the current topology and the imported collateral
  fixture.
* The header boundary has three identities, not two, because first-party
  compilation defaults through spdlog's bundled fmt. Evidence is Q2 and the
  file-link topology at `nv-attestation-sdk-cpp/CMakeLists.txt:478-495`.
* Tests should derive boundary filenames from the production validator's one
  declaration, matching the existing source-extraction convention
  (`test_warning_policy.py:179-238`).
* Linux GCC proves the diagnostic mechanism, but AppleClang/macOS remains a
  required native proof; no Clang compiler exists on this lode.
* A literal real-3.11 full-production configure is currently blocked before
  either mode diverges. A reduced fixture is executable but must be described
  as reduced, not as a production-mode configure.
