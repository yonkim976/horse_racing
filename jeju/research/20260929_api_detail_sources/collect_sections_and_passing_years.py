"""Archive 2002-2026 API6_1 and API303 annual responses for Jeju venue."""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, quote_plus

from horse_racing.collectors.kra_api import (
    RACE_DETAIL_SECTION_RECORD_ENDPOINT,
    RACE_DETAIL_SECTION_RECORD_OPERATION,
    RACE_PASSING_SUMMARY_ENDPOINT,
    RACE_PASSING_SUMMARY_OPERATION,
    KraApiClient,
    response_body,
)
from horse_racing.config import get_settings


ROOT = Path(__file__).resolve().parent
START_YEAR = 2002
END_YEAR = 2026
PAGE_SIZE = 1000
DATASETS = [
    {
        "name": "detail_section",
        "endpoint": RACE_DETAIL_SECTION_RECORD_ENDPOINT,
        "operation": RACE_DETAIL_SECTION_RECORD_OPERATION,
        "date_field": "rcDate",
        "description": "Race-level 1F-12F times and passing ranks; no horse id field in representative schema.",
    },
    {
        "name": "passing_corner",
        "endpoint": RACE_PASSING_SUMMARY_ENDPOINT,
        "operation": RACE_PASSING_SUMMARY_OPERATION,
        "date_field": "rcDate",
        "description": "Race-level corner ranks, 3F/4F passing times, and tempo; no horse id field in representative schema.",
    },
]


def extract_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    items = response_body(payload).get("items") or {}
    values = items.get("item") if isinstance(items, dict) else None
    if values is None:
        return []
    if isinstance(values, dict):
        return [values]
    if isinstance(values, list):
        return [row for row in values if isinstance(row, dict)]
    return []


def api_int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def contains_key(body: bytes, key: str) -> bool:
    variants = (
        key.encode("utf-8"),
        quote(key, safe="").encode("utf-8"),
        quote_plus(key, safe="").encode("utf-8"),
    )
    return any(value and value in body for value in variants)


def immutable_write(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    settings = get_settings()
    secret = settings.data_go_kr_service_key
    if secret is None or not secret.get_secret_value().strip():
        print(json.dumps({"status": "credential_unavailable"}))
        return 2
    service_key = secret.get_secret_value()
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    run_root = ROOT / "raw/full_year_sections_passing" / run_id
    run_root.mkdir(parents=True, exist_ok=False)
    run_manifest: dict[str, Any] = {
        "run_id": run_id,
        "source": "KRA official OpenAPI via data.go.kr/B551015",
        "meet": 2,
        "requested_years": [START_YEAR, END_YEAR],
        "page_size_requested": PAGE_SIZE,
        "credential_recorded": False,
        "scope_note": "All rows returned by meet=2; racetrack venue is not horse breed evidence.",
        "datasets": {},
    }
    run_manifest_path = run_root / "run_manifest.json"

    with KraApiClient(
        service_key,
        base_url=settings.kra_api_base_url,
        timeout_seconds=min(settings.http_timeout_seconds, 20.0),
    ) as client:
        for dataset in DATASETS:
            yearly: list[dict[str, Any]] = []
            dataset_root = run_root / dataset["name"]
            dataset_root.mkdir(parents=True, exist_ok=True)
            for year in range(START_YEAR, END_YEAR + 1):
                year_root = dataset_root / str(year)
                year_root.mkdir(parents=True, exist_ok=True)
                public_params = {"meet": 2, "rc_year": str(year), "_type": "json"}
                result: dict[str, Any] = {
                    "year": year,
                    "endpoint": dataset["endpoint"],
                    "operation": dataset["operation"],
                    "public_params": public_params,
                    "status": "running",
                    "pages": [],
                }
                total_rows = 0
                scope_rows = 0
                expected_pages: int | None = None
                total_count: int | None = None
                actual_page_size: int | None = None
                page_no = 1
                try:
                    while True:
                        fetched = client._fetch_json(
                            dataset["endpoint"],
                            dataset["operation"],
                            {
                                **public_params,
                                "pageNo": page_no,
                                "numOfRows": PAGE_SIZE,
                            },
                            service_key_parameter="serviceKey",
                        )
                        if contains_key(fetched.body, service_key):
                            result["status"] = "credential_echo_rejected"
                            break
                        body = response_body(fetched.payload)
                        page_total = api_int(body.get("totalCount"), 0)
                        page_size = api_int(body.get("numOfRows"), PAGE_SIZE)
                        reported_page_no = api_int(body.get("pageNo"), page_no)
                        rows = extract_rows(fetched.payload)
                        row_matches = sum(
                            str(row.get(dataset["date_field"]) or "").startswith(str(year))
                            for row in rows
                        )
                        if total_count is None:
                            total_count = page_total
                            actual_page_size = page_size
                            expected_pages = max(1, math.ceil(total_count / max(page_size, 1)))
                        page_path = year_root / "source_pages" / f"page_{page_no:04d}.json"
                        immutable_write(page_path, fetched.body)
                        total_rows += len(rows)
                        scope_rows += row_matches
                        result["pages"].append({
                            "page_no": page_no,
                            "reported_page_no": reported_page_no,
                            "status_code": fetched.status_code,
                            "content_type": fetched.content_type,
                            "requested_at_ms": fetched.requested_at_ms,
                            "retrieved_at_ms": fetched.retrieved_at_ms,
                            "response_bytes": len(fetched.body),
                            "response_sha256": hashlib.sha256(fetched.body).hexdigest(),
                            "response_file": str(page_path.relative_to(run_root)),
                            "source_url_without_key": fetched.source_url,
                            "api_total_count": page_total,
                            "api_page_size": page_size,
                            "actual_page_rows": len(rows),
                            "rows_matching_requested_year": row_matches,
                            "response_date_examples": sorted({
                                str(row.get(dataset["date_field"]) or "")
                                for row in rows if row.get(dataset["date_field"]) is not None
                            })[:5],
                        })
                        if page_total != total_count or page_size != actual_page_size or reported_page_no != page_no:
                            result["status"] = "pagination_metadata_mismatch"
                            break
                        if page_no >= (expected_pages or 1):
                            break
                        page_no += 1
                        time.sleep(0.35)

                    result.update({
                        "api_total_count": total_count,
                        "api_page_size": actual_page_size,
                        "expected_page_count": expected_pages,
                        "actual_page_count": len(result["pages"]),
                        "actual_total_rows": total_rows,
                        "rows_matching_requested_year": scope_rows,
                        "row_date_field": dataset["date_field"],
                    })
                    if result["status"] == "running":
                        if total_count == 0 and total_rows == 0:
                            result["status"] = "query_complete_zero_rows"
                            result["positive_data_evidence"] = False
                        elif (
                            total_count == total_rows
                            and total_rows == scope_rows
                            and len(result["pages"]) == expected_pages
                        ):
                            result["status"] = "complete_year_partition"
                            result["positive_data_evidence"] = True
                        else:
                            result["status"] = "incomplete_or_year_scope_mismatch"
                            result["positive_data_evidence"] = bool(total_rows)
                except Exception as exc:
                    result["status"] = "request_failed"
                    result["exception_type"] = type(exc).__name__
                year_manifest = {
                    "run_id": run_id,
                    "source": "KRA official API response bytes",
                    "credential_recorded": False,
                    **result,
                }
                (year_root / "year_manifest.json").write_text(
                    json.dumps(year_manifest, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                yearly.append(result)
                run_manifest["datasets"][dataset["name"]] = {
                    "endpoint": dataset["endpoint"],
                    "operation": dataset["operation"],
                    "description": dataset["description"],
                    "yearly": yearly,
                }
                run_manifest_path.write_text(
                    json.dumps(run_manifest, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                time.sleep(0.35)

    count_status = {
        name: {
            "years_complete": sum(row["status"] in {"complete_year_partition", "query_complete_zero_rows"} for row in info["yearly"]),
            "years_positive": sum(bool(row.get("positive_data_evidence")) for row in info["yearly"]),
            "rows": sum(int(row.get("actual_total_rows") or 0) for row in info["yearly"]),
            "pages": sum(int(row.get("actual_page_count") or 0) for row in info["yearly"]),
            "failed_or_incomplete_years": [row["year"] for row in info["yearly"] if row["status"] not in {"complete_year_partition", "query_complete_zero_rows"}],
        }
        for name, info in run_manifest["datasets"].items()
    }
    run_manifest["summary"] = count_status
    run_manifest_path.write_text(json.dumps(run_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    all_complete = all(value["years_complete"] == END_YEAR - START_YEAR + 1 for value in count_status.values())
    print(json.dumps({"run_id": run_id, "summary": count_status, "manifest": str(run_manifest_path)}, ensure_ascii=False))
    return 0 if all_complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
