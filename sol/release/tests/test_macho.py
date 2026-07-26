import struct
import sys
import tempfile
import unittest
from pathlib import Path


RELEASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RELEASE_DIR))

from release_rail import fixtures, macho  # noqa: E402


class MachOReaderTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def write(self, payload):
        return fixtures.write_fixture(self.directory, "fixture.macho", payload)

    def test_reads_build_version_dylibs_and_rpath(self):
        info = macho.read(self.write(fixtures.macho_fixture()))
        self.assertEqual(info.cputype, macho.CPU_TYPE_ARM64)
        self.assertEqual(info.platforms, (1,))
        self.assertEqual(info.deployments, ((14, 0, 0),))
        self.assertEqual(info.dylibs, ((macho.LC_LOAD_DYLIB, "/usr/lib/libz.1.dylib"),))
        self.assertEqual(info.rpaths, ("@executable_path/../lib",))

    def test_reads_legacy_deployment_command(self):
        info = macho.read(
            self.write(
                fixtures.macho_fixture(
                    deployment_command=macho.LC_VERSION_MIN_MACOSX
                )
            )
        )
        self.assertEqual(info.deployments, ((14, 0, 0),))

    def test_every_fat_magic_is_rejected(self):
        for magic in macho.FAT_MAGICS:
            with self.subTest(magic=hex(magic)):
                with self.assertRaisesRegex(
                    macho.MachOError, "universal Mach-O is not permitted"
                ):
                    macho.read(
                        self.write(fixtures.macho_fixture(fat_magic=magic))
                    )

    def test_truncated_inputs_name_file_and_offset(self):
        complete = fixtures.macho_fixture()
        for length in (0, 20, 31, len(complete) - 1):
            with self.subTest(length=length):
                path = self.write(complete[:length])
                with self.assertRaisesRegex(
                    macho.MachOError, rf"{path}.*offset 0x[0-9a-f]+.*truncated"
                ):
                    macho.read(path)

    def test_overlong_ncmds_is_rejected_at_missing_command(self):
        path = self.write(fixtures.macho_fixture(declared_ncmds=99))
        with self.assertRaisesRegex(
            macho.MachOError, rf"{path}.*load command [0-9]+ exceeds sizeofcmds"
        ):
            macho.read(path)

    def test_invalid_command_size_is_rejected(self):
        payload = bytearray(fixtures.macho_fixture())
        payload[36:40] = struct.pack("<I", 4)
        with self.assertRaisesRegex(macho.MachOError, "invalid cmdsize"):
            macho.read(self.write(bytes(payload)))

    def test_invalid_and_unterminated_string_offsets_are_rejected(self):
        payload = bytearray(
            fixtures.macho_fixture(deployment_command=None, rpaths=())
        )
        payload[40:44] = struct.pack("<I", 4)
        with self.assertRaisesRegex(macho.MachOError, "string offset 4 is invalid"):
            macho.read(self.write(bytes(payload)))

        payload = bytearray(
            fixtures.macho_fixture(deployment_command=None, rpaths=())
        )
        command_size = int.from_bytes(payload[36:40], "little")
        payload[32 + 24 : 32 + command_size] = b"x" * (command_size - 24)
        with self.assertRaisesRegex(macho.MachOError, "unterminated load-command string"):
            macho.read(self.write(bytes(payload)))


if __name__ == "__main__":
    unittest.main()
