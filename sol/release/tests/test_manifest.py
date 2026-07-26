import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


RELEASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RELEASE_DIR))

from release_rail import apple, authority, manifest, runtime  # noqa: E402
from support import tools_for  # noqa: E402


class ManifestTest(unittest.TestCase):
    def test_tool_evidence_has_exact_keys_and_normalized_versions(self):
        data = authority.load()
        shared = (
            "cmake version 3.31.4\n",
            "rustc 1.84.0 (abc 2025-01-01)\n",
            "cargo 1.84.0 (def 2025-01-01)\n",
            "tar (GNU tar) 1.35\n",
            "xz (XZ Utils) 5.6.3\n",
            "Python 3.13.1\n",
        )
        cases = (
            (
                authority.TARGET_IDS[0],
                "gcc (SUSE Linux) 14.2.1 20260101 /host/path\n",
            ),
            (
                authority.TARGET_IDS[2],
                "Apple clang version 16.0.0 /host/path\n",
            ),
        )
        for target_id, compiler in cases:
            with self.subTest(target=target_id):
                target = data.target(target_id)
                outputs = iter((compiler, *shared))
                fixture = tools_for(target)
                tools = manifest.capture_build_tools(
                    target,
                    Path("/missing"),
                    lambda _key, _command: next(outputs),
                    runtime_evidence=fixture.get(runtime.EVIDENCE_KEY),
                    apple_evidence=fixture.get(apple.EVIDENCE_KEY),
                )
                expected = manifest.BUILD_TOOL_KEYS + (
                    (runtime.EVIDENCE_KEY,)
                    if target["host_os"] == "Linux"
                    else (apple.EVIDENCE_KEY,)
                )
                self.assertEqual(tuple(tools), expected)
                rendered = repr(tools)
                self.assertNotIn("/host/path", rendered)
                self.assertNotIn("2025-01-01", rendered)
                self.assertNotIn("(abc", rendered)

    def test_cmake_configured_compiler_is_invoked(self):
        data = authority.load()
        target = data.target(authority.TARGET_IDS[0])
        with tempfile.TemporaryDirectory() as directory:
            build = Path(directory)
            compiler = build / "configured-cxx"
            compiler.write_text("", encoding="utf-8")
            (build / "CMakeCache.txt").write_text(
                f"CMAKE_CXX_COMPILER:FILEPATH={compiler}\n", encoding="utf-8"
            )
            commands = []

            def run(arguments, **_kwargs):
                commands.append(arguments[0])
                outputs = {
                    str(compiler): "gcc 12.3.0\n",
                    "/tools/cmake": "cmake version 3.1.0\n",
                    "/tools/rustc": "rustc 1.80.0\n",
                    "/tools/cargo": "cargo 1.80.0\n",
                    "/tools/tar": "tar (GNU tar) 1.35\n",
                    "/tools/xz": "xz 5.6.0\n",
                    "/tools/python3": "Python 3.13.0\n",
                }
                return mock.Mock(returncode=0, stdout=outputs[arguments[0]])

            with mock.patch("shutil.which", side_effect=lambda value: f"/tools/{value}"):
                with mock.patch("pathlib.Path.is_file", return_value=True):
                    with mock.patch("subprocess.run", side_effect=run):
                        manifest.capture_build_tools(
                            target,
                            build,
                            runtime_evidence=tools_for(target)[runtime.EVIDENCE_KEY],
                        )
            self.assertEqual(commands[0], str(compiler))

    def test_missing_and_unparseable_tools_fail_with_recovery(self):
        target = authority.load().target(authority.TARGET_IDS[0])
        with mock.patch("shutil.which", return_value=None):
            with self.assertRaisesRegex(
                manifest.ManifestError, "missing required build tool.*--version"
            ):
                manifest.capture_build_tools(target, Path("/missing"))
        with mock.patch("shutil.which", return_value="/tool"):
            with mock.patch("pathlib.Path.is_file", return_value=True):
                with mock.patch(
                    "subprocess.run",
                    return_value=mock.Mock(returncode=0, stdout="mystery\n"),
                ):
                    with self.assertRaisesRegex(
                        manifest.ManifestError, "unparseable version output"
                    ):
                        manifest.capture_build_tools(target, Path("/missing"))

    def test_runtime_evidence_is_target_specific_and_normalized(self):
        data = authority.load()
        linux = data.target(authority.TARGET_IDS[0])
        macos = data.target(authority.TARGET_IDS[2])
        evidence = tools_for(linux)[runtime.EVIDENCE_KEY]
        runtime.validate_evidence(evidence)
        malformed = (
            {"client": {}},
            {
                **evidence,
                "engine": {**evidence["engine"], "output": "unobserved"},
            },
        )
        for value in malformed:
            with self.assertRaises(runtime.RuntimeSelectionError):
                runtime.validate_evidence(value)
        incompatible = {
            **evidence,
            "engine": {**evidence["engine"], "architecture": "arm64"},
        }
        with self.assertRaisesRegex(
            runtime.RuntimeSelectionError, "incompatible with target architecture"
        ):
            runtime.validate_evidence(incompatible, linux)

        outputs = {
            "compiler": "gcc 1.2.3",
            "cmake": "cmake 1.2.3",
            "rustc": "rustc 1.2.3",
            "cargo": "cargo 1.2.3",
            "tar": "GNU tar 1.2.3",
            "xz": "xz 1.2.3",
            "python": "Python 1.2.3",
        }
        with self.assertRaisesRegex(manifest.ManifestError, "missing"):
            manifest.capture_build_tools(
                linux,
                Path("/missing"),
                lambda key, _command: outputs[key],
            )
        with self.assertRaisesRegex(manifest.ManifestError, "not permitted"):
            manifest.capture_build_tools(
                macos,
                Path("/missing"),
                lambda key, _command: {
                    **outputs,
                    "compiler": "Apple clang 1.2.3",
                }[key],
                runtime_evidence=evidence,
                apple_evidence=tools_for(macos)[apple.EVIDENCE_KEY],
            )

        with self.assertRaisesRegex(manifest.ManifestError, "missing Apple"):
            manifest.capture_build_tools(
                macos,
                Path("/missing"),
                lambda key, _command: {
                    **outputs,
                    "compiler": "Apple clang 1.2.3",
                }[key],
            )


if __name__ == "__main__":
    unittest.main()
