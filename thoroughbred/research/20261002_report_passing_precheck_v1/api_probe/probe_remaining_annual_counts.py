"""Probe remaining annual API215/API180_1 counts with one-row pages only."""

from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

from horse_racing.config import get_settings
from probe_retrospective_availability import MIN_INTERVAL_SECONDS, safe_body_shape


ROOT = Path(__file__).resolve().parent
YEARS = (2011, 2012, 2013, 2014, 2015, 2016, 2018, 2019, 2021, 2022, 2023)
MEETS = (1, 3)
DATASETS = {
    "judge_report": ("/API215/JudgeReport", "JudgeReport"),
    "sanction_history": ("/API180_1/sanctionHistory_1", "sanctionHistory_1"),
}


def main() -> int:
    settings = get_settings()
    secret = settings.data_go_kr_service_key
    if secret is None or not secret.get_secret_value().strip():
        print(json.dumps({"status": "credential_unavailable"}))
        return 2
    key = secret.get_secret_value()
    raw_root = ROOT / "raw" / "annual_count_probes"
    raw_root.mkdir(parents=True, exist_ok=True)
    records = []
    previous = 0.0
    with httpx.Client(base_url=settings.kra_api_base_url.rstrip("/"), timeout=25.0) as client:
        for dataset, (endpoint, operation) in DATASETS.items():
            for meet in MEETS:
                for year in YEARS:
                    if previous:
                        elapsed = time.monotonic() - previous
                        if elapsed < MIN_INTERVAL_SECONDS:
                            time.sleep(MIN_INTERVAL_SECONDS - elapsed)
                    params = {
                        "serviceKey": key,
                        "meet": meet,
                        "rc_year": str(year),
                        "_type": "json",
                        "pageNo": 1,
                        "numOfRows": 1,
                    }
                    record = {
                        "dataset": dataset,
                        "endpoint": endpoint,
                        "operation": operation,
                        "requested_meet": meet,
                        "requested_year": year,
                        "request_parameters_public": {k: v for k, v in params.items() if k != "serviceKey"},
                        "request_time_utc": datetime.now(UTC).isoformat(),
                    }
                    try:
                        response = client.get(endpoint, params=params)
                        previous = time.monotonic()
                        body = response.content
                        record["http_status"] = response.status_code
                        record["content_type"] = response.headers.get("content-type", "")
                        record["response_bytes"] = len(body)
                        record["response_sha256"] = hashlib.sha256(body).hexdigest()
                        if response.status_code == 200:
                            parsed = safe_body_shape(body, key)
                            record.update({k: v for k, v in parsed.items() if k != "sample_rows"})
                            record["first_row"] = parsed["sample_rows"][0] if parsed["sample_rows"] else None
                        else:
                            record["parse_status"] = "non_200_response"
                        path = raw_root / dataset / str(year) / f"meet_{meet}.json"
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_bytes(body)
                        record["raw_response_path"] = path.relative_to(ROOT).as_posix()
                    except Exception as exc:  # omit exception text/URL by design
                        record["failure_type"] = type(exc).__name__
                        record["failure_category"] = "credential_echo_detected" if str(exc) == "credential_echo_detected" else "request_or_parse_failure"
                    records.append(record)

        # Preserve the overflow page for 2026 Seoul sanctions, which can contain
        # records later than the research cutoff and is needed to identify them.
        endpoint, operation = DATASETS["sanction_history"]
        params = {
            "serviceKey": key,
            "meet": 1,
            "rc_year": "2026",
            "_type": "json",
            "pageNo": 2,
            "numOfRows": 1000,
        }
        elapsed = time.monotonic() - previous
        if previous and elapsed < MIN_INTERVAL_SECONDS:
            time.sleep(MIN_INTERVAL_SECONDS - elapsed)
        record = {
            "dataset": "sanction_history",
            "endpoint": endpoint,
            "operation": operation,
            "requested_meet": 1,
            "requested_year": 2026,
            "request_parameters_public": {k: v for k, v in params.items() if k != "serviceKey"},
            "request_time_utc": datetime.now(UTC).isoformat(),
            "purpose": "inspect and preserve 2026 rows beyond 2026-09-29 cutoff",
        }
        try:
            response = client.get(endpoint, params=params)
            body = response.content
            record["http_status"] = response.status_code
            record["content_type"] = response.headers.get("content-type", "")
            record["response_bytes"] = len(body)
            record["response_sha256"] = hashlib.sha256(body).hexdigest()
            if response.status_code == 200:
                parsed = safe_body_shape(body, key)
                record.update({k: v for k, v in parsed.items() if k != "sample_rows"})
                record["sample_rows"] = parsed["sample_rows"]
            else:
                record["parse_status"] = "non_200_response"
            path = raw_root / "sanction_history" / "2026" / "meet_1_page_2.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
            record["raw_response_path"] = path.relative_to(ROOT).as_posix()
        except Exception as exc:  # omit exception text/URL by design
            record["failure_type"] = type(exc).__name__
            record["failure_category"] = "credential_echo_detected" if str(exc) == "credential_echo_detected" else "request_or_parse_failure"
        records.append(record)

    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    manifest = {
        "run_id": run_id,
        "source": "KRA official OpenAPI; one-row annual count probes plus one overflow page",
        "credential_recorded": False,
        "sample_years": list(YEARS),
        "sample_meets": list(MEETS),
        "one_row_probe_calls": len(YEARS) * len(MEETS) * len(DATASETS),
        "additional_overflow_page_calls": 1,
        "records": records,
    }
    out = ROOT / "api_availability_probe_remaining_annual_manifest.json"
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = [
        {k: r.get(k) for k in ("dataset", "requested_meet", "requested_year", "http_status", "api_result_code", "total_count", "sample_dates", "first_row", "failure_category", "purpose") if k in r}
        for r in records
    ]
    print(json.dumps({"manifest": out.relative_to(ROOT).as_posix(), "calls": len(records), "summary": summary}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
