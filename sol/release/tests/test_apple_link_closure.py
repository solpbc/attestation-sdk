import os
import re
import shlex
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from cmake_support import (
    install_configured_nvat,
    installed_header_fixture_prepare,
    load_codemodel,
    production_configure,
    warning_fixture_prepare,
    write_package_config_stubs,
)


RELEASE_DIR = Path(__file__).resolve().parents[1]
ROOT = RELEASE_DIR.parents[1]
SDK_CMAKE = ROOT / "nv-attestation-sdk-cpp/CMakeLists.txt"
CLI_CMAKE = ROOT / "nv-attestation-cli/CMakeLists.txt"
HELPER = (
    ROOT
    / "nv-attestation-sdk-cpp/cmake/nvat_apple_system_link_closure.cmake"
)
CORROSION_SDK_LINK_DIRECTORY = (
    "/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/usr/lib"
)
PACKAGE_DEPENDENCIES = ("CURL", "LibXml2", "OpenSSL", "spdlog", "xmlsec")
POISON_ENVIRONMENT_KEYS = (
    "CMAKE_FIND_ROOT_PATH",
    "CMAKE_FRAMEWORK_PATH",
    "CMAKE_LIBRARY_PATH",
    "CMAKE_PREFIX_PATH",
    "CMAKE_SYSTEM_PREFIX_PATH",
    "HOMEBREW_CELLAR",
    "HOMEBREW_PREFIX",
    "LDFLAGS",
    "LIBRARY_PATH",
)


def normalized_output(value):
    return re.sub(r"\s+", " ", value).strip()


def sanitized_environment():
    return {
        key: value
        for key, value in os.environ.items()
        if key not in POISON_ENVIRONMENT_KEYS
    }


def extracted_apple_call():
    source = SDK_CMAKE.read_text(encoding="utf-8")
    matches = re.findall(
        r"^if\(APPLE\)\n"
        r"  nvat_configure_apple_system_link_closure\(\)\n"
        r"endif\(\)$",
        source,
        re.MULTILINE,
    )
    if len(matches) != 1:
        raise AssertionError(
            f"expected one production Apple link-closure call, found {len(matches)}"
        )
    return matches[0]


def library_fragments(target):
    return [
        entry["fragment"]
        for entry in target.get("link", {}).get("commandFragments", [])
        if entry.get("role") == "libraries"
    ]


def all_link_fragments(target):
    return [
        entry["fragment"]
        for entry in target.get("link", {}).get("commandFragments", [])
    ]


def normalized_library_fragments(target):
    values = []
    for value in library_fragments(target):
        if value.startswith("-Wl,-rpath,") and "nv-attestation-sdk-build:" in value:
            values.append("-Wl,-rpath,<nv-attestation-sdk-build>:")
            continue
        if value.startswith("-"):
            values.append(value)
        else:
            values.append(Path(value).name)
    return values


def read_properties(path):
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if not separator:
            raise AssertionError(f"malformed property record: {line}")
        values[key] = value
    return values


class ReducedAppleFixture:
    def __init__(
        self,
        root,
        *,
        iconv=True,
        corefoundation=True,
        apple=True,
        before_call="",
        environment=None,
        direct_call=False,
    ):
        self.root = Path(root)
        self.source = self.root / "source"
        self.build = self.root / "build"
        self.sdk = self.root / "MacOSX.sdk"
        self.properties = self.build / "closure-properties.txt"
        self.environment = environment
        self.source.mkdir(parents=True)
        (self.sdk / "usr/lib").mkdir(parents=True)
        frameworks = self.sdk / "System/Library/Frameworks"
        frameworks.mkdir(parents=True)
        if iconv:
            (self.sdk / "usr/lib/libiconv.tbd").write_text(
                "fake selected-SDK iconv\n", encoding="utf-8"
            )
        if corefoundation:
            (frameworks / "CoreFoundation.framework").mkdir()
        for name in ("libregorus_ffi.a", "libxml2.a", "libxmlsec1.a"):
            (self.root / name).touch()
        (self.source / "nvat.cpp").write_text(
            "int nvat_fixture() { return 0; }\n", encoding="utf-8"
        )
        (self.source / "main.cpp").write_text(
            "int main() { return 0; }\n", encoding="utf-8"
        )
        call = (
            re.search(
                r"^  (nvat_configure_apple_system_link_closure\(\))$",
                extracted_apple_call(),
                re.MULTILINE,
            ).group(1)
            if direct_call
            else extracted_apple_call()
        )
        apple_value = "TRUE" if apple else "FALSE"
        (self.source / "CMakeLists.txt").write_text(
            "cmake_minimum_required(VERSION 3.11)\n"
            "project(apple_link_closure_fixture LANGUAGES CXX)\n"
            'message(STATUS "ENGINE=${CMAKE_VERSION}")\n'
            f'set(APPLE {apple_value})\n'
            "# Test-side shims for Darwin library/framework search/link behavior.\n"
            'set(CMAKE_FIND_LIBRARY_SUFFIXES ".tbd;.dylib;.so;.a")\n'
            "set(CMAKE_FIND_FRAMEWORK FIRST)\n"
            'set(CMAKE_CXX_LINK_LIBRARY_USING_FRAMEWORK "-framework <LIBRARY>")\n'
            "set(CMAKE_CXX_LINK_LIBRARY_USING_FRAMEWORK_SUPPORTED TRUE)\n"
            f'set(NVAT_APPLE_SDKROOT "{self.sdk.as_posix()}")\n'
            f'include("{HELPER.as_posix()}")\n'
            "add_library(regorus_ffi INTERFACE)\n"
            "add_library(regorus_ffi-static STATIC IMPORTED GLOBAL)\n"
            "set_target_properties(regorus_ffi-static PROPERTIES\n"
            f'  IMPORTED_LOCATION "{(self.root / "libregorus_ffi.a").as_posix()}"\n'
            "  INTERFACE_LINK_DIRECTORIES "
            f'"{CORROSION_SDK_LINK_DIRECTORY}"\n'
            ")\n"
            "target_link_libraries(regorus_ffi INTERFACE regorus_ffi-static)\n"
            "add_library(LibXml2::LibXml2 STATIC IMPORTED)\n"
            "set_target_properties(LibXml2::LibXml2 PROPERTIES\n"
            f'  IMPORTED_LOCATION "{(self.root / "libxml2.a").as_posix()}"\n'
            ")\n"
            "add_library(xmlsec::xmlsec STATIC IMPORTED)\n"
            "set_target_properties(xmlsec::xmlsec PROPERTIES\n"
            f'  IMPORTED_LOCATION "{(self.root / "libxmlsec1.a").as_posix()}"\n'
            '  INTERFACE_LINK_LIBRARIES "LibXml2::LibXml2"\n'
            ")\n"
            f"{before_call}"
            f"{call}\n"
            "get_target_property(_regorus regorus_ffi INTERFACE_LINK_LIBRARIES)\n"
            "get_target_property(_regorus_static_location regorus_ffi-static "
            "IMPORTED_LOCATION)\n"
            "get_target_property(_regorus_directories regorus_ffi "
            "INTERFACE_LINK_DIRECTORIES)\n"
            "get_target_property(_regorus_static_directories regorus_ffi-static "
            "INTERFACE_LINK_DIRECTORIES)\n"
            "get_target_property(_regorus_type regorus_ffi TYPE)\n"
            "get_target_property(_regorus_static_type regorus_ffi-static TYPE)\n"
            "get_target_property(_libxml LibXml2::LibXml2 "
            "INTERFACE_LINK_LIBRARIES)\n"
            "get_target_property(_xmlsec xmlsec::xmlsec "
            "INTERFACE_LINK_LIBRARIES)\n"
            "get_target_property(_iconv Iconv::Iconv IMPORTED_LOCATION)\n"
            f'file(WRITE "{self.properties.as_posix()}"\n'
            '  "REGORUS=${_regorus}\\n'
            'REGORUS_STATIC_LOCATION=${_regorus_static_location}\\n'
            'REGORUS_DIRECTORIES=${_regorus_directories}\\n'
            'REGORUS_STATIC_DIRECTORIES=${_regorus_static_directories}\\n'
            'REGORUS_TYPE=${_regorus_type}\\n'
            'REGORUS_STATIC_TYPE=${_regorus_static_type}\\n'
            'LIBXML=${_libxml}\\n'
            'XMLSEC=${_xmlsec}\\nICONV=${_iconv}\\n")\n'
            "add_library(nvat SHARED nvat.cpp)\n"
            "target_link_libraries(nvat PRIVATE\n"
            "  xmlsec::xmlsec\n"
            "  LibXml2::LibXml2\n"
            "  regorus_ffi\n"
            ")\n"
            "add_executable(nvattest main.cpp)\n"
            "target_link_libraries(nvattest PRIVATE nvat)\n",
            encoding="utf-8",
        )

    def configure(self, cmake="cmake", query_codemodel=False, arguments=()):
        if query_codemodel:
            query = self.build / ".cmake/api/v1/query"
            query.mkdir(parents=True)
            (query / "codemodel-v2").touch()
        if cmake == "cmake":
            command = [
                cmake,
                "-S",
                str(self.source),
                "-B",
                str(self.build),
                *arguments,
            ]
            cwd = ROOT
        else:
            self.build.mkdir(exist_ok=True)
            command = [cmake, str(self.source), *arguments]
            cwd = self.build
        return subprocess.run(
            command,
            cwd=cwd,
            text=True,
            capture_output=True,
            check=False,
            env=self.environment,
        )


class AppleLinkClosureTest(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls):
        (
            cls.production_temporary,
            cls.production_completed,
            _event_log,
            cls.production_records,
            cls.production_build,
        ) = production_configure(
            ROOT / "nv-attestation-cli",
            fixture_prepare=warning_fixture_prepare(),
            query_codemodel=True,
        )
        if cls.production_completed.returncode == 0:
            _codemodel, cls.production_targets = load_codemodel(
                cls.production_build
            )
        else:
            cls.production_targets = {}

    @classmethod
    def tearDownClass(cls):
        cls.production_temporary.cleanup()

    def assert_production_configured(self):
        self.assertEqual(
            self.production_completed.returncode,
            0,
            self.production_completed.stderr,
        )

    def assert_known_directory_absent(self, fixture, targets):
        links = {
            name: (
                fixture.build / f"CMakeFiles/{name}.dir/link.txt"
            ).read_text(encoding="utf-8")
            for name in ("nvat", "nvattest")
        }
        fragments = {
            name: {
                "libraries": library_fragments(targets[name]),
                "all": all_link_fragments(targets[name]),
            }
            for name in ("nvat", "nvattest")
        }
        self.assertNotIn(
            f"-L{CORROSION_SDK_LINK_DIRECTORY}",
            fragments["nvat"]["all"],
        )
        for name in ("nvat", "nvattest"):
            for surface in (
                fragments[name]["libraries"],
                fragments[name]["all"],
            ):
                for fragment in surface:
                    self.assertNotIn(
                        CORROSION_SDK_LINK_DIRECTORY,
                        fragment,
                    )
            self.assertNotIn(CORROSION_SDK_LINK_DIRECTORY, links[name])
        self.assertEqual(
            fragments["nvattest"]["libraries"],
            [
                f"-Wl,-rpath,{fixture.build.as_posix()}",
                "libnvat.so",
            ],
        )
        return links, fragments

    def test_production_has_one_guarded_call_and_one_edge_truth_source(self):
        call = extracted_apple_call()
        self.assertIn("nvat_configure_apple_system_link_closure()", call)
        sdk_source = SDK_CMAKE.read_text(encoding="utf-8")
        self.assertEqual(
            sdk_source.count(
                'include("${CMAKE_CURRENT_LIST_DIR}/cmake/'
                'nvat_apple_system_link_closure.cmake")'
            ),
            1,
        )
        helper = HELPER.read_text(encoding="utf-8")
        self.assertEqual(
            len(
                re.findall(
                    r"^function\(nvat_configure_apple_system_link_closure\)$",
                    helper,
                    re.MULTILINE,
                )
            ),
            1,
        )
        property_calls = re.findall(
            r"set_property\(TARGET ([^\s]+) APPEND PROPERTY\s+"
            r"INTERFACE_LINK_LIBRARIES ([^)]+)\)",
            helper,
            re.MULTILINE,
        )
        self.assertEqual(len(property_calls), 2)
        self.assertEqual(helper.count(CORROSION_SDK_LINK_DIRECTORY), 1)
        self.assertRegex(
            helper,
            r"set\(\s+_nvat_apple_rust_owner_targets\s+"
            r"regorus_ffi\s+regorus_ffi-static\s+\)",
        )
        self.assertEqual(helper.count("get_target_property("), 1)
        self.assertEqual(
            len(
                re.findall(
                    r"set_property\(\s+TARGET "
                    r'"\$\{_nvat_apple_rust_owner_target\}"\s+'
                    r'PROPERTY INTERFACE_LINK_DIRECTORIES ""\s+\)',
                    helper,
                )
            ),
            1,
        )
        self.assertEqual(
            helper.count(
                "if(NOT _nvat_apple_rust_link_directory STREQUAL\n"
                "           _nvat_apple_corrosion_sdk_link_directory)"
            ),
            1,
        )
        property_read = helper.index("get_target_property(")
        recognizer = helper.index(
            "if(NOT _nvat_apple_rust_link_directory STREQUAL"
        )
        corefoundation_validation = helper.index(
            "if(NOT _nvat_apple_corefoundation_inside_sdk EQUAL 0)"
        )
        directory_clear = helper.index(
            'PROPERTY INTERFACE_LINK_DIRECTORIES ""'
        )
        first_graph_mutation = helper.index(
            "add_library(Iconv::Iconv UNKNOWN IMPORTED)"
        )
        self.assertLess(property_read, recognizer)
        self.assertLess(recognizer, corefoundation_validation)
        self.assertLess(corefoundation_validation, directory_clear)
        self.assertLess(directory_clear, first_graph_mutation)
        link_block = re.search(
            r"^target_link_libraries\(nvat\n.*?^\)$",
            sdk_source,
            re.MULTILINE | re.DOTALL,
        ).group(0)
        self.assertIn("LibXml2::LibXml2", link_block)
        self.assertIn("regorus_ffi", link_block)
        self.assertNotIn("CoreFoundation", link_block)
        self.assertNotIn("Iconv::Iconv", link_block)
        self.assertNotIn("CoreFoundation", CLI_CMAKE.read_text(encoding="utf-8"))
        self.assertNotIn("Iconv::Iconv", CLI_CMAKE.read_text(encoding="utf-8"))

    def test_reduced_apple_fixture_orders_each_owner_edge_once(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = ReducedAppleFixture(directory)
            completed = fixture.configure(query_codemodel=True)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            properties = read_properties(fixture.properties)
            _codemodel, targets = load_codemodel(fixture.build)
            nvat = library_fragments(targets["nvat"])
            links, fragments = self.assert_known_directory_absent(
                fixture, targets
            )
            nvattest_all = fragments["nvattest"]["all"]
            regorus_interface = properties["REGORUS"].split(";")
            self.assertEqual(regorus_interface[0], "regorus_ffi-static")
            self.assertEqual(len(regorus_interface), 2)
            corefoundation = regorus_interface[1]
            iconv_target = properties["LIBXML"]
            iconv_path = properties["ICONV"]
            regorus_path = properties["REGORUS_STATIC_LOCATION"]
            self.assertEqual(Path(regorus_path), fixture.root / "libregorus_ffi.a")
            self.assertEqual(properties["REGORUS_DIRECTORIES"], "")
            self.assertEqual(properties["REGORUS_STATIC_DIRECTORIES"], "")
            self.assertEqual(properties["REGORUS_TYPE"], "INTERFACE_LIBRARY")
            self.assertEqual(properties["REGORUS_STATIC_TYPE"], "STATIC_LIBRARY")
            self.assertEqual(iconv_target, "Iconv::Iconv")
            self.assertEqual(properties["XMLSEC"], "LibXml2::LibXml2")
            self.assertEqual(Path(iconv_path), fixture.sdk / "usr/lib/libiconv.tbd")
            core_indices = [
                index
                for index, value in enumerate(nvat)
                if "CoreFoundation" in value
            ]
            iconv_indices = [
                index for index, value in enumerate(nvat) if value == iconv_path
            ]
            regorus_indices = [
                index
                for index, value in enumerate(nvat)
                if Path(value).name == "libregorus_ffi.a"
            ]
            libxml_indices = [
                index
                for index, value in enumerate(nvat)
                if Path(value).name == "libxml2.a"
            ]
            self.assertEqual(len(core_indices), 1, nvat)
            self.assertEqual(len(iconv_indices), 1, nvat)
            self.assertEqual(len(regorus_indices), 1, nvat)
            self.assertGreaterEqual(len(libxml_indices), 1, nvat)
            self.assertGreater(core_indices[0], regorus_indices[-1])
            self.assertGreater(iconv_indices[0], libxml_indices[-1])
            for marker in (
                Path(regorus_path).name,
                Path(iconv_path).name,
                "CoreFoundation",
            ):
                self.assertFalse(
                    any(marker in fragment for fragment in nvattest_all),
                    nvattest_all,
                )
            nvat_link = links["nvat"]
            nvattest_link = links["nvattest"]
            self.assertIn(iconv_path, nvat_link)
            self.assertIn("CoreFoundation", nvat_link)
            self.assertNotIn(iconv_path, nvattest_link)
            self.assertNotIn("CoreFoundation", nvattest_link)
            self.assertNotIn(Path(regorus_path).name, nvattest_link)

    def test_known_link_directory_on_facade_is_cleared(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = ReducedAppleFixture(
                directory,
                before_call=(
                    "set_property(TARGET regorus_ffi PROPERTY "
                    "INTERFACE_LINK_DIRECTORIES "
                    f'"{CORROSION_SDK_LINK_DIRECTORY}")\n'
                ),
            )
            completed = fixture.configure(query_codemodel=True)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            properties = read_properties(fixture.properties)
            self.assertEqual(properties["REGORUS_DIRECTORIES"], "")
            self.assertEqual(properties["REGORUS_STATIC_DIRECTORIES"], "")
            _codemodel, targets = load_codemodel(fixture.build)
            self.assert_known_directory_absent(fixture, targets)

    def test_unknown_and_malformed_link_directories_fail_closed(self):
        known = CORROSION_SDK_LINK_DIRECTORY
        cases = (
            ("arbitrary", "/opt/homebrew/lib", "/opt/homebrew/lib"),
            (
                "unrecognized SDK",
                "/Applications/Xcode.app/SDKs/Other.sdk/usr/lib",
                "/Applications/Xcode.app/SDKs/Other.sdk/usr/lib",
            ),
            ("leading empty", f";{known}", ""),
            ("trailing empty", f"{known};", ""),
            ("doubled separator", f"{known};;{known}", ""),
            ("relative", "relative/lib", "relative/lib"),
            (
                "embedded semicolon",
                r"/tmp/embedded\;entry",
                "/tmp/embedded;entry",
            ),
            (
                "mixed known and unknown",
                f"{known};/usr/local/lib",
                "/usr/local/lib",
            ),
        )
        for target in ("regorus_ffi", "regorus_ffi-static"):
            for name, value, offending in cases:
                with self.subTest(target=target, case=name):
                    temporary = tempfile.TemporaryDirectory()
                    with temporary:
                        fixture = ReducedAppleFixture(
                            temporary.name,
                            before_call=(
                                f"set_property(TARGET {target} PROPERTY "
                                "INTERFACE_LINK_DIRECTORIES "
                                f'"{value}")\n'
                            ),
                        )
                        completed = fixture.configure()
                        self.assert_exact_diagnostic(
                            completed,
                            "Darwin/arm64 Rust link-directory closure failed: "
                            f"target '{target}' has unsupported "
                            "INTERFACE_LINK_DIRECTORIES entry "
                            f"'{offending}'; remove the unexpected "
                            "link-directory entry and configure from a clean "
                            "build directory, then retry",
                        )

    def test_empty_and_unset_link_directories_are_verified_and_safe(self):
        cases = (
            (
                "empty",
                'set_property(TARGET {target} PROPERTY '
                'INTERFACE_LINK_DIRECTORIES "")\n',
            ),
            (
                "unset",
                "set_property(TARGET {target} PROPERTY "
                "INTERFACE_LINK_DIRECTORIES)\n",
            ),
        )
        for target in ("regorus_ffi", "regorus_ffi-static"):
            for name, command in cases:
                with self.subTest(target=target, state=name):
                    with tempfile.TemporaryDirectory() as directory:
                        fixture = ReducedAppleFixture(
                            directory,
                            before_call=command.format(target=target),
                        )
                        completed = fixture.configure(query_codemodel=True)
                        self.assertEqual(
                            completed.returncode,
                            0,
                            completed.stderr,
                        )
                        properties = read_properties(fixture.properties)
                        self.assertEqual(
                            properties["REGORUS_DIRECTORIES"], ""
                        )
                        self.assertEqual(
                            properties["REGORUS_STATIC_DIRECTORIES"], ""
                        )
                        self.assertEqual(
                            properties["REGORUS_TYPE"],
                            "INTERFACE_LIBRARY",
                        )
                        self.assertEqual(
                            properties["REGORUS_STATIC_TYPE"],
                            "STATIC_LIBRARY",
                        )
                        self.assertEqual(
                            properties["LIBXML"],
                            "Iconv::Iconv",
                        )
                        regorus = properties["REGORUS"].split(";")
                        self.assertEqual(regorus[0], "regorus_ffi-static")
                        self.assertEqual(len(regorus), 2)
                        _codemodel, targets = load_codemodel(fixture.build)
                        links, _fragments = (
                            self.assert_known_directory_absent(
                                fixture, targets
                            )
                        )
                        self.assertIn(properties["ICONV"], links["nvat"])
                        self.assertIn("CoreFoundation", links["nvat"])

    def test_linux_production_link_vectors_are_unchanged(self):
        self.assert_production_configured()
        calls = [
            record
            for record in self.production_records
            if record.get("cmd") == "nvat_configure_apple_system_link_closure"
        ]
        self.assertEqual(calls, [])
        nvat = self.production_targets["nvat"]
        nvattest = self.production_targets["nvattest"]
        self.assertEqual(
            normalized_library_fragments(nvat),
            [
                "libxmlsec1.a",
                "libxmlsec1-openssl.a",
                "libssl.a",
                "libcrypto.a",
                "libcurl.a",
                "libxml2.a",
                "libz.so",
                "libspdlog.a",
                "libfmt.a",
                "libregorus_ffi.a",
                "libxmlsec1.a",
                "libxml2.a",
                "libssl.a",
                "libcrypto.a",
                "-ldl",
                "-lz",
                "-lpthread",
            ],
        )
        self.assertEqual(
            normalized_library_fragments(nvattest),
            [
                "-Wl,-rpath,<nv-attestation-sdk-build>:",
                "libnvat.so.1.2.2",
            ],
        )
        for path in (
            self.production_build
            / "nv-attestation-sdk-build/CMakeFiles/nvat.dir/link.txt",
            self.production_build / "CMakeFiles/nvattest.dir/link.txt",
        ):
            link = path.read_text(encoding="utf-8")
            self.assertNotIn("CoreFoundation", link)
            self.assertNotIn("Iconv", link)
            self.assertNotIn("libiconv", link)

    def test_linux_production_environment_poison_is_inert(self):
        self.assert_production_configured()
        with tempfile.TemporaryDirectory() as directory:
            modeled = Path(directory) / "modeled"
            homebrew = modeled / "opt/homebrew"
            intel = modeled / "usr/local"
            (homebrew / "lib").mkdir(parents=True)
            (homebrew / "Frameworks").mkdir()
            (intel / "lib").mkdir(parents=True)
            (homebrew / "lib/libiconv.tbd").write_text(
                "poison\n", encoding="utf-8"
            )
            (homebrew / "Frameworks/CoreFoundation.framework").mkdir()
            environment = sanitized_environment()
            environment.update(
                {
                    "CMAKE_PREFIX_PATH": str(homebrew),
                    "LDFLAGS": (
                        f"-L{homebrew / 'lib'} "
                        f"-F{homebrew / 'Frameworks'}"
                    ),
                    "LIBRARY_PATH": str(intel / "lib"),
                }
            )
            (
                temporary,
                completed,
                _event_log,
                records,
                build,
            ) = production_configure(
                ROOT / "nv-attestation-cli",
                fixture_prepare=warning_fixture_prepare(),
                query_codemodel=True,
                env=environment,
            )
            with temporary:
                self.assertEqual(completed.returncode, 0, completed.stderr)
                calls = [
                    record
                    for record in records
                    if record.get("cmd")
                    == "nvat_configure_apple_system_link_closure"
                ]
                self.assertEqual(calls, [])
                _codemodel, targets = load_codemodel(build)
                for name in ("nvat", "nvattest"):
                    with self.subTest(target=name):
                        self.assertEqual(
                            normalized_library_fragments(targets[name]),
                            normalized_library_fragments(
                                self.production_targets[name]
                            ),
                        )
                for path in (
                    build
                    / "nv-attestation-sdk-build/CMakeFiles/nvat.dir/link.txt",
                    build / "CMakeFiles/nvattest.dir/link.txt",
                ):
                    link = path.read_text(encoding="utf-8")
                    self.assertNotIn("CoreFoundation", link)
                    self.assertNotIn("Iconv", link)
                    self.assertNotIn("libiconv", link)

    def configure_failure(
        self,
        *,
        iconv=True,
        corefoundation=True,
        apple=True,
        before_call="",
        direct_call=False,
        arguments=(),
    ):
        temporary = tempfile.TemporaryDirectory()
        fixture = ReducedAppleFixture(
            temporary.name,
            iconv=iconv,
            corefoundation=corefoundation,
            apple=apple,
            before_call=before_call,
            direct_call=direct_call,
        )
        completed = fixture.configure(arguments=arguments)
        return temporary, fixture, completed

    def assert_exact_diagnostic(self, completed, diagnostic):
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn(normalized_output(diagnostic), normalized_output(completed.stderr))

    def test_helper_fails_closed_for_platform_sdk_target_and_artifact_errors(self):
        cases = (
            (
                "off Darwin",
                dict(apple=False, direct_call=True),
                "Darwin/arm64 system-link closure failed: helper reached while "
                "APPLE is false; call it only from the post-project Apple-guarded "
                "SDK path, then retry",
            ),
            (
                "missing iconv",
                dict(iconv=False),
                None,
            ),
            (
                "missing CoreFoundation",
                dict(corefoundation=False),
                None,
            ),
        )
        for name, options, diagnostic in cases:
            with self.subTest(name=name):
                temporary, fixture, completed = self.configure_failure(**options)
                with temporary:
                    if name == "missing iconv":
                        diagnostic = (
                            "Darwin/arm64 iconv discovery failed: libiconv.tbd "
                            f"was not found in selected SDK '{fixture.sdk}/usr/lib'; "
                            "select a macOS SDK containing usr/lib/libiconv.tbd "
                            "and remove the build directory, then retry"
                        )
                    elif name == "missing CoreFoundation":
                        diagnostic = (
                            "Darwin/arm64 CoreFoundation discovery failed: "
                            "CoreFoundation.framework was not found in selected "
                            f"SDK '{fixture.sdk}/System/Library/Frameworks'; "
                            "select a macOS SDK containing "
                            "System/Library/Frameworks/CoreFoundation.framework "
                            "and remove the build directory, then retry"
                        )
                    self.assert_exact_diagnostic(completed, diagnostic)

        for target in ("regorus_ffi", "regorus_ffi-static"):
            with self.subTest(missing_target=target):
                with tempfile.TemporaryDirectory() as directory:
                    fixture = ReducedAppleFixture(directory)
                    source_path = fixture.source / "CMakeLists.txt"
                    source = source_path.read_text(encoding="utf-8")
                    if target == "regorus_ffi":
                        source = source.replace(
                            "add_library(regorus_ffi INTERFACE)\n",
                            "",
                            1,
                        )
                    else:
                        source = re.sub(
                            r"add_library\(regorus_ffi-static STATIC IMPORTED "
                            r"GLOBAL\)\n"
                            r"set_target_properties\(regorus_ffi-static "
                            r"PROPERTIES\n.*?^\)\n",
                            "",
                            source,
                            count=1,
                            flags=re.MULTILINE | re.DOTALL,
                        )
                    source = source.replace(
                        "target_link_libraries(regorus_ffi INTERFACE "
                        "regorus_ffi-static)\n",
                        "",
                        1,
                    )
                    source_path.write_text(source, encoding="utf-8")
                    completed = fixture.configure()
                    self.assert_exact_diagnostic(
                        completed,
                        "Darwin/arm64 Rust link-directory closure failed: "
                        f"required owner-chain target '{target}' does not "
                        "exist; recreate the pinned Corrosion regorus_ffi "
                        "staticlib targets in a clean build directory, then "
                        "retry",
                    )

        with tempfile.TemporaryDirectory() as directory:
            fixture = ReducedAppleFixture(directory)
            source = (fixture.source / "CMakeLists.txt").read_text(encoding="utf-8")
            source = re.sub(
                r"add_library\(LibXml2::LibXml2 STATIC IMPORTED\).*?"
                r"\)\n(?=add_library\(xmlsec::xmlsec)",
                "",
                source,
                count=1,
                flags=re.DOTALL,
            )
            source = source.replace(
                '  INTERFACE_LINK_LIBRARIES "LibXml2::LibXml2"\n', ""
            )
            (fixture.source / "CMakeLists.txt").write_text(source, encoding="utf-8")
            completed = fixture.configure()
            self.assert_exact_diagnostic(
                completed,
                "Darwin/arm64 iconv closure failed: static owner target "
                "LibXml2::LibXml2 does not exist; create the selected "
                "LibXml2::LibXml2 target before the Apple closure call, then retry",
            )

        temporary, fixture, completed = self.configure_failure(
            before_call="add_library(Iconv::Iconv UNKNOWN IMPORTED)\n"
        )
        with temporary:
            self.assert_exact_diagnostic(
                completed,
                "Darwin/arm64 iconv discovery failed: target Iconv::Iconv already "
                "exists without selected-SDK validation; remove the pre-existing "
                "Iconv target and configure from a clean build directory, then retry",
            )

    def test_helper_rejects_invalid_selected_sdk_roots(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            non_directory = root / "not-a-directory"
            non_directory.write_text("not an SDK directory\n", encoding="utf-8")
            cases = (
                ("missing", "unset(NVAT_APPLE_SDKROOT)\n", ""),
                (
                    "relative",
                    'set(NVAT_APPLE_SDKROOT "relative/MacOSX.sdk")\n',
                    "relative/MacOSX.sdk",
                ),
                (
                    "non-directory",
                    f'set(NVAT_APPLE_SDKROOT "{non_directory.as_posix()}")\n',
                    str(non_directory),
                ),
            )
            for name, before_call, observation in cases:
                with self.subTest(state=name):
                    fixture = ReducedAppleFixture(
                        root / name,
                        before_call=before_call,
                    )
                    completed = fixture.configure()
                    self.assert_exact_diagnostic(
                        completed,
                        "Darwin/arm64 system-link closure failed: "
                        "NVAT_APPLE_SDKROOT is not an absolute existing "
                        f"directory: '{observation}'; select a valid macOS SDK "
                        "with xcrun and remove the build directory, then retry",
                    )

    def test_selected_sdk_discovery_rejects_each_poison_independently(self):
        rows = (
            ("opt/homebrew", "iconv", "homebrew-prefix"),
            ("usr/local", "iconv", "intel-library"),
            ("Library/Frameworks", "corefoundation", "library-framework"),
            ("host/usr/lib", "iconv", "host-library"),
            ("build/root", "iconv", "build-prefix"),
            ("cache/opt/homebrew", "iconv", "cache-iconv"),
            (
                "cache/usr/local/Library",
                "corefoundation",
                "cache-corefoundation",
            ),
            ("CMAKE_PREFIX_PATH", "iconv", "prefix"),
            ("CMAKE_LIBRARY_PATH", "iconv", "library"),
            ("CMAKE_FRAMEWORK_PATH", "corefoundation", "framework"),
            ("CMAKE_FIND_ROOT_PATH", "iconv", "find-root"),
            ("LIBRARY_PATH", "iconv", "env-library"),
            ("LDFLAGS/opt/homebrew", "iconv", "env-ldflags"),
            (
                "system-prefix/opt/homebrew",
                "iconv",
                "homebrew-system-prefix",
            ),
            (
                "system-prefix/usr/local",
                "iconv",
                "intel-system-prefix",
            ),
            (
                "normal/NVAT_APPLE_ICONV_LIBRARY",
                "iconv",
                "normal-iconv",
            ),
            (
                "normal/NVAT_APPLE_COREFOUNDATION_FRAMEWORK",
                "corefoundation",
                "normal-corefoundation",
            ),
        )

        def write_iconv(directory):
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / "libiconv.tbd"
            path.write_text("poison\n", encoding="utf-8")
            return path

        def write_corefoundation(directory):
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / "CoreFoundation.framework"
            path.mkdir()
            return path

        for label, dependency, kind in rows:
            with self.subTest(poison=label):
                temporary = tempfile.TemporaryDirectory()
                with temporary:
                    root = Path(temporary.name)
                    modeled = root / "modeled"
                    fixture_root = root / "fixture"
                    fixture_sdk = fixture_root / "MacOSX.sdk"
                    fixture_build = fixture_root / "build"
                    before_call = ""
                    arguments = []
                    environment = sanitized_environment()
                    outside_result = None

                    if kind == "homebrew-prefix":
                        prefix = modeled / "opt/homebrew"
                        write_iconv(prefix / "lib")
                        arguments.append(f"-DCMAKE_PREFIX_PATH={prefix}")
                    elif kind == "intel-library":
                        library = modeled / "usr/local/lib"
                        write_iconv(library)
                        arguments.append(f"-DCMAKE_LIBRARY_PATH={library}")
                    elif kind == "library-framework":
                        frameworks = modeled / "Library/Frameworks"
                        write_corefoundation(frameworks)
                        arguments.append(f"-DCMAKE_FRAMEWORK_PATH={frameworks}")
                    elif kind == "host-library":
                        library = modeled / "usr/lib"
                        write_iconv(library)
                        arguments.append(f"-DCMAKE_LIBRARY_PATH={library}")
                    elif kind == "build-prefix":
                        prefix = fixture_build / "host-prefix"
                        write_iconv(prefix / "lib")
                        write_corefoundation(prefix / "Frameworks")
                        arguments.append(f"-DCMAKE_PREFIX_PATH={prefix}")
                    elif kind == "cache-iconv":
                        iconv_path = write_iconv(
                            modeled / "opt/homebrew/lib"
                        )
                        arguments.append(
                            f"-DNVAT_APPLE_ICONV_LIBRARY={iconv_path}"
                        )
                    elif kind == "cache-corefoundation":
                        framework_path = write_corefoundation(
                            modeled / "usr/local/Library/Frameworks"
                        )
                        arguments.append(
                            "-DNVAT_APPLE_COREFOUNDATION_FRAMEWORK="
                            f"{framework_path}"
                        )
                    elif kind == "prefix":
                        prefix = modeled / "prefix"
                        write_iconv(prefix / "lib")
                        arguments.append(f"-DCMAKE_PREFIX_PATH={prefix}")
                    elif kind == "library":
                        library = modeled / "library"
                        write_iconv(library)
                        arguments.append(f"-DCMAKE_LIBRARY_PATH={library}")
                    elif kind == "framework":
                        frameworks = modeled / "frameworks"
                        write_corefoundation(frameworks)
                        arguments.append(
                            f"-DCMAKE_FRAMEWORK_PATH={frameworks}"
                        )
                    elif kind == "find-root":
                        find_root = modeled / "find-root"
                        mirrored_sdk = (
                            find_root
                            / fixture_sdk.as_posix().lstrip("/")
                        )
                        outside_result = write_iconv(
                            mirrored_sdk / "usr/lib"
                        )
                        before_call = (
                            "set(CMAKE_FIND_ROOT_PATH "
                            f'"{find_root.as_posix()}")\n'
                        )
                    elif kind == "env-library":
                        library = modeled / "usr/local/lib"
                        write_iconv(library)
                        environment["LIBRARY_PATH"] = str(library)
                    elif kind == "env-ldflags":
                        prefix = modeled / "opt/homebrew"
                        write_iconv(prefix / "lib")
                        write_corefoundation(prefix / "Frameworks")
                        environment["LDFLAGS"] = (
                            f"-L{prefix / 'lib'} "
                            f"-F{prefix / 'Frameworks'}"
                        )
                    elif kind == "homebrew-system-prefix":
                        prefix = modeled / "opt/homebrew"
                        write_iconv(prefix / "lib")
                        before_call = (
                            "set(CMAKE_SYSTEM_PREFIX_PATH "
                            f'"{prefix.as_posix()}")\n'
                        )
                    elif kind == "intel-system-prefix":
                        prefix = modeled / "usr/local"
                        write_iconv(prefix / "lib")
                        before_call = (
                            "set(CMAKE_SYSTEM_PREFIX_PATH "
                            f'"{prefix.as_posix()}")\n'
                        )
                    elif kind == "normal-iconv":
                        iconv_path = write_iconv(
                            modeled / "opt/homebrew/lib"
                        )
                        before_call = (
                            "set(NVAT_APPLE_ICONV_LIBRARY "
                            f'"{iconv_path.as_posix()}")\n'
                        )
                    elif kind == "normal-corefoundation":
                        framework_path = write_corefoundation(
                            modeled / "usr/local/Library/Frameworks"
                        )
                        before_call = (
                            "set(NVAT_APPLE_COREFOUNDATION_FRAMEWORK "
                            f'"{framework_path.as_posix()}")\n'
                        )
                    fixture = ReducedAppleFixture(
                        fixture_root,
                        iconv=dependency != "iconv",
                        corefoundation=dependency != "corefoundation",
                        before_call=before_call,
                        environment=environment,
                    )
                    completed = fixture.configure(arguments=arguments)
                    if outside_result is not None:
                        diagnostic = (
                            "Darwin/arm64 iconv discovery failed: resolved path "
                            f"'{outside_result.resolve()}' is outside selected "
                            f"SDK '{fixture.sdk.resolve()}'; remove host or "
                            "Homebrew cache inputs and select the macOS SDK, "
                            "then retry"
                        )
                    elif dependency == "iconv":
                        diagnostic = (
                            "Darwin/arm64 iconv discovery failed: libiconv.tbd "
                            f"was not found in selected SDK '{fixture.sdk}/usr/lib'; "
                            "select a macOS SDK containing usr/lib/libiconv.tbd "
                            "and remove the build directory, then retry"
                        )
                    else:
                        diagnostic = (
                            "Darwin/arm64 CoreFoundation discovery failed: "
                            "CoreFoundation.framework was not found in selected "
                            f"SDK '{fixture.sdk}/System/Library/Frameworks'; "
                            "select a macOS SDK containing "
                            "System/Library/Frameworks/CoreFoundation.framework "
                            "and remove the build directory, then retry"
                        )
                    self.assert_exact_diagnostic(completed, diagnostic)

    def test_iconv_target_collision_and_findiconv_inputs_fail_closed(self):
        for variable, value in (
            ("Iconv_LIBRARY", "/modeled/opt/homebrew/lib/libiconv.dylib"),
            ("Iconv_IS_BUILT_IN", "TRUE"),
        ):
            with self.subTest(variable=variable):
                temporary, fixture, completed = self.configure_failure(
                    iconv=False,
                    arguments=(f"-D{variable}={value}",),
                )
                with temporary:
                    self.assert_exact_diagnostic(
                        completed,
                        "Darwin/arm64 iconv discovery failed: libiconv.tbd was "
                        f"not found in selected SDK '{fixture.sdk}/usr/lib'; "
                        "select a macOS SDK containing usr/lib/libiconv.tbd and "
                        "remove the build directory, then retry",
                    )

    def test_selected_sdk_symlinks_cannot_escape(self):
        for dependency in ("iconv", "CoreFoundation"):
            with self.subTest(dependency=dependency):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    fixture = ReducedAppleFixture(
                        root / "fixture",
                        iconv=dependency != "iconv",
                        corefoundation=dependency != "CoreFoundation",
                    )
                    outside = root / "modeled/opt/homebrew"
                    if dependency == "iconv":
                        target = outside / "lib/libiconv.tbd"
                        target.parent.mkdir(parents=True)
                        target.write_text("poison\n", encoding="utf-8")
                        candidate = fixture.sdk / "usr/lib/libiconv.tbd"
                    else:
                        target = (
                            outside
                            / "System/Library/Frameworks/CoreFoundation.framework"
                        )
                        target.mkdir(parents=True)
                        candidate = (
                            fixture.sdk
                            / "System/Library/Frameworks/CoreFoundation.framework"
                        )
                    candidate.symlink_to(target, target_is_directory=target.is_dir())
                    completed = fixture.configure()
                    real_sdk = fixture.sdk.resolve()
                    if dependency == "iconv":
                        diagnostic = (
                            "Darwin/arm64 iconv discovery failed: resolved path "
                            f"'{target.resolve()}' is outside selected SDK "
                            f"'{real_sdk}'; remove host or Homebrew cache inputs "
                            "and select the macOS SDK, then retry"
                        )
                    else:
                        diagnostic = (
                            "Darwin/arm64 CoreFoundation discovery failed: "
                            f"resolved path '{target.resolve()}' is outside "
                            f"selected SDK '{real_sdk}'; remove host or Homebrew "
                            "cache inputs and select the macOS SDK, then retry"
                        )
                    self.assert_exact_diagnostic(completed, diagnostic)

    def test_policy_rejects_linker_escape_hatches_and_non_sdk_inputs(self):
        product_sources = {
            HELPER: HELPER.read_text(encoding="utf-8"),
            SDK_CMAKE: SDK_CMAKE.read_text(encoding="utf-8"),
            CLI_CMAKE: CLI_CMAKE.read_text(encoding="utf-8"),
        }
        product = "\n".join(product_sources.values())
        forbidden_link_tokens = (
            "-undefined dynamic_lookup",
            "-undefined;dynamic_lookup",
            "-undefined suppress",
            "-undefined;suppress",
            "-flat_namespace",
            "-Wl,-undefined",
            "-Xlinker -undefined",
            "-Xlinker;-undefined",
            "--unresolved-symbols",
            "--allow-shlib-undefined",
            "LINKER:-undefined",
            "SHELL:-undefined",
        )
        for token in (
            *forbidden_link_tokens,
            "file(GLOB",
            "file(GLOB_RECURSE",
            "-L/opt/homebrew",
            "-F/opt/homebrew",
            "-L/usr/local",
            "-F/usr/local",
        ):
            with self.subTest(token=token):
                self.assertNotIn(token, product)
        copied_platform_dependency = re.compile(
            r"(?:file\(COPY|configure_file|install)\s*\([^)]*"
            r"(?:iconv|CoreFoundation)[^)]*\)|"
            r"cmake\s+-E\s+copy[^\n]*(?:iconv|CoreFoundation)",
            re.IGNORECASE | re.DOTALL,
        )
        for path, source in product_sources.items():
            with self.subTest(copy_surface=path):
                self.assertNotRegex(source, copied_platform_dependency)
        self.assertNotIn(
            "-framework CoreFoundation",
            product_sources[HELPER],
        )
        with tempfile.TemporaryDirectory() as directory:
            fixture = ReducedAppleFixture(directory)
            completed = fixture.configure(query_codemodel=True)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            properties = read_properties(fixture.properties)
            _codemodel, targets = load_codemodel(fixture.build)
            links, fragments = self.assert_known_directory_absent(
                fixture, targets
            )
            self.assertEqual(properties["REGORUS_DIRECTORIES"], "")
            self.assertEqual(properties["REGORUS_STATIC_DIRECTORIES"], "")
            self.assertEqual(properties["REGORUS_TYPE"], "INTERFACE_LIBRARY")
            self.assertEqual(
                properties["REGORUS_STATIC_TYPE"],
                "STATIC_LIBRARY",
            )
            generated_surfaces = (
                *properties.values(),
                " ".join(fragments["nvat"]["all"]),
                " ".join(fragments["nvattest"]["all"]),
                links["nvat"],
                links["nvattest"],
            )
            for token in forbidden_link_tokens:
                for index, surface in enumerate(generated_surfaces):
                    with self.subTest(token=token, generated_surface=index):
                        self.assertNotIn(token, surface)

            regorus_interface = properties["REGORUS"].split(";")
            self.assertEqual(regorus_interface[0], "regorus_ffi-static")
            self.assertEqual(len(regorus_interface), 2)
            expected = (
                (
                    properties["REGORUS_STATIC_LOCATION"],
                    Path(properties["REGORUS_STATIC_LOCATION"]).name,
                ),
                (
                    properties["ICONV"],
                    Path(properties["ICONV"]).name,
                ),
                (
                    regorus_interface[1],
                    "CoreFoundation",
                ),
            )
            nvat = " ".join(
                (*fragments["nvat"]["all"], links["nvat"])
            )
            nvattest = " ".join(
                (*fragments["nvattest"]["all"], links["nvattest"])
            )
            for exact, generated_marker in expected:
                self.assertIn(generated_marker, nvat)
                self.assertNotIn(exact, nvattest)
                self.assertNotIn(generated_marker, nvattest)

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
            if (
                completed.returncode == 0
                and match
                and match.group(1).startswith("3.11.")
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

    def assert_extracted_fixture(self, cmake):
        with tempfile.TemporaryDirectory() as directory:
            fixture = ReducedAppleFixture(directory)
            completed = fixture.configure(cmake=cmake)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertRegex(completed.stdout, r"ENGINE=\d+\.\d+")
            self.assertTrue((fixture.build / "CMakeCache.txt").exists())
            properties = read_properties(fixture.properties)
            self.assertEqual(properties["LIBXML"], "Iconv::Iconv")
            self.assertEqual(properties["REGORUS_DIRECTORIES"], "")
            self.assertEqual(properties["REGORUS_STATIC_DIRECTORIES"], "")
            self.assertEqual(properties["REGORUS_TYPE"], "INTERFACE_LIBRARY")
            self.assertEqual(
                properties["REGORUS_STATIC_TYPE"],
                "STATIC_LIBRARY",
            )
            regorus = properties["REGORUS"].split(";")
            self.assertEqual(regorus[0], "regorus_ffi-static")
            self.assertEqual(len(regorus), 2)
            nvat_link = (fixture.build / "CMakeFiles/nvat.dir/link.txt").read_text(
                encoding="utf-8"
            )
            nvattest_link = (
                fixture.build / "CMakeFiles/nvattest.dir/link.txt"
            ).read_text(encoding="utf-8")
            self.assertIn(properties["REGORUS_STATIC_LOCATION"], nvat_link)
            self.assertIn(properties["ICONV"], nvat_link)
            self.assertIn("CoreFoundation", nvat_link)
            self.assertNotIn(
                properties["REGORUS_STATIC_LOCATION"],
                nvattest_link,
            )
            self.assertNotIn(properties["ICONV"], nvattest_link)
            self.assertNotIn("CoreFoundation", nvattest_link)
            self.assertNotIn(CORROSION_SDK_LINK_DIRECTORY, nvat_link)
            self.assertNotIn(CORROSION_SDK_LINK_DIRECTORY, nvattest_link)

    def test_extracted_link_closure_with_release_cmake(self):
        self.assert_extracted_fixture("cmake")

    def test_extracted_link_closure_with_real_cmake_311_when_available(self):
        self.assert_extracted_fixture(self.cmake_311())

    def test_helper_avoids_post_311_commands(self):
        helper = HELPER.read_text(encoding="utf-8")
        for token in (
            "list(PREPEND",
            "string(JOIN",
            "FetchContent_MakeAvailable",
            "target_link_options",
            "file(REAL_PATH",
            "cmake_path",
        ):
            with self.subTest(token=token):
                self.assertNotIn(token, helper)

    def install_fixture(self):
        self.assert_production_configured()
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        prefix = root / "prefix"
        installed = install_configured_nvat(self.production_build, prefix)
        self.assertEqual(installed.returncode, 0, installed.stderr)
        return temporary, prefix

    def test_install_export_omits_private_platform_closure(self):
        temporary, prefix = self.install_fixture()
        with temporary:
            cmake_dir = prefix / "share/cmake/nvat"
            targets = (cmake_dir / "nvatTargets.cmake").read_text(encoding="utf-8")
            config = (cmake_dir / "nvatConfig.cmake").read_text(encoding="utf-8")
            for source in (targets, config):
                self.assertNotIn(str(self.production_build), source)
                self.assertNotIn("MacOSX.sdk", source)
                self.assertNotIn("Iconv::Iconv", source)
                self.assertNotIn("regorus_ffi", source)
                self.assertNotIn("CoreFoundation", source)
            for package in PACKAGE_DEPENDENCIES:
                self.assertIn(f"find_dependency({package} REQUIRED)", config)

    def test_config_stubbed_clean_prefix_consumer_configures(self):
        temporary, prefix = self.install_fixture()
        with temporary:
            root = Path(temporary.name)
            stubs = write_package_config_stubs(
                root / "package-stubs", PACKAGE_DEPENDENCIES
            )
            source = root / "consumer"
            build = root / "consumer-build"
            source.mkdir()
            (source / "main.cpp").write_text(
                "int main() { return 0; }\n", encoding="utf-8"
            )
            (source / "CMakeLists.txt").write_text(
                "cmake_minimum_required(VERSION 3.11)\n"
                "project(nvat_consumer LANGUAGES CXX)\n"
                "set(CMAKE_FIND_PACKAGE_PREFER_CONFIG ON)\n"
                "find_package(nvat CONFIG REQUIRED)\n"
                "add_executable(consumer main.cpp)\n"
                "target_link_libraries(consumer PRIVATE nvat::nvat)\n",
                encoding="utf-8",
            )
            completed = subprocess.run(
                [
                    "cmake",
                    "-S",
                    str(source),
                    "-B",
                    str(build),
                    f"-DCMAKE_PREFIX_PATH={prefix};{stubs}",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            link = (build / "CMakeFiles/consumer.dir/link.txt").read_text(
                encoding="utf-8"
            )
            self.assertIn(str(prefix / "lib/libnvat.so.1.2.2"), link)
            self.assertNotIn("CoreFoundation", link)
            self.assertNotIn("Iconv", link)

    def test_use_system_nvat_cli_has_no_direct_platform_edges(self):
        temporary, prefix = self.install_fixture()
        with temporary:
            base_prepare = installed_header_fixture_prepare()

            def prepare(fixture_root):
                arguments, project_include = base_prepare(fixture_root)
                arguments = [
                    argument
                    for argument in arguments
                    if not argument.startswith("-DNVAT_INCLUDE_DIR=")
                    and not argument.startswith("-DNVAT_LIBRARY=")
                ]
                arguments.extend(
                    (
                        f"-DNVAT_INCLUDE_DIR={prefix / 'include'}",
                        f"-DNVAT_LIBRARY={prefix / 'lib/libnvat.so'}",
                    )
                )
                return arguments, project_include

            (
                configured_temporary,
                completed,
                _event_log,
                _records,
                build,
            ) = production_configure(
                ROOT / "nv-attestation-cli",
                fixture_prepare=prepare,
                query_codemodel=True,
            )
            with configured_temporary:
                self.assertEqual(completed.returncode, 0, completed.stderr)
                _codemodel, targets = load_codemodel(build)
                expected_library = str(prefix / "lib/libnvat.so")
                expected_rpath = f"-Wl,-rpath,{prefix / 'lib'}:"
                fragments = library_fragments(targets["nvattest"])
                self.assertEqual(fragments, [expected_rpath, expected_library])
                self.assertEqual(
                    normalized_library_fragments(targets["nvattest"]),
                    [expected_rpath, "libnvat.so"],
                )
                link = (build / "CMakeFiles/nvattest.dir/link.txt").read_text(
                    encoding="utf-8"
                )
                generated_library_fragments = [
                    token
                    for token in shlex.split(link)
                    if token.startswith(("-l", "-Wl,-rpath,"))
                    or re.search(
                        r"\.(?:a|dylib|tbd|so(?:\.[0-9.]+)?)$",
                        token,
                    )
                ]
                self.assertEqual(
                    generated_library_fragments,
                    [expected_rpath, expected_library],
                )
                self.assertNotIn("CoreFoundation", link)
                self.assertNotIn("Iconv", link)

    def test_readme_assigns_native_link_closure_to_vpe(self):
        readme = (RELEASE_DIR / "README.md").read_text(encoding="utf-8")
        normalized = normalized_output(readme)
        self.assertIn("VPE must also rerun Pro5E", normalized)
        self.assertIn("record both final link commands", normalized)
        self.assertIn("exactly once after their static owners", normalized)
        self.assertIn("contain neither as a direct link item", normalized)
        self.assertIn(
            "This Linux lode observed only generated CMake link structure; "
            "it did not prove native Apple linkage.",
            normalized,
        )


if __name__ == "__main__":
    unittest.main()
