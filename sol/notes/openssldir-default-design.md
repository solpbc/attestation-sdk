# nvattest vendored OpenSSL `--openssldir` default design

**Authority.** This record is the implementation authority for stopping the
vendored OpenSSL 3.6.1 build from compiling `CMAKE_BINARY_DIR/openssl-install`
in as OPENSSLDIR (the default trust-store / config data area), and for
failing closed if that bake returns. It accepts
`sol/notes/openssldir-default-prep.md` as ground truth and does not re-derive
prep Q1–Q6. The prep's 11-occurrence histogram, 7/4 split, and Q4 clean
verdict have been independently confirmed.

This is a compile-time bake plus a whole-file string gate. It does not fail
loudly at runtime: curl's `CURL_CA_FALLBACK` branch discards
`X509_STORE_set_default_paths`'s return value, and libcrypto's `openssl.cnf`
autoload is non-fatal by design (`DEFAULT_CONF_MFLAGS` includes
`CONF_MFLAGS_IGNORE_MISSING_FILE` and `CONF_MFLAGS_IGNORE_RETURN_CODES`).
`nv_http.cpp`'s CA-resolution tiers are what actually find a bundle.

**Citation basis.** Repository line citations refer to integration tip
`493c1a7` (`sol: document the re-pin and baseline move required after a
rebase`), the same tree the prep measured.

## Change surface

One implementation commit changes:

* `nv-attestation-sdk-cpp/CMakeLists.txt` lines 236 and 246 only
  (`--openssldir=…`, `INSTALL_COMMAND`);
* `sol/release/release_rail/gate.py` (`FORBIDDEN_CA_PATHS` one-entry
  append, new sibling constant, `_forbidden_strings`);
* `sol/release/tests/test_gate.py` (two new methods);
* `sol/release/README.md` (one paragraph under Verification
  responsibility → Authored and checked on the lode);
* new `sol/notes/openssl-enginesdir-modulesdir.md` (D5.1).

The prep note and this design note are the documentation records.

Explicitly unchanged:

* `nv-attestation-sdk-cpp/src/nv_http.cpp`;
* `sol/release/targets.toml`;
* `--prefix=${OPENSSL_INSTALL_DIR}` (`CMakeLists.txt:235`) and
  `set(OPENSSL_INSTALL_DIR …)` (`:226`);
* the four `OPENSSL_INSTALL_DIR` consumers at `:307`, `:317`, `:334`,
  `:350` (`--with-openssl=` and `PKG_CONFIG_PATH=`);
* imported OpenSSL targets at `:250-272`;
* `sol/release/release_rail/curl.py`;
* `gate.is_binary_member`;
* the DT_NEEDED / Mach-O allowlist mechanism;
* `driver.py` (`_gate_binaries` already runs on staged and extracted
  binaries at `:606` and `:627`);
* `rail.py`, `fixtures.py`, `authority.py`, Containerfile, Makefile,
  `test_baseline_stability.py`, `test_curl.py`.

No test may assert over `CMakeLists.txt`'s configure-flag text. The
binary string gate is the single guard. A source-text assertion on
`--openssldir` would be a parallel truth source that drifts from what
the compiler actually baked.

Editing `:236` / `:246` does not disturb `test_baseline_stability.py`.
`test_all_dependency_coordinates_and_rust_wiring_are_unchanged`
(`test_baseline_stability.py:151-219`) freezes, for the SDK
`CMakeLists.txt`: the `project(… VERSION …)` identity (`:174-179`), the
`corrosion_import_crate` token list (`:183-201`), and the dependency
coordinate records (`:91-110`, `:167-172`) which are
`(kind, name, "git"|"archive", repository|url, tag|url_hash)` only.
`generate-dependencies.py:95-96` reads `URL` / `URL_HASH`.
`test_compiled_warning_exemption_is_byte_identical` (`:318-339`) freezes
the `nvat_exempt_compiled_third_party` function body and its two call
sites. None of those tokens include `--openssldir` or `install_ssldirs`.

## D1 — `--openssldir=/nvat-openssl`

The value is the literal absolute path `/nvat-openssl`. It is not a
CMake variable, not relative, and not derived from `CMAKE_BINARY_DIR`.
Prep Q5 recommended it; no defect in that recommendation is recorded
here.

It is the compiled default trust store, and it is deliberately empty.
OpenSSL will look for `/nvat-openssl/cert.pem`, `/nvat-openssl/certs`,
and `/nvat-openssl/openssl.cnf` (the last constructed at runtime). Those
paths will not exist. That is the honest "no baked default", not a
working CA location. Operator and distro bundles continue to come from
`nv_http.cpp`'s resolution tiers.

### Every clause

* **Absolute.** `unix-Makefile.tmpl:307-330`: a relative `--openssldir`
  is concatenated onto `$prefix`. `$prefix` is
  `${CMAKE_BINARY_DIR}/openssl-install`. A relative value would recreate
  the defect. `/nvat-openssl` is absolute, so OPENSSLDIR is that string
  without change (prep Q6: generated `OPENSSLDIR=/nvat-openssl`).
* **Outside `CMAKE_BINARY_DIR` on both release layouts.** Linux
  container `_build` (`driver.py:279-284`) is `-B build/release` with
  `-w /src`, so `CMAKE_BINARY_DIR` is `/src/build/release`. Darwin
  native `_build` (`driver.py:294-300`) is the same `build/release` on
  the host, so `CMAKE_BINARY_DIR` is `<repo-root>/build/release`.
  `/nvat-openssl` is neither of those and does not sit under either.
  (CI `Makefile:52-55` uses `-B build` → `/src/build`; also not a
  parent of `/nvat-openssl`.)
* **Not a by-name prohibition, not a host trust root, not
  world-writable, non-existent, unprivileged-non-creatable.** Walked
  with the rejected values below. Prep Q5: `ABSENT /nvat-openssl`;
  unprivileged `mkdir /nvat-openssl` → `Permission denied`. macOS is
  citation (Apple 102149 SIP; Apple SSV page for the macOS 10.15+
  read-only system volume / macOS 11+ signed system volume), not a
  mkdir on this lode.

### Why each prohibited value was rejected

Two failure modes, used below:

* **(a) `install_ssldirs` writing into the host/container system tree
  at build time.** That target `mkdir -p`s
  `$(DESTDIR)$(OPENSSLDIR)/{certs,private,misc}` and copies
  `openssl.cnf` / `ct_log_list.cnf` there (prep Q6). The CI/release
  Containerfile has no `USER`, so the build is root. A root
  `install_ssldirs` against a real system path succeeds and plants
  OpenSSL's stock config and empty cert dirs on top of, or beside, the
  distro trust store.
* **(b) shipping a library whose compiled default trust store is
  world-writable.** `X509_STORE_set_default_paths` loads
  `OPENSSLDIR/cert.pem` and `OPENSSLDIR/certs`. If OPENSSLDIR is `1777`,
  any local user can plant a CA.

`/etc/ssl` looks like "the obvious OpenSSL data area" on Debian,
Alpine, and macOS (`/etc/ssl` → `/private/etc/ssl`). It is a host trust
root. Root `install_ssldirs` would write `openssl.cnf` and `certs/`
into the system SSL directory **(a)**. The compiled default would then
be the *host* store, which is the opposite of a self-contained
release. Rejected.

`/etc/pki` is the RHEL-family trust root (`/etc/pki/tls/certs/ca-bundle.crt`
is already a `FORBIDDEN_CA_PATHS` member). Same **(a)** against the
platform this rail actually builds on. Rejected.

`/usr/local/ssl` is OpenSSL's own default OPENSSLDIR when `--prefix`
is `/usr/local` and `--openssldir` is omitted (`Configure:59-63`,
default `PREFIX/ssl`). It is a real FHS location. Root
`install_ssldirs` would create a second OpenSSL data area on the
builder **(a)**. It is also the path people copy from OpenSSL's
INSTALL.md without noticing it is a host prefix. Rejected.

`/private/etc/ssl` is the Darwin host trust root (the target of
`/etc/ssl` on macOS). The Darwin release is a native `_build`. Even
when that build is unprivileged, the compiled default would still *name*
the host store; if the operator later ran install as root, **(a)**
writes into macOS's SSL directory. Rejected.

`/tmp` is `1777` (prep Q5). OPENSSLDIR there is **(b)**: anyone can
create `/tmp/cert.pem` or `/tmp/certs`. It is also in the prohibition
list because tmpfs contents are not a trust root and are not stable.
Rejected.

`/var/tmp` is the same **(b)** with a longer-lived world-writable
directory. Rejected.

`/nvat-openssl` is none of those. It is not a distro CA path. It is not
`1777`. Unprivileged processes cannot create it. A leftover
`install_ssldirs` as root *could* create it inside the container, which
is why D2 drops that target rather than relying on the path staying
absent by luck.

## D2 — Drop `install_ssldirs`

`INSTALL_COMMAND` becomes `make install_sw` only. `install_ssldirs` is
removed.

Consequence chain (prep Q6):

* `install_ssldirs` is the only live target that `mkdir -p`s
  `$(DESTDIR)$(OPENSSLDIR)` (via `certs` / `private` / `misc`) and
  copies `openssl.cnf` and `ct_log_list.cnf` there. `install_fips` would
  also mkdir OPENSSLDIR; fips is disabled and that target is a stub.
* With D1's `/nvat-openssl`, keeping `install_ssldirs` is not redundant.
  It is actively wrong. Configure does not create the directory (prep
  Q6: `CONFIGURE_EXIT=0`, `/nvat-openssl` still absent). The
  Containerfile declares no `USER`, so the container build runs as
  root, and a leftover `install_ssldirs` **would succeed** and create
  `/nvat-openssl` inside the container, complete with stock
  `openssl.cnf`. The compiled default would then point at a directory
  the build just invented.
* `install_sw` is `install_dev install_engines install_modules
  install_runtime`. `install_dev` installs `INSTALL_LIBS` (`libcrypto.a`
  `libssl.a`) into `$(libdir)`, headers into
  `$(INSTALLTOP)/include/openssl`, and
  `INSTALL_EXPORTERS_PKGCONFIG` (`libcrypto.pc` `libssl.pc` `openssl.pc`)
  into `$(PKGCONFIGDIR)`. Those are `--prefix` paths, not OPENSSLDIR.
  That is everything the imported targets at `:250-272` and the four
  `OPENSSL_INSTALL_DIR` consumers at `:307/317/334/350` need. Prep Q6
  did not run `make install_sw` in the scratch tree; the claim is the
  generated recipe plus the live prefix already containing those files
  from the original combined install.

`--prefix` does not change. `DESTDIR` is not introduced.

## D3 — Needle set and how the gate recognizes it

A correct fix takes **11 → 4** occurrences. The four survivors are
`--prefix`-derived (`ENGINESDIR`, `MODULESDIR`, and their two banners).
The seven openssldir-derived occurrences go away. The gate must fire on
the seven and must not fire on the four.

The needle is the openssldir-**exclusive** set, never the bare path.
`openssl-install` as a bare substring is a prefix of all four survivors
(`…/openssl-install/lib/engines-3`, `…/openssl-install/lib/ossl-modules`,
and the two banners). Gating on the bare marker would make a correct
fix red.

### (a) Anchoring: build-tree marker `openssl-install`

Anchor on the path component `openssl-install`, not on a prefix
threaded in from `driver`.

`OPENSSL_INSTALL_DIR` is `${CMAKE_BINARY_DIR}/openssl-install`
(`CMakeLists.txt:226`) on every target. The baked openssldir *today*
is that directory, so every exclusive string contains the component
`openssl-install` followed by `/certs`, `/cert.pem`, `/private`, or
`/ct_log_list.cnf`. That component is identical for
`/src/build/release/openssl-install` (Linux container),
`<repo-root>/build/release/openssl-install` (Darwin native), and
`/src/build/openssl-install` (CI `-B build`).

Threading the build prefix from `driver` would add a parameter to
`gate_file` and both `_gate_binaries` calls (`driver.py:606` staged,
`:627` extracted), and every `test_gate.py` fixture would have to plant
a matching prefix. The gate already searches whole-file bytes
(`elf.py:81-82`, `macho.py:81`; `_forbidden_strings` at `gate.py:39-42`,
called from `gate_elf` / `gate_macho`). A self-contained marker needs
none of that. `is_binary_member` is unchanged; `nvattest` contains zero
`openssl-install` bytes (prep), so the hit is `libnvat`, which is
already gated.

One needle set, one check. No configurable framework.

### (b) Needle members

Prep Q2: the openssldir-exclusive contiguous C-strings are `/certs`,
`/cert.pem`, `/private`, `/ct_log_list.cnf`, the `OPENSSLDIR: "…"`
banner, and two bare OPENSSLDIR occurrences. The four leaf paths are
the exclusive set that can be marker-anchored without matching the
survivors.

Constant, beside `FORBIDDEN_CA_PATHS` in `gate.py`:

```text
FORBIDDEN_OPENSSLDIR_PATHS = (
    b"openssl-install/certs",
    b"openssl-install/cert.pem",
    b"openssl-install/private",
    b"openssl-install/ct_log_list.cnf",
)
```

`<openssldir>/openssl.cnf` is **not** a needle. Prep Q2: it is not in
the artifact. `OPENSSL_CONF` is the bare filename `"openssl.cnf"`;
`CONF_get1_default_config_file` concatenates OPENSSLDIR + `"/"` + that
filename at runtime. A speculative `openssl-install/openssl.cnf` needle
would not have gone red on the pre-fix library and would not go red on
a regression that only restores the bake we measured.

Each chosen needle is **not** a substring of any of the four
`--prefix`-derived survivors. Survivors (prep Q1/Q3):

* `…/openssl-install/lib/engines-3`
* `…/openssl-install/lib/ossl-modules`
* `ENGINESDIR: "…/openssl-install/lib/engines-3"`
* `MODULESDIR: "…/openssl-install/lib/ossl-modules"`

`openssl-install/certs` is not inside `openssl-install/lib/…`.
`openssl-install/cert.pem` is not a prefix of `openssl-install/certs`
(the next byte is `s` vs `.`). `openssl-install/private` and
`openssl-install/ct_log_list.cnf` do not appear in `lib/engines-3` or
`lib/ossl-modules`. That is the property the negative twin tests.

### (c) The banner is not a needle

`OPENSSLDIR: "<value>"` exists after the fix too
(`cversion.c`: `return "OPENSSLDIR: \"" OPENSSLDIR "\";"`). After D1
it is `OPENSSLDIR: "/nvat-openssl"`. Gating on the bare banner prefix
`OPENSSLDIR: "` would fire unconditionally.

`b'openssl-install"'` would be a precise *pre-fix* banner needle: the
OPENSSLDIR banner is the only occurrence whose build-path form ends
`openssl-install"` (closing quote). The two bare OPENSSLDIR strings are
NUL-terminated; the two prefix-derived banners end `engines-3"` /
`ossl-modules"`.

It is **not included**. Any regression that repoints `--openssldir` at
the build-tree `openssl-install` directory reproduces all four leaf
strings. The banner would be redundant coverage of that one regression.
Redundant coverage of one regression is not a virtue. The four leaves
are the gate.

### (d) Residual detection limit

This design does not catch a regression that (1) renames
`OPENSSL_INSTALL_DIR` away from the path component `openssl-install`,
or (2) points `--openssldir` at some other build-tree directory that
does not contain that component followed by `/certs`, `/cert.pem`,
`/private`, or `/ct_log_list.cnf` — for example
`--openssldir=${CMAKE_BINARY_DIR}` (`/src/build/release/certs` has no
`openssl-install/certs`) or `--openssldir=${OPENSSL_INSTALL_DIR}/ssl`
(`openssl-install/ssl/certs` is not `openssl-install/certs`). It also
does not catch a host OPENSSLDIR that is none of the D4 CA paths.
Those misses are accepted. The gate is four fragments and one
`/etc/ssl/cert.pem` append, not a prefix-parameterized scanner.

### (e) Naming and seam

* Constant: `FORBIDDEN_OPENSSLDIR_PATHS` (above), a sibling of
  `FORBIDDEN_CA_PATHS` placed directly below it. The members are path
  fragments, not generic strings.
* Check: inside the existing `_forbidden_strings` (`gate.py:39-42`),
  after the `FORBIDDEN_CA_PATHS` loop, a second loop over
  `FORBIDDEN_OPENSSLDIR_PATHS`. Call sites stay
  `gate_elf` / `gate_macho` / `gate_file`. Both staged and extracted
  `driver._gate_binaries` passes are covered without a `driver.py` edit.
* Error message matches the neighbour two lines above in
  `_forbidden_strings` (`{path}: compiled host CA path found: …`),
  not `curl.py`'s `"<what> failed: <fact>"` shape.
  `GateError.__init__` already appends `; rebuild the target artifact
  with the reported policy violation corrected, then retry`. Do not
  duplicate a recovery clause.

```python
f"{path}: build-tree openssldir path found: {value.decode()}"
```

`{path}` is the gated file. `{value}` is the matching member of
`FORBIDDEN_OPENSSLDIR_PATHS`. The existing CA message is not reused
for these fragments and is not edited.

## D4 — `FORBIDDEN_CA_PATHS`

Prep Q4 came back clean (independently confirmed):
`b"/etc/ssl/cert.pem"` is absent from `libnvat.so.1.2.2`, `nvattest`,
and every vendored `.a`. `nv_http.cpp:44` splits
`"/etc/" + "ssl/cert.pem"`, so the contiguous 17-byte sequence is not
compiled in.

**Append exactly one entry**, `b"/etc/ssl/cert.pem"`, as the third
member of `FORBIDDEN_CA_PATHS`. Do not restructure the tuple,
`_forbidden_strings`, or its call sites. The D3 second loop is an
addition for a different constant, not a restructure of this tuple.

`test_baked_host_ca_paths_fail_for_each_format` (`test_gate.py:95`)
iterates `gate.FORBIDDEN_CA_PATHS` for ELF and Mach-O. The new entry is
covered automatically. No new test is written for it.

The "do not touch `FORBIDDEN_CA_PATHS`" constraint at
`curl-ca-configure-design.md:390` is narrowed here by this deliberate
exception, not overridden. That design's non-goal still holds for the
curl-config work: curl-config work must not edit this tuple. This
openssldir work may append this one Alpine/macOS fallback path because
Q4 proved it is currently absent and because it is a host CA path of
the same kind the tuple already forbids.

## D5 — Records

### D5.1 — `ENGINESDIR` / `MODULESDIR` non-goal

File: `sol/notes/openssl-enginesdir-modulesdir.md`, dated 2026-08-20
in the heading. It outlives this lode. Content, no more:

* Four `--prefix`-derived build-path strings survive this fix by
  design: `ENGINESDIR`, `MODULESDIR`, and their two
  `OpenSSL_version` banners. Prep Q1: those are the 4 in 11→4.
* `MODULESDIR` is a `dlopen` root (`ossl_get_modulesdir` /
  `$(libdir)/ossl-modules`) and is the higher-severity instance.
  `ENGINESDIR` is baked even with `no-engine` (`CMakeLists.txt:243`).
* OpenSSL 3.6.1 has **no** `--enginesdir` / `--modulesdir` Configure
  flag. Vendored `Configure` option parser (`Configure:1042-1164`)
  accepts `--api`, `--libdir`, `--openssldir`, `--with-*`, `--fips-key`,
  `--banner`, `--cross-compile-prefix`, `--config`, `--help`. It does
  not accept `--enginesdir` or `--modulesdir`.
  `Configurations/unix-Makefile.tmpl:336-337` hard-wires
  `ENGINESDIR=$(libdir)/engines-…` and `MODULESDIR=$(libdir)/ossl-modules`
  from `--prefix` + `--libdir`.
* The only lever is `--prefix`. Moving prefix out of the build tree
  requires `DESTDIR` (or a post-install rewrite), which changes
  `libcrypto.pc` / `libssl.pc` and therefore what the two
  `PKG_CONFIG_PATH=` entries and two `--with-openssl=` flags at
  `CMakeLists.txt:307/317/334/350` resolve to.

Recorded and left. This work does not change `ENGINESDIR` / `MODULESDIR`.

### D5.2 — README paragraph

Add one paragraph to `sol/release/README.md` § Verification
responsibility → **Authored and checked on the lode**, after the
existing curl sentence (`README.md:129-131`), still inside that
subsection, before `### Post-ship VPE native work`. Mirror that curl
wording. Verbatim:

```text
The vendored OpenSSL openssldir gate is unfalsified and must
not be cited as coverage until VPE has rebuilt with the openssldir
pointed back into the build tree and seen it go red.
```

It names “the openssldir” and does not restate the four fragments. It
does not go in “Post-ship VPE native work”.

### D5.3 — VPE-direct list

VPE-direct, not claimed by this lode:

1. Rebuild the vendored OpenSSL with `--openssldir` pointed back at
   `${OPENSSL_INSTALL_DIR}` (the pre-fix assignment) and confirm the
   new `FORBIDDEN_OPENSSLDIR_PATHS` gate goes red on staged `libnvat`
   with `build-tree openssldir path found`. Until that rebuild is red,
   the gate is unfalsified (D5.2).
2. Confirm the after-fix `strings` histogram on a real
   `linux-x86_64` release artifact (the lode records this during
   implement; VPE repeats it on the promoted archive).
3. On native `linux-aarch64` and native `macos-arm64`, confirm the
   same 4 prefix survivors, no
   `openssl-install/{certs,cert.pem,private,ct_log_list.cnf}` bytes,
   and that `/nvat-openssl` was not created on the builder.
4. Confirm a root container build after D2 does not create
   `/nvat-openssl` (the D2 sharp point).
5. Do not treat Darwin SIP / SSV citations as native mkdir proof;
   the macOS operator records that `/nvat-openssl` is absent after the
   native `_build`.

## Tests (`sol/release/tests/test_gate.py`)

No `unittest.skip` / `skipIf`. Fail closed. One test method per
concern, table-driven with `subTest`. Fixtures are
`fixtures.elf_fixture(strings=…)` and `fixtures.macho_fixture(strings=…)`.

1. **Positive needles.** One method. For each member of
   `FORBIDDEN_OPENSSLDIR_PATHS`, ELF (`TARGET_IDS[0]`) and Mach-O
   (`TARGET_IDS[2]`): `assertRaisesRegex(gate.GateError, "build-tree openssldir path found")`
   on a fixture whose `strings=` is that member. Iterate the production
   constant; do not copy the four literals into the test.
2. **Negative twin.** One method. A synthetic ELF and a synthetic
   Mach-O whose `strings=` is exactly prep Q3's verbatim literal
   `/home/jer/.hopper/worktrees/6patvfem/build/openssl-install/lib/ossl-modules`
   must **not** raise. That string is prefix-derived `MODULESDIR` and
   contains `openssl-install` but none of the four exclusive leaves.
   `gate_file` returns. Do not also plant the four needles in this
   fixture.

D4 is covered by `test_baked_host_ca_paths_fail_for_each_format`
(`test_gate.py:95`). No third method for `/etc/ssl/cert.pem`.

No test reads `CMakeLists.txt` configure-flag text.

## Before / after `strings`

**Before** (prep Q1, this hopper `-B build`, independently confirmed).
`LIB=build/nv-attestation-sdk-build/libnvat.so.1.2.2`:

```text
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

11 occurrences, 7 openssldir / 4 prefix.

**After** (implement, same hopper `-B build`, OpenSSL Makefile
`OPENSSLDIR=/nvat-openssl`, `configdata.pm` `"openssldir" => "/nvat-openssl"`).
Same command:

```text
      1 ENGINESDIR: "/home/jer/.hopper/worktrees/6patvfem/build/openssl-install/lib/engines-3"
      1 /home/jer/.hopper/worktrees/6patvfem/build/openssl-install/lib/engines-3
      1 /home/jer/.hopper/worktrees/6patvfem/build/openssl-install/lib/ossl-modules
      1 MODULESDIR: "/home/jer/.hopper/worktrees/6patvfem/build/openssl-install/lib/ossl-modules"
```

Exactly 4, all `--prefix`-derived (11→4). Zero matches for the four
`FORBIDDEN_OPENSSLDIR_PATHS` needles. The openssldir family is now
`/nvat-openssl/{certs,cert.pem,private,ct_log_list.cnf}`,
`OPENSSLDIR: "/nvat-openssl"`, and two bare `/nvat-openssl` (7
occurrences). `install_sw` left `lib/{libcrypto,libssl}.a`, 142
`include/openssl/` headers, and the three `.pc` files; `certs`,
`private`, `misc`, `openssl.cnf`, and `ct_log_list.cnf` are absent
under the prefix. `/nvat-openssl` was not created on the host.

## Non-goals

* Do not touch `nv_http.cpp`, `targets.toml`, `--prefix`,
  `CMakeLists.txt:307/317/334/350`, `curl.py`, `is_binary_member`, or
  the allowlist mechanism.
* Do not change `ENGINESDIR` / `MODULESDIR` (D5.1).
* Do not claim the defect fails loudly at runtime.
* Do not design a configurable or parameterized gate. One needle set,
  one check.
* Do not add `openssl-install/openssl.cnf` or `b'openssl-install"'` to
  the needle set.
* Do not assert over `CMakeLists.txt` configure-flag text.
* Do not introduce `DESTDIR`. Do not keep `install_ssldirs`.

## Implementation order

1. `CMakeLists.txt:236` `--openssldir=/nvat-openssl`; `:246`
   `make install_sw` only.
2. `gate.py`: append `b"/etc/ssl/cert.pem"` to `FORBIDDEN_CA_PATHS`;
   add `FORBIDDEN_OPENSSLDIR_PATHS` directly below it; second loop in
   `_forbidden_strings` with
   `{path}: build-tree openssldir path found: {value}`.
3. `test_gate.py`: positive-needle method and negative-twin method.
4. `README.md` D5.2 paragraph.
5. `sol/notes/openssl-enginesdir-modulesdir.md` (D5.1).
6. After-fix `strings` listing on the rebuilt library (implement
   record, not a product file).

## Risks

* A future rename of `openssl-install` silently drops D3 coverage
  (D3d). Accepted.
* Native Tumbleweed xmlsec/curl `lib64` vs `lib/` (prep prewarm) is
  unrelated and must not be "fixed" in this change.
* Darwin `libnvat.dylib` strings were not measured. Unix OPENSSLDIR
  macros are the same; VPE-direct item 3 is the native proof.
* After the fix, `/nvat-openssl/cert.pem` **will** appear in the
  library. That is D1 working. It is not a `FORBIDDEN_CA_PATHS` hit
  (`/etc/ssl/cert.pem` is a different 17 bytes).
