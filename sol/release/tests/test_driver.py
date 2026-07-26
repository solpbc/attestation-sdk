import contextlib
import hashlib
import io
import os
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
from release_rail import apple, archive, authority, driver, manifest, runtime  # noqa: E402
from support import tools_for  # noqa: E402


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
        selection = runtime.Selection(
            runtime.RUNTIME_NAMES[1], tools_for(target)[runtime.EVIDENCE_KEY]
        )
        with mock.patch.object(driver, "_git", return_value="/git/common"):
            with mock.patch.object(driver, "_run") as run:
                driver._build(
                    root,
                    target,
                    root / "build/release",
                    1234567890,
                    selection,
                )
        arguments = run.call_args.args[0]
        self.assertEqual(arguments[0], selection.name)
        self.assertIn(runtime.LOCAL_IMAGE_TAG, arguments)
        self.assertIn(runtime.render_mount(root, "/src", False), arguments)
        self.assertIn(
            runtime.render_mount("/git/common", "/git/common", True), arguments
        )
        self.assertEqual(
            arguments[arguments.index("-e") + 1],
            "SOURCE_DATE_EPOCH=1234567890",
        )

    def test_archive_and_manifest_errors_use_normal_cli_error_form(self):
        errors = (
            archive.ArchiveError("tar broke"),
            apple.AppleToolchainError("Apple tools broke"),
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


class DriverRuntimeTest(unittest.TestCase):
    def setUp(self):
        self.data = authority.load()
        self.target = self.data.target(authority.TARGET_IDS[0])
        self.selection = runtime.Selection(
            runtime.RUNTIME_NAMES[1],
            tools_for(self.target)[runtime.EVIDENCE_KEY],
        )

    def test_release_threads_one_selection_through_every_container_command(self):
        distinctive = runtime.Selection(
            "selected-runtime",
            tools_for(self.target)[runtime.EVIDENCE_KEY],
        )
        container_commands = []

        def run(arguments, *, cwd, **_kwargs):
            if len(arguments) > 1 and arguments[1] == "run":
                container_commands.append(arguments)
                if "/ownership" in " ".join(map(str, arguments)):
                    (cwd / "probe").write_text("", encoding="utf-8")
            if "sol/release/generate-dependencies.py" in arguments:
                Path(arguments[arguments.index("--json") + 1]).write_text(
                    "[]", encoding="utf-8"
                )
            return mock.Mock(returncode=0, stdout="")

        def tool_run(arguments, **_kwargs):
            container_commands.append(arguments)
            return mock.Mock(returncode=0, stdout=f"{arguments[-2]} 1.2.3\n")

        def capture(
            target,
            _build_dir,
            invoker=None,
            *,
            runtime_evidence=None,
            apple_evidence=None,
        ):
            for key, command in zip(
                ("compiler", "cmake", "rustc", "cargo"),
                target["required_tools"],
            ):
                invoker(key, command)
            self.assertEqual(runtime_evidence, distinctive.evidence)
            self.assertIsNone(apple_evidence)
            return tools_for(target)

        def construct(_stage, destination, *_arguments):
            destination.write_bytes(b"archive")

        def transaction_run(*, builder, **_kwargs):
            with tempfile.TemporaryDirectory() as directory:
                owned = Path(directory)
                return builder(owned, mock.Mock())

        source = {
            "commit": "1" * 40,
            "upstream_base_commit": self.data.release["upstream_base_commit"],
            "sol_series_commits": [{"commit": "1" * 40, "subject": "test"}],
            "source_date_epoch": 1_700_000_000,
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with contextlib.ExitStack() as patches:
                patches.enter_context(
                    mock.patch.object(
                        driver,
                        "_git",
                        side_effect=lambda _root, *args: (
                            "" if args[0] == "status" else "/git/common"
                        ),
                    )
                )
                select = patches.enter_context(
                    mock.patch.object(runtime, "select", return_value=distinctive)
                )
                patches.enter_context(mock.patch.object(driver, "_run", side_effect=run))
                patches.enter_context(
                    mock.patch.object(
                        driver.subprocess, "run", side_effect=tool_run
                    )
                )
                patches.enter_context(
                    mock.patch.object(
                        manifest, "capture_build_tools", side_effect=capture
                    )
                )
                patches.enter_context(
                    mock.patch.object(
                        driver, "_version", return_value="1.2.2-sol.2"
                    )
                )
                patches.enter_context(
                    mock.patch.object(driver, "_source", return_value=source)
                )
                patches.enter_context(mock.patch.object(driver, "_acquire_ca"))
                patches.enter_context(mock.patch.object(driver, "_stage"))
                patches.enter_context(mock.patch.object(driver, "_validate_layout"))
                patches.enter_context(mock.patch.object(driver, "_gate_binaries"))
                patches.enter_context(
                    mock.patch.object(
                        archive, "construct", side_effect=construct
                    )
                )
                patches.enter_context(mock.patch.object(archive, "write_sidecar"))
                patches.enter_context(
                    mock.patch.object(manifest, "build", return_value={})
                )
                patches.enter_context(mock.patch.object(manifest, "write"))
                patches.enter_context(
                    mock.patch.object(
                        driver.transaction, "run", side_effect=transaction_run
                    )
                )
                driver.release(root, self.target["id"])

        select.assert_called_once_with(self.target)
        self.assertEqual(len(container_commands), 12)
        for arguments in container_commands:
            self.assertEqual(arguments[0], distinctive.name)
            self.assertIn(
                f"--platform={self.target['container_platform']}", arguments
            )
        local_image_commands = [
            arguments
            for arguments in container_commands
            if runtime.LOCAL_IMAGE_TAG in arguments
        ]
        self.assertEqual(len(local_image_commands), 9)
        for image in self.target["gate_images"]:
            self.assertTrue(
                any(image in arguments for arguments in container_commands)
            )

    def test_tool_invoker_uses_selected_runtime_mount_platform_and_bare_tag(self):
        result = mock.Mock(returncode=0, stdout="cmake version 1.2.3\n")
        with mock.patch.object(driver.subprocess, "run", return_value=result) as run:
            output = driver._tool_invoker(
                Path("/source"), self.target, self.selection
            )("cmake", "cmake")
        self.assertEqual(output, result.stdout)
        arguments = run.call_args.args[0]
        self.assertEqual(arguments[0], self.selection.name)
        self.assertIn(
            f"--platform={self.target['container_platform']}", arguments
        )
        self.assertIn(runtime.LOCAL_IMAGE_TAG, arguments)
        self.assertIn(
            runtime.render_mount("/source", "/src", True), arguments
        )

    def test_linux_runtime_gates_keep_full_argument_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            owned = root / "owned"
            extracted = root / "extracted"
            owned.mkdir()
            extracted.mkdir()
            quartet = {
                key: owned / name
                for key, name in {
                    "archive": "artifact.tar.xz",
                    "archive-sha256": "artifact.tar.xz.sha256",
                    "manifest": "artifact.manifest.json",
                    "manifest-sha256": "artifact.manifest.json.sha256",
                }.items()
            }
            with mock.patch.object(driver, "_run") as run:
                driver._runtime_gates(
                    root,
                    owned,
                    extracted,
                    quartet,
                    self.target,
                    mock.Mock(),
                    self.selection,
                )
        self.assertEqual(run.call_count, 2)
        for call, image in zip(
            run.call_args_list, self.target["gate_images"], strict=True
        ):
            arguments = call.args[0]
            self.assertEqual(arguments[0], self.selection.name)
            self.assertIn(
                f"--platform={self.target['container_platform']}", arguments
            )
            self.assertIn(image, arguments)
            for mount in (
                runtime.render_mount(extracted, "/artifact", True),
                runtime.render_mount(owned, "/release", True),
                runtime.render_mount(
                    root / "sol/release/runtime-gate.sh",
                    "/gate/runtime-gate.sh",
                    True,
                ),
                runtime.render_mount(owned / "layout.tsv", "/gate/layout.tsv", True),
                runtime.render_mount(owned / "counts.tsv", "/gate/counts.tsv", True),
            ):
                self.assertIn(mount, arguments)
            script_index = arguments.index("/gate/runtime-gate.sh")
            self.assertEqual(
                arguments[script_index + 1 :],
                [
                    "/artifact",
                    "/release/artifact.tar.xz",
                    "/release/artifact.tar.xz.sha256",
                    "/release/artifact.manifest.json",
                    "/release/artifact.manifest.json.sha256",
                    "/gate/layout.tsv",
                    "/gate/counts.tsv",
                    "linux",
                ],
            )

    def test_ownership_probe_accepts_mapping_rejects_uid_and_type_and_cleans(self):
        actual_uid = os.getuid()
        for state, message in (
            ("matching", None),
            ("uid", "created the host probe as uid"),
            ("missing", "probe file is absent"),
            ("symlink", "probe path is a symlink"),
            ("type", "probe path is not a regular file"),
        ):
            with self.subTest(state=state):
                captured = {}

                def run(arguments, *, cwd, **_kwargs):
                    captured["directory"] = cwd
                    captured["arguments"] = arguments
                    probe = cwd / "probe"
                    if state == "missing":
                        pass
                    elif state == "symlink":
                        probe.symlink_to("missing")
                    elif state == "type":
                        probe.mkdir()
                    else:
                        probe.write_text("", encoding="utf-8")

                getuid = (
                    (lambda: actual_uid)
                    if state != "uid"
                    else (lambda: actual_uid + 1)
                )
                with mock.patch.object(driver, "_run", side_effect=run):
                    with mock.patch.object(driver.os, "getuid", side_effect=getuid):
                        if state == "matching":
                            driver._ownership_probe(self.selection, self.target)
                        else:
                            with self.assertRaisesRegex(
                                runtime.RuntimeSelectionError,
                                message,
                            ):
                                driver._ownership_probe(self.selection, self.target)
                self.assertFalse(captured["directory"].exists())
                self.assertEqual(captured["arguments"][0], self.selection.name)
                self.assertIn(self.target["gate_images"][0], captured["arguments"])
                self.assertIn(
                    runtime.render_mount(
                        captured["directory"], "/ownership", False
                    ),
                    captured["arguments"],
                )

    def test_ownership_failure_precedes_dist_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with mock.patch.object(driver, "_git", return_value=""):
                with mock.patch.object(runtime, "select", return_value=self.selection):
                    with mock.patch.object(
                        driver,
                        "_ownership_probe",
                        side_effect=runtime.RuntimeSelectionError("unsafe mapping"),
                    ):
                        with self.assertRaisesRegex(
                            runtime.RuntimeSelectionError, "unsafe mapping"
                        ):
                            driver.release(root, self.target["id"])
            self.assertFalse((root / "dist").exists())

    def test_macos_paths_remain_native(self):
        target = self.data.target(authority.TARGET_IDS[2])
        root = Path("/source")
        build = root / "build/release"
        with mock.patch.object(driver, "_run") as run:
            driver._build(root, target, build, 123, None)
        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args_list[0].args[0][0], "cmake")
        self.assertIn(
            f"-DCMAKE_OSX_DEPLOYMENT_TARGET={target['abi_floor']['macos']}",
            run.call_args_list[0].args[0],
        )
        self.assertEqual(driver._tool_invoker(root, target, None), None)

        with tempfile.TemporaryDirectory() as directory:
            native_root = Path(directory)
            owned = native_root / "owned"
            extracted = native_root / "extracted"
            owned.mkdir()
            extracted.mkdir()
            quartet = {
                "archive": owned / "a.tar.xz",
                "archive-sha256": owned / "a.tar.xz.sha256",
                "manifest": owned / "a.manifest.json",
                "manifest-sha256": owned / "a.manifest.json.sha256",
            }
            with mock.patch.object(driver, "_run") as native_run:
                driver._runtime_gates(
                    native_root,
                    owned,
                    extracted,
                    quartet,
                    target,
                    mock.Mock(),
                    None,
                )
            arguments = native_run.call_args.args[0]
            self.assertEqual(arguments[0], str(native_root / "sol/release/runtime-gate.sh"))
            self.assertEqual(len(arguments[1:]), 8)
            self.assertEqual(arguments[-1], "macos")

    def test_macos_preflight_captures_apple_evidence_before_dist(self):
        target = self.data.target(authority.TARGET_IDS[2])
        evidence = tools_for(target)[apple.EVIDENCE_KEY]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with mock.patch.object(
                authority.Authority, "compatible_target", return_value=target["id"]
            ):
                with mock.patch.object(
                    authority.Authority, "require_compatible", return_value=target
                ):
                    with mock.patch.object(authority, "load", return_value=self.data):
                        with mock.patch.object(driver, "_git", return_value=""):
                            with mock.patch.object(
                                apple, "preflight", return_value=evidence
                            ) as preflight:
                                with mock.patch.object(
                                    manifest, "capture_build_tools"
                                ) as capture:
                                    driver._preflight(root, target["id"])
            self.assertFalse((root / "dist").exists())
        preflight.assert_called_once_with(target)
        self.assertEqual(capture.call_args.kwargs["apple_evidence"], evidence)
        self.assertIsNone(capture.call_args.kwargs["runtime_evidence"])


if __name__ == "__main__":
    unittest.main()
