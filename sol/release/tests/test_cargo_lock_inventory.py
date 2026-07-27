import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


RELEASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RELEASE_DIR))

from release_rail import inventory  # noqa: E402


class CargoLockInventoryTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.git("init", "-q", "-b", "inventory")
        self.git("config", "user.name", "Inventory Test")
        self.git("config", "user.email", "inventory-test@example.invalid")

    def tearDown(self):
        self.temporary.cleanup()

    def git(self, *arguments):
        return subprocess.check_output(
            ["git", "-C", str(self.root), *arguments],
            text=True,
        ).strip()

    def write(self, path, content=""):
        destination = self.root / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")

    def test_tracked_lock_is_classified(self):
        path = "sol/tracked/Cargo.lock"
        self.write(path)
        self.git("add", path)
        self.git("commit", "-q", "-m", "add tracked lock")

        result = inventory.cargo_locks(self.root)

        self.assertEqual(result.tracked, (path,))
        self.assertEqual(result.untracked_non_ignored, ())
        self.assertEqual(result.ignored, ())

    def test_untracked_non_ignored_lock_is_classified(self):
        path = "sol/untracked/Cargo.lock"
        self.write(path)

        result = inventory.cargo_locks(self.root)

        self.assertEqual(result.tracked, ())
        self.assertEqual(result.untracked_non_ignored, (path,))
        self.assertEqual(result.ignored, ())

    def test_ignored_nested_repository_lock_is_classified(self):
        self.write(".gitignore", "build/\n")
        self.git("add", ".gitignore")
        self.git("commit", "-q", "-m", "ignore build")
        path = "build/_deps/example-src/Cargo.lock"
        nested_repository = (self.root / path).parent
        nested_repository.mkdir(parents=True)
        subprocess.check_output(
            ["git", "-C", str(nested_repository), "init", "-q", "-b", "fetched"],
            text=True,
        )
        self.write(path)

        # The embedded repository collapses to a directory record, so its lock
        # is reachable only through the ignored-directory walk.
        result = inventory.cargo_locks(self.root)

        self.assertEqual(result.tracked, ())
        self.assertEqual(result.untracked_non_ignored, ())
        self.assertEqual(result.ignored, (path,))


if __name__ == "__main__":
    unittest.main()
