#!/usr/bin/env python3
"""Freeze hash-verified API78 equipment evidence against the thoroughbred core.

Read-only inputs: the operational SQLite store, the frozen thoroughbred core,
saved API78 documents in data/raw, archived review examples, and optional local
historical captures under ../historical_raw. No network or database writes.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import sqlite3
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

import duckdb


ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parent
RAW_ROOT = (ROOT / "data/raw").resolve()
OPERATIONAL = ROOT / "data/horse_racing.sqlite3"
CORE = ROOT / "thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb"
ARCHIVE_ROOT = ROOT / "thoroughbred/research/20261001_equipment_unobserved_review_v1/official"
HISTORICAL_ROOT = OUT.parent / "historical_raw"
ENDPOINT = "/API78/chulmainfo"
MEETS = {1, 3, 4}
START_DAY = "20100101"
END_DAY = "20260929"
KST = ZoneInfo("Asia/Seoul")
INTEGER = re.compile(r"(\d+)")
ARCHIVE_NAME = re.compile(r"api78_(\d)_(\d{8})\.json$")
MARK = re.compile(r"^(.+?)\s*([+-])\s*$")
HISTORICAL_MANIFEST_BYTES: bytes | None = None
HISTORICAL_TARGETS_BYTES: bytes | None = None


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def day8(value: object) -> str:
    text = clean(value)
    korean = re.search(r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일?", text)
    if korean:
        return f"{int(korean.group(1)):04d}{int(korean.group(2)):02d}{int(korean.group(3)):02d}"
    separated = re.search(r"(\d{4})[-./](\d{1,2})[-./](\d{1,2})", text)
    if separated:
        return f"{int(separated.group(1)):04d}{int(separated.group(2)):02d}{int(separated.group(3)):02d}"
    digits = "".join(re.findall(r"\d", text))
    return digits[:8] if len(digits) >= 8 else ""


def number(value: object) -> int | None:
    match = INTEGER.search(clean(value))
    return int(match.group(1)) if match else None


def normalize_name(value: object) -> str:
    text = unicodedata.normalize("NFKC", clean(value))
    text = text.removeprefix("★").strip()
    text = re.sub(r"^\[[^]]+\]\s*", "", text)
    text = text.removeprefix("★").strip()
    return "".join(text.split()).casefold()


def iso_kst_to_ms(value: object) -> int | None:
    text = clean(value)
    if not text:
        return None
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=KST)
    return int(parsed.timestamp() * 1000)


def ms_to_kst(value: int | None) -> str:
    if value is None:
        return ""
    return datetime.fromtimestamp(value / 1000, timezone.utc).astimezone(KST).isoformat(timespec="milliseconds")


def read_payload(path: Path) -> tuple[dict[str, object], list[dict[str, object]]]:
    payload = json.loads(path.read_bytes())
    if not isinstance(payload, dict):
        raise ValueError("payload_not_object")
    response = payload.get("response")
    if not isinstance(response, dict):
        raise ValueError("response_missing")
    header = response.get("header") or {}
    if isinstance(header, dict):
        code = clean(header.get("resultCode"))
        if code and code not in {"00", "0000"}:
            raise ValueError("api_response_error")
    body = response.get("body")
    if not isinstance(body, dict):
        raise ValueError("body_missing")
    bucket = body.get("items", {})
    if isinstance(bucket, dict):
        bucket = bucket.get("item", [])
    if bucket in (None, ""):
        bucket = []
    if isinstance(bucket, dict):
        bucket = [bucket]
    if not isinstance(bucket, list) or any(not isinstance(item, dict) for item in bucket):
        raise ValueError("items_container_invalid")
    return body, bucket


def safe_raw_path(local_path: str) -> Path:
    candidate = Path(local_path)
    if not candidate.is_absolute():
        candidate = ROOT / candidate
    resolved = candidate.resolve(strict=True)
    if not resolved.is_relative_to(RAW_ROOT) or not resolved.is_file():
        raise ValueError("raw_path_outside_data_raw")
    return resolved


def sqlite_snapshot() -> tuple[sqlite3.Connection, dict[str, object], list[dict[str, object]], list[dict[str, object]]]:
    before = sha256(OPERATIONAL)
    wal = Path(str(OPERATIONAL) + "-wal")
    wal_before = sha256(wal) if wal.is_file() else ""
    con = sqlite3.connect(OPERATIONAL.as_uri() + "?mode=ro", uri=True, timeout=20)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only=ON")
    con.execute("BEGIN")
    # This first read fixes the SQLite read snapshot for all following selects.
    snapshot_started = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    con.execute("SELECT count(*) FROM sqlite_master").fetchone()
    data_version = con.execute("PRAGMA data_version").fetchone()[0]
    schema_version = con.execute("PRAGMA schema_version").fetchone()[0]

    documents: list[dict[str, object]] = []
    query = """
        SELECT sd.id document_id, sd.ingestion_run_id, sd.local_path,
               sd.sha256, sd.requested_at_ms, sd.retrieved_at_ms,
               sd.http_status_code, sd.response_bytes, sd.endpoint, sd.operation,
               sd.request_params_json, ir.source run_source, ir.data_type run_data_type,
               ir.started_at_ms run_started_at_ms, ir.completed_at_ms run_completed_at_ms,
               ir.status run_status
        FROM source_documents sd
        JOIN ingestion_runs ir ON ir.id=sd.ingestion_run_id
        WHERE sd.endpoint=?
        ORDER BY sd.retrieved_at_ms, sd.id
    """
    for row in con.execute(query, (ENDPOINT,)):
        raw_params = row["request_params_json"]
        try:
            params = json.loads(raw_params)
            date = day8(params.get("race_dt"))
            meet = int(params.get("rccrs_cd"))
            page = int(params.get("pageNo", 1))
            params_ok = True
        except (ValueError, TypeError, AttributeError, json.JSONDecodeError):
            params = {}
            date, meet, page = "", None, None
            params_ok = False
        if not params_ok or meet not in MEETS or not (START_DAY <= date <= END_DAY):
            continue
        documents.append({
            "source_kind": "operational_source_document",
            "batch_group_id": f"operational:{row['ingestion_run_id']}:{date}:{meet}",
            "document_ref": f"operational:source_document:{row['document_id']}",
            "document_id": int(row["document_id"]),
            "ingestion_run_id": int(row["ingestion_run_id"]),
            "event_date": date,
            "meet": meet,
            "page_no": page,
            "local_path": str(row["local_path"]),
            "sha256_expected": str(row["sha256"]),
            "requested_at_ms": int(row["requested_at_ms"]),
            "retrieved_at_ms": int(row["retrieved_at_ms"]),
            "http_status_code": row["http_status_code"],
            "response_bytes": int(row["response_bytes"]),
            "endpoint": str(row["endpoint"]),
            "operation": row["operation"] or "",
            "run_source": row["run_source"],
            "run_data_type": str(row["run_data_type"]),
            "run_started_at_ms": int(row["run_started_at_ms"]),
            "run_completed_at_ms": row["run_completed_at_ms"],
            "run_status": str(row["run_status"]),
            "request_identity_basis": "source_documents.request_params_json_allowlisted_fields",
            "capture_time_basis": "source_documents.retrieved_at_ms",
        })

    operational_rows: list[dict[str, object]] = []
    q_entries = """
        SELECT rc.kra_meet_code meet, r.race_date_local event_date,
               r.race_number race_no, e.horse_number horse_no,
               h.kra_horse_id horse_id, h.name_ko horse_name, e.id entry_id
        FROM race_entries e
        JOIN races r ON r.id=e.race_id
        JOIN racecourses rc ON rc.id=r.racecourse_id
        JOIN horses h ON h.id=e.horse_id
        WHERE rc.kra_meet_code IN (1,3,4)
          AND r.race_date_local BETWEEN '2010-01-01' AND '2026-09-29'
    """
    for row in con.execute(q_entries):
        operational_rows.append({
            "meet": int(row["meet"]), "event_date": day8(row["event_date"]),
            "race_no": int(row["race_no"]), "horse_no": int(row["horse_no"]),
            "horse_id": str(row["horse_id"]), "horse_name": str(row["horse_name"]),
            "entry_id": int(row["entry_id"]),
        })

    snapshot_meta = {
        "operational_snapshot_started_at_utc": snapshot_started,
        "operational_data_version": data_version,
        "operational_schema_version": schema_version,
        "operational_db_sha256_before": before,
        "operational_wal_sha256_before": wal_before,
    }
    return con, snapshot_meta, documents, operational_rows


def core_snapshot() -> tuple[dict[tuple[int, str, int, int], list[dict[str, object]]], list[dict[str, object]], str]:
    core_hash_before = sha256(CORE)
    db = duckdb.connect(str(CORE), read_only=True)
    raw_rows = db.execute("""
        SELECT source_meet, result_date, result_race_no, horse_program_no_raw,
               horse_id_raw, horse_name_raw
        FROM confirmed_runners
        WHERE source_meet IN ('1','3','4')
          AND result_date BETWEEN '20100101' AND '20260929'
        ORDER BY source_meet, result_date, result_race_no, horse_program_no_raw
    """).fetchall()
    db.close()
    core_hash_after = sha256(CORE)
    if core_hash_before != core_hash_after:
        raise RuntimeError("core database changed during read-only inventory")
    keyed: dict[tuple[int, str, int, int], list[dict[str, object]]] = defaultdict(list)
    ledger: list[dict[str, object]] = []
    for meet_raw, date_raw, race_raw, horse_raw, horse_id_raw, horse_name_raw in raw_rows:
        key = (int(meet_raw), day8(date_raw), number(race_raw), number(horse_raw))
        record = {
            "meet": key[0], "event_date": key[1], "race_no": key[2], "horse_no": key[3],
            "horse_id": clean(horse_id_raw), "horse_name": clean(horse_name_raw),
            "horse_name_normalized": normalize_name(horse_name_raw),
        }
        if None in key:
            raise ValueError("core runner has invalid meet/date/race/program identity")
        keyed[key].append(record)
        ledger.append(record)
    return keyed, ledger, core_hash_after


def archived_documents() -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    if not ARCHIVE_ROOT.exists():
        return result
    for path in sorted(ARCHIVE_ROOT.glob("api78_*.json")):
        match = ARCHIVE_NAME.fullmatch(path.name)
        if not match:
            continue
        meet, date = int(match.group(1)), match.group(2)
        if meet not in MEETS or not (START_DAY <= date <= END_DAY):
            continue
        sidecar = path.with_name(path.stem + ".metadata.json")
        try:
            metadata = json.loads(sidecar.read_bytes())
            content_hash = sha256(path)
            expected_hash = str(metadata["sha256"])
            if content_hash != expected_hash:
                raise ValueError("archive_hash_mismatch")
            if int(metadata.get("http_status") or 0) != 200:
                raise ValueError("archive_http_status_not_200")
            requested = iso_kst_to_ms(metadata.get("requested_at_kst"))
            retrieved = iso_kst_to_ms(metadata.get("retrieved_at_kst"))
            if requested is None or retrieved is None:
                raise ValueError("archive_capture_time_missing")
            file_ok = True
            validation_error = ""
        except Exception as exc:
            metadata = {}
            content_hash = sha256(path)
            expected_hash = clean(metadata.get("sha256"))
            requested = retrieved = None
            file_ok = False
            validation_error = str(exc) or type(exc).__name__
        result.append({
            "source_kind": "review_archive_document",
            "batch_group_id": "archive:" + str(path.relative_to(ROOT)),
            "document_ref": "archive:" + str(path.relative_to(ROOT)),
            "document_id": "",
            "ingestion_run_id": "",
            "event_date": date,
            "meet": meet,
            "page_no": 1,
            "local_path": str(path.relative_to(ROOT)),
            "absolute_path": path,
            "sha256_expected": expected_hash,
            "sha256_actual": content_hash,
            "requested_at_ms": requested,
            "retrieved_at_ms": retrieved,
            "http_status_code": metadata.get("http_status", ""),
            "response_bytes": path.stat().st_size,
            "endpoint": ENDPOINT,
            "operation": "chulmainfo",
            "run_source": "",
            "run_data_type": "",
            "run_started_at_ms": "",
            "run_completed_at_ms": "",
            "run_status": "",
            "request_identity_basis": "archive_filename_and_payload_date",
            "capture_time_basis": metadata.get("retrieved_at_basis", "") if metadata else "",
            "metadata_valid": file_ok,
            "prevalidation_error": validation_error,
        })
    return result


def capture_queue_records() -> list[dict[str, object]]:
    """Return safe date/meet entries from the historical capture queue."""
    targets_path = HISTORICAL_ROOT / "targets.json"
    manifest_path = HISTORICAL_ROOT / "capture_manifest.json"
    targets_bytes = HISTORICAL_TARGETS_BYTES
    manifest_bytes = HISTORICAL_MANIFEST_BYTES
    if targets_bytes is None and targets_path.is_file():
        targets_bytes = targets_path.read_bytes()
    if manifest_bytes is None and manifest_path.is_file():
        manifest_bytes = manifest_path.read_bytes()
    if targets_bytes is None:
        return []
    targets_data = json.loads(targets_bytes)
    queued = []
    for item in targets_data.get("targets", []):
        try:
            date, meet = day8(item.get("date")), int(item.get("meet"))
        except (AttributeError, TypeError, ValueError):
            continue
        if meet in MEETS and START_DAY <= date <= END_DAY:
            queued.append((date, meet))
    manifest_records: dict[tuple[str, int], dict[str, object]] = {}
    if manifest_bytes is not None:
        manifest = json.loads(manifest_bytes)
        for record in manifest.get("records", []):
            try:
                key = (day8(record.get("date")), int(record.get("meet")))
            except (AttributeError, TypeError, ValueError):
                continue
            if key[1] in MEETS and START_DAY <= key[0] <= END_DAY:
                # Copy only the few scalar fields needed by the CSV.
                manifest_records[key] = {
                    "record_complete": bool(record.get("complete")),
                    "record_error_present": bool(record.get("error")),
                    "record_page_count": len(record.get("pages", [])),
                    "record_total_count": record.get("total_count", ""),
                }
    return [
        {"event_date": date, "meet": meet, **manifest_records.get((date, meet), {})}
        for date, meet in sorted(set(queued), key=lambda pair: (pair[0], pair[1]))
    ]


def additional_historical_documents() -> list[dict[str, object]]:
    """Import local captures from an adjacent folder using a sanitized sidecar.

    Each page may have a sidecar named `<stem>.metadata.json` or
    `<filename>.metadata.json`. Sidecars must carry date, meet, page, sha256,
    HTTP status, and retrieval time fields; raw URLs/params are never read.
    """
    result: list[dict[str, object]] = []
    if not HISTORICAL_ROOT.exists():
        return result
    manifest_artifacts: set[str] = set()
    manifest_path = HISTORICAL_ROOT / "capture_manifest.json"
    manifest_bytes = HISTORICAL_MANIFEST_BYTES
    if manifest_bytes is None and manifest_path.is_file():
        manifest_bytes = manifest_path.read_bytes()
    if manifest_bytes is not None:
        # The incoming manifest can contain source_url. Only allowlisted page
        # fields are copied; no URL or request blob enters the frozen exports.
        manifest = json.loads(manifest_bytes)
        for record_index, record in enumerate(manifest.get("records", [])):
            try:
                date = day8(record.get("date"))
                meet = int(record.get("meet"))
            except (TypeError, ValueError):
                continue
            if meet not in MEETS or not (START_DAY <= date <= END_DAY):
                continue
            group_id = f"historical_manifest:{record_index}:{meet}:{date}"
            for page in record.get("pages", []):
                artifact = clean(page.get("artifact"))
                if not artifact:
                    continue
                candidate = Path(artifact)
                if not candidate.is_absolute():
                    candidate = ROOT / candidate
                try:
                    resolved = candidate.resolve(strict=True)
                    if not resolved.is_file() or not resolved.is_relative_to(ROOT):
                        raise ValueError("historical_artifact_outside_repository")
                    relpath = str(resolved.relative_to(ROOT))
                    page_date = day8(page.get("date", record.get("date")))
                    page_meet = int(page.get("meet", record.get("meet")))
                    page_no = int(page.get("page", 1))
                    expected_hash = str(page.get("sha256") or "")
                    requested = iso_kst_to_ms(page.get("requested_at_kst"))
                    retrieved = iso_kst_to_ms(page.get("retrieved_at_kst"))
                    status = int(page.get("http_status") or 0)
                    issues = []
                    if page_date != date or page_meet != meet:
                        issues.append("page_identity_differs_from_capture_record")
                    if status != 200:
                        issues.append("http_status_not_200")
                    if not expected_hash:
                        issues.append("sha256_missing")
                    if retrieved is None:
                        issues.append("retrieval_time_missing")
                    actual_hash = sha256(resolved)
                    if expected_hash and actual_hash != expected_hash:
                        issues.append("sha256_mismatch")
                    manifest_artifacts.add(str(resolved))
                    result.append({
                        "source_kind": "historical_raw_document",
                        "batch_group_id": group_id,
                        "document_ref": "historical_raw:" + relpath,
                        "document_id": "", "ingestion_run_id": "",
                        "event_date": date, "meet": meet, "page_no": page_no,
                        "local_path": relpath, "absolute_path": resolved,
                        "sha256_expected": expected_hash,
                        "sha256_actual": actual_hash,
                        "requested_at_ms": requested or "",
                        "retrieved_at_ms": retrieved or "",
                        "http_status_code": status,
                        "response_bytes": resolved.stat().st_size,
                        "endpoint": ENDPOINT, "operation": "chulmainfo",
                        "run_source": "", "run_data_type": "historical_raw_capture",
                        "run_started_at_ms": "", "run_completed_at_ms": "", "run_status": "",
                        "request_identity_basis": "capture_manifest_allowlisted_date_meet_page",
                        "capture_time_basis": clean(page.get("retrieved_at_basis")),
                        "metadata_valid": not issues,
                        "prevalidation_error": ";".join(issues),
                    })
                except Exception as exc:
                    result.append({
                        "source_kind": "historical_raw_document",
                        "batch_group_id": group_id,
                        "document_ref": "historical_raw:" + artifact,
                        "document_id": "", "ingestion_run_id": "",
                        "event_date": date, "meet": meet,
                        "page_no": page.get("page", ""), "local_path": artifact,
                        "absolute_path": None, "sha256_expected": clean(page.get("sha256")),
                        "sha256_actual": "", "requested_at_ms": "", "retrieved_at_ms": "",
                        "http_status_code": page.get("http_status", ""),
                        "response_bytes": "", "endpoint": ENDPOINT,
                        "operation": "chulmainfo", "run_source": "",
                        "run_data_type": "historical_raw_capture", "run_started_at_ms": "",
                        "run_completed_at_ms": "", "run_status": "",
                        "request_identity_basis": "capture_manifest_allowlisted_date_meet_page",
                        "capture_time_basis": clean(page.get("retrieved_at_basis")),
                        "metadata_valid": False,
                        "prevalidation_error": str(exc) or type(exc).__name__,
                    })
    safe_keys = {
        "event_date", "race_date", "race_dt", "meet", "rccrs_cd", "page_no",
        "pageNo", "sha256", "http_status_code", "http_status", "status_code",
        "requested_at_ms", "retrieved_at_ms", "requested_at_kst", "retrieved_at_kst",
        "capture_time_basis", "request_identity_basis",
    }
    for path in sorted(p for p in HISTORICAL_ROOT.rglob("*.json") if ".metadata." not in p.name and not p.name.endswith(".metadata.json")):
        if str(path.resolve()) in manifest_artifacts:
            continue
        sidecars = [path.with_name(path.stem + ".metadata.json"), path.with_name(path.name + ".metadata.json")]
        metadata_path = next((candidate for candidate in sidecars if candidate.is_file()), None)
        if metadata_path is None:
            continue
        try:
            raw_metadata = json.loads(metadata_path.read_bytes())
            metadata = {key: value for key, value in raw_metadata.items() if key in safe_keys}
            date = day8(metadata.get("event_date", metadata.get("race_date", metadata.get("race_dt"))))
            meet = int(metadata.get("meet", metadata.get("rccrs_cd")))
            page = int(metadata.get("page_no", metadata.get("pageNo", 1)))
            expected_hash = str(metadata["sha256"])
            content_hash = sha256(path)
            http_status = int(metadata.get("http_status_code", metadata.get("http_status", metadata.get("status_code", 0))))
            retrieved = metadata.get("retrieved_at_ms") or iso_kst_to_ms(metadata.get("retrieved_at_kst"))
            requested = metadata.get("requested_at_ms") or iso_kst_to_ms(metadata.get("requested_at_kst"))
            if content_hash != expected_hash or http_status != 200 or retrieved is None:
                raise ValueError("historical_sidecar_validation_failed")
            if meet not in MEETS or not (START_DAY <= date <= END_DAY):
                continue
            validation_error = ""
            metadata_valid = True
        except Exception as exc:
            # Keep identifiable invalid historical files in a diagnostic manifest.
            date, meet, page = "", None, None
            content_hash = sha256(path)
            expected_hash = ""
            requested = retrieved = None
            http_status = ""
            validation_error = str(exc) or type(exc).__name__
            metadata_valid = False
        result.append({
            "source_kind": "historical_raw_document",
            "batch_group_id": "historical_sidecar:" + str(path.relative_to(ROOT)),
            "document_ref": "historical_raw:" + str(path.relative_to(ROOT)),
            "document_id": "",
            "ingestion_run_id": "",
            "event_date": date,
            "meet": meet,
            "page_no": page,
            "local_path": str(path.relative_to(ROOT)),
            "absolute_path": path,
            "sha256_expected": expected_hash,
            "sha256_actual": content_hash,
            "requested_at_ms": requested or "",
            "retrieved_at_ms": retrieved or "",
            "http_status_code": http_status,
            "response_bytes": path.stat().st_size,
            "endpoint": ENDPOINT,
            "operation": "chulmainfo",
            "run_source": "",
            "run_data_type": "historical_raw_capture",
            "run_started_at_ms": "",
            "run_completed_at_ms": "",
            "run_status": "",
            "request_identity_basis": metadata.get("request_identity_basis", "historical_manifest_allowlisted_fields") if metadata_valid else "",
            "capture_time_basis": metadata.get("capture_time_basis", "") if metadata_valid else "",
            "metadata_valid": metadata_valid,
            "prevalidation_error": validation_error,
        })
    return result


def verify_document(document: dict[str, object]) -> tuple[dict[str, object], list[dict[str, object]]]:
    details = dict(document)
    details.pop("absolute_path", None)
    details["file_hash_valid"] = False
    details["payload_valid"] = False
    details["page_total_count"] = ""
    details["page_size"] = ""
    details["item_count"] = 0
    details["validation_error"] = clean(document.get("prevalidation_error"))
    try:
        path = document.get("absolute_path")
        if path is None:
            path = safe_raw_path(str(document["local_path"]))
        actual_hash = sha256(Path(path))
        details["sha256_actual"] = actual_hash
        details["file_hash_valid"] = actual_hash == str(document["sha256_expected"])
        if not details["file_hash_valid"]:
            raise ValueError("sha256_mismatch")
        if int(document.get("http_status_code") or 0) != 200:
            raise ValueError("http_status_not_200")
        body, items = read_payload(Path(path))
        date = str(document["event_date"])
        total = number(body.get("totalCount"))
        page_size = number(body.get("numOfRows"))
        body_page = number(body.get("pageNo"))
        if total is None or page_size is None or page_size < 1:
            raise ValueError("page_total_or_size_missing")
        if body_page != int(document["page_no"]):
            raise ValueError("request_response_page_disagrees")
        if int(document["page_no"]) < 1:
            raise ValueError("page_number_invalid")
        if len(items) > page_size:
            raise ValueError("page_item_count_exceeds_page_size")
        item_dates = [day8(item.get("raceDt")) for item in items if item.get("raceDt") not in (None, "")]
        if any(item_date != date for item_date in item_dates):
            raise ValueError("item_date_differs_from_request")
        item_keys: list[tuple[int, int]] = []
        for item in items:
            race_no = number(item.get("raceNo"))
            horse_no = number(item.get("gtno"))
            if race_no is None or horse_no is None:
                raise ValueError("runner_race_or_program_missing")
            item_keys.append((race_no, horse_no))
        if len(item_keys) != len(set(item_keys)):
            raise ValueError("duplicate_race_program_key_on_page")
        details["page_total_count"] = total
        details["page_size"] = page_size
        details["item_count"] = len(items)
        details["payload_valid"] = True
        details["validation_error"] = ""
        details["_body"] = body
        details["_items"] = items
        return details, items
    except Exception as exc:
        details["validation_error"] = str(exc) or type(exc).__name__
        return details, []


def validate_batches(documents: list[dict[str, object]]) -> tuple[list[dict[str, object]], dict[tuple[str, int, str], dict[str, object]]]:
    verified_docs: list[dict[str, object]] = []
    grouped: dict[tuple[str, int, str], list[dict[str, object]]] = defaultdict(list)
    for document in documents:
        verified, _ = verify_document(document)
        verified_docs.append(verified)
        group_id = str(document.get("batch_group_id") or document.get("ingestion_run_id") or document["document_ref"])
        grouped[(str(document["event_date"]), int(document["meet"]), group_id)].append(verified)

    batches: list[dict[str, object]] = []
    selected_payloads: dict[tuple[str, int, str], dict[str, object]] = {}
    by_date_meet: dict[tuple[str, int], list[dict[str, object]]] = defaultdict(list)
    for (date, meet, run_or_ref), pages in grouped.items():
        source_kind = str(pages[0]["source_kind"])
        run_id = pages[0].get("ingestion_run_id") or ""
        # Archive/historical files are distinct one-page capture groups.
        ordered = sorted(pages, key=lambda page: int(page["page_no"] or 0))
        errors = [str(page["validation_error"]) for page in ordered if page["validation_error"]]
        page_numbers = [int(page["page_no"] or 0) for page in ordered]
        totals = {int(page["page_total_count"]) for page in ordered if page["page_total_count"] != ""}
        sizes = {int(page["page_size"]) for page in ordered if page["page_size"] != ""}
        flat_items = []
        for page in ordered:
            for item in page.get("_items", []):
                flat_items.append({**item, "_inventory_page_no": int(page["page_no"])})
        if len(page_numbers) != len(set(page_numbers)):
            errors.append("duplicate_page_number")
        if page_numbers != list(range(1, len(ordered) + 1)):
            errors.append("page_sequence_not_contiguous_from_one")
        if len(totals) != 1 or len(sizes) != 1:
            errors.append("page_total_or_size_inconsistent")
        elif totals:
            total, page_size = next(iter(totals)), next(iter(sizes))
            expected_pages = max(1, (total + page_size - 1) // page_size)
            if len(ordered) != expected_pages:
                errors.append("page_count_does_not_cover_total")
            if len(flat_items) != total:
                errors.append("item_count_does_not_equal_total")
        all_keys = []
        for item in flat_items:
            all_keys.append((number(item.get("raceNo")), number(item.get("gtno"))))
        if len(all_keys) != len(set(all_keys)):
            errors.append("duplicate_runner_key_across_pages")
        complete = not errors and bool(ordered)
        retrieved = max((int(page["retrieved_at_ms"]) for page in ordered if str(page.get("retrieved_at_ms", "")).isdigit()), default=None)
        requested = min((int(page["requested_at_ms"]) for page in ordered if str(page.get("requested_at_ms", "")).isdigit()), default=None)
        run_statuses = {str(page.get("run_status") or "") for page in ordered if page.get("run_status")}
        run_status = next(iter(run_statuses)) if len(run_statuses) == 1 else "mixed" if run_statuses else ""
        source_refs = [str(page["document_ref"]) for page in ordered]
        batch_id = f"{source_kind}:{date}:{meet}:{run_or_ref}"
        batch = {
            "batch_id": batch_id, "event_date": date, "meet": meet,
            "source_kind": source_kind, "ingestion_run_id": run_id,
            "ingestion_run_status": run_status,
            "source_document_refs": ";".join(source_refs),
            "page_count": len(ordered), "page_numbers": ";".join(map(str, page_numbers)),
            "api_total_count": next(iter(totals)) if len(totals) == 1 else "",
            "observed_runner_count": len(flat_items),
            "complete_payload": complete,
            "validation_errors": ";".join(dict.fromkeys(errors)),
            "requested_at_ms": requested or "", "requested_at_kst": ms_to_kst(requested),
            "retrieved_at_ms": retrieved or "", "retrieved_at_kst": ms_to_kst(retrieved),
            "capture_time_basis": ";".join(sorted({str(page.get("capture_time_basis") or "") for page in ordered if page.get("capture_time_basis")})),
        }
        batches.append(batch)
        by_date_meet[(date, meet)].append(batch)
        if complete:
            selected_payloads[(date, meet, batch_id)] = {
                "batch": batch, "pages": ordered, "items": flat_items,
            }
    selected: dict[tuple[str, int], dict[str, object]] = {}
    for key, options in by_date_meet.items():
        complete_options = [item for item in options if item["complete_payload"]]
        if not complete_options:
            continue
        chosen = max(complete_options, key=lambda item: (
            int(item["retrieved_at_ms"] or 0),
            int(item["requested_at_ms"] or 0),
            str(item["batch_id"]),
        ))
        selected[key] = selected_payloads[(key[0], key[1], str(chosen["batch_id"]))]
    return verified_docs, {"batches": batches, "selected": selected}


def link_observation(
    *, key: tuple[int, str, int, int], api_name: str,
    core_by_key: dict[tuple[int, str, int, int], list[dict[str, object]]],
    op_by_key: dict[tuple[int, str, int, int], list[dict[str, object]]],
) -> dict[str, object]:
    core_candidates = core_by_key.get(key, [])
    op_candidates = op_by_key.get(key, [])
    api_norm = normalize_name(api_name)
    core_name_matches = [row for row in core_candidates if api_norm and api_norm == row["horse_name_normalized"]]
    op_name_matches = [row for row in op_candidates if api_norm and api_norm == normalize_name(row["horse_name"])]
    fields: dict[str, object] = {
        "api_horse_name_normalized": api_norm,
        "core_key_candidate_count": len(core_candidates),
        "core_key_name_match_count": len(core_name_matches),
        "operational_key_candidate_count": len(op_candidates),
        "operational_key_name_match_count": len(op_name_matches),
        "core_horse_name_raw_candidate": core_candidates[0]["horse_name"] if len(core_candidates) == 1 else "",
        "core_horse_name_normalized_candidate": core_candidates[0]["horse_name_normalized"] if len(core_candidates) == 1 else "",
        "operational_horse_name_raw_candidate": op_candidates[0]["horse_name"] if len(op_candidates) == 1 else "",
        "operational_horse_id_candidate": op_candidates[0]["horse_id"] if len(op_candidates) == 1 else "",
        "linked_core_horse_id": "",
        "link_method": "",
        "link_status": "unresolved",
        "link_reason": "",
    }
    if len(core_candidates) == 0:
        fields["link_reason"] = "no_core_runner_at_exact_meet_date_race_program"
        return fields
    if len(core_candidates) > 1:
        fields["link_reason"] = "multiple_core_runners_at_exact_meet_date_race_program"
        return fields
    if not api_norm:
        fields["link_reason"] = "api78_horse_name_missing_or_blank"
        return fields
    if len(core_name_matches) != 1:
        fields["link_reason"] = "normalized_api_name_does_not_match_unique_core_runner"
        return fields
    core = core_candidates[0]
    if len(op_candidates) > 1:
        fields["link_reason"] = "multiple_operational_entries_at_exact_key"
        return fields
    if len(op_candidates) == 1:
        op = op_candidates[0]
        if op["horse_id"] != core["horse_id"]:
            fields["link_reason"] = "operational_and_core_official_horse_ids_disagree"
            return fields
        if not op_name_matches:
            fields["link_reason"] = "normalized_api_name_does_not_match_operational_name"
            return fields
        fields["link_status"] = "linked_op_id_corroborated"
        fields["link_method"] = "exact_meet_date_race_program+normalized_name+matching_operational_official_id"
    else:
        fields["link_status"] = "linked_core_key_name_only"
        fields["link_method"] = "exact_meet_date_race_program+normalized_name+core_official_result_id"
    fields["linked_core_horse_id"] = core["horse_id"]
    return fields


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def sanitized_manifest_bytes(raw: bytes | None) -> bytes | None:
    if raw is None:
        return None
    source = json.loads(raw)
    forbidden = {"source_url", "url", "request_params", "request_params_json", "servicekey", "api_key", "apikey"}

    def sanitize(value: object) -> object:
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                normalized = str(key).casefold()
                if normalized in forbidden or normalized.endswith("_url") or "servicekey" in normalized or "api_key" in normalized:
                    continue
                if normalized in {"error", "error_message", "exception", "traceback"}:
                    result["error_present"] = bool(item)
                    continue
                result[key] = sanitize(item)
            return result
        if isinstance(value, list):
            return [sanitize(item) for item in value]
        return value

    return (json.dumps(sanitize(source), ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def main() -> None:
    global HISTORICAL_MANIFEST_BYTES, HISTORICAL_TARGETS_BYTES
    OUT.mkdir(parents=True, exist_ok=True)
    manifest_path = HISTORICAL_ROOT / "capture_manifest.json"
    targets_path = HISTORICAL_ROOT / "targets.json"
    HISTORICAL_MANIFEST_BYTES = manifest_path.read_bytes() if manifest_path.is_file() else None
    HISTORICAL_TARGETS_BYTES = targets_path.read_bytes() if targets_path.is_file() else None
    historical_manifest_sha = hashlib.sha256(HISTORICAL_MANIFEST_BYTES).hexdigest() if HISTORICAL_MANIFEST_BYTES is not None else ""
    historical_targets_sha = hashlib.sha256(HISTORICAL_TARGETS_BYTES).hexdigest() if HISTORICAL_TARGETS_BYTES is not None else ""
    historical_manifest_snapshot_kst = datetime.now(timezone.utc).astimezone(KST).isoformat(timespec="milliseconds")
    snapshot_tag = datetime.now(timezone.utc).astimezone(KST).strftime("%Y%m%dT%H%M%S%fKST")
    manifest_snapshot = sanitized_manifest_bytes(HISTORICAL_MANIFEST_BYTES)
    targets_snapshot = sanitized_manifest_bytes(HISTORICAL_TARGETS_BYTES)
    manifest_snapshot_path = OUT / f"historical_capture_manifest_frozen_{snapshot_tag}.json"
    targets_snapshot_path = OUT / f"historical_targets_frozen_{snapshot_tag}.json"
    if manifest_snapshot is not None:
        manifest_snapshot_path.write_bytes(manifest_snapshot)
    if targets_snapshot is not None:
        targets_snapshot_path.write_bytes(targets_snapshot)
    manifest_snapshot_sha = hashlib.sha256(manifest_snapshot).hexdigest() if manifest_snapshot is not None else ""
    targets_snapshot_sha = hashlib.sha256(targets_snapshot).hexdigest() if targets_snapshot is not None else ""
    sqlite_con, snapshot_meta, db_documents, operational_rows = sqlite_snapshot()
    core_by_key, core_rows, core_hash = core_snapshot()
    op_by_key: dict[tuple[int, str, int, int], list[dict[str, object]]] = defaultdict(list)
    for row in operational_rows:
        key = (row["meet"], row["event_date"], row["race_no"], row["horse_no"])
        op_by_key[key].append(row)
    duplicates = {key: len(rows) for key, rows in op_by_key.items() if len(rows) > 1}
    if duplicates:
        raise ValueError(f"operational exact event/program key is not unique: {len(duplicates)}")

    documents = db_documents + archived_documents() + additional_historical_documents()
    verified_documents, inventory = validate_batches(documents)
    all_batches = inventory["batches"]
    selected = inventory["selected"]

    target_date_meets = sorted({(row["event_date"], row["meet"]) for row in core_rows})
    target_date_meet_set = set(target_date_meets)
    core_runner_count_by_date_meet = Counter((row["event_date"], row["meet"]) for row in core_rows)
    missing_date_meets = [
        {"event_date": date, "meet": meet, "missing_reason": "no_hash_and_page_verified_complete_api78_capture"}
        for date, meet in target_date_meets if (date, meet) not in selected
    ]

    selected_batch_rows: list[dict[str, object]] = []
    selected_page_rows: list[dict[str, object]] = []
    runner_rows: list[dict[str, object]] = []
    mark_rows: list[dict[str, object]] = []
    observation_by_key: dict[tuple[int, str, int, int], list[dict[str, object]]] = defaultdict(list)
    batch_by_date_meet = {key: payload["batch"] for key, payload in selected.items()}

    for key, payload in sorted(selected.items(), key=lambda item: (item[0][0], item[0][1])):
        batch = payload["batch"]
        source_items = payload["items"]
        batch_rows: list[dict[str, object]] = []
        state_counts: Counter[str] = Counter()
        added_marks = removed_marks = 0
        for page in payload["pages"]:
            page_row = {
                "batch_id": batch["batch_id"], "event_date": key[0], "meet": key[1],
                "source_kind": page["source_kind"], "document_ref": page["document_ref"],
                "document_id": page.get("document_id", ""),
                "ingestion_run_id": page.get("ingestion_run_id", ""),
                "ingestion_run_status": page.get("run_status", ""),
                "page_no": page["page_no"], "local_path": page["local_path"],
                "sha256": page["sha256_actual"],
                "requested_at_ms": page.get("requested_at_ms", ""),
                "requested_at_kst": ms_to_kst(int(page["requested_at_ms"])) if str(page.get("requested_at_ms", "")).isdigit() else "",
                "retrieved_at_ms": page.get("retrieved_at_ms", ""),
                "retrieved_at_kst": ms_to_kst(int(page["retrieved_at_ms"])) if str(page.get("retrieved_at_ms", "")).isdigit() else "",
                "http_status_code": page.get("http_status_code", ""),
                "response_bytes": page.get("response_bytes", ""),
                "request_identity_basis": page.get("request_identity_basis", ""),
                "capture_time_basis": page.get("capture_time_basis", ""),
            }
            selected_page_rows.append(page_row)
        for source_index, item in enumerate(source_items, start=1):
            race_no = number(item.get("raceNo"))
            horse_no = number(item.get("gtno"))
            raw_name = clean(item.get("hrnm"))
            equipment_present = "equipCrs" in item
            raw_equipment = item.get("equipCrs") if equipment_present else None
            if not equipment_present:
                value_state = "field_missing"
            elif raw_equipment is None:
                value_state = "null"
            elif not str(raw_equipment).strip():
                value_state = "blank"
            else:
                value_state = "nonblank"
            state_counts[value_state] += 1
            full_key = (key[1], key[0], int(race_no), int(horse_no))
            link = link_observation(
                key=full_key, api_name=raw_name, core_by_key=core_by_key, op_by_key=op_by_key,
            )
            page_no = int(item.get("_inventory_page_no") or 1)
            matching_page = next((page for page in payload["pages"] if int(page["page_no"]) == page_no), payload["pages"][0])
            observation_id = f"{batch['batch_id']}:r{race_no}:g{horse_no}"
            record = {
                "observation_id": observation_id,
                "batch_id": batch["batch_id"],
                "source_kind": batch["source_kind"],
                "source_document_ref": matching_page["document_ref"],
                "source_document_id": matching_page.get("document_id", ""),
                "ingestion_run_id": matching_page.get("ingestion_run_id", ""),
                "ingestion_run_status": matching_page.get("run_status", ""),
                "source_sha256": matching_page["sha256_actual"],
                "page_no": matching_page["page_no"],
                "source_index_in_batch": source_index,
                "event_date": key[0], "meet": key[1],
                "race_no": int(race_no), "horse_no": int(horse_no),
                "api_horse_name_raw": raw_name,
                "api_horse_name_normalized": link["api_horse_name_normalized"],
                "equipment_raw": "" if raw_equipment is None else str(raw_equipment),
                "equipment_field_present": equipment_present,
                "equipment_is_null": equipment_present and raw_equipment is None,
                "equipment_value_state": value_state,
                "linked_core_meet": key[1] if link["linked_core_horse_id"] else "",
                "linked_core_event_date": key[0] if link["linked_core_horse_id"] else "",
                "linked_core_race_no": int(race_no) if link["linked_core_horse_id"] else "",
                "linked_core_horse_no": int(horse_no) if link["linked_core_horse_id"] else "",
                **link,
                "request_date": key[0], "capture_retrieved_at_ms": batch["retrieved_at_ms"],
                "capture_retrieved_at_kst": batch["retrieved_at_kst"],
            }
            runner_rows.append(record)
            batch_rows.append(record)
            observation_by_key[full_key].append(record)
            if value_state == "nonblank":
                raw_text = str(raw_equipment)
                for position, token in enumerate(raw_text.split(","), start=1):
                    match = MARK.fullmatch(token.strip())
                    if match is None or not match.group(1).strip():
                        continue
                    change_type = "added" if match.group(2) == "+" else "removed"
                    added_marks += change_type == "added"
                    removed_marks += change_type == "removed"
                    mark_rows.append({
                        "observation_id": observation_id,
                        "batch_id": batch["batch_id"], "source_document_ref": matching_page["document_ref"],
                        "source_sha256": matching_page["sha256_actual"],
                        "event_date": key[0], "meet": key[1], "race_no": int(race_no), "horse_no": int(horse_no),
                        "api_horse_name_raw": raw_name,
                        "linked_core_horse_id": link["linked_core_horse_id"],
                        "link_status": link["link_status"],
                        "position": position, "token_raw": token,
                        "equipment_name_raw": match.group(1).strip(), "change_type": change_type,
                    })
        selected_batch_rows.append({
            **batch,
            "selected": True,
            "core_date_meet_target": (key[0], key[1]) in target_date_meet_set,
            "core_runner_count_for_date_meet": core_runner_count_by_date_meet[(key[0], key[1])],
            "runner_rows_exported": len(batch_rows),
            "equipment_field_missing_count": state_counts["field_missing"],
            "equipment_null_count": state_counts["null"],
            "equipment_blank_count": state_counts["blank"],
            "equipment_nonblank_count": state_counts["nonblank"],
            "equipment_blank_or_null_count": state_counts["field_missing"] + state_counts["null"] + state_counts["blank"],
            "explicit_added_mark_count": added_marks,
            "explicit_removed_mark_count": removed_marks,
            "linked_op_id_corroborated_count": sum(row["link_status"] == "linked_op_id_corroborated" for row in batch_rows),
            "linked_core_key_name_only_count": sum(row["link_status"] == "linked_core_key_name_only" for row in batch_rows),
            "unresolved_identity_count": sum(row["link_status"] == "unresolved" for row in batch_rows),
        })

    core_ledger: list[dict[str, object]] = []
    absence_evidence: list[dict[str, object]] = []
    api_names_by_date_meet: dict[tuple[str, int], dict[str, list[dict[str, object]]]] = defaultdict(lambda: defaultdict(list))
    for api_row in runner_rows:
        normalized = str(api_row["api_horse_name_normalized"])
        if normalized:
            api_names_by_date_meet[(api_row["event_date"], api_row["meet"])][normalized].append(api_row)
    for core_row in core_rows:
        key = (core_row["meet"], core_row["event_date"], core_row["race_no"], core_row["horse_no"])
        candidates = observation_by_key.get(key, [])
        batch = batch_by_date_meet.get((key[1], key[0]))
        linked = [row for row in candidates if row["linked_core_horse_id"] == core_row["horse_id"]]
        if len(candidates) > 1:
            state = "ambiguous_api78_exact_key"
        elif len(linked) == 1:
            state = {
                "null": "observed_null",
                "blank": "observed_blank",
                "nonblank": "observed_nonblank",
                "field_missing": "observed_equipment_field_missing",
            }[linked[0]["equipment_value_state"]]
        elif candidates:
            state = "unresolved_api78_identity_candidate"
        elif batch:
            state = "runner_absent_from_complete_api78_card"
        else:
            state = "no_complete_api78_batch_for_date_meet"
        candidate = candidates[0] if len(candidates) == 1 else {}
        same_name_rows = api_names_by_date_meet[(key[1], key[0])].get(core_row["horse_name_normalized"], [])
        same_name_keys = sorted({
            f"r{row['race_no']}:g{row['horse_no']}" for row in same_name_rows
        })
        if not batch:
            name_presence_state = "no_selected_complete_card"
        elif not same_name_rows:
            name_presence_state = "no_same_normalized_name_on_card"
        elif any((row["race_no"], row["horse_no"]) == (key[2], key[3]) for row in same_name_rows):
            name_presence_state = "same_name_at_exact_race_program_key"
        else:
            name_presence_state = "same_name_at_other_card_key"
        batch_pages = selected.get((key[1], key[0]), {}).get("pages", [])
        batch_sha256s = [str(page["sha256_actual"]) for page in batch_pages]
        if state == "runner_absent_from_complete_api78_card":
            absence_evidence.append({
                "core_meet": core_row["meet"], "core_event_date": core_row["event_date"],
                "core_race_no": core_row["race_no"], "core_horse_no": core_row["horse_no"],
                "core_horse_id": core_row["horse_id"], "core_horse_name_raw": core_row["horse_name"],
                "core_horse_name_normalized": core_row["horse_name_normalized"],
                "selected_batch_id": batch["batch_id"] if batch else "",
                "selected_batch_source_kind": batch["source_kind"] if batch else "",
                "selected_batch_run_status": batch["ingestion_run_status"] if batch else "",
                "selected_batch_source_document_refs": batch["source_document_refs"] if batch else "",
                "selected_batch_page_sha256s": ";".join(batch_sha256s),
                "selected_batch_page_count": batch["page_count"] if batch else "",
                "selected_batch_api_total_count": batch["api_total_count"] if batch else "",
                "selected_batch_observed_runner_count": batch["observed_runner_count"] if batch else "",
                "selected_batch_requested_at_ms": batch["requested_at_ms"] if batch else "",
                "selected_batch_retrieved_at_ms": batch["retrieved_at_ms"] if batch else "",
                "selected_batch_retrieved_at_kst": batch["retrieved_at_kst"] if batch else "",
                "api78_same_name_card_candidate_count": len(same_name_rows),
                "api78_same_name_card_keys": ";".join(same_name_keys),
                "api78_same_name_card_presence_state": name_presence_state,
            })
        core_ledger.append({
            "core_meet": core_row["meet"], "core_event_date": core_row["event_date"],
            "core_race_no": core_row["race_no"], "core_horse_no": core_row["horse_no"],
            "core_horse_id": core_row["horse_id"], "core_horse_name_raw": core_row["horse_name"],
            "core_horse_name_normalized": core_row["horse_name_normalized"],
            "equipment_observation_state": state,
            "selected_batch_id": batch["batch_id"] if batch else "",
            "selected_batch_source_kind": batch["source_kind"] if batch else "",
            "selected_batch_run_status": batch["ingestion_run_status"] if batch else "",
            "api78_observation_id_candidate": candidate.get("observation_id", ""),
            "api78_link_status_candidate": candidate.get("link_status", ""),
            "api78_link_reason_candidate": candidate.get("link_reason", ""),
            "api78_horse_name_raw_candidate": candidate.get("api_horse_name_raw", ""),
            "api78_equipment_raw_candidate": candidate.get("equipment_raw", ""),
            "api78_equipment_value_state_candidate": candidate.get("equipment_value_state", ""),
            "api78_source_document_ref_candidate": candidate.get("source_document_ref", ""),
            "api78_source_sha256_candidate": candidate.get("source_sha256", ""),
        })
    unresolved_ledger = [row for row in runner_rows if row["link_status"] == "unresolved"]

    # Batch-level inventory includes incomplete/failed pages and batches.
    batch_rows = sorted(all_batches, key=lambda row: (row["event_date"], row["meet"], row["source_kind"], row["batch_id"]))
    selected_ids = {row["batch_id"] for row in selected_batch_rows}
    for row in batch_rows:
        row["selected"] = row["batch_id"] in selected_ids
        row["core_date_meet_target"] = (row["event_date"], row["meet"]) in target_date_meet_set

    export_fields: dict[str, list[str]] = {
        "api78_runner_records.csv": list(runner_rows[0].keys()) if runner_rows else [],
        "api78_selected_batches.csv": list(selected_batch_rows[0].keys()) if selected_batch_rows else [],
        "api78_selected_pages.csv": list(selected_page_rows[0].keys()) if selected_page_rows else [],
        "api78_batch_inventory.csv": list(batch_rows[0].keys()) if batch_rows else [],
        "api78_source_document_inventory.csv": [
            "source_kind", "document_ref", "document_id", "ingestion_run_id", "event_date", "meet", "page_no",
            "local_path", "sha256_expected", "sha256_actual", "file_hash_valid", "payload_valid",
            "page_total_count", "page_size", "item_count", "requested_at_ms", "retrieved_at_ms",
            "http_status_code", "response_bytes", "run_source", "run_data_type", "run_started_at_ms",
            "run_completed_at_ms", "run_status", "request_identity_basis", "capture_time_basis",
            "validation_error",
        ],
        "api78_explicit_change_marks.csv": [
            "observation_id", "batch_id", "source_document_ref", "source_sha256", "event_date", "meet",
            "race_no", "horse_no", "api_horse_name_raw", "linked_core_horse_id", "link_status",
            "position", "token_raw", "equipment_name_raw", "change_type",
        ],
        "api78_core_runner_ledger.csv": list(core_ledger[0].keys()) if core_ledger else [],
        "api78_unresolved_runner_identity_ledger.csv": list(runner_rows[0].keys()) if runner_rows else [],
        "api78_missing_core_date_meets.csv": ["event_date", "meet", "missing_reason"],
    }
    output_rows = {
        "api78_runner_records.csv": runner_rows,
        "api78_selected_batches.csv": selected_batch_rows,
        "api78_selected_pages.csv": selected_page_rows,
        "api78_batch_inventory.csv": batch_rows,
        "api78_source_document_inventory.csv": verified_documents,
        "api78_explicit_change_marks.csv": mark_rows,
        "api78_core_runner_ledger.csv": core_ledger,
        "api78_unresolved_runner_identity_ledger.csv": unresolved_ledger,
        "api78_missing_core_date_meets.csv": missing_date_meets,
    }
    for filename, rows in output_rows.items():
        # Empty files still have a deterministic header.
        fields = export_fields[filename]
        write_csv(OUT / filename, rows, fields)

    absence_fields = [
        "core_meet", "core_event_date", "core_race_no", "core_horse_no", "core_horse_id",
        "core_horse_name_raw", "core_horse_name_normalized", "selected_batch_id",
        "selected_batch_source_kind", "selected_batch_run_status", "selected_batch_source_document_refs",
        "selected_batch_page_sha256s", "selected_batch_page_count", "selected_batch_api_total_count",
        "selected_batch_observed_runner_count", "selected_batch_requested_at_ms",
        "selected_batch_retrieved_at_ms", "selected_batch_retrieved_at_kst",
        "api78_same_name_card_candidate_count", "api78_same_name_card_keys",
        "api78_same_name_card_presence_state",
    ]
    absence_path = OUT / "core_runner_absence_evidence.csv"
    write_csv(absence_path, absence_evidence, absence_fields)

    # Summary CSVs make year/meet and historical coverage easy to consume.
    coverage = []
    coverage_counts: dict[tuple[str, int], Counter[str]] = defaultdict(Counter)
    for row in core_rows:
        coverage_counts[(row["event_date"][:4], row["meet"])]["core_runner_count"] += 1
        if (row["event_date"], row["meet"]) in selected:
            coverage_counts[(row["event_date"][:4], row["meet"])]["covered_core_runner_count"] += 1
    for (date, meet), payload in selected.items():
        batch = payload["batch"]
        coverage_counts[(date[:4], meet)]["selected_complete_date_meets"] += 1
        coverage_counts[(date[:4], meet)]["selected_api78_runner_count"] += len(payload["items"])
        coverage_counts[(date[:4], meet)]["selected_partial_run_count"] += batch["ingestion_run_status"] == "partial"
        coverage_counts[(date[:4], meet)]["selected_archived_count"] += batch["source_kind"] != "operational_source_document"
    for row in runner_rows:
        cell = coverage_counts[(row["event_date"][:4], row["meet"])]
        if row["equipment_value_state"] in {"field_missing", "null", "blank"}:
            cell["equipment_blank_or_null_count"] += 1
        elif row["equipment_value_state"] == "nonblank":
            cell["equipment_nonblank_count"] += 1
    for row in mark_rows:
        cell = coverage_counts[(row["event_date"][:4], row["meet"])]
        cell[f"explicit_{row['change_type']}_mark_count"] += 1
    missing_by_year = Counter(date[:4] for date, _meet in target_date_meets if (date, _meet) not in selected)
    target_by_year = Counter(date[:4] for date, _meet in target_date_meets)
    for year, meet in sorted(coverage_counts):
        cell = coverage_counts[(year, meet)]
        target_count = sum(1 for date, target_meet in target_date_meets if date[:4] == year and target_meet == meet)
        coverage.append({
            "year": year, "meet": meet,
            "core_target_date_meet_count": target_count,
            "selected_complete_date_meet_count": cell["selected_complete_date_meets"],
            "missing_complete_date_meet_count": target_count - cell["selected_complete_date_meets"],
            "core_runner_count": cell["core_runner_count"],
            "core_runner_count_with_selected_date_meet": cell["covered_core_runner_count"],
            "selected_api78_runner_count": cell["selected_api78_runner_count"],
            "selected_partial_run_count": cell["selected_partial_run_count"],
            "selected_archive_or_historical_count": cell["selected_archived_count"],
            "equipment_blank_or_null_count": cell["equipment_blank_or_null_count"],
            "equipment_nonblank_count": cell["equipment_nonblank_count"],
            "explicit_added_mark_count": cell["explicit_added_mark_count"],
            "explicit_removed_mark_count": cell["explicit_removed_mark_count"],
        })
    coverage_fields = [
        "year", "meet", "core_target_date_meet_count", "selected_complete_date_meet_count",
        "missing_complete_date_meet_count", "core_runner_count", "core_runner_count_with_selected_date_meet",
        "selected_api78_runner_count", "selected_partial_run_count", "selected_archive_or_historical_count",
        "equipment_blank_or_null_count", "equipment_nonblank_count",
        "explicit_added_mark_count", "explicit_removed_mark_count",
    ]
    write_csv(OUT / "api78_coverage_by_meet_year.csv", coverage, coverage_fields)

    target_date_set = target_date_meet_set
    queue_rows = []
    for queued in capture_queue_records():
        key = (queued["event_date"], queued["meet"])
        chosen = selected.get(key)
        queue_rows.append({
            **queued,
            "core_date_meet_target": key in target_date_set,
            "selected_complete_capture": bool(chosen),
            "selected_batch_id": chosen["batch"]["batch_id"] if chosen else "",
            "selected_source_kind": chosen["batch"]["source_kind"] if chosen else "",
            "selected_runner_count": len(chosen["items"]) if chosen else 0,
        })
    queue_fields = [
        "event_date", "meet", "record_complete", "record_error_present", "record_page_count",
        "record_total_count", "core_date_meet_target", "selected_complete_capture",
        "selected_batch_id", "selected_source_kind", "selected_runner_count",
    ]
    write_csv(OUT / "api78_capture_queue_status.csv", queue_rows, queue_fields)

    sqlite_con.rollback()
    sqlite_con.close()
    snapshot_meta["operational_db_sha256_after"] = sha256(OPERATIONAL)
    wal_after_path = Path(str(OPERATIONAL) + "-wal")
    snapshot_meta["operational_wal_sha256_after"] = sha256(wal_after_path) if wal_after_path.is_file() else ""
    snapshot_meta["core_db_sha256"] = core_hash
    snapshot_meta["historical_manifest_snapshot_at_kst"] = historical_manifest_snapshot_kst
    snapshot_meta["historical_capture_manifest_path"] = str((HISTORICAL_ROOT / "capture_manifest.json").relative_to(ROOT))
    snapshot_meta["historical_capture_manifest_sha256"] = historical_manifest_sha
    snapshot_meta["historical_capture_manifest_snapshot_path"] = str(manifest_snapshot_path.relative_to(ROOT))
    snapshot_meta["historical_capture_manifest_snapshot_sha256"] = manifest_snapshot_sha
    snapshot_meta["historical_targets_manifest_path"] = str((HISTORICAL_ROOT / "targets.json").relative_to(ROOT))
    snapshot_meta["historical_targets_manifest_sha256"] = historical_targets_sha
    snapshot_meta["historical_targets_manifest_snapshot_path"] = str(targets_snapshot_path.relative_to(ROOT))
    snapshot_meta["historical_targets_manifest_snapshot_sha256"] = targets_snapshot_sha
    snapshot_meta["scope"] = f"{START_DAY}..{END_DAY}; meets 1,3,4; API78 only"
    snapshot_meta["read_only"] = True
    snapshot_meta["network_used"] = False
    snapshot_meta["operational_query_only"] = True
    snapshot_meta["operational_read_transaction"] = True
    snapshot_meta["core_runner_count"] = len(core_rows)
    snapshot_meta["core_target_date_meet_count"] = len(target_date_meets)
    snapshot_meta["saved_in_scope_source_document_count"] = len(db_documents)
    snapshot_meta["saved_archive_document_count"] = len(archived_documents())
    snapshot_meta["saved_historical_raw_document_count"] = len(additional_historical_documents())
    snapshot_meta["historical_capture_queue_date_meet_count"] = len(capture_queue_records())
    snapshot_meta["historical_capture_queue_complete_manifest_count"] = sum(bool(row.get("record_complete")) for row in capture_queue_records())
    snapshot_meta["verified_document_count"] = sum(bool(row["file_hash_valid"] and row["payload_valid"]) for row in verified_documents)
    snapshot_meta["complete_batch_candidate_count"] = sum(bool(row["complete_payload"]) for row in batch_rows)
    snapshot_meta["selected_complete_date_meet_count"] = len(selected)
    snapshot_meta["missing_core_date_meet_count"] = len(missing_date_meets)
    snapshot_meta["selected_api78_runner_count"] = len(runner_rows)
    snapshot_meta["selected_unresolved_identity_runner_count"] = len(unresolved_ledger)
    snapshot_meta["selected_runner_link_status_counts"] = dict(Counter(row["link_status"] for row in runner_rows))
    snapshot_meta["selected_equipment_value_state_counts"] = dict(Counter(row["equipment_value_state"] for row in runner_rows))
    snapshot_meta["selected_explicit_added_mark_count"] = sum(row["change_type"] == "added" for row in mark_rows)
    snapshot_meta["selected_explicit_removed_mark_count"] = sum(row["change_type"] == "removed" for row in mark_rows)
    snapshot_meta["selected_core_runner_state_counts"] = dict(Counter(row["equipment_observation_state"] for row in core_ledger))
    snapshot_meta["core_years_without_any_core_date_meet"] = [year for year in map(str, range(2010, 2027)) if target_by_year[year] == 0]

    # Hash the frozen CSVs last and preserve a tiny output manifest for the loader.
    export_manifest = []
    for path in sorted(OUT.glob("api78_*.csv")):
        with path.open(encoding="utf-8", newline="") as stream:
            row_count = max(0, sum(1 for _ in csv.DictReader(stream)))
        export_manifest.append({
            "file_name": path.name,
            "row_count": row_count,
            "sha256": sha256(path),
        })
    with (OUT / "frozen_export_manifest.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["file_name", "row_count", "sha256"])
        writer.writeheader()
        writer.writerows(export_manifest)
    snapshot_meta["frozen_export_manifest_path"] = str((OUT / "frozen_export_manifest.csv").relative_to(ROOT))
    snapshot_meta["frozen_export_manifest_sha256"] = sha256(OUT / "frozen_export_manifest.csv")
    snapshot_meta["frozen_export_manifest_csv_count"] = len(export_manifest)
    review_evidence_manifest = [{
        "file_name": absence_path.name,
        "row_count": len(absence_evidence),
        "sha256": sha256(absence_path),
    }]
    review_manifest_path = OUT / "review_evidence_manifest.csv"
    write_csv(review_manifest_path, review_evidence_manifest, ["file_name", "row_count", "sha256"])
    snapshot_meta["review_evidence_manifest_path"] = str(review_manifest_path.relative_to(ROOT))
    snapshot_meta["review_evidence_manifest_sha256"] = sha256(review_manifest_path)
    snapshot_meta["review_evidence_manifest_csv_count"] = len(review_evidence_manifest)
    (OUT / "snapshot_summary.json").write_text(json.dumps(snapshot_meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
