#!/usr/bin/env python3
"""Extract HWP5 preview and paragraph text records using only the stdlib.

This bounded parser is intended for the small, locally preserved KRA schedule
attachments in this evidence package. It reads OLE compound streams, applies
the HWP5 raw-deflate flag to BodyText section streams, and emits decoded
paragraph text records for manual source verification.
"""

from __future__ import annotations

import argparse
import csv
import pathlib
import struct
import zlib

OLE_SIGNATURE = bytes.fromhex("d0cf11e0a1b11ae1")
ENDOFCHAIN = 0xFFFFFFFE
FREESECT = 0xFFFFFFFF
FATSECT = 0xFFFFFFFD
DIFSECT = 0xFFFFFFFC
MAXREGSECT = 0xFFFFFFFA


def unpack_u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


class CompoundFile:
    def __init__(self, data: bytes):
        if data[:8] != OLE_SIGNATURE:
            raise ValueError("input is not an OLE compound file")
        self.data = data
        self.sector_size = 1 << struct.unpack_from("<H", data, 30)[0]
        self.mini_sector_size = 1 << struct.unpack_from("<H", data, 32)[0]
        self.num_fat = unpack_u32(data, 44)
        self.first_dir = unpack_u32(data, 48)
        self.mini_cutoff = unpack_u32(data, 56)
        self.first_minifat = unpack_u32(data, 60)
        self.num_minifat = unpack_u32(data, 64)
        self.first_difat = unpack_u32(data, 68)
        self.num_difat = unpack_u32(data, 72)

        difat = [s for s in struct.unpack_from("<109I", data, 76) if s < MAXREGSECT]
        current = self.first_difat
        for _ in range(self.num_difat):
            values = struct.unpack("<%dI" % (self.sector_size // 4), self.sector(current))
            difat.extend(s for s in values[:-1] if s < MAXREGSECT)
            current = values[-1]
        if len(difat) < self.num_fat:
            raise ValueError("truncated OLE FAT sector list")

        self.fat: list[int] = []
        for fat_sector in difat[: self.num_fat]:
            self.fat.extend(struct.unpack("<%dI" % (self.sector_size // 4), self.sector(fat_sector)))

        directory = self.read_regular(self.first_dir, self.sector_size * 100_000)
        self.entries = self.parse_directory(directory)
        roots = [entry for entry in self.entries if entry["type"] == 5]
        if len(roots) != 1:
            raise ValueError("expected one OLE root storage")
        root = roots[0]
        self.mini_stream = self.read_regular(root["start"], root["size"])
        minifat_bytes = self.read_regular(self.first_minifat, self.num_minifat * self.sector_size)
        self.minifat = list(struct.unpack("<%dI" % (len(minifat_bytes) // 4), minifat_bytes)) if minifat_bytes else []

    def sector(self, index: int) -> bytes:
        start = (index + 1) * self.sector_size
        end = start + self.sector_size
        if index >= MAXREGSECT or start < 0 or end > len(self.data):
            raise ValueError("OLE sector index outside input")
        return self.data[start:end]

    @staticmethod
    def chain(start: int, table: list[int]) -> list[int]:
        output: list[int] = []
        seen: set[int] = set()
        current = start
        while current not in (ENDOFCHAIN, FREESECT) and current < MAXREGSECT:
            if current >= len(table) or current in seen:
                raise ValueError("invalid or cyclic OLE allocation chain")
            seen.add(current)
            output.append(current)
            current = table[current]
        return output

    def read_regular(self, start: int, size: int) -> bytes:
        if size <= 0 or start in (ENDOFCHAIN, FREESECT):
            return b""
        return b"".join(self.sector(s) for s in self.chain(start, self.fat))[:size]

    @staticmethod
    def parse_directory(data: bytes) -> list[dict[str, int | str]]:
        entries: list[dict[str, int | str]] = []
        for offset in range(0, len(data) - 127, 128):
            record = data[offset : offset + 128]
            name_len = struct.unpack_from("<H", record, 64)[0]
            entry_type = record[66]
            if not entry_type:
                continue
            if name_len < 2 or name_len > 64:
                raise ValueError("invalid OLE directory name length")
            name = record[: name_len - 2].decode("utf-16le", "replace")
            entries.append(
                {
                    "name": name,
                    "type": entry_type,
                    "start": unpack_u32(record, 116),
                    "size": struct.unpack_from("<Q", record, 120)[0],
                }
            )
        return entries

    def read_stream(self, entry: dict[str, int | str]) -> bytes:
        start, size = int(entry["start"]), int(entry["size"])
        if size < self.mini_cutoff:
            if not self.minifat and size:
                raise ValueError("missing OLE mini FAT for small stream")
            chunks = [
                self.mini_stream[s * self.mini_sector_size : (s + 1) * self.mini_sector_size]
                for s in self.chain(start, self.minifat)
            ]
            return b"".join(chunks)[:size]
        return self.read_regular(start, size)


def clean_text(data: bytes) -> str:
    text = data.decode("utf-16le", "replace")
    return "".join(ch for ch in text if ch in "\t\n\r" or ord(ch) >= 32).strip()


def paragraph_records(data: bytes) -> list[dict[str, int | str]]:
    records: list[dict[str, int | str]] = []
    offset = 0
    record_index = 0
    while offset + 4 <= len(data):
        header = unpack_u32(data, offset)
        offset += 4
        tag = header & 0x3FF
        level = (header >> 10) & 0x3FF
        length = (header >> 20) & 0xFFF
        if length == 0xFFF:
            if offset + 4 > len(data):
                raise ValueError("truncated extended HWP record length")
            length = unpack_u32(data, offset)
            offset += 4
        if offset + length > len(data):
            raise ValueError("truncated HWP record body")
        body = data[offset : offset + length]
        offset += length
        text = clean_text(body) if tag == 67 else ""
        records.append({"record_index": record_index, "tag": tag, "level": level, "size": length, "text": text})
        record_index += 1
    if offset != len(data):
        raise ValueError("trailing bytes after HWP records")
    return records


def extract(path: pathlib.Path) -> tuple[str, list[dict[str, int | str]]]:
    compound = CompoundFile(path.read_bytes())
    streams = {str(e["name"]): compound.read_stream(e) for e in compound.entries if e["type"] == 2}
    file_header = streams.get("FileHeader", b"")
    compressed = bool(len(file_header) >= 40 and (unpack_u32(file_header, 36) & 1))
    section = next((name for name in streams if name == "Section0"), None)
    if section is None:
        raise ValueError("HWP document has no Section0 stream")
    section_data = zlib.decompress(streams[section], -15) if compressed else streams[section]
    records = paragraph_records(section_data)
    preview = streams.get("PrvText", b"").decode("utf-16le", "replace")
    return preview, records


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=pathlib.Path)
    parser.add_argument("--preview", required=True, type=pathlib.Path)
    parser.add_argument("--records", required=True, type=pathlib.Path)
    args = parser.parse_args()
    preview, records = extract(args.input)
    args.preview.parent.mkdir(parents=True, exist_ok=True)
    args.records.parent.mkdir(parents=True, exist_ok=True)
    args.preview.write_text(preview, encoding="utf-8")
    with args.records.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=["record_index", "tag", "level", "size", "text"])
        writer.writeheader()
        writer.writerows(records)
    print(f"wrote {len(records)} HWP records; preview characters={len(preview)}")


if __name__ == "__main__":
    main()
