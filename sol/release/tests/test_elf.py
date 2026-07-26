import tempfile
import unittest
from pathlib import Path
import sys


RELEASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RELEASE_DIR))

from release_rail import elf, fixtures  # noqa: E402


class ElfReaderTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def write(self, payload):
        return fixtures.write_fixture(self.directory, "fixture.elf", payload)

    def test_reads_each_architecture_and_dynamic_metadata(self):
        for machine in (elf.EM_X86_64, elf.EM_AARCH64):
            with self.subTest(machine=machine):
                info = elf.read(
                    self.write(
                        fixtures.elf_fixture(
                            machine,
                            needed=("libc.so.6", "libz.so.1"),
                            versions=("GLIBC_2.28", "CXXABI_1.3.11"),
                        )
                    )
                )
                self.assertEqual(info.machine, machine)
                self.assertEqual(info.needed, ("libc.so.6", "libz.so.1"))
                self.assertEqual(info.versions, ("GLIBC_2.28", "CXXABI_1.3.11"))

    def test_truncated_inputs_name_file_and_offset(self):
        complete = fixtures.elf_fixture(elf.EM_X86_64)
        for length in (0, 20, 63, len(complete) - 1):
            with self.subTest(length=length):
                path = self.write(complete[:length])
                with self.assertRaisesRegex(
                    elf.ElfError, rf"{path}.*offset 0x[0-9a-f]+.*truncated"
                ):
                    elf.read(path)

    def test_invalid_section_entry_size_is_rejected(self):
        payload = bytearray(fixtures.elf_fixture(elf.EM_X86_64))
        payload[58:60] = (8).to_bytes(2, "little")
        with self.assertRaisesRegex(elf.ElfError, "section entry size 8 is below 64"):
            elf.read(self.write(bytes(payload)))

    def test_unterminated_dynamic_string_is_rejected(self):
        payload = bytearray(fixtures.elf_fixture(elf.EM_X86_64))
        section_offset = int.from_bytes(payload[40:48], "little")
        string_header = section_offset + 64
        string_offset = int.from_bytes(payload[string_header + 24 : string_header + 32], "little")
        string_size = int.from_bytes(payload[string_header + 32 : string_header + 40], "little")
        payload[string_offset + string_size - 1] = ord("x")
        with self.assertRaisesRegex(elf.ElfError, "unterminated DT_NEEDED string"):
            elf.read(self.write(bytes(payload)))


if __name__ == "__main__":
    unittest.main()
