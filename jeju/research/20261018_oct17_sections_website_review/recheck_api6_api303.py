"""Make a bounded, key-safe API6/API303 reread for Jeju 2026-10-17 only."""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import sys
from datetime import date, datetime, UTC
from pathlib import Path
from urllib.parse import urlsplit

import httpx


ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from horse_racing import config as config_module  # noqa: E402
from horse_racing.collectors import kra_api as api  # noqa: E402
from jeju.refresh import collect  # noqa: E402


DATE = "20261017"
MAX_BYTES = 4 * 1024 * 1024
TIMEOUT_SECONDS = 20
MAX_WORKERS = 2
API_RAW = ROOT / "api_recheck" / "raw"
API_RAW.mkdir(parents=True, exist_ok=True)


class BoundedTransport(httpx.BaseTransport):
    """Read at most 4 MiB from the network response body before returning."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.inner = httpx.HTTPTransport(verify=True)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        response = self.inner.handle_request(request)
        try:
            chunks = []
            size = 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > self.limit:
                    raise httpx.RequestError("response_size_limit_exceeded", request=request)
                chunks.append(chunk)
            body = b"".join(chunks)
            headers = response.headers
            status = response.status_code
            extensions = response.extensions
        finally:
            response.close()
        return httpx.Response(
            status_code=status,
            headers=headers,
            content=body,
            request=request,
            extensions=extensions,
        )

    def close(self) -> None:
        self.inner.close()


def load_client() -> tuple[api.KraApiClient, str]:
    settings = config_module.get_settings()
    secret_obj = settings.data_go_kr_service_key
    if secret_obj is None:
        raise RuntimeError("official_api_credential_unavailable")
    secret = secret_obj.get_secret_value()
    parts = urlsplit(settings.kra_api_base_url)
    if (
        parts.scheme != "https"
        or parts.hostname != "apis.data.go.kr"
        or parts.path.rstrip("/") != "/B551015"
        or parts.query
        or parts.fragment
        or parts.username
        or parts.password
    ):
        raise RuntimeError("configured_official_api_base_url_not_allowlisted")
    client = api.KraApiClient(
        secret,
        base_url=settings.kra_api_base_url,
        timeout_seconds=TIMEOUT_SECONDS,
        transport=BoundedTransport(MAX_BYTES),
    )
    client._client.follow_redirects = False
    return client, secret


def tasks() -> list[dict]:
    return [
        {
            "family": "section_records",
            "endpoint": api.RACE_DETAIL_SECTION_RECORD_ENDPOINT,
            "operation": api.RACE_DETAIL_SECTION_RECORD_OPERATION,
            "key_parameter": "serviceKey",
            "params": {"meet": 2, "rc_date": DATE, "_type": "json", "pageNo": 1, "numOfRows": 1000},
        },
        {
            "family": "corner_rank",
            "endpoint": api.RACE_PASSING_SUMMARY_ENDPOINT,
            "operation": api.RACE_PASSING_SUMMARY_OPERATION,
            "key_parameter": "serviceKey",
            "params": {"meet": 2, "rc_date": DATE, "_type": "json", "pageNo": 1, "numOfRows": 1000},
        },
    ]


def run_one(client: api.KraApiClient, budget: collect._RequestBudget, task: dict, secret: str) -> dict:
    result = {
        "family": task["family"],
        "endpoint": task["endpoint"],
        "operation": task["operation"],
        "params": task["params"],
        "collected_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "timeout_seconds": TIMEOUT_SECONDS,
        "response_byte_limit": MAX_BYTES,
        "redirects_followed": False,
        "tls_certificate_verification": True,
        "request_attempt_limit": 1,
        "raw_path": None,
        "sha256": None,
    }
    try:
        fetched = collect._fetch_one(
            client,
            budget,
            endpoint=task["endpoint"],
            operation=task["operation"],
            params=task["params"],
            key_parameter=task["key_parameter"],
        )
        body_bytes = fetched.body
        if len(body_bytes) > MAX_BYTES:
            result["status"] = "response_over_limit"
            return result
        if collect._payload_has_secret(body_bytes, secret):
            result["status"] = "credential_echo_blocked_from_storage"
            return result
        payload = fetched.payload
        api_body = api.response_body(payload)
        rows = collect._rows(payload)
        in_scope, out_scope = collect._validate_scope_rows(
            task["family"], rows, date(2026, 10, 17), date(2026, 10, 17), exact_date=DATE
        )
        if out_scope != 0 or in_scope != len(rows):
            result["status"] = "scope_validation_failed"
            result["http_status"] = fetched.status_code
            result["row_count"] = len(rows)
            result["in_scope_rows"] = in_scope
            result["out_of_scope_rows"] = out_scope
            return result

        destination = API_RAW / task["family"] / DATE / "page_0001.json"
        collect._atomic_immutable_write(destination, body_bytes)
        result.update(
            {
                "status": "complete" if rows else "empty_success",
                "http_status": fetched.status_code,
                "content_type": fetched.content_type,
                "response_bytes": len(body_bytes),
                "result_code": (payload.get("response") or {}).get("header", {}).get("resultCode"),
                "total_count": int(api_body.get("totalCount") or 0),
                "row_count": len(rows),
                "in_scope_rows": in_scope,
                "out_of_scope_rows": out_scope,
                "raw_path": destination.relative_to(ROOT).as_posix(),
                "sha256": hashlib.sha256(body_bytes).hexdigest(),
                "record_summaries": summarize(task["family"], rows),
            }
        )
        return result
    except api.KraApiError as exc:
        safe = exc.safe_details()
        result.update(
            {
                "status": safe.get("error_reason", "api_error"),
                "http_status": safe.get("http_status"),
                "result_code": safe.get("api_result_code"),
            }
        )
        return result
    except Exception as exc:
        result.update({"status": "failed", "error_type": type(exc).__name__})
        return result


def summarize(family: str, rows: list[dict]) -> list[dict]:
    summary = []
    for row in rows:
        if family == "section_records":
            points = []
            for i in range(1, 13):
                distance_key, time_key, cumulative_key = f"dist_{i}f", f"time_{i}f", f"passtime_{i}f"
                distance = row.get(distance_key)
                time_value = row.get(time_key)
                cumulative = row.get(cumulative_key)
                if distance not in (None, 0, "0") or time_value not in (None, 0, "0") or cumulative not in (None, 0, "0"):
                    points.append(
                        {
                            "furlong_index": i,
                            "distance_m_raw": distance,
                            "interval_time_raw": time_value,
                            "cumulative_time_raw": cumulative,
                        }
                    )
            summary.append(
                {
                    "race_no": row.get("rcNo"),
                    "date_raw": row.get("rcDate"),
                    "meet_raw": row.get("meet"),
                    "race_distance_m_raw": row.get("rcDist"),
                    "section_points": points,
                    "passing_groups_raw": {
                        key: row.get(key)
                        for key in (
                            "passrankS1f",
                            "passrankG8f_1c",
                            "passrankG6f_2c",
                            "passrankG4f_3c",
                            "passrankG3f_4c",
                            "passrankG2f",
                            "passrankG1f",
                        )
                    },
                }
            )
        else:
            summary.append(
                {
                    "race_no": row.get("rcNo"),
                    "date_raw": row.get("rcDate"),
                    "meet_raw": row.get("meet"),
                    "corner_groups_raw": {f"corner_{i}": row.get(f"corner_{i}") for i in range(1, 10)},
                    "three_furlong_time_raw": row.get("passtime_3f"),
                    "four_furlong_time_raw": row.get("passtime_4f"),
                    "tempo_raw": row.get("tempo"),
                }
            )
    return summary


def main() -> None:
    if any(API_RAW.rglob("page_*.json")):
        raise FileExistsError("Refusing to overwrite existing API reread raw pages")
    client, secret = load_client()
    collect.MAX_RESPONSE_BYTES = MAX_BYTES
    collect.MAX_RETRIES = 0
    budget = collect._RequestBudget(limit=2)
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = [pool.submit(run_one, client, budget, task, secret) for task in tasks()]
            records = [future.result() for future in concurrent.futures.as_completed(futures)]
    finally:
        client.close()
    records.sort(key=lambda r: r["family"])
    previous = {
        "run_id": "20261017T220226_4747d5bd",
        "retrieved_at_utc": "2026-10-17T13:02:49.688761+00:00",
        "section_records_rows": 0,
        "corner_rank_rows": 0,
        "source_manifest": "jeju/research/20261017_core_refresh/runs/20261017T220226_4747d5bd/collection/source_manifest.json",
        "source_manifest_sha256": "9dc27d3d21f4dc993cd276879f1b0b83d89927b2b2a57429efd358ea601f5f72",
    }
    report = {
        "date": "2026-10-17",
        "meet": "Jeju (meet=2)",
        "purpose": "Narrow current reread of only API6 and API303, following the official homepage check.",
        "credential_handling": "Loaded through existing settings helper in memory; never printed or stored. Raw pages were checked for direct and URL-encoded secret echo before saving.",
        "bounds": {
            "max_concurrent_requests": MAX_WORKERS,
            "per_request_timeout_seconds": TIMEOUT_SECONDS,
            "max_response_bytes": MAX_BYTES,
            "max_calls": 2,
            "retries": 0,
            "tls_verification": True,
            "redirects_followed": False,
        },
        "previous_recheck": previous,
        "today": {
            "retrieved_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
            "page_count": len(records),
            "total_rows": sum(int(r.get("row_count") or 0) for r in records),
            "families": records,
        },
        "publication_comparison": [
            {
                "family": r["family"],
                "previous_rows": 0,
                "today_rows": r.get("row_count"),
                "today_status": r["status"],
                "newly_available_since_previous_refresh": bool(r.get("row_count")),
                "continued_zero_row_response": r.get("row_count") == 0 and r["status"] == "empty_success",
            }
            for r in records
        ],
    }
    path = ROOT / "api_recheck_summary.json"
    with path.open("x", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
        f.write("\n")
    safe_summary = {
        "api_rows_today": {r["family"]: r.get("row_count") for r in records},
        "prior_api_rows": {"section_records": 0, "corner_rank": 0},
        "api_http_statuses": {r["family"]: r.get("http_status") for r in records},
        "api_sha256": {r["family"]: r.get("sha256") for r in records},
    }
    print(json.dumps(safe_summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Error messages and URLs can contain the API credential; emit only a
        # fixed error class, never exception text or request details.
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__}, ensure_ascii=False))
        raise SystemExit(1)
