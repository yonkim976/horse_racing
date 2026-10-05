#!/usr/bin/env python3
"""Capture complete read-only KRA API215 and API180_1 yearly partitions.

Exact successful response bytes are retained under ``source/raw``. The collector
never accesses a database or service and never prints or persists the API key.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import sys
import tempfile
import time
import uuid
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, quote_plus

import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT / "thoroughbred/research/20261002_steward_reports_v1"
OUTPUT = PACKAGE / "source"
BASE_URL = "https://apis.data.go.kr/B551015"
PAGE_SIZE = 1000
MIN_INTERVAL_SECONDS = 0.5
START_DATE = date(2010, 1, 1)
CUTOFF_DATE = date(2026, 9, 29)
DATASETS = {
    "api215_judge_report": {
        "endpoint": "/API215/JudgeReport",
        "operation": "JudgeReport",
        "service_key_parameter": "serviceKey",
        "record_type": "race_steward_narrative",
    },
    "api180_1_sanction_history": {
        "endpoint": "/API180_1/sanctionHistory_1",
        "operation": "sanctionHistory_1",
        "service_key_parameter": "serviceKey",
        "record_type": "sanction_history_entry",
    },
}
MEET_LABELS = {1: "서울", 3: "부산/부경", 4: "영천"}
MEET_TEXT_CODES = {
    "1": 1, "서울": 1,
    "3": 3, "부산": 3, "부경": 3, "부산경남": 3,
    "4": 4, "영천": 4,
}
TEXT_FIELDS = (
    "judgement", "addJudgement", "jkChange", "member", "weather",
    "gubun", "prNo", "prName", "kind", "reason", "spDate", "stDate", "etlTime",
)

OBSERVATION_SCHEMA = pa.schema([
    pa.field("capture_id", pa.string(), nullable=False),
    pa.field("dataset", pa.string(), nullable=False),
    pa.field("record_type", pa.string(), nullable=False),
    pa.field("requested_year", pa.int16(), nullable=False),
    pa.field("requested_meet", pa.int8(), nullable=False),
    pa.field("actual_meet_code", pa.int8()),
    pa.field("meet", pa.string()),
    pa.field("rcDate", pa.int64()),
    pa.field("race_date_iso", pa.string()),
    pa.field("rcNo", pa.int16()),
    pa.field("race_key", pa.string()),
    pa.field("judgement", pa.string()),
    pa.field("addJudgement", pa.string()),
    pa.field("jkChange", pa.string()),
    pa.field("member", pa.string()),
    pa.field("weather", pa.string()),
    pa.field("gubun", pa.string()),
    pa.field("prNo", pa.string()),
    pa.field("prName", pa.string()),
    pa.field("subject_class", pa.string()),
    pa.field("subject_id", pa.string()),
    pa.field("horse_id", pa.string()),
    pa.field("jockey_id", pa.string()),
    pa.field("chulNo", pa.int16()),
    pa.field("kind", pa.string()),
    pa.field("fine", pa.string()),
    pa.field("reason", pa.string()),
    pa.field("spDate", pa.string()),
    pa.field("stDate", pa.string()),
    pa.field("etlTime", pa.string()),
    pa.field("has_structured_horse_locator", pa.bool_(), nullable=False),
    pa.field("raw_item_json", pa.string(), nullable=False),
    pa.field("source_fields_present_json", pa.string(), nullable=False),
    pa.field("source_field_types_json", pa.string(), nullable=False),
    pa.field("source_row_sha256", pa.string(), nullable=False),
    pa.field("row_scope_status", pa.string(), nullable=False),
    pa.field("exclusion_reasons_json", pa.string()),
    pa.field("source_path", pa.string(), nullable=False),
    pa.field("page_sha256", pa.string(), nullable=False),
    pa.field("source_captured_at_utc", pa.string(), nullable=False),
    pa.field("source_captured_at_ms", pa.int64(), nullable=False),
    pa.field("requested_at_utc", pa.string(), nullable=False),
    pa.field("requested_at_ms", pa.int64(), nullable=False),
    pa.field("page_no", pa.int32(), nullable=False),
    pa.field("row_no", pa.int32(), nullable=False),
    pa.field("source_location", pa.string(), nullable=False),
])

PAGE_SCHEMA = pa.schema([
    pa.field("capture_id", pa.string(), nullable=False),
    pa.field("dataset", pa.string(), nullable=False),
    pa.field("requested_year", pa.int16(), nullable=False),
    pa.field("requested_meet", pa.int8(), nullable=False),
    pa.field("endpoint", pa.string(), nullable=False),
    pa.field("operation", pa.string(), nullable=False),
    pa.field("source_url_redacted", pa.string(), nullable=False),
    pa.field("request_public_params_json", pa.string(), nullable=False),
    pa.field("requested_at_ms", pa.int64(), nullable=False),
    pa.field("requested_at_utc", pa.string(), nullable=False),
    pa.field("retrieved_at_ms", pa.int64(), nullable=False),
    pa.field("retrieved_at_utc", pa.string(), nullable=False),
    pa.field("http_status", pa.int16(), nullable=False),
    pa.field("content_type", pa.string()),
    pa.field("result_code", pa.string(), nullable=False),
    pa.field("result_message", pa.string()),
    pa.field("total_count", pa.int64(), nullable=False),
    pa.field("reported_page_no", pa.int32()),
    pa.field("reported_num_of_rows", pa.int32()),
    pa.field("requested_num_of_rows", pa.int32(), nullable=False),
    pa.field("expected_pages_at_response", pa.int32(), nullable=False),
    pa.field("returned_item_count", pa.int32(), nullable=False),
    pa.field("items_container_kind", pa.string(), nullable=False),
    pa.field("response_body_bytes", pa.int64(), nullable=False),
    pa.field("response_body_sha256", pa.string(), nullable=False),
    pa.field("credential_echo_checked", pa.bool_(), nullable=False),
    pa.field("raw_page_path", pa.string(), nullable=False),
])


def utc_iso(epoch_ms: int) -> str:
    return datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc).isoformat(
        timespec="milliseconds"
    ).replace("+00:00", "Z")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=False, separators=(",", ":"))


def sha256_bytes(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def as_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def source_text(value: Any) -> str | None:
    if value is None:
        return None
    return value if isinstance(value, str) else canonical_json(value)


def source_date(value: Any) -> date | None:
    if isinstance(value, bool) or value is None:
        return None
    text = str(value).strip()
    if len(text) != 8 or not text.isascii() or not text.isdigit():
        return None
    try:
        return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    except ValueError:
        return None


def actual_meet(value: Any) -> int | None:
    if value is None:
        return None
    return MEET_TEXT_CODES.get(str(value).strip())


def expected_partitions() -> list[tuple[int, int]]:
    partitions = [(year, meet) for year in range(2010, 2026) for meet in (1, 3)]
    partitions.extend((2026, meet) for meet in (1, 3, 4))
    return partitions


def response_parts(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    response = payload.get("response", payload)
    if not isinstance(response, dict):
        raise ValueError("response_not_object")
    header, body = response.get("header"), response.get("body")
    if not isinstance(header, dict) or not isinstance(body, dict):
        raise ValueError("header_or_body_missing")
    return header, body


def decode_items(body: dict[str, Any], total_count: int) -> tuple[list[dict[str, Any]], str]:
    if "items" not in body:
        if total_count == 0:
            return [], "missing_zero_result"
        raise ValueError("items_missing_with_nonzero_total")
    container = body.get("items")
    if container in (None, ""):
        if total_count == 0:
            return [], "empty_container_zero_result"
        raise ValueError("empty_container_with_nonzero_total")
    if not isinstance(container, dict):
        raise ValueError("items_container_not_object")
    if "item" not in container or container.get("item") in (None, ""):
        if total_count == 0:
            return [], "empty_item_zero_result"
        raise ValueError("item_missing_with_nonzero_total")
    rows = container["item"]
    if isinstance(rows, dict):
        return [rows], "single_object"
    if isinstance(rows, list) and all(isinstance(row, dict) for row in rows):
        return rows, "list"
    raise ValueError("item_list_not_object_or_array")


def check_no_credential_echo(body: bytes, secret: str) -> None:
    variants = {secret.encode("utf-8"), quote(secret, safe="").encode(), quote_plus(secret, safe="").encode()}
    if any(variant and variant in body for variant in variants):
        raise ValueError("credential_echo_detected")


def scope_reasons(
    year: int, meet: int, event_date: date | None, actual_code: int | None,
) -> list[str]:
    reasons: list[str] = []
    if event_date is None:
        reasons.append("invalid_or_missing_rcDate")
    else:
        if event_date < START_DATE:
            reasons.append("before_scope_start")
        if event_date > CUTOFF_DATE:
            reasons.append("after_scope_cutoff")
        if event_date.year != year:
            reasons.append("requested_year_mismatch")
    if actual_code is None:
        reasons.append("unknown_or_missing_actual_meet")
    elif actual_code != meet:
        reasons.append("requested_meet_mismatch")
    if meet == 4 and year != 2026:
        reasons.append("meet4_outside_requested_scope")
    return reasons


def normalize_item(
    *, dataset: str, item: dict[str, Any], requested_year: int, requested_meet: int,
    capture_id: str, page: dict[str, Any], source_path: str, page_sha: str, row_no: int,
) -> dict[str, Any]:
    event_date = source_date(item.get("rcDate"))
    actual_code = actual_meet(item.get("meet"))
    rc_no = as_int(item.get("rcNo"))
    date_iso = event_date.isoformat() if event_date else None
    race_key = f"{actual_code}:{date_iso}:{rc_no}" if actual_code and date_iso and rc_no is not None else None
    reasons = scope_reasons(requested_year, requested_meet, event_date, actual_code)
    if rc_no is None:
        reasons.append("invalid_or_missing_rcNo")
    subject_class = source_text(item.get("gubun"))
    subject_id = source_text(item.get("prNo"))
    horse_id = subject_id if dataset == "api180_1_sanction_history" and subject_class == "말" else None
    jockey_id = subject_id if dataset == "api180_1_sanction_history" and subject_class == "기수" else None
    structured_horse_locator = bool(horse_id) or any(
        key in item for key in ("horseNo", "horse_id", "hrNo", "horseId", "chulNo")
    )
    raw_text = canonical_json(item)
    return {
        "capture_id": capture_id,
        "dataset": dataset,
        "record_type": DATASETS[dataset]["record_type"],
        "requested_year": requested_year,
        "requested_meet": requested_meet,
        "actual_meet_code": actual_code,
        "meet": source_text(item.get("meet")),
        "rcDate": as_int(item.get("rcDate")),
        "race_date_iso": date_iso,
        "rcNo": rc_no,
        "race_key": race_key,
        **{field: source_text(item.get(field)) for field in TEXT_FIELDS},
        "subject_class": subject_class,
        "subject_id": subject_id,
        "horse_id": horse_id,
        "jockey_id": jockey_id,
        "chulNo": as_int(item.get("chulNo")),
        "fine": source_text(item.get("fine")),
        "has_structured_horse_locator": structured_horse_locator,
        "raw_item_json": raw_text,
        "source_fields_present_json": canonical_json(sorted(item)),
        "source_field_types_json": canonical_json({key: type(value).__name__ for key, value in item.items()}),
        "source_row_sha256": sha256_bytes(raw_text.encode("utf-8")),
        "row_scope_status": "included" if not reasons else "excluded",
        "exclusion_reasons_json": canonical_json(reasons) if reasons else None,
        "source_path": source_path,
        "page_sha256": page_sha,
        "source_captured_at_utc": page["retrieved_at_utc"],
        "source_captured_at_ms": page["retrieved_at_ms"],
        "requested_at_utc": page["requested_at_utc"],
        "requested_at_ms": page["requested_at_ms"],
        "page_no": page["reported_page_no"] or page["request_page_no"],
        "row_no": row_no,
        "source_location": f"{source_path}#item[{row_no}]",
    }


def save_parquet(path: Path, rows: list[dict[str, Any]], schema: pa.Schema) -> None:
    table = pa.Table.from_pylist(rows, schema=schema)
    pq.write_table(table, path, compression="zstd")


def collect_partition(
    *, client: Any, staging: Path, capture_id: str, dataset: str,
    requested_year: int, requested_meet: int, secret: str, minimum_interval: float,
    last_request_end_monotonic: float | None, observations: list[dict[str, Any]],
    pages: list[dict[str, Any]],
) -> tuple[dict[str, Any], float]:
    endpoint = DATASETS[dataset]["endpoint"]
    operation = DATASETS[dataset]["operation"]
    public = {"meet": requested_meet, "rc_year": str(requested_year), "_type": "json"}
    expected_total: int | None = None
    expected_pages: int | None = None
    partition_rows = 0
    partition_page_count = 0
    min_date: str | None = None
    max_date: str | None = None
    excluded_count = 0
    items_kind_counts: Counter[str] = Counter()
    request_end = last_request_end_monotonic

    # page 1 is always requested, including zero-result partitions, yielding a
    # durable raw empty receipt and page-ledger record.
    page_no = 1
    while True:
        if request_end is not None:
            delay = minimum_interval - (time.monotonic() - request_end)
            if delay > 0:
                time.sleep(delay)
        request_params = {**public, "pageNo": page_no, "numOfRows": PAGE_SIZE}
        fetched = client._fetch_json(
            endpoint, operation, request_params,
            service_key_parameter=DATASETS[dataset]["service_key_parameter"],
        )
        request_end = time.monotonic()
        body_bytes = fetched.body
        check_no_credential_echo(body_bytes, secret)
        header, body = response_parts(fetched.payload)
        total_count = as_int(body.get("totalCount"))
        reported_page = as_int(body.get("pageNo"))
        reported_size = as_int(body.get("numOfRows"))
        if total_count is None or total_count < 0:
            raise ValueError("invalid_totalCount")
        if expected_total is None:
            expected_total = total_count
            expected_pages = max(1, math.ceil(total_count / PAGE_SIZE))
        elif total_count != expected_total:
            raise ValueError("totalCount_changed_between_pages")
        if reported_page is not None and reported_page != page_no:
            raise ValueError("reported_pageNo_mismatch")
        if reported_size is not None and reported_size != PAGE_SIZE:
            raise ValueError("reported_numOfRows_mismatch")
        items, container_kind = decode_items(body, total_count)
        expected_here = max(0, min(PAGE_SIZE, total_count - (page_no - 1) * PAGE_SIZE))
        if len(items) != expected_here:
            raise ValueError("page_row_count_mismatch")
        if page_no > (expected_pages or 1):
            raise ValueError("unexpected_extra_page")

        retrieved_ms = fetched.retrieved_at_ms
        requested_ms = fetched.requested_at_ms
        rel_raw = Path("raw") / dataset / f"year={requested_year}" / f"meet={requested_meet}" / f"page-{page_no:04d}.json"
        raw_file = staging / rel_raw
        raw_file.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive create prevents an existing response from being silently replaced.
        with raw_file.open("xb") as stream:
            stream.write(body_bytes)
        page_sha = sha256_bytes(body_bytes)
        if sha256_file(raw_file) != page_sha:
            raise ValueError("saved_raw_page_hash_mismatch")
        rel_path = rel_raw.as_posix()
        page_row = {
            "capture_id": capture_id,
            "dataset": dataset,
            "requested_year": requested_year,
            "requested_meet": requested_meet,
            "endpoint": endpoint,
            "operation": operation,
            "source_url_redacted": fetched.source_url,
            "request_public_params_json": canonical_json(request_params),
            "requested_at_ms": requested_ms,
            "requested_at_utc": utc_iso(requested_ms),
            "retrieved_at_ms": retrieved_ms,
            "retrieved_at_utc": utc_iso(retrieved_ms),
            "http_status": fetched.status_code,
            "content_type": fetched.content_type,
            "result_code": str(header.get("resultCode", "")),
            "result_message": source_text(header.get("resultMsg")),
            "total_count": total_count,
            "reported_page_no": reported_page,
            "reported_num_of_rows": reported_size,
            "requested_num_of_rows": PAGE_SIZE,
            "expected_pages_at_response": expected_pages or 1,
            "returned_item_count": len(items),
            "items_container_kind": container_kind,
            "response_body_bytes": len(body_bytes),
            "response_body_sha256": page_sha,
            "credential_echo_checked": True,
            "raw_page_path": rel_path,
            "request_page_no": page_no,
        }
        pages.append({k: v for k, v in page_row.items() if k != "request_page_no"})
        items_kind_counts[container_kind] += 1
        partition_page_count += 1
        for row_no, item in enumerate(items, start=1):
            normalized = normalize_item(
                dataset=dataset, item=item, requested_year=requested_year,
                requested_meet=requested_meet, capture_id=capture_id, page=page_row,
                source_path=rel_path, page_sha=page_sha, row_no=row_no,
            )
            observations.append(normalized)
            partition_rows += 1
            if normalized["row_scope_status"] == "excluded":
                excluded_count += 1
            dt = normalized["race_date_iso"]
            if normalized["actual_meet_code"] == requested_meet and dt:
                min_date = dt if min_date is None else min(min_date, dt)
                max_date = dt if max_date is None else max(max_date, dt)

        if page_no >= (expected_pages or 1):
            break
        page_no += 1

    complete = expected_total == partition_rows and partition_page_count == (expected_pages or 1)
    if not complete:
        raise ValueError("partition_count_incomplete")
    return ({
        "dataset": dataset,
        "requested_year": requested_year,
        "requested_meet": requested_meet,
        "meet_label": MEET_LABELS[requested_meet],
        "total_count_reported": expected_total,
        "rows_captured": partition_rows,
        "pages_expected": expected_pages,
        "pages_captured": partition_page_count,
        "response_complete": complete,
        "empty_receipt": expected_total == 0,
        "min_actual_race_date": min_date,
        "max_actual_race_date": max_date,
        "excluded_occurrences": excluded_count,
        "page_container_kinds": dict(items_kind_counts),
    }, request_end)


def key_counts(rows: list[dict[str, Any]], key_fields: tuple[str, ...]) -> tuple[int, int, list[dict[str, Any]]]:
    counts: Counter[tuple[Any, ...]] = Counter(
        tuple(row.get(field) for field in key_fields) for row in rows
    )
    duplicate = [
        {**dict(zip(key_fields, key)), "occurrences": count}
        for key, count in counts.items() if count > 1
    ]
    return len(counts), sum(count - 1 for count in counts.values()), duplicate


def write_readme(path: Path) -> None:
    path.write_text(
        """# KRA API215/API180_1 steward and sanction source capture

This package stores exact response-body bytes from the official read-only KRA OpenAPI endpoints `API215/JudgeReport` and `API180_1/sanctionHistory_1`. It requests annual `rc_year` + `meet` partitions for 2010–2025 meets 1/3 and 2026 meets 1/3/4, with 1,000 rows per page and at least 0.5 seconds between requests. The service key is read from project settings in memory only; source parameters, redacted URLs, raw response bytes, logs, and manifests do not contain it.

`api_observations.parquet` keeps one source-item occurrence and all original fields in `raw_item_json`; `api_exclusions.parquet` repeats out-of-scope occurrences with reasons. `api_page_ledger.parquet` records every request, including zero-row receipts, public parameters, timestamps, response metadata, exact body size/hash, and raw-page path. `raw_page_sha256_manifest.json` independently lists each exact response. The collector verifies page numbers/lengths and a stable partition `totalCount` before marking a partition complete.

API215 contains race-level narrative (`judgement`, `addJudgement`) and race locator fields, but no structured horse ID/entry number in observed rows. Horse numbers/names in prose are retained verbatim and are not automatically parsed into horse links. API180_1 uses `gubun` to identify the sanction subject: observed `말` records carry a horse ID in `prNo`, horse name in `prName`, and `chulNo`; `기수` rows carry a jockey ID in `prNo`. `kind`, `reason`, `fine`, `spDate`, and `stDate` remain source values; `etlTime` is preserved as an opaque source field, not treated as a publication timestamp.

The annual response counts show retrieval availability, not that every past report or sanction exists in the endpoint. In particular, API215 returned normal zero-count responses for 2010–2016 Seoul/Busan; this is a zero-result receipt and not proof that historical reports never existed. Coverage and missing confirmed-race keys are supplied separately for review. These files do not modify or load any database or service.
""",
        encoding="utf-8",
    )


def build_core_comparison(staging: Path, observations: list[dict[str, Any]]) -> dict[str, Any]:
    """Compare race keys with frozen local research exports, never a live DB."""
    core_file = ROOT / "thoroughbred/research/20261002_passing_groups_v1/root_expected_confirmed_races.json"
    nonexec_file = ROOT / "thoroughbred/research/20261001_closure_gap_followup_v4/core_review/race_nonexecution_adjudication.csv"
    if not core_file.exists():
        return {"status": "unavailable", "reason": "frozen_core_confirmed_race_export_missing"}
    import csv

    raw_core = json.loads(core_file.read_text(encoding="utf-8"))
    confirmed: dict[str, dict[str, Any]] = {}
    for row in raw_core:
        code = as_int(row.get("meet"))
        event = source_date(str(row.get("event_date", "")).replace("-", ""))
        no = as_int(row.get("race_no"))
        if code and event and no is not None:
            key = f"{code}:{event.isoformat()}:{no}"
            confirmed[key] = {"race_key": key, "meet": code, "race_date": event.isoformat(), "race_no": no}
    nonexecution: dict[str, dict[str, str]] = {}
    if nonexec_file.exists():
        with nonexec_file.open(encoding="utf-8-sig", newline="") as stream:
            for row in csv.DictReader(stream):
                code = as_int(row.get("meet"))
                event = source_date(row.get("date"))
                no = as_int(row.get("race_no"))
                if code and event and no is not None:
                    nonexecution[f"{code}:{event.isoformat()}:{no}"] = {
                        "execution_verdict": row.get("execution_verdict", ""),
                        "adjudication_status": row.get("adjudication_status", ""),
                    }

    by_dataset_keys: dict[str, set[str]] = defaultdict(set)
    for row in observations:
        if row.get("row_scope_status") == "included" and row.get("race_key"):
            by_dataset_keys[row["dataset"]].add(row["race_key"])

    rows_out = []
    missing_reports = []
    unconfirmed = []
    for dataset in DATASETS:
        keys = by_dataset_keys.get(dataset, set())
        for key, race in confirmed.items():
            exists = key in keys
            rows_out.append({
                "dataset": dataset,
                **race,
                "has_source_record_for_race": exists,
                "adjudicated_nonexecution": key in nonexecution,
                "execution_verdict": nonexecution.get(key, {}).get("execution_verdict"),
                "adjudication_status": nonexecution.get(key, {}).get("adjudication_status"),
                "interpretation": (
                    "source_record_present" if exists else
                    "no_api215_race_report_observed" if dataset == "api215_judge_report" else
                    "no_sanction_record_observed_not_a_completeness_failure"
                ),
            })
            if dataset == "api215_judge_report" and not exists:
                missing_reports.append({
                    **race,
                    "adjudicated_nonexecution": key in nonexecution,
                    "execution_verdict": nonexecution.get(key, {}).get("execution_verdict"),
                    "adjudication_status": nonexecution.get(key, {}).get("adjudication_status"),
                })
        for key in sorted(keys - set(confirmed)):
            unconfirmed.append({
                "dataset": dataset, "race_key": key,
                "adjudicated_nonexecution": key in nonexecution,
                "execution_verdict": nonexecution.get(key, {}).get("execution_verdict"),
                "adjudication_status": nonexecution.get(key, {}).get("adjudication_status"),
            })
    with (staging / "core_race_source_comparison.csv").open("w", encoding="utf-8", newline="") as stream:
        fields = list(rows_out[0]) if rows_out else []
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader(); writer.writerows(rows_out)
    with (staging / "api215_missing_confirmed_race_keys.csv").open("w", encoding="utf-8", newline="") as stream:
        fields = list(missing_reports[0]) if missing_reports else ["race_key", "meet", "race_date", "race_no"]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader(); writer.writerows(missing_reports)
    with (staging / "source_race_keys_not_in_confirmed_core.csv").open("w", encoding="utf-8", newline="") as stream:
        fields = list(unconfirmed[0]) if unconfirmed else ["dataset", "race_key"]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader(); writer.writerows(unconfirmed)
    return {
        "status": "compared_to_frozen_local_exports",
        "confirmed_reference": str(core_file.relative_to(ROOT)),
        "confirmed_race_key_count": len(confirmed),
        "adjudicated_nonexecution_key_count": len(nonexecution),
        "api215_observed_distinct_race_keys": len(by_dataset_keys.get("api215_judge_report", set())),
        "api215_confirmed_races_without_report_record": len(missing_reports),
        "api180_distinct_races_with_sanction_records": len(by_dataset_keys.get("api180_1_sanction_history", set())),
        "source_race_keys_not_in_confirmed_reference": len(unconfirmed),
        "interpretation_limit": "No API180 sanction is expected for every race; absent rows are not coverage failures. Confirmed-core mismatches and nonexecution overlaps are review aids, not automatic source errors.",
    }


def collect_all(minimum_interval: float) -> Path:
    from horse_racing.collectors.kra_api import KraApiClient
    from horse_racing.config import get_settings

    settings = get_settings()
    secret_setting = settings.data_go_kr_service_key
    if secret_setting is None or not secret_setting.get_secret_value().strip():
        raise RuntimeError("credential_unavailable")
    if settings.kra_api_base_url.rstrip("/") != BASE_URL:
        raise RuntimeError("unexpected_api_base_url")
    if OUTPUT.exists():
        raise FileExistsError("output_exists")
    PACKAGE.mkdir(parents=True, exist_ok=True)
    capture_id = str(uuid.uuid4())
    started_ms = time.time_ns() // 1_000_000
    started_utc = utc_iso(started_ms)
    staging = Path(tempfile.mkdtemp(prefix=f".source_capture_{capture_id}_", dir=PACKAGE))
    observations: list[dict[str, Any]] = []
    pages: list[dict[str, Any]] = []
    coverage: list[dict[str, Any]] = []
    secret = secret_setting.get_secret_value()
    last_request_end: float | None = None
    try:
        with KraApiClient(
            secret, base_url=BASE_URL, timeout_seconds=settings.http_timeout_seconds,
        ) as client:
            partitions = expected_partitions()
            task_partitions = [(dataset, year, meet) for dataset in DATASETS for year, meet in partitions]
            for index, (dataset, year, meet) in enumerate(task_partitions, start=1):
                partition, last_request_end = collect_partition(
                    client=client, staging=staging, capture_id=capture_id,
                    dataset=dataset, requested_year=year, requested_meet=meet,
                    secret=secret, minimum_interval=minimum_interval,
                    last_request_end_monotonic=last_request_end,
                    observations=observations, pages=pages,
                )
                coverage.append(partition)
                print(json.dumps({
                    "partition": f"{dataset}:{year}/meet={meet}",
                    "index": index,
                    "partition_count": len(task_partitions),
                    "pages": partition["pages_captured"],
                    "reported_rows": partition["total_count_reported"],
                    "captured_rows": partition["rows_captured"],
                    "complete": partition["response_complete"],
                }, ensure_ascii=False), flush=True)

        excluded = [row for row in observations if row["row_scope_status"] == "excluded"]
        save_parquet(staging / "api_observations.parquet", observations, OBSERVATION_SCHEMA)
        save_parquet(staging / "api_exclusions.parquet", excluded, OBSERVATION_SCHEMA)
        save_parquet(staging / "api_page_ledger.parquet", pages, PAGE_SCHEMA)
        coverage_doc = {
            "capture_id": capture_id,
            "capture_started_at_utc": started_utc,
            "capture_finished_at_utc": utc_iso(time.time_ns() // 1_000_000),
            "scope": {"start_date_inclusive": START_DATE.isoformat(), "cutoff_date_inclusive": CUTOFF_DATE.isoformat(), "meets": {str(k): v for k, v in MEET_LABELS.items()}, "partitions_per_dataset": len(expected_partitions())},
            "page_size": PAGE_SIZE,
            "minimum_request_interval_seconds": minimum_interval,
            "partition_count": len(coverage),
            "partition_count_expected": len(DATASETS) * len(expected_partitions()),
            "all_partitions_complete": len(coverage) == len(DATASETS) * len(expected_partitions()) and all(r["response_complete"] for r in coverage),
            "api_item_occurrence_count": len(observations),
            "in_scope_occurrence_count": len(observations) - len(excluded),
            "excluded_occurrence_count": len(excluded),
            "page_count": len(pages),
            "partitions": coverage,
        }
        (staging / "api_year_meet_coverage.json").write_text(json.dumps(coverage_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        duplicate_audit: dict[str, Any] = {}
        duplicate_outputs: dict[str, list[dict[str, Any]]] = {}
        for dataset in DATASETS:
            rows = [r for r in observations if r["dataset"] == dataset and r["row_scope_status"] == "included"]
            distinct, extra, duplicated = key_counts(rows, ("race_key",))
            duplicate_audit[dataset] = {
                "in_scope_row_occurrences": len(rows),
                "distinct_race_keys_with_source_rows": distinct,
                "extra_occurrences_on_repeated_race_keys": extra,
                "repeated_race_key_count": len(duplicated),
            }
            duplicate_outputs[dataset] = duplicated
        sanction_rows = [r for r in observations if r["dataset"] == "api180_1_sanction_history" and r["row_scope_status"] == "included"]
        sanction_identity = ("race_key", "gubun", "prNo", "chulNo", "kind", "reason", "spDate", "stDate", "fine")
        identity_distinct, identity_extra, identity_duplicates = key_counts(sanction_rows, sanction_identity)
        exact_counts = Counter(r["source_row_sha256"] for r in sanction_rows)
        exact_duplicate_hashes = [{"source_row_sha256": h, "occurrences": n} for h, n in exact_counts.items() if n > 1]
        duplicate_doc = {
            "by_dataset_race_key": duplicate_audit,
            "sanction_candidate_event_key_fields": list(sanction_identity),
            "sanction_candidate_event_key_distinct": identity_distinct,
            "sanction_candidate_event_key_extra_occurrences": identity_extra,
            "sanction_candidate_event_key_repeat_count": len(identity_duplicates),
            "exact_sanction_item_hash_repeat_count": len(exact_duplicate_hashes),
            "interpretation": "The API provides no event ID in observed fields. Repeated candidate keys and identical records are reported, not deduplicated; source occurrences remain intact.",
            "repeated_race_keys": duplicate_outputs,
            "repeated_sanction_candidate_event_keys": identity_duplicates,
            "repeated_exact_sanction_item_hashes": exact_duplicate_hashes,
        }
        (staging / "duplicate_key_audit.json").write_text(json.dumps(duplicate_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        core_comparison = build_core_comparison(staging, observations)
        (staging / "core_race_comparison_summary.json").write_text(json.dumps(core_comparison, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        raw_manifest = [{
            "path": page["raw_page_path"], "dataset": page["dataset"],
            "requested_year": page["requested_year"], "requested_meet": page["requested_meet"],
            "page_no": page["reported_page_no"], "bytes": page["response_body_bytes"],
            "sha256": page["response_body_sha256"], "captured_at_utc": page["retrieved_at_utc"],
            "total_count": page["total_count"], "rows": page["returned_item_count"],
        } for page in pages]
        (staging / "raw_page_sha256_manifest.json").write_text(json.dumps(raw_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        write_readme(staging / "README.md")
        files = [p for p in staging.rglob("*") if p.is_file()]
        artifact_hashes = {p.relative_to(staging).as_posix(): sha256_file(p) for p in files}
        manifest = {
            "status": "complete" if coverage_doc["all_partitions_complete"] else "incomplete",
            "capture_id": capture_id,
            "source": "KRA official OpenAPI",
            "base_url": BASE_URL,
            "datasets": DATASETS,
            "capture_started_at_utc": started_utc,
            "capture_finished_at_utc": coverage_doc["capture_finished_at_utc"],
            "scope": coverage_doc["scope"],
            "request": {"year_parameter": "rc_year", "meet_parameter": "meet", "format_parameter": "_type=json", "page_parameter": "pageNo", "page_size_parameter": "numOfRows", "page_size": PAGE_SIZE, "minimum_interval_seconds": minimum_interval, "credential_in_source_files": False, "credential_in_logs": False},
            "counts": {"pages": len(pages), "source_item_occurrences": len(observations), "in_scope_occurrences": len(observations) - len(excluded), "excluded_occurrences": len(excluded), "complete_partitions": sum(bool(r["response_complete"]) for r in coverage)},
            "observation_schema": str(OBSERVATION_SCHEMA),
            "page_schema": str(PAGE_SCHEMA),
            "core_comparison": core_comparison,
            "collector_path": str(Path(__file__).resolve().relative_to(ROOT)),
            "collector_sha256": sha256_file(Path(__file__).resolve()),
            "artifact_sha256": artifact_hashes,
            "raw_pages": raw_manifest,
        }
        (staging / "source_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if not manifest["status"] == "complete":
            raise RuntimeError("capture_incomplete")
        os.rename(staging, OUTPUT)
        return OUTPUT
    except Exception:
        if staging.exists():
            marker = staging / "capture_failure.json"
            marker.write_text(json.dumps({
                "capture_id": capture_id,
                "failure_type": "collection_or_validation_error",
                "capture_started_at_utc": started_utc,
                "captured_pages_before_failure": len(pages),
                "captured_rows_before_failure": len(observations),
            }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            preserved = PACKAGE / f"source_incomplete_{capture_id}"
            if not preserved.exists():
                os.rename(staging, preserved)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--minimum-request-interval", type=float, default=MIN_INTERVAL_SECONDS)
    args = parser.parse_args()
    if args.minimum_request_interval < MIN_INTERVAL_SECONDS:
        parser.error("minimum-request-interval must be at least 0.5 seconds")
    try:
        output = collect_all(args.minimum_request_interval)
    except Exception as exc:
        # Never emit exception text: HTTP clients can include credentialed URLs.
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps({"status": "complete", "output": str(output.relative_to(ROOT))}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
