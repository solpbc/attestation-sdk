import ast
import re
import subprocess
import sys
import unittest
from collections import Counter
from pathlib import Path


RELEASE_DIR = Path(__file__).resolve().parents[1]
ROOT = RELEASE_DIR.parents[1]
sys.path.insert(0, str(RELEASE_DIR))

from release_rail import authority, set_validator  # noqa: E402


BASELINE = "31ff1fbe824dd2856ee217d2398176ef293f847b"
TARGETS = Path("sol/release/targets.toml")
AUTHORITY = Path("sol/release/release_rail/authority.py")
SDK_CMAKE = Path("nv-attestation-sdk-cpp/CMakeLists.txt")
CLI_CMAKE = Path("nv-attestation-cli/CMakeLists.txt")
PIN = re.compile(
    r"(?:^|[\s(])(GIT_REPOSITORY|GIT_TAG|URL_HASH|URL)[ \t]+([^\s)]+)",
    re.MULTILINE,
)
PROJECT = re.compile(
    r"^project\(([^\s)]+)\s+VERSION\s+([^\s)]+)\)$", re.MULTILINE
)
TARGET_IDS = re.compile(r"^TARGET_IDS\s*=\s*(\([^\n]*\))$", re.MULTILINE)


class BaselineStabilityTest(unittest.TestCase):
    def baseline(self, path):
        return subprocess.run(
            ["git", "show", f"{BASELINE}:{path.as_posix()}"],
            cwd=ROOT,
            check=True,
            capture_output=True,
        ).stdout

    def source(self, path):
        return (ROOT / path).read_bytes()

    def test_targets_authority_is_byte_identical(self):
        self.assertEqual(self.source(TARGETS), self.baseline(TARGETS))

    def test_target_ids_are_unchanged(self):
        values = []
        for source in (self.baseline(AUTHORITY), self.source(AUTHORITY)):
            match = TARGET_IDS.search(source.decode())
            self.assertIsNotNone(match)
            values.append(ast.literal_eval(match.group(1)))
        self.assertEqual(values[0], values[1])

    def cmake_values(self, source):
        text = re.sub(r"#[^\n]*", "", source.decode())
        pins = PIN.findall(text)
        projects = PROJECT.findall(text)
        self.assertEqual(len(projects), 1)
        return pins, projects[0]

    def test_cmake_versions_and_dependency_coordinates_are_unchanged(self):
        for path in (SDK_CMAKE, CLI_CMAKE):
            with self.subTest(path=path):
                baseline_pins, baseline_project = self.cmake_values(
                    self.baseline(path)
                )
                current_pins, current_project = self.cmake_values(self.source(path))
                self.assertEqual(current_pins, baseline_pins)
                self.assertEqual(Counter(field for field, _ in current_pins),
                                 Counter(field for field, _ in baseline_pins))
                self.assertEqual(current_project, baseline_project)

    def test_release_version_matches_baseline_sdk_version(self):
        _, (_, version) = self.cmake_values(self.baseline(SDK_CMAKE))
        expected = f"{version}-sol.{authority.load().release['sol_revision']}"
        self.assertEqual(
            set_validator.release_version(ROOT, authority.load()), expected
        )


if __name__ == "__main__":
    unittest.main()
