"""Bounds-checked reader for the ELF64 little-endian fields used by the rail."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path


ELF_MAGIC = b"\x7fELF"
ELFCLASS64 = 2
ELFDATA2LSB = 1
EM_X86_64 = 62
EM_AARCH64 = 183
SHT_STRTAB = 3
SHT_DYNAMIC = 6
SHT_GNU_VERNEED = 0x6FFFFFFE
DT_NEEDED = 1


class ElfError(ValueError):
    def __init__(self, path: Path, offset: int, message: str):
        super().__init__(f"{path}: ELF parse error at offset 0x{offset:x}: {message}")
        self.path = path
        self.offset = offset


@dataclass(frozen=True)
class ElfInfo:
    machine: int
    needed: tuple[str, ...]
    versions: tuple[str, ...]
    data: bytes


@dataclass(frozen=True)
class _Section:
    section_type: int
    offset: int
    size: int
    link: int
    entry_size: int


def _require(data: bytes, path: Path, offset: int, size: int, what: str) -> None:
    if offset < 0 or size < 0 or offset > len(data) or size > len(data) - offset:
        raise ElfError(path, max(offset, 0), f"truncated {what}")


def _cstring(data: bytes, path: Path, start: int, limit: int, what: str) -> str:
    if start < 0 or start >= limit:
        raise ElfError(path, max(start, 0), f"{what} string offset is outside its table")
    end = data.find(b"\0", start, limit)
    if end < 0:
        raise ElfError(path, start, f"unterminated {what} string")
    try:
        return data[start:end].decode("utf-8")
    except UnicodeDecodeError as error:
        raise ElfError(path, start, f"non-UTF-8 {what} string") from error


def _string_from_section(
    data: bytes, path: Path, sections: list[_Section], index: int, offset: int, what: str
) -> str:
    if index >= len(sections):
        raise ElfError(path, 0, f"{what} references missing string-table section {index}")
    strings = sections[index]
    if strings.section_type != SHT_STRTAB:
        raise ElfError(path, strings.offset, f"{what} link is not a string table")
    _require(data, path, strings.offset, strings.size, f"{what} string table")
    return _cstring(
        data,
        path,
        strings.offset + offset,
        strings.offset + strings.size,
        what,
    )


def read(path: Path) -> ElfInfo:
    try:
        data = path.read_bytes()
    except OSError as error:
        raise ElfError(path, 0, f"cannot read file: {error}") from error
    _require(data, path, 0, 64, "ELF64 header")
    if data[:4] != ELF_MAGIC:
        raise ElfError(path, 0, "bad ELF magic")
    if data[4] != ELFCLASS64:
        raise ElfError(path, 4, "expected ELFCLASS64")
    if data[5] != ELFDATA2LSB:
        raise ElfError(path, 5, "expected little-endian ELF")

    machine = struct.unpack_from("<H", data, 18)[0]
    section_offset = struct.unpack_from("<Q", data, 40)[0]
    section_entry_size, section_count = struct.unpack_from("<HH", data, 58)
    if section_count == 0:
        raise ElfError(path, 60, "extended or empty section table is not supported")
    if section_entry_size < 64:
        raise ElfError(path, 58, f"section entry size {section_entry_size} is below 64")
    _require(
        data,
        path,
        section_offset,
        section_entry_size * section_count,
        "section table",
    )

    sections: list[_Section] = []
    for index in range(section_count):
        offset = section_offset + index * section_entry_size
        values = struct.unpack_from("<IIQQQQIIQQ", data, offset)
        section = _Section(
            section_type=values[1],
            offset=values[4],
            size=values[5],
            link=values[6],
            entry_size=values[9],
        )
        if section.section_type != 0:
            _require(data, path, section.offset, section.size, f"section {index}")
        sections.append(section)

    needed: list[str] = []
    versions: list[str] = []
    for section in sections:
        if section.section_type == SHT_DYNAMIC:
            if section.entry_size not in (0, 16) or section.size % 16:
                raise ElfError(path, section.offset, "invalid dynamic-section entry size")
            for offset in range(section.offset, section.offset + section.size, 16):
                tag, value = struct.unpack_from("<qQ", data, offset)
                if tag == DT_NEEDED:
                    needed.append(
                        _string_from_section(
                            data, path, sections, section.link, value, "DT_NEEDED"
                        )
                    )
        elif section.section_type == SHT_GNU_VERNEED:
            cursor = section.offset
            end = section.offset + section.size
            seen: set[int] = set()
            while cursor < end:
                if cursor in seen:
                    raise ElfError(path, cursor, "version-need record cycle")
                seen.add(cursor)
                _require(data, path, cursor, 16, "version-need record")
                _, count, _, auxiliary, next_record = struct.unpack_from("<HHIII", data, cursor)
                auxiliary_cursor = cursor + auxiliary
                for auxiliary_index in range(count):
                    if auxiliary_cursor >= end:
                        raise ElfError(path, auxiliary_cursor, "version auxiliary is outside section")
                    _require(data, path, auxiliary_cursor, 16, "version auxiliary")
                    _, _, _, name_offset, next_auxiliary = struct.unpack_from(
                        "<IHHII", data, auxiliary_cursor
                    )
                    versions.append(
                        _string_from_section(
                            data,
                            path,
                            sections,
                            section.link,
                            name_offset,
                            "symbol version",
                        )
                    )
                    if next_auxiliary == 0:
                        if auxiliary_index + 1 != count:
                            raise ElfError(
                                path,
                                auxiliary_cursor,
                                "version auxiliary chain ends before declared count",
                            )
                        break
                    auxiliary_cursor += next_auxiliary
                if next_record == 0:
                    break
                cursor += next_record
            if cursor > end:
                raise ElfError(path, cursor, "version-need record is outside section")

    return ElfInfo(
        machine=machine,
        needed=tuple(needed),
        versions=tuple(versions),
        data=data,
    )
