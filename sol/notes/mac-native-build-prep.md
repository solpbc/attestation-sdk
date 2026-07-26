# Native macOS arm64 build prep

Research captured in the worktree
`/home/jer/.hopper/worktrees/vjqz4u7b`. No product file was changed, no
production configure was run, and `make ci` was not run.

## Q1 — Warnings-as-errors delivery to fmt

The production configure enters through `nv-attestation-cli/CMakeLists.txt`.
It sets `CMAKE_COMPILE_WARNING_AS_ERROR` as a normal directory variable before
creating any relevant target (`nv-attestation-cli/CMakeLists.txt:10-11`).
Consequently `nvattest`, created at `nv-attestation-cli/CMakeLists.txt:28-35`,
has its `COMPILE_WARNING_AS_ERROR` target property initialized true. The normal
variable is inherited when the SDK is entered by `add_subdirectory`
(`nv-attestation-cli/CMakeLists.txt:78-84`).

The SDK then executes
`set(CMAKE_COMPILE_WARNING_AS_ERROR ON CACHE STRING ...)`
(`nv-attestation-sdk-cpp/CMakeLists.txt:7-12`). With no `FORCE`, this creates
or preserves the cache entry; it does not remove or replace the inherited
normal-variable binding. Variable lookup therefore still finds the inherited
normal value, `ON`. The distinction is not outcome-changing in this tree
because both values are `ON`, but the value in effect when fmt's targets are
created is the inherited normal binding, not a cache value overriding it.

This is the documented CMake >= 3.24 mechanism, rather than directory compile
options: `CMAKE_COMPILE_WARNING_AS_ERROR` initializes the target property on
all targets (`/usr/share/cmake/Help/variable/CMAKE_COMPILE_WARNING_AS_ERROR.rst:4-9`);
`COMPILE_WARNING_AS_ERROR` is initialized from the variable if it is set when
the target is created and emits the compiler's warning-as-error flag
(`/usr/share/cmake/Help/prop_tgt/COMPILE_WARNING_AS_ERROR.rst:4-9,35-37`).
AppleClang is an implemented compiler ID
(`/usr/share/cmake/Help/prop_tgt/COMPILE_WARNING_AS_ERROR.rst:11-18`).
Thus fmt's `add_library` calls, reached through
`FetchContent_MakeAvailable(fmt)` at
`nv-attestation-sdk-cpp/CMakeLists.txt:107-115`, receive a true per-target
property and CMake adds `-Werror` to their compile commands.

The supplied claim about the general warning options is correct. fmt is
populated at `nv-attestation-sdk-cpp/CMakeLists.txt:107-115` and spdlog at
`:117-127`, whereas `add_compile_options(-Wall -Wextra -Wpedantic -pedantic)`
does not execute until `:346-354`. Directory compile options affect targets
created after the call, so neither already-created dependency inherits those
four options. They still inherit the warning-as-error target-property policy.
In particular, spdlog is under the same policy today because it too is created
while the variable is true (`:117-127`).

The first-party production targets that must retain the supplied policy are:

* `nvattest`, declared at `nv-attestation-cli/CMakeLists.txt:28-35`.
* `nvat`, declared after the SDK warning options at
  `nv-attestation-sdk-cpp/CMakeLists.txt:348-368` (sources continue at
  `:369-395`).

The CMake < 3.24 fallback explicitly adds `-Werror` only under its version and
policy condition (`nv-attestation-sdk-cpp/CMakeLists.txt:349-351`).
Generalizing a dependency-warning exception beyond the fmt defect is an
explicit non-goal from scope §9.1; spdlog's current participation is recorded
here, not treated as authority to change it.

**Observed on this lode:** the source ordering, variable scopes, and installed
CMake 4.3.4 documentation above. **Unobserved on this lode:** an AppleClang fmt
compile line from the production Darwin configure; this host is Linux and the
production tree was not configured in this research stage.

## Q2 — Apple SDK, architecture, and floor after configure

The three CMake variables and their target effects are:

* `CMAKE_OSX_SYSROOT` is the SDK location or SDK name. If not explicitly set,
  CMake 4.x initializes it from `SDKROOT`, otherwise it defaults to empty and
  normally leaves SDK choice to the compiler
  (`/usr/share/cmake/Help/variable/CMAKE_OSX_SYSROOT.rst:4-17`). Some Clang
  configurations synthesize `-isysroot` from `xcrun` even while the variable
  is empty (`:27-29`). It is therefore **not guaranteed to be populated or
  absolute** when the user did not pass it. Even an explicit legal value can
  be the SDK name `macosx`, not an absolute path (`:14-17`).
* `CMAKE_OSX_ARCHITECTURES` initializes each target's `OSX_ARCHITECTURES`
  property. If unset, the compiler default is used; for Xcode-provided
  compilers this is the host architecture
  (`/usr/share/cmake/Help/variable/CMAKE_OSX_ARCHITECTURES.rst:4-12`).
* `CMAKE_OSX_DEPLOYMENT_TARGET` is initialized from the nonempty
  `MACOSX_DEPLOYMENT_TARGET` environment variable when not explicit; otherwise
  its non-Xcode default is empty
  (`/usr/share/cmake/Help/variable/CMAKE_OSX_DEPLOYMENT_TARGET.rst:7-21`).
  With a non-Xcode generator, a nonempty value becomes
  `-mmacosx-version-min=<value>` or equivalent on compile/link commands
  (`:23-37`).

For an ordinary first-party target, CMake consumes these variables through
generator/toolchain logic: architecture initializes a target property;
nonempty sysroot and deployment values become `-isysroot` and
`-mmacosx-version-min` (or generator equivalents). This applies to `nvattest`
and `nvat` because they are ordinary targets
(`nv-attestation-cli/CMakeLists.txt:28-35`;
`nv-attestation-sdk-cpp/CMakeLists.txt:368-395`).

An `ExternalProject_Add` custom `CONFIGURE_COMMAND` is a separate child
process. CMake documents that the project itself must forward toolchain
details, flags, or settings; the parent does not do so automatically
(`/usr/share/cmake/Modules/ExternalProject.cmake:539-550`). The four real
declarations pass only `_EP_CC` and `_EP_CFLAGS`, initialized from
`CMAKE_C_COMPILER` and `${CMAKE_C_FLAGS} -fPIC`
(`nv-attestation-sdk-cpp/CMakeLists.txt:182-183`), in their configure argv
(`:200-220`, `:246-265`, `:270-293`, `:300-326`). None mentions any
`CMAKE_OSX_*`, `SDKROOT`, or `MACOSX_DEPLOYMENT_TARGET`.

The release driver explicitly passes only
`-DCMAKE_OSX_DEPLOYMENT_TARGET=14.0` to the parent configure
(`sol/release/release_rail/driver.py:268-284`). It copies the caller's
environment and adds only `SOURCE_DATE_EPOCH` (`:264-267`); it does not resolve
or pass a sysroot. Therefore the CMake cache floor reaches first-party compile
lines, but it does not create a `MACOSX_DEPLOYMENT_TARGET` environment value
for child processes. An externally preexisting `SDKROOT`,
`MACOSX_DEPLOYMENT_TARGET`, or `CC` would be inherited by default, but that is
ambient input, not current rail delivery; argv `CC=...` then overrides `CC`
inside each configure program.

**Observed on this lode:** documentation and emitted declaration inputs.
**Unobserved on this lode:** actual resolved values in a Darwin
`CMakeCache.txt`, because there is no macOS configure here. In particular no
absolute SDK path can be asserted from this Linux host.

## Q3 — How the four dependency build systems consume Apple inputs

The exact pinned sources were downloaded to a scratch directory and inspected;
the pins originate in `nv-attestation-sdk-cpp/CMakeLists.txt:200-220`,
`:246-265`, `:270-293`, and `:300-326`.

### OpenSSL 3.6.1

`Configure` seeds `CC` and `CFLAGS` from the environment
(`openssl-3.6.1/Configure:759-776`). It documents internally that
`VAR=string` arguments override corresponding target attributes, while bare
flag arguments are additional (`:786-802`). Its merge chooses a nonempty user
value before the selected target's uppercase attribute (`:1479-1511`) and only
then appends bare command-line flags (`:1513-1525`).

Therefore the current single argv element `CFLAGS=${_EP_CFLAGS}` **replaces**
the selected target's uppercase `CFLAGS`, rather than appending to it. For
`darwin64-arm64-cc`, that suppresses the inherited release `-O3` and added
`-Wall` (`openssl-3.6.1/Configurations/10-main.conf:1843-1851,1911-1915`).
It does not suppress the lower-case target `cflags` containing `-arch arm64`
(`:1911-1918`): the generated makefile keeps target `CNF_CFLAGS` and user
`CFLAGS` separately, then combines them
(`openssl-3.6.1/Configurations/unix-Makefile.tmpl:377-383,420-460`).

OpenSSL directly respects environment `CC` and `CFLAGS`; current argv
assignments override them. It has no special `SDKROOT` or
`MACOSX_DEPLOYMENT_TARGET` parsing in `Configure`; those can still affect
Apple's compiler as inherited environment variables. `CC` supplied by CMake
is explicit; `SDKROOT` and the floor are merely inherited if the launching
environment happened to contain them.

Space handling has two layers. CMake preserves quoted CMake arguments as one
process argv element, so `"CFLAGS=a b"` reaches Perl whole. OpenSSL stores the
entire value as one array element and joins flag arrays with spaces in the
makefile (`Configure:759-766`;
`Configurations/unix-Makefile.tmpl:383,420`). Make then expands the unquoted
flag variable into a shell recipe, where whitespace is split. This is desired
between flags but breaks an unquoted pathname containing spaces. Quote
characters embedded in the value (for example `-isysroot "/SDK Path"`) are
written into the recipe and interpreted by the recipe shell, so the pathname
remains one compiler argument; escaping must survive CMake, Perl's
backslash/quote stringification (`Configure:1793-1800`), Make, and shell.

### libxml2 2.11.9, xmlsec 1.2.39, and curl 7.88.1

All three are generated autoconf scripts with the same argv-assignment
mechanism. A `*=*` argv word is parsed into a valid variable name, assigned
from the complete `ac_optarg`, and exported
(`libxml2-2.11.9/configure:1393-1401`;
`xmlsec1-1.2.39/configure:1481-1489`;
`curl-7.88.1/configure:1689-1697`). Thus the current quoted CMake element
`"CFLAGS=${_EP_CFLAGS}"` arrives as one argv word and sets/replaces `CFLAGS`;
it is not appended to a package default. `CC=...` behaves identically and
overrides inherited `CC`. The scripts use those variables in unquoted shell
compile templates such as `$CC -c $CFLAGS ...`
(`libxml2-2.11.9/configure:2813-2814`;
`xmlsec1-1.2.39/configure:3149`;
`curl-7.88.1/configure:3463`).

All three preserve `CC` and `CFLAGS` as precious variables and substitute
them into generated makefiles (for example
`libxml2-2.11.9/Makefile.in:490-492`;
`xmlsec1-1.2.39/Makefile.in:257-259`;
`curl-7.88.1/Makefile.in:353-355`). They do not consume `SDKROOT` as an
autoconf option, but Apple's compiler can consume inherited `SDKROOT`.
Their libtool logic does inspect inherited `MACOSX_DEPLOYMENT_TARGET`
(`libxml2-2.11.9/configure:8704`;
`xmlsec1-1.2.39/configure:8961`;
`curl-7.88.1/configure:12039`). None receives that variable from the parent's
CMake cache today.

For spaces, the initial CMake quoting protects the complete `CFLAGS=...` as
one configure argv element. Autoconf assigns its whole value. Later configure
compile probes and generated Make recipes expand `$CFLAGS`/`$(CFLAGS)`
unquoted, so the shell splits on spaces. Embedded shell quotes in the stored
value are parsed at that later shell invocation and can preserve a path with
spaces; without embedded quoting a sysroot path is split. Quotes used only in
the CMake source to delimit the argv element are not themselves part of the
value and cannot protect the later split.

**Observed on this lode:** exact pinned scripts, including assignment and
Makefile templates, plus successful archive retrieval. **Unobserved on this
lode:** execution under Apple `cc`, including the empirical behavior of an SDK
path containing spaces.

## Q4 — Observable ExternalProject emission surface

CMake's real `ExternalProject` implementation extracts the configure command
then calls `configure_file` during parent configuration to write
`${tmp_dir}/${name}-cfgcmd.txt`
(`/usr/share/cmake/Modules/ExternalProject.cmake:2771-2796`). Its template is
exactly `cmd='@cmd@'`
(`/usr/share/cmake/Modules/ExternalProject/cfgcmd.txt.in:1`), so the stored
value is CMake's semicolon-joined command list. For this tree, default EP
layout makes the files
`<build>/nv-attestation-sdk-build/<dep>_external-prefix/tmp/<dep>_external-cfgcmd.txt`.
The same extracted `cmd` is used to generate the configure step and therefore
appears, shell-escaped for execution, in
`CMakeFiles/<dep>_external.dir/build.make`
(`/usr/share/cmake/Modules/ExternalProject.cmake:2785-2796,2806-2810`).

The four `ExternalProject_Add` URL archives are **not** downloaded during
parent configure. Their configure steps follow their download/update/patch
steps, and URL retrieval is a build-step dependency
(`/usr/share/cmake/Modules/ExternalProject.cmake:539-555`; declarations at
`nv-attestation-sdk-cpp/CMakeLists.txt:200-220,246-326`). Their cfgcmd and
build.make surfaces exist before those downloads.

A full real-tree configure does require network unless FetchContent sources
are already supplied locally. The production path immediately populates:
CLI11 and json (`nv-attestation-cli/CMakeLists.txt:19-26`); Corrosion and
regorus (`nv-attestation-sdk-cpp/CMakeLists.txt:43-57`); jwt-cpp (`:74-95`);
json (`:95-96`); fmt (`:107-115`); and spdlog (`:117-127`). GoogleTest is
populated only when the test subdirectory includes
`nvat_fetch_gtest.cmake` (`nv-attestation-sdk-cpp/cmake/nvat_fetch_gtest.cmake:7-15`);
the release configure uses `BUILD_TESTING=OFF`
(`sol/release/release_rail/driver.py:275-280`), so gtest is not fetched there.
CLI test declarations likewise execute only after the guarded test
subdirectory (`nv-attestation-cli/CMakeLists.txt:122-125`;
`nv-attestation-cli/tests/CMakeLists.txt:26-59`).

No suitable CMake FetchContent source cache was found on this lode. Therefore
the smallest acceptable reproduction here is still a configure of the real
CLI/SDK tree with every configure-time FetchContent dependency satisfied
either by network or by explicit real-source overrides/cache. A minimal
project that includes or copies only the EP declarations would test CMake's
module, not this tree's actual expanded variables and argv, and is not an
acceptable before-side.

`make rail-test` is entirely offline and can validate Python/schema/shell
behavior, but it does not configure CMake or emit any cfgcmd surface
(`Makefile:37-39`). Without prepopulated FetchContent sources, it cannot
validate the real EP argv offline. Producing the Linux before-side would
require the real production configure, network access for seven production
FetchContent declarations (CLI11, json, Corrosion, regorus, jwt-cpp, fmt,
spdlog), a C/C++/Rust-capable configure environment, and however long those
network clones/downloads take; no reliable duration was observed.

**Observed on this lode:** CMake module generation semantics and absence of a
usable source cache. **Unobserved on this lode:** actual real-tree cfgcmd and
build.make files; `build/release/` is absent and the requested stage forbids
an unnecessary production configure.

## Q5 — Dependency pin sensitivity

The generator scans every CLI/SDK `CMakeLists.txt` plus
`nvat_fetch_gtest.cmake` (`sol/release/generate-dependencies.py:56-64`). Its
regex recognizes only literal `ExternalProject_Add(` or
`FetchContent_Declare(` spellings (`:10-13`). The paren matcher counts nested
unquoted parentheses, tracks double quotes and backslash escapes only while
quoted, and raises on an unclosed body (`:14-32`). It strips every
`#`-to-newline sequence without regard to quoting, then applies POSIX
`shlex.split`, so unmatched shell quoting also raises (`:33-37`).

Only the first token (name) and the first `URL`, `URL_HASH`,
`GIT_REPOSITORY`, and `GIT_TAG` token/value pairs affect pin output
(`:40-44,64-88`). Extra `"CFLAGS=..."` argv elements and a
`${CMAKE_COMMAND} -E env` prefix inside `CONFIGURE_COMMAND` are ignored,
provided they do not accidentally introduce one of those four exact tokens
or break quoting/parenthesis balance. An `if(APPLE)` around a declaration is
ignored because the scanner is textual and does not evaluate CMake control
flow. An `if(APPLE)` nested inside a declaration has its parentheses balanced
by the matcher and its tokens ignored after the pin fields, though such a
body may not be valid CMake/ExternalProject syntax. Inserting an unmatched
parenthesis, unmatched quote, a comment marker inside a quoted value, or a
second dependency keyword before its intended value can change parsing or
raise. Changing/duplicating recognized pins is checked for completeness,
hash shape, floating URLs, and cross-declaration conflicts (`:70-100`).

Before-side command:

```text
$ python3 sol/release/generate-dependencies.py --root . \
    --json /tmp/tmp.5TkEQOXaDq/pins-before.json \
    --notices /tmp/tmp.5TkEQOXaDq/notices-before.md
generated 12 dependency pins
[exit 0]
$ sha256sum /tmp/tmp.5TkEQOXaDq/pins-before.json
88af736d64debbf044e4d7a69f78412ea5f611f116d57e19027de5f66cbf128b
```

The complete ordered pin list is:

```text
CLI11 git v2.6.1
Corrosion git 6be991bb34c348dfb8344be22f3606288ea5c7fd
curl_external archive sha256:cdb38b72e36bc5d33d5b8810f8018ece1baa29a8f215b4495e495ded82bbf3c7
fmt git 10.2.1
googletest git v1.16.0
json archive sha256:42f6e95cad6ec532fd372391373363b62a14af6d771056dbfc86160e6dfff7aa
jwt-cpp git v0.7.1
libxml2_external archive sha256:780157a1efdb57188ec474dca87acaee67a3a839c2525b2214d318228451809f
openssl_external archive sha256:b1bfedcd5b289ff22aee87c9d600f515767ebf45f77168cb6d64f231f518a82e
regorus git regorus-v0.4.0
spdlog git v1.14.1
xmlsec_external archive sha256:15f2f55ea5968e578fcd24b3b427e553876c86c147dc7f03923e98fc2768a1fa
```

**Observed on this lode:** the generator exited 0 and produced the hash/list
above. The sensitivity statements follow directly from its parser.

## Q6 — Baseline and host feasibility

The explicitly requested baseline passed:

```text
$ make rail-test
python3 -m unittest discover -s sol/release/tests -p 'test_*.py'
.......................................................................
----------------------------------------------------------------------
Ran 71 tests in 0.375s

OK
shellcheck $(find sol -type f -name '*.sh' -print | sort)
[exit 0; elapsed 0.53s, user 0.44s, sys 0.11s]
```

Workspace/host facts:

```text
build/release/: absent
dist/: absent
cmake version 4.3.4
Python 3.13.13
podman: /usr/bin/podman; version 5.8.3
podman info: 5.8.3 linux amd64 true
docker: absent
```

Thus the session-scope statement that an already configured Linux release
tree exists is false in this worktree. Producing the Linux cfgcmd before-side
requires the real configure and the network/cache conditions in Q4.

`make ci` is mechanically runnable through Podman: `ci` first runs the same
rail tests, then `ci-container`; the latter builds the pinned image and runs a
fresh vendored configure/build/test in it (`Makefile:41-54`). Podman is
installed, rootless, and responds to `podman info`; Docker is not needed.
Network is required to obtain the base image and uncached FetchContent/EP
sources. Network connectivity was observed while retrieving the four exact
pinned archives for Q3, but registry-image availability and a complete CI run
were not verified. Per direction, `make ci` was not run.

**Observed on this lode:** all commands and absence statements above.
**Unobserved on this lode:** CI image pull/build success, full vendored build
duration, and Linux cfgcmd contents.

## Q7 — Manifest evidence precedent

The existing nested-evidence precedent is container runtime evidence:

* `runtime.EVIDENCE_KEY` is the stable key `container_runtime`
  (`sol/release/release_rail/runtime.py:15-20`).
* `validate_evidence` requires exact insertion-order tuples at the outer,
  client, and engine levels, normalized nonempty strings, paired product
  identities, versions matching `_VERSION`, Linux OS, and a closed
  architecture set (`sol/release/release_rail/runtime.py:60-63,157-184`).
  With a target, it cross-checks engine architecture against target
  architecture (`:185-190`).
* Capture cross-checks independent command outputs: Podman client/version/info
  must agree on version and platform (`runtime.py:193-223`); Docker version
  and info must agree (`:226-238`). Failures use
  `RuntimeSelectionError` (`:66-67`) and diagnostics name the failed command,
  malformed field, incompatibility, or recovery action
  (`:79-110,125-153,185-189`).

Build-tool evidence uses another closed, ordered schema:

* `BUILD_TOOL_KEYS` is exactly compiler, cmake, rustc, cargo, tar, xz, python
  (`sol/release/release_rail/manifest.py:19-20`).
* `capture_build_tools` requires exactly seven authority commands, emits those
  keys in order, requires runtime evidence only for Linux, and wraps runtime
  failures with the target ID (`manifest.py:104-138`).
* `validate_build_tools` enforces the exact ordered tuple (plus
  `container_runtime` only on Linux), and exact `("name", "version")` tuples
  for each tool (`manifest.py:141-161`).
* `_compiler_from_cache` is the precedent for checking captured evidence
  against configured reality: it reads `CMAKE_CXX_COMPILER:FILEPATH` from
  `CMakeCache.txt`, falling back only for pre-config fixture contexts
  (`manifest.py:23-35`).
* Version capture extracts a bounded dotted version and rejects missing,
  unrecognized, or unparseable tools with commands the operator can run to
  recover (`manifest.py:38-101`).

Set validation reuses the manifest validator before target identity,
artifact, sidecar, member, and binary checks
(`sol/release/release_rail/set_validator.py:65-107,108-176`).
`validate` then enforces the closed three-target release-set inventory and
source identity (`set_validator.py:179-220` and following). Any Darwin-only
toolchain evidence would consequently have to survive both manifest creation
and this later validation path.

Authority is also fail-closed. `_TARGET_KEYS` is the only allowed target-field
set (`sol/release/release_rail/authority.py:13-44`); load rejects unknown and
missing fields (`:127-163`). Mach-O-specific authority requirements are
checked at `:176-187`.

Test fixtures centralize ordinary tool evidence in `TOOLS`; `tools_for` copies
it and conditionally adds target-specific Linux runtime evidence
(`sol/release/tests/support.py:15-37`). Consumers are:

* manifest capture/schema and cache-cross-check tests
  (`sol/release/tests/test_manifest.py:15-89,109-158`);
* driver runtime/tool-capture tests
  (`sol/release/tests/test_driver.py:205,255-287`);
* archive manifest fixtures (`sol/release/tests/test_archive.py:12,50`);
* shared quartet construction used by set-validation tests
  (`sol/release/tests/support.py:82-107`);
* direct malformed runtime-evidence set tests
  (`sol/release/tests/test_set_validator.py:178-216`).

The macOS floor is currently hardcoded in four production/authority locations:
the CLI default (`nv-attestation-cli/CMakeLists.txt:2-4`), SDK default
(`nv-attestation-sdk-cpp/CMakeLists.txt:2-4`), release-driver configure argv
(`sol/release/release_rail/driver.py:268-281`), and authority
`abi_floor.macos` (`sol/release/targets.toml:66-77`). A test also hardcodes the
normalized `14.0.0` diagnostic expectation
(`sol/release/tests/test_gate.py:156`). Historical design notes contain
additional prose values but are not executable inputs. Other Apple-specific
production values found are compiler-name normalization
(`manifest.py:38-47`), the Darwin host/architecture and Mach-O policy in
targets (`targets.toml:66-90`), and the CLI install rpath
(`nv-attestation-cli/CMakeLists.txt:106-111`).

**Observed on this lode:** all schema, fixture, validation, and hardcoded-value
touch points above, plus their passing baseline tests. **Unobserved on this
lode:** genuine Apple toolchain evidence from a native release manifest.

## Open verification boundaries

No unresolved repository code path was found within the requested scope. The
remaining empirical questions require a native macOS arm64 configure/build:
the actual cache representation of an implicitly selected SDK, AppleClang
compile argv (including fmt's `-Werror`), child configure/build behavior with
a real SDK path containing spaces, and genuine toolchain evidence values.
Those are explicitly unobserved on this Linux lode.
