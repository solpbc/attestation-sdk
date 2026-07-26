import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


RELEASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RELEASE_DIR))

from release_rail import authority, driver  # noqa: E402


class DriverPreflightTest(unittest.TestCase):
    def test_missing_target_fails_before_dist_exists(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(
                driver.ReleaseError,
                rf"release target is required.*make release TARGET={authority.TARGET_IDS[0]}",
            ):
                driver.release(root, None)
            self.assertFalse((root / "dist").exists())

    def test_dirty_source_tree_fails_before_dist_exists(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def git(_root, *arguments):
                if arguments[0] == "status":
                    return " M tracked-file"
                raise AssertionError(arguments)

            with mock.patch.object(driver, "_git", side_effect=git):
                with self.assertRaisesRegex(
                    driver.ReleaseError, "release requires a clean source tree"
                ):
                    driver.release(root, authority.TARGET_IDS[0])
            self.assertFalse((root / "dist").exists())

    def test_unavailable_and_hash_mismatched_ca_fail_closed(self):
        release = authority.load().release
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ca.pem"
            with mock.patch.object(
                driver, "_download", side_effect=driver.ReleaseError("unavailable")
            ):
                with self.assertRaisesRegex(driver.ReleaseError, "unavailable"):
                    driver._acquire_ca(release, path)

            payload = b"wrong"
            published = f"{hashlib.sha256(payload).hexdigest()}  ca.pem\n".encode()
            with mock.patch.object(driver, "_download", side_effect=(payload, published)):
                with self.assertRaisesRegex(
                    driver.ReleaseError, "pinned dependency hash mismatch"
                ):
                    driver._acquire_ca(release, path)

    def test_linux_build_exports_source_date_epoch(self):
        target = authority.load().target("linux-x86_64")
        root = Path("/source")
        with mock.patch.object(driver, "_git", return_value="/git/common"):
            with mock.patch.object(driver, "_run") as run:
                driver._build(root, target, root / "build/release", 1234567890)
        arguments = run.call_args.args[0]
        self.assertEqual(
            arguments[arguments.index("-e") + 1],
            "SOURCE_DATE_EPOCH=1234567890",
        )


if __name__ == "__main__":
    unittest.main()
