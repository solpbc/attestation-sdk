import json
import os
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

    def test_production_prefix_normalizes_absent_architecture(self):
        for cmake_path, relative in (
            (SDK_CMAKE, Path("nv-attestation-sdk-cpp/CMakeLists.txt")),
            (CLI_CMAKE, Path("nv-attestation-cli/CMakeLists.txt")),
        ):
            with self.subTest(path=cmake_path):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    script = root / relative
                    script.parent.mkdir(parents=True)
                    module = (
                        root
                        / "nv-attestation-sdk-cpp/cmake/nvat_apple_sdk.cmake"
                    )
                    module.parent.mkdir(parents=True, exist_ok=True)
                    os.symlink(MODULE, module)
                    sdk = root / "MacOSX.sdk"
                    sdk.mkdir()
                    result = root / "result.txt"
                    prefix = cmake_path.read_text(encoding="utf-8").split(
                        "project(", 1
                    )[0]
                    script.write_text(
                        'set(CMAKE_HOST_SYSTEM_NAME "Darwin")\n'
                        + prefix
                        + "get_property(_resolved GLOBAL "
                        "PROPERTY NVAT_APPLE_TOOLCHAIN_RESOLVED)\n"
                        + f'file(WRITE "{result.as_posix()}" '
                        '"architecture=${CMAKE_OSX_ARCHITECTURES}\\n'
                        'resolved=${_resolved}\\n")\n',
                        encoding="utf-8",
                    )
                    completed = subprocess.run(
                        [
                            "cmake",
                            f"-DCMAKE_OSX_SYSROOT={sdk}",
                            "-DCMAKE_OSX_DEPLOYMENT_TARGET=14.0",
                            "-P",
                            str(script),
                        ],
                        text=True,
                        capture_output=True,
                        check=False,
                    )
                    self.assertEqual(completed.returncode, 0, completed.stderr)
                    self.assertEqual(
                        result.read_text(encoding="utf-8"),
                        "architecture=arm64\nresolved=TRUE\n",
                    )

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
            self.assertRegex(
                path.read_text(encoding="utf-8"),
                r"project\([^)]+\)\s*nvat_validate_apple_architecture\(\)",
            )
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

    def production_configure(self, source, values, *, nested=False, build=None):
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        build = build or root / "build"
        sdk = root / "MacOSX.sdk"
        sdk.mkdir(exist_ok=True)
        event_log = root / "events.txt"
        project_include = root / "project-include.cmake"
        project_include.write_text(
            "get_property(_validated GLOBAL "
            "PROPERTY NVAT_APPLE_ARCHITECTURE_VALIDATED)\n"
            f'file(APPEND "{event_log.as_posix()}" '
            '"project=${PROJECT_NAME};loaded=${CMAKE_CXX_COMPILER_LOADED};'
            'compiler=${CMAKE_CXX_COMPILER};validated=${_validated}\\n")\n'
            f'set(CMAKE_HOST_SYSTEM_NAME "{values.get("host_name", "Darwin")}")\n'
            f'set(CMAKE_HOST_SYSTEM_PROCESSOR "{values.get("host_processor", "arm64")}")\n'
            f'set(CMAKE_SYSTEM_NAME "{values.get("system_name", "Darwin")}")\n'
            f'set(CMAKE_SYSTEM_PROCESSOR "{values.get("system_processor", "arm64")}")\n'
            f'set(CMAKE_OSX_ARCHITECTURES "{values.get("architecture", "arm64")}")\n'
            f'set(CMAKE_CROSSCOMPILING "{values.get("crosscompiling", "FALSE")}")\n'
            + (
                'if(PROJECT_NAME STREQUAL "nv-attestation")\n'
                '  set(CMAKE_HOST_SYSTEM_PROCESSOR "x86_64")\n'
                "endif()\n"
                if nested
                else ""
            ),
            encoding="utf-8",
        )
        trace = root / "trace.json"
        arguments = [
            "cmake",
            "--trace-format=json-v1",
            f"--trace-redirect={trace}",
            "-S",
            str(source),
            "-B",
            str(build),
            f"-DCMAKE_PROJECT_INCLUDE={project_include}",
            f"-DCMAKE_OSX_SYSROOT={sdk}",
            "-DCMAKE_OSX_DEPLOYMENT_TARGET=14.0",
            "-DCMAKE_OSX_ARCHITECTURES=arm64",
            "-DBUILD_TESTING=OFF",
        ]
        if nested:
            prefix = CLI_CMAKE.read_text(encoding="utf-8").split(
                "add_subdirectory(", 1
            )[0]
            declared = set(
                re.findall(r"FetchContent_Declare\s*\(\s*([^\s)]+)", prefix)
            )
            stubs = {"CLI11", "json", "fmt", "spdlog"}
            self.assertEqual(declared, stubs)
            for name in stubs:
                stub = root / f"stub-{name}"
                stub.mkdir()
                targets = {
                    "CLI11": "CLI11::CLI11",
                    "json": "nlohmann_json::nlohmann_json",
                    "fmt": "fmt::fmt",
                    "spdlog": "spdlog::spdlog",
                }
                plain = targets[name].replace("::", "_")
                (stub / "CMakeLists.txt").write_text(
                    "cmake_minimum_required(VERSION 3.11)\n"
                    f"add_library({plain} INTERFACE)\n"
                    f"add_library({targets[name]} ALIAS {plain})\n",
                    encoding="utf-8",
                )
                arguments.append(f"-DFETCHCONTENT_SOURCE_DIR_{name.upper()}={stub}")
            arguments.extend(
                (
                    f"-DFETCHCONTENT_SOURCE_DIR_CORROSION={root / 'missing-corrosion'}",
                    "-DUSE_SYSTEM_NVAT=OFF",
                )
            )
        else:
            arguments.append(
                f"-DFETCHCONTENT_SOURCE_DIR_CORROSION={root / 'missing-corrosion'}"
            )
        completed = subprocess.run(
            arguments, text=True, capture_output=True, check=False
        )
        records = [
            json.loads(line)
            for line in trace.read_text(encoding="utf-8").splitlines()
            if line.startswith("{")
        ]
        return temporary, completed, event_log, records, build

    @staticmethod
    def traced_calls(records, command):
        return [record for record in records if record.get("cmd") == command]

    def test_postproject_host_processor_assertion_is_relocated_exactly(self):
        temporary, completed, _, records, _ = self.production_configure(
            SDK_CMAKE.parent, {"host_processor": "x86_64"}
        )
        with temporary:
            self.assertNotEqual(completed.returncode, 0)
            self.assertRegex(
                completed.stderr,
                r"Apple architecture validation failed:\s+"
                r"CMAKE_HOST_SYSTEM_PROCESSOR 'x86_64'\s+"
                r"is not arm64 or aarch64;\s+run CMake natively on an Apple "
                r"Silicon arm64 host,\s+then retry",
            )
            self.assertEqual(
                len(self.traced_calls(records, "nvat_validate_apple_architecture")),
                1,
            )

    def test_each_postproject_architecture_check_fails_independently(self):
        cases = (
            ({"host_processor": ""}, "CMAKE_HOST_SYSTEM_PROCESSOR is empty"),
            ({"system_processor": ""}, "CMAKE_SYSTEM_PROCESSOR is empty"),
            (
                {"system_processor": "x86_64"},
                "CMAKE_SYSTEM_PROCESSOR 'x86_64' is not arm64 or aarch64",
            ),
            ({"architecture": ""}, "CMAKE_OSX_ARCHITECTURES is empty"),
            (
                {"architecture": "x86_64"},
                "CMAKE_OSX_ARCHITECTURES 'x86_64' is not exactly arm64",
            ),
            (
                {"architecture": "arm64;x86_64"},
                "CMAKE_OSX_ARCHITECTURES 'arm64;x86_64' contains 2 entries",
            ),
            ({"crosscompiling": "TRUE"}, "CMAKE_CROSSCOMPILING 'TRUE' is not false"),
            ({"system_name": "Linux"}, "CMAKE_SYSTEM_NAME 'Linux' is not Darwin"),
            (
                {
                    "host_processor": "arm64",
                    "system_processor": "x86_64",
                    "architecture": "x86_64",
                },
                "CMAKE_SYSTEM_PROCESSOR 'x86_64' is not arm64 or aarch64",
            ),
            (
                {
                    "system_name": "Linux",
                    "system_processor": "x86_64",
                },
                "CMAKE_SYSTEM_PROCESSOR 'x86_64' is not arm64 or aarch64",
            ),
        )
        for values, message in cases:
            with self.subTest(values=values):
                temporary, completed, _, _, _ = self.production_configure(
                    SDK_CMAKE.parent, values
                )
                with temporary:
                    self.assertNotEqual(completed.returncode, 0)
                    self.assertIn(message, re.sub(r"\s+", " ", completed.stderr))

    def test_standalone_sdk_validates_once_per_process_without_cache_marker(self):
        with tempfile.TemporaryDirectory() as directory:
            build = Path(directory) / "build"
            for run in range(2):
                temporary, completed, event_log, records, _ = self.production_configure(
                    SDK_CMAKE.parent, {}, build=build
                )
                with temporary:
                    self.assertNotEqual(completed.returncode, 0)
                    self.assertIn("missing-corrosion", completed.stderr)
                    self.assertIn("loaded=1;compiler=", event_log.read_text())
                    writes = [
                        record
                        for record in self.traced_calls(records, "set_property")
                        if "NVAT_APPLE_ARCHITECTURE_VALIDATED" in record.get("args", [])
                    ]
                    self.assertEqual(len(writes), 1, f"configure run {run + 1}")
                    boundary_index = next(
                        index
                        for index, record in enumerate(records)
                        if record.get("cmd") == "file"
                        and record.get("args", [None])[0] == "APPEND"
                    )
                    validator_index = next(
                        index
                        for index, record in enumerate(records)
                        if record.get("cmd")
                        == "nvat_validate_apple_architecture"
                    )
                    self.assertLess(boundary_index, validator_index)
            self.assertNotIn(
                "NVAT_APPLE_ARCHITECTURE_VALIDATED",
                (build / "CMakeCache.txt").read_text(encoding="utf-8"),
            )

    def test_cli_with_sdk_uses_all_pre_nesting_stubs_and_validates_once(self):
        temporary, completed, event_log, records, _ = self.production_configure(
            CLI_CMAKE.parent, {}, nested=True
        )
        with temporary:
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("missing-corrosion", completed.stderr)
            events = event_log.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(events), 2)
            self.assertIn("project=nvattest;loaded=1;", events[0])
            self.assertIn("project=nv-attestation;loaded=1;", events[1])
            self.assertIn("validated=TRUE", events[1])
            calls = self.traced_calls(records, "nvat_validate_apple_architecture")
            self.assertEqual(len(calls), 2)
            boundary_indices = [
                index
                for index, record in enumerate(records)
                if record.get("cmd") == "file"
                and record.get("args", [None])[0] == "APPEND"
            ]
            validator_indices = [
                index
                for index, record in enumerate(records)
                if record.get("cmd") == "nvat_validate_apple_architecture"
            ]
            self.assertEqual(len(boundary_indices), 2)
            self.assertEqual(len(validator_indices), 2)
            for boundary_index, validator_index in zip(
                boundary_indices, validator_indices
            ):
                self.assertLess(boundary_index, validator_index)
            writes = [
                record
                for record in self.traced_calls(records, "set_property")
                if "NVAT_APPLE_ARCHITECTURE_VALIDATED" in record.get("args", [])
            ]
            self.assertEqual(len(writes), 1)

    def test_postproject_failure_precedes_dependency_population(self):
        temporary, completed, _, _, build = self.production_configure(
            SDK_CMAKE.parent, {"architecture": "x86_64"}
        )
        with temporary:
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn(
                "CMAKE_OSX_ARCHITECTURES 'x86_64' is not exactly arm64",
                re.sub(r"\s+", " ", completed.stderr),
            )
            self.assertFalse((build / "_deps").exists())
            self.assertEqual(list(build.glob("*_external-prefix")), [])


if __name__ == "__main__":
    unittest.main()
