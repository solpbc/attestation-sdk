import sys
import tempfile
import unittest
from pathlib import Path


RELEASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RELEASE_DIR))

from release_rail import authority, elf, fixtures, gate, macho  # noqa: E402


class GateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.authority = authority.load()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def target(self, target_id):
        target = self.authority.target(target_id)
        allowlist = authority.read_allowlist(self.authority, target)
        return target, allowlist

    def write(self, name, payload):
        return fixtures.write_fixture(self.directory, name, payload)

    def test_each_elf_architecture_accepts_its_own_and_rejects_the_other(self):
        cases = (
            (authority.TARGET_IDS[0], elf.EM_X86_64, elf.EM_AARCH64),
            (authority.TARGET_IDS[1], elf.EM_AARCH64, elf.EM_X86_64),
        )
        for target_id, native, foreign in cases:
            target, allowlist = self.target(target_id)
            with self.subTest(target=target_id, state="native"):
                gate.gate_file(
                    self.write(target_id, fixtures.elf_fixture(native)),
                    target,
                    allowlist,
                )
            with self.subTest(target=target_id, state="foreign"):
                with self.assertRaisesRegex(gate.GateError, "wrong ELF architecture"):
                    gate.gate_file(
                        self.write(target_id, fixtures.elf_fixture(foreign)),
                        target,
                        allowlist,
                    )

    def test_elf_empty_needed_forbidden_dso_and_above_floor_fail(self):
        target, allowlist = self.target(authority.TARGET_IDS[0])
        glibc_floor = target["abi_floor"]["glibc"]
        glibc_parts = glibc_floor.split(".")
        glibc_parts[-1] = str(int(glibc_parts[-1]) + 1)
        above_glibc = ".".join(glibc_parts)
        cases = (
            (
                fixtures.elf_fixture(elf.EM_X86_64, needed=()),
                "no DT_NEEDED entries",
            ),
            (
                fixtures.elf_fixture(
                    elf.EM_X86_64, needed=("libcurl.so.4",)
                ),
                "forbidden DT_NEEDED entry: libcurl.so.4",
            ),
            (
                fixtures.elf_fixture(
                    elf.EM_X86_64, versions=(f"GLIBC_{above_glibc}",)
                ),
                f"GLIBC requirement {above_glibc} exceeds target floor {glibc_floor}",
            ),
            (
                fixtures.elf_fixture(
                    elf.EM_X86_64, versions=("GLIBCXX_3.4.26",)
                ),
                "GLIBCXX requirement 3.4.26 exceeds target floor 3.4.25",
            ),
            (
                fixtures.elf_fixture(
                    elf.EM_X86_64, versions=("CXXABI_1.3.12",)
                ),
                "CXXABI requirement 1.3.12 exceeds target floor 1.3.11",
            ),
        )
        for payload, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(gate.GateError, message):
                    gate.gate_file(self.write("bad.elf", payload), target, allowlist)

    def test_baked_host_ca_paths_fail_for_each_format(self):
        elf_target, elf_allowlist = self.target(authority.TARGET_IDS[0])
        macho_target, macho_allowlist = self.target(authority.TARGET_IDS[2])
        for ca_path in gate.FORBIDDEN_CA_PATHS:
            text = ca_path.decode()
            with self.subTest(format="elf", path=text):
                with self.assertRaisesRegex(gate.GateError, "compiled host CA path"):
                    gate.gate_file(
                        self.write(
                            "bad.elf",
                            fixtures.elf_fixture(
                                elf.EM_X86_64, strings=(text,)
                            ),
                        ),
                        elf_target,
                        elf_allowlist,
                    )
            with self.subTest(format="macho", path=text):
                with self.assertRaisesRegex(gate.GateError, "compiled host CA path"):
                    gate.gate_file(
                        self.write(
                            "bad.macho", fixtures.macho_fixture(strings=(text,))
                        ),
                        macho_target,
                        macho_allowlist,
                    )

    def test_baked_openssldir_paths_fail_for_each_format(self):
        elf_target, elf_allowlist = self.target(authority.TARGET_IDS[0])
        macho_target, macho_allowlist = self.target(authority.TARGET_IDS[2])
        for fragment in gate.FORBIDDEN_OPENSSLDIR_PATHS:
            text = fragment.decode()
            with self.subTest(format="elf", path=text):
                with self.assertRaisesRegex(
                    gate.GateError, "build-tree openssldir path found"
                ):
                    gate.gate_file(
                        self.write(
                            "bad.elf",
                            fixtures.elf_fixture(
                                elf.EM_X86_64, strings=(text,)
                            ),
                        ),
                        elf_target,
                        elf_allowlist,
                    )
            with self.subTest(format="macho", path=text):
                with self.assertRaisesRegex(
                    gate.GateError, "build-tree openssldir path found"
                ):
                    gate.gate_file(
                        self.write(
                            "bad.macho", fixtures.macho_fixture(strings=(text,))
                        ),
                        macho_target,
                        macho_allowlist,
                    )

    def test_prefix_derived_module_and_engine_roots_are_forbidden(self):
        # The verbatim pre-fix MODULESDIR C-string from a real build tree, and
        # its ENGINESDIR sibling. Since sol.5 both name /nvat-openssl.
        twins = (
            "/home/jer/.hopper/worktrees/6patvfem/build/"
            "openssl-install/lib/ossl-modules",
            "/src/build/release/openssl-install/lib/engines-3",
        )
        elf_target, elf_allowlist = self.target(authority.TARGET_IDS[0])
        macho_target, macho_allowlist = self.target(authority.TARGET_IDS[2])
        for twin in twins:
            with self.subTest(format="elf", path=twin):
                with self.assertRaisesRegex(
                    gate.GateError, "build-tree OpenSSL module or engine root found"
                ):
                    gate.gate_file(
                        self.write(
                            "bad.elf",
                            fixtures.elf_fixture(elf.EM_X86_64, strings=(twin,)),
                        ),
                        elf_target,
                        elf_allowlist,
                    )
            with self.subTest(format="macho", path=twin):
                with self.assertRaisesRegex(
                    gate.GateError, "build-tree OpenSSL module or engine root found"
                ):
                    gate.gate_file(
                        self.write(
                            "bad.macho",
                            fixtures.macho_fixture(strings=(twin,)),
                        ),
                        macho_target,
                        macho_allowlist,
                    )

    def test_inert_module_and_engine_roots_are_allowed(self):
        inert = ("/nvat-openssl/ossl-modules", "/nvat-openssl/engines-3")
        elf_target, elf_allowlist = self.target(authority.TARGET_IDS[0])
        gate.gate_file(
            self.write("ok.elf", fixtures.elf_fixture(elf.EM_X86_64, strings=inert)),
            elf_target,
            elf_allowlist,
        )

    def test_elf_runpath_policy(self):
        target, allowlist = self.target(authority.TARGET_IDS[0])
        self.assertEqual(target["elf_runpath"], "$ORIGIN/../lib")
        gate.gate_file(self.write("nvattest", fixtures.elf_fixture(elf.EM_X86_64)), target, allowlist)
        gate.gate_file(
            self.write("libnvat.so", fixtures.elf_fixture(elf.EM_X86_64, soname="libnvat.so.1")),
            target,
            allowlist,
        )
        refusals = (
            ("missing", {"runpaths": ()}, "exactly DT_RUNPATH"),
            ("build tree", {"runpaths": ("/src/build/release/nv-attestation-sdk-build:",)}, "empty entry"),
            ("empty entry", {"runpaths": ("$ORIGIN/../lib:",)}, "empty entry"),
            ("other value", {"runpaths": ("$ORIGIN/lib",)}, "exactly DT_RUNPATH"),
            ("twice", {"runpaths": ("$ORIGIN/../lib", "$ORIGIN/../lib")}, "exactly DT_RUNPATH"),
            ("rpath", {"rpaths": ("$ORIGIN/../lib",)}, "DT_RPATH is not permitted"),
            ("library runpath", {"soname": "libnvat.so.1", "runpaths": ("$ORIGIN",)}, "library must not contain DT_RUNPATH"),
            ("library rpath", {"soname": "libnvat.so.1", "rpaths": ("/x/y",)}, "DT_RPATH is not permitted"),
        )
        for name, options, message in refusals:
            with self.subTest(case=name):
                with self.assertRaisesRegex(gate.GateError, message):
                    gate.gate_file(
                        self.write("refused.elf", fixtures.elf_fixture(elf.EM_X86_64, **options)),
                        target,
                        allowlist,
                    )

    def test_build_root_gate_refuses_each_root_in_any_member(self):
        roots = gate.build_root_strings(
            ["/nvat-sol-release/src", "/nvat-sol-release/src/build/release", "/home/u/.cargo", "/home/u/"]
        )
        self.assertEqual(roots[-1], b"/home/u")
        clean = self.write("clean", b"./_deps/regorus-src/src/lib.rs\0cargo-home/registry/src\0")
        gate.gate_build_root_files([clean], roots)
        for planted in (
            b"/nvat-sol-release/src/build/release/_deps/regorus-src/src/lib.rs",
            b"file:///nvat-sol-release/src/x",
            b"/home/u/.cargo/registry/src/index.crates.io-1/serde/src/de.rs",
            b"notices mention /home/u somewhere",
        ):
            with self.subTest(planted=planted):
                member = self.write("member", b"prefix\0" + planted + b"\0suffix")
                with self.assertRaisesRegex(gate.GateError, "build-host root found"):
                    gate.gate_build_root_files([clean, member], roots)

    def test_build_root_gate_refuses_roots_it_cannot_test(self):
        for roots in ([], ["relative/path"], ["/src"], ["/root/"], ["/"]):
            with self.subTest(roots=roots):
                with self.assertRaises(gate.GateError):
                    gate.build_root_strings(roots)

    def test_valid_macho_executable_and_library(self):
        target, allowlist = self.target(authority.TARGET_IDS[2])
        gate.gate_file(
            self.write(
                "nvattest",
                fixtures.macho_fixture(
                    deployment_version=(14, 0, 0),
                    rpaths=("@executable_path/../lib",),
                ),
            ),
            target,
            allowlist,
        )
        gate.gate_file(
            self.write(
                "libnvat.1.2.2.dylib",
                fixtures.macho_fixture(
                    deployment_version=(14, 0, 0),
                    dylib_id="@rpath/libnvat.1.dylib",
                    rpaths=(),
                ),
            ),
            target,
            allowlist,
        )

    def test_macho_foreign_arch_missing_deployment_and_below_floor_fail(self):
        target, allowlist = self.target(authority.TARGET_IDS[2])
        cases = (
            (
                fixtures.macho_fixture(cputype=0x01000007),
                "wrong Mach-O architecture",
            ),
            (
                fixtures.macho_fixture(deployment_command=None),
                "missing LC_BUILD_VERSION and LC_VERSION_MIN_MACOSX",
            ),
            (
                fixtures.macho_fixture(deployment_version=(13, 6, 0)),
                "deployment target must be 14.0.0",
            ),
        )
        for payload, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(gate.GateError, message):
                    gate.gate_file(
                        self.write("bad.macho", payload), target, allowlist
                    )

    def test_forbidden_dylib_and_external_prefixes_fail(self):
        target, allowlist = self.target(authority.TARGET_IDS[2])
        references = (
            "libssl.3.dylib",
            "/opt/homebrew/lib/libssl.3.dylib",
            "/usr/local/lib/libssl.3.dylib",
            str(self.directory / "build/libssl.3.dylib"),
        )
        for reference in references:
            with self.subTest(reference=reference):
                with self.assertRaisesRegex(
                    gate.GateError, "forbidden Mach-O runtime reference"
                ):
                    gate.gate_file(
                        self.write(
                            "bad.macho",
                            fixtures.macho_fixture(dylibs=(reference,)),
                        ),
                        target,
                        allowlist,
                    )

    def test_invalid_macho_identity_and_rpath_fail(self):
        target, allowlist = self.target(authority.TARGET_IDS[2])
        cases = (
            (
                fixtures.macho_fixture(
                    dylib_id="@rpath/libnvat.dylib", rpaths=()
                ),
                "LC_ID_DYLIB must be",
            ),
            (
                fixtures.macho_fixture(rpaths=("/opt/homebrew/lib",)),
                "executable must contain exactly LC_RPATH",
            ),
        )
        for payload, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(gate.GateError, message):
                    gate.gate_file(
                        self.write("bad.macho", payload), target, allowlist
                    )


if __name__ == "__main__":
    unittest.main()
