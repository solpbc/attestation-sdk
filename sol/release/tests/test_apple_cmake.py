import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


RELEASE_DIR = Path(__file__).resolve().parents[1]
ROOT = RELEASE_DIR.parents[1]
MODULE = ROOT / "nv-attestation-sdk-cpp/cmake/nvat_apple_sdk.cmake"
SDK_CMAKE = ROOT / "nv-attestation-sdk-cpp/CMakeLists.txt"
CLI_CMAKE = ROOT / "nv-attestation-cli/CMakeLists.txt"


class AppleCMakeTest(unittest.TestCase):
    def run_script(
        self,
        host,
        sdk,
        floor="14.0",
        architecture="arm64",
        xcrun=None,
        processor="arm64",
    ):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result_path = root / "result.txt"
            script = root / "driver.cmake"
            script.write_text(
                "cmake_minimum_required(VERSION 3.11)\n"
                f'include("{MODULE.as_posix()}")\n'
                'if(DEFINED NVAT_TEST_HOST_SYSTEM_NAME)\n'
                '  set(CMAKE_HOST_SYSTEM_NAME "${NVAT_TEST_HOST_SYSTEM_NAME}")\n'
                "endif()\n"
                'if(CMAKE_HOST_SYSTEM_NAME STREQUAL "Darwin")\n'
                "  nvat_resolve_apple_toolchain()\n"
                "endif()\n"
                "if(DEFINED NVAT_EP_ENV_COMMAND)\n"
                "  list(LENGTH NVAT_EP_ENV_COMMAND _length)\n"
                "  list(GET NVAT_EP_ENV_COMMAND 3 _environment)\n"
                f'  file(WRITE "{result_path.as_posix()}" '
                '"ran=${_length}\\nenv=${_environment}\\n")\n'
                "else()\n"
                f'  file(WRITE "{result_path.as_posix()}" "skipped\\n")\n'
                "endif()\n",
                encoding="utf-8",
            )
            arguments = [
                "cmake",
                f"-DNVAT_TEST_HOST_SYSTEM_NAME={host}",
                f"-DCMAKE_HOST_SYSTEM_PROCESSOR={processor}",
                f"-DCMAKE_OSX_SYSROOT={sdk}",
                f"-DCMAKE_OSX_DEPLOYMENT_TARGET={floor}",
                f"-DCMAKE_OSX_ARCHITECTURES={architecture}",
            ]
            if xcrun is not None:
                arguments.append(f"-DNVAT_APPLE_XCRUN={xcrun}")
            arguments.extend(("-P", str(script)))
            completed = subprocess.run(
                arguments, text=True, capture_output=True, check=False
            )
            output = result_path.read_text(encoding="utf-8") if result_path.exists() else ""
            return completed, output

    def test_guard_skips_non_darwin_and_runs_for_darwin(self):
        with tempfile.TemporaryDirectory() as directory:
            sdk = Path(directory) / "MacOSX.sdk"
            sdk.mkdir()
            skipped, skipped_output = self.run_script("Linux", sdk)
            self.assertEqual(skipped.returncode, 0, skipped.stderr)
            self.assertEqual(skipped_output, "skipped\n")
            ran, ran_output = self.run_script("Darwin", sdk)
            self.assertEqual(ran.returncode, 0, ran.stderr)
            self.assertEqual(ran_output, f"ran=4\nenv=SDKROOT={sdk}\n")

    def test_spaced_hostile_sdk_path_remains_one_inert_environment_element(self):
        with tempfile.TemporaryDirectory() as directory:
            sdk = Path(directory) / "SDK $(touch should-not-exist) & [fixture].sdk"
            sdk.mkdir()
            completed, output = self.run_script("Darwin", sdk)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(output, f"ran=4\nenv=SDKROOT={sdk}\n")
            self.assertFalse((Path(directory) / "should-not-exist").exists())

    def test_list_separator_sdk_paths_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            for character, name in (
                ("semicolon", "SDK;fixture.sdk"),
                ("backslash", r"SDK\fixture.sdk"),
            ):
                with self.subTest(character=character):
                    sdk = Path(directory) / name
                    sdk.mkdir()
                    completed, _ = self.run_script("Darwin", sdk)
                    self.assertNotEqual(completed.returncode, 0)
                    self.assertRegex(
                        completed.stderr,
                        r"resolved path contains a semicolon or\s+backslash",
                    )
                    self.assertIn(
                        "-DCMAKE_OSX_SYSROOT=<absolute SDK directory>",
                        completed.stderr,
                    )

    def test_missing_floor_and_invalid_architecture_fail_with_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            sdk = Path(directory) / "MacOSX.sdk"
            sdk.mkdir()
            missing, _ = self.run_script("Darwin", sdk, floor="")
            self.assertNotEqual(missing.returncode, 0)
            self.assertIn("-DCMAKE_OSX_DEPLOYMENT_TARGET=<version>", missing.stderr)
            wrong, _ = self.run_script("Darwin", sdk, architecture="x86_64")
            self.assertNotEqual(wrong.returncode, 0)
            self.assertIn("-DCMAKE_OSX_ARCHITECTURES=arm64", wrong.stderr)
            processor, _ = self.run_script("Darwin", sdk, processor="x86_64")
            self.assertNotEqual(processor.returncode, 0)
            self.assertIn("native processor x86_64 is not arm64", processor.stderr)

    def test_nonexistent_sdk_fails_closed(self):
        completed, _ = self.run_script("Darwin", "/missing/MacOSX.sdk")
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("SDK directory does not exist", completed.stderr)

    def test_xcrun_selector_resolution_and_failures_are_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sdk = root / "Selected SDK With Spaces.sdk"
            sdk.mkdir()

            def stub(name, body):
                path = root / name
                path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
                path.chmod(0o755)
                return path

            success, output = self.run_script(
                "Darwin", "macosx", xcrun=stub("success", f"printf '%s\\n' '{sdk}'")
            )
            self.assertEqual(success.returncode, 0, success.stderr)
            self.assertEqual(output, f"ran=4\nenv=SDKROOT={sdk}\n")

            cases = (
                ("/missing/xcrun", "cannot invoke xcrun"),
                (stub("nonzero", "echo unavailable >&2; exit 7"), "exited 7"),
                (stub("empty", "exit 0"), "returned an empty path"),
                (stub("relative", "echo relative.sdk"), "not absolute"),
            )
            for executable, message in cases:
                with self.subTest(message=message):
                    completed, _ = self.run_script(
                        "Darwin", "macosx", xcrun=executable
                    )
                    self.assertNotEqual(completed.returncode, 0)
                    self.assertIn(message, completed.stderr)

    def declarations(self):
        text = SDK_CMAKE.read_text(encoding="utf-8")
        pattern = re.compile(r"ExternalProject_Add\s*\(")
        values = {}
        for match in pattern.finditer(text):
            depth = 1
            index = match.end()
            quoted = False
            while depth:
                char = text[index]
                if char == '"':
                    quoted = not quoted
                elif not quoted and char == "(":
                    depth += 1
                elif not quoted and char == ")":
                    depth -= 1
                index += 1
            body = text[match.end() : index - 1]
            name = body.split()[0]
            values[name] = body
        return values

    def test_all_external_projects_consume_shared_outputs(self):
        declarations = self.declarations()
        self.assertEqual(
            set(declarations),
            {
                "openssl_external",
                "libxml2_external",
                "xmlsec_external",
                "curl_external",
            },
        )
        for name, body in declarations.items():
            with self.subTest(dependency=name):
                self.assertEqual(body.count("${NVAT_EP_ENV_COMMAND}"), 3)
                self.assertNotIn("-isysroot", body)
                self.assertNotIn("MACOSX_DEPLOYMENT_TARGET", body)
        self.assertIn("${_EP_OPENSSL_CFLAGS}", declarations["openssl_external"])
        for name in ("libxml2_external", "xmlsec_external", "curl_external"):
            self.assertIn("${_EP_AUTOCONF_CFLAGS}", declarations[name])

    def test_preproject_guards_and_fmt_exemption_are_exact(self):
        for path in (CLI_CMAKE, SDK_CMAKE):
            prefix = path.read_text(encoding="utf-8").split("project(", 1)[0]
            self.assertNotIn("if(APPLE", prefix)
            self.assertIn('CMAKE_HOST_SYSTEM_NAME STREQUAL "Darwin"', prefix)
        sdk_prefix = SDK_CMAKE.read_text(encoding="utf-8").split("project(", 1)[0]
        self.assertIn("PROPERTY NVAT_APPLE_TOOLCHAIN_RESOLVED", sdk_prefix)
        self.assertIn("if(NOT _NVAT_APPLE_TOOLCHAIN_RESOLVED)", sdk_prefix)
        sdk = SDK_CMAKE.read_text(encoding="utf-8")
        self.assertIn("if(NOT TARGET fmt)", sdk)
        self.assertEqual(
            sdk.count(
                "set_target_properties(fmt PROPERTIES COMPILE_WARNING_AS_ERROR OFF)"
            ),
            1,
        )
        self.assertNotIn(
            "set_target_properties(spdlog PROPERTIES COMPILE_WARNING_AS_ERROR OFF)",
            sdk,
        )


if __name__ == "__main__":
    unittest.main()
