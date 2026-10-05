"""Archive KRA's official Jeju riding-trial API by year (2003–2025).

This is an immutable-source collector. It stores successful HTTP response bodies
byte-for-byte and never records the data.go.kr service key.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

from horse_racing.collectors.kra_api import KraApiClient, response_body
from horse_racing.config import get_settings


ROOT = Path(__file__).resolve().parent
ATTEMPTS = ROOT / "raw" / "trials"
ENDPOINT = "/API20_1/ridingTestResult_1"
OPERATION = "ridingTestResult_1"
MEET = 2
YEARS = tuple(range(2003, 2026))
SUPPLEMENTAL_YEARS = tuple(range(2000, 2003))
SUPPORTED_YEARS = SUPPLEMENTAL_YEARS + YEARS
PAGE_SIZE = 1000
PORTAL_URL = "https://www.data.go.kr/data/15056974/openapi.do"


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def atomic_replace(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temp_path = Path(stream.name)
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp_path, path)


def atomic_create(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temp_path = Path(stream.name)
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.link(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def create_attempt(year: int) -> tuple[str, Path]:
    parent = ATTEMPTS / str(year) / "attempts"
    parent.mkdir(parents=True, exist_ok=True)
    base = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    attempt_id = base
    suffix = 1
    while True:
        path = parent / attempt_id
        try:
            path.mkdir()
            return attempt_id, path
        except FileExistsError:
            suffix += 1
            attempt_id = f"{base}-{suffix}"


def rows_from(payload: dict) -> list[dict]:
    body = response_body(payload)
    items = body.get("items") or {}
    values = items.get("item") if isinstance(items, dict) else None
    if values is None:
        return []
    if isinstance(values, dict):
        return [values]
    if isinstance(values, list) and all(isinstance(row, dict) for row in values):
        return values
    raise ValueError("Unexpected riding-trial API item structure")


def safe_error_type(exc: Exception) -> str:
    # Exception text can include a request URL. Keep only the class name.
    return type(exc).__name__


def latest_attempt_manifests(year: int) -> list[tuple[Path, dict]]:
    found: list[tuple[Path, dict]] = []
    folder = ATTEMPTS / str(year) / "attempts"
    if not folder.exists():
        return found
    for path in sorted(folder.glob("*/attempt_manifest.json")):
        try:
            found.append((path, json.loads(path.read_text(encoding="utf-8"))))
        except (OSError, json.JSONDecodeError):
            continue
    return found


def completed_attempt(year: int) -> tuple[Path, dict] | None:
    for path, manifest in reversed(latest_attempt_manifests(year)):
        if manifest.get("status") == "completed_api_response":
            return path, manifest
    return None


def refresh_inventory(year_states: dict[str, dict], run_id: str, started_at: str) -> None:
    def rollup(years: tuple[int, ...]) -> dict:
        chosen = [year_states[str(year)] for year in years if str(year) in year_states and year_states[str(year)].get("status") == "completed_api_response"]
        coverages = [state.get("row_coverage") or {} for state in chosen]
        majong_counts: Counter[str] = Counter()
        for coverage in coverages:
            majong_counts.update(coverage.get("raw_majong_value_counts") or {})
        return {
            "years_completed": len(chosen),
            "years_expected": len(years),
            "all_years_completed": len(chosen) == len(years),
            "response_pages": sum(int(state.get("response_page_count") or 0) for state in chosen),
            "upstream_total_count": sum(int(state.get("upstream_total_count") or 0) for state in chosen),
            "upstream_rows_seen": sum(int(state.get("upstream_rows_seen") or 0) for state in chosen),
            "raw_majong_exact_jeju_label_rows": sum(int(coverage.get("raw_majong_exact_jeju_label_rows") or 0) for coverage in coverages),
            "raw_first_train_date": min((coverage["first_train_date"] for coverage in coverages if coverage.get("first_train_date")), default=None),
            "raw_last_train_date": max((coverage["last_train_date"] for coverage in coverages if coverage.get("last_train_date")), default=None),
            "exact_jeju_label_first_train_date": min((coverage["exact_jeju_label_first_train_date"] for coverage in coverages if coverage.get("exact_jeju_label_first_train_date")), default=None),
            "exact_jeju_label_last_train_date": max((coverage["exact_jeju_label_last_train_date"] for coverage in coverages if coverage.get("exact_jeju_label_last_train_date")), default=None),
            "majong_value_counts": dict(sorted(majong_counts.items())),
        }

    inventory = {
        "run_id": run_id,
        "started_at_utc": started_at,
        "updated_at_utc": datetime.now(UTC).isoformat(),
        "source": "KRA OpenAPI 15056974 한국마사회 주행심사 상세결과",
        "endpoint": ENDPOINT,
        "operation": OPERATION,
        "source_host": "apis.data.go.kr",
        "official_definition": {
            "url": PORTAL_URL,
            "portal_declared_fields_include": ["마종", "마번", "주행심사일자", "심사차수", "경주기록"],
            "observed_json_field_for_breed": "majong",
            "breed_code_dictionary_verified": False,
            "note": "공식 포털 설명은 majong/마종 필드의 의미와 응답항목을 명시하지만 enum 코드표는 공개 화면에서 확인되지 않았다. 원문 label 빈도만 보존하며 label을 코드로 단정하지 않는다.",
        },
        "requested_years": list(YEARS),
        "supplemental_probe_years": list(SUPPLEMENTAL_YEARS),
        "year_status": year_states,
        "aggregate_coverage": {
            "requested_years_2003_2025": rollup(YEARS),
            "supplemental_probe_years_2000_2002": rollup(SUPPLEMENTAL_YEARS),
            "combined_years_2000_2025": rollup(SUPPORTED_YEARS),
        },
        "complete_years": sorted(int(y) for y, state in year_states.items() if state.get("status") == "completed_api_response"),
        "failed_years": sorted(int(y) for y, state in year_states.items() if state.get("status") == "failed"),
        "unattempted_years": sorted(set(YEARS) - {int(y) for y in year_states}),
        "service_key_recorded": False,
        "phase2_db_modified": False,
        "operational_db_modified": False,
        "rpt_or_txt_used_as_source": False,
    }
    atomic_replace(ROOT / "collection_inventory.json", json_bytes(inventory))


def summarize_rows(rows: list[dict]) -> dict:
    breed_counts = Counter("(blank)" if row.get("majong") is None or str(row.get("majong")).strip() == "" else str(row.get("majong")) for row in rows)
    dates: list[str] = []
    jeju_dates: list[str] = []
    horse_ids: set[str] = set()
    rows_with_horse_id = 0
    for row in rows:
        raw_date = str(row.get("trainDate") or "").strip()
        digits = re.sub(r"\D", "", raw_date)
        if len(digits) >= 8:
            dates.append(digits[:8])
            if str(row.get("majong") or "").strip() == "제주":
                jeju_dates.append(digits[:8])
        horse_id = str(row.get("hrNo") or "").strip()
        if horse_id:
            rows_with_horse_id += 1
            horse_ids.add(horse_id)
    return {
        "rows_seen": len(rows),
        "raw_majong_value_counts": dict(sorted(breed_counts.items())),
        "raw_majong_exact_jeju_label_rows": breed_counts.get("제주", 0),
        "rows_with_horse_id": rows_with_horse_id,
        "unique_horse_ids": len(horse_ids),
        "distinct_train_dates": len(set(dates)),
        "first_train_date": min(dates) if dates else None,
        "last_train_date": max(dates) if dates else None,
        "exact_jeju_label_first_train_date": min(jeju_dates) if jeju_dates else None,
        "exact_jeju_label_last_train_date": max(jeju_dates) if jeju_dates else None,
        "rows_without_parseable_train_date": len(rows) - len(dates),
        "breed_filter_note": "Exact majong=제주 is reported as an upstream label count only; it is not silently normalized to an official breed code.",
    }


def collect_year(year: int, service_key: str, base_url: str, *, timeout: float) -> tuple[str, Path, dict]:
    attempt_id, attempt_dir = create_attempt(year)
    started = datetime.now(UTC).isoformat()
    pages: list[dict] = []
    all_rows: list[dict] = []
    total_counts: list[int] = []
    source_host = "apis.data.go.kr"
    base_manifest = {
        "attempt_id": attempt_id,
        "year": year,
        "started_at_utc": started,
        "source": "KRA OpenAPI 15056974 한국마사회 주행심사 상세결과",
        "portal_metadata_url": PORTAL_URL,
        "endpoint": ENDPOINT,
        "operation": OPERATION,
        "source_host": source_host,
        "requested_scope": {
            "meet": MEET,
            "tr_year": str(year),
            "public_params": {"meet": MEET, "tr_year": str(year), "_type": "json"},
            "page_size": PAGE_SIZE,
        },
        "service_key_recorded": False,
        "source_page_storage": "source_pages/page_NNNN.json (successful response body bytes unchanged)",
        "existing_attempt_artifacts_overwritten": False,
    }
    manifest_path = attempt_dir / "attempt_manifest.json"
    atomic_create(manifest_path, json_bytes({**base_manifest, "status": "in_progress", "completed_source_pages": []}))

    try:
        with KraApiClient(service_key, base_url=base_url, timeout_seconds=timeout) as client:
            for page_no, fetched in enumerate(client.iter_pages(
                endpoint=ENDPOINT,
                operation=OPERATION,
                public_params={"meet": MEET, "tr_year": str(year), "_type": "json"},
                page_size=PAGE_SIZE,
                service_key_parameter="ServiceKey",
            ), start=1):
                # Refuse to persist any response that echoes the secret.
                encoded_secret = quote(service_key, safe="").encode()
                if service_key.encode() in fetched.body or (encoded_secret != service_key.encode() and encoded_secret in fetched.body):
                    raise RuntimeError("Response body contained a service-key value; refusing to archive it")
                body_path = attempt_dir / "source_pages" / f"page_{page_no:04d}.json"
                atomic_create(body_path, fetched.body)
                batch = rows_from(fetched.payload)
                body = response_body(fetched.payload)
                total_count = int(body.get("totalCount") or 0)
                total_counts.append(total_count)
                page_record = {
                    "page": page_no,
                    "status_code": fetched.status_code,
                    "requested_at_ms": fetched.requested_at_ms,
                    "retrieved_at_ms": fetched.retrieved_at_ms,
                    "response_bytes": len(fetched.body),
                    "response_sha256": hashlib.sha256(fetched.body).hexdigest(),
                    "response_file": body_path.relative_to(attempt_dir).as_posix(),
                    "source_url_without_key": fetched.source_url,
                    "page_num_of_rows": body.get("numOfRows"),
                    "page_total_count": total_count,
                    "response_rows": len(batch),
                }
                pages.append(page_record)
                all_rows.extend(batch)
                atomic_replace(manifest_path, json_bytes({
                    **base_manifest,
                    "status": "in_progress",
                    "updated_at_utc": datetime.now(UTC).isoformat(),
                    "completed_source_pages": pages,
                }))
                time.sleep(0.2)

        unique_totals = sorted(set(total_counts))
        summary = summarize_rows(all_rows)
        expected_total = unique_totals[-1] if unique_totals else 0
        counts_consistent = len(unique_totals) <= 1
        row_count_matches = len(all_rows) == expected_total
        completed = counts_consistent and row_count_matches
        manifest = {
            **base_manifest,
            "status": "completed_api_response" if completed else "incomplete_api_response",
            "completed_at_utc": datetime.now(UTC).isoformat(),
            "response_page_count": len(pages),
            "upstream_total_count": expected_total,
            "upstream_total_count_values_across_pages": unique_totals,
            "upstream_rows_seen": len(all_rows),
            "upstream_total_count_consistent": counts_consistent,
            "upstream_row_count_matches_total": row_count_matches,
            "row_coverage": summary,
            "source_pages": pages,
            "persisted_response_files": [record["response_file"] for record in pages],
        }
        atomic_replace(manifest_path, json_bytes(manifest))
        return attempt_id, attempt_dir, manifest
    except Exception as exc:
        manifest = {
            **base_manifest,
            "status": "failed",
            "failed_at_utc": datetime.now(UTC).isoformat(),
            "completed_source_pages": pages,
            "total_counts_seen": sorted(set(total_counts)),
            "partial_row_coverage": summarize_rows(all_rows),
            "exception_type": safe_error_type(exc),
            "failure_detail": "Request or response validation failed; sensitive exception text was intentionally omitted.",
        }
        atomic_replace(manifest_path, json_bytes(manifest))
        return attempt_id, attempt_dir, manifest


def manifest_state(year: int) -> dict:
    successful = completed_attempt(year)
    if successful:
        path, manifest = successful
        coverage = dict(manifest.get("row_coverage") or {})
        if "exact_jeju_label_first_train_date" not in coverage:
            label_dates: list[str] = []
            for page in manifest.get("source_pages", []):
                response_path = path.parent / page["response_file"]
                raw = response_path.read_bytes()
                if hashlib.sha256(raw).hexdigest() != page.get("response_sha256"):
                    raise RuntimeError(f"SHA-256 mismatch while deriving inventory coverage: {response_path}")
                payload = json.loads(raw)
                for row in rows_from(payload):
                    event_date = re.sub(r"\D", "", str(row.get("trainDate") or ""))[:8]
                    if event_date and str(row.get("majong") or "").strip() == "제주":
                        label_dates.append(event_date)
            coverage["exact_jeju_label_first_train_date"] = min(label_dates) if label_dates else None
            coverage["exact_jeju_label_last_train_date"] = max(label_dates) if label_dates else None
        return {
            "status": manifest["status"],
            "attempt_id": manifest.get("attempt_id"),
            "attempt_manifest": path.relative_to(ROOT).as_posix(),
            "upstream_total_count": manifest.get("upstream_total_count"),
            "upstream_rows_seen": manifest.get("upstream_rows_seen"),
            "response_page_count": manifest.get("response_page_count"),
            "row_coverage": coverage,
        }
    attempts = latest_attempt_manifests(year)
    if attempts:
        path, manifest = attempts[-1]
        return {
            "status": manifest.get("status", "unknown"),
            "attempt_id": manifest.get("attempt_id"),
            "attempt_manifest": path.relative_to(ROOT).as_posix(),
            "completed_pages": len(manifest.get("completed_source_pages", [])),
            "exception_type": manifest.get("exception_type"),
        }
    return {"status": "unattempted"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, action="append", choices=SUPPORTED_YEARS, help="Limit this run to one or more years; repeat as needed.")
    parser.add_argument("--timeout", type=float, default=90.0)
    args = parser.parse_args()

    settings = get_settings()
    secret = settings.data_go_kr_service_key
    if secret is None:
        raise SystemExit("KRA service key unavailable; no network request was made.")
    service_key = secret.get_secret_value()
    selected_years = tuple(args.year or YEARS)
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    started = datetime.now(UTC).isoformat()
    states = {str(year): manifest_state(year) for year in SUPPORTED_YEARS if completed_attempt(year)}
    refresh_inventory(states, run_id, started)
    base_url = settings.kra_api_base_url

    for year in selected_years:
        if completed_attempt(year):
            states[str(year)] = manifest_state(year)
            print(json.dumps({"year": year, "status": "already_complete", "rows": states[str(year)].get("upstream_rows_seen")}, ensure_ascii=False))
            continue
        attempt_id, attempt_dir, manifest = collect_year(year, service_key, base_url, timeout=args.timeout)
        states[str(year)] = manifest_state(year)
        refresh_inventory(states, run_id, started)
        line = {
            "year": year,
            "attempt_id": attempt_id,
            "status": manifest.get("status"),
            "upstream_rows": manifest.get("upstream_rows_seen"),
            "total_count": manifest.get("upstream_total_count"),
            "page_count": manifest.get("response_page_count"),
            "attempt_manifest": str((attempt_dir / "attempt_manifest.json").relative_to(ROOT)),
        }
        print(json.dumps(line, ensure_ascii=False))

    refresh_inventory(states, run_id, started)
    counts = Counter(state.get("status") for state in states.values())
    print(json.dumps({"run_id": run_id, "completed_years": counts.get("completed_api_response", 0),
                      "failed_years": [int(year) for year, state in states.items() if state.get("status") == "failed"],
                      "incomplete_years": [int(year) for year, state in states.items() if state.get("status") == "incomplete_api_response"],
                      "inventory": str((ROOT / "collection_inventory.json"))}, ensure_ascii=False))


if __name__ == "__main__":
    main()
