# OpenSSL ENGINESDIR / MODULESDIR (2026-08-20)

Non-goal recorded during the vendored `--openssldir` default work
(vpe-345). It outlives that lode. The four `--prefix`-derived
build-path strings that survive pointing `--openssldir` at
`/nvat-openssl` are left as they are.

## What survives, by design

A pre-fix `libnvat.so` contained 11 occurrences of
`<builddir>/openssl-install`. Seven were OPENSSLDIR (certs, cert.pem,
private, ct_log_list.cnf, the OPENSSLDIR banner, two bare OPENSSLDIR
copies). Four were `--prefix`-derived and remain after the openssldir
change:

* `ENGINESDIR: "<prefix>/openssl-install/lib/engines-3"`
* `<prefix>/openssl-install/lib/engines-3`
* `MODULESDIR: "<prefix>/openssl-install/lib/ossl-modules"`
* `<prefix>/openssl-install/lib/ossl-modules`

`MODULESDIR` is a `dlopen` root (`ossl_get_modulesdir` /
`$(libdir)/ossl-modules`) and is the higher-severity instance.
`ENGINESDIR` is still compiled in with `no-engine`
(`nv-attestation-sdk-cpp/CMakeLists.txt:243`).

## No Configure lever

OpenSSL 3.6.1 has no `--enginesdir` or `--modulesdir` flag.

Vendored `Configure` (openssl-3.6.1 tarball, option parser
approximately lines 1042–1164) accepts `--api`, `--libdir`,
`--openssldir`, `--with-*`, `--fips-key`, `--banner`,
`--cross-compile-prefix`, `--config`, and `--help`. A search of that
file for `--enginesdir` and `--modulesdir` is empty.

`Configurations/unix-Makefile.tmpl:336-337` hard-wires both from
`--prefix` + `--libdir`:

```make
ENGINESDIR=$(libdir)/engines-{- $sover_dirname -}
MODULESDIR=$(libdir)/ossl-modules
```

The only lever is `--prefix`. Moving prefix out of the build tree
requires `DESTDIR` (or a post-install rewrite), which changes
`libcrypto.pc` / `libssl.pc` and therefore what the two
`PKG_CONFIG_PATH=` entries and two `--with-openssl=` flags at
`CMakeLists.txt:307`, `:317`, `:334`, and `:350` resolve to.

Recorded and left.

## Same class: the Linux executable's RUNPATH

The released Linux `bin/nvattest` (1.2.2-sol.2 and 1.2.2-sol.3, x86_64
and aarch64) carries `DT_RUNPATH`
`/src/build/release/nv-attestation-sdk-build:`. The build-tree entry is
the same leak as the paths above. The trailing empty entry is worse:
glibc resolves it against the working directory, so `libstdc++.so.6`,
`libm.so.6` and the rest of the executable's `DT_NEEDED` are looked for
in whatever directory the caller runs from, before the system cache.
The macOS executable is clean (`@executable_path/../lib` only).

The consumer that installs this archive now always starts the process
from `/`, which closes the working-directory entry for every revision.
The artifact itself still carries both entries. Fix them in the next
release revision alongside `ENGINESDIR`/`MODULESDIR`: set the
executable's RUNPATH to `$ORIGIN/../lib` and confirm with
`readelf -d bin/nvattest` on both Linux targets.
