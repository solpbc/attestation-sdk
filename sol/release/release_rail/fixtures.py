"""Minimal synthetic bytes for release-gate unit tests."""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Iterable

from . import elf, macho


def _align(value: int, alignment: int = 8) -> int:
    return (value + alignment - 1) // alignment * alignment


def elf_fixture(
    machine: int,
    needed: Iterable[str] = ("libc.so.6",),
    versions: Iterable[str] = (),
    strings: Iterable[str] = (),
    *,
    truncated_at: int | None = None,
) -> bytes:
    needed = tuple(needed)
    versions = tuple(versions)
    table = bytearray(b"\0")

    def add_string(value: str) -> int:
        offset = len(table)
        table.extend(value.encode("utf-8") + b"\0")
        return offset

    needed_offsets = [add_string(value) for value in needed]
    version_offsets = [add_string(value) for value in versions]
    dynamic = b"".join(struct.pack("<qQ", elf.DT_NEEDED, offset) for offset in needed_offsets)
    dynamic += struct.pack("<qQ", 0, 0)

    version_need = bytearray()
    if version_offsets:
        version_need.extend(struct.pack("<HHIII", 1, len(version_offsets), 0, 16, 0))
        for index, name_offset in enumerate(version_offsets):
            next_offset = 16 if index + 1 < len(version_offsets) else 0
            version_need.extend(struct.pack("<IHHII", 0, 0, 0, name_offset, next_offset))

    payload = "\0".join(strings).encode("utf-8")
    blobs = [b"", bytes(table), dynamic, bytes(version_need), payload]
    types = [0, elf.SHT_STRTAB, elf.SHT_DYNAMIC, elf.SHT_GNU_VERNEED, 1]
    links = [0, 0, 1, 1, 0]
    entry_sizes = [0, 0, 16, 0, 0]
    offsets: list[int] = []
    body = bytearray(b"\0" * 64)
    for blob in blobs:
        if not blob:
            offsets.append(0)
            continue
        position = _align(len(body))
        body.extend(b"\0" * (position - len(body)))
        offsets.append(position)
        body.extend(blob)
    section_offset = _align(len(body))
    body.extend(b"\0" * (section_offset - len(body)))
    for index, blob in enumerate(blobs):
        body.extend(
            struct.pack(
                "<IIQQQQIIQQ",
                0,
                types[index],
                0,
                0,
                offsets[index],
                len(blob),
                links[index],
                0,
                1,
                entry_sizes[index],
            )
        )
    header = struct.pack(
        "<16sHHIQQQIHHHHHH",
        elf.ELF_MAGIC + bytes((elf.ELFCLASS64, elf.ELFDATA2LSB, 1)) + b"\0" * 9,
        3,
        machine,
        1,
        0,
        0,
        section_offset,
        0,
        64,
        0,
        0,
        64,
        len(blobs),
        0,
    )
    body[:64] = header
    result = bytes(body)
    return result if truncated_at is None else result[:truncated_at]


def _packed_version(value: tuple[int, int, int]) -> int:
    return value[0] << 16 | value[1] << 8 | value[2]


def _string_command(command: int, value: str, fixed_size: int) -> bytes:
    encoded = value.encode("utf-8") + b"\0"
    command_size = _align(fixed_size + len(encoded))
    if fixed_size == 24:
        header = struct.pack("<IIIIII", command, command_size, fixed_size, 0, 0, 0)
    else:
        header = struct.pack("<III", command, command_size, fixed_size)
    return header + encoded + b"\0" * (command_size - fixed_size - len(encoded))


def macho_fixture(
    cputype: int = macho.CPU_TYPE_ARM64,
    cpusubtype: int = 0,
    deployment_command: int | None = macho.LC_BUILD_VERSION,
    deployment_version: tuple[int, int, int] = (14, 0, 0),
    dylibs: Iterable[str] = ("/usr/lib/libz.1.dylib",),
    dylib_id: str | None = None,
    rpaths: Iterable[str] = ("@executable_path/../lib",),
    strings: Iterable[str] = (),
    *,
    declared_ncmds: int | None = None,
    fat_magic: int | None = None,
    truncated_at: int | None = None,
) -> bytes:
    if fat_magic is not None:
        result = struct.pack(">I", fat_magic) + b"\0" * 28
        return result if truncated_at is None else result[:truncated_at]
    commands: list[bytes] = []
    if deployment_command == macho.LC_BUILD_VERSION:
        commands.append(
            struct.pack(
                "<IIIIII",
                macho.LC_BUILD_VERSION,
                24,
                1,
                _packed_version(deployment_version),
                _packed_version(deployment_version),
                0,
            )
        )
    elif deployment_command == macho.LC_VERSION_MIN_MACOSX:
        commands.append(
            struct.pack(
                "<IIII",
                macho.LC_VERSION_MIN_MACOSX,
                16,
                _packed_version(deployment_version),
                _packed_version(deployment_version),
            )
        )
    if dylib_id is not None:
        commands.append(_string_command(macho.LC_ID_DYLIB, dylib_id, 24))
    commands.extend(_string_command(macho.LC_LOAD_DYLIB, value, 24) for value in dylibs)
    commands.extend(_string_command(macho.LC_RPATH, value, 12) for value in rpaths)
    command_data = b"".join(commands)
    header = struct.pack(
        "<IIIIIIII",
        macho.MH_MAGIC_64,
        cputype,
        cpusubtype,
        2,
        len(commands) if declared_ncmds is None else declared_ncmds,
        len(command_data),
        0,
        0,
    )
    result = header + command_data + "\0".join(strings).encode("utf-8")
    return result if truncated_at is None else result[:truncated_at]


def write_fixture(directory: Path, name: str, payload: bytes) -> Path:
    path = directory / name
    path.write_bytes(payload)
    return path
