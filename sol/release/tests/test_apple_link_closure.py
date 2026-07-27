import os
import re
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
PACKAGE_DEPENDENCIES = ("CURL", "LibXml2", "OpenSSL", "spdlog", "xmlsec")


def normalized_output(value):
    return re.sub(r"\s+", " ", value).strip()


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
            "add_library(regorus_ffi STATIC IMPORTED GLOBAL)\n"
            "set_target_properties(regorus_ffi PROPERTIES\n"
            f'  IMPORTED_LOCATION "{(self.root / "libregorus_ffi.a").as_posix()}"\n'
            ")\n"
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
            "get_target_property(_libxml LibXml2::LibXml2 "
            "INTERFACE_LINK_LIBRARIES)\n"
            "get_target_property(_xmlsec xmlsec::xmlsec "
            "INTERFACE_LINK_LIBRARIES)\n"
            "get_target_property(_iconv Iconv::Iconv IMPORTED_LOCATION)\n"
            f'file(WRITE "{self.properties.as_posix()}"\n'
            '  "REGORUS=${_regorus}\\nLIBXML=${_libxml}\\n'
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
        cls.production_state = {}
        (
            cls.production_temporary,
            cls.production_completed,
            _event_log,
            cls.production_records,
            cls.production_build,
        ) = production_configure(
            ROOT / "nv-attestation-cli",
            fixture_prepare=warning_fixture_prepare(cls.production_state),
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
            nvattest = library_fragments(targets["nvattest"])
            corefoundation = properties["REGORUS"]
            iconv_target = properties["LIBXML"]
            iconv_path = properties["ICONV"]
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
            for value in (corefoundation, iconv_path):
                self.assertNotIn(value, nvattest)
            nvat_link = (fixture.build / "CMakeFiles/nvat.dir/link.txt").read_text(
                encoding="utf-8"
            )
            nvattest_link = (
                fixture.build / "CMakeFiles/nvattest.dir/link.txt"
            ).read_text(encoding="utf-8")
            self.assertIn(iconv_path, nvat_link)
            self.assertIn("CoreFoundation", nvat_link)
            self.assertNotIn(iconv_path, nvattest_link)
            self.assertNotIn("CoreFoundation", nvattest_link)

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

    def configure_failure(
        self,
        *,
        iconv=True,
        corefoundation=True,
        apple=True,
        before_call="",
        environment=None,
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
            environment=environment,
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
                "missing regorus",
                {},
                None,
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
                if name == "missing regorus":
                    with tempfile.TemporaryDirectory() as directory:
                        fixture = ReducedAppleFixture(directory)
                        source = (fixture.source / "CMakeLists.txt").read_text(
                            encoding="utf-8"
                        )
                        source = re.sub(
                            r"add_library\(regorus_ffi STATIC IMPORTED GLOBAL\).*?"
                            r"\)\n(?=add_library\(LibXml2::LibXml2)",
                            "",
                            source,
                            count=1,
                            flags=re.DOTALL,
                        )
                        (fixture.source / "CMakeLists.txt").write_text(
                            source, encoding="utf-8"
                        )
                        completed = fixture.configure()
                        self.assert_exact_diagnostic(
                            completed,
                            "Darwin/arm64 CoreFoundation closure failed: static "
                            "owner target regorus_ffi does not exist; create the "
                            "pinned regorus_ffi target before the Apple closure "
                            "call, then retry",
                        )
                    continue
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

    def test_selected_sdk_discovery_rejects_each_poison_independently(self):
        rows = (
            ("opt/homebrew", "iconv", "prefix"),
            ("usr/local", "iconv", "library"),
            ("Library/Frameworks", "corefoundation", "framework"),
            ("host/usr/lib", "iconv", "find-root"),
            ("build/root", "iconv", "prefix"),
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
            ("opt/homebrew/system-prefix", "iconv", "system-prefix"),
        )
        for label, dependency, kind in rows:
            with self.subTest(poison=label):
                temporary = tempfile.TemporaryDirectory()
                with temporary:
                    root = Path(temporary.name)
                    poison = root / "poison" / label
                    iconv_path = (
                        poison / "usr/lib/libiconv.tbd"
                        if kind == "find-root"
                        else poison / "lib/libiconv.tbd"
                    )
                    framework_path = (
                        poison
                        / "System/Library/Frameworks/CoreFoundation.framework"
                    )
                    iconv_path.parent.mkdir(parents=True)
                    iconv_path.write_text("poison\n", encoding="utf-8")
                    framework_path.mkdir(parents=True)
                    before_call = ""
                    arguments = []
                    environment = os.environ.copy()
                    if kind == "prefix":
                        arguments.append(f"-DCMAKE_PREFIX_PATH={poison}")
                    elif kind == "library":
                        arguments.append(f"-DCMAKE_LIBRARY_PATH={iconv_path.parent}")
                    elif kind == "framework":
                        arguments.append(
                            f"-DCMAKE_FRAMEWORK_PATH={framework_path.parent}"
                        )
                    elif kind == "find-root":
                        before_call = (
                            f'set(CMAKE_FIND_ROOT_PATH "{poison.as_posix()}")\n'
                        )
                    elif kind == "cache-iconv":
                        arguments.append(
                            f"-DNVAT_APPLE_ICONV_LIBRARY={iconv_path}"
                        )
                    elif kind == "cache-corefoundation":
                        arguments.append(
                            "-DNVAT_APPLE_COREFOUNDATION_FRAMEWORK="
                            f"{framework_path}"
                        )
                    elif kind == "env-library":
                        environment["LIBRARY_PATH"] = str(iconv_path.parent)
                    elif kind == "env-ldflags":
                        environment["LDFLAGS"] = f"-L{iconv_path.parent}"
                    elif kind == "system-prefix":
                        before_call = (
                            f'set(CMAKE_SYSTEM_PREFIX_PATH "{poison.as_posix()}")\n'
                        )
                    fixture = ReducedAppleFixture(
                        root / "fixture",
                        iconv=dependency != "iconv",
                        corefoundation=dependency != "corefoundation",
                        before_call=before_call,
                        environment=environment,
                    )
                    completed = fixture.configure(arguments=arguments)
                    if dependency == "iconv":
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
        helper = HELPER.read_text(encoding="utf-8")
        product = helper + SDK_CMAKE.read_text(encoding="utf-8")
        for token in (
            "-undefined dynamic_lookup",
            "-flat_namespace",
            "--unresolved-symbols",
            "file(GLOB",
            "file(GLOB_RECURSE",
            "-L/opt/homebrew",
            "-F/opt/homebrew",
            "-L/usr/local",
            "-F/usr/local",
        ):
            with self.subTest(token=token):
                self.assertNotIn(token, product)
        self.assertNotRegex(
            helper,
            r"(?:file\(COPY|configure_file|cmake\s+-E\s+copy).*"
            r"(?:iconv|CoreFoundation)",
        )
        self.assertNotIn("-framework CoreFoundation", helper)
        with tempfile.TemporaryDirectory() as directory:
            fixture = ReducedAppleFixture(directory)
            completed = fixture.configure(query_codemodel=True)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            properties = read_properties(fixture.properties)
            _codemodel, targets = load_codemodel(fixture.build)
            expected = (properties["REGORUS"], properties["ICONV"])
            nvattest = " ".join(library_fragments(targets["nvattest"]))
            for value in expected:
                self.assertNotIn(value, nvattest)

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
            nvat_link = (fixture.build / "CMakeFiles/nvat.dir/link.txt").read_text(
                encoding="utf-8"
            )
            nvattest_link = (
                fixture.build / "CMakeFiles/nvattest.dir/link.txt"
            ).read_text(encoding="utf-8")
            self.assertIn(properties["ICONV"], nvat_link)
            self.assertIn("CoreFoundation", nvat_link)
            self.assertNotIn(properties["ICONV"], nvattest_link)
            self.assertNotIn("CoreFoundation", nvattest_link)

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
            state = {}
            base_prepare = installed_header_fixture_prepare(state)

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
                fragments = " ".join(library_fragments(targets["nvattest"]))
                self.assertIn(str(prefix / "lib/libnvat.so"), fragments)
                self.assertNotIn("CoreFoundation", fragments)
                self.assertNotIn("Iconv", fragments)
                link = (build / "CMakeFiles/nvattest.dir/link.txt").read_text(
                    encoding="utf-8"
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
