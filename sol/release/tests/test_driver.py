import hashlib
import io
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock


RELEASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RELEASE_DIR))

import rail  # noqa: E402
from release_rail import archive, authority, driver, manifest  # noqa: E402


class SourceTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.git("init", "-q", "-b", "fork")
        self.git("config", "user.name", "Release Test")
        self.git("config", "user.email", "release-test@example.invalid")
        self.base = self.commit("upstream base")
        self.expected = [
            (self.commit("sol one"), "sol one"),
            (self.commit("sol two"), "sol two"),
            (self.commit("sol three"), "sol three"),
        ]
        self.tip = self.expected[-1][0]
        self.release = dict(authority.load().release)
        self.release["upstream_base_commit"] = self.base

    def tearDown(self):
        self.temporary.cleanup()

    def git(self, *arguments, input_text=None):
        return subprocess.check_output(
            ["git", "-C", str(self.root), *arguments],
            input=input_text,
            text=True,
        ).strip()

    def commit(self, subject):
        path = self.root / f"tracked-{subject.replace(' ', '-')}"
        path.write_text(f"{subject}\n", encoding="utf-8")
        self.git("add", path.name)
        self.git("commit", "-q", "-m", subject)
        return self.git("rev-parse", "HEAD")

    def assert_valid_source(self):
        value = driver._source(self.root, self.release)
        self.assertEqual(value["commit"], self.tip)
        self.assertEqual(value["upstream_base_commit"], self.base)
        self.assertEqual(
            value["sol_series_commits"],
            [
                {"commit": revision, "subject": subject}
                for revision, subject in self.expected
            ],
        )

    def test_main_absent_stale_or_at_fork_tip_does_not_affect_series(self):
        self.assert_valid_source()
        self.git("branch", "main", self.base)
        self.assert_valid_source()
        self.git("branch", "-f", "main", self.tip)
        self.assert_valid_source()

    def test_missing_and_noncommit_base_fail_closed(self):
        missing = "0" * 40
        blob = self.git("hash-object", "-w", "--stdin", input_text="not a commit")
        for value in (missing, blob):
            with self.subTest(base=value):
                release = dict(self.release, upstream_base_commit=value)
                with self.assertRaisesRegex(
                    driver.SourceError,
                    "pinned upstream base is missing or is not a commit.*"
                    "fetch the repository history containing that commit",
                ):
                    driver._source(self.root, release)

    def test_nonancestor_base_fails_closed(self):
        tree = self.git("rev-parse", f"{self.base}^{{tree}}")
        unrelated = self.git(
            "commit-tree", tree, "-p", self.base, input_text="unrelated\n"
        )
        release = dict(self.release, upstream_base_commit=unrelated)
        with self.assertRaisesRegex(
            driver.SourceError,
            "pinned upstream base is not an ancestor of source.commit.*"
            "check out the intended sol release history",
        ):
            driver._source(self.root, release)

    def test_empty_series_fails_closed(self):
        release = dict(self.release, upstream_base_commit=self.tip)
        with self.assertRaisesRegex(
            driver.SourceError,
            "source series is empty.*check out the sol release commits",
        ):
            driver._source(self.root, release)

    def test_merge_in_range_fails_closed(self):
        self.git("switch", "-q", "-c", "side", self.base)
        self.commit("side change")
        self.git("switch", "-q", "fork")
        self.git("merge", "-q", "--no-ff", "side", "-m", "merge side")
        with self.assertRaisesRegex(
            driver.SourceError,
            "source series contains merge commit.*rebase the sol series",
        ):
            driver._source(self.root, self.release)

    def test_wrong_terminus_fails_closed(self):
        real_git = driver._git

        def git(root, *arguments):
            value = real_git(root, *arguments)
            if arguments[:3] == ("log", "--reverse", "--format=%H%x09%s"):
                lines = value.splitlines()
                lines[-1] = f"{self.base}\t{lines[-1].split(chr(9), 1)[1]}"
                return "\n".join(lines)
            return value

        with mock.patch.object(driver, "_git", side_effect=git):
            with self.assertRaisesRegex(
                driver.SourceError,
                "source series does not end at source.commit.*restore the complete",
            ):
                driver._source(self.root, self.release)

    def test_first_parent_must_be_pinned_base(self):
        first = self.expected[0][0]
        real_git = driver._git

        def git(root, *arguments):
            if arguments == ("rev-parse", f"{first}^"):
                return self.tip
            return real_git(root, *arguments)

        with mock.patch.object(driver, "_git", side_effect=git):
            with self.assertRaisesRegex(
                driver.SourceError,
                "source series does not begin immediately after the pinned upstream "
                "base.*fetch or restore the complete base-exclusive series",
            ):
                driver._source(self.root, self.release)


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
        target = authority.load().target(authority.TARGET_IDS[0])
        root = Path("/source")
        with mock.patch.object(driver, "_git", return_value="/git/common"):
            with mock.patch.object(driver, "_run") as run:
                driver._build(root, target, root / "build/release", 1234567890)
        arguments = run.call_args.args[0]
        self.assertEqual(
            arguments[arguments.index("-e") + 1],
            "SOURCE_DATE_EPOCH=1234567890",
        )

    def test_archive_and_manifest_errors_use_normal_cli_error_form(self):
        errors = (
            archive.ArchiveError("tar broke"),
            manifest.ManifestError("tool broke"),
            driver.SourceError("source broke"),
        )
        for error in errors:
            with self.subTest(error=type(error).__name__):
                output = io.StringIO()
                with mock.patch.object(
                    sys, "argv", ["rail.py", "release", authority.TARGET_IDS[0]]
                ):
                    with mock.patch.object(rail.driver, "release", side_effect=error):
                        with redirect_stderr(output):
                            self.assertEqual(rail.main(), 2)
                self.assertEqual(
                    output.getvalue(),
                    f"release rail error: {error}\n",
                )


if __name__ == "__main__":
    unittest.main()
