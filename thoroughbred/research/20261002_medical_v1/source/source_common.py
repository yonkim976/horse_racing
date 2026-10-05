"""Shared fixed schema and provenance helpers for the medical source package."""

from __future__ import annotations

import hashlib
import re
from datetime import date
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq


OBSERVATION_SCHEMA = pa.schema([
    ("source_kind", pa.string()), ("source_cohort", pa.string()),
    ("event_date", pa.string()), ("source_file_date", pa.string()),
    ("meet_code", pa.int16()), ("meet_raw", pa.string()),
    ("horse_name_raw", pa.string()), ("hr_no_raw", pa.string()),
    ("stable_no_raw", pa.string()), ("part_raw", pa.string()),
    ("hospital_name_raw", pa.string()), ("ill_name1_raw", pa.string()),
    ("ill_name2_raw", pa.string()), ("diagnosis_rpt_raw", pa.string()),
    ("raw_payload_json", pa.string()), ("raw_line", pa.string()),
    ("decode_has_replacement", pa.bool_()), ("source_path", pa.string()),
    ("source_sha256", pa.string()), ("capture_id", pa.string()),
    ("source_captured_at_utc", pa.string()), ("capture_timestamp_basis", pa.string()),
    ("page_no", pa.int32()), ("row_no", pa.int32()), ("line_no", pa.int32()),
    ("request_year", pa.int16()), ("request_meet", pa.int16()),
    ("response_result_code", pa.string()), ("response_result_message", pa.string()),
    ("source_row_hash", pa.string()),
])


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def iso_day(value: Any) -> str | None:
    if value is None:
        return None
    digits = re.sub(r"\D", "", str(value))
    if len(digits) != 8:
        return None
    candidate = f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    try:
        return date.fromisoformat(candidate).isoformat()
    except ValueError:
        return None


def text_value(value: Any) -> str | None:
    return None if value is None else str(value)


def row_locator_hash(source_kind: str, source_path: str, *, page_no: int | None = None,
                     row_no: int | None = None, line_no: int | None = None) -> str:
    locator = f"{source_kind}\0{source_path}\0{page_no or ''}\0{row_no or ''}\0{line_no or ''}"
    return hashlib.sha256(locator.encode("utf-8")).hexdigest()


class ParquetRowWriter:
    """Write bounded batches with a stable schema, including all-null columns."""

    def __init__(self, path: Path, schema: pa.Schema, batch_size: int = 20_000) -> None:
        self.path = path
        self.schema = schema
        self.batch_size = batch_size
        self.buffer: list[dict[str, Any]] = []
        self.writer: pq.ParquetWriter | None = None
        self.count = 0

    def __enter__(self) -> "ParquetRowWriter":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.writer = pq.ParquetWriter(self.path, self.schema, compression="zstd")
        return self

    def append(self, row: dict[str, Any]) -> None:
        self.buffer.append(row)
        if len(self.buffer) >= self.batch_size:
            self.flush()

    def append_many(self, rows: list[dict[str, Any]]) -> None:
        for row in rows:
            self.append(row)

    def flush(self) -> None:
        if not self.buffer:
            return
        assert self.writer is not None
        table = pa.Table.from_pylist(self.buffer, schema=self.schema)
        self.writer.write_table(table)
        self.count += len(self.buffer)
        self.buffer.clear()

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self.writer is not None:
            if exc_type is None:
                self.flush()
            self.writer.close()
