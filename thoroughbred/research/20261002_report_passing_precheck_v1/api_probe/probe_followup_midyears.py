"""Follow-up year probes: judge/sanction midyears and API303 2016 venues."""

from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

from horse_racing.config import get_settings
from probe_retrospective_availability import DATASETS, MIN_INTERVAL_SECONDS, PAGE_SIZE, safe_body_shape


ROOT = Path(__file__).resolve().parent
REQUESTS = [
    (dataset, meet, year)
    for dataset in ("judge_report", "sanction_history")
    for meet in (1, 3, 4)
    for year in (2020, 2024)
] + [("passing_groups", meet, 2016) for meet in (1, 3)]


def main() -> int:
    settings = get_settings()
    secret = settings.data_go_kr_service_key
    if secret is None or not secret.get_secret_value().strip():
        print(json.dumps({"status": "credential_unavailable"}))
        return 2
    key = secret.get_secret_value()
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    raw_root = ROOT / "raw" / "followup_midyears"
    raw_root.mkdir(parents=True, exist_ok=True)
    manifest = {
        "run_id": run_id,
        "source": "KRA official OpenAPI; read-only midyear availability probe",
        "credential_recorded": False,
        "page_size": PAGE_SIZE,
        "min_interval_seconds": MIN_INTERVAL_SECONDS,
        "records": [],
    }
    previous = 0.0
    with httpx.Client(base_url=settings.kra_api_base_url.rstrip("/"), timeout=25.0) as client:
        for dataset, meet, year in REQUESTS:
            endpoint, operation, _ = DATASETS[dataset]
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
                "numOfRows": PAGE_SIZE,
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
                    record["sample_rows"] = parsed["sample_rows"]
                else:
                    record["parse_status"] = "non_200_response"
                path = raw_root / dataset / str(year) / f"meet_{meet}.json"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(body)
                record["raw_response_path"] = path.relative_to(ROOT).as_posix()
            except Exception as exc:  # omit exception text/URL by design
                record["failure_type"] = type(exc).__name__
                record["failure_category"] = "credential_echo_detected" if str(exc) == "credential_echo_detected" else "request_or_parse_failure"
            manifest["records"].append(record)
    out = ROOT / "api_availability_probe_followup_manifest.json"
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = [
        {k: r.get(k) for k in ("dataset", "requested_meet", "requested_year", "http_status", "api_result_code", "total_count", "first_page_rows", "sample_dates", "failure_category") if k in r}
        for r in manifest["records"]
    ]
    print(json.dumps({"manifest": out.relative_to(ROOT).as_posix(), "calls": len(manifest["records"]), "summary": summary}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
