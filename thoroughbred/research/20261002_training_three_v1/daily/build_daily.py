#!/usr/bin/env python3
"""Reconstruct API18_1 daily training observations from local raw captures only."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import shutil
import sqlite3
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from zoneinfo import ZoneInfo

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[4]
RESEARCH = ROOT / "thoroughbred/research/20261002_training_three_v1"
DAILY = RESEARCH / "daily"
INPUT = RESEARCH / "loader/input"
MONTHLY_ROOT = ROOT / "data/raw/kra_api_monthly/horse_training"
MONTHLY_MANIFEST = MONTHLY_ROOT / "manifest.jsonl"
OPERATING_DB = ROOT / "data/horse_racing.sqlite3"
CORE_DB = ROOT / "thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb"
RECENT_CAPTURE_MANIFEST = RESEARCH / "recent_raw/capture_manifest.json"
START_DATE = date(2010, 1, 1)
END_DATE = date(2026, 9, 29)
MEETS = (1, 3)
KST = ZoneInfo("Asia/Seoul")
UTC = timezone.utc
BATCH_SIZE = 8_192

FINAL_SCHEMA = pa.schema(
    [
        ("dataset", pa.string()),
        ("observation_id", pa.string()),
        ("event_date", pa.date32()),
        ("meet", pa.string()),
        ("official_horse_id", pa.string()),
        ("raw_name", pa.string()),
        ("raw_path", pa.string()),
        ("raw_sha256", pa.string()),
        ("source_page_no", pa.int32()),
        ("source_row_no", pa.int32()),
        ("source_captured_at", pa.timestamp("us")),
        ("capture_basis", pa.string()),
        ("endpoint", pa.string()),
        ("raw_payload_json", pa.string()),
        ("typed_fields_json", pa.string()),
        ("link_status", pa.string()),
        ("linked_core_horse_id", pa.string()),
        ("qa_flags_json", pa.string()),
        ("capture_id", pa.string()),
    ]
)
STAGE_SCHEMA = FINAL_SCHEMA.append(pa.field("natural_key_signature", pa.string()))
STAGE_SCHEMA = STAGE_SCHEMA.append(pa.field("payload_sha256", pa.string()))

MEET_LABEL_CODE = {
    "서울": 1,
    "제주": 2,
    "부산": 3,
    "부산경남": 3,
    "부경": 3,
    "영남": 3,
    "영천": 4,
}


@dataclass
class PageFile:
    raw_path: str
    absolute_path: Path
    raw_sha256: str
    page_no: int | None
    row_count: int
    capture_id: str
    capture_basis: str
    captured_at_ms: int | None
    requested_at_ms: int | None
    retrieved_at_ms: int | None
    endpoint: str
    metadata: dict[str, Any]
    integrity_status: str = "verified"
    page_total_count: int | None = None
    page_size: int | None = None
    page_meet: int | None = None
    page_month: str | None = None
    page_date: str | None = None
    is_selected: bool = False


@dataclass
class Capture:
    capture_id: str
    source_kind: str
    meet: int
    capture_at_ms: int | None
    basis: str
    pages: list[PageFile] = field(default_factory=list)
    complete: bool = False
    completeness_reason: str = "not_checked"
    month: str | None = None
    query_date: str | None = None
    request_at_ms: int | None = None
    retrieved_at_ms: int | None = None
    effective_through: date | None = None
    total_count: int | None = None
    date_counts: Counter[str] = field(default_factory=Counter)
    selected_scope_dates: set[str] = field(default_factory=set)


def canonical_json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_source_path(raw_path: str) -> tuple[str, Path]:
    candidate = Path(raw_path)
    resolved = candidate.resolve(strict=True) if candidate.is_absolute() else (ROOT / candidate).resolve(strict=True)
    if not resolved.is_relative_to(ROOT):
        raise ValueError("source path resolves outside the repository root")
    return resolved.relative_to(ROOT).as_posix(), resolved


def epoch_ms_to_utc_naive(value: int | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromtimestamp(value / 1000, UTC).replace(tzinfo=None)


def iso_kst_to_epoch_ms(value: str | None) -> int | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=KST)
    return int(parsed.astimezone(UTC).timestamp() * 1000)


def parse_api_date(value: Any) -> date:
    raw = str(value)
    if len(raw) != 8 or not raw.isdigit():
        raise ValueError("invalid trDate")
    return date(int(raw[:4]), int(raw[4:6]), int(raw[6:8]))


def source_items(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    response = payload.get("response")
    if not isinstance(response, dict):
        raise ValueError("API response envelope is missing")
    header = response.get("header")
    body = response.get("body")
    if not isinstance(header, dict) or not isinstance(body, dict):
        raise ValueError("API response header/body is malformed")
    container = body.get("items")
    item = container.get("item") if isinstance(container, dict) else None
    if isinstance(item, dict):
        rows = [item]
    elif isinstance(item, list):
        rows = item
    elif item in (None, []):
        rows = []
    else:
        raise ValueError("API item collection is malformed")
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError("API item is not an object")
    return header, body, rows


def read_page(page: PageFile, *, verify_hash: bool = True) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    raw = page.absolute_path.read_bytes()
    if verify_hash and sha256_bytes(raw) != page.raw_sha256:
        raise ValueError(f"raw page SHA-256 changed: {page.raw_path}")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError(f"raw page envelope is malformed: {page.raw_path}")
    return source_items(payload)


def page_integrity(page: PageFile) -> tuple[bool, str, list[dict[str, Any]]]:
    try:
        header, body, rows = read_page(page)
    except Exception as exc:
        return False, f"page_read_error:{type(exc).__name__}", []
    if str(header.get("resultCode")) not in ("00", "0"):
        return False, "api_result_code_not_success", rows
    try:
        body_page = int(body.get("pageNo") or 0)
        total = int(body.get("totalCount") or 0)
        page_size = int(body.get("numOfRows") or 0)
    except (TypeError, ValueError):
        return False, "pagination_header_not_integer", rows
    if page.page_no is not None and body_page != page.page_no:
        return False, "page_number_mismatch", rows
    if page.row_count != len(rows):
        return False, "manifest_item_count_mismatch", rows
    page.page_total_count = total
    page.page_size = page_size
    return True, "verified", rows


def month_bounds(month: str) -> tuple[date, date]:
    year, mon = int(month[:4]), int(month[4:6])
    first = date(year, mon, 1)
    if mon == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, mon + 1, 1)
    return first, date.fromordinal(next_month.toordinal() - 1)


def next_month(month: str) -> str:
    year, mon = int(month[:4]), int(month[4:6])
    return f"{year + (mon == 12):04d}{1 if mon == 12 else mon + 1:02d}"


def source_files_row(page: PageFile) -> dict[str, Any]:
    return {
        "raw_path": page.raw_path,
        "raw_sha256": page.raw_sha256,
        "source_page_no": page.page_no,
        "row_count": page.row_count,
        "source_row_count": page.row_count,
        "capture_id": page.capture_id,
        "source_captured_at": epoch_ms_to_utc_naive(page.captured_at_ms).isoformat(sep=" ") if page.captured_at_ms is not None else None,
        "capture_basis": page.capture_basis,
        "endpoint": page.endpoint,
        "is_selected": page.is_selected,
        "requested_at_ms": page.requested_at_ms,
        "retrieved_at_ms": page.retrieved_at_ms,
        "source_metadata_json": canonical_json(page.metadata),
        "integrity_status": page.integrity_status,
    }


def add_manifest_captures() -> tuple[list[Capture], list[PageFile], dict[str, str]]:
    if not MONTHLY_MANIFEST.is_file():
        raise FileNotFoundError(MONTHLY_MANIFEST)
    manifest_hash = file_sha256(MONTHLY_MANIFEST)
    events: list[dict[str, Any]] = []
    with MONTHLY_MANIFEST.open(encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                event = json.loads(line)
                if int(event.get("meet") or 0) in MEETS and START_DATE.strftime("%Y%m") <= str(event.get("month") or "") <= END_DATE.strftime("%Y%m"):
                    events.append(event)

    groups: dict[tuple[int, str], list[tuple[int, dict[str, Any], PageFile]]] = defaultdict(list)
    all_files: list[PageFile] = []
    event_page_candidates: list[tuple[int, dict[str, Any], PageFile]] = []
    for index, event in enumerate(events, start=1):
        raw_path, absolute = safe_source_path(str(event["path"]))
        declared_sha = str(event.get("sha256") or "")
        status = str(event.get("status") or "")
        recorded_ms = int(event["recorded_at_ms"]) if event.get("recorded_at_ms") is not None else None
        metadata = {
            "source_kind": "monthly_manifest",
            "manifest_status": status,
            "manifest_recorded_at_ms": recorded_ms,
            "manifest_item_count": int(event.get("item_count") or 0),
            "manifest_total_count": int(event.get("total_count") or 0),
            "file_sha256_verified": False,
            "manifest_sha256": manifest_hash,
        }
        file_hash = file_sha256(absolute)
        verified = file_hash == declared_sha
        metadata["file_sha256_verified"] = verified
        basis = (
            "monthly_manifest_download_recorded_at_ms_after_response"
            if status == "downloaded"
            else "monthly_manifest_cached_event_no_new_retrieval_time"
        )
        provisional_id = f"api18-archive-event-{index:05d}"
        page = PageFile(
            raw_path=raw_path,
            absolute_path=absolute,
            raw_sha256=declared_sha,
            page_no=int(event["page"]) if event.get("page") is not None else None,
            row_count=int(event.get("item_count") or 0),
            capture_id=provisional_id,
            capture_basis=basis,
            captured_at_ms=recorded_ms if status == "downloaded" else None,
            requested_at_ms=None,
            retrieved_at_ms=None,
            endpoint="API18_1",
            metadata=metadata,
            integrity_status="verified" if verified else "manifest_sha256_mismatch",
            page_month=str(event.get("month") or ""),
            page_meet=int(event.get("meet") or 0),
        )
        all_files.append(page)
        if status == "downloaded" and verified:
            event_page_candidates.append((index, event, page))
            groups[(page.page_meet or 0, page.page_month or "")].append((index, event, page))

    captures: list[Capture] = []
    chosen_event_indices: set[int] = set()
    for (meet, month), candidates in sorted(groups.items()):
        # Pick the newest actual download for each page. Cached ledger events
        # remain in the inventory but cannot advance capture recency.
        by_page: dict[int, tuple[int, dict[str, Any], PageFile]] = {}
        for candidate in candidates:
            idx, event, page = candidate
            pageno = int(event["page"])
            old = by_page.get(pageno)
            if old is None or int(event.get("recorded_at_ms") or 0) > int(old[1].get("recorded_at_ms") or 0):
                by_page[pageno] = candidate
        selected = [by_page[key] for key in sorted(by_page)]
        latest_ms = max((int(event.get("recorded_at_ms") or 0) for _, event, _ in selected), default=None)
        seed = "|".join(page.raw_sha256 for _, _, page in selected)
        capture_id = f"api18-monthly-m{meet}-{month}-{(sha256_bytes(seed.encode())[:10] if seed else 'empty')}"
        capture = Capture(
            capture_id=capture_id,
            source_kind="monthly_archive",
            meet=meet,
            capture_at_ms=latest_ms,
            basis="monthly_manifest_download_recorded_at_ms_after_response",
            month=month,
            pages=[page for _, _, page in selected],
            total_count=None,
        )
        for idx, event, page in selected:
            page.capture_id = capture_id
            page.capture_basis = capture.basis
            page.metadata["capture_id"] = capture_id
            chosen_event_indices.add(idx)
        capture.complete, capture.completeness_reason = validate_capture_pages(capture, expected_month=month)
        if capture.complete and capture.capture_at_ms:
            cap_day = datetime.fromtimestamp(capture.capture_at_ms / 1000, UTC).astimezone(KST).date()
            _, month_end = month_bounds(month)
            capture.effective_through = min(cap_day, month_end, END_DATE)
            capture.date_counts = count_capture_dates(capture, expected_month=month)
            first_month, _ = month_bounds(month)
            if capture.effective_through < first_month:
                capture.complete = False
                capture.completeness_reason = "capture_precedes_requested_month"
        captures.append(capture)

    # Earlier downloaded versions with the same month/page are retained as
    # source inventory entries, though only the selected current file version
    # participates in the complete monthly capture.
    for index, event, page in event_page_candidates:
        if index not in chosen_event_indices:
            event_id = f"api18-archive-version-{index:05d}"
            page.capture_id = event_id
            page.metadata["capture_id"] = event_id
            page.capture_basis = "monthly_manifest_older_download_version_not_selected"
            page.captured_at_ms = int(event["recorded_at_ms"]) if event.get("recorded_at_ms") is not None else None

    return captures, all_files, {"manifest_sha256": manifest_hash}


def validate_capture_pages(capture: Capture, *, expected_month: str | None = None, expected_date: str | None = None) -> tuple[bool, str]:
    if not capture.pages:
        return False, "no_verified_pages"
    total_values: set[int] = set()
    item_sum = 0
    row_date_ok = True
    meet_ok = True
    for page in capture.pages:
        good, reason, rows = page_integrity(page)
        page.integrity_status = reason
        if not good:
            return False, reason
        assert page.page_total_count is not None and page.page_size is not None
        total_values.add(page.page_total_count)
        item_sum += len(rows)
        for row in rows:
            try:
                event_date = parse_api_date(row.get("trDate"))
            except Exception:
                row_date_ok = False
                continue
            if expected_month and event_date.strftime("%Y%m") != expected_month:
                row_date_ok = False
            if expected_date and event_date.strftime("%Y%m%d") != expected_date:
                row_date_ok = False
            raw_meet = row.get("meet")
            parsed_meet = MEET_LABEL_CODE.get(str(raw_meet).strip()) if raw_meet is not None else None
            if parsed_meet != capture.meet:
                meet_ok = False
        page.page_date = expected_date
        page.page_month = expected_month
    if len(total_values) != 1:
        return False, "page_total_count_changed"
    total = next(iter(total_values))
    page_size = capture.pages[0].page_size or 1
    expected_pages = max(1, math.ceil(total / max(page_size, 1)))
    page_numbers = [page.page_no for page in capture.pages]
    if page_numbers != list(range(1, expected_pages + 1)):
        return False, "page_sequence_or_count_mismatch"
    if item_sum != total:
        return False, "response_item_count_does_not_match_total_count"
    if not row_date_ok:
        return False, "event_date_does_not_match_query_window"
    if not meet_ok:
        return False, "raw_meet_does_not_match_query_meet"
    capture.total_count = total
    return True, "complete_all_pages_hashes_headers_and_rows_verified"


def count_capture_dates(capture: Capture, *, expected_month: str | None = None) -> Counter[str]:
    counts: Counter[str] = Counter()
    for page in capture.pages:
        _, _, rows = read_page(page)
        for row in rows:
            event_date = parse_api_date(row.get("trDate"))
            if event_date < START_DATE or event_date > END_DATE:
                continue
            counts[event_date.isoformat()] += 1
    return counts


def add_recent_month_capture() -> tuple[list[Capture], list[PageFile], dict[str, str]]:
    if not RECENT_CAPTURE_MANIFEST.is_file():
        raise FileNotFoundError(RECENT_CAPTURE_MANIFEST)
    manifest_hash = file_sha256(RECENT_CAPTURE_MANIFEST)
    data = json.loads(RECENT_CAPTURE_MANIFEST.read_text(encoding="utf-8"))
    captures: list[Capture] = []
    files: list[PageFile] = []
    for record in data.get("records", []):
        if record.get("dataset") != "daily" or int(record.get("meet") or 0) not in MEETS:
            continue
        month = str(record.get("month") or "")
        if month != "202609":
            continue
        meet = int(record["meet"])
        pages: list[PageFile] = []
        request_times: list[int] = []
        retrieval_times: list[int] = []
        for item in record.get("pages", []):
            raw_path, absolute = safe_source_path(str(item["path"]))
            raw_sha = str(item["sha256"])
            requested = iso_kst_to_epoch_ms(item.get("requested_at_kst"))
            retrieved = iso_kst_to_epoch_ms(item.get("retrieved_at_kst"))
            if requested is not None:
                request_times.append(requested)
            if retrieved is not None:
                retrieval_times.append(retrieved)
            metadata = {
                "source_kind": "fresh_month_capture_manifest",
                "capture_manifest_sha256": manifest_hash,
                "request_time_kst": item.get("requested_at_kst"),
                "retrieval_time_kst": item.get("retrieved_at_kst"),
                "retrieval_time_basis": item.get("retrieved_at_basis"),
                "http_status": item.get("http_status"),
                "response_bytes": item.get("response_bytes"),
                "page_size": item.get("page_size"),
                "total_count": item.get("total_count"),
                "item_count": item.get("item_count"),
            }
            page = PageFile(
                raw_path=raw_path,
                absolute_path=absolute,
                raw_sha256=raw_sha,
                page_no=int(item["page"]) if item.get("page") is not None else None,
                row_count=int(item.get("item_count") or 0),
                capture_id="pending",
                capture_basis="fresh_month_capture_manifest_actual_http_request_and_retrieval_time",
                captured_at_ms=retrieved,
                requested_at_ms=requested,
                retrieved_at_ms=retrieved,
                endpoint="API18_1",
                metadata=metadata,
                integrity_status="verified" if file_sha256(absolute) == raw_sha else "manifest_sha256_mismatch",
                page_month=month,
                page_meet=meet,
            )
            files.append(page)
            pages.append(page)
        capture_at = max(retrieval_times) if retrieval_times else None
        seed = "|".join(page.raw_sha256 for page in pages)
        capture_id = f"api18-monthly-m{meet}-{month}-fresh-{sha256_bytes(seed.encode())[:10]}"
        for page in pages:
            page.capture_id = capture_id
            page.metadata["capture_id"] = capture_id
        capture = Capture(
            capture_id=capture_id,
            source_kind="fresh_month_capture",
            meet=meet,
            capture_at_ms=capture_at,
            basis="fresh_month_capture_manifest_actual_http_retrieval_time",
            pages=pages,
            month=month,
            request_at_ms=min(request_times) if request_times else None,
            retrieved_at_ms=capture_at,
        )
        capture.complete, capture.completeness_reason = validate_capture_pages(
            capture, expected_month=month,
        )
        capture.complete = capture.complete and bool(record.get("complete"))
        if capture.complete and capture.capture_at_ms:
            _, month_end = month_bounds(month)
            capture.effective_through = min(month_end, END_DATE)
            capture.date_counts = count_capture_dates(capture, expected_month=month)
        captures.append(capture)
    return captures, files, {"capture_manifest_sha256": manifest_hash}


def load_roster_ids() -> set[str]:
    core = duckdb.connect(str(CORE_DB.resolve()), read_only=True)
    try:
        core.execute("BEGIN TRANSACTION")
        values = core.execute(
            "SELECT DISTINCT entity_id_official_string FROM entity_reference_roster WHERE entity_type = ?",
            ["horse"],
        ).fetchall()
        core.execute("ROLLBACK")
        return {str(row[0]) for row in values if row[0] is not None and str(row[0]) != ""}
    finally:
        core.close()


def add_operational_daily_captures() -> tuple[list[Capture], list[PageFile], dict[str, Any]]:
    uri = f"file:{OPERATING_DB.resolve()}?mode=ro"
    db = sqlite3.connect(uri, uri=True, timeout=60)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA query_only=ON")
    db.execute("BEGIN")
    query = """
        SELECT sd.id, sd.ingestion_run_id, sd.requested_at_ms, sd.retrieved_at_ms,
               sd.http_status_code, sd.content_type, sd.response_bytes, sd.local_path,
               sd.sha256, sd.request_params_json, ir.status AS run_status
        FROM source_documents sd
        JOIN ingestion_runs ir ON ir.id = sd.ingestion_run_id
        WHERE ir.data_type = ? AND ir.source = ?
        ORDER BY sd.retrieved_at_ms, sd.id
    """
    source_rows = db.execute(query, ("horse_training", "data.go.kr/B551015/API18_1")).fetchall()
    groups: dict[tuple[int, str, int], list[tuple[sqlite3.Row, PageFile]]] = defaultdict(list)
    all_files: list[PageFile] = []
    query_date_counts: Counter[str] = Counter()
    queried_date_meets: set[tuple[str, int]] = set()
    for row in source_rows:
        params: dict[str, Any] = {}
        try:
            parsed_params = json.loads(row["request_params_json"])
            if isinstance(parsed_params, dict):
                params = parsed_params
        except (TypeError, ValueError):
            params = {}
        query_date = str(params.get("tr_date") or "")
        try:
            meet = int(params.get("meet"))
        except (TypeError, ValueError):
            meet = 0
        try:
            page_no = int(params.get("pageNo") or 1)
        except (TypeError, ValueError):
            page_no = None
        if len(query_date) != 8 or not query_date.isdigit():
            query_date = ""
        if query_date and len(query_date) == 8 and query_date.isdigit() and meet in MEETS:
            query_date_counts[query_date] += 1
            queried_date_meets.add((query_date, meet))
        raw_path, absolute = safe_source_path(str(row["local_path"]))
        metadata = {
            "source_kind": "operational_source_document",
            "source_document_id": int(row["id"]),
            "ingestion_run_id": int(row["ingestion_run_id"]),
            "run_status": str(row["run_status"]),
            "requested_at_ms": int(row["requested_at_ms"]) if row["requested_at_ms"] is not None else None,
            "retrieved_at_ms": int(row["retrieved_at_ms"]) if row["retrieved_at_ms"] is not None else None,
            "http_status_code": int(row["http_status_code"]) if row["http_status_code"] is not None else None,
            "content_type": row["content_type"],
            "response_bytes": int(row["response_bytes"] or 0),
        }
        captured_ms = int(row["retrieved_at_ms"]) if row["retrieved_at_ms"] is not None else None
        page = PageFile(
            raw_path=raw_path,
            absolute_path=absolute,
            raw_sha256=str(row["sha256"]),
            page_no=page_no,
            row_count=-1,
            capture_id=f"api18-daily-run-{int(row['ingestion_run_id'])}",
            capture_basis="operational_source_document_requested_at_ms_and_retrieved_at_ms",
            captured_at_ms=captured_ms,
            requested_at_ms=int(row["requested_at_ms"]) if row["requested_at_ms"] is not None else None,
            retrieved_at_ms=captured_ms,
            endpoint="API18_1",
            metadata=metadata,
            integrity_status="verified" if file_sha256(absolute) == str(row["sha256"]) else "source_document_sha256_mismatch",
            page_date=query_date or None,
            page_meet=meet if meet in MEETS else None,
        )
        all_files.append(page)
        if page.integrity_status == "verified":
            try:
                _, body, items = read_page(page)
                page.row_count = len(items)
                page.page_total_count = int(body.get("totalCount") or 0)
                page.page_size = int(body.get("numOfRows") or 0)
                if page.page_no is None:
                    page.page_no = int(body.get("pageNo") or 1)
            except Exception:
                page.integrity_status = "page_parse_error"
        groups[(int(row["ingestion_run_id"]), query_date, meet)].append((row, page))
    db.rollback()
    db.close()

    captures: list[Capture] = []
    for (run_id, query_date, meet), rows in sorted(groups.items()):
        pages = [page for _, page in rows]
        pages.sort(key=lambda page: (page.page_no or 0, page.raw_path))
        for page in pages:
            page.capture_id = f"api18-daily-run-{run_id}"
            page.metadata["capture_id"] = page.capture_id
        requested = [int(row["requested_at_ms"]) for row, _ in rows if row["requested_at_ms"] is not None]
        retrieved = [int(row["retrieved_at_ms"]) for row, _ in rows if row["retrieved_at_ms"] is not None]
        capture_at = max(retrieved) if retrieved else None
        capture = Capture(
            capture_id=f"api18-daily-run-{run_id}",
            source_kind="daily_exact_date_source_document",
            meet=meet,
            capture_at_ms=capture_at,
            basis="operational_source_document_requested_at_ms_and_retrieved_at_ms",
            pages=pages,
            query_date=query_date or None,
            request_at_ms=min(requested) if requested else None,
            retrieved_at_ms=capture_at,
        )
        if meet not in MEETS or not query_date or len(query_date) != 8 or not query_date.isdigit():
            capture.complete, capture.completeness_reason = False, "query_date_or_meet_unavailable"
        elif any(str(row["run_status"]) != "completed" for row, _ in rows):
            capture.complete, capture.completeness_reason = False, "ingestion_run_not_completed"
        elif any(row["http_status_code"] != 200 for row, _ in rows):
            capture.complete, capture.completeness_reason = False, "http_status_not_200"
        else:
            capture.complete, capture.completeness_reason = validate_capture_pages(
                capture, expected_date=query_date,
            )
            if capture.complete:
                capture.date_counts = Counter({query_date[:4] + "-" + query_date[4:6] + "-" + query_date[6:]: capture.total_count or 0})
                capture.effective_through = parse_api_date(query_date)
        captures.append(capture)
    return captures, all_files, {
        "operational_db_path": OPERATING_DB.relative_to(ROOT).as_posix(),
        "source_document_rows": len(source_rows),
        "distinct_exact_date_meet_queries": len(queried_date_meets),
    }


def build_capture_set() -> tuple[list[Capture], list[PageFile], dict[str, Any]]:
    captures: list[Capture] = []
    files: list[PageFile] = []
    source_catalog: dict[str, Any] = {}
    monthly, monthly_files, monthly_meta = add_manifest_captures()
    captures.extend(monthly)
    files.extend(monthly_files)
    source_catalog.update(monthly_meta)
    recent, recent_files, recent_meta = add_recent_month_capture()
    captures.extend(recent)
    files.extend(recent_files)
    source_catalog.update(recent_meta)
    daily, daily_files, daily_meta = add_operational_daily_captures()
    captures.extend(daily)
    files.extend(daily_files)
    source_catalog.update(daily_meta)
    return captures, files, source_catalog


def scope_dates() -> Iterator[date]:
    current = START_DATE
    while current <= END_DATE:
        yield current
        current = date.fromordinal(current.toordinal() + 1)


def select_coverage(captures: list[Capture]) -> tuple[dict[tuple[str, int], Capture | None], list[dict[str, Any]]]:
    candidates: dict[tuple[str, int], list[Capture]] = defaultdict(list)
    incomplete: dict[tuple[str, int], list[Capture]] = defaultdict(list)
    for capture in captures:
        if capture.source_kind in ("monthly_archive", "fresh_month_capture"):
            if capture.month is None:
                continue
            first, _ = month_bounds(capture.month)
            last = capture.effective_through
            if last is None:
                if capture.capture_at_ms is None:
                    continue
                capture_date = datetime.fromtimestamp(capture.capture_at_ms / 1000, UTC).astimezone(KST).date()
                _, month_end = month_bounds(capture.month)
                last = min(capture_date, month_end, END_DATE)
            current = max(first, START_DATE)
            while current <= min(last, END_DATE):
                key = (current.isoformat(), capture.meet)
                (candidates if capture.complete else incomplete)[key].append(capture)
                current = date.fromordinal(current.toordinal() + 1)
        elif capture.source_kind == "daily_exact_date_source_document" and capture.query_date:
            try:
                event_date = parse_api_date(capture.query_date)
            except ValueError:
                continue
            if START_DATE <= event_date <= END_DATE:
                key = (event_date.isoformat(), capture.meet)
                (candidates if capture.complete else incomplete)[key].append(capture)

    selected: dict[tuple[str, int], Capture | None] = {}
    coverage: list[dict[str, Any]] = []
    for current in scope_dates():
        iso_date = current.isoformat()
        for meet in MEETS:
            key = (iso_date, meet)
            options = candidates.get(key, [])
            winner = max(options, key=lambda item: item.capture_at_ms or -1) if options else None
            selected[key] = winner
            if winner is not None:
                winner.selected_scope_dates.add(iso_date)
                row_count = winner.date_counts.get(iso_date, 0)
                source_desc = (
                    "complete_exact_date_query"
                    if winner.source_kind == "daily_exact_date_source_document"
                    else "complete_month_query_filtered_by_trDate_through_capture_cutoff"
                )
                coverage.append(
                    {
                        "event_date": iso_date,
                        "meet": str(meet),
                        "coverage_status": "complete_rows" if row_count else "complete_zero_rows",
                        "selected_capture_id": winner.capture_id,
                        "selection_rule": "latest_complete_capture_by_actual_retrieval_or_manifest_recorded_time",
                        "coverage_basis": source_desc,
                        "expected_rows": row_count,
                        "observed_rows": row_count,
                    }
                )
            else:
                observed_incomplete = incomplete.get(key, [])
                coverage.append(
                    {
                        "event_date": iso_date,
                        "meet": str(meet),
                        "coverage_status": "incomplete_capture" if observed_incomplete else "missing_capture",
                        "selected_capture_id": None,
                        "selection_rule": "no_complete_capture_available",
                        "coverage_basis": ";".join(sorted({item.completeness_reason for item in observed_incomplete})) if observed_incomplete else "no_query_or_month_capture_covering_date",
                        "expected_rows": None,
                        "observed_rows": 0,
                    }
                )
    return selected, coverage


def load_core_roster_ids() -> set[str]:
    return load_roster_ids()


def parse_optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def time_diagnostics(item: dict[str, Any], event_date: date) -> tuple[list[str], int | None, int | None, int | None]:
    flags: list[str] = []
    starts = item.get("stTime")
    ends = item.get("spTime")
    duration = parse_optional_int(item.get("trTerm"))
    start_dt: datetime | None = None
    end_dt: datetime | None = None
    if starts in (None, ""):
        flags.append("start_time_missing")
    else:
        try:
            start_dt = datetime.strptime(str(starts), "%Y%m%d%H%M%S")
            if start_dt.date() != event_date:
                flags.append("start_time_date_mismatch")
        except ValueError:
            flags.append("start_time_invalid")
    if ends in (None, ""):
        flags.append("end_time_missing")
    else:
        try:
            end_dt = datetime.strptime(str(ends), "%Y%m%d%H%M%S")
            if end_dt.date() != event_date:
                flags.append("end_time_date_mismatch")
        except ValueError:
            flags.append("end_time_invalid")
    elapsed = int((end_dt - start_dt).total_seconds()) if start_dt is not None and end_dt is not None else None
    if elapsed is not None and elapsed < 0:
        flags.append("end_before_start")
    if item.get("trTerm") not in (None, "") and duration is None:
        flags.append("duration_not_integer")
    if duration is None:
        flags.append("duration_missing")
    elif duration < 0:
        flags.append("duration_negative")
    elif duration == 0:
        flags.append("duration_zero")
    difference = duration - elapsed if duration is not None and elapsed is not None else None
    if difference not in (None, 0):
        flags.append("duration_differs_from_raw_time_delta")
    return flags, elapsed, duration, difference


def signature_for_item(item: dict[str, Any], meet: int, event_date: date, official_id: str | None) -> str:
    natural_key = [
        official_id or "",
        str(meet),
        str(item.get("trDate") or ""),
        "" if item.get("stTime") in (None, "") else str(item.get("stTime")),
        "" if item.get("spTime") in (None, "") else str(item.get("spTime")),
    ]
    return sha256_bytes(canonical_json(natural_key).encode("utf-8"))


def iter_selected_items(
    captures: list[Capture], selected: dict[tuple[str, int], Capture | None],
) -> Iterator[tuple[Capture, PageFile, int, dict[str, Any], date]]:
    for capture in sorted(captures, key=lambda value: (value.capture_at_ms or 0, value.capture_id)):
        if not capture.complete or not capture.selected_scope_dates:
            continue
        for page in sorted(capture.pages, key=lambda value: (value.page_no or 0, value.raw_path)):
            _, _, items = read_page(page)
            for row_number, item in enumerate(items, start=1):
                try:
                    event_date = parse_api_date(item.get("trDate"))
                except ValueError:
                    continue
                if not (START_DATE <= event_date <= END_DATE):
                    continue
                key = (event_date.isoformat(), capture.meet)
                if selected.get(key) is not capture:
                    continue
                yield capture, page, row_number, item, event_date


def mkdirs() -> None:
    DAILY.mkdir(parents=True, exist_ok=True)
    INPUT.mkdir(parents=True, exist_ok=True)


def append_batch(writer: pq.ParquetWriter, columns: dict[str, list[Any]], schema: pa.Schema) -> None:
    if not columns["observation_id"]:
        return
    table = pa.Table.from_pydict(columns, schema=schema)
    writer.write_table(table, row_group_size=BATCH_SIZE)
    for values in columns.values():
        values.clear()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".partial", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def atomic_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".partial", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def make_stage_row(
    capture: Capture,
    page: PageFile,
    row_number: int,
    item: dict[str, Any],
    event_date: date,
    roster: set[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    raw_id_value = item.get("hrNo")
    official_id = None if raw_id_value is None or str(raw_id_value).strip() == "" else str(raw_id_value)
    raw_name_value = item.get("hrName")
    raw_name = None if raw_name_value is None else str(raw_name_value)
    link_status = (
        "missing_official_id"
        if official_id is None
        else "exact_core_roster_match"
        if official_id in roster
        else "unmatched_official_id"
    )
    raw_payload = canonical_json(item)
    payload_hash = sha256_bytes(raw_payload.encode("utf-8"))
    natural_signature = signature_for_item(item, capture.meet, event_date, official_id)
    qa_flags, elapsed, duration, difference = time_diagnostics(item, event_date)
    if link_status == "missing_official_id":
        qa_flags.append("missing_official_id")
    raw_meet = item.get("meet")
    if raw_meet is None or str(raw_meet).strip() == "":
        qa_flags.append("raw_meet_label_missing")
    elif MEET_LABEL_CODE.get(str(raw_meet).strip()) != capture.meet:
        qa_flags.append("raw_meet_label_query_mismatch")
    observation_id = f"api18_1:{capture.capture_id}:{page.raw_sha256}:p{page.page_no or 0}:r{row_number}"
    base = {
        "dataset": "daily_training",
        "observation_id": observation_id,
        "event_date": event_date,
        "meet": str(capture.meet),
        "official_horse_id": official_id,
        "raw_name": raw_name,
        "raw_path": page.raw_path,
        "raw_sha256": page.raw_sha256,
        "source_page_no": page.page_no,
        "source_row_no": row_number,
        "source_captured_at": epoch_ms_to_utc_naive(page.captured_at_ms),
        "capture_basis": page.capture_basis,
        "endpoint": "API18_1",
        "raw_payload_json": raw_payload,
        "typed_fields_json": raw_payload,
        "link_status": link_status,
        "linked_core_horse_id": official_id if link_status == "exact_core_roster_match" else None,
        "qa_flags_json": canonical_json(sorted(set(qa_flags))),
        "capture_id": capture.capture_id,
    }
    stage = dict(base)
    stage["natural_key_signature"] = natural_signature
    stage["payload_sha256"] = payload_hash
    qa = {
        "observation_id": observation_id,
        "event_date": event_date.isoformat(),
        "meet": str(capture.meet),
        "official_horse_id": official_id,
        "raw_name": raw_name,
        "raw_path": page.raw_path,
        "raw_sha256": page.raw_sha256,
        "source_page_no": page.page_no,
        "source_row_no": row_number,
        "natural_key_signature": natural_signature,
        "payload_sha256": payload_hash,
        "raw_started_at": item.get("stTime"),
        "raw_ended_at": item.get("spTime"),
        "raw_duration_seconds": item.get("trTerm"),
        "raw_trainer_name": item.get("trName"),
        "raw_rider_type": item.get("prGubun"),
        "raw_rider_id": item.get("prNo"),
        "raw_canter_count": item.get("run1Cnt"),
        "raw_gallop_count": item.get("run2Cnt"),
        "raw_time_delta_seconds": elapsed,
        "duration_delta_seconds": difference,
        "qa_flags_json": canonical_json(sorted(set(qa_flags))),
    }
    return stage, qa


def read_horse_roster() -> set[str]:
    return load_core_roster_ids()


def write_stage_parquet(
    captures: list[Capture],
    selected: dict[tuple[str, int], Capture | None],
    roster: set[str],
    stage_path: Path,
) -> tuple[int, dict[str, int], dict[str, dict[str, Any]], list[dict[str, Any]]]:
    row_count = 0
    link_counts: Counter[str] = Counter()
    horses: dict[str, dict[str, Any]] = {}
    duration_qa: list[dict[str, Any]] = []
    columns: dict[str, list[Any]] = {name: [] for name in STAGE_SCHEMA.names}
    writer = pq.ParquetWriter(
        stage_path,
        STAGE_SCHEMA,
        compression="zstd",
        compression_level=7,
        use_dictionary=["dataset", "meet", "capture_basis", "endpoint", "link_status", "capture_id"],
        write_statistics=True,
    )
    try:
        for capture, page, row_number, item, event_date in iter_selected_items(captures, selected):
            stage, qa = make_stage_row(capture, page, row_number, item, event_date, roster)
            for name in STAGE_SCHEMA.names:
                columns[name].append(stage[name])
            row_count += 1
            link_counts[stage["link_status"]] += 1
            official_id = stage["official_horse_id"]
            if official_id is not None:
                horse = horses.setdefault(
                    official_id,
                    {
                        "row_count": 0,
                        "first_event_date": event_date.isoformat(),
                        "last_event_date": event_date.isoformat(),
                        "meets": set(),
                        "names": set(),
                        "link_status": stage["link_status"],
                    },
                )
                horse["row_count"] += 1
                horse["first_event_date"] = min(horse["first_event_date"], event_date.isoformat())
                horse["last_event_date"] = max(horse["last_event_date"], event_date.isoformat())
                horse["meets"].add(stage["meet"])
                if stage["raw_name"] is not None:
                    horse["names"].add(stage["raw_name"])
            if stage["qa_flags_json"] != "[]":
                duration_qa.append(qa)
            if len(columns["observation_id"]) >= BATCH_SIZE:
                append_batch(writer, columns, STAGE_SCHEMA)
        append_batch(writer, columns, STAGE_SCHEMA)
    finally:
        writer.close()
    return row_count, dict(link_counts), horses, duration_qa


def duplicate_signatures(stage_path: Path) -> tuple[set[str], set[tuple[str, str]], list[dict[str, Any]], list[dict[str, Any]]]:
    temporary_dir = Path(tempfile.mkdtemp(prefix="api18-duckdb-", dir="/private/tmp"))
    con = duckdb.connect(":memory:")
    try:
        con.execute("SET memory_limit='4GB'")
        con.execute(f"SET temp_directory='{temporary_dir.as_posix()}'")
        con.from_parquet(str(stage_path)).create_view("daily_stage")
        key_rows = con.execute(
            """
            SELECT natural_key_signature, count(*) AS row_count,
                   count(DISTINCT payload_sha256) AS payload_variants
            FROM daily_stage
            GROUP BY natural_key_signature
            HAVING count(*) > 1
            """
        ).fetchall()
        conflict_keys = {str(row[0]) for row in key_rows if int(row[2]) > 1}
        pair_rows = con.execute(
            """
            SELECT natural_key_signature, payload_sha256, count(*) AS repeated_rows
            FROM daily_stage
            GROUP BY natural_key_signature, payload_sha256
            HAVING count(*) > 1
            """
        ).fetchall()
        exact_pairs = {(str(row[0]), str(row[1])) for row in pair_rows}
        conflict_details: list[dict[str, Any]] = []
        exact_details: list[dict[str, Any]] = []
        if conflict_keys:
            con.register("conflict_keys", pa.table({"natural_key_signature": sorted(conflict_keys)}))
            result = con.execute(
                """
                SELECT s.observation_id, s.event_date, s.meet, s.official_horse_id,
                       s.raw_name, s.raw_path, s.raw_sha256, s.source_page_no,
                       s.source_row_no, s.natural_key_signature, s.payload_sha256,
                       s.typed_fields_json, s.qa_flags_json
                FROM daily_stage s JOIN conflict_keys k USING (natural_key_signature)
                ORDER BY s.natural_key_signature, s.payload_sha256, s.observation_id
                """
            ).fetchall()
            cols = [desc[0] for desc in con.description]
            conflict_details = [dict(zip(cols, row)) for row in result]
        if exact_pairs:
            con.register(
                "exact_pairs",
                pa.table(
                    {
                        "natural_key_signature": [key for key, _ in sorted(exact_pairs)],
                        "payload_sha256": [payload for _, payload in sorted(exact_pairs)],
                    }
                ),
            )
            result = con.execute(
                """
                SELECT s.observation_id, s.event_date, s.meet, s.official_horse_id,
                       s.raw_name, s.raw_path, s.raw_sha256, s.source_page_no,
                       s.source_row_no, s.natural_key_signature, s.payload_sha256,
                       s.typed_fields_json, s.qa_flags_json
                FROM daily_stage s JOIN exact_pairs e
                  USING (natural_key_signature, payload_sha256)
                ORDER BY s.natural_key_signature, s.payload_sha256, s.observation_id
                """
            ).fetchall()
            cols = [desc[0] for desc in con.description]
            exact_details = [dict(zip(cols, row)) for row in result]
        return conflict_keys, exact_pairs, conflict_details, exact_details
    finally:
        con.close()
        shutil.rmtree(temporary_dir, ignore_errors=True)


def rewrite_final_parquet(
    stage_path: Path,
    parquet_path: Path,
    conflict_keys: set[str],
    exact_pairs: set[tuple[str, str]],
) -> None:
    temporary = parquet_path.with_name(f".{parquet_path.name}.{os.getpid()}.partial")
    reader = pq.ParquetFile(stage_path)
    writer = pq.ParquetWriter(
        temporary,
        FINAL_SCHEMA,
        compression="zstd",
        compression_level=7,
        use_dictionary=["dataset", "meet", "capture_basis", "endpoint", "link_status", "capture_id"],
        write_statistics=True,
    )
    try:
        for batch in reader.iter_batches(batch_size=BATCH_SIZE):
            data = batch.to_pydict()
            for idx, flags_json in enumerate(data["qa_flags_json"]):
                flags = json.loads(flags_json)
                signature = data["natural_key_signature"][idx]
                payload_hash = data["payload_sha256"][idx]
                if signature in conflict_keys:
                    flags.append("nonidentical_natural_key_variant")
                if (signature, payload_hash) in exact_pairs:
                    flags.append("exact_repeat_same_payload")
                data["qa_flags_json"][idx] = canonical_json(sorted(set(flags)))
            final_data = {name: data[name] for name in FINAL_SCHEMA.names}
            writer.write_table(pa.Table.from_pydict(final_data, schema=FINAL_SCHEMA), row_group_size=BATCH_SIZE)
        writer.close()
        with temporary.open("rb") as stream:
            os.fsync(stream.fileno())
        os.replace(temporary, parquet_path)
    except Exception:
        writer.close()
        temporary.unlink(missing_ok=True)
        raise


def qa_csv_row(detail: dict[str, Any], kind: str) -> dict[str, Any]:
    typed: dict[str, Any] = {}
    try:
        typed = json.loads(detail.get("typed_fields_json") or "{}")
    except (TypeError, ValueError):
        typed = {}
    return {
        "conflict_type": kind,
        "observation_id": detail.get("observation_id"),
        "event_date": str(detail.get("event_date")),
        "meet": detail.get("meet"),
        "official_horse_id": detail.get("official_horse_id"),
        "raw_name": detail.get("raw_name"),
        "raw_path": detail.get("raw_path"),
        "raw_sha256": detail.get("raw_sha256"),
        "source_page_no": detail.get("source_page_no"),
        "source_row_no": detail.get("source_row_no"),
        "natural_key_signature": detail.get("natural_key_signature"),
        "payload_sha256": detail.get("payload_sha256"),
        "raw_started_at": typed.get("stTime"),
        "raw_ended_at": typed.get("spTime"),
        "raw_duration_seconds": typed.get("trTerm"),
        "raw_trainer_name": typed.get("trName"),
        "raw_rider_type": typed.get("prGubun"),
        "raw_rider_id": typed.get("prNo"),
        "raw_canter_count": typed.get("run1Cnt"),
        "raw_gallop_count": typed.get("run2Cnt"),
        "qa_flags_json": detail.get("qa_flags_json"),
    }


def finalize_qa_rows(
    duration_qa: list[dict[str, Any]],
    conflict_details: list[dict[str, Any]],
    exact_details: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for detail in duration_qa:
        flags = json.loads(detail["qa_flags_json"])
        if any(flag != "missing_official_id" for flag in flags):
            rows[detail["observation_id"]] = qa_csv_row(detail, ";".join(flags))
    for detail in conflict_details:
        rows[detail["observation_id"]] = qa_csv_row(detail, "nonidentical_natural_key_variant")
    for detail in exact_details:
        rows[detail["observation_id"]] = qa_csv_row(detail, "exact_repeat_same_payload")
    return sorted(rows.values(), key=lambda row: (row.get("event_date") or "", row.get("meet") or "", row.get("observation_id") or ""))


def coverage_counts(coverage: list[dict[str, Any]]) -> dict[str, int]:
    return dict(Counter(row["coverage_status"] for row in coverage))


def build_horse_inventory(horses: dict[str, dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    all_rows: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []
    for official_id, info in sorted(horses.items()):
        row = {
            "official_horse_id": official_id,
            "link_status": info["link_status"],
            "linked_core_horse_id": official_id if info["link_status"] == "exact_core_roster_match" else None,
            "row_count": info["row_count"],
            "first_event_date": info["first_event_date"],
            "last_event_date": info["last_event_date"],
            "meets_json": canonical_json(sorted(info["meets"])),
            "raw_name_variants_json": canonical_json(sorted(info["names"])),
        }
        all_rows.append(row)
        if info["link_status"] != "exact_core_roster_match":
            unmatched.append(row)
    return all_rows, unmatched


def write_readme(
    *, row_count: int, coverage: list[dict[str, Any]], file_count: int,
    captures: list[Capture], link_counts: dict[str, int], qa_rows: list[dict[str, Any]],
    conflict_count: int, exact_count: int, parquet_hash: str,
) -> None:
    counts = coverage_counts(coverage)
    selected_capture_count = sum(bool(capture.selected_scope_dates) for capture in captures)
    text = f"""# API18_1 daily training source reconstruction

Scope: event dates {START_DATE.isoformat()} through {END_DATE.isoformat()}, meet 1 (Seoul) and meet 3 (KRA raw region label retained in each source row). Meet 3 is not split into a physical racecourse. No Jeju meet or hill training is included.

The reconstruction uses the local API18_1 monthly page archive, exact-date API18_1 pages referenced by operating `source_documents`/`ingestion_runs`, and the fresh complete 2026-09 monthly capture. It makes no network requests and does not write to the operating SQLite database or core DuckDB.

## Output

- Parquet: `../loader/input/daily_training.parquet`
- Inventory: `../loader/input/daily_training_inventory.json`
- Date-by-meet coverage: `date_meet_coverage.csv`
- QA and raw natural-key conflicts: `qa_conflicts.csv`
- Exact official-ID link inventory: `horse_link_inventory.csv`
- Unmatched official-ID ledger: `unmatched_official_ids.csv`
- Selected and examined batches: `selected_capture_batches.json`

The Parquet contains {row_count:,} raw observations from {file_count:,} source page files. Its SHA-256 is `{parquet_hash}`. The inventory retains selected and older capture metadata, per-page hashes, pagination counts, and request/retrieval time basis. Historical monthly archive timestamps come from `manifest.recorded_at_ms` after download; the one cached ledger event is not treated as a later HTTP capture. Exact-date source documents retain their stored request and retrieval times. The fresh September monthly capture uses its recorded HTTP request/retrieval timestamps.

All {len(coverage):,} date-by-meet cells have a coverage record: {counts.get('complete_rows', 0):,} with rows, {counts.get('complete_zero_rows', 0):,} complete zero-row cells, {counts.get('missing_capture', 0):,} missing, and {counts.get('incomplete_capture', 0):,} with only incomplete captures. Selection uses the latest complete capture for each date and meet. Month responses cover dates no later than the capture cutoff; rows after {END_DATE.isoformat()} are excluded from the research Parquet even when present in the complete September response.

## Preservation and QA

`raw_payload_json` and `typed_fields_json` contain the complete canonicalized API item with all original keys, values, and JSON value types; missing fields are not filled. Raw response files remain untouched. Each observation ID includes its capture ID, source page hash, page number, and one-based row number, so exact repeated rows and nonidentical natural-key variants remain separate observations.

Core links use exact official horse ID equality against `entity_reference_roster.entity_id_official_string` where `entity_type='horse'`. No name-based linking is used. Row counts by link status: {canonical_json(link_counts)}. The unmatched ledger preserves every unmatched official ID and its observed raw name variants.

The QA file has {len(qa_rows):,} affected observations, including {conflict_count:,} rows in nonidentical same-natural-key groups and {exact_count:,} exact repeated payload rows. Time QA retains negative and zero `trTerm`, start/end ordering, raw-time date validity, and any difference between `trTerm` and the raw start/end time delta. No rollover or absolute-value correction is applied.

## Rebuild

Run `.venv/bin/python thoroughbred/research/20261002_training_three_v1/daily/build_daily.py` from the repository root. The builder reads archived JSON using JSON parsing, opens both databases read-only, validates source hashes and pagination, and writes the Parquet and inventories atomically.
"""
    path = DAILY / "README.md"
    temporary = path.with_suffix(".md.partial")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def main() -> None:
    mkdirs()
    parquet_path = INPUT / "daily_training.parquet"
    inventory_path = INPUT / "daily_training_inventory.json"
    stage_path = INPUT / f".daily_training_stage_{os.getpid()}.parquet"
    captures, files, source_catalog = build_capture_set()
    selected, coverage = select_coverage(captures)
    roster = read_horse_roster()
    row_count, link_counts, horses, duration_qa = write_stage_parquet(captures, selected, roster, stage_path)
    conflict_keys, exact_pairs, conflict_details, exact_details = duplicate_signatures(stage_path)
    rewrite_final_parquet(stage_path, parquet_path, conflict_keys, exact_pairs)
    stage_path.unlink(missing_ok=True)
    parquet_hash = file_sha256(parquet_path)
    qa_rows = finalize_qa_rows(duration_qa, conflict_details, exact_details)
    horse_rows, unmatched_rows = build_horse_inventory(horses)
    atomic_csv(
        DAILY / "qa_conflicts.csv",
        qa_rows,
        ["conflict_type", "observation_id", "event_date", "meet", "official_horse_id", "raw_name", "raw_path", "raw_sha256", "source_page_no", "source_row_no", "natural_key_signature", "payload_sha256", "raw_started_at", "raw_ended_at", "raw_duration_seconds", "raw_trainer_name", "raw_rider_type", "raw_rider_id", "raw_canter_count", "raw_gallop_count", "raw_time_delta_seconds", "duration_delta_seconds", "qa_flags_json"],
    )
    atomic_csv(
        DAILY / "date_meet_coverage.csv",
        coverage,
        ["event_date", "meet", "coverage_status", "selected_capture_id", "selection_rule", "coverage_basis", "expected_rows", "observed_rows"],
    )
    atomic_csv(
        DAILY / "horse_link_inventory.csv",
        horse_rows,
        ["official_horse_id", "link_status", "linked_core_horse_id", "row_count", "first_event_date", "last_event_date", "meets_json", "raw_name_variants_json"],
    )
    atomic_csv(
        DAILY / "unmatched_official_ids.csv",
        unmatched_rows,
        ["official_horse_id", "link_status", "linked_core_horse_id", "row_count", "first_event_date", "last_event_date", "meets_json", "raw_name_variants_json"],
    )
    selected_batches = []
    for capture in sorted(captures, key=lambda value: (value.capture_at_ms or 0, value.capture_id)):
        selected_batches.append(
            {
                "capture_id": capture.capture_id,
                "source_kind": capture.source_kind,
                "meet": str(capture.meet),
                "query_month": capture.month,
                "query_date": capture.query_date,
                "complete": capture.complete,
                "completeness_reason": capture.completeness_reason,
                "capture_at_utc": epoch_ms_to_utc_naive(capture.capture_at_ms).isoformat(sep=" ") if capture.capture_at_ms else None,
                "request_at_ms": capture.request_at_ms,
                "retrieved_at_ms": capture.retrieved_at_ms,
                "capture_time_basis": capture.basis,
                "effective_through": capture.effective_through.isoformat() if capture.effective_through else None,
                "source_page_count": len(capture.pages),
                "source_item_count": capture.total_count,
                "selected_scope_date_count": len(capture.selected_scope_dates),
                "source_page_paths": [page.raw_path for page in capture.pages],
            }
        )
    atomic_json(DAILY / "selected_capture_batches.json", selected_batches)

    for page in files:
        page.is_selected = any(
            capture.capture_id == page.capture_id and bool(capture.selected_scope_dates)
            for capture in captures
        )
    source_file_inventory = [source_files_row(page) for page in files]
    inventory = {
        "schema_version": 1,
        "dataset": "daily_training",
        "endpoint": "API18_1",
        "scope_start": START_DATE.isoformat(),
        "scope_end": END_DATE.isoformat(),
        "meets": ["1", "3"],
        "row_count": row_count,
        "parquet_path": parquet_path.relative_to(ROOT).as_posix(),
        "parquet_sha256": parquet_hash,
        "source_catalog": source_catalog,
        "source_files": source_file_inventory,
        "date_coverage": coverage,
        "selected_capture_batches": selected_batches,
        "link_status_counts": link_counts,
        "horse_id_count": len(horse_rows),
        "unmatched_official_id_count": len(unmatched_rows),
        "qa_summary": {
            "affected_observation_rows": len(qa_rows),
            "nonidentical_natural_key_rows": len(conflict_details),
            "nonidentical_natural_key_groups": len(conflict_keys),
            "exact_repeat_rows": len(exact_details),
            "exact_repeat_payload_groups": len(exact_pairs),
            "flag_counts": dict(Counter(flag for row in qa_rows for flag in str(row.get("conflict_type") or "").split(";"))),
        },
        "output_rules": {
            "raw_payload_json": "complete source API item, canonical JSON key order, original values and JSON types retained",
            "typed_fields_json": "complete source API item, no missing fields filled",
            "row_identity": "capture_id + source page SHA-256 + page number + one-based row number",
            "horse_linking": "exact official ID only against entity_reference_roster type horse; no name linking",
            "meet_3": "retained as KRA meet code 3 with raw venue label in payload; physical course not inferred",
            "date_cutoff": "events after 2026-09-29 excluded",
            "monthly_capture_time": "downloaded manifest record time used as approximate post-response capture time; cached events do not advance recency",
            "parquet_timestamp": "timezone-naive UTC; source timestamp basis and raw request/retrieval milliseconds remain in source_files",
        },
    }
    atomic_json(inventory_path, inventory)
    write_readme(
        row_count=row_count,
        coverage=coverage,
        file_count=len(files),
        captures=captures,
        link_counts=link_counts,
        qa_rows=qa_rows,
        conflict_count=len(conflict_details),
        exact_count=len(exact_details),
        parquet_hash=parquet_hash,
    )
    print(json.dumps({
        "status": "complete",
        "dataset": "daily_training",
        "row_count": row_count,
        "parquet_path": parquet_path.relative_to(ROOT).as_posix(),
        "parquet_sha256": parquet_hash,
        "coverage_counts": coverage_counts(coverage),
        "capture_count": len(captures),
        "selected_capture_count": sum(bool(capture.selected_scope_dates) for capture in captures),
        "source_file_count": len(files),
        "link_status_counts": link_counts,
        "natural_key_collision_groups": len(conflict_keys),
        "exact_repeat_groups": len(exact_pairs),
        "qa_observation_rows": len(qa_rows),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
