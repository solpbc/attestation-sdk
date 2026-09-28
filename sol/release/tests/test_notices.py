import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


RELEASE_DIR = Path(__file__).resolve().parents[1]
ROOT = RELEASE_DIR.parents[1]
SPEC = importlib.util.spec_from_file_location(
    "generate_dependencies", RELEASE_DIR / "generate-dependencies.py"
)
generator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(generator)


class NoticesTest(unittest.TestCase):
    def test_release_notices_include_every_pinned_crate_and_native_licence(self):
        dependencies = generator.parse(ROOT)
        lock = RELEASE_DIR / "regorus-Cargo.lock"
        inventory = json.loads((RELEASE_DIR / "notices/regorus-sources.json").read_text())
        # Union of cargo tree --locked --offline --edges normal,build for the
        # three release triples with regorus/semver, generated 2026-09-28.
        self.assertEqual(len(inventory["packages"]), 162)
        for rustc in ("1.88.0", "1.97.1"):
            notice = generator.notices(dependencies, lock, rustc)
            for package in inventory["packages"]:
                self.assertIn(
                    f"### {package['name']} {package['version']}\n", notice
                )
            for name in generator.CPP_NOTICE_FILES:
                self.assertIn(f"## {name}\n", notice)
            self.assertIn(f"## Rust standard library {rustc}\n", notice)
            self.assertIn("### COPYRIGHT-library.html\n", notice)
            self.assertIn("### libxml2-hash.c-notice.txt\n", notice)
            self.assertGreater(len(notice), 1_000_000)

    def test_changed_built_lock_fails_before_notice_generation(self):
        dependencies = generator.parse(ROOT)
        with tempfile.TemporaryDirectory() as directory:
            lock = Path(directory) / "Cargo.lock"
            lock.write_bytes((RELEASE_DIR / "regorus-Cargo.lock").read_bytes() + b"\n")
            with self.assertRaisesRegex(ValueError, "differs from the release pin"):
                generator.notices(dependencies, lock, "1.88.0")


if __name__ == "__main__":
    unittest.main()
