#!/usr/bin/env python3
"""Capture complete API303 yearly passing-group responses without database access."""

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
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT / "thoroughbred/research/20261002_passing_groups_v1"
OUTPUT = PACKAGE / "api_source"
ENDPOINT = "/API303/corner_rank"
OPERATION = "corner_rank"
BASE_URL = "https://apis.data.go.kr/B551015"
PAGE_SIZE = 1000
MIN_REQUEST_INTERVAL_SECONDS = 0.5
START_DATE = date(2010, 1, 1)
CUTOFF_DATE = date(2026, 9, 29)
SOURCE_FIELDS = (
    "corner_1", "corner_2", "corner_3", "corner_4", "corner_5",
    "corner_6", "corner_7", "corner_8", "corner_9",
    "meet", "rcDate", "rcNo", "passtime_3f", "passtime_4f", "tempo",
)
MEET_LABELS = {
    "서울": 1,
    "부산": 3,
    "부경": 3,
    "부산경남": 3,
    "영천": 4,
}

OBSERVATION_SCHEMA = pa.schema(
    [
        pa.field("capture_id", pa.string(), nullable=False),
        pa.field("source_cohort", pa.string(), nullable=False),
        pa.field("requested_year", pa.int16(), nullable=False),
        pa.field("requested_meet", pa.int8(), nullable=False),
        pa.field("actual_meet_code", pa.int8()),
        pa.field("meet", pa.string()),
        pa.field("rcDate", pa.int64()),
        pa.field("rc_date_raw_json", pa.string()),
        pa.field("race_date_iso", pa.string()),
        pa.field("rcNo", pa.int64()),
        pa.field("rc_no_raw_json", pa.string()),
        *[pa.field(f"corner_{index}", pa.string()) for index in range(1, 10)],
        pa.field("passtime_3f", pa.string()),
        pa.field("passtime_4f", pa.string()),
        pa.field("tempo", pa.string()),
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
    ]
)

PAGE_SCHEMA = pa.schema(
    [
        pa.field("capture_id", pa.string(), nullable=False),
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
        pa.field("raw_page_path", pa.string(), nullable=False),
    ]
)


def utc_iso(epoch_ms: int) -> str:
    return datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc).isoformat(
        timespec="milliseconds"
    ).replace("+00:00", "Z")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=False, separators=(",", ":"))


def canonical_scalar_json(value: Any) -> str | None:
    return None if value is None else canonical_json(value)


def source_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return canonical_json(value)


def as_int_or_none(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed


def parse_source_date(value: Any) -> date | None:
    if isinstance(value, bool) or value is None:
        return None
    text = str(value)
    if len(text) != 8 or not text.isascii() or not text.isdigit():
        return None
    try:
        parsed = date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    except ValueError:
        return None
    return parsed


def field_type_map(item: dict[str, Any]) -> str:
    return canonical_json({key: type(value).__name__ for key, value in item.items()})


def decode_items(body: dict[str, Any], total_count: int) -> tuple[list[dict[str, Any]], str]:
    if "items" not in body:
        if total_count == 0:
            return [], "missing_zero_result"
        raise ValueError("API 응답에 items 컨테이너가 없습니다.")
    container = body["items"]
    if container in (None, ""):
        if total_count == 0:
            return [], "empty_container_zero_result"
        raise ValueError("API items가 비었지만 totalCount는 0이 아닙니다.")
    if not isinstance(container, dict):
        raise ValueError("API items 컨테이너 형식이 객체가 아닙니다.")
    if "item" not in container or container.get("item") in (None, ""):
        if total_count == 0:
            return [], "empty_item_zero_result"
        raise ValueError("API item 목록이 비었지만 totalCount는 0이 아닙니다.")
    raw_items = container["item"]
    if isinstance(raw_items, dict):
        raw_items = [raw_items]
        kind = "single_object"
    elif isinstance(raw_items, list):
        kind = "list"
    else:
        raise ValueError("API item 목록 형식이 객체 또는 배열이 아닙니다.")
    if any(not isinstance(row, dict) for row in raw_items):
        raise ValueError("API item 목록에 객체가 아닌 원소가 있습니다.")
    if not raw_items and total_count != 0:
        raise ValueError("API item 배열이 비었지만 totalCount는 0이 아닙니다.")
    return raw_items, kind


def body_metadata(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    response = payload.get("response", payload)
    if not isinstance(response, dict):
        raise ValueError("API response가 객체가 아닙니다.")
    header = response.get("header")
    body = response.get("body")
    if not isinstance(header, dict) or not isinstance(body, dict):
        raise ValueError("API header/body가 객체가 아닙니다.")
    return header, body


def scope_reasons(
    *, requested_year: int, requested_meet: int, raw_meet: str | None,
    actual_meet: int | None, event_date: date | None, race_no: int | None,
) -> list[str]:
    reasons: list[str] = []
    if event_date is None:
        reasons.append("invalid_or_missing_rcDate")
    else:
        if event_date < START_DATE:
            reasons.append("before_scope_start")
        if event_date > CUTOFF_DATE:
            reasons.append("after_scope_cutoff")
        if event_date.year != requested_year:
            reasons.append("requested_year_mismatch")
    if actual_meet is None:
        reasons.append("unknown_or_missing_actual_meet")
    elif actual_meet != requested_meet:
        reasons.append("requested_meet_mismatch")
    if race_no is None or race_no <= 0:
        reasons.append("invalid_or_missing_rcNo")
    if requested_meet == 4 and requested_year != 2026:
        reasons.append("meet4_outside_requested_schedule")
    return reasons


def build_observation(
    *, capture_id: str, requested_year: int, requested_meet: int,
    item: dict[str, Any], page_no: int, row_no: int,
    raw_page_path: str, page_sha256: str,
    requested_at_ms: int, retrieved_at_ms: int,
) -> dict[str, Any]:
    meet_raw = source_text(item.get("meet"))
    actual_meet = MEET_LABELS.get(meet_raw.strip()) if meet_raw is not None else None
    event_date = parse_source_date(item.get("rcDate"))
    race_no = as_int_or_none(item.get("rcNo"))
    reasons = scope_reasons(
        requested_year=requested_year,
        requested_meet=requested_meet,
        raw_meet=meet_raw,
        actual_meet=actual_meet,
        event_date=event_date,
        race_no=race_no,
    )
    item_json = canonical_json(item)
    raw_page = Path(raw_page_path)
    location = f"{raw_page_path}#/response/body/items/item/{row_no - 1}"
    record: dict[str, Any] = {
        "capture_id": capture_id,
        "source_cohort": "current_annual",
        "requested_year": requested_year,
        "requested_meet": requested_meet,
        "actual_meet_code": actual_meet,
        "meet": meet_raw,
        "rcDate": as_int_or_none(item.get("rcDate")),
        "rc_date_raw_json": canonical_scalar_json(item.get("rcDate")),
        "race_date_iso": event_date.isoformat() if event_date else None,
        "rcNo": race_no,
        "rc_no_raw_json": canonical_scalar_json(item.get("rcNo")),
        **{f"corner_{index}": source_text(item.get(f"corner_{index}")) for index in range(1, 10)},
        "passtime_3f": source_text(item.get("passtime_3f")),
        "passtime_4f": source_text(item.get("passtime_4f")),
        "tempo": source_text(item.get("tempo")),
        "raw_item_json": item_json,
        "source_fields_present_json": canonical_json(list(item.keys())),
        "source_field_types_json": field_type_map(item),
        "source_row_sha256": hashlib.sha256(item_json.encode("utf-8")).hexdigest(),
        "row_scope_status": "excluded" if reasons else "in_scope",
        "exclusion_reasons_json": canonical_json(reasons) if reasons else None,
        "source_path": raw_page_path,
        "page_sha256": page_sha256,
        "source_captured_at_utc": utc_iso(retrieved_at_ms),
        "source_captured_at_ms": retrieved_at_ms,
        "requested_at_utc": utc_iso(requested_at_ms),
        "requested_at_ms": requested_at_ms,
        "page_no": page_no,
        "row_no": row_no,
        "source_location": location,
    }
    return record


def int_meta(body: dict[str, Any], name: str) -> int:
    value = as_int_or_none(body.get(name))
    if value is None or value < 0:
        raise ValueError(f"API 응답 {name} 메타데이터가 정수가 아닙니다.")
    return value


def count_item_values(rows: list[dict[str, Any]], field: str) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for row in rows:
        value = row.get(field)
        if value is None:
            key = "<null-or-missing>"
        elif value == "":
            key = "<empty-string>"
        else:
            key = str(value)
        counter[key] += 1
    return dict(sorted(counter.items()))


def save_parquet(path: Path, rows: list[dict[str, Any]], schema: pa.Schema) -> None:
    table = pa.Table.from_pylist(rows, schema=schema)
    pq.write_table(table, path, compression="zstd", version="2.6")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def expected_partitions() -> list[tuple[int, int]]:
    result = [(year, meet) for year in range(2010, 2027) for meet in (1, 3)]
    result.append((2026, 4))
    return result


def collect_partition(
    *, client: Any, staging: Path, capture_id: str, capture_started_at_utc: str,
    requested_year: int, requested_meet: int, all_observations: list[dict[str, Any]],
    all_pages: list[dict[str, Any]], minimum_interval: float,
) -> dict[str, Any]:
    from horse_racing.collectors.kra_api import (
        RACE_PASSING_SUMMARY_ENDPOINT,
        RACE_PASSING_SUMMARY_OPERATION,
    )

    public_base = {"meet": requested_meet, "rc_year": str(requested_year), "_type": "json"}
    page_no = 1
    target_pages = 1
    page_rows: list[dict[str, Any]] = []
    partition_observations: list[dict[str, Any]] = []
    errors: list[str] = []
    seen_totals: list[int] = []
    while page_no <= target_pages:
        public_params = {
            **public_base,
            "pageNo": page_no,
            "numOfRows": PAGE_SIZE,
        }
        fetched = client._fetch_json(
            RACE_PASSING_SUMMARY_ENDPOINT,
            RACE_PASSING_SUMMARY_OPERATION,
            public_params,
            service_key_parameter="serviceKey",
        )
        time.sleep(minimum_interval)
        header, body = body_metadata(fetched.payload)
        total_count = int_meta(body, "totalCount")
        reported_page = as_int_or_none(body.get("pageNo"))
        reported_size = as_int_or_none(body.get("numOfRows"))
        current_expected_pages = max(1, math.ceil(total_count / PAGE_SIZE))
        target_pages = max(target_pages, current_expected_pages)
        raw_items, container_kind = decode_items(body, total_count)
        page_hash = hashlib.sha256(fetched.body).hexdigest()
        rel_path = Path("raw") / f"year={requested_year}" / f"meet={requested_meet}" / (
            f"page_{page_no:04d}_{fetched.retrieved_at_ms}_{page_hash[:12]}.json"
        )
        raw_path = staging / rel_path
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        with raw_path.open("xb") as raw_stream:
            raw_stream.write(fetched.body)
        if sha256_file(raw_path) != page_hash:
            raise ValueError("저장한 raw 페이지 SHA-256이 응답 본문과 다릅니다.")

        page_record = {
            "capture_id": capture_id,
            "requested_year": requested_year,
            "requested_meet": requested_meet,
            "endpoint": fetched.endpoint,
            "operation": fetched.operation,
            "source_url_redacted": fetched.source_url,
            "request_public_params_json": canonical_json(dict(fetched.public_params)),
            "requested_at_ms": fetched.requested_at_ms,
            "requested_at_utc": utc_iso(fetched.requested_at_ms),
            "retrieved_at_ms": fetched.retrieved_at_ms,
            "retrieved_at_utc": utc_iso(fetched.retrieved_at_ms),
            "http_status": fetched.status_code,
            "content_type": fetched.content_type,
            "result_code": str(header.get("resultCode", "")),
            "result_message": source_text(header.get("resultMsg")),
            "total_count": total_count,
            "reported_page_no": reported_page,
            "reported_num_of_rows": reported_size,
            "requested_num_of_rows": PAGE_SIZE,
            "expected_pages_at_response": current_expected_pages,
            "returned_item_count": len(raw_items),
            "items_container_kind": container_kind,
            "response_body_bytes": len(fetched.body),
            "response_body_sha256": page_hash,
            "raw_page_path": rel_path.as_posix(),
        }
        page_rows.append(page_record)
        seen_totals.append(total_count)
        if fetched.status_code != 200:
            errors.append(f"page_{page_no}:http_status_{fetched.status_code}")
        if str(header.get("resultCode", "")) not in {"00", "0000"}:
            errors.append(f"page_{page_no}:api_result_code")
        if reported_page != page_no:
            errors.append(f"page_{page_no}:reported_page_no_mismatch")
        if reported_size != PAGE_SIZE:
            errors.append(f"page_{page_no}:reported_page_size_mismatch")
        expected_rows = min(PAGE_SIZE, max(0, total_count - (page_no - 1) * PAGE_SIZE))
        if len(raw_items) != expected_rows:
            errors.append(f"page_{page_no}:item_count_mismatch")

        for row_no, item in enumerate(raw_items, start=1):
            observation = build_observation(
                capture_id=capture_id,
                requested_year=requested_year,
                requested_meet=requested_meet,
                item=item,
                page_no=page_no,
                row_no=row_no,
                raw_page_path=rel_path.as_posix(),
                page_sha256=page_hash,
                requested_at_ms=fetched.requested_at_ms,
                retrieved_at_ms=fetched.retrieved_at_ms,
            )
            partition_observations.append(observation)
        page_no += 1

    if page_rows:
        if len(set(seen_totals)) != 1:
            errors.append("totalCount_changed_between_pages")
        first_total = seen_totals[0]
        required_pages = max(1, math.ceil(first_total / PAGE_SIZE))
        if len(page_rows) != required_pages:
            errors.append("captured_page_count_mismatch")
        expected_numbers = list(range(1, required_pages + 1))
        if [int(row["reported_page_no"] or 0) for row in page_rows] != expected_numbers:
            errors.append("page_number_sequence_mismatch")
        if sum(int(row["returned_item_count"]) for row in page_rows) != first_total:
            errors.append("captured_item_count_does_not_equal_totalCount")

    scoped_rows = [row for row in partition_observations if row["row_scope_status"] == "in_scope"]
    excluded_rows = [row for row in partition_observations if row["row_scope_status"] == "excluded"]
    dates = [row["race_date_iso"] for row in scoped_rows if row["race_date_iso"]]
    coverage = {
        "requested_year": requested_year,
        "requested_meet": requested_meet,
        "venue_expected": {1: "서울", 3: "부산/부경", 4: "영천"}[requested_meet],
        "partition_date_start": f"{requested_year}-01-01",
        "partition_date_end": f"{requested_year}-12-31",
        "cutoff_date": CUTOFF_DATE.isoformat(),
        "page_size_requested": PAGE_SIZE,
        "pages_expected": max(1, math.ceil((seen_totals[0] if seen_totals else 0) / PAGE_SIZE)),
        "pages_captured": len(page_rows),
        "total_count_values": sorted(set(seen_totals)),
        "rows_reported_total": seen_totals[0] if seen_totals else 0,
        "rows_captured": len(partition_observations),
        "rows_in_scope": len(scoped_rows),
        "rows_excluded": len(excluded_rows),
        "unique_in_scope_race_keys": len({(r["actual_meet_code"], r["race_date_iso"], r["rcNo"]) for r in scoped_rows}),
        "in_scope_date_min": min(dates) if dates else None,
        "in_scope_date_max": max(dates) if dates else None,
        "meet_literal_counts": count_item_values(partition_observations, "meet"),
        "scope_exclusion_reason_counts": dict(Counter(
            reason
            for row in excluded_rows
            for reason in json.loads(row["exclusion_reasons_json"] or "[]")
        )),
        "page_validation_errors": errors,
        "response_complete": not errors and len(partition_observations) == (seen_totals[0] if seen_totals else 0),
        "page_ledger_rows": len(page_rows),
        "capture_started_at_utc": capture_started_at_utc,
    }
    all_observations.extend(partition_observations)
    all_pages.extend(page_rows)
    return coverage


def write_readme(path: Path) -> None:
    path.write_text(
        """# API303 passing-group raw capture

This package captures `https://apis.data.go.kr/B551015/API303/corner_rank` by annual `rc_year` and `meet` partition. It uses the project settings key in memory and never stores or prints it. Request pacing is at least 0.5 seconds.

The raw page JSON files are the exact successful HTTP response body bytes. Parquet observations keep one item occurrence per source page and row; they retain source fields including `corner_1` through `corner_9`, `meet`, `rcDate`, `rcNo`, `passtime_3f`, `passtime_4f`, and `tempo`. Empty strings, `-`, `X`, and nulls are not interpreted in this package. `actual_meet_code` and `race_date_iso` are extra derived locator fields; `raw_item_json` and the exact page body preserve the original values. Records outside scope remain in the observation file and are repeated in `api_exclusions.parquet` with reasons.

Completeness is reported per year/meet in `api_year_meet_coverage.json`. A zero-count request still has a page-ledger row. This source collector does not read or write any database.
""",
        encoding="utf-8",
    )


def collect_all(minimum_interval: float) -> Path:
    from horse_racing.collectors.kra_api import KraApiClient
    from horse_racing.config import get_settings

    settings = get_settings()
    if settings.data_go_kr_service_key is None:
        raise RuntimeError("data.go.kr 서비스 키 설정이 없습니다.")
    if settings.kra_api_base_url.rstrip("/") != BASE_URL:
        raise RuntimeError("KRA API base URL이 고정 허용 주소와 다릅니다.")
    if OUTPUT.exists():
        raise FileExistsError("출력 경로가 이미 있습니다. 기존 자료를 덮어쓰지 않습니다.")
    PACKAGE.mkdir(parents=True, exist_ok=True)
    capture_id = str(uuid.uuid4())
    capture_started_ms = time.time_ns() // 1_000_000
    capture_started_at_utc = utc_iso(capture_started_ms)
    staging = Path(tempfile.mkdtemp(prefix=f".api303_capture_{capture_id}_", dir=PACKAGE))
    all_observations: list[dict[str, Any]] = []
    all_pages: list[dict[str, Any]] = []
    coverage_rows: list[dict[str, Any]] = []
    try:
        with KraApiClient(
            settings.data_go_kr_service_key.get_secret_value(),
            base_url=BASE_URL,
            timeout_seconds=settings.http_timeout_seconds,
        ) as client:
            partitions = expected_partitions()
            for index, (year, meet) in enumerate(partitions, start=1):
                part = collect_partition(
                    client=client,
                    staging=staging,
                    capture_id=capture_id,
                    capture_started_at_utc=capture_started_at_utc,
                    requested_year=year,
                    requested_meet=meet,
                    all_observations=all_observations,
                    all_pages=all_pages,
                    minimum_interval=minimum_interval,
                )
                coverage_rows.append(part)
                print(json.dumps({
                    "partition": f"{year}/meet={meet}",
                    "index": index,
                    "partition_count": len(partitions),
                    "pages": part["pages_captured"],
                    "reported_rows": part["rows_reported_total"],
                    "captured_rows": part["rows_captured"],
                    "response_complete": part["response_complete"],
                }, ensure_ascii=False), flush=True)

        staging.mkdir(parents=True, exist_ok=True)
        save_parquet(staging / "api_observations.parquet", all_observations, OBSERVATION_SCHEMA)
        excluded = [row for row in all_observations if row["row_scope_status"] == "excluded"]
        save_parquet(staging / "api_exclusions.parquet", excluded, OBSERVATION_SCHEMA)
        save_parquet(staging / "api_page_ledger.parquet", all_pages, PAGE_SCHEMA)
        coverage_doc = {
            "dataset": "KRA API303 corner_rank",
            "endpoint": ENDPOINT,
            "operation": OPERATION,
            "capture_id": capture_id,
            "capture_cohort": "current_annual",
            "capture_started_at_utc": capture_started_at_utc,
            "capture_finished_at_utc": utc_iso(time.time_ns() // 1_000_000),
            "history_start_date": START_DATE.isoformat(),
            "cutoff_date": CUTOFF_DATE.isoformat(),
            "page_size": PAGE_SIZE,
            "request_minimum_interval_seconds": minimum_interval,
            "partitions_requested": len(expected_partitions()),
            "partitions_captured": len(coverage_rows),
            "page_count": len(all_pages),
            "observation_occurrence_count": len(all_observations),
            "in_scope_occurrence_count": len(all_observations) - len(excluded),
            "excluded_occurrence_count": len(excluded),
            "all_partitions_response_complete": len(coverage_rows) == len(expected_partitions()) and all(
                row["response_complete"] for row in coverage_rows
            ),
            "partitions": coverage_rows,
        }
        (staging / "api_year_meet_coverage.json").write_text(
            json.dumps(coverage_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        write_readme(staging / "README.md")

        code_hash = sha256_file(Path(__file__).resolve())
        output_files = [
            "README.md", "api_observations.parquet", "api_exclusions.parquet",
            "api_page_ledger.parquet", "api_year_meet_coverage.json",
        ]
        artifact_hashes = {name: sha256_file(staging / name) for name in output_files}
        raw_pages = [row["raw_page_path"] for row in all_pages]
        raw_hash_manifest = [
            {
                "path": row["raw_page_path"],
                "sha256": row["response_body_sha256"],
                "bytes": row["response_body_bytes"],
                "requested_year": row["requested_year"],
                "requested_meet": row["requested_meet"],
                "page_no": row["reported_page_no"],
                "captured_at_utc": row["retrieved_at_utc"],
            }
            for row in all_pages
        ]
        (staging / "raw_page_sha256_manifest.json").write_text(
            json.dumps(raw_hash_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        artifact_hashes["raw_page_sha256_manifest.json"] = sha256_file(
            staging / "raw_page_sha256_manifest.json"
        )
        manifest = {
            "status": "complete" if coverage_doc["all_partitions_response_complete"] else "incomplete",
            "dataset": "KRA API303 corner_rank",
            "endpoint": ENDPOINT,
            "operation": OPERATION,
            "base_url": BASE_URL,
            "capture_id": capture_id,
            "capture_cohort": "current_annual",
            "capture_started_at_utc": capture_started_at_utc,
            "capture_finished_at_utc": coverage_doc["capture_finished_at_utc"],
            "scope": {
                "start_date": START_DATE.isoformat(),
                "cutoff_date_inclusive": CUTOFF_DATE.isoformat(),
                "meets": {"1": "서울", "3": "부산/부경", "4": "영천 (2026 only)"},
                "partitions": len(expected_partitions()),
            },
            "request": {
                "parameters": {"rc_year": "requested year", "meet": "requested meet", "_type": "json", "pageNo": "all pages", "numOfRows": PAGE_SIZE},
                "minimum_interval_seconds": minimum_interval,
                "credential_in_source_files": False,
                "credential_in_logs": False,
            },
            "counts": {
                "page_count": len(all_pages),
                "observation_occurrences": len(all_observations),
                "in_scope_occurrences": coverage_doc["in_scope_occurrence_count"],
                "excluded_occurrences": len(excluded),
                "complete_partitions": sum(bool(row["response_complete"]) for row in coverage_rows),
            },
            "parquet_schemas": {
                "api_observations.parquet": str(OBSERVATION_SCHEMA),
                "api_exclusions.parquet": str(OBSERVATION_SCHEMA),
                "api_page_ledger.parquet": str(PAGE_SCHEMA),
            },
            "collector_path": str(Path(__file__).resolve().relative_to(ROOT)),
            "collector_sha256": code_hash,
            "artifact_sha256": artifact_hashes,
            "raw_pages": raw_hash_manifest,
            "raw_pages_sha256_manifest_entry_count": len(raw_pages),
        }
        (staging / "source_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        if manifest["status"] != "complete":
            incomplete_name = PACKAGE / f"api_source_incomplete_{capture_id}"
            os.rename(staging, incomplete_name)
            raise RuntimeError(f"API 응답 커버리지 검증 실패; 불완전 캡처는 {incomplete_name.name}에 보존했습니다.")
        os.rename(staging, OUTPUT)
        return OUTPUT
    except Exception:
        # Preserve partial raw responses for audit without putting them in the loader's
        # primary api_source path. The service key is never included in this message.
        if staging.exists():
            marker = staging / "capture_failure.json"
            marker.write_text(json.dumps({
                "capture_id": capture_id,
                "failure_type": "collection_or_validation_error",
                "capture_started_at_utc": capture_started_at_utc,
                "captured_pages_before_failure": len(all_pages),
                "captured_rows_before_failure": len(all_observations),
            }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            preserved = PACKAGE / f"api_source_incomplete_{capture_id}"
            if not preserved.exists():
                os.rename(staging, preserved)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--minimum-request-interval",
        type=float,
        default=MIN_REQUEST_INTERVAL_SECONDS,
        help="Seconds to wait after each page request (minimum 0.5).",
    )
    args = parser.parse_args()
    if args.minimum_request_interval < MIN_REQUEST_INTERVAL_SECONDS:
        parser.error("minimum-request-interval must be at least 0.5 seconds")
    try:
        output = collect_all(args.minimum_request_interval)
    except Exception as exc:
        # Do not print exception messages or request URLs; transport details may contain
        # the credential query parameter in third-party exception representations.
        print(
            json.dumps({"status": "failed", "error_type": type(exc).__name__}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 1
    print(json.dumps({"status": "complete", "output": str(output.relative_to(ROOT))}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
