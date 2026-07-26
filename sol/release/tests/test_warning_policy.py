import re
import subprocess
import unittest
from pathlib import Path

from cmake_support import (
    load_codemodel,
    load_compile_commands,
    production_configure,
    warning_fixture_prepare,
)


RELEASE_DIR = Path(__file__).resolve().parents[1]
ROOT = RELEASE_DIR.parents[1]
SDK_CMAKE = ROOT / "nv-attestation-sdk-cpp/CMakeLists.txt"
CLI_CMAKE = ROOT / "nv-attestation-cli/CMakeLists.txt"
FIRST_PARTY_ROOTS = (SDK_CMAKE.parent.resolve(), CLI_CMAKE.parent.resolve())
ACCEPTED_DEMOTIONS = {
    "-Wno-unused",
    "-Wno-unused-parameter",
    "-Wno-c++17-extensions",
}
EXPECTED_FIRST_PARTY_WARNINGS = {
    "nvat": [
        "-Wall",
        "-Wextra",
        "-Wpedantic",
        "-pedantic",
        "-Wno-unused",
        "-Wno-unused-parameter",
        "-Wno-c++17-extensions",
        "-Werror",
    ],
    "nvattest": ["-Werror"],
}
EXEMPTION_CALL = re.compile(
    r"^[ \t]*nvat_exempt_compiled_third_party"
    r"\(\s*([A-Za-z0-9_.+-]+)\s+\"([^\"]+)\"\s*\)[ \t]*$",
    re.MULTILINE,
)


def exemption_calls(text):
    return [
        (match.group(1), match.group(2), match.start(), match.end())
        for match in EXEMPTION_CALL.finditer(text)
    ]


def is_within(path, root):
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def warning_options(arguments):
    return [
        argument
        for argument in arguments
        if argument == "-pedantic" or argument.startswith("-W")
    ]


def warnings_as_errors(arguments):
    return any(
        argument == "-Werror" or argument.startswith("-Werror=")
        for argument in arguments
    )


class WarningPolicyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture_state = {}
        (
            cls.temporary,
            cls.completed,
            _event_log,
            _records,
            cls.build,
        ) = production_configure(
            CLI_CMAKE.parent,
            fixture_prepare=warning_fixture_prepare(cls.fixture_state),
            query_codemodel=True,
            export_compile_commands=True,
        )
        if cls.completed.returncode != 0:
            raise AssertionError(cls.completed.stderr)
        _codemodel, cls.targets = load_codemodel(cls.build)
        cls.commands = load_compile_commands(cls.build)
        cls.compile_sources = {}
        for name, target in cls.targets.items():
            target_root = Path(target["paths"]["source"])
            if not target_root.is_absolute():
                target_root = CLI_CMAKE.parent / target_root
            sources = []
            for source in target.get("sources", []):
                if source.get("compileGroupIndex") is None:
                    continue
                source_path = Path(source["path"])
                if not source_path.is_absolute():
                    source_path = target_root / source_path
                sources.append(source_path.resolve())
            cls.compile_sources[name] = sources
        cls.compile_sources = {
            name: sources
            for name, sources in cls.compile_sources.items()
            if sources
        }
        cls.source_targets = {
            source: name
            for name, sources in cls.compile_sources.items()
            for source in sources
        }
        cls.commands_by_target = {name: [] for name in cls.compile_sources}
        for command in cls.commands:
            source = Path(command["file"]).resolve()
            if source not in cls.source_targets:
                raise AssertionError(f"unclassified compile command source: {source}")
            cls.commands_by_target[cls.source_targets[source]].append(command)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def classified_owners(self):
        first_party = set()
        third_party = set()
        third_roots = self.fixture_state["third_party_roots"]
        for target, sources in self.compile_sources.items():
            classes = set()
            for source in sources:
                if any(is_within(source, root) for root in FIRST_PARTY_ROOTS):
                    classes.add("first")
                elif any(is_within(source, root) for root in third_roots):
                    classes.add("third")
                else:
                    classes.add("outside")
            self.assertEqual(
                len(classes),
                1,
                f"{target} has mixed or unclassified compile sources: {classes}",
            )
            classification = classes.pop()
            self.assertNotEqual(
                classification, "outside", f"{target} source is outside known roots"
            )
            (first_party if classification == "first" else third_party).add(target)
        return first_party, third_party

    def test_production_codemodel_classifies_every_compile_owner(self):
        first_party, third_party = self.classified_owners()
        sdk = SDK_CMAKE.read_text(encoding="utf-8")
        declared_third_party = {
            target for target, _pin, _start, _end in exemption_calls(sdk)
        }
        effective_werror = {
            target
            for target, commands in self.commands_by_target.items()
            if commands
            and all(warnings_as_errors(command["arguments"]) for command in commands)
        }
        self.assertEqual(third_party, declared_third_party)
        self.assertEqual(first_party, effective_werror)
        self.assertEqual(set(self.compile_sources), first_party | third_party)

    def test_compiled_third_party_exemption_calls_are_adjacent_and_fail_closed(self):
        sdk = SDK_CMAKE.read_text(encoding="utf-8")
        calls = exemption_calls(sdk)
        self.assertTrue(calls)
        fallback = sdk.index(
            "if (CMAKE_VERSION VERSION_LESS 3.24.0 "
            "AND CMAKE_COMPILE_WARNING_AS_ERROR)"
        )
        for target, pin, start, _end in calls:
            self.assertTrue(
                sdk[:start].rstrip().endswith(
                    f"FetchContent_MakeAvailable({target})"
                )
            )
            self.assertLess(start, fallback)
            state = {}
            temporary, completed, _, _, _ = production_configure(
                CLI_CMAKE.parent,
                fixture_prepare=warning_fixture_prepare(state, {target}),
            )
            with temporary:
                self.assertNotEqual(completed.returncode, 0)
                self.assertIn(
                    f"{target} warning-policy exemption failed: expected compiled "
                    f"target {target} after",
                    re.sub(r"\s+", " ", completed.stderr),
                )
                self.assertIn(
                    f"verify the pinned {pin} target layout",
                    re.sub(r"\s+", " ", completed.stderr),
                )

    def test_modern_effective_warning_commands_are_exact_and_undemoted(self):
        first_party, third_party = self.classified_owners()
        self.assertEqual(first_party, set(EXPECTED_FIRST_PARTY_WARNINGS))
        for target in first_party:
            expected = EXPECTED_FIRST_PARTY_WARNINGS[target]
            options = [
                warning_options(command["arguments"])
                for command in self.commands_by_target[target]
            ]
            self.assertTrue(options)
            self.assertTrue(all(value == expected for value in options))
            for command in self.commands_by_target[target]:
                arguments = command["arguments"]
                self.assertNotIn("-w", arguments)
                self.assertNotIn("-Wno-error", arguments)
                self.assertFalse(
                    any(value.startswith("-Wno-error=") for value in arguments)
                )
                demotions = {
                    value
                    for value in arguments
                    if value.startswith("-Wno-")
                }
                self.assertLessEqual(demotions, ACCEPTED_DEMOTIONS)
        for target in third_party:
            policies = [
                warnings_as_errors(command["arguments"])
                for command in self.commands_by_target[target]
            ]
            self.assertTrue(policies)
            self.assertEqual(set(policies), {False})

    def test_extracted_legacy_policy_owns_only_first_party_targets(self):
        sdk = SDK_CMAKE.read_text(encoding="utf-8")
        cli = CLI_CMAKE.read_text(encoding="utf-8")
        helper = re.search(
            r"^function\(nvat_exempt_compiled_third_party\b.*?^endfunction\(\)$",
            sdk,
            re.MULTILINE | re.DOTALL,
        ).group(0)
        sdk_policy = re.search(
            r"^add_compile_options\(-Wall -Wextra -Wpedantic -pedantic\)$.*?"
            r"^add_compile_options\(-Wno-unused -Wno-unused-parameter\)$",
            sdk,
            re.MULTILINE | re.DOTALL,
        ).group(0)
        cli_fallback = re.search(
            r"^if\(CMAKE_VERSION VERSION_LESS 3\.24\.0 "
            r"AND CMAKE_COMPILE_WARNING_AS_ERROR\)$.*?^endif\(\)$",
            cli,
            re.MULTILINE | re.DOTALL,
        ).group(0)
        calls = exemption_calls(sdk)
        self.assertTrue(calls)
        legacy_state = {}

        def prepare(root):
            source = root / "legacy"
            source.mkdir()
            parts = [
                "cmake_minimum_required(VERSION 3.11)\n",
                "project(legacy_warning_policy LANGUAGES CXX)\n",
                helper,
                "\n",
            ]
            for target, pin, _start, _end in calls:
                (source / f"{target}.cpp").write_text(
                    f"int {target}_fixture() {{ return 0; }}\n", encoding="utf-8"
                )
                parts.extend(
                    (
                        f"add_library({target} STATIC {target}.cpp)\n",
                        f'nvat_exempt_compiled_third_party({target} "{pin}")\n',
                    )
                )
            (source / "nvat.cpp").write_text(
                "int nvat_fixture() { return 0; }\n", encoding="utf-8"
            )
            (source / "nvattest.cpp").write_text(
                "int main() { return 0; }\n", encoding="utf-8"
            )
            parts.extend(
                (
                    "add_executable(nvattest nvattest.cpp)\n",
                    "set(CMAKE_VERSION 3.11.0)\n",
                    "set(CMAKE_COMPILE_WARNING_AS_ERROR ON)\n",
                    cli_fallback,
                    "\n",
                    sdk_policy,
                    "\nadd_library(nvat STATIC nvat.cpp)\n",
                )
            )
            (source / "CMakeLists.txt").write_text(
                "".join(parts), encoding="utf-8"
            )
            legacy_state["source"] = source
            return [], ""

        # This proves production text, ordering, and fallback ownership. It does
        # not prove execution by a CMake 3.11 engine.
        temporary, completed, _, _, build = production_configure(
            lambda root: root / "legacy",
            fixture_prepare=prepare,
            export_compile_commands=True,
        )
        with temporary:
            self.assertEqual(completed.returncode, 0, completed.stderr)
            commands = load_compile_commands(build)
            options = {
                Path(command["file"]).stem: warning_options(command["arguments"])
                for command in commands
            }
            self.assertIn("-Werror", options["nvat"])
            self.assertEqual(options["nvattest"], ["-Werror"])
            for target, _pin, _start, _end in calls:
                self.assertNotIn("-Werror", options[target])
            fallback = sdk.index(
                "if (CMAKE_VERSION VERSION_LESS 3.24.0 "
                "AND CMAKE_COMPILE_WARNING_AS_ERROR)"
            )
            for target, _pin, start, _end in calls:
                self.assertLess(
                    sdk.index(f"FetchContent_MakeAvailable({target})"), start
                )
                self.assertLess(start, fallback)

    def test_effective_commands_classify_controlled_warning(self):
        first_party, third_party = self.classified_owners()
        fixture = self.fixture_state["root"] / "controlled-warning.cpp"
        fixture.write_text("int f() { }\n", encoding="utf-8")
        for target in first_party | third_party:
            command = self.commands_by_target[target][0]
            source = str(Path(command["file"]).resolve())
            arguments = list(command["arguments"])
            matches = [
                index
                for index, argument in enumerate(arguments)
                if str(Path(argument).resolve()) == source
            ]
            self.assertEqual(matches, [len(arguments) - 1])
            arguments[matches[0]] = str(fixture)
            completed = subprocess.run(
                arguments,
                cwd=command["directory"],
                text=True,
                capture_output=True,
                check=False,
            )
            diagnostic = completed.stdout + completed.stderr
            self.assertTrue(diagnostic, target)
            if target in first_party:
                self.assertNotEqual(completed.returncode, 0, target)
            else:
                self.assertEqual(completed.returncode, 0, diagnostic)

    def test_readme_names_all_derived_compile_owners_for_vpe(self):
        first_party, third_party = self.classified_owners()
        owners = first_party | third_party
        readme = (RELEASE_DIR / "README.md").read_text(encoding="utf-8")
        match = re.search(
            r"verbose\s+([A-Za-z0-9_./+-]+) warning\s+flags", readme
        )
        self.assertIsNotNone(match)
        self.assertEqual(set(match.group(1).split("/")), owners)


if __name__ == "__main__":
    unittest.main()
