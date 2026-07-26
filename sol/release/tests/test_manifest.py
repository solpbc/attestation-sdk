import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


RELEASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RELEASE_DIR))

from release_rail import authority, manifest  # noqa: E402


class ManifestTest(unittest.TestCase):
    def test_tool_evidence_has_exact_keys_and_normalized_versions(self):
        data = authority.load()
        target = dict(data.target(authority.TARGET_IDS[0]))
        outputs = iter(
            (
                "gcc (SUSE Linux) 14.2.1 20260101 /host/path\n",
                "cmake version 3.31.4\n",
                "rustc 1.84.0 (abc 2025-01-01)\n",
                "cargo 1.84.0 (def 2025-01-01)\n",
                "tar (GNU tar) 1.35\n",
                "xz (XZ Utils) 5.6.3\n",
                "Python 3.13.1\n",
            )
        )

        def run(*_args, **_kwargs):
            return mock.Mock(returncode=0, stdout=next(outputs))

        with mock.patch("shutil.which", side_effect=lambda value: f"/tools/{value}"):
            with mock.patch("pathlib.Path.is_file", return_value=True):
                with mock.patch("subprocess.run", side_effect=run):
                    tools = manifest.capture_build_tools(target, Path("/missing"))
        self.assertEqual(
            tuple(tools),
            ("compiler", "cmake", "rustc", "cargo", "tar", "xz", "python"),
        )
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
                        manifest.capture_build_tools(target, build)
            self.assertEqual(commands[0], str(compiler))

    def test_missing_and_unparseable_tools_fail_with_recovery(self):
        data = authority.load()
        target = data.target(authority.TARGET_IDS[0])
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


if __name__ == "__main__":
    unittest.main()
