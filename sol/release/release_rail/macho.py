"""Bounds-checked reader for the Mach-O 64 fields used by the rail."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path


MH_MAGIC_64 = 0xFEEDFACF
MH_CIGAM_64 = 0xCFFAEDFE
FAT_MAGICS = {0xCAFEBABE, 0xBEBAFECA, 0xCAFEBABF, 0xBFBAFECA}
CPU_TYPE_ARM64 = 0x0100000C
CPU_SUBTYPE_MASK = 0x00FFFFFF
LC_REQ_DYLD = 0x80000000
LC_LOAD_DYLIB = 0x0C
LC_ID_DYLIB = 0x0D
LC_LOAD_WEAK_DYLIB = LC_REQ_DYLD | 0x18
LC_RPATH = LC_REQ_DYLD | 0x1C
LC_REEXPORT_DYLIB = LC_REQ_DYLD | 0x1F
LC_LAZY_LOAD_DYLIB = 0x20
LC_LOAD_UPWARD_DYLIB = LC_REQ_DYLD | 0x23
LC_VERSION_MIN_MACOSX = 0x24
LC_BUILD_VERSION = 0x32
DYLIB_COMMANDS = {
    LC_LOAD_DYLIB,
    LC_ID_DYLIB,
    LC_LOAD_WEAK_DYLIB,
    LC_REEXPORT_DYLIB,
    LC_LAZY_LOAD_DYLIB,
    LC_LOAD_UPWARD_DYLIB,
}


class MachOError(ValueError):
    def __init__(self, path: Path, offset: int, message: str):
        super().__init__(f"{path}: Mach-O parse error at offset 0x{offset:x}: {message}")
        self.path = path
        self.offset = offset


@dataclass(frozen=True)
class MachOInfo:
    cputype: int
    cpusubtype: int
    platforms: tuple[int, ...]
    deployments: tuple[tuple[int, int, int], ...]
    dylibs: tuple[tuple[int, str], ...]
    rpaths: tuple[str, ...]
    data: bytes


def _require(data: bytes, path: Path, offset: int, size: int, what: str) -> None:
    if offset < 0 or size < 0 or offset > len(data) or size > len(data) - offset:
        raise MachOError(path, max(offset, 0), f"truncated {what}")


def _command_string(
    data: bytes, path: Path, command_offset: int, command_size: int, string_offset: int
) -> str:
    if string_offset < 8 or string_offset >= command_size:
        raise MachOError(
            path, command_offset + 8, f"load-command string offset {string_offset} is invalid"
        )
    start = command_offset + string_offset
    end = data.find(b"\0", start, command_offset + command_size)
    if end < 0:
        raise MachOError(path, start, "unterminated load-command string")
    try:
        return data[start:end].decode("utf-8")
    except UnicodeDecodeError as error:
        raise MachOError(path, start, "non-UTF-8 load-command string") from error


def _version(value: int) -> tuple[int, int, int]:
    return value >> 16, (value >> 8) & 0xFF, value & 0xFF


def read(path: Path) -> MachOInfo:
    try:
        data = path.read_bytes()
    except OSError as error:
        raise MachOError(path, 0, f"cannot read file: {error}") from error
    _require(data, path, 0, 4, "magic")
    magic_be = struct.unpack_from(">I", data, 0)[0]
    if magic_be in FAT_MAGICS:
        raise MachOError(path, 0, "universal Mach-O is not permitted")
    magic = struct.unpack_from("<I", data, 0)[0]
    if magic == MH_CIGAM_64:
        raise MachOError(path, 0, "big-endian Mach-O is not supported")
    if magic != MH_MAGIC_64:
        raise MachOError(path, 0, "bad Mach-O magic")
    _require(data, path, 0, 32, "mach_header_64")
    cputype, cpusubtype = struct.unpack_from("<II", data, 4)
    command_count, command_bytes = struct.unpack_from("<II", data, 16)
    _require(data, path, 32, command_bytes, "load-command table")

    cursor = 32
    command_end = 32 + command_bytes
    platforms: list[int] = []
    deployments: list[tuple[int, int, int]] = []
    dylibs: list[tuple[int, str]] = []
    rpaths: list[str] = []
    for index in range(command_count):
        if cursor + 8 > command_end:
            raise MachOError(path, cursor, f"load command {index} exceeds sizeofcmds")
        _require(data, path, cursor, 8, f"load command {index}")
        command, command_size = struct.unpack_from("<II", data, cursor)
        if command_size < 8:
            raise MachOError(path, cursor + 4, f"load command {index} has invalid cmdsize")
        if cursor + command_size > command_end:
            raise MachOError(path, cursor, f"load command {index} exceeds sizeofcmds")
        _require(data, path, cursor, command_size, f"load command {index}")
        if command == LC_BUILD_VERSION:
            if command_size < 24:
                raise MachOError(path, cursor, "LC_BUILD_VERSION is shorter than 24 bytes")
            platforms.append(struct.unpack_from("<I", data, cursor + 8)[0])
            deployments.append(_version(struct.unpack_from("<I", data, cursor + 12)[0]))
        elif command == LC_VERSION_MIN_MACOSX:
            if command_size < 16:
                raise MachOError(path, cursor, "LC_VERSION_MIN_MACOSX is shorter than 16 bytes")
            platforms.append(1)
            deployments.append(_version(struct.unpack_from("<I", data, cursor + 8)[0]))
        elif command in DYLIB_COMMANDS:
            if command_size < 24:
                raise MachOError(path, cursor, "dylib command is shorter than 24 bytes")
            name_offset = struct.unpack_from("<I", data, cursor + 8)[0]
            dylibs.append(
                (command, _command_string(data, path, cursor, command_size, name_offset))
            )
        elif command == LC_RPATH:
            if command_size < 12:
                raise MachOError(path, cursor, "LC_RPATH is shorter than 12 bytes")
            path_offset = struct.unpack_from("<I", data, cursor + 8)[0]
            rpaths.append(
                _command_string(data, path, cursor, command_size, path_offset)
            )
        cursor += command_size

    if cursor != command_end:
        raise MachOError(path, cursor, "sizeofcmds contains unclaimed bytes")
    return MachOInfo(
        cputype=cputype,
        cpusubtype=cpusubtype & CPU_SUBTYPE_MASK,
        platforms=tuple(platforms),
        deployments=tuple(deployments),
        dylibs=tuple(dylibs),
        rpaths=tuple(rpaths),
        data=data,
    )
