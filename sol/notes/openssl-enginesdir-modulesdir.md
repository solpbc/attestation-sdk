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
