import shlex
import sys
import tempfile
import unittest
from pathlib import Path


RELEASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RELEASE_DIR))

from release_rail import curl  # noqa: E402


LIVE_CONFIGURE = (
    " '--prefix=/src/build/curl-install' "
    "'--with-openssl=/src/build/openssl-install' '--without-libssh2' "
    "'--without-nghttp2' '--without-brotli' '--without-zstd' "
    "'--without-libidn2' '--without-librtmp' '--without-libpsl' "
    "'--with-ca-fallback' '--without-ca-bundle' '--without-ca-path' "
    "'--disable-ldap' '--disable-shared' '--enable-static' "
    "'CC=/opt/rh/gcc-toolset-14/root/usr/bin/cc' 'CFLAGS= -fPIC' "
    "'PKG_CONFIG_PATH=/src/build/openssl-install/lib/pkgconfig'"
)


def emit_configure(tokens):
    return " " + " ".join(shlex.quote(token) for token in tokens)


class CurlConfigTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.build_dir = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def install(self):
        return self.build_dir / "curl-install"

    def script(self):
        return self.install() / "bin" / "curl-config"

    def write_script(self, body, mode=0o755):
        path = self.script()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
        path.chmod(mode)
        return path

    def write_curl_config(self, *, ca="", configure=LIVE_CONFIGURE, mode=0o755):
        ca_command = f"printf '%s\\n' {shlex.quote(ca)}"
        configure_command = f"printf '%s\\n' {shlex.quote(configure)}"
        return self.write_script(
            f'if [ "$1" = "--ca" ]; then {ca_command}; exit 0; fi\n'
            f'if [ "$1" = "--configure" ]; then {configure_command}; exit 0; fi\n'
            "exit 1",
            mode=mode,
        )

    def assert_check_fails(self, expected):
        with self.assertRaises(curl.CurlConfigError) as raised:
            curl.check(self.build_dir)
        self.assertEqual(str(raised.exception), expected)

    def test_green_configure_is_accepted(self):
        self.write_curl_config()
        self.assertIsNone(curl.check(self.build_dir))

    def test_unbuilt_tree_fails(self):
        install = self.install()
        self.assert_check_fails(
            "vendored curl configure evidence failed: "
            f"{install} is not a directory; remove build/release and rerun "
            "the release so the vendored curl ExternalProject installs "
            "curl-config, then retry"
        )

    def test_missing_binary_fails(self):
        self.install().mkdir()
        script = self.script()
        self.assert_check_fails(
            "vendored curl configure evidence failed: "
            f"{script} is absent; remove build/release and rerun the release "
            "so the vendored curl ExternalProject installs curl-config, then "
            "retry"
        )

    def test_non_executable_fails(self):
        script = self.write_curl_config(mode=0o644)
        self.assert_check_fails(
            "vendored curl configure evidence failed: "
            f"{script} is not executable; remove build/release and rerun the "
            "release so the installed curl-config is the ExternalProject "
            "install output, then retry"
        )

    def test_nonzero_exit_fails(self):
        script = self.write_script("echo 'curl-config boom' >&2\nexit 7")
        self.assert_check_fails(
            "vendored curl configure evidence failed: "
            f"{script} --ca failed: exit 7: curl-config boom; remove "
            "build/release and rerun the release, then retry"
        )

    def test_baked_ca_path_fails(self):
        script = self.write_curl_config(ca="baked.pem")
        self.assert_check_fails(
            "vendored curl configure evidence failed: "
            f"{script} --ca reported a baked CA path 'baked.pem'; configure "
            "the vendored curl without a baked host CA path, remove "
            "build/release, and retry"
        )

    def test_missing_required_configure_flag_fails(self):
        tokens = list(curl._configure_tokens(LIVE_CONFIGURE))
        script = self.script()
        for flag in curl.REQUIRED_CONFIGURE_FLAGS:
            remaining = [token for token in tokens if token != flag]
            if flag.startswith("--without-"):
                remaining.append(f"--with-{flag.removeprefix('--without-')}=/x")
            self.write_curl_config(configure=emit_configure(remaining))
            with self.subTest(flag=flag):
                self.assert_check_fails(
                    "vendored curl configure evidence failed: "
                    f"{script} --configure is missing {flag}; configure the "
                    f"vendored curl with {flag}, remove build/release, and "
                    "retry"
                )


if __name__ == "__main__":
    unittest.main()
