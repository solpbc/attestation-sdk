import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


RELEASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RELEASE_DIR))

from release_rail import apple, authority, manifest  # noqa: E402
from support import SOURCE, tools_for  # noqa: E402


class AppleToolchainTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.sdk = self.root / "MacOSX Test.sdk"
        self.sdk.mkdir()
        self.data = authority.load()
        self.target = self.data.target(authority.TARGET_IDS[2])
        self.commands = []
        self.command_results = {
            ("clang++", "--version"): (
                0,
                "Apple clang version 1.2.3 (clang-123)\n",
                "",
            ),
            ("/tools/clang++", "--version"): (
                0,
                "Apple clang version 1.2.3\n",
                "",
            ),
            ("xcodebuild", "-version"): (
                0,
                "Xcode 2.3.4\nBuild version A123\n",
                "",
            ),
            (
                "xcrun",
                "--sdk",
                apple.SDK_NAME,
                "--show-sdk-path",
            ): (0, f"{self.sdk}\n", ""),
            (
                "xcrun",
                "--sdk",
                apple.SDK_NAME,
                "--show-sdk-version",
            ): (0, "3.4.5\n", ""),
        }

    def tearDown(self):
        self.temporary.cleanup()

    def runner(self, arguments, **_kwargs):
        command = tuple(arguments)
        self.commands.append(command)
        return subprocess.CompletedProcess(
            arguments, *self.command_results[command]
        )

    def evidence(self):
        return apple.preflight(self.target, self.runner)

    def write_build(
        self,
        *,
        compiler_id="AppleClang",
        compiler_version="1.2.3",
        compiler_metadata=None,
        **overrides,
    ):
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
            (
                f'set(CMAKE_CXX_COMPILER_ID "{compiler_id}")\n'
                f'set(CMAKE_CXX_COMPILER_VERSION "{compiler_version}")\n'
                if compiler_metadata is None
                else compiler_metadata
            ),
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

    def test_resolve_normalizes_native_build_qualified_appleclang_identity(self):
        native = "Apple clang version 21.0.0 (clang-2100.1.1.101)\n"
        self.command_results[("clang++", "--version")] = (0, native, "")
        self.command_results[("/tools/clang++", "--version")] = (0, native, "")
        self.write_build(compiler_version="21.0.0.21000101")

        evidence = apple.resolve(self.target, self.root, self.runner)

        self.assertEqual(
            evidence["apple_clang"],
            {"name": "Apple clang", "version": "21.0.0"},
        )
        self.assertEqual(evidence, self.evidence())

    def test_resolve_accepts_exact_three_component_cmake_version(self):
        native = "Apple clang version 21.0.0 (clang-2100.1.1.101)\n"
        self.command_results[("clang++", "--version")] = (0, native, "")
        self.command_results[("/tools/clang++", "--version")] = (0, native, "")
        self.write_build(compiler_version="21.0.0")

        evidence = apple.resolve(self.target, self.root, self.runner)

        self.assertEqual(
            evidence["apple_clang"],
            {"name": "Apple clang", "version": "21.0.0"},
        )
        self.assertEqual(evidence, self.evidence())

    def test_resolve_invokes_exact_cache_compiler_path(self):
        compiler = str(self.root / "Configured Toolchain/clang++")
        self.command_results[(compiler, "--version")] = (
            0,
            "Apple clang version 1.2.3\n",
            "",
        )
        self.write_build(CMAKE_CXX_COMPILER=compiler)

        apple.resolve(self.target, self.root, self.runner)

        self.assertEqual(self.commands[0], (compiler, "--version"))

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
                with self.assertRaisesRegex(
                    apple.AppleToolchainError, message
                ) as raised:
                    apple.resolve(self.target, self.root, self.runner)
                if message == "compiler observation":
                    diagnostic = str(raised.exception)
                    self.assertIn("configured compiler '/tools/clang++'", diagnostic)
                    self.assertIn(
                        "compiler observation is 'Apple clang' '1.2.3'",
                        diagnostic,
                    )
                    self.assertIn(
                        "CMake ID/version record is 'AppleClang' '9.9.9'",
                        diagnostic,
                    )
                    self.assertIn(
                        "select one Xcode toolchain, remove build/release, and retry",
                        diagnostic,
                    )

    def test_resolve_rejects_invalid_cmake_appleclang_records(self):
        native = "Apple clang version 21.0.0 (clang-2100.1.1.101)\n"
        self.command_results[("/tools/clang++", "--version")] = (0, native, "")
        cases = (
            ("id-clang", "Clang", "21.0.0.21000101", None, True, None),
            ("id-gnu", "GNU", "21.0.0.21000101", None, True, None),
            ("id-case", "appleclang", "21.0.0.21000101", None, True, None),
            ("id-space", "AppleClang ", "21.0.0.21000101", None, True, None),
            (
                "id-empty",
                "",
                "21.0.0.21000101",
                None,
                False,
                "CMAKE_CXX_COMPILER_ID",
            ),
            ("version-major", "AppleClang", "20.0.0", None, True, None),
            ("version-minor", "AppleClang", "21.1.0", None, True, None),
            ("version-patch", "AppleClang", "21.0.1", None, True, None),
            ("version-one", "AppleClang", "21", None, True, None),
            ("version-two", "AppleClang", "21.0", None, True, None),
            ("version-five", "AppleClang", "21.0.0.1.2", None, True, None),
            ("version-trailing-dot", "AppleClang", "21.0.0.", None, True, None),
            ("version-leading-dot", "AppleClang", ".21.0.0", None, True, None),
            (
                "version-build-five",
                "AppleClang",
                "21.0.0.21000101.1",
                None,
                True,
                None,
            ),
            ("version-plus", "AppleClang", "+21.0.0", None, True, None),
            ("version-minus", "AppleClang", "-21.0.0", None, True, None),
            ("version-trailing-space", "AppleClang", "21.0.0 ", None, True, None),
            ("version-leading-space", "AppleClang", " 21.0.0", None, True, None),
            ("version-suffix", "AppleClang", "21.0.0rc1", None, True, None),
            ("version-prefix", "AppleClang", "v21.0.0", None, True, None),
            (
                "version-empty",
                "AppleClang",
                "",
                None,
                False,
                "CMAKE_CXX_COMPILER_VERSION",
            ),
            (
                "version-absent",
                "AppleClang",
                "unused",
                'set(CMAKE_CXX_COMPILER_ID "AppleClang")\n',
                False,
                "CMAKE_CXX_COMPILER_VERSION",
            ),
        )
        for (
            label,
            compiler_id,
            compiler_version,
            compiler_metadata,
            observed,
            invalid_field,
        ) in cases:
            with self.subTest(label=label):
                self.commands.clear()
                self.write_build(
                    compiler_id=compiler_id,
                    compiler_version=compiler_version,
                    compiler_metadata=compiler_metadata,
                )

                with self.assertRaises(apple.AppleToolchainError) as raised:
                    apple.resolve(self.target, self.root, self.runner)

                diagnostic = str(raised.exception)
                self.assertEqual(
                    diagnostic.count("Apple toolchain evidence failed: "), 1
                )
                self.assertIn("configured compiler '/tools/clang++'", diagnostic)
                if observed:
                    self.assertIn(
                        "compiler observation is 'Apple clang' '21.0.0'",
                        diagnostic,
                    )
                    self.assertIn(
                        "CMake ID/version record is "
                        f"{compiler_id!r} {compiler_version!r}",
                        diagnostic,
                    )
                    self.assertIn(
                        "select one Xcode toolchain, remove build/release, and retry",
                        diagnostic,
                    )
                    self.assertEqual(
                        self.commands, [("/tools/clang++", "--version")]
                    )
                else:
                    self.assertIn("public observation not attempted", diagnostic)
                    self.assertIn("record is malformed", diagnostic)
                    self.assertIn(f"invalid {invalid_field}", diagnostic)
                    self.assertIn(
                        "remove the build directory and rerun the native configure",
                        diagnostic,
                    )
                    self.assertEqual(self.commands, [])

    def test_resolve_rejects_invalid_public_appleclang_observations(self):
        cases = (
            (
                "two-components",
                0,
                "Apple clang version 21.0\n",
                "",
                "compiler is not normalized AppleClang",
            ),
            (
                "four-components",
                0,
                "Apple clang version 21.0.0.21000101 (x)\n",
                "",
                "compiler is not normalized AppleClang",
            ),
            (
                "letter-suffix",
                0,
                "Apple clang version 21.0.0rc1\n",
                "",
                "compiler is not normalized AppleClang",
            ),
            (
                "five-components",
                0,
                "Apple clang version 21.0.0.1.2 (x)\n",
                "",
                "compiler is not normalized AppleClang",
            ),
            (
                "prefixed-product",
                0,
                "prefixed Apple clang version 21.0.0 (x)\n",
                "",
                "compiler is not normalized AppleClang",
            ),
            (
                "wrong-product",
                0,
                "Apple LLVM version 21.0.0\n",
                "",
                "compiler is not normalized AppleClang",
            ),
            (
                "arbitrary-tail",
                0,
                "Apple clang version 21.0.0 arbitrary\n",
                "",
                "compiler is not normalized AppleClang",
            ),
            (
                "text-after-token",
                0,
                "Apple clang version 21.0.0 (clang-2100) extra\n",
                "",
                "compiler is not normalized AppleClang",
            ),
            (
                "stderr-only",
                0,
                "",
                "not selected",
                "returned empty output",
            ),
            ("empty", 0, "", "", "returned empty output"),
        )
        for label, returncode, stdout, stderr, fragment in cases:
            with self.subTest(label=label):
                self.commands.clear()
                self.command_results[("/tools/clang++", "--version")] = (
                    returncode,
                    stdout,
                    stderr,
                )
                self.write_build(compiler_version="21.0.0.21000101")

                with self.assertRaises(apple.AppleToolchainError) as raised:
                    apple.resolve(self.target, self.root, self.runner)

                diagnostic = str(raised.exception)
                self.assertEqual(
                    diagnostic.count("Apple toolchain evidence failed: "), 1
                )
                self.assertEqual(diagnostic.count("then retry"), 1)
                self.assertIn("configured compiler '/tools/clang++'", diagnostic)
                self.assertIn(
                    "CMake ID/version record is "
                    "'AppleClang' '21.0.0.21000101'",
                    diagnostic,
                )
                self.assertIn("public observation", diagnostic)
                self.assertIn(fragment, diagnostic)
                self.assertEqual(
                    self.commands, [("/tools/clang++", "--version")]
                )

    def test_resolve_compiler_observation_failures_compose_one_recovery(self):
        cases = (
            (
                "nonzero",
                (1, "", "not selected"),
                "Apple toolchain evidence failed: configured compiler "
                "'/tools/clang++'; CMake ID/version record is "
                "'AppleClang' '21.0.0.21000101'; public observation "
                "/tools/clang++ --version failed: not selected; select a valid "
                "Xcode developer directory with `xcode-select`, then retry",
            ),
            (
                "empty",
                (0, "", ""),
                "Apple toolchain evidence failed: configured compiler "
                "'/tools/clang++'; CMake ID/version record is "
                "'AppleClang' '21.0.0.21000101'; public observation "
                "/tools/clang++ --version returned empty output; verify the command "
                "and active Xcode selection, then retry",
            ),
            (
                "unparseable",
                (0, "clang version 21.0.0\n", ""),
                "Apple toolchain evidence failed: configured compiler "
                "'/tools/clang++'; CMake ID/version record is "
                "'AppleClang' '21.0.0.21000101'; public observation compiler is not "
                "normalized AppleClang: 'clang version 21.0.0'; select the Xcode "
                "AppleClang toolchain, then retry",
            ),
        )
        for label, result, expected in cases:
            with self.subTest(label=label):
                self.commands.clear()
                self.command_results[("/tools/clang++", "--version")] = result
                self.write_build(compiler_version="21.0.0.21000101")

                with self.assertRaises(apple.AppleToolchainError) as raised:
                    apple.resolve(self.target, self.root, self.runner)

                diagnostic = str(raised.exception)
                self.assertEqual(diagnostic, expected)
                self.assertEqual(
                    diagnostic.count("Apple toolchain evidence failed: "), 1
                )
                self.assertEqual(diagnostic.count("then retry"), 1)

    def test_resolve_compiler_observation_composes_unprefixed_error_sanely(self):
        self.write_build(compiler_version="21.0.0.21000101")
        error = apple.AppleToolchainError(
            "unprefixed compiler failure; inspect the configured compiler, then retry"
        )

        with mock.patch.object(
            apple, "_compiler_observation", side_effect=error
        ):
            with self.assertRaises(apple.AppleToolchainError) as raised:
                apple.resolve(self.target, self.root, self.runner)

        diagnostic = str(raised.exception)
        self.assertEqual(
            diagnostic,
            "Apple toolchain evidence failed: configured compiler '/tools/clang++'; "
            "CMake ID/version record is 'AppleClang' '21.0.0.21000101'; public "
            "observation unprefixed compiler failure; inspect the configured compiler, "
            "then retry",
        )
        self.assertEqual(diagnostic.count("Apple toolchain evidence failed: "), 1)
        self.assertEqual(diagnostic.count("then retry"), 1)

    def test_authored_arm64_cache_rejects_non_arm64_host_observation(self):
        self.write_build(CMAKE_OSX_ARCHITECTURES="arm64")
        self.assertIn(
            "CMAKE_OSX_ARCHITECTURES:STRING=arm64",
            (self.root / "CMakeCache.txt").read_text(encoding="utf-8"),
        )
        with self.assertRaisesRegex(
            authority.AuthorityError, "unsupported release host Darwin/x86_64"
        ):
            self.target = authority.load().require_compatible(
                "macos-arm64", os_name="Darwin", machine="x86_64"
            )

    def test_resolve_real_subprocess_compiler_path_failures_are_closed(self):
        missing = self.root / "missing-clang++"
        unreadable = self.root / "unreadable-clang++"
        unreadable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        unreadable.chmod(0o000)
        non_executable = self.root / "non-executable-clang++"
        non_executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        non_executable.chmod(0o644)

        for label, compiler in (
            ("missing", missing),
            ("unreadable", unreadable),
            ("non-executable", non_executable),
        ):
            with self.subTest(label=label):
                self.write_build(
                    compiler_version="21.0.0.21000101",
                    CMAKE_CXX_COMPILER=str(compiler),
                )

                with self.assertRaises(apple.AppleToolchainError) as raised:
                    apple.resolve(self.target, self.root)

                diagnostic = str(raised.exception)
                self.assertEqual(
                    diagnostic.count("Apple toolchain evidence failed: "), 1
                )
                self.assertEqual(diagnostic.count("then retry"), 1)
                self.assertIn(
                    f"configured compiler {str(compiler)!r}", diagnostic
                )
                self.assertIn(
                    "CMake ID/version record is "
                    "'AppleClang' '21.0.0.21000101'",
                    diagnostic,
                )
                self.assertIn(
                    f"public observation cannot invoke {compiler}", diagnostic
                )
                self.assertIn(
                    "install Xcode Command Line Tools and verify the active "
                    "developer directory with `xcode-select -p`, then retry",
                    diagnostic,
                )
                self.assertNotIn("xcodebuild", diagnostic)
                self.assertNotIn("xcrun", diagnostic)

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
        self.commands.clear()
        with self.assertRaisesRegex(
            apple.AppleToolchainError, "one configured"
        ) as raised:
            apple.resolve(self.target, self.root, self.runner)
        diagnostic = str(raised.exception)
        self.assertIn("configured compiler '/tools/clang++'", diagnostic)
        self.assertIn("public observation not attempted", diagnostic)
        self.assertIn("record is missing or ambiguous", diagnostic)
        self.assertIn(
            "remove the build directory and rerun the native configure",
            diagnostic,
        )
        self.assertEqual(self.commands, [])

    def test_unreadable_compiler_metadata_is_normalized(self):
        self.write_build()
        metadata = next(
            (self.root / "CMakeFiles").glob("*/CMakeCXXCompiler.cmake")
        )
        read_text = Path.read_text

        def read(path, *arguments, **keywords):
            if path == metadata:
                raise OSError("permission denied")
            return read_text(path, *arguments, **keywords)

        with mock.patch.object(Path, "read_text", new=read):
            with self.assertRaisesRegex(
                apple.AppleToolchainError,
                rf"cannot read {re.escape(str(metadata))}: permission denied; "
                "remove the build directory",
            ) as raised:
                apple.resolve(self.target, self.root, self.runner)
        diagnostic = str(raised.exception)
        self.assertIn("configured compiler '/tools/clang++'", diagnostic)
        self.assertIn("public observation not attempted", diagnostic)
        self.assertIn("record is unreadable", diagnostic)
        self.assertEqual(self.commands, [])

    def test_resolve_missing_and_malformed_metadata_name_compiler_context(self):
        cases = (
            (
                "absent-id",
                'set(CMAKE_CXX_COMPILER_VERSION "1.2.3")\n',
                "CMAKE_CXX_COMPILER_ID",
                False,
            ),
            (
                "absent-version",
                'set(CMAKE_CXX_COMPILER_ID "AppleClang")\n',
                "CMAKE_CXX_COMPILER_VERSION",
                False,
            ),
            (
                "empty-id",
                'set(CMAKE_CXX_COMPILER_ID "")\n'
                'set(CMAKE_CXX_COMPILER_VERSION "1.2.3")\n',
                "CMAKE_CXX_COMPILER_ID",
                False,
            ),
            (
                "empty-version",
                'set(CMAKE_CXX_COMPILER_ID "AppleClang")\n'
                'set(CMAKE_CXX_COMPILER_VERSION "")\n',
                "CMAKE_CXX_COMPILER_VERSION",
                False,
            ),
            (
                "duplicate-id",
                'set(CMAKE_CXX_COMPILER_ID "AppleClang")\n'
                'set(CMAKE_CXX_COMPILER_ID "Clang")\n'
                'set(CMAKE_CXX_COMPILER_VERSION "1.2.3")\n',
                "CMAKE_CXX_COMPILER_ID",
                False,
            ),
            ("ambiguous-file", None, "one configured", True),
        )
        for label, metadata_text, expected, ambiguous in cases:
            with self.subTest(label=label):
                self.commands.clear()
                self.write_build(compiler_metadata=metadata_text)
                if ambiguous:
                    second = (
                        self.root
                        / "CMakeFiles/other/CMakeCXXCompiler.cmake"
                    )
                    second.parent.mkdir(parents=True, exist_ok=True)
                    second.write_text(
                        'set(CMAKE_CXX_COMPILER_ID "AppleClang")\n'
                        'set(CMAKE_CXX_COMPILER_VERSION "1.2.3")\n',
                        encoding="utf-8",
                    )

                with self.assertRaises(apple.AppleToolchainError) as raised:
                    apple.resolve(self.target, self.root, self.runner)

                diagnostic = str(raised.exception)
                self.assertEqual(
                    diagnostic.count("Apple toolchain evidence failed: "), 1
                )
                self.assertIn("configured compiler '/tools/clang++'", diagnostic)
                self.assertIn("public observation not attempted", diagnostic)
                self.assertIn(expected, diagnostic)
                if ambiguous:
                    self.assertIn("record is missing or ambiguous", diagnostic)
                else:
                    self.assertIn("record is malformed", diagnostic)
                self.assertIn(
                    "remove the build directory and rerun the native configure",
                    diagnostic,
                )
                self.assertEqual(self.commands, [])

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

    def test_manifest_validation_does_not_normalize_build_qualified_appleclang_version(
        self,
    ):
        artifact = self.root / "artifact.tar.xz"
        artifact.write_bytes(b"artifact")
        tools = tools_for(self.target)
        tools[apple.EVIDENCE_KEY]["apple_clang"]["version"] = (
            "21.0.0.21000101"
        )
        value = manifest.build(
            release=self.data.release,
            target=self.target,
            version="1.2.2-sol.2",
            source=SOURCE,
            artifact_path=artifact,
            dependencies=[],
            build_tools=tools,
        )

        round_trip = json.loads(json.dumps(value))
        manifest.validate_build_tools(
            self.target, round_trip["build_tools"]
        )

        version = round_trip["build_tools"][apple.EVIDENCE_KEY][
            "apple_clang"
        ]["version"]
        self.assertEqual(version, "21.0.0.21000101")
        self.assertNotEqual(version, "21.0.0")

    def test_historical_public_appleclang_evidence_round_trips(self):
        artifact = self.root / "artifact.tar.xz"
        artifact.write_bytes(b"artifact")
        tools = tools_for(self.target)
        tools[apple.EVIDENCE_KEY]["apple_clang"]["version"] = "21.0.0"
        value = manifest.build(
            release=self.data.release,
            target=self.target,
            version="1.2.2-sol.2",
            source=SOURCE,
            artifact_path=artifact,
            dependencies=[],
            build_tools=tools,
        )

        round_trip = json.loads(json.dumps(value))
        manifest.validate_build_tools(
            self.target, round_trip["build_tools"]
        )

        compiler = round_trip["build_tools"][apple.EVIDENCE_KEY][
            "apple_clang"
        ]
        self.assertEqual(
            compiler,
            {"name": "Apple clang", "version": "21.0.0"},
        )
        self.assertEqual(tuple(compiler), ("name", "version"))

    def test_command_and_output_failures_are_actionable(self):
        def failed(arguments, **_kwargs):
            return subprocess.CompletedProcess(arguments, 1, "", "not selected")

        with self.assertRaisesRegex(
            apple.AppleToolchainError, "failed: not selected.*then retry"
        ):
            apple.preflight(self.target, failed)


if __name__ == "__main__":
    unittest.main()
