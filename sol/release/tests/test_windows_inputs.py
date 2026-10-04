import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
INPUTS = ROOT / "sol/windows/inputs.json"
SDK_CMAKE = ROOT / "nv-attestation-sdk-cpp/CMakeLists.txt"
TARGETS = ROOT / "sol/release/targets.toml"
BLOCK = re.compile(r"ExternalProject_Add\((\w+)(.*?)\n\s*\)", re.DOTALL)
URL = re.compile(r"^\s*URL\s+(\S+)\s*$", re.MULTILINE)
URL_HASH = re.compile(r"^\s*URL_HASH\s+SHA256=([0-9a-f]{64})\s*$", re.MULTILINE)


def external_sources(text):
    sources = []
    for name, body in BLOCK.findall(text):
        url = URL.search(body)
        digest = URL_HASH.search(body)
        if url and digest:
            sources.append((name, url.group(1), digest.group(1)))
    return sources


class WindowsInputsTest(unittest.TestCase):
    """The Windows build compiles the same pinned sources as the POSIX build."""

    def setUp(self):
        self.inputs = json.loads(INPUTS.read_text())
        self.sources = {item["url"]: item for item in self.inputs["sources"]}

    def test_every_posix_external_source_is_pinned_identically(self):
        declared = external_sources(SDK_CMAKE.read_text())
        self.assertEqual(
            {name for name, _, _ in declared},
            {"openssl_external", "libxml2_external", "xmlsec_external", "curl_external"},
        )
        for name, url, sha256 in declared:
            with self.subTest(name=name):
                self.assertIn(url, self.sources)
                self.assertEqual(self.sources[url]["sha256"], sha256)

    def test_windows_only_sources_are_pinned(self):
        posix_urls = {url for _, url, _ in external_sources(SDK_CMAKE.read_text())}
        extra = [item for url, item in self.sources.items() if url not in posix_urls]
        self.assertEqual([item["dir"] for item in extra], ["zlib-1.3.1"])
        for item in self.inputs["sources"] + self.inputs["build_tools"]:
            with self.subTest(name=item["name"]):
                self.assertRegex(item["sha256"], r"^[0-9a-f]{64}$")
                self.assertTrue(item["url"].startswith("https://"))
                self.assertEqual(item["url"].rsplit("/", 1)[1], item["name"])

    def test_build_script_reads_the_ca_bundle_pin_from_the_release_authority(self):
        targets = TARGETS.read_text()
        self.assertRegex(targets, r'(?m)^ca_bundle_url\s*=\s*"https://')
        self.assertRegex(targets, r'(?m)^ca_bundle_sha256\s*=\s*"[0-9a-f]{64}"')


if __name__ == "__main__":
    unittest.main()
