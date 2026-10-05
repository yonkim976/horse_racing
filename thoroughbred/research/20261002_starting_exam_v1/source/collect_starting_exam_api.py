"""Capture official KRA API21_1 starting-exam pages and build a research input.

This collector writes immutable raw captures and a hash-pinned Parquet export.
It never writes to the core or operating databases.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import time
from datetime import date, datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, quote
from urllib.request import Request, urlopen
import uuid

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from horse_racing.config import get_settings


REPO_ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parents[1]
RAW = OUT / "raw"
CAPTURES = RAW / "captures"
INPUT = OUT / "input"
CORE_DB = REPO_ROOT / "thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb"
ENDPOINT = "https://apis.data.go.kr/B551015/API21_1/startingTestResult_1"
PORTAL = "https://www.data.go.kr/data/15057405/openapi.do"
API_FIELDS = [
    "meet", "trainDate", "daySerial", "trainNo", "chulNo", "hrName", "hrNo",
    "name", "sex", "age", "rider", "trName", "trNo", "owName", "owNo",
    "passFlag", "reason", "nopassReason",
]
YEARS = range(2010, 2027)
MEETS = ("1", "3")
RAW_MEET_LABELS_BY_QUERY = {"1": {"서울"}, "3": {"부산경남", "부경", "영남"}}
START_DATE = date(2010, 1, 1)
END_DATE = date(2026, 9, 29)
PAGE_SIZE = 10_000
MIN_REQUEST_GAP_SECONDS = 1.0
SUCCESS_CODES = {"00", "0000"}
PARQUET_COLUMNS = [
    "dataset", "observation_id", "event_date", "meet", "official_horse_id",
    "raw_name", "raw_path", "raw_sha256", "source_page_no", "source_row_no",
    "source_captured_at", "capture_basis", "endpoint", "raw_payload_json",
    "typed_fields_json", "link_status", "linked_core_horse_id", "qa_flags_json",
    "capture_id",
]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds")


def utc_naive_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(tzinfo=None).isoformat(timespec="microseconds")


def parse_api_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def json_bytes(value: Any, *, pretty: bool = True) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2 if pretty else None,
                       separators=None if pretty else (",", ":")) + "\n").encode("utf-8")


def write_new(path: Path, body: bytes) -> None:
    """Create a new immutable file and fail rather than replacing any prior capture."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())


def parse_response(payload: Any) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    wrapped = payload.get("response", payload) if isinstance(payload, dict) else {}
    header = wrapped.get("header", {}) if isinstance(wrapped, dict) else {}
    body = wrapped.get("body", {}) if isinstance(wrapped, dict) else {}
    items_obj = body.get("items", {}) if isinstance(body, dict) else {}
    item_value = items_obj.get("item") if isinstance(items_obj, dict) else None
    if item_value is None:
        rows: list[dict[str, Any]] = []
    elif isinstance(item_value, dict):
        rows = [item_value]
    elif isinstance(item_value, list) and all(isinstance(row, dict) for row in item_value):
        rows = item_value
    else:
        raise ValueError("unexpected API item container")
    return header, body, rows


def roster_ids() -> set[str]:
    """Read the pinned research core roster through a DuckDB read-only connection."""
    if not CORE_DB.is_file():
        raise RuntimeError("research core database is unavailable")
    connection = duckdb.connect(str(CORE_DB), read_only=True)
    try:
        return {
            str(row[0]) for row in connection.execute(
                "SELECT DISTINCT entity_id_official_string FROM entity_reference_roster "
                "WHERE entity_type='horse' AND entity_id_official_string IS NOT NULL"
            ).fetchall()
        }
    finally:
        connection.close()


def sanitized_request(meet: str, year: int, page_no: int) -> dict[str, Any]:
    return {
        "meet": meet,
        "tr_year": str(year),
        "_type": "json",
        "pageNo": page_no,
        "numOfRows": PAGE_SIZE,
    }


def capture_page(meet: str, year: int, page_no: int, secret: str,
                 last_request_finished: float | None) -> tuple[dict[str, Any], bytes | None, float]:
    if last_request_finished is not None:
        pause = MIN_REQUEST_GAP_SECONDS - (time.monotonic() - last_request_finished)
        if pause > 0:
            time.sleep(pause)
    requested_at = utc_now()
    public_params = sanitized_request(meet, year, page_no)
    request_params = {**public_params, "ServiceKey": secret}
    request = Request(
        ENDPOINT + "?" + urlencode(request_params),
        headers={"User-Agent": "horse_racing_thoroughbred_research/1.0", "Accept": "application/json"},
    )
    status_code: int | None = None
    content_type: str | None = None
    body = b""
    failure_class: str | None = None
    try:
        with urlopen(request, timeout=60) as response:
            status_code = response.status
            content_type = response.headers.get("Content-Type")
            body = response.read()
    except HTTPError as error:
        status_code = error.code
        content_type = error.headers.get("Content-Type")
        body = error.read()
        failure_class = "http_error"
    except (URLError, TimeoutError, OSError) as error:
        # Do not format exception text: urllib messages can include credentialed URLs.
        failure_class = type(error).__name__
    retrieved_at = utc_now()
    finished = time.monotonic()
    record = {
        "requested_at_utc": utc_text(requested_at),
        "retrieved_at_utc": utc_text(retrieved_at),
        "status_code": status_code,
        "content_type": content_type,
        "response_bytes": len(body),
        "response_sha256": sha256_bytes(body) if body else None,
        "request_parameters_without_authentication": public_params,
        "failure_class": failure_class,
    }
    if secret.encode("utf-8") in body or quote(secret, safe="").encode("utf-8") in body:
        record["failure_class"] = "credential_echo_refused"
        record["credential_echo_refused"] = True
        return record, None, finished
    return record, body, finished


def safe_sample(rows: list[dict[str, Any]], first_body: dict[str, Any], header: dict[str, Any]) -> dict[str, Any]:
    safe_fields = ("meet", "trainDate", "daySerial", "trainNo", "chulNo", "sex", "age", "passFlag")
    first = rows[0] if rows else {}
    return {
        "event": "first_api_sample",
        "field_keys": list(first.keys()) if first else API_FIELDS,
        "safe_example_values": {key: first[key] for key in safe_fields if key in first},
        "result_code": header.get("resultCode"),
        "requested_page_size": PAGE_SIZE,
        "response_page_size": first_body.get("numOfRows"),
        "page_no": first_body.get("pageNo"),
        "total_count": first_body.get("totalCount"),
        "page_row_count": len(rows),
    }


def load_cached_manifest() -> dict[str, Any] | None:
    path = RAW / "capture_manifest.json"
    if not path.exists():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("dataset") != "starting_exam" or value.get("endpoint") != "API21_1":
        raise RuntimeError("existing capture manifest has a different dataset contract")
    for source in [*value.get("source_files", []), *value.get("failure_files", [])]:
        if not source.get("raw_path"):
            continue
        path = REPO_ROOT / source["raw_path"]
        if not path.is_file() or sha256_file(path) != source.get("raw_sha256"):
            raise RuntimeError("cached raw page failed its recorded SHA-256 check")
    return value


def collect(capture_id: str, secret: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], bool]:
    source_files: list[dict[str, Any]] = []
    request_attempts: list[dict[str, Any]] = []
    coverage: list[dict[str, Any]] = []
    page_rows: list[dict[str, Any]] = []
    last_finished: float | None = None
    sample_sent = False
    auth_echo_detected = False
    capture_root = CAPTURES / capture_id

    for year in YEARS:
        for meet in MEETS:
            partition_dir = capture_root / f"meet_{meet}" / f"year_{year}"
            partition_started = utc_now()
            partition_sources: list[dict[str, Any]] = []
            observed_rows = 0
            total_count: int | None = None
            effective_page_size: int | None = None
            result_status = "fail"
            failure_class: str | None = None
            page_no = 1
            year_mismatch_rows = 0
            invalid_train_date_rows = 0
            raw_meet_query_mismatch_rows = 0
            raw_meet_labels: dict[str, int] = {}

            while True:
                response_record, body_bytes, last_finished = capture_page(meet, year, page_no, secret, last_finished)
                request_attempts.append({"capture_id": capture_id, "meet": meet, "year": year,
                                         "source_page_no": page_no, **response_record})
                if body_bytes is None:
                    failure_class = str(response_record.get("failure_class") or "transport_error")
                    auth_echo_detected = failure_class == "credential_echo_refused"
                    break

                if response_record.get("status_code") != 200:
                    raw_path = partition_dir / f"page_{page_no:04d}_http_error.bin"
                    write_new(raw_path, body_bytes)
                    source_files.append({
                        "capture_id": capture_id, "meet": meet, "year": year,
                        "source_page_no": page_no, "requested_at_utc": response_record["requested_at_utc"],
                        "retrieved_at_utc": response_record["retrieved_at_utc"],
                        "status_code": response_record.get("status_code"), "failure_class": "http_error",
                        "raw_path": raw_path.relative_to(REPO_ROOT).as_posix(),
                        "raw_sha256": sha256_bytes(body_bytes), "response_bytes": len(body_bytes),
                        "source_row_count": 0, "page_total_count": total_count,
                        "page_item_count": None, "page_size": PAGE_SIZE,
                        "request_parameters_without_authentication": response_record["request_parameters_without_authentication"],
                    })
                    failure_class = "http_error"
                    break

                try:
                    payload = json.loads(body_bytes)
                    header, body, rows = parse_response(payload)
                    result_code = str(header.get("resultCode") or "")
                except (json.JSONDecodeError, TypeError, ValueError):
                    result_code, body, rows, header = "", {}, [], {}
                if result_code not in SUCCESS_CODES:
                    raw_path = partition_dir / f"page_{page_no:04d}_api_error.json"
                    write_new(raw_path, body_bytes)
                    source_files.append({
                        "capture_id": capture_id, "meet": meet, "year": year,
                        "source_page_no": page_no, "requested_at_utc": response_record["requested_at_utc"],
                        "retrieved_at_utc": response_record["retrieved_at_utc"],
                        "status_code": 200, "failure_class": "api_error_or_invalid_response",
                        "result_code": result_code or None,
                        "raw_path": raw_path.relative_to(REPO_ROOT).as_posix(),
                        "raw_sha256": sha256_bytes(body_bytes), "response_bytes": len(body_bytes),
                        "source_row_count": 0, "page_total_count": None,
                        "page_item_count": None, "page_size": PAGE_SIZE,
                        "request_parameters_without_authentication": response_record["request_parameters_without_authentication"],
                    })
                    failure_class = "api_error_or_invalid_response"
                    break

                try:
                    page_total = int(body.get("totalCount"))
                    response_page_no = int(body.get("pageNo"))
                    reported_page_size = int(body.get("numOfRows") or PAGE_SIZE)
                    if page_total < 0 or response_page_no != page_no or reported_page_size <= 0:
                        raise ValueError
                except (TypeError, ValueError):
                    raw_path = partition_dir / f"page_{page_no:04d}_invalid_meta.json"
                    write_new(raw_path, body_bytes)
                    source_files.append({
                        "capture_id": capture_id, "meet": meet, "year": year,
                        "source_page_no": page_no, "requested_at_utc": response_record["requested_at_utc"],
                        "retrieved_at_utc": response_record["retrieved_at_utc"],
                        "status_code": 200, "failure_class": "invalid_page_metadata",
                        "raw_path": raw_path.relative_to(REPO_ROOT).as_posix(),
                        "raw_sha256": sha256_bytes(body_bytes), "response_bytes": len(body_bytes),
                        "source_row_count": len(rows), "page_total_count": None,
                        "page_item_count": reported_page_size if "reported_page_size" in locals() else None,
                        "page_size": PAGE_SIZE,
                        "request_parameters_without_authentication": response_record["request_parameters_without_authentication"],
                    })
                    failure_class = "invalid_page_metadata"
                    break

                if total_count is None:
                    total_count = page_total
                    effective_page_size = min(reported_page_size, PAGE_SIZE)
                if page_total != total_count or reported_page_size != effective_page_size or len(rows) > effective_page_size:
                    failure_class = "inconsistent_page_metadata"
                raw_path = partition_dir / f"page_{page_no:04d}.json"
                write_new(raw_path, body_bytes)
                digest = sha256_bytes(body_bytes)
                retrieved = datetime.fromisoformat(response_record["retrieved_at_utc"])
                page_record = {
                    "capture_id": capture_id,
                    "dataset": "starting_exam",
                    "meet": meet,
                    "year": year,
                    "source_page_no": page_no,
                    "page_no": response_page_no,
                    "requested_at_utc": response_record["requested_at_utc"],
                    "retrieved_at_utc": response_record["retrieved_at_utc"],
                    "source_captured_at_utc": response_record["retrieved_at_utc"],
                    "status_code": 200,
                    "result_code": result_code,
                    "content_type": response_record.get("content_type"),
                    "request_parameters_without_authentication": response_record["request_parameters_without_authentication"],
                    "raw_path": raw_path.relative_to(REPO_ROOT).as_posix(),
                    "raw_sha256": digest,
                    "response_bytes": len(body_bytes),
                    "source_row_count": len(rows),
                    "page_total_count": page_total,
                    "page_item_count": len(rows),
                    "api_num_of_rows": reported_page_size,
                    "page_size": effective_page_size,
                }
                partition_sources.append(page_record)
                source_files.append(page_record)
                for row_no, row in enumerate(rows, start=1):
                    row_date = parse_api_date(row.get("trainDate"))
                    if row_date is None:
                        invalid_train_date_rows += 1
                    elif row_date.year != year:
                        year_mismatch_rows += 1
                    label = row.get("meet")
                    if label is not None:
                        label_text = str(label)
                        raw_meet_labels[label_text] = raw_meet_labels.get(label_text, 0) + 1
                    else:
                        label_text = ""
                    if label_text not in RAW_MEET_LABELS_BY_QUERY[meet]:
                        raw_meet_query_mismatch_rows += 1
                    page_rows.append({
                        "meet": meet, "year": year, "capture_id": capture_id,
                        "page_no": page_no, "row_no": row_no, "raw": row,
                        "raw_path": page_record["raw_path"], "raw_sha256": digest,
                        "source_captured_at": retrieved.replace(tzinfo=None),
                        "captured_at_utc": response_record["retrieved_at_utc"],
                    })
                observed_rows += len(rows)

                if not sample_sent:
                    sample = safe_sample(rows, body, header)
                    sample["meet_query"] = meet
                    sample["year_query"] = year
                    print(json.dumps(sample, ensure_ascii=False), flush=True)
                    sample_sent = True

                if total_count == 0:
                    if rows:
                        failure_class = "zero_count_with_rows"
                    break
                if failure_class:
                    break
                expected_pages = math.ceil(total_count / effective_page_size)
                if page_no >= expected_pages:
                    if observed_rows != total_count:
                        failure_class = "incomplete_row_count"
                    break
                page_no += 1

            if failure_class is None and invalid_train_date_rows:
                failure_class = "invalid_trainDate"
            if failure_class is None and year_mismatch_rows:
                failure_class = "trainDate_year_mismatch"
            if failure_class is None and raw_meet_query_mismatch_rows:
                failure_class = "raw_meet_query_mismatch"
            if failure_class is None:
                if total_count == 0 and observed_rows == 0:
                    result_status = "zero"
                elif total_count is not None and observed_rows == total_count:
                    result_status = "complete"
                else:
                    failure_class = "incomplete_capture"
            partition = {
                "dataset": "starting_exam", "endpoint": "API21_1", "meet": meet, "year": year,
                "capture_id": capture_id, "status": result_status, "failure_class": failure_class,
                "started_at_utc": utc_text(partition_started), "finished_at_utc": utc_text(utc_now()),
                "total_count": total_count, "observed_row_count": observed_rows,
                "trainDate_year_mismatch_row_count": year_mismatch_rows,
                "invalid_trainDate_row_count": invalid_train_date_rows,
                "raw_meet_label_counts": raw_meet_labels,
                "raw_meet_query_mismatch_row_count": raw_meet_query_mismatch_rows,
                "page_size": effective_page_size, "page_count": len(partition_sources),
                "source_files": [item["raw_path"] for item in partition_sources],
            }
            write_new(partition_dir / "partition_manifest.json", json_bytes(partition))
            coverage.append(partition)
            print(json.dumps({
                "event": "partition_complete", "meet": meet, "year": year,
                "status": result_status, "failure_class": failure_class,
                "total_count": total_count, "observed_row_count": observed_rows,
                "page_count": len(partition_sources),
            }, ensure_ascii=False), flush=True)
            if auth_echo_detected:
                # A response containing a credential cannot safely be archived. Stop all requests.
                break
        if auth_echo_detected:
            break
    coverage_by_key = {(item["meet"], item["year"]): item for item in coverage}
    for source in source_files:
        partition = coverage_by_key.get((source.get("meet"), source.get("year")), {})
        source["is_selected"] = (partition.get("status") in {"complete", "zero"}
                                 and source.get("status_code") == 200
                                 and source.get("result_code") in SUCCESS_CODES)
        source["endpoint"] = "API21_1"
        source.setdefault("capture_basis", "API21_1 source response page")
        source.setdefault("row_count", source.get("source_row_count", 0))
        source.setdefault("source_row_count", source.get("row_count", 0))
        source.setdefault("page_item_count", source.get("row_count", 0))
        source.setdefault("source_captured_at_utc", source.get("retrieved_at_utc"))
        source.setdefault("hash_check_status", "verified_at_capture")
    source_files = [source for source in source_files if source.get("raw_path") and source.get("raw_sha256")]
    return page_rows, source_files, request_attempts, coverage, sample_sent


def observation_rows(page_rows: list[dict[str, Any]], core_ids: set[str]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    output: list[dict[str, Any]] = []
    cutoff_counts = {"raw_rows": len(page_rows), "included_rows": 0, "outside_scope_rows": 0,
                     "invalid_or_missing_date_rows": 0, "missing_official_id_rows": 0,
                     "unmatched_official_id_rows": 0, "exact_core_roster_match_rows": 0,
                     "nonstandard_official_id_value_count": 0}
    id_anomalies: set[str] = set()
    natural_key_index: dict[tuple[str, ...], list[int]] = {}
    for occurrence in page_rows:
        raw = occurrence["raw"]
        source_date = raw.get("trainDate")
        try:
            event_date = date.fromisoformat(str(source_date))
        except (TypeError, ValueError):
            cutoff_counts["invalid_or_missing_date_rows"] += 1
            continue
        if not START_DATE <= event_date <= END_DATE:
            cutoff_counts["outside_scope_rows"] += 1
            continue
        raw_id = raw.get("hrNo")
        normalized_id: str | None
        if raw_id is None or raw_id == "" or raw_id == "-":
            normalized_id = None
            link_status = "missing_official_id"
            cutoff_counts["missing_official_id_rows"] += 1
        else:
            normalized_id = raw_id if isinstance(raw_id, str) else json.dumps(raw_id, ensure_ascii=False)
            if normalized_id in core_ids:
                link_status = "exact_core_roster_match"
                cutoff_counts["exact_core_roster_match_rows"] += 1
            else:
                link_status = "unmatched_official_id"
                cutoff_counts["unmatched_official_id_rows"] += 1
            if isinstance(raw_id, str) and raw_id.strip() and raw_id not in {"-"} and raw_id != raw_id.strip():
                id_anomalies.add(raw_id)
            if normalized_id in {"0", "00", "000000", "0000000", "N/A", "NA"}:
                id_anomalies.add(normalized_id)

        payload_json = json.dumps(raw, ensure_ascii=False, separators=(",", ":"))
        payload_digest = sha256_bytes(payload_json.encode("utf-8"))
        occurrence_id = ":".join(("API21_1", occurrence["capture_id"], occurrence["meet"], str(occurrence["year"]),
                                   str(occurrence["page_no"]), str(occurrence["row_no"])))
        flags: list[str] = []
        natural_values = [source_date, occurrence["meet"], raw.get("daySerial"), raw.get("trainNo"),
                          raw.get("chulNo"), raw.get("hrNo")]
        if all(value not in (None, "", "-") for value in natural_values):
            natural_key = tuple(str(value) for value in natural_values)
            natural_key_index.setdefault(natural_key, []).append(len(output))
        else:
            flags.append("natural_key_has_missing_component")
        raw_name = raw.get("hrName")
        if not isinstance(raw_name, str):
            raw_name = None
        output.append({
            "dataset": "starting_exam",
            "observation_id": occurrence_id,
            "event_date": event_date,
            "meet": occurrence["meet"],
            "official_horse_id": normalized_id,
            "raw_name": raw_name,
            "raw_path": occurrence["raw_path"],
            "raw_sha256": occurrence["raw_sha256"],
            "source_page_no": occurrence["page_no"],
            "source_row_no": occurrence["row_no"],
            "source_captured_at": occurrence["source_captured_at"],
            "capture_basis": "API21_1 response retrieved time; historical publication time unverified",
            "endpoint": "API21_1",
            "raw_payload_json": payload_json,
            "typed_fields_json": payload_json,
            "link_status": link_status,
            "linked_core_horse_id": normalized_id if link_status == "exact_core_roster_match" else None,
            "qa_flags_json": flags,
            "capture_id": occurrence["capture_id"],
            "_payload_sha256": payload_digest,
        })
        cutoff_counts["included_rows"] += 1

    for indices in natural_key_index.values():
        if len(indices) < 2:
            continue
        signatures = {output[index]["_payload_sha256"] for index in indices}
        flag = "exact_natural_key_payload_repeat" if len(signatures) == 1 else "natural_key_payload_variant"
        for index in indices:
            output[index]["qa_flags_json"].append(flag)
    for row in output:
        row.pop("_payload_sha256", None)
        row["qa_flags_json"] = json.dumps(row["qa_flags_json"], ensure_ascii=False, separators=(",", ":"))
    cutoff_counts["nonstandard_official_id_value_count"] = len(id_anomalies)
    cutoff_counts["nonstandard_official_id_examples"] = sorted(id_anomalies)[:20]
    return output, cutoff_counts


def parquet_schema() -> pa.Schema:
    return pa.schema([
        ("dataset", pa.string()), ("observation_id", pa.string()), ("event_date", pa.date32()),
        ("meet", pa.string()), ("official_horse_id", pa.string()), ("raw_name", pa.string()),
        ("raw_path", pa.string()), ("raw_sha256", pa.string()), ("source_page_no", pa.int32()),
        ("source_row_no", pa.int32()), ("source_captured_at", pa.timestamp("us")),
        ("capture_basis", pa.string()), ("endpoint", pa.string()),
        ("raw_payload_json", pa.string()), ("typed_fields_json", pa.string()),
        ("link_status", pa.string()), ("linked_core_horse_id", pa.string()),
        ("qa_flags_json", pa.string()), ("capture_id", pa.string()),
    ])


def write_parquet_immutable(rows: list[dict[str, Any]], path: Path) -> str:
    if path.exists():
        raise RuntimeError("Parquet output already exists; cached output must be verified and reused")
    path.parent.mkdir(parents=True, exist_ok=True)
    schema = parquet_schema()
    arrays = [pa.array([row[name] for row in rows], type=schema.field(name).type) for name in PARQUET_COLUMNS]
    table = pa.Table.from_arrays(arrays, schema=schema)
    fd, temp_name = tempfile.mkstemp(prefix=".starting-exam.", suffix=".parquet", dir=path.parent)
    os.close(fd)
    temporary = Path(temp_name)
    try:
        pq.write_table(table, temporary, compression="zstd")
        digest = sha256_file(temporary)
        os.link(temporary, path)
        return digest
    finally:
        temporary.unlink(missing_ok=True)


def validate_cached_export(manifest: dict[str, Any]) -> None:
    path = REPO_ROOT / manifest["parquet_path"]
    if not path.is_file() or sha256_file(path) != manifest.get("parquet_sha256"):
        raise RuntimeError("cached starting-exam Parquet failed its recorded SHA-256 check")
    connection = duckdb.connect(":memory:")
    try:
        rows = connection.execute("SELECT count(*) FROM read_parquet(?)", [str(path)]).fetchone()[0]
        if rows != manifest.get("row_count"):
            raise RuntimeError("cached Parquet row count differs from capture manifest")
        schema = [(col[0], str(col[1]).upper()) for col in connection.execute(
            "DESCRIBE SELECT * FROM read_parquet(?)", [str(path)]).fetchall()]
        expected = [
            ("dataset", "VARCHAR"), ("observation_id", "VARCHAR"), ("event_date", "DATE"),
            ("meet", "VARCHAR"), ("official_horse_id", "VARCHAR"), ("raw_name", "VARCHAR"),
            ("raw_path", "VARCHAR"), ("raw_sha256", "VARCHAR"), ("source_page_no", "INTEGER"),
            ("source_row_no", "INTEGER"), ("source_captured_at", "TIMESTAMP"),
            ("capture_basis", "VARCHAR"), ("endpoint", "VARCHAR"), ("raw_payload_json", "VARCHAR"),
            ("typed_fields_json", "VARCHAR"), ("link_status", "VARCHAR"),
            ("linked_core_horse_id", "VARCHAR"), ("qa_flags_json", "VARCHAR"), ("capture_id", "VARCHAR"),
        ]
        if schema != expected:
            raise RuntimeError("cached Parquet schema differs from the agreed input contract")
    finally:
        connection.close()
    validate_cached_capture_pages(manifest)


def validate_cached_capture_pages(manifest: dict[str, Any]) -> None:
    """Verify each selected raw response against its requested meet/year partition."""
    for source in manifest.get("source_files", []):
        if not source.get("is_selected"):
            continue
        meet = str(source.get("meet"))
        year = int(source.get("year"))
        path = REPO_ROOT / str(source.get("raw_path"))
        body_bytes = path.read_bytes()
        if sha256_bytes(body_bytes) != source.get("raw_sha256"):
            raise RuntimeError("selected raw API page failed its recorded SHA-256 check")
        try:
            header, body, rows = parse_response(json.loads(body_bytes))
        except (json.JSONDecodeError, TypeError, ValueError) as error:
            raise RuntimeError("selected raw API page is not a valid response") from error
        if str(header.get("resultCode") or "") not in SUCCESS_CODES:
            raise RuntimeError("selected raw API page does not have a success result code")
        if len(rows) != int(source.get("source_row_count", -1)):
            raise RuntimeError("selected raw API page row count differs from its capture ledger")
        if int(body.get("pageNo", -1)) != int(source.get("source_page_no", -2)):
            raise RuntimeError("selected raw API page number differs from its capture ledger")
        for row in rows:
            row_date = parse_api_date(row.get("trainDate"))
            if row_date is None or row_date.year != year:
                raise RuntimeError("selected raw API page has an invalid or wrong-year trainDate")
            if str(row.get("meet") or "") not in RAW_MEET_LABELS_BY_QUERY.get(meet, set()):
                raise RuntimeError("selected raw API page meet label does not match its query meet")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)
    CAPTURES.mkdir(parents=True, exist_ok=True)
    INPUT.mkdir(parents=True, exist_ok=True)
    cached = load_cached_manifest()
    if cached is not None:
        validate_cached_export(cached)
        print(json.dumps({"event": "verified_cached_capture", "row_count": cached["row_count"],
                          "parquet_sha256": cached["parquet_sha256"], "network_requests": 0}))
        return

    setting = get_settings().data_go_kr_service_key
    if setting is None:
        raise SystemExit("KRA service key unavailable; no request was made")
    secret = setting.get_secret_value()
    capture_id = utc_now().strftime("%Y%m%dT%H%M%S.%fZ") + "-" + uuid.uuid4().hex[:8]
    core_ids = roster_ids()
    page_rows, source_files, request_attempts, coverage, sample_sent = collect(capture_id, secret)
    if len(coverage) != len(YEARS) * len(MEETS):
        # Credential echo refusal stops collection and is explicitly recorded as a partial capture.
        coverage.extend([
            {"dataset": "starting_exam", "endpoint": "API21_1", "meet": meet, "year": year,
             "capture_id": capture_id, "status": "fail", "failure_class": "not_requested_after_credential_echo_refusal",
             "total_count": None, "observed_row_count": 0, "page_size": None, "page_count": 0}
            for year in YEARS for meet in MEETS
            if not any(row.get("year") == year and row.get("meet") == meet for row in coverage)
        ])
    complete_partitions = {(item["meet"], item["year"]) for item in coverage
                           if item["status"] in {"complete", "zero"}}
    export_rows = [item for item in page_rows if (item["meet"], item["year"]) in complete_partitions]
    rows, scoped_counts = observation_rows(export_rows, core_ids)
    scoped_counts["captured_rows_all_partitions"] = len(page_rows)
    scoped_counts["excluded_incomplete_partition_rows"] = len(page_rows) - len(export_rows)
    parquet_path = INPUT / "starting_exam.parquet"
    parquet_hash = write_parquet_immutable(rows, parquet_path)
    coverage_payload = {
        "schema_version": "starting_exam_coverage_v1",
        "dataset": "starting_exam",
        "endpoint": "API21_1",
        "scope_start_date_inclusive": START_DATE.isoformat(),
        "scope_end_date_inclusive": END_DATE.isoformat(),
        "meet_scope": list(MEETS),
        "partition_count_expected": len(YEARS) * len(MEETS),
        "partition_count_observed": len(coverage),
        "partition_status_counts": {status: sum(row["status"] == status for row in coverage)
                                     for status in ("complete", "zero", "fail")},
        "partitions": coverage,
        "scoped_row_counts": scoped_counts,
        "judgment_policy": "Raw passFlag/reason/nopassReason values are preserved; no pass/fail adjudication is inferred.",
        "venue_policy": "meet 3 remains the API's combined Yeongnam region; physical venue is not inferred.",
    }
    coverage_path = RAW / "coverage_summary.json"
    write_new(coverage_path, json_bytes(coverage_payload))
    source_manifest = {
        "schema_version": "starting_exam_capture_v1",
        "dataset": "starting_exam",
        "endpoint": "API21_1",
        "source": "KRA OpenAPI 15057405 starting exam result",
        "portal_metadata_url": PORTAL,
        "endpoint_host": "apis.data.go.kr",
        "endpoint_path": "/B551015/API21_1/startingTestResult_1",
        "capture_id": capture_id,
        "capture_started_at_utc": coverage[0].get("started_at_utc"),
        "capture_finished_at_utc": utc_text(utc_now()),
        "scope": {"start_date_inclusive": START_DATE.isoformat(), "end_date_inclusive": END_DATE.isoformat(),
                  "meets": list(MEETS), "year_query_range": [min(YEARS), max(YEARS)]},
        "raw_api_partition_scope": "Each source page is retained intact, including any 2026 rows after the export cutoff.",
        "source_time_basis": "retrieved_at_utc is the local capture time; historical API publication time is unverified.",
        "request_rate_seconds_minimum": MIN_REQUEST_GAP_SECONDS,
        "requested_page_size": PAGE_SIZE,
        "api_item_fields_from_official_swagger": API_FIELDS,
        "source_files": source_files,
        "request_attempts": request_attempts,
        "coverage_summary_path": coverage_path.relative_to(REPO_ROOT).as_posix(),
        "row_count": len(rows),
        "scoped_row_counts": scoped_counts,
        "parquet_path": parquet_path.relative_to(REPO_ROOT).as_posix(),
        "parquet_sha256": parquet_hash,
        "database_write_performed": False,
        "identity_rule": "Exact official hrNo string equality to entity_reference_roster.entity_type='horse'; no name-based matching.",
        "placeholder_policy": "Null, empty, and '-' hrNo become missing_official_id; raw JSON is unchanged.",
        "natural_key_policy": "date, requested meet code, daySerial, trainNo, chulNo, hrNo; repeats and variants stay as separate occurrences and receive QA flags.",
        "field_semantics_policy": "No distance is inferred; rider text is not converted to an official jockey ID; judgment values remain raw.",
    }
    manifest_path = RAW / "capture_manifest.json"
    write_new(manifest_path, json_bytes(source_manifest))
    validate_cached_export(source_manifest)
    print(json.dumps({"event": "collection_complete", "capture_id": capture_id,
                      "row_count": len(rows), "parquet_sha256": parquet_hash,
                      "coverage_status_counts": coverage_payload["partition_status_counts"],
                      "manifest_path": manifest_path.relative_to(REPO_ROOT).as_posix()}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
