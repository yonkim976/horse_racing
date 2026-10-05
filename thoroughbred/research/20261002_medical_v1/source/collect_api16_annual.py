"""Capture paginated, year-scoped KRA API16 observations for research."""

from __future__ import annotations

import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from source_common import OBSERVATION_SCHEMA, ParquetRowWriter, iso_day, row_locator_hash, sha256_bytes, text_value


REPO = Path(__file__).resolve().parents[4]
OUT = REPO / "thoroughbred/research/20261002_medical_v1/source"
API_URL = "https://apis.data.go.kr/B551015/API16_1/raceHorseClinic_1"
START_DATE = "2010-01-01"
END_DATE = "2026-09-29"
MEET_NAMES = {1: {"서울"}, 3: {"영남", "부산경남", "부경"}}


def unpack_items(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    envelope = payload.get("response", payload)
    if not isinstance(envelope, dict):
        raise ValueError("API16 response envelope is not an object")
    header = envelope.get("header")
    body = envelope.get("body")
    if not isinstance(header, dict) or not isinstance(body, dict):
        raise ValueError("API16 response lacks a header or body object")
    container = body.get("items")
    raw_rows = container.get("item", []) if isinstance(container, dict) else []
    if raw_rows is None:
        rows: list[dict[str, Any]] = []
    elif isinstance(raw_rows, dict):
        rows = [raw_rows]
    elif isinstance(raw_rows, list) and all(isinstance(row, dict) for row in raw_rows):
        rows = raw_rows
    else:
        raise ValueError("API16 item container has an unsupported shape")
    return header, body, rows


def safe_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    if rows:
        table = pa.Table.from_pylist(rows)
    else:
        table = pa.table({"empty_result": pa.array([], type=pa.string())})
    pq.write_table(table, path, compression="zstd")


def main() -> None:
    sys.path.insert(0, str(REPO / "src"))
    from horse_racing.collectors.kra_api import (
        RACE_HORSE_CLINIC_ENDPOINT,
        RACE_HORSE_CLINIC_OPERATION,
        KraApiClient,
        response_body,
    )
    from horse_racing.config import get_settings

    settings = get_settings()
    secret = settings.data_go_kr_service_key
    if secret is None or not secret.get_secret_value().strip():
        raise RuntimeError("KRA API credential is not configured")

    capture_started = datetime.now(UTC)
    capture_id = capture_started.strftime("%Y%m%dT%H%M%SZ")
    capture_root = OUT / "raw/api16" / capture_id
    capture_root.mkdir(parents=True, exist_ok=False)
    page_ledger: list[dict[str, Any]] = []
    coverage_rows: list[dict[str, Any]] = []
    exclusion_rows: list[dict[str, Any]] = []

    with ParquetRowWriter(OUT / "api16_current_annual_observations.parquet", OBSERVATION_SCHEMA) as observations:
        with KraApiClient(secret.get_secret_value(), timeout_seconds=90) as client:
            for year in range(2010, 2027):
                for meet in (1, 3):
                    expected_total: int | None = None
                    response_rows_seen = 0
                    normalized_rows = 0
                    returned_dates: list[str] = []
                    this_pages: list[dict[str, Any]] = []
                    page_no = 1
                    while True:
                        fetched = client._fetch_json(
                            RACE_HORSE_CLINIC_ENDPOINT,
                            RACE_HORSE_CLINIC_OPERATION,
                            {"meet": meet, "clinic_year": str(year), "_type": "json",
                             "pageNo": page_no, "numOfRows": 20_000},
                            service_key_parameter="ServiceKey",
                        )
                        header, body, items = unpack_items(fetched.payload)
                        result_code = str(header.get("resultCode", ""))
                        if result_code not in {"00", "0000"}:
                            raise RuntimeError(f"API16 unsuccessful page for {year}/{meet}/{page_no}")
                        actual_page = int(body.get("pageNo") or page_no)
                        if actual_page != page_no:
                            raise RuntimeError(f"API16 page number mismatch for {year}/{meet}/{page_no}")
                        total_count = int(body.get("totalCount") or 0)
                        page_size = int(body.get("numOfRows") or 20_000)
                        if expected_total is None:
                            expected_total = total_count
                        elif expected_total != total_count:
                            raise RuntimeError(f"API16 totalCount changed across pages for {year}/{meet}")

                        page_rel = Path("raw/api16") / capture_id / f"meet_{meet}" / str(year) / f"page_{page_no:04d}.json"
                        page_path = OUT / page_rel
                        page_path.parent.mkdir(parents=True, exist_ok=True)
                        page_path.write_bytes(fetched.body)
                        page_hash = sha256_bytes(fetched.body)
                        fetched_at = datetime.fromtimestamp(fetched.retrieved_at_ms / 1000, UTC).isoformat(timespec="milliseconds")
                        ledger_entry = {
                            "source_kind": "api16",
                            "source_cohort": "current_annual",
                            "capture_id": capture_id,
                            "source_url": API_URL,
                            "source_path": page_path.relative_to(REPO).as_posix(),
                            "source_sha256": page_hash,
                            "source_bytes": len(fetched.body),
                            "source_captured_at_utc": fetched_at,
                            "capture_timestamp_basis": "KraApiClient.retrieved_at_ms",
                            "request_year": year,
                            "request_meet": meet,
                            "requested_page_no": page_no,
                            "returned_page_no": actual_page,
                            "requested_page_size": 20_000,
                            "returned_page_size": page_size,
                            "reported_total_count": total_count,
                            "response_row_count": len(items),
                            "response_result_code": result_code,
                            "response_result_message": str(header.get("resultMsg", "")),
                            "http_status": fetched.status_code,
                        }
                        page_ledger.append(ledger_entry)
                        this_pages.append(ledger_entry)

                        for row_no, raw_row in enumerate(items, 1):
                            event_date = iso_day(raw_row.get("clinicDate"))
                            meet_raw = text_value(raw_row.get("meet"))
                            if event_date is None or event_date[:4] != str(year):
                                raise ValueError(f"API16 clinic_year filter mismatch for {year}/{meet}/{page_no}")
                            if meet_raw not in MEET_NAMES[meet]:
                                raise ValueError(f"API16 meet filter mismatch for {year}/{meet}: {meet_raw!r}")
                            returned_dates.append(event_date)
                            source_path = page_path.relative_to(REPO).as_posix()
                            if not START_DATE <= event_date <= END_DATE:
                                exclusion_rows.append({
                                    "source_kind": "api16", "source_cohort": "current_annual",
                                    "reason": "event_date_outside_research_cutoff",
                                    "event_date": event_date, "request_year": year, "request_meet": meet,
                                    "source_path": source_path, "source_sha256": page_hash,
                                    "capture_id": capture_id, "page_no": page_no, "row_no": row_no,
                                    "raw_payload_json": json.dumps(raw_row, ensure_ascii=False, separators=(",", ":")),
                                })
                                continue
                            observations.append({
                                "source_kind": "api16", "source_cohort": "current_annual",
                                "event_date": event_date, "source_file_date": None,
                                "meet_code": meet, "meet_raw": meet_raw,
                                "horse_name_raw": text_value(raw_row.get("hrName")),
                                "hr_no_raw": text_value(raw_row.get("hrNo")),
                                "stable_no_raw": None,
                                "part_raw": text_value(raw_row.get("part")),
                                "hospital_name_raw": text_value(raw_row.get("hospiName")),
                                "ill_name1_raw": text_value(raw_row.get("illName1")),
                                "ill_name2_raw": text_value(raw_row.get("illName2")),
                                "diagnosis_rpt_raw": None,
                                "raw_payload_json": json.dumps(raw_row, ensure_ascii=False, separators=(",", ":")),
                                "raw_line": None, "decode_has_replacement": None,
                                "source_path": source_path, "source_sha256": page_hash,
                                "capture_id": capture_id, "source_captured_at_utc": fetched_at,
                                "capture_timestamp_basis": "KraApiClient.retrieved_at_ms",
                                "page_no": page_no, "row_no": row_no, "line_no": None,
                                "request_year": year, "request_meet": meet,
                                "response_result_code": result_code,
                                "response_result_message": str(header.get("resultMsg", "")),
                                "source_row_hash": row_locator_hash("api16", source_path,
                                    page_no=page_no, row_no=row_no),
                            })
                            normalized_rows += 1
                        response_rows_seen += len(items)
                        if page_no >= max(1, (total_count + max(1, page_size) - 1) // max(1, page_size)):
                            break
                        if not items:
                            raise RuntimeError(f"API16 empty intermediate page for {year}/{meet}/{page_no}")
                        page_no += 1
                        time.sleep(0.2)
                    if response_rows_seen != (expected_total or 0):
                        raise RuntimeError(f"API16 pagination incomplete for {year}/{meet}: {response_rows_seen}/{expected_total}")
                    coverage_rows.append({
                        "source_kind": "api16", "source_cohort": "current_annual",
                        "source_url": API_URL, "capture_id": capture_id,
                        "request_year": year, "request_meet": meet,
                        "reported_total_count": expected_total or 0,
                        "collected_response_row_count": response_rows_seen,
                        "normalized_in_scope_row_count": normalized_rows,
                        "page_count": len(this_pages),
                        "successful_empty_response": (expected_total or 0) == 0,
                        "pagination_complete": True,
                        "returned_date_min": min(returned_dates) if returned_dates else None,
                        "returned_date_max": max(returned_dates) if returned_dates else None,
                        "scope_start_date": START_DATE, "scope_end_date": END_DATE,
                        "historical_completeness": "API pagination complete; provider historical completeness unverified",
                    })
                    print(json.dumps({"year": year, "meet": meet,
                                      "total": expected_total or 0, "pages": len(this_pages),
                                      "in_scope": normalized_rows}, ensure_ascii=False), flush=True)

    write_rows(OUT / "api16_page_ledger.parquet", page_ledger)
    write_rows(OUT / "api16_year_meet_coverage.parquet", coverage_rows)
    write_rows(OUT / "api16_current_annual_exclusions.parquet", exclusion_rows)
    manifest = {
        "source_kind": "api16", "source_cohort": "current_annual", "capture_id": capture_id,
        "source_url": API_URL, "started_at_utc": capture_started.isoformat(timespec="seconds"),
        "completed_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "credential_value_stored": False,
        "requested_years": [2010, 2026], "requested_meets": [1, 3],
        "page_count": len(page_ledger), "year_meet_query_count": len(coverage_rows),
        "response_row_count": sum(int(p["response_row_count"]) for p in page_ledger),
        "normalized_in_scope_row_count": sum(int(r["normalized_in_scope_row_count"]) for r in coverage_rows),
        "successful_empty_year_meet_response_count": sum(bool(r["successful_empty_response"]) for r in coverage_rows),
        "exclusion_row_count": len(exclusion_rows),
        "raw_capture_root": capture_root.relative_to(REPO).as_posix(),
        "pages": page_ledger,
        "coverage_rows": coverage_rows,
    }
    safe_json(OUT / "api16_current_annual_capture_manifest.json", manifest)
    print(json.dumps({"capture_id": capture_id, "api_pages": len(page_ledger),
                      "year_meet_queries": len(coverage_rows),
                      "observations": sum(int(r["normalized_in_scope_row_count"]) for r in coverage_rows)},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
