import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from cmake_support import (
    HEADER_BOUNDARY_CMAKE,
    installed_header_fixture_prepare,
    load_compile_commands,
    pinned_header_boundary_records,
    populate_pinned_header_tree,
    production_configure,
    warning_fixture_prepare,
)


RELEASE_DIR = Path(__file__).resolve().parents[1]
ROOT = RELEASE_DIR.parents[1]
CLI_DIR = ROOT / "nv-attestation-cli"
CLI_CMAKE = CLI_DIR / "CMakeLists.txt"
SDK_CMAKE = ROOT / "nv-attestation-sdk-cpp/CMakeLists.txt"
CONSUMER_FILES = (
    SDK_CMAKE,
    CLI_CMAKE,
    ROOT / "nv-attestation-cli/tests/CMakeLists.txt",
    ROOT / "nv-attestation-sdk-cpp/unit-tests/CMakeLists.txt",
)
HELPER_CALL = re.compile(
    r"nvat_target_include_pinned_logging_headers\(\s*"
    r"([A-Za-z0-9_.+-]+)\s+ORDINARY\s+(.*?)\)",
    re.DOTALL,
)


def canonical_include_root(path, directory):
    value = Path(path)
    if not value.is_absolute():
        value = Path(directory) / value
    return value.resolve()


def ordinary_conflicts_with_pinned(left, right):
    left = Path(left)
    right = Path(right)
    try:
        left.relative_to(right)
        return True
    except ValueError:
        return False


def include_roots(command):
    ordinary = []
    system = []
    arguments = command["arguments"]
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument == "-isystem":
            index += 1
            system.append(
                canonical_include_root(arguments[index], command["directory"])
            )
        elif argument.startswith("-isystem") and argument != "-isystem":
            system.append(
                canonical_include_root(
                    argument[len("-isystem"):], command["directory"]
                )
            )
        elif argument == "-I":
            index += 1
            ordinary.append(
                canonical_include_root(arguments[index], command["directory"])
            )
        elif argument.startswith("-I"):
            ordinary.append(
                canonical_include_root(argument[2:], command["directory"])
            )
        index += 1
    return ordinary, system


def command_for(commands, source_suffix):
    matches = [
        command
        for command in commands
        if Path(command["file"]).as_posix().endswith(source_suffix)
    ]
    if len(matches) != 1:
        raise AssertionError(
            f"expected one command ending in {source_suffix}, found {len(matches)}"
        )
    return matches[0]


def commands_under(commands, root):
    root = Path(root).resolve()
    return [
        command
        for command in commands
        if Path(command["file"]).resolve().is_relative_to(root)
    ]


def extracted_helper_call():
    source = CLI_CMAKE.read_text(encoding="utf-8")
    matches = HELPER_CALL.findall(source)
    calls = [
        f"nvat_target_include_pinned_logging_headers(\n"
        f"  {target}\n  ORDINARY\n{ordinary})"
        for target, ordinary in matches
        if target == "nvattest"
    ]
    if len(calls) != 1:
        raise AssertionError(f"expected one nvattest helper call, found {len(calls)}")
    return calls[0]


class HeaderConsumerBoundaryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.embedded_state = {}
        (
            cls.embedded_temporary,
            cls.embedded_completed,
            _events,
            _records,
            cls.embedded_build,
        ) = production_configure(
            CLI_DIR,
            fixture_prepare=warning_fixture_prepare(cls.embedded_state),
            export_compile_commands=True,
        )
        if cls.embedded_completed.returncode != 0:
            raise AssertionError(cls.embedded_completed.stderr)
        cls.embedded_commands = load_compile_commands(cls.embedded_build)

        cls.installed_state = {}
        (
            cls.installed_temporary,
            cls.installed_completed,
            _events,
            _records,
            cls.installed_build,
        ) = production_configure(
            CLI_DIR,
            fixture_prepare=installed_header_fixture_prepare(cls.installed_state),
            export_compile_commands=True,
        )
        if cls.installed_completed.returncode != 0:
            raise AssertionError(cls.installed_completed.stderr)
        cls.installed_commands = load_compile_commands(cls.installed_build)

    @classmethod
    def tearDownClass(cls):
        cls.embedded_temporary.cleanup()
        cls.installed_temporary.cleanup()

    def assert_pinned_system(self, command, state):
        ordinary, system = include_roots(command)
        pinned = {
            (state["fmt"] / "include").resolve(),
            (state["spdlog"] / "include").resolve(),
        }
        self.assertTrue(pinned <= set(system))
        self.assertTrue(pinned.isdisjoint(ordinary))
        self.assertEqual(
            sum(root in pinned for root in system),
            2,
            (ordinary, system),
        )
        for ordinary_root in ordinary:
            for pinned_root in pinned:
                self.assertFalse(
                    ordinary_conflicts_with_pinned(ordinary_root, pinned_root),
                    (ordinary_root, pinned_root),
                )

    def test_helper_registry_and_all_four_calls_are_closed(self):
        records = pinned_header_boundary_records()
        self.assertTrue(records)
        self.assertTrue(all(len(record) == 4 for record in records))
        self.assertEqual(
            {record[0] for record in records},
            {"fmt_SOURCE_DIR", "spdlog_SOURCE_DIR"},
        )
        module = HEADER_BOUNDARY_CMAKE.read_text(encoding="utf-8")
        self.assertEqual(module.count("NVAT_PINNED_HEADER_BOUNDARIES_BEGIN"), 1)
        self.assertEqual(module.count("NVAT_PINNED_HEADER_BOUNDARIES_END"), 1)
        self.assertIn(
            "target_include_directories(${target} SYSTEM PRIVATE "
            "${_nvat_pinned_roots})",
            module,
        )
        helper = re.search(
            r"^function\(nvat_target_include_pinned_logging_headers\b.*?"
            r"^endfunction\(\)$",
            module,
            re.MULTILINE | re.DOTALL,
        ).group(0)
        include_calls = re.findall(
            r"target_include_directories\(\$\{target\}\s+([^)]+)\)",
            helper,
        )
        self.assertEqual(len(include_calls), 2)
        self.assertRegex(include_calls[0], r"^PRIVATE\b")
        self.assertRegex(include_calls[1], r"^SYSTEM PRIVATE\b")
        for call in include_calls:
            self.assertNotRegex(call, r"\b(?:PUBLIC|INTERFACE)\b")
        targets = set()
        for path in CONSUMER_FILES:
            source = path.read_text(encoding="utf-8")
            calls = HELPER_CALL.findall(source)
            self.assertEqual(len(calls), 1, path)
            targets.add(calls[0][0])
            self.assertNotIn("${spdlog_SOURCE_DIR}/include", source)
            self.assertNotIn("${fmt_SOURCE_DIR}/include", source)
        self.assertEqual(
            targets,
            {
                "nvat",
                "nvattest",
                "nv-attestation-cli-tests",
                "nv-attestation-unit-tests",
            },
        )
        cli = CLI_CMAKE.read_text(encoding="utf-8")
        property_pattern = (
            "set_property(TARGET nvattest PROPERTY "
            "NO_SYSTEM_FROM_IMPORTED ON)"
        )
        self.assertEqual(cli.count(property_pattern), 1)
        installed_start = cli.index("if(USE_SYSTEM_NVAT)")
        embedded_start = cli.index("else()", installed_start)
        self.assertLess(installed_start, cli.index(property_pattern))
        self.assertLess(cli.index(property_pattern), embedded_start)
        for path in CONSUMER_FILES[2:]:
            self.assertNotIn(
                "NO_SYSTEM_FROM_IMPORTED",
                path.read_text(encoding="utf-8"),
            )

    def test_embedded_production_include_vectors(self):
        nvat_commands = commands_under(self.embedded_commands, SDK_CMAKE.parent)
        nvattest_commands = commands_under(self.embedded_commands, CLI_DIR)
        self.assertTrue(nvat_commands)
        self.assertEqual(len(nvattest_commands), 6)
        for command in nvat_commands:
            self.assert_pinned_system(command, self.embedded_state)
            ordinary, _ = include_roots(command)
            self.assertIn((SDK_CMAKE.parent / "src").resolve(), ordinary)
            self.assertIn((SDK_CMAKE.parent / "include").resolve(), ordinary)
            self.assertIn(
                (
                    self.embedded_build
                    / "nv-attestation-sdk-build/include"
                ).resolve(),
                ordinary,
            )
        for command in nvattest_commands:
            self.assert_pinned_system(command, self.embedded_state)
            ordinary, _ = include_roots(command)
            self.assertIn((CLI_DIR / "src").resolve(), ordinary)
            self.assertIn(self.embedded_build.resolve(), ordinary)
            self.assertIn(
                (
                    self.embedded_build
                    / "nv-attestation-sdk-build/include"
                ).resolve(),
                ordinary,
            )

    def test_installed_production_include_vectors_are_isolated(self):
        self.assertEqual(len(self.installed_commands), 6)
        self.assertFalse(
            any(
                Path(command["file"]).is_relative_to(SDK_CMAKE.parent)
                for command in self.installed_commands
            )
        )
        self.assertFalse(
            (self.installed_build / "nv-attestation-sdk-build").exists()
        )
        allowed_roots = (CLI_DIR.resolve(), self.installed_state["root"].resolve())
        for command in self.installed_commands:
            self.assert_pinned_system(command, self.installed_state)
            ordinary, system = include_roots(command)
            self.assertIn(self.installed_state["nvat_include"], ordinary)
            self.assertIn(self.installed_state["cli11"], ordinary)
            self.assertIn(self.installed_state["json"], ordinary)
            for root in ordinary + system:
                self.assertTrue(
                    any(root.is_relative_to(allowed) for allowed in allowed_roots),
                    f"ambient include root: {root}",
                )

    def copied_cli_source(self, root, before_call="", extra_ordinary=""):
        source = root / "nv-attestation-cli"
        source.mkdir()
        (source / "src").symlink_to(CLI_DIR / "src")
        (root / "nv-attestation-sdk-cpp").symlink_to(SDK_CMAKE.parent)
        text = CLI_CMAKE.read_text(encoding="utf-8")
        matches = [
            match
            for match in HELPER_CALL.finditer(text)
            if match.group(1) == "nvattest"
        ]
        self.assertEqual(len(matches), 1)
        match = matches[0]
        call = match.group(0)
        if extra_ordinary:
            call = call[:-1] + f"    {extra_ordinary}\n)"
        text = text[:match.start()] + before_call + call + text[match.end():]
        (source / "CMakeLists.txt").write_text(text, encoding="utf-8")
        return source

    def test_invalid_exact_pinned_boundary_fails_at_production_cmake_seam(self):
        records = pinned_header_boundary_records()
        first_by_root = {}
        for record in records:
            first_by_root.setdefault(record[0], record)

        def configure_case(mutate, source=None):
            state = {}
            base = installed_header_fixture_prepare(state)

            def prepare(root):
                arguments, project_include = base(root)
                mutate(root, state)
                return arguments, project_include

            temporary, completed, _, _, _ = production_configure(
                source or CLI_DIR,
                fixture_prepare=prepare,
            )
            return temporary, completed

        for root_variable, record in first_by_root.items():
            for statement in (
                f"unset({root_variable})",
                f'set({root_variable} "")',
            ):
                with self.subTest(
                    failure="missing/empty source variable",
                    record=record,
                    statement=statement,
                ):
                    def source(
                        root,
                        statement=statement,
                    ):
                        return self.copied_cli_source(
                            root,
                            before_call=statement + "\n",
                        )

                    temporary, completed = configure_case(
                        lambda _root, _state: None,
                        source=source,
                    )
                    with temporary:
                        self.assertNotEqual(completed.returncode, 0)
                        self.assertIn(
                            f"expected populated {record[1]} source variable "
                            f"{root_variable}",
                            re.sub(r"\s+", " ", completed.stderr),
                        )

            with self.subTest(failure="absent include root", record=record):
                def remove_include(_root, state, root_variable=root_variable):
                    source_root = (
                        state["fmt"]
                        if root_variable == "fmt_SOURCE_DIR"
                        else state["spdlog"]
                    )
                    shutil.rmtree(source_root / "include")

                temporary, completed = configure_case(remove_include)
                with temporary:
                    self.assertNotEqual(completed.returncode, 0)
                    self.assertIn(
                        f"expected {record[1]} include root",
                        re.sub(r"\s+", " ", completed.stderr),
                    )

        headers = {}
        for record in records:
            headers.setdefault((record[0], record[2]), record)
        for (root_variable, relative_header), record in headers.items():
            with self.subTest(failure="absent public header", record=record):
                def remove_header(
                    _root,
                    state,
                    root_variable=root_variable,
                    relative_header=relative_header,
                ):
                    source_root = (
                        state["fmt"]
                        if root_variable == "fmt_SOURCE_DIR"
                        else state["spdlog"]
                    )
                    (source_root / "include" / relative_header).unlink()

                temporary, completed = configure_case(remove_header)
                with temporary:
                    self.assertNotEqual(completed.returncode, 0)
                    self.assertIn(
                        f"expected {record[1]} public header "
                        f"'{relative_header}'",
                        re.sub(r"\s+", " ", completed.stderr),
                    )

        for index, record in enumerate(records):
            for variant in ("missing", "near", "commented"):
                with self.subTest(
                    failure="identity mismatch",
                    record=record,
                    variant=variant,
                ):
                    def break_identity(
                        _root,
                        state,
                        record=record,
                        variant=variant,
                        index=index,
                    ):
                        root_variable, _pin, relative_header, identity = record
                        source_root = (
                            state["fmt"]
                            if root_variable == "fmt_SOURCE_DIR"
                            else state["spdlog"]
                        )
                        header = source_root / "include" / relative_header
                        content = header.read_text(encoding="utf-8")
                        replacements = {
                            "missing": f"BROKEN_IDENTITY_{index}",
                            "near": identity + "0",
                            "commented": "// " + identity,
                        }
                        header.write_text(
                            content.replace(
                                identity,
                                replacements[variant],
                                1,
                            ),
                            encoding="utf-8",
                        )

                    temporary, completed = configure_case(break_identity)
                    with temporary:
                        self.assertNotEqual(completed.returncode, 0)
                        self.assertIn(
                            f"expected '{record[2]}' to identify {record[1]}",
                            re.sub(r"\s+", " ", completed.stderr),
                        )

        overlap_record = first_by_root["fmt_SOURCE_DIR"]
        overlap_path = {}

        def create_overlap(_root, state):
            path = state["fmt"] / "include" / "ordinary"
            path.mkdir()
            overlap_path["value"] = path

        def overlap_source(root):
            return self.copied_cli_source(
                root,
                extra_ordinary=str(overlap_path["value"]),
            )

        temporary, completed = configure_case(
            create_overlap,
            source=overlap_source,
        )
        with temporary:
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn(
                f"overlaps pinned {overlap_record[1]} root",
                re.sub(r"\s+", " ", completed.stderr),
            )

    def write_reduced_fixture(self, root, installed):
        source = root / ("installed" if installed else "embedded")
        source.mkdir()
        (source / "main.cpp").write_text(
            "int main() { return 0; }\n", encoding="utf-8"
        )
        (source / "src").mkdir()
        fmt = source / "fmt"
        spdlog = source / "spdlog"
        populate_pinned_header_tree(
            {"fmt_SOURCE_DIR": fmt, "spdlog_SOURCE_DIR": spdlog}
        )
        helper = HEADER_BOUNDARY_CMAKE.read_text(encoding="utf-8")
        property_line = re.search(
            r"^\s*set_property\(TARGET nvattest PROPERTY "
            r"NO_SYSTEM_FROM_IMPORTED ON\)\s*$",
            CLI_CMAKE.read_text(encoding="utf-8"),
            re.MULTILINE,
        ).group(0)
        nvat_target = (
            "add_library(nvat::nvat INTERFACE IMPORTED)\n"
            f'set_property(TARGET nvat::nvat PROPERTY '
            f'INTERFACE_INCLUDE_DIRECTORIES "{source / "nvat"}")\n'
            if installed
            else
            "add_library(nvat INTERFACE)\n"
            "add_library(nvat::nvat ALIAS nvat)\n"
            f'target_include_directories(nvat INTERFACE "{source / "nvat"}")\n'
        )
        (source / "nvat").mkdir()
        parts = [
            "cmake_minimum_required(VERSION 3.11)\n",
            "project(header_boundary LANGUAGES CXX)\n",
            'message(STATUS "ENGINE=${CMAKE_VERSION}")\n',
            helper,
            "\nadd_executable(nvattest main.cpp)\n",
            nvat_target,
            "add_library(CLI11::CLI11 INTERFACE IMPORTED)\n",
            "add_library(nlohmann_json::nlohmann_json INTERFACE IMPORTED)\n",
            "target_link_libraries(nvattest PRIVATE nvat::nvat "
            "CLI11::CLI11 nlohmann_json::nlohmann_json)\n",
        ]
        if installed:
            parts.append(property_line + "\n")
        parts.extend(
            (
                f'set(fmt_SOURCE_DIR "{fmt}")\n',
                f'set(spdlog_SOURCE_DIR "{spdlog}")\n',
                extracted_helper_call() + "\n",
            )
        )
        (source / "CMakeLists.txt").write_text("".join(parts), encoding="utf-8")
        return source, fmt, spdlog, source / "nvat"

    def configure_reduced(self, cmake, installed):
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        source, fmt, spdlog, nvat = self.write_reduced_fixture(root, installed)
        build = root / "build"
        build.mkdir()
        if cmake == "cmake":
            arguments = [
                cmake,
                "-S",
                str(source),
                "-B",
                str(build),
                "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON",
            ]
            cwd = ROOT
        else:
            arguments = [
                cmake,
                str(source),
                "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON",
            ]
            cwd = build
        completed = subprocess.run(
            arguments, cwd=cwd, text=True, capture_output=True, check=False
        )
        return temporary, completed, build, fmt, spdlog, nvat

    def assert_reduced(self, cmake, installed):
        temporary, completed, build, fmt, spdlog, nvat = self.configure_reduced(
            cmake, installed
        )
        with temporary:
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertRegex(completed.stdout, r"ENGINE=\d+\.\d+")
            self.assertTrue((build / "CMakeCache.txt").exists())
            command = load_compile_commands(build)[0]
            ordinary, system = include_roots(command)
            self.assertEqual(
                set(system),
                {(fmt / "include").resolve(), (spdlog / "include").resolve()},
            )
            self.assertIn(nvat.resolve(), ordinary)

    def test_extracted_boundary_fixture_with_release_cmake(self):
        for installed in (False, True):
            with self.subTest(installed=installed):
                self.assert_reduced("cmake", installed)

    def cmake_311(self):
        override = os.environ.get("NVAT_TEST_CMAKE_311")
        candidates = [override] if override else [
            shutil.which("cmake3.11"),
            shutil.which("cmake-3.11"),
            shutil.which("cmake"),
        ]
        for candidate in filter(None, candidates):
            completed = subprocess.run(
                [candidate, "--version"],
                text=True,
                capture_output=True,
                check=False,
            )
            match = re.search(r"cmake version (\d+\.\d+\.\d+)", completed.stdout)
            if completed.returncode == 0 and match and match.group(1).startswith(
                "3.11."
            ):
                return candidate
        if override:
            self.fail(
                f"NVAT_TEST_CMAKE_311 does not name a real CMake 3.11: {override}"
            )
        self.skipTest(
            "real CMake 3.11 not available; set NVAT_TEST_CMAKE_311 "
            "to a 3.11 executable"
        )

    def test_extracted_boundary_fixture_with_real_cmake_311_when_available(self):
        cmake = self.cmake_311()
        for installed in (False, True):
            with self.subTest(installed=installed):
                self.assert_reduced(cmake, installed)

    def compiler_arguments(self, command, source, output, include_kind, include):
        arguments = list(command["arguments"])
        filtered = []
        index = 0
        while index < len(arguments):
            argument = arguments[index]
            if argument in {"-I", "-isystem"}:
                index += 2
                continue
            if argument.startswith("-I") or argument.startswith("-isystem"):
                index += 1
                continue
            if argument == "-o":
                filtered.extend(("-o", str(output)))
                index += 2
                continue
            if Path(argument).resolve() == Path(command["file"]).resolve():
                filtered.append(str(source))
            else:
                filtered.append(argument)
            index += 1
        filtered[1:1] = [include_kind, str(include)]
        return filtered

    def test_compiler_observes_header_boundary_and_use_site(self):
        command = command_for(self.embedded_commands, "/src/nvat.cpp")
        self.assertNotIn("-Wsystem-headers", command["arguments"])
        self.assertIn("-Werror", command["arguments"])
        root = self.embedded_state["root"] / "compiler-boundary"
        include = root / "include"
        include.mkdir(parents=True)
        warning_header = include / "probe.h"
        warning_header.write_text(
            "inline int header_warning() { }\n", encoding="utf-8"
        )
        use = root / "use.cpp"
        use.write_text(
            "#include <probe.h>\nint main() { return header_warning(); }\n",
            encoding="utf-8",
        )
        for kind, expected in (("-isystem", 0), ("-I", 1)):
            with self.subTest(classification=kind):
                arguments = self.compiler_arguments(
                    command, use, root / f"{kind[1:]}.o", kind, include
                )
                completed = subprocess.run(
                    arguments,
                    cwd=command["directory"],
                    text=True,
                    capture_output=True,
                    check=False,
                )
                if expected:
                    self.assertNotEqual(completed.returncode, 0)
                    self.assertTrue(completed.stdout + completed.stderr)
                else:
                    self.assertEqual(completed.returncode, 0, completed.stderr)

        (include / "deprecated.h").write_text(
            '#pragma once\n__attribute__((deprecated("boundary proof"))) '
            "inline int old_api() { return 0; }\n",
            encoding="utf-8",
        )
        deprecated_use = root / "deprecated-use.cpp"
        deprecated_use.write_text(
            "#include <deprecated.h>\nint main() { return old_api(); }\n",
            encoding="utf-8",
        )
        completed = subprocess.run(
            self.compiler_arguments(
                command,
                deprecated_use,
                root / "deprecated.o",
                "-isystem",
                include,
            ),
            cwd=command["directory"],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertTrue(completed.stdout + completed.stderr)

    def test_readme_records_header_classification_for_vpe(self):
        readme = (RELEASE_DIR / "README.md").read_text(encoding="utf-8")
        normalized = re.sub(r"\s+", " ", readme)
        self.assertIn(
            "ordinary first-party/generated/installed roots", normalized
        )
        self.assertIn(
            "system-classified pinned fmt/spdlog roots", normalized
        )


if __name__ == "__main__":
    unittest.main()
