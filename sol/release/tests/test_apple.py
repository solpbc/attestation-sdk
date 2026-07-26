import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


RELEASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RELEASE_DIR))

from release_rail import apple, authority  # noqa: E402


class AppleToolchainTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.sdk = self.root / "MacOSX Test.sdk"
        self.sdk.mkdir()
        self.target = authority.load().target(authority.TARGET_IDS[2])

    def tearDown(self):
        self.temporary.cleanup()

    def runner(self, arguments, **_kwargs):
        outputs = {
            ("clang++", "--version"): "Apple clang version 1.2.3 (clang-123)\n",
            ("/tools/clang++", "--version"): "Apple clang version 1.2.3\n",
            ("xcodebuild", "-version"): "Xcode 2.3.4\nBuild version A123\n",
            (
                "xcrun",
                "--sdk",
                apple.SDK_NAME,
                "--show-sdk-path",
            ): f"{self.sdk}\n",
            (
                "xcrun",
                "--sdk",
                apple.SDK_NAME,
                "--show-sdk-version",
            ): "3.4.5\n",
        }
        return subprocess.CompletedProcess(arguments, 0, outputs[tuple(arguments)], "")

    def evidence(self):
        return apple.preflight(self.target, self.runner)

    def write_build(self, **overrides):
        values = {
            "CMAKE_CXX_COMPILER": "/tools/clang++",
            "CMAKE_OSX_SYSROOT": str(self.sdk),
            "CMAKE_OSX_ARCHITECTURES": "arm64",
            "CMAKE_OSX_DEPLOYMENT_TARGET": self.target["abi_floor"]["macos"],
        }
        values.update(overrides)
        (self.root / "CMakeCache.txt").write_text(
            "".join(f"{key}:STRING={value}\n" for key, value in values.items()),
            encoding="utf-8",
        )
        metadata = self.root / "CMakeFiles/1.2.3/CMakeCXXCompiler.cmake"
        metadata.parent.mkdir(parents=True, exist_ok=True)
        metadata.write_text(
            'set(CMAKE_CXX_COMPILER_ID "AppleClang")\n'
            'set(CMAKE_CXX_COMPILER_VERSION "1.2.3")\n',
            encoding="utf-8",
        )

    def test_preflight_returns_closed_normalized_evidence(self):
        evidence = self.evidence()
        self.assertEqual(
            tuple(evidence),
            (
                "apple_clang",
                "xcode",
                "sdk",
                "architecture",
                "deployment_target",
            ),
        )
        self.assertEqual(evidence["sdk"]["path"], str(self.sdk))
        self.assertEqual(evidence["architecture"], "arm64")
        self.assertEqual(
            evidence["deployment_target"], self.target["abi_floor"]["macos"]
        )

    def test_resolve_cross_checks_cache_and_compiler_metadata(self):
        self.write_build()
        self.assertEqual(
            apple.resolve(self.target, self.root, self.runner), self.evidence()
        )

    def test_cache_and_compiler_disagreements_fail_closed(self):
        cases = (
            (
                {"CMAKE_OSX_SYSROOT": str(self.root / "missing.sdk")},
                None,
                "configured SDK sysroot",
            ),
            (
                {"CMAKE_OSX_ARCHITECTURES": "x86_64"},
                None,
                "configured architecture",
            ),
            (
                {"CMAKE_OSX_DEPLOYMENT_TARGET": "13.0"},
                None,
                "configured deployment target",
            ),
            ({}, ("AppleClang", "9.9.9"), "compiler observation"),
        )
        for overrides, metadata, message in cases:
            with self.subTest(message=message):
                self.write_build(**overrides)
                if metadata is not None:
                    path = next(
                        (self.root / "CMakeFiles").glob(
                            "*/CMakeCXXCompiler.cmake"
                        )
                    )
                    path.write_text(
                        f'set(CMAKE_CXX_COMPILER_ID "{metadata[0]}")\n'
                        f'set(CMAKE_CXX_COMPILER_VERSION "{metadata[1]}")\n',
                        encoding="utf-8",
                    )
                with self.assertRaisesRegex(apple.AppleToolchainError, message):
                    apple.resolve(self.target, self.root, self.runner)

    def test_missing_cache_and_ambiguous_metadata_fail_closed(self):
        with self.assertRaisesRegex(apple.AppleToolchainError, "cannot read"):
            apple.resolve(self.target, self.root, self.runner)
        self.write_build()
        second = self.root / "CMakeFiles/other/CMakeCXXCompiler.cmake"
        second.parent.mkdir()
        second.write_text(
            'set(CMAKE_CXX_COMPILER_ID "AppleClang")\n'
            'set(CMAKE_CXX_COMPILER_VERSION "1.2.3")\n',
            encoding="utf-8",
        )
        with self.assertRaisesRegex(apple.AppleToolchainError, "one configured"):
            apple.resolve(self.target, self.root, self.runner)

    def test_validator_rejects_malformed_and_target_inconsistent_values(self):
        evidence = self.evidence()
        cases = (
            {**evidence, "extra": "field"},
            {
                **evidence,
                "apple_clang": {"name": apple.APPLE_CLANG_NAME, "version": "raw"},
            },
            {**evidence, "architecture": "x86_64"},
            {**evidence, "deployment_target": "13.0"},
        )
        for value in cases:
            with self.subTest(value=value):
                with self.assertRaises(apple.AppleToolchainError):
                    apple.validate_evidence(value, self.target)

    def test_command_and_output_failures_are_actionable(self):
        def failed(arguments, **_kwargs):
            return subprocess.CompletedProcess(arguments, 1, "", "not selected")

        with self.assertRaisesRegex(
            apple.AppleToolchainError, "failed: not selected.*then retry"
        ):
            apple.preflight(self.target, failed)


if __name__ == "__main__":
    unittest.main()
