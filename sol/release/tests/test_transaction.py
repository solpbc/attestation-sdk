import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


RELEASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RELEASE_DIR))

from release_rail import authority, transaction  # noqa: E402


class InjectedFailure(RuntimeError):
    pass


class TransactionTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.dist = self.root / "dist"
        self.dist.mkdir()
        self.sentinel = self.dist / "keep-me"
        self.sentinel.write_text("untouched", encoding="utf-8")
        self.names = {
            "archive": "artifact.tar.xz",
            "archive-sha256": "artifact.tar.xz.sha256",
            "manifest": "artifact.manifest.json",
            "manifest-sha256": "artifact.manifest.json.sha256",
        }
        self.construction = (
            *transaction.CONSTRUCTION_CHECKPOINTS,
            "after-runtime-gate:fedora",
            "after-runtime-gate:tumbleweed",
        )

    def tearDown(self):
        self.temporary.cleanup()

    def builder(self, owned, checkpoint):
        for name in self.construction:
            checkpoint(name)
        outputs = {}
        for key, basename in self.names.items():
            path = owned / basename
            path.write_text(key, encoding="utf-8")
            outputs[key] = path
        return outputs

    def assert_no_quartet(self):
        self.assertTrue(self.sentinel.is_file())
        self.assertEqual(self.sentinel.read_text(encoding="utf-8"), "untouched")
        for basename in self.names.values():
            self.assertFalse((self.dist / basename).exists())

    def test_every_construction_and_promotion_checkpoint_rolls_back(self):
        checkpoints = (
            "before-construction",
            *self.construction,
            "before-promotion",
            *(f"after-promotion:{key}" for key in transaction.QUARTET_ORDER),
        )
        for injected in checkpoints:
            with self.subTest(checkpoint=injected):
                def fault(name):
                    if name == injected:
                        raise InjectedFailure(name)

                with self.assertRaises(InjectedFailure):
                    transaction.run(
                        dist=self.dist,
                        target_id=authority.TARGET_IDS[0],
                        version="1.2.2-sol.2",
                        destination_names=self.names,
                        builder=self.builder,
                        fault_hook=fault,
                    )
                self.assert_no_quartet()

    def test_clean_rerun_replaces_only_owned_staging(self):
        owned = self.dist / f".staging/{authority.TARGET_IDS[0]}-1.2.2-sol.2"
        owned.mkdir(parents=True)
        (owned / "stale").write_text("old", encoding="utf-8")
        other = self.dist / ".staging/other"
        other.mkdir()
        (other / "keep").write_text("other", encoding="utf-8")
        result = transaction.run(
            dist=self.dist,
            target_id=authority.TARGET_IDS[0],
            version="1.2.2-sol.2",
            destination_names=self.names,
            builder=self.builder,
        )
        self.assertEqual(set(result), set(transaction.QUARTET_ORDER))
        self.assertFalse((owned / "stale").exists())
        self.assertEqual((other / "keep").read_text(encoding="utf-8"), "other")
        self.assertEqual(self.sentinel.read_text(encoding="utf-8"), "untouched")

    def test_existing_complete_quartet_is_never_overwritten(self):
        for basename in self.names.values():
            (self.dist / basename).write_text("previous", encoding="utf-8")
        with self.assertRaisesRegex(
            transaction.TransactionError,
            "promotion refuses to overwrite: .*move the existing quartet aside with "
            "`retained=\\$\\(mktemp -d .*\\.XXXXXX\\) && mv .*`, then retry",
        ):
            transaction.run(
                dist=self.dist,
                target_id=authority.TARGET_IDS[0],
                version="1.2.2-sol.2",
                destination_names=self.names,
                builder=self.builder,
            )
        for basename in self.names.values():
            self.assertEqual((self.dist / basename).read_text(), "previous")
        self.assertFalse((self.dist / ".staging").exists())

    def test_concurrent_destination_creation_does_not_clobber(self):
        real_link = transaction.os.link

        def race(source, destination):
            if destination.name == self.names["manifest"]:
                destination.write_text("concurrent", encoding="utf-8")
                raise FileExistsError(17, "exists", source, destination)
            real_link(source, destination)

        with mock.patch.object(transaction.os, "link", side_effect=race):
            with self.assertRaisesRegex(
                transaction.TransactionError,
                "promotion destination appeared concurrently",
            ):
                transaction.run(
                    dist=self.dist,
                    target_id=authority.TARGET_IDS[0],
                    version="1.2.2-sol.2",
                    destination_names=self.names,
                    builder=self.builder,
                )
        self.assertEqual(
            (self.dist / self.names["manifest"]).read_text(encoding="utf-8"),
            "concurrent",
        )
        for key, basename in self.names.items():
            if key != "manifest":
                self.assertFalse((self.dist / basename).exists())


if __name__ == "__main__":
    unittest.main()
