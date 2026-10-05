#!/usr/bin/env python3
"""Reconstruct raw API22_1 start and API216 swim observations from local captures."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import sqlite3
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator
from zoneinfo import ZoneInfo

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[4]
RESEARCH = ROOT / "thoroughbred/research/20261002_training_three_v1"
HERE = RESEARCH / "start_swim"
INPUT = RESEARCH / "loader/input"
START_MANIFEST = ROOT / "data/raw/kra_api_monthly/start_training/manifest.jsonl"
RECENT_MANIFEST = RESEARCH / "recent_raw/capture_manifest.json"
OPERATING_DB = ROOT / "data/horse_racing.sqlite3"
CORE_DB = ROOT / "thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb"
START_DATE = date(2010, 1, 1)
END_DATE = date(2026, 9, 29)
MEETS = (1, 3)
KST = ZoneInfo("Asia/Seoul")
UTC = timezone.utc
BATCH_SIZE = 8192

SCHEMA = pa.schema([
    ("dataset", pa.string()), ("observation_id", pa.string()), ("event_date", pa.date32()),
    ("meet", pa.string()), ("official_horse_id", pa.string()), ("raw_name", pa.string()),
    ("raw_path", pa.string()), ("raw_sha256", pa.string()), ("source_page_no", pa.int32()),
    ("source_row_no", pa.int32()), ("source_captured_at", pa.timestamp("us")),
    ("capture_basis", pa.string()), ("endpoint", pa.string()), ("raw_payload_json", pa.string()),
    ("typed_fields_json", pa.string()), ("link_status", pa.string()),
    ("linked_core_horse_id", pa.string()), ("qa_flags_json", pa.string()),
    ("capture_id", pa.string()),
])

MEET_CODE = {
    "1": 1, "서울": 1, "3": 3, "영남": 3, "부산경남": 3, "부경": 3,
}


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def safe_path(raw_path: str) -> tuple[str, Path]:
    value = Path(raw_path)
    full = value.resolve(strict=True) if value.is_absolute() else (ROOT / value).resolve(strict=True)
    if not full.is_relative_to(ROOT.resolve(strict=True)) or not full.is_file():
        raise ValueError("raw source path is missing or outside the repository")
    return full.relative_to(ROOT).as_posix(), full


def utc_naive(ms: int | None) -> datetime | None:
    return datetime.fromtimestamp(ms / 1000, UTC).replace(tzinfo=None) if ms is not None else None


def utc_text(ms: int | None) -> str | None:
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000, UTC).isoformat(timespec="milliseconds") + "Z"


def kst_date(ms: int | None) -> date | None:
    return datetime.fromtimestamp(ms / 1000, UTC).astimezone(KST).date() if ms is not None else None


def api_date(value: Any) -> date:
    raw = str(value or "")
    if len(raw) != 8 or not raw.isdigit():
        raise ValueError("invalid raw trDate")
    return date(int(raw[:4]), int(raw[4:6]), int(raw[6:8]))


def meet_code(value: Any) -> int | None:
    return MEET_CODE.get(str(value).strip()) if value is not None else None


def json_page(path: Path) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    payload = json.loads(path.read_bytes())
    envelope = payload.get("response")
    if not isinstance(envelope, dict):
        raise ValueError("API22 response envelope missing")
    header, body = envelope.get("header"), envelope.get("body")
    if not isinstance(header, dict) or not isinstance(body, dict):
        raise ValueError("API22 response header/body malformed")
    item = (body.get("items") or {}).get("item") if isinstance(body.get("items") or {}, dict) else None
    if item is None or item == []:
        rows: list[dict[str, Any]] = []
    elif isinstance(item, dict):
        rows = [item]
    elif isinstance(item, list):
        rows = item
    else:
        raise ValueError("API22 item collection malformed")
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError("API22 item is not an object")
    return header, body, rows


def xml_page(path: Path) -> tuple[dict[str, Any], list[dict[str, str]], int, int, int]:
    raw = path.read_bytes()
    text = raw.decode("utf-8-sig")
    if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        raise ValueError("DTD or custom XML entity declaration rejected")
    root = ET.fromstring(text)
    header = {name: root.findtext(".//" + name) or "" for name in ("resultCode", "resultMsg")}
    rows = [{child.tag: child.text or "" for child in item} for item in root.findall(".//items/item")]
    page_no = int(root.findtext(".//pageNo") or "0")
    total = int(root.findtext(".//totalCount") or "-1")
    size = int(root.findtext(".//numOfRows") or "0")
    return header, rows, page_no, total, size


@dataclass
class Page:
    raw_path: str
    path: Path
    digest: str
    page_no: int | None
    row_count: int
    capture_id: str
    captured_ms: int | None
    requested_ms: int | None
    retrieved_ms: int | None
    basis: str
    endpoint: str
    metadata: dict[str, Any] = field(default_factory=dict)
    total_count: int | None = None
    page_size: int | None = None
    integrity: str = "unchecked"
    selected: bool = False


@dataclass
class Capture:
    capture_id: str
    dataset: str
    kind: str
    meet: int | None
    start: date
    end: date
    captured_ms: int | None
    basis: str
    pages: list[Page]
    complete: bool = False
    reason: str = "not_checked"
    counts: Counter[tuple[str, int]] = field(default_factory=Counter)
    selected_dates: set[str] = field(default_factory=set)
    expected_count: int | None = None


def page_rows(page: Page, dataset: str, *, check_hash: bool = True) -> tuple[list[dict[str, Any]], int, int, int]:
    actual = sha_file(page.path) if check_hash else page.digest
    if actual != page.digest:
        raise ValueError("source page SHA-256 mismatch: " + page.raw_path)
    if dataset == "start_training":
        header, body, rows = json_page(page.path)
        if str(header.get("resultCode")) not in ("00", "0", "0000"):
            raise ValueError("API22 resultCode not successful")
        pageno, total, size = int(body.get("pageNo") or 0), int(body.get("totalCount") or 0), int(body.get("numOfRows") or 0)
    else:
        header, rows, pageno, total, size = xml_page(page.path)
        if str(header.get("resultCode")) not in ("00", "0", "0000"):
            raise ValueError("API216 resultCode not successful")
    if page.page_no is not None and pageno != page.page_no:
        raise ValueError("page number mismatch")
    if len(rows) != page.row_count:
        raise ValueError("manifest/source_documents item count mismatch")
    page.total_count, page.page_size = total, size
    return rows, pageno, total, size


def validate_capture(capture: Capture, query_month: str | None = None, query_date: str | None = None,
                     query_year: int | None = None) -> tuple[bool, str]:
    if not capture.pages:
        return False, "no_pages"
    totals: set[int] = set()
    sizes: set[int] = set()
    observed = 0
    counts: Counter[tuple[str, int]] = Counter()
    for page in sorted(capture.pages, key=lambda value: value.page_no or 0):
        try:
            rows, _, total, size = page_rows(page, capture.dataset)
        except Exception as exc:
            page.integrity = "page_error:" + type(exc).__name__
            return False, page.integrity
        page.integrity = "verified"
        totals.add(total)
        sizes.add(size)
        observed += len(rows)
        for row in rows:
            try:
                current = api_date(row.get("trDate"))
            except Exception:
                return False, "invalid_trDate"
            if query_month and current.strftime("%Y%m") != query_month:
                return False, "row_outside_requested_month"
            if query_date and current.strftime("%Y%m%d") != query_date:
                return False, "row_outside_requested_date"
            if query_year and current.year != query_year:
                return False, "row_outside_requested_year"
            mc = meet_code(row.get("meet"))
            if capture.meet is not None and mc != capture.meet:
                return False, "raw_meet_mismatch"
            if START_DATE <= current <= END_DATE and mc in MEETS:
                counts[(current.isoformat(), int(mc))] += 1
    if len(totals) != 1 or len(sizes) != 1:
        return False, "page_headers_disagree"
    total = next(iter(totals))
    size = next(iter(sizes))
    pages = sorted((page.page_no or 0) for page in capture.pages)
    expected_pages = max(1, math.ceil(total / max(size, 1)))
    if pages != list(range(1, expected_pages + 1)):
        return False, "page_sequence_or_count_mismatch"
    if observed != total:
        return False, "items_do_not_match_totalCount"
    capture.counts = counts
    capture.expected_count = total
    return True, "all_pages_hashes_headers_and_rows_verified"


def build_start_sources(db: sqlite3.Connection) -> tuple[list[Capture], list[Page]]:
    captures: list[Capture] = []
    all_pages: list[Page] = []
    with START_MANIFEST.open(encoding="utf-8") as stream:
        manifest_events = [json.loads(line) for line in stream if line.strip()]
    manifest_digest = sha_file(START_MANIFEST)
    filtered = [e for e in manifest_events if int(e.get("meet") or 0) in MEETS and START_DATE.strftime("%Y%m") <= str(e.get("month") or "") <= END_DATE.strftime("%Y%m")]

    month_groups: dict[tuple[int, str], list[tuple[int, dict[str, Any], Page]]] = defaultdict(list)
    for index, event in enumerate(filtered, 1):
        raw_path, path = safe_path(str(event["path"]))
        declared = str(event.get("sha256") or "")
        recorded = int(event["recorded_at_ms"]) if event.get("recorded_at_ms") is not None else None
        is_downloaded = str(event.get("status")) == "downloaded"
        meta = {
            "source_kind": "monthly_manifest", "manifest_status": str(event.get("status") or ""),
            "manifest_recorded_at_ms": recorded, "manifest_sha256": manifest_digest,
            "manifest_declared_item_count": int(event.get("item_count") or 0),
            "manifest_declared_total_count": int(event.get("total_count") or 0),
            "raw_file_sha256_verified": sha_file(path) == declared,
        }
        page = Page(raw_path, path, declared, int(event["page"]) if event.get("page") is not None else None,
                    int(event.get("item_count") or 0), "pending", recorded if is_downloaded else None,
                    None, recorded if is_downloaded else None,
                    "API22_1_monthly_manifest_download_recorded_at_after_response" if is_downloaded else "cached_manifest_record_time_not_used_for_recency",
                    "API22_1", meta)
        page.integrity = "hash_verified" if meta["raw_file_sha256_verified"] else "manifest_hash_mismatch"
        all_pages.append(page)
        if is_downloaded and meta["raw_file_sha256_verified"]:
            month_groups[(int(event["meet"]), str(event["month"]))].append((index, event, page))

    for (meet, month), items in sorted(month_groups.items()):
        latest_by_page: dict[int, tuple[int, dict[str, Any], Page]] = {}
        for item in items:
            old = latest_by_page.get(int(item[1].get("page") or 1))
            if old is None or int(item[1].get("recorded_at_ms") or 0) > int(old[1].get("recorded_at_ms") or 0):
                latest_by_page[int(item[1].get("page") or 1)] = item
        chosen = [latest_by_page[n] for n in sorted(latest_by_page)]
        seed = "|".join(x[2].digest for x in chosen)
        capture_id = "api22-monthly-m{}-{}-{}".format(meet, month, sha_text(seed)[:12])
        pages = [x[2] for x in chosen]
        for p in pages:
            p.capture_id = capture_id
        captured = max((int(x[1]["recorded_at_ms"]) for x in chosen if x[1].get("recorded_at_ms") is not None), default=None)
        first = date(int(month[:4]), int(month[4:6]), 1)
        if int(month[4:6]) == 12:
            nxt = date(int(month[:4]) + 1, 1, 1)
        else:
            nxt = date(int(month[:4]), int(month[4:6]) + 1, 1)
        last = date.fromordinal(nxt.toordinal() - 1)
        cutoff = min(last, kst_date(captured) or last, END_DATE)
        cap = Capture(capture_id, "start_training", "monthly_exact_month", meet, first, cutoff, captured,
                      "latest downloaded API22 monthly manifest response", pages)
        cap.complete, cap.reason = validate_capture(cap, query_month=month)
        captures.append(cap)
        chosen_indices = {x[0] for x in chosen}
        for index, event, page in items:
            if index not in chosen_indices:
                page.capture_id = "api22-monthly-version-{:06d}".format(index)
                page.basis = "older_downloaded_monthly_version_not_selected"
        # Cached events are retained in source_files with a unique metadata capture identity.
    for idx, event in enumerate(filtered, 1):
        if str(event.get("status")) == "cached":
            for page in all_pages:
                if page.metadata.get("manifest_status") == "cached" and page.raw_path == str(event.get("path")):
                    page.capture_id = "api22-monthly-cached-event-{:06d}".format(idx)
                    break

    recent_manifest = json.loads(RECENT_MANIFEST.read_text(encoding="utf-8"))
    for record in recent_manifest.get("records", []):
        if record.get("dataset") != "start" or int(record.get("meet") or 0) not in MEETS:
            continue
        month = str(record.get("month") or "")
        if month != "202609":
            continue
        meet = int(record["meet"])
        pages: list[Page] = []
        requested_values: list[int] = []
        retrieved_values: list[int] = []
        for item in record.get("pages", []):
            raw_path, path = safe_path(str(item["path"]))
            requested = int(datetime.fromisoformat(item["requested_at_kst"]).timestamp() * 1000)
            retrieved = int(datetime.fromisoformat(item["retrieved_at_kst"]).timestamp() * 1000)
            requested_values.append(requested)
            retrieved_values.append(retrieved)
            meta = {
                "source_kind": "fresh_month_capture_manifest", "capture_manifest_sha256": sha_file(RECENT_MANIFEST),
                "request_time_kst": item.get("requested_at_kst"), "retrieval_time_kst": item.get("retrieved_at_kst"),
                "retrieval_time_basis": item.get("retrieved_at_basis"), "http_status": item.get("http_status"),
                "response_bytes": item.get("response_bytes"), "page_size": item.get("page_size"),
                "total_count": item.get("total_count"), "item_count": item.get("item_count"),
            }
            page = Page(raw_path, path, str(item["sha256"]), int(item["page"]), int(item.get("item_count") or 0),
                        "pending", retrieved, requested, retrieved,
                        "API22_1 fresh monthly capture actual request and retrieval timestamps", "API22_1", meta)
            page.integrity = "hash_verified" if sha_file(path) == page.digest else "manifest_hash_mismatch"
            pages.append(page)
            all_pages.append(page)
        captured = max(retrieved_values) if retrieved_values else None
        seed = "|".join(x.digest for x in pages)
        capture_id = "api22-monthly-fresh-m{}-{}-{}".format(meet, month, sha_text(seed)[:12])
        for page in pages:
            page.capture_id = capture_id
        first = date(2026, 9, 1)
        cap = Capture(capture_id, "start_training", "fresh_month_exact_month", meet, first,
                      min(date(2026, 9, 30), kst_date(captured) or date(2026, 9, 30), END_DATE), captured,
                      "fresh API22 month response retrieved 2026-10-02 KST", pages)
        cap.complete, cap.reason = validate_capture(cap, query_month=month)
        cap.complete = cap.complete and bool(record.get("complete"))
        captures.append(cap)

    # API22 date-specific source documents are read from one coherent read-only SQLite snapshot.
    query = """
      SELECT sd.id, sd.ingestion_run_id, sd.requested_at_ms, sd.retrieved_at_ms,
             sd.http_status_code, sd.content_type, sd.response_bytes, sd.local_path, sd.sha256,
             sd.request_params_json, ir.status AS run_status
      FROM source_documents sd JOIN ingestion_runs ir ON ir.id=sd.ingestion_run_id
      WHERE ir.data_type=? AND ir.source=? ORDER BY sd.retrieved_at_ms,sd.id
    """
    source_rows = db.execute(query, ("horse_start_training", "data.go.kr/B551015/API22_1")).fetchall()
    groups: dict[tuple[int, str, int], list[tuple[sqlite3.Row, Page]]] = defaultdict(list)
    for row in source_rows:
        params = json.loads(row["request_params_json"] or "{}")
        raw_date = str(params.get("tr_date") or "")
        try:
            meet = int(params.get("meet") or 0)
            page_no = int(params.get("pageNo") or 1)
        except (TypeError, ValueError):
            meet, page_no = 0, None
        if len(raw_date) != 8 or not raw_date.isdigit() or meet not in MEETS:
            continue
        current = api_date(raw_date)
        if not START_DATE <= current <= END_DATE:
            continue
        raw_path, path = safe_path(str(row["local_path"]))
        requested = int(row["requested_at_ms"]) if row["requested_at_ms"] is not None else None
        retrieved = int(row["retrieved_at_ms"]) if row["retrieved_at_ms"] is not None else None
        safe_params = {k: params[k] for k in ("_type", "meet", "numOfRows", "pageNo", "tr_date") if k in params}
        meta = {"source_kind": "operational_source_document", "source_document_id": int(row["id"]),
                "ingestion_run_id": int(row["ingestion_run_id"]), "run_status": str(row["run_status"]),
                "http_status": int(row["http_status_code"]) if row["http_status_code"] is not None else None,
                "content_type": row["content_type"], "response_bytes": int(row["response_bytes"] or 0),
                "request_params": safe_params}
        try:
            _, body, items = json_page(path)
            count = len(items)
            if page_no is None:
                page_no = int(body.get("pageNo") or 1)
        except Exception:
            count = -1
        page = Page(raw_path, path, str(row["sha256"]), page_no, count, "pending", retrieved, requested,
                    retrieved, "API22_1 exact-date source_document request/retrieval timestamps", "API22_1", meta)
        page.integrity = "hash_verified" if sha_file(path) == page.digest else "source_document_hash_mismatch"
        all_pages.append(page)
        groups[(int(row["ingestion_run_id"]), raw_date, meet)].append((row, page))
    for (run_id, raw_date, meet), items in sorted(groups.items()):
        pages = [x[1] for x in items]
        pages.sort(key=lambda p: (p.page_no or 0, p.raw_path))
        capture_id = "api22-daily-run-{}".format(run_id)
        for p in pages:
            p.capture_id = capture_id
        requested = [int(r["requested_at_ms"]) for r, _ in items if r["requested_at_ms"] is not None]
        retrieved = [int(r["retrieved_at_ms"]) for r, _ in items if r["retrieved_at_ms"] is not None]
        captured = max(retrieved) if retrieved else None
        current = api_date(raw_date)
        cap = Capture(capture_id, "start_training", "daily_exact_date", meet, current, current, captured,
                      "API22_1 exact-date capture from source_documents request/retrieval timestamps", pages)
        if any(str(r["run_status"]) != "completed" for r, _ in items):
            cap.complete, cap.reason = False, "ingestion_run_not_completed"
        elif any(r["http_status_code"] != 200 for r, _ in items):
            cap.complete, cap.reason = False, "http_status_not_200"
        else:
            cap.complete, cap.reason = validate_capture(cap, query_date=raw_date)
        captures.append(cap)
    return captures, all_pages


def snapshot_context() -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, path in (("main", OPERATING_DB), ("wal", Path(str(OPERATING_DB) + "-wal"))):
        if path.exists():
            stat = path.stat()
            result[name] = {"size_bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns,
                            "sha256": sha_file(path) if name == "wal" else None}
        else:
            result[name] = None
    return result


def open_snapshot() -> tuple[sqlite3.Connection, dict[str, Any]]:
    before = snapshot_context()
    connection = sqlite3.connect("file:{}?mode=ro".format(OPERATING_DB), uri=True, timeout=60)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    connection.execute("BEGIN")
    metadata = {
        "journal_mode": connection.execute("PRAGMA journal_mode").fetchone()[0],
        "schema_version": connection.execute("PRAGMA schema_version").fetchone()[0],
        "data_version_at_begin": connection.execute("PRAGMA data_version").fetchone()[0],
        "before": before,
    }
    return connection, metadata


def close_snapshot(connection: sqlite3.Connection, metadata: dict[str, Any]) -> None:
    metadata["data_version_before_rollback"] = connection.execute("PRAGMA data_version").fetchone()[0]
    connection.rollback()
    connection.close()
    metadata["after"] = snapshot_context()


def build_swim_sources(db: sqlite3.Connection) -> tuple[list[Capture], list[Page], dict[str, Any]]:
    query = """
      SELECT sd.id,sd.ingestion_run_id,sd.requested_at_ms,sd.retrieved_at_ms,sd.http_status_code,
             sd.content_type,sd.response_bytes,sd.local_path,sd.sha256,sd.request_params_json,
             ir.status AS run_status
      FROM source_documents sd JOIN ingestion_runs ir ON ir.id=sd.ingestion_run_id
      WHERE ir.data_type=? AND ir.source=? ORDER BY sd.retrieved_at_ms,sd.id
    """
    rows = db.execute(query, ("horse_swim_training", "data.go.kr/B551015/API216")).fetchall()
    groups: dict[tuple[int, int], list[tuple[sqlite3.Row, Page]]] = defaultdict(list)
    pages_all: list[Page] = []
    excluded = Counter()
    for row in rows:
        params = json.loads(row["request_params_json"] or "{}")
        try:
            year = int(params.get("tr_year") or 0)
            page_no = int(params.get("pageNo") or 1)
        except (TypeError, ValueError):
            excluded["invalid_year_or_page"] += 1
            continue
        if not 2010 <= year <= 2026:
            excluded["year_outside_scope"] += 1
            continue
        raw_path, path = safe_path(str(row["local_path"]))
        requested = int(row["requested_at_ms"]) if row["requested_at_ms"] is not None else None
        retrieved = int(row["retrieved_at_ms"]) if row["retrieved_at_ms"] is not None else None
        safe_params = {k: params[k] for k in ("tr_year", "numOfRows", "pageNo") if k in params}
        meta = {"source_kind": "operational_source_document", "source_document_id": int(row["id"]),
                "ingestion_run_id": int(row["ingestion_run_id"]), "run_status": str(row["run_status"]),
                "http_status": int(row["http_status_code"]) if row["http_status_code"] is not None else None,
                "content_type": row["content_type"], "response_bytes": int(row["response_bytes"] or 0),
                "request_params": safe_params}
        try:
            _, item_rows, actual_page, total, size = xml_page(path)
            count = len(item_rows)
            if page_no != actual_page:
                raise ValueError("page number mismatch")
        except Exception:
            count = -1
        page = Page(raw_path, path, str(row["sha256"]), page_no, count,
                    "api216-run-{}-year-{}".format(row["ingestion_run_id"], year), retrieved,
                    requested, retrieved, "API216 annual source_document request/retrieval timestamps", "API216", meta)
        page.integrity = "hash_verified" if sha_file(path) == page.digest else "source_document_hash_mismatch"
        pages_all.append(page)
        groups[(int(row["ingestion_run_id"]), year)].append((row, page))

    captures: list[Capture] = []
    for (run_id, year), items in sorted(groups.items()):
        pages = sorted((p for _, p in items), key=lambda p: (p.page_no or 0, p.raw_path))
        captured_values = [int(r["retrieved_at_ms"]) for r, _ in items if r["retrieved_at_ms"] is not None]
        captured = max(captured_values) if captured_values else None
        if year == 2026:
            end = min(date(2026, 12, 31), kst_date(captured) or date(2026, 12, 31), END_DATE)
        else:
            end = date(year, 12, 31)
        start = date(year, 1, 1)
        cap_id = "api216-annual-run-{}-year-{}".format(run_id, year)
        for page in pages:
            page.capture_id = cap_id
        cap = Capture(cap_id, "swim_training", "annual_year_query", None, start, end, captured,
                      "API216 complete tr_year annual response source_document retrieval timestamp", pages)
        if any(str(r["run_status"]) != "completed" for r, _ in items):
            cap.complete, cap.reason = False, "ingestion_run_not_completed"
        elif any(r["http_status_code"] != 200 for r, _ in items):
            cap.complete, cap.reason = False, "http_status_not_200"
        else:
            cap.complete, cap.reason = validate_capture(cap, query_year=year)
        captures.append(cap)
    return captures, pages_all, {"source_document_rows": len(rows), "years_outside_scope": excluded["year_outside_scope"]}


def scope_dates() -> Iterator[date]:
    current = START_DATE
    while current <= END_DATE:
        yield current
        current = date.fromordinal(current.toordinal() + 1)


def choose_coverage(captures: list[Capture], dataset: str) -> tuple[dict[tuple[str, int], Capture | None], list[dict[str, Any]]]:
    complete: dict[tuple[str, int], list[Capture]] = defaultdict(list)
    incomplete: dict[tuple[str, int], list[Capture]] = defaultdict(list)
    for capture in captures:
        current = max(capture.start, START_DATE)
        last = min(capture.end, END_DATE)
        covered_meets = MEETS if capture.meet is None else (capture.meet,)
        while current <= last:
            for meet in covered_meets:
                key = (current.isoformat(), meet)
                (complete if capture.complete else incomplete)[key].append(capture)
            current = date.fromordinal(current.toordinal() + 1)
    selected: dict[tuple[str, int], Capture | None] = {}
    coverage: list[dict[str, Any]] = []
    for current in scope_dates():
        iso = current.isoformat()
        for meet in MEETS:
            key = (iso, meet)
            options = complete.get(key, [])
            # Recency is primary. Exact-date capture wins only an identical-time tie.
            rank = {"daily_exact_date": 2, "monthly_exact_month": 1, "fresh_month_exact_month": 3,
                    "annual_year_query": 1}
            winner = max(options, key=lambda c: (c.captured_ms or -1, rank.get(c.kind, 0), c.capture_id)) if options else None
            selected[key] = winner
            if winner:
                winner.selected_dates.add(iso)
                count = winner.counts[(iso, meet)]
                coverage.append({"event_date": iso, "meet": str(meet),
                    "coverage_status": "complete_rows" if count else "complete_zero_rows",
                    "selected_capture_id": winner.capture_id,
                    "selection_rule": "latest hash-verified complete capture per event-date and meet by actual response retrieval time",
                    "coverage_basis": "exact-date query" if winner.kind == "daily_exact_date" else
                                     "complete monthly query filtered by raw trDate through capture cutoff" if "month" in winner.kind else
                                     "complete annual tr_year query filtered by raw trDate through capture cutoff",
                    "expected_rows": count, "observed_rows": count})
            else:
                bad = incomplete.get(key, [])
                coverage.append({"event_date": iso, "meet": str(meet),
                    "coverage_status": "incomplete_capture" if bad else "missing_capture",
                    "selected_capture_id": None,
                    "selection_rule": "no complete capture available",
                    "coverage_basis": ";".join(sorted({c.reason for c in bad})) if bad else "no capture covers date and meet",
                    "expected_rows": None, "observed_rows": 0})
    return selected, coverage


def core_roster() -> set[str]:
    db = duckdb.connect(str(CORE_DB.resolve(strict=True)), read_only=True)
    try:
        db.execute("BEGIN TRANSACTION")
        rows = db.execute("SELECT DISTINCT entity_id_official_string FROM entity_reference_roster WHERE entity_type=?", ["horse"]).fetchall()
        db.execute("ROLLBACK")
        return {str(row[0]) for row in rows if row[0] is not None and str(row[0]) != ""}
    finally:
        db.close()


def source_rows(capture: Capture, dataset: str, event: date, meet: int) -> Iterator[tuple[Page, int, dict[str, Any]]]:
    for page in sorted(capture.pages, key=lambda value: (value.page_no or 0, value.raw_path)):
        if dataset == "start_training":
            _, _, rows = json_page(page.path)
        else:
            _, rows, _, _, _ = xml_page(page.path)
        for row_no, raw in enumerate(rows, 1):
            try:
                current = api_date(raw.get("trDate"))
            except Exception:
                continue
            code = meet_code(raw.get("meet"))
            if current == event and code == meet:
                yield page, row_no, raw


def key_and_payload(dataset: str, meet: int, event: date, raw: dict[str, Any]) -> tuple[str, str]:
    raw_id = raw.get("hrNo")
    horse_key = "" if raw_id is None else str(raw_id)
    key = canonical([horse_key, str(meet), event.isoformat()])
    return key, sha_text(canonical(raw))


def selected_row_iter(captures: list[Capture], selected: dict[tuple[str, int], Capture | None], dataset: str,
                      pages_by_capture: dict[str, list[Page]]) -> Iterator[tuple[Capture, Page, int, date, int, dict[str, Any]]]:
    # Scan each selected capture page once. Annual swim pages can contain tens of
    # thousands of rows; rescanning them for every date would be quadratic.
    selected_captures = {id(capture): capture for capture in selected.values() if capture is not None}
    for capture in sorted(selected_captures.values(), key=lambda c: (c.start, c.capture_id)):
        for page in sorted(capture.pages, key=lambda value: (value.page_no or 0, value.raw_path)):
            if dataset == "start_training":
                _, _, rows = json_page(page.path)
            else:
                _, rows, _, _, _ = xml_page(page.path)
            for row_no, raw in enumerate(rows, 1):
                try:
                    event = api_date(raw.get("trDate"))
                except Exception:
                    continue
                meet = meet_code(raw.get("meet"))
                if (START_DATE <= event <= END_DATE and meet in MEETS
                        and selected.get((event.isoformat(), int(meet))) is capture):
                    yield capture, page, row_no, event, int(meet), raw


def build_page_inventory(pages: list[Page], selected_capture_ids: set[str], endpoint: str) -> list[dict[str, Any]]:
    # One record per raw path/page/capture, as required by the loader's unique key.
    unique: dict[tuple[str, int | None, str], Page] = {}
    for page in pages:
        key = (page.raw_path, page.page_no, page.capture_id)
        if key not in unique:
            unique[key] = page
    result = []
    for page in sorted(unique.values(), key=lambda p: (p.raw_path, p.capture_id, p.page_no or 0)):
        metadata = dict(page.metadata)
        if page.total_count is not None:
            metadata["page_total_count"] = page.total_count
        if page.row_count >= 0:
            metadata["page_item_count"] = page.row_count
        metadata["integrity_status"] = page.integrity
        result.append({
            "raw_path": page.raw_path, "raw_sha256": page.digest, "source_page_no": page.page_no,
            "row_count": max(0, page.row_count), "page_item_count": max(0, page.row_count),
            "page_total_count": page.total_count, "capture_id": page.capture_id,
            "source_captured_at": utc_text(page.captured_ms), "requested_at_ms": page.requested_ms,
            "retrieved_at_ms": page.retrieved_ms, "capture_basis": page.basis, "endpoint": endpoint,
            "is_selected": page.capture_id in selected_capture_ids and page.integrity in ("verified", "hash_verified"),
            "source_metadata_json": canonical(metadata),
        })
    return result


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def export_dataset(dataset: str, endpoint: str, captures: list[Capture], pages: list[Page],
                   source_meta: dict[str, Any], roster: set[str], snapshot: dict[str, Any]) -> dict[str, Any]:
    selected, coverage = choose_coverage(captures, dataset)
    # Profile natural keys and payload hashes without changing or dropping occurrences.
    key_counts: Counter[str] = Counter()
    key_payload_counts: Counter[tuple[str, str]] = Counter()
    key_payload_sets: dict[str, set[str]] = defaultdict(set)
    row_count = 0
    for capture, page, row_no, event, meet, raw in selected_row_iter(captures, selected, dataset, {}):
        key, payload_hash = key_and_payload(dataset, meet, event, raw)
        key_counts[key] += 1
        key_payload_counts[(key, payload_hash)] += 1
        key_payload_sets[key].add(payload_hash)
        row_count += 1
        if row_count % 100000 == 0:
            print(json.dumps({"stage": "profile", "dataset": dataset, "rows": row_count}), flush=True)
    occurrence_seen: Counter[str] = Counter()
    dest = INPUT / (dataset + ".parquet")
    temporary = dest.with_suffix(".parquet.tmp")
    writer = pq.ParquetWriter(temporary, SCHEMA, compression="zstd", version="2.6")
    columns: dict[str, list[Any]] = {field.name: [] for field in SCHEMA}
    counts = Counter()
    unmatched: Counter[tuple[str, str]] = Counter()
    exact_repeats = 0
    conflict_keys: set[str] = set()
    output_rows = 0
    for capture, page, row_no, event, meet, raw in selected_row_iter(captures, selected, dataset, {}):
        key, payload_hash = key_and_payload(dataset, meet, event, raw)
        occurrence_seen[key] += 1
        flags: list[str] = []
        if key_counts[key] > 1:
            flags.append("same_natural_key_multiplicity_preserved")
            conflict_keys.add(key)
        if key_payload_counts[(key, payload_hash)] > 1:
            flags.append("exact_payload_repeat_preserved")
            exact_repeats += 1
        elif key_counts[key] > 1:
            flags.append("nonidentical_same_natural_key_multiplicity_preserved")
        raw_id_value = raw.get("hrNo")
        official_id = None if raw_id_value is None or not str(raw_id_value).strip() else str(raw_id_value)
        raw_name = None if raw.get("hrName") is None else str(raw.get("hrName"))
        if official_id is None:
            link = "missing_official_id"
            flags.append("missing_official_horse_id")
            linked = None
        elif official_id in roster:
            link, linked = "exact_core_roster_match", official_id
        else:
            link, linked = "unmatched_official_id", None
            flags.append("unmatched_official_horse_id")
            unmatched[(str(meet), official_id)] += 1
        raw_meet = str(raw.get("meet") or "")
        if meet == 3:
            flags.append("meet3_physical_venue_unadjudicated")
        typed = dict(raw)
        if dataset == "start_training":
            typed["anonymous_occurrence_ordinal"] = occurrence_seen[key]
            typed["anonymous_occurrence_order_basis"] = "selected source page and row storage order; not event time or event ID"
            typed["event_time_verified"] = False
        else:
            typed["cnt_unit_status"] = "unresolved_api216_count_vs_website_baekwi"
            typed["cnt_value_preserved_without_transform"] = True
            flags.append("swim_cnt_unit_unresolved")
            try:
                cnt = int(str(raw.get("cnt")))
                if cnt == 0:
                    flags.append("swim_cnt_raw_zero_preserved")
                if cnt < 0:
                    flags.append("swim_cnt_raw_negative_preserved")
                if cnt >= 20:
                    flags.append("swim_cnt_raw_large_value_preserved")
            except (TypeError, ValueError):
                pass
        if raw.get("horsepart") is not None or raw.get("trpart") is not None:
            typed["number_field_mapping_status"] = "raw horsepart and trpart preserved; no physical stall inference"
        flags = sorted(set(flags))
        obsid = sha_text("|".join((dataset, page.digest, str(page.page_no or 0), str(row_no))))
        values = {
            "dataset": dataset, "observation_id": obsid, "event_date": event, "meet": str(meet),
            "official_horse_id": official_id, "raw_name": raw_name, "raw_path": page.raw_path,
            "raw_sha256": page.digest, "source_page_no": page.page_no, "source_row_no": row_no,
            "source_captured_at": utc_naive(page.captured_ms), "capture_basis": capture.basis,
            "endpoint": endpoint, "raw_payload_json": canonical(raw), "typed_fields_json": canonical(typed),
            "link_status": link, "linked_core_horse_id": linked, "qa_flags_json": canonical(flags),
            "capture_id": capture.capture_id,
        }
        for col in columns:
            columns[col].append(values[col])
        counts["rows"] += 1
        counts["meet_" + str(meet)] += 1
        counts["link_" + link] += 1
        if len(columns["dataset"]) >= BATCH_SIZE:
            table = pa.Table.from_pydict(columns, schema=SCHEMA)
            writer.write_table(table)
            columns = {field.name: [] for field in SCHEMA}
        output_rows += 1
        if output_rows % 100000 == 0:
            print(json.dumps({"stage": "write", "dataset": dataset, "rows": output_rows}), flush=True)
    if columns["dataset"]:
        writer.write_table(pa.Table.from_pydict(columns, schema=SCHEMA))
    writer.close()
    temporary.replace(dest)
    parquet_hash = sha_file(dest)

    selected_capture_ids = {row["selected_capture_id"] for row in coverage if row["selected_capture_id"]}
    for page in pages:
        page.selected = page.capture_id in selected_capture_ids
    inventory = {
        "schema_version": 1, "dataset": dataset, "endpoint": endpoint,
        "scope_start": START_DATE.isoformat(), "scope_end": END_DATE.isoformat(),
        "row_count": output_rows,
        "parquet_path": dest.relative_to(ROOT).as_posix(), "parquet_sha256": parquet_hash,
        "timestamp_policy": "source_captured_at is timezone-naive UTC; original request/retrieval timestamps and timezone basis remain in source_metadata_json",
        "capture_selection": "latest hash-verified complete capture per event-date and meet by actual response retrieval time; API22 captures may be monthly or date-specific; API216 captures are annual tr_year pages",
        "identity_rule": "exact official horse ID string to entity_reference_roster entity_type=horse; no name merge",
        "venue_rule": "raw meet labels retained; meet 3 physical venue not inferred",
        "dataset_rule": "raw occurrence multiplicity retained; source row order is storage order only",
        "source_snapshot": snapshot,
        "source_catalog": source_meta,
        "source_files": build_page_inventory(pages, selected_capture_ids, endpoint),
        "date_coverage": coverage,
    }
    invpath = INPUT / (dataset + "_inventory.json")
    invpath.write_text(json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    date_coverage_path = HERE / (dataset + "_date_coverage.csv")
    write_csv(date_coverage_path, coverage, ["event_date", "meet", "coverage_status", "selected_capture_id", "selection_rule", "coverage_basis", "expected_rows", "observed_rows"])
    ledger = []
    for capture in captures:
        ledger.append({"capture_id": capture.capture_id, "dataset": dataset, "capture_kind": capture.kind,
            "meet": str(capture.meet) if capture.meet is not None else "all_returned_meets",
            "coverage_start": capture.start.isoformat(), "coverage_end": capture.end.isoformat(),
            "captured_at_utc": utc_text(capture.captured_ms), "capture_basis": capture.basis,
            "complete": capture.complete, "completeness_reason": capture.reason,
            "page_count": len(capture.pages), "expected_count": capture.expected_count,
            "observed_scope_rows": sum(capture.counts.values()),
            "selected_scope_dates": len(capture.selected_dates),
            "source_page_paths": ";".join(p.raw_path for p in capture.pages)})
    write_csv(HERE / (dataset + "_capture_ledger.csv"), ledger,
              ["capture_id", "dataset", "capture_kind", "meet", "coverage_start", "coverage_end", "captured_at_utc", "capture_basis", "complete", "completeness_reason", "page_count", "expected_count", "observed_scope_rows", "selected_scope_dates", "source_page_paths"])
    write_csv(HERE / (dataset + "_unmatched_official_ids.csv"),
              [{"meet": m, "official_horse_id": horse, "observation_count": n} for (m, horse), n in sorted(unmatched.items())],
              ["meet", "official_horse_id", "observation_count"])
    summary = {
        "dataset": dataset, "endpoint": endpoint, "row_count": output_rows,
        "meet_counts": {"1": counts["meet_1"], "3": counts["meet_3"]},
        "link_status_counts": {k.removeprefix("link_"): v for k, v in counts.items() if k.startswith("link_")},
        "source_capture_count": len(captures), "complete_capture_count": sum(c.complete for c in captures),
        "selected_capture_count": len(selected_capture_ids), "source_page_record_count": len(inventory["source_files"]),
        "selected_source_page_count": sum(bool(f["is_selected"]) for f in inventory["source_files"]),
        "date_coverage_counts": dict(Counter(r["coverage_status"] for r in coverage)),
        "same_natural_key_rows": sum(n for n in key_counts.values() if n > 1),
        "same_natural_key_groups": sum(n > 1 for n in key_counts.values()),
        "exact_payload_repeat_rows": exact_repeats,
        "nonidentical_same_key_groups": sum(key_counts[k] > 1 and len(v) > 1 for k, v in key_payload_sets.items()),
        "unmatched_official_id_count": len(unmatched), "parquet_sha256": parquet_hash,
    }
    return summary


def normalized_payload_tuple(raw: dict[str, Any]) -> tuple[int | None, str | None, str | None, str | None]:
    def blank_none(value: Any) -> str | None:
        if value is None or str(value).strip() == "":
            return None
        return str(value)
    part_value = raw.get("part")
    try:
        part = int(str(part_value)) if part_value is not None and str(part_value).strip() else None
    except ValueError:
        part = None
    return part, blank_none(raw.get("partNo")), blank_none(raw.get("prName")), blank_none(raw.get("remark"))


def compare_operational_start(parquet_path: Path) -> dict[str, Any]:
    """Read-only diagnostic of operational multiplicity mapped to API22 source rows."""
    raw_counts: Counter[tuple[str | None, str, str]] = Counter()
    raw_refs: dict[tuple[str | None, str, str], list[str]] = defaultdict(list)
    raw_ids: dict[tuple[str | None, str, str], list[str]] = defaultdict(list)
    raw_payload_hashes: dict[tuple[str | None, str, str], list[str]] = defaultdict(list)
    parquet_file = pq.ParquetFile(parquet_path)
    for batch in parquet_file.iter_batches(batch_size=32768,
            columns=["event_date", "meet", "official_horse_id", "raw_payload_json", "observation_id", "raw_path", "source_page_no", "source_row_no"]):
        for row in batch.to_pylist():
            key = (row["official_horse_id"], row["meet"], row["event_date"].isoformat())
            raw_counts[key] += 1
            raw_refs[key].append("{}#p{}:r{}".format(row["raw_path"], row["source_page_no"], row["source_row_no"]))
            raw_ids[key].append(row["observation_id"])
            raw_payload_hashes[key].append(sha_text(row["raw_payload_json"]))

    db, snapshot = open_snapshot()
    try:
        rows = db.execute("""
          SELECT h.kra_horse_id AS official_horse_id, s.meet_code, s.training_date_local,
                 COUNT(*) AS occurrence_count
          FROM horse_start_training s LEFT JOIN horses h ON h.id=s.horse_id
          WHERE s.training_date_local BETWEEN ? AND ? AND s.meet_code IN (?,?)
          GROUP BY h.kra_horse_id,s.meet_code,s.training_date_local
          ORDER BY h.kra_horse_id,s.meet_code,s.training_date_local
        """, (START_DATE.isoformat(), END_DATE.isoformat(), *MEETS)).fetchall()
        op_counts: Counter[tuple[str | None, str, str]] = Counter()
        for row in rows:
            official = str(row["official_horse_id"]) if row["official_horse_id"] is not None else None
            meet = str(row["meet_code"])
            event = str(row["training_date_local"])
            key = (official, meet, event)
            op_counts[key] += int(row["occurrence_count"])
        op_rows = sum(op_counts.values())
        close_snapshot(db, snapshot)
    except Exception:
        db.rollback()
        db.close()
        raise

    differing = []
    keys = set(raw_counts) | set(op_counts)
    op_only_rows = raw_only_rows = 0
    duplicate_operation_keys_without_raw_multiplicity = 0
    for key in sorted(keys, key=lambda k: (k[2], k[1], k[0] or "")):
        raw_n, op_n = raw_counts[key], op_counts[key]
        if raw_n == op_n:
            continue
        op_only_rows += max(0, op_n - raw_n)
        raw_only_rows += max(0, raw_n - op_n)
        if op_n > 1 and raw_n <= 1:
            duplicate_operation_keys_without_raw_multiplicity += 1
        differing.append({
            "event_date": key[2], "meet": key[1], "official_horse_id": key[0] or "",
            "operational_row_count": op_n, "raw_api22_observation_count": raw_n,
            "operational_extra_same_key_rows": max(0, op_n - raw_n),
            "raw_observation_count_confirms_multiplicity": raw_n > 1,
            "raw_payload_sha256s": ";".join(raw_payload_hashes.get(key, [])),
            "raw_observation_ids": ";".join(raw_ids.get(key, [])),
            "raw_source_refs": ";".join(raw_refs.get(key, [])),
        })
    write_csv(HERE / "start_training_operational_difference_ledger.csv", differing,
              ["event_date", "meet", "official_horse_id", "operational_row_count", "raw_api22_observation_count",
               "operational_extra_same_key_rows", "raw_observation_count_confirms_multiplicity",
               "raw_payload_sha256s", "raw_observation_ids", "raw_source_refs"])
    return {
        "comparison_scope": "operational horse_start_training rows joined to horses.kra_horse_id exact string, compared to selected API22 observations by official ID/meet/date; ledger carries raw payload hashes, observation IDs, and page/row locations",
        "payload_value_comparison": "not used for multiplicity conclusions because historical operating normalization differs from raw API22 fields",
        "operational_snapshot": snapshot,
        "operational_rows": op_rows, "raw_api22_rows": sum(raw_counts.values()),
        "operational_natural_key_groups": len(op_counts), "raw_natural_key_groups": len(raw_counts),
        "operational_duplicate_key_groups": sum(n > 1 for n in op_counts.values()),
        "operational_duplicate_extra_rows": sum(n - 1 for n in op_counts.values() if n > 1),
        "raw_duplicate_key_groups": sum(n > 1 for n in raw_counts.values()),
        "raw_duplicate_extra_rows": sum(n - 1 for n in raw_counts.values() if n > 1),
        "keys_with_count_difference": len(differing),
        "operational_only_rows_by_key_count": op_only_rows,
        "raw_only_rows_by_key_count": raw_only_rows,
        "operational_duplicate_keys_with_raw_count_at_most_one": duplicate_operation_keys_without_raw_multiplicity,
        "difference_ledger": (HERE / "start_training_operational_difference_ledger.csv").relative_to(ROOT).as_posix(),
    }


def main() -> None:
    HERE.mkdir(parents=True, exist_ok=True)
    INPUT.mkdir(parents=True, exist_ok=True)
    db, snapshot = open_snapshot()
    try:
        start_caps, start_pages = build_start_sources(db)
        swim_caps, swim_pages, swim_source_meta = build_swim_sources(db)
    finally:
        close_snapshot(db, snapshot)
    roster = core_roster()
    print(json.dumps({"stage": "sources_loaded", "start_captures": len(start_caps),
        "start_complete": sum(c.complete for c in start_caps), "start_pages": len(start_pages),
        "swim_captures": len(swim_caps), "swim_complete": sum(c.complete for c in swim_caps),
        "swim_pages": len(swim_pages), "roster_ids": len(roster), "snapshot": snapshot}, ensure_ascii=False), flush=True)
    start_meta = {"monthly_manifest_sha256": sha_file(START_MANIFEST),
                  "fresh_capture_manifest_sha256": sha_file(RECENT_MANIFEST),
                  "operational_source_document_count": sum(1 for p in start_pages if p.metadata.get("source_kind") == "operational_source_document")}
    swim_source_meta["year_capture_ids"] = {str(year): [c.capture_id for c in swim_caps if c.start.year == year] for year in range(2010, 2027)}
    start_summary = export_dataset("start_training", "API22_1", start_caps, start_pages, start_meta, roster, snapshot)
    swim_summary = export_dataset("swim_training", "API216", swim_caps, swim_pages, swim_source_meta, roster, snapshot)
    start_summary["operational_comparison"] = compare_operational_start(INPUT / "start_training.parquet")
    report = {"schema_version": 1, "scope": "2010-01-01..2026-09-29 inclusive; meets 1 and 3; no Jeju meet 2; no physical venue inference for meet 3",
        "operating_snapshot": snapshot, "roster_exact_match_type": "entity_reference_roster entity_type=horse exact official ID string",
        "datasets": {"start_training": start_summary, "swim_training": swim_summary},
        "known_semantics": {"start_training": "API22_1 has no event ID or event time; repeated same-horse-day observations preserved with anonymous storage ordinal only",
                            "swim_training": "API216 cnt is preserved raw; count versus website 바퀴 unit unresolved; horsepart/trpart retained without physical stable inference"}}
    (HERE / "qa_summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    readme = """# START and SWIM raw reconstruction

Scope: 2010-01-01 through 2026-09-29 inclusive, API meet 1 and 3. Jeju meet 2 is excluded. Raw venue labels are retained; meet 3 is not assigned to a physical venue.

The source is API22_1 monthly JSON plus verified API22_1 exact-date source documents and the fresh 2026-09 monthly response; API216 annual XML source documents. Capture selection is the latest hash-verified complete response covering each event date and meet, based on actual response retrieval time. Every date × meet has an explicit coverage row, so complete zero-row responses remain distinct from missing or incomplete captures.

The Parquets preserve every selected source row as an observation. API22_1 supplies no event ID/time, so repeated same-key rows retain their page/row locations and an anonymous storage ordinal that is not chronology. API216 raw cnt, horsepart, and trpart are not transformed; cnt's count-versus-바퀴 unit is unresolved. Core links use exact official horse ID matching only; unmatched IDs are in separate ledgers.

`source_captured_at` is stored as timezone-naive UTC. Source request/retrieval timestamps and their original KST/UTC basis are retained in sanitized inventory metadata. Raw payload JSON is canonical compact JSON of the source row. Exact and nonidentical natural-key repeats are flagged and kept.

This directory and loader/input contain research artifacts only. The script reads the operating SQLite in a query-only transaction and the core DuckDB in a read-only transaction; it does not call APIs or write to either database.
"""
    (HERE / "README.md").write_text(readme, encoding="utf-8")
    print(json.dumps({"stage": "complete", "report": report}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
