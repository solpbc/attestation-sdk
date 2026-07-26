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
                    elf.EM_X86_64, versions=("GLIBC_2.29",)
                ),
                "GLIBC requirement 2.29 exceeds target floor 2.28",
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

    def test_valid_macho_executable_and_library(self):
        target, allowlist = self.target(authority.TARGET_IDS[2])
        gate.gate_file(
            self.write(
                "nvattest",
                fixtures.macho_fixture(rpaths=(target["macho_rpath"],)),
            ),
            target,
            allowlist,
        )
        gate.gate_file(
            self.write(
                "libnvat.1.2.2.dylib",
                fixtures.macho_fixture(
                    dylib_id=target["macho_install_id"], rpaths=()
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
