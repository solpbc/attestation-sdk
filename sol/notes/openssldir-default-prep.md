# nvattest vendored OpenSSL `--openssldir` default prep

Research was captured on the Linux x86_64 lode `suze`
(`/home/jer/.hopper/worktrees/6patvfem`) on 2026-08-20. The repository tip
was exactly `493c1a7` (`sol: document the re-pin and baseline move required
after a rebase`), and `git status --porcelain --untracked-files=all` was
empty before this note. No production or test file was changed. `make ci`
and `make release` were not run. Python was 3.13.13.

The pre-fix vendored OpenSSL 3.6.1 tree was produced by the already-running
configure/build:

```text
cmake -S nv-attestation-cli -B build \
  -DUSE_SYSTEM_NVAT=OFF -DUSE_SYSTEM_DEPS=OFF \
  -DBUILD_TESTING=OFF -DBUILD_SHARED_LIBS=ON &&
cmake --build build -j16
```

Log: `/var/tmp/claude-1000/-home-jer--hopper-worktrees-6patvfem/2e87bac8-401d-4d00-be7f-7ac22699007c/scratchpad/prewarm-build.log`.
`<builddir>` is `/home/jer/.hopper/worktrees/6patvfem/build`.
`CMakeLists.txt` was not edited.

## Required baseline

Not re-run. Already recorded:

```text
Ran 177 tests ... OK (skipped=2)
```

shellcheck clean.

Porcelain was empty at the start of this note.

## Prewarm build: EXIT=2, then a build-dir-only resume

The prewarm log ended:

```text
gmake[2]: *** No rule to make target 'xmlsec-install/lib/libxmlsec1.a', needed by 'nv-attestation-sdk-build/libnvat.so.1.2.2'.  Stop.
gmake[1]: *** [CMakeFiles/Makefile2:690: nv-attestation-sdk-build/CMakeFiles/nvat.dir/all] Error 2
gmake: *** [Makefile:156: all] Error 2
EXIT=2
```

OpenSSL itself had already finished. `build/openssl-install/lib/libcrypto.a`
and `libssl.a` were present, and `install_ssldirs` had populated
`certs/`, `private/`, `openssl.cnf`, `ct_log_list.cnf` under
`build/openssl-install/`.

xmlsec 1.2.39 (and curl 7.88.1) installed into `lib64/` on this
Tumbleweed host because their ExternalProject configure lines do not pass
`--libdir=.../lib`. OpenSSL does (`CMakeLists.txt:237 --libdir=lib`), so
its prefix layout was already `lib/`. `Findxmlsec.cmake:10-11` and the
curl imported location both expect `lib/*.a`. That is a native-host
layout mismatch with the RHEL8-family container, not the defect under
study.

Build-dir-only workaround, no product-file edit:

```text
ln -sfn lib64 build/xmlsec-install/lib
ln -sfn lib64 build/curl-install/lib
cmake --build build -j16
RESUME_EXIT=0
```

`build/nv-attestation-sdk-build/libnvat.so.1.2.2` is the pre-fix shared
library. The 11 `openssl-install` strings in it are identical to those
in `build/openssl-install/lib/libcrypto.a` (same `uniq -c` histogram),
so the resume did not change the OpenSSL bake.

`nvattest` (`build/nvattest`) DT_NEEDED-links `libnvat.so.1` and contains
zero `openssl-install` bytes. The defect lives in the shipped library,
not the CLI executable.

## Defect sites (cited, not re-derived)

```cmake
# nv-attestation-sdk-cpp/CMakeLists.txt:226
set(OPENSSL_INSTALL_DIR "${CMAKE_BINARY_DIR}/openssl-install")
```

```cmake
# nv-attestation-sdk-cpp/CMakeLists.txt:235-246
      --prefix=${OPENSSL_INSTALL_DIR}
      --openssldir=${OPENSSL_INSTALL_DIR}
      --libdir=lib
      ...
    INSTALL_COMMAND ${NVAT_EP_ENV_COMMAND} make install_sw install_ssldirs
```

`--prefix` must not change. `--openssldir=${OPENSSL_INSTALL_DIR}` is the
defect. `CMAKE_BINARY_DIR` is the top-level `-B` directory, not the nested
SDK binary dir (`nv-attestation-cli/CMakeLists.txt:86-92`
`add_subdirectory(..., nv-attestation-sdk-build)`). Confirmed here:

```text
CMAKE_CACHEFILE_DIR:INTERNAL=/home/jer/.hopper/worktrees/6patvfem/build
CMAKE_HOME_DIRECTORY:INTERNAL=/home/jer/.hopper/worktrees/6patvfem/nv-attestation-cli
```

Release Linux `_build` (`driver.py:279-284`) uses `-B build/release`
inside the container (`-w /src`), so the baked value there is
`/src/build/release/openssl-install`. `make ci-container` (`Makefile:52-55`)
uses `-B build` → `/src/build/openssl-install`. Darwin native `_build`
(`driver.py:294-300`) uses the same `build/release` on the host path.

Gate seam:

```python
# sol/release/release_rail/gate.py:12-15
FORBIDDEN_CA_PATHS = (
    b"/etc/ssl/certs/ca-certificates.crt",
    b"/etc/pki/tls/certs/ca-bundle.crt",
)
```

```python
# gate.py:39-42
def _forbidden_strings(path: Path, data: bytes) -> None:
    for value in FORBIDDEN_CA_PATHS:
        if value in data:
            raise GateError(f"{path}: compiled host CA path found: {value.decode()}")
```

Called from `gate_elf` (`gate.py:70`) and `gate_macho` (`gate.py:132`)
over `info.data`. Both readers load the whole file:

```python
# elf.py:81-82
        data = path.read_bytes()
# macho.py:81
        data = path.read_bytes()
```

`test_gate.py:95-120` (`test_baked_host_ca_paths_fail_for_each_format`)
injects each `FORBIDDEN_CA_PATHS` member as a fixture string into both
formats.

This is not a loud runtime failure. curl 7.88.1
`lib/vtls/openssl.c:3270-3275` under `CURL_CA_FALLBACK` (defined in the
vendored `lib/curl_config.h`) calls `X509_STORE_set_default_paths(store)`
and discards the return value. OpenSSL
`crypto/x509/x509_d2.c:40-43` then `ERR_clear_error()` and returns 1
anyway. libcrypto config autoload uses
`DEFAULT_CONF_MFLAGS` (`include/internal/conf.h:16-17`) =
`CONF_MFLAGS_DEFAULT_SECTION | CONF_MFLAGS_IGNORE_MISSING_FILE |
CONF_MFLAGS_IGNORE_RETURN_CODES`. `ossl_config_int`
(`crypto/conf/conf_sap.c:46-76`) still sets `openssl_configured = 1`
after `CONF_modules_load_file_ex`.

## Q1 — What the artifact contains today

Shipped library:

```text
$ find build -name 'libnvat.so*' -printf '%p %s\n'
build/nv-attestation-sdk-build/libnvat.so.1.2.2 34260448
build/nv-attestation-sdk-build/libnvat.so.1 16
build/nv-attestation-sdk-build/libnvat.so 12

$ ls -la build/nv-attestation-sdk-build/libnvat.so*
lrwxrwxrwx. ... libnvat.so -> libnvat.so.1
lrwxrwxrwx. ... libnvat.so.1 -> libnvat.so.1.2.2
-rwxr-xr-x. ... 34260448 ... libnvat.so.1.2.2

$ file build/nv-attestation-sdk-build/libnvat.so.1.2.2
build/nv-attestation-sdk-build/libnvat.so.1.2.2: ELF 64-bit LSB shared object, x86-64, version 1 (GNU/Linux), dynamically linked, BuildID[sha1]=441efa9ab33370f8ac65fdfe9f852aff48f3b9b2, with debug_info, not stripped
```

Command (LIB is the real file, not a symlink):

```text
$ pwd
/home/jer/.hopper/worktrees/6patvfem
$ LIB=build/nv-attestation-sdk-build/libnvat.so.1.2.2
$ strings -a "$LIB" | grep -F "$(pwd)/build/openssl-install" | sort | uniq -c
      1 ENGINESDIR: "/home/jer/.hopper/worktrees/6patvfem/build/openssl-install/lib/engines-3"
      2 /home/jer/.hopper/worktrees/6patvfem/build/openssl-install
      1 /home/jer/.hopper/worktrees/6patvfem/build/openssl-install/cert.pem
      1 /home/jer/.hopper/worktrees/6patvfem/build/openssl-install/certs
      1 /home/jer/.hopper/worktrees/6patvfem/build/openssl-install/ct_log_list.cnf
      1 /home/jer/.hopper/worktrees/6patvfem/build/openssl-install/lib/engines-3
      1 /home/jer/.hopper/worktrees/6patvfem/build/openssl-install/lib/ossl-modules
      1 /home/jer/.hopper/worktrees/6patvfem/build/openssl-install/private
      1 MODULESDIR: "/home/jer/.hopper/worktrees/6patvfem/build/openssl-install/lib/ossl-modules"
      1 OPENSSLDIR: "/home/jer/.hopper/worktrees/6patvfem/build/openssl-install"
```

**Count: 11 occurrences, 10 unique C-strings.** The scope's 11 is the
occurrence count (`uniq -c` sums to 11). The duplicate is the bare
OPENSSLDIR path (count 2). Unique C-string count is 10, not 11.

Byte-exact unique C-strings, with occurrence counts from a NUL-delimited
scan of the same file:

```text
   2 b'/home/jer/.hopper/worktrees/6patvfem/build/openssl-install'
   1 b'/home/jer/.hopper/worktrees/6patvfem/build/openssl-install/private'
   1 b'/home/jer/.hopper/worktrees/6patvfem/build/openssl-install/certs'
   1 b'/home/jer/.hopper/worktrees/6patvfem/build/openssl-install/cert.pem'
   1 b'/home/jer/.hopper/worktrees/6patvfem/build/openssl-install/lib/engines-3'
   1 b'/home/jer/.hopper/worktrees/6patvfem/build/openssl-install/lib/ossl-modules'
   1 b'/home/jer/.hopper/worktrees/6patvfem/build/openssl-install/ct_log_list.cnf'
   1 b'OPENSSLDIR: "/home/jer/.hopper/worktrees/6patvfem/build/openssl-install"'
   1 b'ENGINESDIR: "/home/jer/.hopper/worktrees/6patvfem/build/openssl-install/lib/engines-3"'
   1 b'MODULESDIR: "/home/jer/.hopper/worktrees/6patvfem/build/openssl-install/lib/ossl-modules"'
unique 10 total 11
```

**Split, confirming the scope's 7 / 4 arithmetic on occurrences:**

openssldir-derived (7 occurrences, 6 unique C-strings):

| n | literal |
| --- | --- |
| 1 | `OPENSSLDIR: "/home/jer/.hopper/worktrees/6patvfem/build/openssl-install"` |
| 2 | `/home/jer/.hopper/worktrees/6patvfem/build/openssl-install` |
| 1 | `/home/jer/.hopper/worktrees/6patvfem/build/openssl-install/certs` |
| 1 | `/home/jer/.hopper/worktrees/6patvfem/build/openssl-install/cert.pem` |
| 1 | `/home/jer/.hopper/worktrees/6patvfem/build/openssl-install/private` |
| 1 | `/home/jer/.hopper/worktrees/6patvfem/build/openssl-install/ct_log_list.cnf` |

prefix-derived (4 occurrences, 4 unique C-strings):

| n | literal |
| --- | --- |
| 1 | `ENGINESDIR: "/home/jer/.hopper/worktrees/6patvfem/build/openssl-install/lib/engines-3"` |
| 1 | `/home/jer/.hopper/worktrees/6patvfem/build/openssl-install/lib/engines-3` |
| 1 | `MODULESDIR: "/home/jer/.hopper/worktrees/6patvfem/build/openssl-install/lib/ossl-modules"` |
| 1 | `/home/jer/.hopper/worktrees/6patvfem/build/openssl-install/lib/ossl-modules` |

`11 − 7 = 4` holds on occurrences. After dropping the six unique
openssldir C-strings, four unique prefix C-strings remain. The
`--prefix`-derived family is `ENGINESDIR`, `MODULESDIR`, and their two
banner strings, as the scope claimed.

`libssl.a` and `libcurl.a` contain none of these. `libcrypto.a` contains
the same 11-occurrence histogram as `libnvat.so.1.2.2`.

Generated OpenSSL Makefile (in-source EP, `BUILD_IN_SOURCE 1`):

```text
INSTALLTOP=/home/jer/.hopper/worktrees/6patvfem/build/openssl-install
OPENSSLDIR=/home/jer/.hopper/worktrees/6patvfem/build/openssl-install
LIBDIR=lib
libdir=$(INSTALLTOP)/$(LIBDIR)
ENGINESDIR=$(libdir)/engines-3
MODULESDIR=$(libdir)/ossl-modules
LIB_CPPFLAGS=... -DOPENSSLDIR="\"$(OPENSSLDIR)\"" -DENGINESDIR="\"$(ENGINESDIR)\"" -DMODULESDIR="\"$(MODULESDIR)\"" ...
```

Today OPENSSLDIR == INSTALLTOP because `--openssldir` was given the
prefix. `unix-Makefile.tmpl:307-330` (quoted under Q6) is the rule that
makes an *absolute* `--openssldir` the OPENSSLDIR value without change.

## Q2 — openssldir-exclusive strings and their OpenSSL origins

Expected family vs this artifact:

| Expected | Present as a contiguous C-string? | Producer |
| --- | --- | --- |
| `<openssldir>/certs` | yes | `X509_CERT_DIR` |
| `<openssldir>/cert.pem` | yes | `X509_CERT_FILE` |
| `<openssldir>/private` | yes | `X509_PRIVATE_DIR` |
| `<openssldir>/ct_log_list.cnf` | yes | `CTLOG_FILE` |
| `<openssldir>/openssl.cnf` | **no** | runtime concat, not a baked path |
| `OPENSSLDIR: "<value>"` | yes | `OpenSSL_version(OPENSSL_DIR)` |
| bare `<openssldir>` (count 2) | yes | `OPENSSLDIR` / `X509_CERT_AREA` |

**Correction for the gate needle:** do not include
`<openssldir>/openssl.cnf`. It is not in the artifact. `openssl.cnf`
appears only as the bare filename (`OPENSSL_CONF` in
`include/internal/common.h:80`). `CONF_get1_default_config_file`
(`crypto/conf/conf_mod.c:690-714`) builds
`X509_get_default_cert_area()` + `"/"` + `OPENSSL_CONF` with
`BIO_snprintf` at runtime.

Defines (`include/internal/common.h:80-87`):

```c
#define OPENSSL_CONF "openssl.cnf"

#ifndef OPENSSL_SYS_VMS
#define X509_CERT_AREA OPENSSLDIR
#define X509_CERT_DIR OPENSSLDIR "/certs"
#define X509_CERT_FILE OPENSSLDIR "/cert.pem"
#define X509_PRIVATE_DIR OPENSSLDIR "/private"
#define CTLOG_FILE OPENSSLDIR "/ct_log_list.cnf"
```

Callers that emit those strings on Unix (this build):

- `crypto/x509/x509_def.c:69-106` — `X509_get_default_private_dir` /
  `cert_area` / `cert_dir` / `cert_file` return the four `X509_*`
  macros. Two compilation units both return the bare `OPENSSLDIR`
  (`x509_def.c` via `X509_CERT_AREA`, `crypto/defaults.c:158-159`
  `ossl_get_openssldir` via `return OPENSSLDIR;`), which is why the
  bare path occurs twice.
- `crypto/ct/ct_log.c:163-166` — `CTLOG_STORE_load_default_file` uses
  `CTLOG_FILE` when `CTLOG_FILE` env is unset.
- `crypto/cversion.c:108-109` — `return "OPENSSLDIR: \"" OPENSSLDIR "\"";`
- `crypto/x509/x509_d2.c:15-43` `X509_STORE_set_default_paths_ex` loads
  `X509_FILETYPE_DEFAULT`, which
  `crypto/x509/by_file.c:55-63` resolves to
  `X509_get_default_cert_file()` (`.../cert.pem`) and
  `crypto/x509/by_dir.c:90-97` to `X509_get_default_cert_dir()`
  (`.../certs`).

Prefix-derived (not openssldir-exclusive), for contrast:

- `crypto/defaults.c:174` `return ENGINESDIR;`
- `crypto/defaults.c:190` `return MODULESDIR;`
- `crypto/cversion.c:114-121` `ENGINESDIR: "..."` / `MODULESDIR: "..."`
  banners.

`ENGINESDIR` / `MODULESDIR` come from `--prefix` + `--libdir=lib`
(`$(INSTALLTOP)/lib/engines-3`, `$(INSTALLTOP)/lib/ossl-modules`).
`no-engine` (`CMakeLists.txt:243`) does not drop the ENGINESDIR strings.

The six unique openssldir C-strings above are the regression-needle
set. A substring of `<builddir>/openssl-install` that also matches
`.../lib/engines-3` or `.../lib/ossl-modules` is not exclusive.

## Q3 — Negative twin, byte-exact

From the same NUL-delimited scan of
`build/nv-attestation-sdk-build/libnvat.so.1.2.2`:

```text
'/home/jer/.hopper/worktrees/6patvfem/build/openssl-install/lib/ossl-modules'
```

hex:
`2f686f6d652f6a65722f2e686f707065722f776f726b74726565732f367061747666656d2f6275696c642f6f70656e73736c2d696e7374616c6c2f6c69622f6f73736c2d6d6f64756c6573`

The banner form is a *different* C-string:

```text
'MODULESDIR: "/home/jer/.hopper/worktrees/6patvfem/build/openssl-install/lib/ossl-modules"'
```

The twin test wants the path without the banner prefix, as it appears as
its own C-string. It is prefix-derived (`MODULESDIR`), not
openssldir-derived. After an `--openssldir` change it must still be
present (this `<builddir>` value, or the equivalent
`<prefix>/lib/ossl-modules` on a release `-B`).

## Q4 — `/etc/ssl/cert.pem` in the library and archives

**Verdict: clean.** Appending `b"/etc/ssl/cert.pem"` to
`FORBIDDEN_CA_PATHS` would not turn this pre-fix artifact red.

Python `bytes.find` on whole files (`-1` = absent):

```text
build/nv-attestation-sdk-build/libnvat.so.1.2.2: size=34260448
  /etc/ssl/cert.pem: -1
  /etc/ssl/certs/ca-certificates.crt: -1
  /etc/pki/tls/certs/ca-bundle.crt: -1
build/nvattest: size=1347456  (all three -1)
build/openssl-install/lib/libcrypto.a: size=12821518  (all three -1)
build/openssl-install/lib/libssl.a: size=2368570  (all three -1)
build/curl-install/lib/libcurl.a: size=1236674  (all three -1)
build/xmlsec-install/lib/libxmlsec1.a: size=987598  (all three -1)
build/xmlsec-install/lib/libxmlsec1-openssl.a: size=630096  (all three -1)
build/libxml2-install/lib/libxml2.a: size=2447918  (all three -1)
```

`strings -a` of `libnvat.so.1.2.2` for `/etc/ssl` is empty.
`data.find(b"/etc/ssl")` is `-1`.

Related fragments that *are* present, and must not be confused with the
contiguous needle:

```text
b'openssl.cnf'          count 1   (OPENSSL_CONF filename only)
b'/openssl.cnf'         count 0
b'ssl/cert.pem'         count 1   (nv_http.cpp split; see below)
b'/etc/ssl/cert.pem'    count 0
```

`nv_http.cpp:39-45` splits our own literals so the contiguous host
paths are not compiled in:

```cpp
        const std::array<std::string, 5> CA_BUNDLE_PROBE_PATHS = {{
            std::string("/etc/") + "ssl/certs/ca-certificates.crt",
            std::string("/etc/") + "pki/tls/certs/ca-bundle.crt",
            std::string("/etc/") + "ssl/ca-bundle.pem",
            std::string("/etc/") + "ca-certificates/extracted/tls-ca-bundle.pem",
            std::string("/etc/") + "ssl/cert.pem",
        }};
```

That is why `ssl/cert.pem` exists as its own C-string and
`/etc/ssl/cert.pem` does not. A `FORBIDDEN_CA_PATHS` member of
`/etc/ssl/cert.pem` matches only the contiguous 17-byte sequence.

On this host `/etc/ssl/cert.pem` itself does not exist
(`ABSENT /etc/ssl/cert.pem`); `/etc/ssl/certs` is a symlink to
`../../var/lib/ca-certificates/pem`. That is a distro layout fact, not
a baked string.

## Q5 — Candidate `--openssldir` values

Clauses applied to every candidate:

- absolute (required: `unix-Makefile.tmpl:307-330` — a relative
  `--openssldir` is concatenated onto `$prefix`, which is
  `CMAKE_BINARY_DIR/openssl-install`, i.e. the defect again);
- identical on Linux container (`CMAKE_BINARY_DIR=/src/build/release`)
  and Darwin native (`<repo>/build/release`);
- not `/etc/ssl`, `/etc/pki`, `/usr/local/ssl`, `/private/etc/ssl`,
  `/tmp`, `/var/tmp`;
- non-existent, not a host trust root, not world-writable;
- unprivileged process cannot create it on this Linux host (exercised)
  and on macOS 11+ (cited, not exercised).

Three candidates evaluated:

| | `/nvat-openssl` | `/usr/nvat-openssl` | `/opt/nvat-openssl` |
| --- | --- | --- | --- |
| absolute, identical on both OS | yes | yes | yes |
| outside `CMAKE_BINARY_DIR` | yes | yes | yes |
| in the by-name prohibition list | no | no | no |
| exists here | no | no | no |
| unprivileged `mkdir` here | `Permission denied` | `Permission denied` | `Permission denied` |
| parent exists / mode here | `/` root `755` (btrfs rw snapshot) | `/usr` root `755` | `/opt` root `555` |
| host trust root | no | no | no |
| world-writable | no | no | no |
| SIP-protected `/usr` `/var` `/System` (Apple 102149) | n/a (new name at `/`) | yes (`/usr`, not the `/usr/local` carve-out) | **no** (`/opt` is not on the SIP list) |
| SSV sealed system volume (Apple SSV page, macOS 11+) | write would be to the read-only system volume | `/usr` is on the system volume | `/opt` is not listed as SIP-protected; Homebrew-on-ARM already lives under `/opt/homebrew` |

Commands (uid 1000, this lode):

```text
$ ls -ld / /usr /opt /tmp /var/tmp /etc/ssl
drwxr-xr-x.    1 root root    150 May 22 17:15 /
drwxr-xr-x.    1 root root    124 Mar  2 05:41 /usr
dr-xr-xr-x.    1 root root     12 Apr 16 14:48 /opt
drwxrwxrwt. 9531 root root 198460 Aug 20 11:05 /tmp
drwxrwxrwt.    1 root root 292038 Aug 20 11:07 /var/tmp
drwxr-xr-x.    1 root root    134 Jun  8 07:21 /etc/ssl

$ for p in /nvat-openssl /usr/nvat-openssl /opt/nvat-openssl; do
>   mkdir "$p" 2>&1 || true
> done
mkdir: cannot create directory ‘/nvat-openssl’: Permission denied
mkdir: cannot create directory ‘/usr/nvat-openssl’: Permission denied
mkdir: cannot create directory ‘/opt/nvat-openssl’: Permission denied

EXISTS /etc/ssl
ABSENT  /usr/local/ssl
ABSENT  /private/etc/ssl
ABSENT  /etc/ssl/cert.pem
```

`/tmp` and `/var/tmp` are `1777` — disqualified by the clause, not
exercised as candidates.

**Recommend `/nvat-openssl`.**

Why the runners-up lose:

- `/usr/nvat-openssl` is a real FHS prefix. Apple's SIP list protects
  `/usr` but explicitly carves out `/usr/local` as writable
  (https://support.apple.com/en-us/102149, retrieved 2026-08-20:
  "Paths and apps that third-party apps and installers can continue to
  write to include: `/Applications`, `/Library`, `/usr/local`").
  `/usr/local/ssl` is already a by-name prohibition (classic OpenSSL
  default). A `/usr/...` openssldir sits next to that carve-out and
  looks like an install prefix rather than a deliberately non-existent
  data area.
- `/opt/nvat-openssl` is **not** on the SIP protected list. The parent
  `/opt` exists on this host and on many Linux images; Apple Silicon
  Homebrew already uses `/opt/homebrew`. An unprivileged Homebrew user
  does not own `/opt` itself, but `/opt` is the weakest of the three
  against "cannot be created" on macOS because it is outside SIP and
  outside the sealed system-volume root.

macOS evidence is a citation, not a mkdir on this lode (Linux only):

- SIP (Apple Support 102149, title "About System Integrity Protection
  on your Mac"): "System Integrity Protection includes protection for
  these parts of the system: `/System`, `/usr`, `/bin`, `/sbin`,
  `/var`." SIP "restricts the root user account and limits the actions
  that the root user can perform on protected parts of the Mac
  operating system."
- Signed system volume (Apple Platform Security,
  https://support.apple.com/guide/security/signed-system-volume-security-secd698747c9/web,
  retrieved 2026-08-20): "In macOS 10.15, Apple introduced the
  read-only system volume, a dedicated, isolated volume for system
  content. macOS 11 or later adds strong cryptographic protections to
  system content with a signed system volume (SSV). SSV features a
  kernel mechanism that verifies the integrity of the system content at
  runtime and rejects any data—code and noncode—without a valid
  cryptographic signature from Apple." The same page distinguishes the
  sealed system volume from the user *data volume*. A new top-level
  name such as `/nvat-openssl` is not a data-volume firmlink; creating
  it is a write to the sealed system volume.

RHEL8-family Linux was not a second machine. This Tumbleweed host
shows the POSIX fact the container will share: `/` is `root:root` `755`,
unprivileged `mkdir /nvat-openssl` is `EACCES`. The CI/release
Containerfile (`sol/ci/Containerfile`) has no `USER`, so the *build*
runs as root and *could* create `/nvat-openssl` if `install_ssldirs`
still ran — that is Q6, not a reason to pick a different path.

## Q6 — Configure accepts the candidate without creating it; `install_sw` vs `install_ssldirs`

### Configure does not mkdir `--openssldir`

`Configure:59` documents `--openssldir` as "OpenSSL data area, such as
openssl.cnf, certificates and keys." Parser (`Configure:1053-1055`):

```perl
                elsif (/^--openssldir=(.*)$/)
                        {
                        $config{openssldir}=$1;
                        }
```

It stores the string. It does not create the directory.

Empirical, throwaway tree under `/var/tmp` (the live in-source EP
Makefile was **not** overwritten). Tarball
`build/nv-attestation-sdk-build/openssl_external-prefix/src/openssl-3.6.1.tar.gz`
extracted to `/var/tmp/nvat-openssl-q6/openssl-3.6.1`:

```text
$ ./Configure linux-x86_64 \
    --prefix=/var/tmp/nvat-openssl-q6/pfx \
    --openssldir=/nvat-openssl \
    --libdir=lib \
    no-shared no-tests no-apps no-docs no-legacy no-engine no-dtls
Configuring OpenSSL version 3.6.1 for target linux-x86_64
...
***   OpenSSL has been successfully configured                     ***
CONFIGURE_EXIT=0
after /nvat-openssl: NO
after pfx: NO

INSTALLTOP=/var/tmp/nvat-openssl-q6/pfx
OPENSSLDIR=/nvat-openssl
LIBDIR=lib
libdir=$(INSTALLTOP)/$(LIBDIR)
ENGINESDIR=$(libdir)/engines-3
MODULESDIR=$(libdir)/ossl-modules
PKGCONFIGDIR=$(libdir)/pkgconfig
```

`--openssldir=/nvat-openssl` was accepted. Neither `/nvat-openssl` nor
the prefix directory was created. Live EP Makefile still has
`OPENSSLDIR=/home/jer/.hopper/worktrees/6patvfem/build/openssl-install`.

A first attempt to run the *already-configured* in-source tree's
`Configure` from `/var/tmp` failed with "There are files missing" /
`Makefile wasn't produced` because that source dir already had an
in-source build. It also did not create `/nvat-openssl`. The clean
tarball extract is the successful measurement.

### `install_sw` vs `install_ssldirs` (tmpl + both generated Makefiles)

`Configurations/unix-Makefile.tmpl:666-719` (and the generated
Makefiles, same recipes):

```make
install: Makefile ## Install software and documentation, create OpenSSL directories
	$(MAKE) install_sw
	$(MAKE) install_ssldirs

install_sw: install_dev install_engines install_modules install_runtime ## Install just the software and libraries

install_ssldirs:
	@$(PERL) $(SRCDIR)/util/mkdir-p.pl "$(DESTDIR)$(OPENSSLDIR)/certs"
	@$(PERL) $(SRCDIR)/util/mkdir-p.pl "$(DESTDIR)$(OPENSSLDIR)/private"
	@$(PERL) $(SRCDIR)/util/mkdir-p.pl "$(DESTDIR)$(OPENSSLDIR)/misc"
	... copies openssl.cnf / ct_log_list.cnf into OPENSSLDIR ...
```

`install_dev` (generated Makefile ~2767, invoked by `install_sw`):

```make
install_dev: install_runtime_libs
	@$(PERL) $(SRCDIR)/util/mkdir-p.pl "$(DESTDIR)$(INSTALLTOP)/include/openssl"
	... cp include/openssl/*.h ...
	@$(PERL) $(SRCDIR)/util/mkdir-p.pl "$(DESTDIR)$(libdir)"
	... cp $(INSTALL_LIBS) -> $(libdir) ...
	@$(PERL) $(SRCDIR)/util/mkdir-p.pl "$(DESTDIR)$(PKGCONFIGDIR)"
	... cp $(INSTALL_EXPORTERS_PKGCONFIG) ...
```

Live Makefile:

```text
INSTALL_LIBS=libcrypto.a libssl.a
INSTALL_EXPORTERS_PKGCONFIG=exporters/libcrypto.pc exporters/libssl.pc \
                            exporters/openssl.pc
```

Those four files plus `include/openssl/*` are exactly what
`CMakeLists.txt:250-266` consumes (`OPENSSL_INCLUDE_DIR`,
`libcrypto.a`, `libssl.a`) and what curl/xmlsec consume via
`PKG_CONFIG_PATH=${OPENSSL_INSTALL_DIR}/lib/pkgconfig`.

`mkdir-p.pl` of `$(DESTDIR)$(OPENSSLDIR)` in the *generated* Makefile
(fips disabled, matching `CMakeLists.txt` flags):

```text
# Q6 Makefile (prefix ≠ openssldir) and live EP Makefile (prefix == openssldir):
2727: mkdir-p.pl "$(DESTDIR)$(OPENSSLDIR)/certs"
2728: mkdir-p.pl "$(DESTDIR)$(OPENSSLDIR)/private"
2729: mkdir-p.pl "$(DESTDIR)$(OPENSSLDIR)/misc"
```

Those three lines are the `install_ssldirs` body. `mkdir-p` of a child
creates `$(DESTDIR)$(OPENSSLDIR)` as a parent. There is no other live
`mkdir-p.pl "$(DESTDIR)$(OPENSSLDIR)"` when fips is disabled.

The tmpl *does* mkdir OPENSSLDIR directly in `install_fips` when fips
is enabled (`unix-Makefile.tmpl:691`). Our generated Makefile stubs
that target:

```make
install_fips:
	@$(ECHO) "The 'install_fips' target requires the 'enable-fips' option"
```

`install_sw` mkdir's `INSTALLTOP`, `libdir`, `PKGCONFIGDIR`,
`ENGINESDIR`, `MODULESDIR` — prefix paths, not OPENSSLDIR. When
`--openssldir=/nvat-openssl` and `--prefix=<builddir>/openssl-install`,
`install_sw` alone does not create `/nvat-openssl`.

`make install_sw` was **not** executed in the scratch tree (it would
compile OpenSSL 3.6.1). The claim that `install_sw` still produces
`lib/libcrypto.a`, `lib/libssl.a`, `include/openssl/*`, and
`lib/pkgconfig/{libcrypto,libssl,openssl}.pc` is from the `install_dev`
recipe plus the live prefix, which already contains exactly those
files:

```text
build/openssl-install/lib/libcrypto.a
build/openssl-install/lib/libssl.a
build/openssl-install/include/openssl/   (142 headers)
build/openssl-install/lib/pkgconfig/libcrypto.pc
build/openssl-install/lib/pkgconfig/libssl.pc
build/openssl-install/lib/pkgconfig/openssl.pc
```

`install_ssldirs` is what populated `certs/`, `private/`, `misc/`,
`openssl.cnf`, `ct_log_list.cnf` next to them in the live tree, because
today OPENSSLDIR == INSTALLTOP.

Containerfile has no `USER`. A root `make install_ssldirs` with
`OPENSSLDIR=/nvat-openssl` **would** create `/nvat-openssl` inside the
build container. Configure will not; `install_sw` will not.

## Consumers and touch points

| Location | Relation |
| --- | --- |
| `nv-attestation-sdk-cpp/CMakeLists.txt:226,235-246` | defect; `--prefix` and `OPENSSL_INSTALL_DIR` stay |
| `:250-266` | imported `OpenSSL::Crypto` / `OpenSSL::SSL` from `${OPENSSL_INSTALL_DIR}/lib/*.a` |
| `:307,317,334,350` | curl/xmlsec `--with-openssl` / `PKG_CONFIG_PATH` against the **prefix**, not OPENSSLDIR |
| `sol/release/release_rail/gate.py:12-15,39-42,70,132` | whole-file substring gate |
| `sol/release/release_rail/elf.py:81-82,184` / `macho.py:81,149` | `info.data` is the full file |
| `sol/release/tests/test_gate.py:95-120` | iterates `FORBIDDEN_CA_PATHS` for ELF and Mach-O |
| `sol/release/release_rail/driver.py:379-383,584-605` | `_gate_binaries` on staged `bin/nvattest` and `lib/*`; Linux `-B build/release`, Darwin the same path natively |
| `Makefile:52-55` | CI `-B build` → container prefix `/src/build` |
| `nv-attestation-sdk-cpp/src/nv_http.cpp:39-45` | split host CA probes, including `ssl/cert.pem` |
| `sol/release/tests/test_curl.py:16,22` | baked `--with-openssl=/src/build/openssl-install` (prefix; not OPENSSLDIR) |
| `sol/release/tests/test_baseline_stability.py` | freezes SDK `project()`, FetchContent/ExternalProject **URL/URL_HASH**, `corrosion_import_crate`, `nvat_exempt_compiled_third_party`. `generate-dependencies.py:95-96` reads `URL` / `URL_HASH` only. `--openssldir` is not a frozen coordinate. |
| curl `lib/vtls/openssl.c:3270-3275` | `CURL_CA_FALLBACK` → discarded `X509_STORE_set_default_paths` |

`nvattest` does not contain the bake; `libnvat.so*` does. The gate
already walks both (`gate.is_binary_member`, `driver._gate_binaries`).

## Patterns to follow

- Gate policy is whole-file `bytes` membership, not parsed string
  tables. A needle must be a contiguous sequence that actually appears.
- Host CA paths that the SDK itself probes are already split
  (`"/etc/" + "ssl/cert.pem"`) so they do not trip that gate.
- Vendored OpenSSL prefix is `CMAKE_BINARY_DIR/openssl-install` with
  `--libdir=lib`. That prefix is also curl's `--with-openssl` and
  xmlsec's `--with-openssl`. Changing OPENSSLDIR does not change those.
- `unix-Makefile.tmpl` treats an absolute `--openssldir` as OPENSSLDIR
  verbatim. Relative would re-attach to prefix.
- `install_sw` is software+headers+pc; `install_ssldirs` is the data
  area. `install` runs both. The ExternalProject `INSTALL_COMMAND`
  currently names both.
- Do not treat a missing `openssl.cnf` or missing default cert file as
  a hard OpenSSL/curl failure. The flags and `ERR_clear_error` /
  ignored return are intentional.

## Unobserved here

- Native macOS mkdir / SIP / SSV were not exercised; only Apple's
  published pages were retrieved.
- RHEL8-family container was not entered. Container root vs
  unprivileged is inferred from `Containerfile` having no `USER`.
- `make install_sw` was not run in the Q6 scratch tree.
- Darwin `libnvat.dylib` strings were not measured. The defines are
  the same Unix ones (`ifndef OPENSSL_SYS_VMS`).
- `make ci` / `make release` / the 177-test suite were not run.
- The `/var/tmp/nvat-openssl-q6` Configure tree was a throwaway and
  was removed after this note.
