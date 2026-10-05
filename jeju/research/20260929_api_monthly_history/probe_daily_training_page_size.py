"""Probe whether API18_1 accepts numOfRows=20000 for the 2016-09 partition."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from horse_racing.collectors.kra_api import (
    DAILY_TRAINING_ENDPOINT,
    DAILY_TRAINING_OPERATION,
    KraApiClient,
    KraApiRateLimitError,
    KraApiTransientError,
)
from horse_racing.config import get_settings

from collect_monthly_history import (
    BACKOFF_BASE_SECONDS,
    MAX_NEW_REQUESTS_DEFAULT,
    MAX_TRANSIENT_RETRIES,
    ROOT,
    atomic_immutable_write,
    atomic_json_write,
    contains_secret,
    date_values,
    digest,
    error_metadata,
    load_ledger,
    normalized_date,
    response_body,
    response_rows,
)


MONTH = "201609"
PROBE_PAGE_SIZE = 20_000
EXPECTED_SAMPLE_TOTAL = 5_357


def main() -> int:
    settings = get_settings()
    secret = settings.data_go_kr_service_key
    if secret is None or not secret.get_secret_value().strip():
        print(json.dumps({"status": "credential_unavailable", "credential_recorded": False}))
        return 2
    service_key = secret.get_secret_value()
    ledger = load_ledger()
    started = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    kst_date = datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()
    run_path = ROOT / "runs" / f"{started}_page_size_probe.json"
    run: dict[str, object] = {
        "run_id": started,
        "kst_date": kst_date,
        "kind": "API18_1_numOfRows_probe",
        "status": "running",
        "credential_recorded": False,
        "public_params": {"meet": 2, "tr_month": MONTH, "_type": "json"},
        "page_no": 1,
        "requested_num_of_rows": PROBE_PAGE_SIZE,
        "request_attempts": 0,
        "transient_retry_limit": MAX_TRANSIENT_RETRIES,
        "backoff_seconds": [1, 2, 4],
        "quota_signal": False,
    }
    run_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_run = {"run_id": started, "status": "running_page_size_probe", "manifest": str(run_path.relative_to(ROOT))}
    ledger["runs"].append(ledger_run)
    atomic_json_write(ROOT / "ledger.json", ledger)
    atomic_json_write(run_path, run)

    final_status = "probe_failed"
    with KraApiClient(
        service_key,
        base_url=settings.kra_api_base_url,
        timeout_seconds=min(settings.http_timeout_seconds, 30.0),
    ) as client:
        retry_count = 0
        request_errors: list[dict[str, str | int]] = []
        while True:
            attempts_today = int(ledger["request_attempts_by_kst_date"].get(kst_date, 0))
            if attempts_today >= MAX_NEW_REQUESTS_DEFAULT:
                final_status = "request_budget_checkpoint"
                run["request_budget_reached"] = True
                break
            run["request_attempts"] = int(run["request_attempts"]) + 1
            ledger["request_attempts_by_this_collector"] = int(ledger.get("request_attempts_by_this_collector", 0)) + 1
            ledger["request_attempts_by_kst_date"][kst_date] = attempts_today + 1
            request_started_ms = int(time.time() * 1000)
            atomic_json_write(ROOT / "ledger.json", ledger)
            atomic_json_write(run_path, run)
            try:
                fetched = client._fetch_json.__wrapped__(
                    client,
                    DAILY_TRAINING_ENDPOINT,
                    DAILY_TRAINING_OPERATION,
                    {
                        "meet": 2,
                        "tr_month": MONTH,
                        "_type": "json",
                        "pageNo": 1,
                        "numOfRows": PROBE_PAGE_SIZE,
                    },
                    service_key_parameter="serviceKey",
                )
            except Exception as exc:
                error = error_metadata(exc, service_key)
                request_errors.append({"attempt_number": int(run["request_attempts"]), "request_started_at_ms": request_started_ms, **error})
                run["request_errors"] = request_errors
                if isinstance(exc, KraApiRateLimitError) or error["quota_signal"] == "true":
                    final_status = "quota_stopped"
                    run["quota_signal"] = True
                    run["last_error"] = error
                    break
                if isinstance(exc, KraApiTransientError) and retry_count < MAX_TRANSIENT_RETRIES:
                    delay = BACKOFF_BASE_SECONDS * (2 ** retry_count)
                    retry_count += 1
                    run.setdefault("retry_events", []).append({
                        "retry_number": retry_count,
                        "backoff_seconds": delay,
                        "classification": error["classification"],
                    })
                    atomic_json_write(ROOT / "ledger.json", ledger)
                    atomic_json_write(run_path, run)
                    time.sleep(delay)
                    continue
                run["last_error"] = error
                break

            if contains_secret(fetched.body, service_key):
                final_status = "credential_echo_rejected"
                run["credential_echo_rejected"] = True
                break
            body = response_body(fetched.payload)
            total_count = int(body.get("totalCount") or 0)
            page_no = int(body.get("pageNo") or 1)
            effective_page_size = int(body.get("numOfRows") or 0)
            rows = response_rows(fetched.payload)
            row_dates = date_values(rows, "trDate")
            month_matches = sum(normalized_date(row.get("trDate")).startswith(MONTH) for row in rows)
            relative = Path("raw_probes") / "daily_training" / MONTH / started / f"page_0001_numOfRows_{PROBE_PAGE_SIZE}.json"
            atomic_immutable_write(ROOT / relative, fetched.body)
            raw_sha = digest(fetched.body)
            probe = {
                "status_code": fetched.status_code,
                "content_type": fetched.content_type,
                "requested_at_ms": fetched.requested_at_ms,
                "retrieved_at_ms": fetched.retrieved_at_ms,
                "request_started_at_ms": request_started_ms,
                "request_attempt_number": int(run["request_attempts"]),
                "source_url_without_key": fetched.source_url,
                "public_params": {"meet": 2, "tr_month": MONTH, "_type": "json"},
                "page_no": page_no,
                "api_page_size": effective_page_size,
                "requested_num_of_rows": PROBE_PAGE_SIZE,
                "api_total_count": total_count,
                "actual_rows": len(rows),
                "row_date_field": "trDate",
                "row_date_min": min(row_dates) if row_dates else None,
                "row_date_max": max(row_dates) if row_dates else None,
                "rows_matching_requested_month": month_matches,
                "response_bytes": len(fetched.body),
                "response_sha256": raw_sha,
                "response_file": str(relative),
                "credential_recorded": False,
                "credential_echo_rejected": False,
                "matches_prior_1000_rows_sample_total": total_count == EXPECTED_SAMPLE_TOTAL,
            }
            complete = (
                total_count > 0
                and len(rows) == total_count
                and page_no == 1
                and effective_page_size == PROBE_PAGE_SIZE
                and month_matches == len(rows)
                and total_count == EXPECTED_SAMPLE_TOTAL
            )
            final_status = "probe_complete_20000_accepted" if complete else "probe_incomplete_or_capped"
            if complete:
                ledger.setdefault("default_page_size_by_dataset", {})["daily_training"] = PROBE_PAGE_SIZE
            run["probe_result"] = probe
            run["status"] = final_status
            run["complete_positive_probe"] = complete
            break

    run["status"] = final_status
    run["finished_at_utc"] = datetime.now(UTC).isoformat()
    run["request_errors"] = request_errors if "request_errors" in locals() else []
    run["request_attempts_by_this_collector_total"] = ledger["request_attempts_by_this_collector"]
    run["request_attempts_kst_date_total"] = ledger["request_attempts_by_kst_date"].get(kst_date, 0)
    ledger_run["status"] = final_status
    ledger_run["request_attempts"] = run["request_attempts"]
    ledger_run["probe_partition"] = f"daily_training:{MONTH}"
    ledger["page_size_probe"] = run.get("probe_result", {"status": final_status, "request_errors": run.get("request_errors", [])})
    atomic_json_write(ROOT / "ledger.json", ledger)
    atomic_json_write(run_path, run)
    print(json.dumps({
        "run_id": started,
        "status": final_status,
        "request_attempts": run["request_attempts"],
        "probe_result": run.get("probe_result"),
        "ledger": str(ROOT / "ledger.json"),
        "run_manifest": str(run_path),
        "credential_recorded": False,
    }, ensure_ascii=False))
    return 0 if final_status == "probe_complete_20000_accepted" else 1


if __name__ == "__main__":
    raise SystemExit(main())
