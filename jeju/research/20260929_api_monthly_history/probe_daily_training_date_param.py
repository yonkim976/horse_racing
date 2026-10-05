"""Bounded API18_1 tr_date filter probe for the failed 2015-06 monthly partition.

This diagnostic stores complete raw pages for two exact dates and records all
attempts in the monthly history ledger without persisting credentials.
"""

from __future__ import annotations

import json
import math
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from horse_racing.collectors.kra_api import (
    DAILY_TRAINING_ENDPOINT,
    DAILY_TRAINING_OPERATION,
    KraApiClient,
    KraApiTransientError,
    response_body,
)
from horse_racing.config import get_settings

from collect_monthly_history import (
    BACKOFF_BASE_SECONDS,
    MAX_TRANSIENT_RETRIES,
    MAX_NEW_REQUESTS_DEFAULT,
    ROOT,
    atomic_immutable_write,
    atomic_json_write,
    contains_secret,
    digest,
    error_metadata,
    response_rows,
    quota_signal,
)


LEDGER_PATH = ROOT / "ledger.json"
DATES = ("20150615", "20150630")
PAGE_SIZE = 1000
PACE_SECONDS = 0.35


def load_ledger() -> dict[str, Any]:
    return json.loads(LEDGER_PATH.read_text(encoding="utf-8"))


def persist(ledger: dict[str, Any], run_path: Path, run: dict[str, Any]) -> None:
    ledger["updated_at_utc"] = datetime.now(UTC).isoformat()
    atomic_json_write(LEDGER_PATH, ledger)
    atomic_json_write(run_path, run)


def main() -> int:
    settings = get_settings()
    secret = settings.data_go_kr_service_key
    if secret is None or not secret.get_secret_value().strip():
        print(json.dumps({"status": "credential_unavailable", "credential_recorded": False}))
        return 2
    service_key = secret.get_secret_value()
    started = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    run_path = ROOT / "runs" / f"{started}_tr_date_probe.json"
    run: dict[str, Any] = {
        "run_id": started,
        "probe": "API18_1 tr_date exact-date parameter",
        "source": "KRA official API response pages",
        "credential_recorded": False,
        "requested_dates": list(DATES),
        "page_size": PAGE_SIZE,
        "transient_retry_limit_per_page": MAX_TRANSIENT_RETRIES,
        "transient_backoff_seconds": [1, 2, 4],
        "dates": {},
        "request_attempts": 0,
        "status": "running",
        "quota_or_error": None,
    }
    ledger = load_ledger()
    ledger.setdefault("date_param_probes", []).append({
        "run_id": started,
        "status": "running",
        "manifest": str(run_path.relative_to(ROOT)),
        "parameter": "tr_date",
        "dates": list(DATES),
    })
    probe_record = ledger["date_param_probes"][-1]
    persist(ledger, run_path, run)
    kst_date = datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()
    should_stop = False
    with KraApiClient(
        service_key,
        base_url=settings.kra_api_base_url,
        timeout_seconds=min(settings.http_timeout_seconds, 20.0),
    ) as client:
        for date_value in DATES:
            date_record: dict[str, Any] = {
                "date": date_value,
                "public_params": {"meet": 2, "tr_date": date_value, "_type": "json"},
                "page_size": PAGE_SIZE,
                "pages": [],
                "request_errors": [],
                "transient_retry_events": [],
                "status": "running",
            }
            run["dates"][date_value] = date_record
            persist(ledger, run_path, run)
            page_no = 1
            expected_page_count: int | None = None
            total_count: int | None = None
            validation_errors: list[str] = []
            while expected_page_count is None or page_no <= expected_page_count:
                retries = 0
                while True:
                    current_attempts = int(ledger["request_attempts_by_kst_date"].get(kst_date, 0))
                    if current_attempts >= MAX_NEW_REQUESTS_DEFAULT:
                        date_record["status"] = "request_budget_checkpoint"
                        run["status"] = "request_budget_checkpoint"
                        should_stop = True
                        break
                    params = {
                        "meet": 2,
                        "tr_date": date_value,
                        "_type": "json",
                        "pageNo": page_no,
                        "numOfRows": PAGE_SIZE,
                    }
                    run["request_attempts"] += 1
                    ledger["request_attempts_by_this_collector"] = int(ledger.get("request_attempts_by_this_collector", 0)) + 1
                    ledger["request_attempts_by_kst_date"][kst_date] = current_attempts + 1
                    request_started_ms = int(time.time() * 1000)
                    persist(ledger, run_path, run)
                    try:
                        fetched = client._fetch_json.__wrapped__(
                            client,
                            DAILY_TRAINING_ENDPOINT,
                            DAILY_TRAINING_OPERATION,
                            params,
                            service_key_parameter="serviceKey",
                        )
                    except Exception as exc:
                        error = error_metadata(exc, service_key)
                        attempt = {
                            "page_no": page_no,
                            "attempt_number": len([x for x in date_record["request_errors"] if x["page_no"] == page_no]) + 1,
                            "request_started_at_ms": request_started_ms,
                            **error,
                        }
                        date_record["request_errors"].append(attempt)
                        run["quota_or_error"] = error
                        if quota_signal(exc):
                            date_record["status"] = "quota_stopped"
                            run["status"] = "quota_stopped"
                            should_stop = True
                            persist(ledger, run_path, run)
                            break
                        if isinstance(exc, KraApiTransientError) and retries < MAX_TRANSIENT_RETRIES:
                            delay = BACKOFF_BASE_SECONDS * (2**retries)
                            retries += 1
                            date_record["transient_retry_events"].append({
                                "page_no": page_no,
                                "retry_number": retries,
                                "attempt_number": attempt["attempt_number"],
                                "backoff_seconds": delay,
                                "classification": error["classification"],
                            })
                            persist(ledger, run_path, run)
                            time.sleep(delay)
                            continue
                        date_record["status"] = "request_failed"
                        run["status"] = "date_request_failed"
                        should_stop = True
                        persist(ledger, run_path, run)
                        break
                    if contains_secret(fetched.body, service_key):
                        date_record["status"] = "credential_echo_rejected"
                        run["status"] = "credential_echo_rejected"
                        should_stop = True
                        persist(ledger, run_path, run)
                        break
                    body = response_body(fetched.payload)
                    try:
                        page_total = int(body.get("totalCount") or 0)
                    except (TypeError, ValueError):
                        page_total = -1
                    rows = response_rows(fetched.payload)
                    if page_total < 0:
                        validation_errors.append("invalid_totalCount")
                        date_record["status"] = "invalid_totalCount"
                        run["status"] = "validation_failed"
                        should_stop = True
                        persist(ledger, run_path, run)
                        break
                    if total_count is None:
                        total_count = page_total
                        expected_page_count = max(1, math.ceil(total_count / PAGE_SIZE))
                    elif page_total != total_count:
                        validation_errors.append("totalCount_changed_between_pages")
                    requested_rows = min(PAGE_SIZE, max(0, total_count - (page_no - 1) * PAGE_SIZE))
                    if len(rows) != requested_rows:
                        validation_errors.append("page_row_count_mismatch")
                    response_page_no = body.get("pageNo")
                    response_page_size = body.get("numOfRows")
                    if response_page_no is not None and int(response_page_no) != page_no:
                        validation_errors.append("pageNo_mismatch")
                    if response_page_size is not None and int(response_page_size) != PAGE_SIZE:
                        validation_errors.append("numOfRows_mismatch")
                    row_dates = [str(row.get("trDate") or "").replace("-", "")[:8] for row in rows]
                    if any(value != date_value for value in row_dates):
                        validation_errors.append("trDate_not_exactly_requested_date")
                    relative = Path("raw") / "date_probes" / date_value / started / f"page_{page_no:04d}.json"
                    atomic_immutable_write(ROOT / relative, fetched.body)
                    date_record["pages"].append({
                        "page_no": page_no,
                        "status_code": fetched.status_code,
                        "content_type": fetched.content_type,
                        "request_started_at_ms": request_started_ms,
                        "requested_at_ms": fetched.requested_at_ms,
                        "retrieved_at_ms": fetched.retrieved_at_ms,
                        "source_url_without_key": fetched.source_url,
                        "public_params": {"meet": 2, "tr_date": date_value, "_type": "json"},
                        "requested_page_size": PAGE_SIZE,
                        "api_total_count": page_total,
                        "api_page_no": response_page_no,
                        "api_page_size": response_page_size,
                        "actual_page_rows": len(rows),
                        "row_date_min": min(row_dates) if row_dates else None,
                        "row_date_max": max(row_dates) if row_dates else None,
                        "response_bytes": len(fetched.body),
                        "response_sha256": digest(fetched.body),
                        "response_file": str(relative),
                    })
                    persist(ledger, run_path, run)
                    break
                if should_stop or validation_errors:
                    break
                if expected_page_count is not None and page_no >= expected_page_count:
                    break
                page_no += 1
                time.sleep(PACE_SECONDS)
            if should_stop:
                break
            page_rows = [int(p["actual_page_rows"]) for p in date_record["pages"]]
            actual_total = sum(page_rows)
            date_record.update({
                "api_total_count": total_count,
                "expected_page_count": expected_page_count,
                "actual_page_count": len(date_record["pages"]),
                "actual_total_rows": actual_total,
                "exact_date_rows": sum(
                    int(p["actual_page_rows"])
                    for p in date_record["pages"]
                    if p.get("row_date_min") == date_value and p.get("row_date_max") == date_value
                ),
                "validation_errors": validation_errors,
                "status": "validated_exact_date" if actual_total > 0 and actual_total == total_count and not validation_errors else "empty_or_unverified",
            })
            time.sleep(PACE_SECONDS)
    if run["status"] == "running":
        run["status"] = "probe_complete"
    run["finished_at_utc"] = datetime.now(UTC).isoformat()
    probe_record["status"] = run["status"]
    probe_record["results"] = {
        date_value: {
            "status": date_record["status"],
            "api_total_count": date_record.get("api_total_count"),
            "actual_total_rows": date_record.get("actual_total_rows"),
            "actual_page_count": date_record.get("actual_page_count"),
            "date_range": [
                min((p["row_date_min"] for p in date_record.get("pages", []) if p.get("row_date_min")), default=None),
                max((p["row_date_max"] for p in date_record.get("pages", []) if p.get("row_date_max")), default=None),
            ],
            "validation_errors": date_record.get("validation_errors", []),
        }
        for date_value, date_record in run["dates"].items()
    }
    persist(ledger, run_path, run)
    print(json.dumps({
        "run_id": started,
        "status": run["status"],
        "request_attempts": run["request_attempts"],
        "results": probe_record["results"],
        "credential_recorded": False,
        "run_manifest": str(run_path),
    }, ensure_ascii=False))
    return 0 if run["status"] == "probe_complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
