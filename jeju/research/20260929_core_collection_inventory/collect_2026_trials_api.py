"""Fetch and archive 2026 Jeju running-trial results from KRA OpenAPI."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from horse_racing.collectors.kra_api import KraApiClient, response_body
from horse_racing.config import get_settings


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "raw" / "trials" / "2026" / "attempts"
ENDPOINT = "/API20_1/ridingTestResult_1"
OPERATION = "ridingTestResult_1"
MEET = 2
YEAR = 2026
TARGET_DATE = "20260916"
PAGE_SIZE = 1000


def atomic_create(path: Path, content: bytes) -> None:
    """Create immutable artifact; fail instead of replacing an existing path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def create_attempt() -> tuple[str, Path]:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    base = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    attempt_id = base
    suffix = 1
    while True:
        path = OUTPUT / attempt_id
        try:
            path.mkdir()
            return attempt_id, path
        except FileExistsError:
            suffix += 1
            attempt_id = f"{base}-{suffix}"


def rows_from(payload: dict) -> list[dict]:
    wrapped = response_body(payload).get("items") or {}
    values = wrapped.get("item") if isinstance(wrapped, dict) else None
    if values is None:
        return []
    if isinstance(values, dict):
        return [values]
    if isinstance(values, list) and all(isinstance(row, dict) for row in values):
        return values
    raise ValueError("Unexpected riding-trial API item structure")


def safe_error(exc: Exception, service_key: str | None) -> list[dict[str, str]]:
    chain: list[dict[str, str]] = []
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        message = str(current)
        if service_key:
            message = message.replace(service_key, "[REDACTED]")
        message = re.sub(r"(?i)(servicekey|service_key)=([^&\s]+)", r"\1=[REDACTED]", message)
        chain.append({"type": type(current).__name__, "message": message})
        current = current.__cause__ or current.__context__
    return chain


def main() -> None:
    secret = get_settings().data_go_kr_service_key
    service_key = secret.get_secret_value() if secret is not None else None
    attempt_id, attempt_dir = create_attempt()
    started = datetime.now(UTC).isoformat()
    page_dir = attempt_dir / "source_pages"
    audit: list[dict] = []
    target_rows: list[dict] = []
    total_rows = 0
    total_count = 0
    page_total_counts: set[int] = set()
    source_host = urlparse(get_settings().kra_api_base_url).hostname
    base_manifest = {
        "attempt_id": attempt_id,
        "started_at_utc": started,
        "source": "KRA OpenAPI 15056974 한국마사회 주행심사 상세결과",
        "endpoint": ENDPOINT,
        "operation": OPERATION,
        "source_host": source_host,
        "requested_scope": {
            "meet": MEET,
            "tr_year": str(YEAR),
            "target_date_to_audit": TARGET_DATE,
            "public_params": {"meet": MEET, "tr_year": str(YEAR), "_type": "json"},
            "page_size": PAGE_SIZE,
        },
        "service_key_recorded": False,
        "source_page_storage": "source_pages/page_NNNN.json (response body bytes as returned)",
        "existing_attempt_artifacts_overwritten": False,
    }
    manifest_path = attempt_dir / "attempt_manifest.json"

    try:
        if service_key is None:
            raise RuntimeError("KRA service key unavailable")

        with KraApiClient(service_key, base_url=get_settings().kra_api_base_url, timeout_seconds=90) as client:
            for page_no, fetched in enumerate(client.iter_pages(
                endpoint=ENDPOINT,
                operation=OPERATION,
                public_params={"meet": MEET, "tr_year": str(YEAR), "_type": "json"},
                page_size=PAGE_SIZE,
                service_key_parameter="ServiceKey",
            ), start=1):
                body_path = page_dir / f"page_{page_no:04d}.json"
                atomic_create(body_path, fetched.body)
                batch = rows_from(fetched.payload)
                body = response_body(fetched.payload)
                page_total_counts.add(int(body.get("totalCount") or 0))
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
                    "page_total_count": body.get("totalCount"),
                    "response_rows": len(batch),
                }
                audit.append(page_record)
                total_rows += len(batch)
                total_count = int(body.get("totalCount") or 0)
                for row in batch:
                    event_date = str(row.get("trainDate") or "").replace("-", "")[:8]
                    if event_date[:4] != str(YEAR):
                        raise ValueError("Out-of-year row in riding-trial API response")
                    if row.get("meet") != "제주":
                        raise ValueError("Unexpected meet in meet=2 riding-trial API response")
                    if event_date == TARGET_DATE:
                        target_rows.append(row)

        if not audit:
            raise ValueError("API returned no response pages")
        if len(page_total_counts) != 1:
            raise ValueError(f"Inconsistent totalCount across API pages: {sorted(page_total_counts)}")
        if total_rows != total_count:
            raise ValueError(f"Incomplete API trial pages: {total_rows}/{total_count}")
        target_keys = [
            (str(row.get("trainDate")), str(row.get("trainNo")), str(row.get("chulNo")))
            for row in target_rows
        ]
        target_horse_ids = [str(row.get("hrNo") or "").strip() for row in target_rows]
        if not target_rows or len(set(target_keys)) != len(target_keys):
            raise ValueError("Target-date API rows are empty or have duplicate trial/runner keys")
        if any(not value for value in target_horse_ids) or len(set(target_horse_ids)) != len(target_horse_ids):
            raise ValueError("Target-date API rows have missing or duplicate official horse IDs")

        canonical = b"".join(
            (json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
            for row in target_rows
        )
        target_path = "trial_results_20260916.jsonl"
        atomic_create(attempt_dir / target_path, canonical)
        manifest = {
            **base_manifest,
            "status": "completed_api_response",
            "completed_at_utc": datetime.now(UTC).isoformat(),
            "response_page_count": len(audit),
            "upstream_total_count": total_count,
            "upstream_rows_seen": total_rows,
            "target_date": TARGET_DATE,
            "target_date_rows": len(target_rows),
            "target_date_unique_trial_ids": sorted({str(row.get("trainNo")) for row in target_rows}),
            "target_date_trial_row_counts": {
                str(train_no): sum(str(row.get("trainNo")) == str(train_no) for row in target_rows)
                for train_no in sorted({row.get("trainNo") for row in target_rows}, key=str)
            },
            "target_date_pass_flag_counts": {
                str(value): sum(row.get("passFlag") == value for row in target_rows)
                for value in sorted({row.get("passFlag") for row in target_rows}, key=str)
            },
            "target_date_unique_horse_ids": len(set(target_horse_ids)),
            "target_date_jsonl": target_path,
            "target_date_jsonl_sha256": hashlib.sha256(canonical).hexdigest(),
            "source_pages": audit,
            "persisted_response_files": [row["response_file"] for row in audit],
        }
        atomic_create(manifest_path, (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode())
        print(json.dumps({"attempt_id": attempt_id, "status": manifest["status"],
                          "upstream_rows": total_rows, "target_date_rows": len(target_rows),
                          "attempt_dir": str(attempt_dir.relative_to(ROOT.parents[2]))}, ensure_ascii=False))
    except Exception as exc:
        response = getattr(exc.__cause__, "response", None)
        response_body_path = None
        response_body_sha = None
        if response is not None and (not service_key or service_key.encode() not in response.content):
            response_body_path = "http_error_response.body"
            response_body_sha = hashlib.sha256(response.content).hexdigest()
            atomic_create(attempt_dir / response_body_path, response.content)
        manifest = {
            **base_manifest,
            "status": "failed",
            "failed_at_utc": datetime.now(UTC).isoformat(),
            "completed_source_pages": audit,
            "exception_chain": safe_error(exc, service_key),
            "http_status_code": getattr(response, "status_code", None),
            "http_error_response_file": response_body_path,
            "http_error_response_sha256": response_body_sha,
            "existing_attempt_artifacts_overwritten": False,
        }
        atomic_create(manifest_path, (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode())
        print(json.dumps({"attempt_id": attempt_id, "status": "failed",
                          "http_status_code": manifest["http_status_code"],
                          "exception_types": [row["type"] for row in manifest["exception_chain"]],
                          "attempt_manifest": str(manifest_path)}, ensure_ascii=False))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
