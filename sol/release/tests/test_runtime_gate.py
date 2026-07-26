import subprocess
import tempfile
import unittest
from pathlib import Path


RELEASE_DIR = Path(__file__).resolve().parents[1]


class RuntimeGateTest(unittest.TestCase):
    def test_hidden_directory_entry_counts_as_an_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".unexpected").write_text("hidden", encoding="utf-8")
            layout = root / "layout.tsv"
            layout.write_text("", encoding="utf-8")
            counts = root / "counts.tsv"
            counts.write_text(".\t0\n", encoding="utf-8")
            result = subprocess.run(
                [
                    str(RELEASE_DIR / "runtime-gate.sh"),
                    str(root),
                    "unused-archive",
                    "unused-archive-sidecar",
                    "unused-manifest",
                    "unused-manifest-sidecar",
                    str(layout),
                    str(counts),
                    "linux",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
