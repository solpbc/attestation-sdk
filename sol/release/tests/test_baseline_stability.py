import ast
import importlib.util
import re
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path


RELEASE_DIR = Path(__file__).resolve().parents[1]
ROOT = RELEASE_DIR.parents[1]
sys.path.insert(0, str(RELEASE_DIR))

from release_rail import authority, set_validator  # noqa: E402


GENERATOR_PATH = RELEASE_DIR / "generate-dependencies.py"
GENERATOR_SPEC = importlib.util.spec_from_file_location(
    "generate_dependencies", GENERATOR_PATH
)
generate_dependencies = importlib.util.module_from_spec(GENERATOR_SPEC)
GENERATOR_SPEC.loader.exec_module(generate_dependencies)


BASELINE = "b75e95ae0c08ac6eaa05673a0cf227b8723e2b58"
TARGETS = Path("sol/release/targets.toml")
AUTHORITY = Path("sol/release/release_rail/authority.py")
SDK_CMAKE = Path("nv-attestation-sdk-cpp/CMakeLists.txt")
CLI_CMAKE = Path("nv-attestation-cli/CMakeLists.txt")
LICENSE = Path("LICENSE")
HEADER_BOUNDARY = Path(
    "nv-attestation-sdk-cpp/cmake/nvat_header_consumer_boundary.cmake"
)
APPLE_LINK_CLOSURE = Path(
    "nv-attestation-sdk-cpp/cmake/nvat_apple_system_link_closure.cmake"
)
RUST_INVENTORY = (
    "nv-attestation-sdk-rust/Cargo.toml",
    "nv-attestation-sdk-rust/nv-attestation-sdk-sys/Cargo.toml",
    "nv-attestation-sdk-rust/nv-attestation-sdk-sys/build.rs",
    "nv-attestation-sdk-rust/nv-attestation-sdk/Cargo.toml",
)
PROJECT = re.compile(
    r"^project\(([^\s)]+)\s+VERSION\s+([^\s)]+)\)$", re.MULTILINE
)
TARGET_IDS = re.compile(r"^TARGET_IDS\s*=\s*(\([^\n]*\))$", re.MULTILINE)


class BaselineStabilityTest(unittest.TestCase):
    def baseline(self, path):
        return subprocess.run(
            ["git", "show", f"{BASELINE}:{path.as_posix()}"],
            cwd=ROOT,
            check=True,
            capture_output=True,
        ).stdout

    def source(self, path):
        return (ROOT / path).read_bytes()

    def baseline_dependency_inputs(self):
        listing = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", BASELINE],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
        return generate_dependencies.select_dependency_inputs(
            Path(path) for path in listing
        )

    def current_dependency_inputs(self):
        return [
            path.relative_to(ROOT)
            for path in generate_dependencies.dependency_inputs(ROOT)
        ]

    def dependency_sources(self, paths, baseline):
        return {
            path: (
                self.baseline(path).decode()
                if baseline
                else self.source(path).decode()
            )
            for path in paths
        }

    def coordinate_records(self, sources):
        by_path = {}
        for path, text in sources.items():
            records = []
            for kind, tokens in generate_dependencies.declaration_records(
                text, path
            ):
                name = tokens[0]
                repository = generate_dependencies.value_after(
                    tokens, "GIT_REPOSITORY"
                )
                tag = generate_dependencies.value_after(tokens, "GIT_TAG")
                url = generate_dependencies.value_after(tokens, "URL")
                url_hash = generate_dependencies.value_after(tokens, "URL_HASH")
                if repository or tag:
                    record = (kind, name, "git", repository, tag)
                else:
                    record = (kind, name, "archive", url, url_hash)
                records.append(record)
            by_path[path] = Counter(records)
        return by_path

    def call_tokens(self, source, command):
        pattern = re.compile(rf"{re.escape(command)}\s*\(")
        matches = list(pattern.finditer(source))
        self.assertEqual(len(matches), 1)
        start = matches[0].end()
        depth = 1
        index = start
        quoted = False
        while index < len(source) and depth:
            character = source[index]
            if character == '"':
                quoted = not quoted
            elif not quoted and character == "(":
                depth += 1
            elif not quoted and character == ")":
                depth -= 1
            index += 1
        self.assertEqual(depth, 0)
        return tuple(
            re.findall(r'"[^"]*"|[^\s]+', source[start:index - 1])
        )

    def test_targets_authority_is_byte_identical(self):
        self.assertEqual(self.source(TARGETS), self.baseline(TARGETS))

    def test_target_ids_are_unchanged(self):
        values = []
        for source in (self.baseline(AUTHORITY), self.source(AUTHORITY)):
            match = TARGET_IDS.search(source.decode())
            self.assertIsNotNone(match)
            values.append(ast.literal_eval(match.group(1)))
        self.assertEqual(values[0], values[1])

    def project_value(self, source):
        projects = PROJECT.findall(source.decode())
        self.assertEqual(len(projects), 1)
        return projects[0]

    def test_all_dependency_coordinates_and_rust_wiring_are_unchanged(self):
        baseline_inputs = self.baseline_dependency_inputs()
        current_inputs = self.current_dependency_inputs()
        baseline_sources = self.dependency_sources(baseline_inputs, True)
        current_sources = self.dependency_sources(current_inputs, False)
        all_inputs = set(baseline_inputs) | set(current_inputs)
        baseline_by_path = self.coordinate_records(baseline_sources)
        current_by_path = self.coordinate_records(current_sources)
        baseline_complete = {
            path: baseline_by_path.get(path, Counter()) for path in all_inputs
        }
        current_complete = {
            path: current_by_path.get(path, Counter()) for path in all_inputs
        }
        with self.subTest(comparison="input inventory"):
            self.assertEqual(current_inputs, baseline_inputs)
        with self.subTest(comparison="coordinates by path"):
            self.assertEqual(current_complete, baseline_complete)
        with self.subTest(comparison="global coordinate multiset"):
            baseline_global = sum(baseline_complete.values(), Counter())
            current_global = sum(current_complete.values(), Counter())
            self.assertEqual(current_global, baseline_global)

        for path in (SDK_CMAKE, CLI_CMAKE):
            with self.subTest(path=path):
                self.assertEqual(
                    self.project_value(self.source(path)),
                    self.project_value(self.baseline(path)),
                )

        baseline_sdk = baseline_sources[SDK_CMAKE]
        current_sdk = current_sources[SDK_CMAKE]
        self.assertEqual(
            self.call_tokens(current_sdk, "corrosion_import_crate"),
            self.call_tokens(baseline_sdk, "corrosion_import_crate"),
        )
        self.assertEqual(
            self.call_tokens(current_sdk, "corrosion_import_crate"),
            (
                "MANIFEST_PATH",
                '"${regorus_SOURCE_DIR}/bindings/ffi/Cargo.toml"',
                "PROFILE",
                '"release"',
                "CRATES",
                "regorus-ffi",
                "FEATURES",
                '"regorus/semver"',
                "CRATE_TYPES",
                '"staticlib"',
            ),
        )

        regorus = [
            record
            for record in current_complete[SDK_CMAKE]
            if record[1].lower() == "regorus"
        ]
        self.assertEqual(
            regorus,
            [
                (
                    "FetchContent_Declare",
                    "regorus",
                    "git",
                    "https://github.com/microsoft/regorus.git",
                    "regorus-v0.4.0",
                )
            ],
        )

    def test_release_version_matches_baseline_sdk_version(self):
        _, version = self.project_value(self.baseline(SDK_CMAKE))
        expected = f"{version}-sol.{authority.load().release['sol_revision']}"
        self.assertEqual(
            set_validator.release_version(ROOT, authority.load()), expected
        )

    def test_header_boundary_helper_declares_no_dependency_coordinates(self):
        source = self.source(HEADER_BOUNDARY).decode()
        for token in (
            "FetchContent_Declare",
            "ExternalProject_Add",
            "GIT_REPOSITORY",
            "GIT_TAG",
            "URL",
            "URL_HASH",
        ):
            with self.subTest(token=token):
                self.assertNotIn(token, source)

    def test_apple_link_closure_helper_declares_no_dependency_coordinates(self):
        source = self.source(APPLE_LINK_CLOSURE).decode()
        for token in (
            "FetchContent_Declare",
            "ExternalProject_Add",
            "GIT_REPOSITORY",
            "GIT_TAG",
            "URL",
            "URL_HASH",
        ):
            with self.subTest(token=token):
                self.assertNotIn(token, source)

    def test_rust_and_licensing_inventory_is_unchanged(self):
        baseline_listing = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", BASELINE],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
        current_listing = subprocess.run(
            ["git", "ls-files"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
        baseline_rust = tuple(
            line
            for line in baseline_listing
            if line.startswith("nv-attestation-sdk-rust/")
            if Path(line).name in {"Cargo.toml", "Cargo.lock", "build.rs"}
        )
        current_rust = tuple(
            line
            for line in current_listing
            if line.startswith("nv-attestation-sdk-rust/")
            if Path(line).name in {"Cargo.toml", "Cargo.lock", "build.rs"}
        )
        self.assertEqual(baseline_rust, RUST_INVENTORY)
        self.assertEqual(current_rust, RUST_INVENTORY)
        baseline_locks = tuple(
            line for line in baseline_listing if Path(line).name == "Cargo.lock"
        )
        current_locks = tuple(
            line for line in current_listing if Path(line).name == "Cargo.lock"
        )
        self.assertEqual(baseline_locks, ())
        self.assertEqual(current_locks, ())
        working_locks = tuple(
            sorted(
                path.relative_to(ROOT).as_posix()
                for path in ROOT.rglob("Cargo.lock")
                if ".git" not in path.relative_to(ROOT).parts
            )
        )
        untracked_locks = tuple(
            path for path in working_locks if path not in set(current_locks)
        )
        self.assertEqual(untracked_locks, ())
        self.assertEqual(working_locks, current_locks)

        self.assertEqual(self.source(LICENSE), self.baseline(LICENSE))
        baseline_inputs = self.baseline_dependency_inputs()
        baseline_sources = self.dependency_sources(baseline_inputs, True)
        with tempfile.TemporaryDirectory() as directory:
            baseline_root = Path(directory)
            for path, source in baseline_sources.items():
                destination = baseline_root / path
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(source, encoding="utf-8")
            baseline_dependencies = generate_dependencies.parse(baseline_root)
        current_dependencies = generate_dependencies.parse(ROOT)
        baseline_runtime = [
            dependency
            for dependency in baseline_dependencies
            if dependency["classification"] == "runtime"
        ]
        current_runtime = [
            dependency
            for dependency in current_dependencies
            if dependency["classification"] == "runtime"
        ]
        self.assertEqual(current_runtime, baseline_runtime)
        self.assertEqual(
            generate_dependencies.notices(current_dependencies).encode(),
            generate_dependencies.notices(baseline_dependencies).encode(),
        )

    def test_compiled_warning_exemption_is_byte_identical(self):
        function_pattern = re.compile(
            rb"^function\(nvat_exempt_compiled_third_party\b.*?"
            rb"^endfunction\(\)$",
            re.MULTILINE | re.DOTALL,
        )
        call_pattern = re.compile(
            rb"^nvat_exempt_compiled_third_party\([^\r\n]*\)$",
            re.MULTILINE,
        )
        current_source = self.source(SDK_CMAKE)
        baseline_source = self.baseline(SDK_CMAKE)
        current = (
            function_pattern.findall(current_source),
            call_pattern.findall(current_source),
        )
        baseline = (
            function_pattern.findall(baseline_source),
            call_pattern.findall(baseline_source),
        )
        self.assertEqual(tuple(map(len, current)), (1, 2))
        self.assertEqual(current, baseline)


if __name__ == "__main__":
    unittest.main()
