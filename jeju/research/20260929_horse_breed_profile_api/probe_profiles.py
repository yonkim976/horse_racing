"""Probe API42_1 bulk pagination and direct horse-ID lookups; archive responses."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from horse_racing.collectors.kra_api import KraApiClient, response_body
from horse_racing.config import get_settings


ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parents[2]
INITIAL_ATTEMPT = ROOT / "attempts/20260929T135818.827876Z"
ENDPOINT = "/API42_1/totalHorseInfo_1"
OPERATION = "totalHorseInfo_1"


def immutable_write(path: Path, content: bytes) -> None:
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


def api_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    wrapped = response_body(payload).get("items") or {}
    value = wrapped.get("item") if isinstance(wrapped, dict) else None
    if value is None:
        return []
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list) and all(isinstance(row, dict) for row in value):
        return value
    raise ValueError("Unexpected API42_1 item structure")


def safe_error(exc: BaseException, key: str) -> list[dict[str, str]]:
    chain: list[dict[str, str]] = []
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        message = str(current).replace(key, "[REDACTED]")
        message = re.sub(r"(?i)(servicekey|service_key)=([^&\s]+)", r"\1=[REDACTED]", message)
        chain.append({"type": type(current).__name__, "message": message})
        current = current.__cause__ or current.__context__
    return chain


def new_attempt() -> tuple[str, Path]:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    root = ROOT / "attempts"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{stamp}-probes"
    path.mkdir()
    return path.name, path


def main() -> None:
    observed_at = datetime.now(UTC).isoformat()
    initial = [json.loads(line) for line in (INITIAL_ATTEMPT / "candidate_profile_crosswalk.jsonl").read_text(encoding="utf-8").splitlines()]
    matched_id = next(row["hrNo"] for row in initial if row["profile_match_count"] == 1)
    unmatched_id = next(row["hrNo"] for row in initial if row["profile_match_count"] == 0)
    probes = [
        {"name": "bulk_page1_numRows20000", "params": {"_type": "json", "pageNo": 1, "numOfRows": 20_000}},
        {"name": "bulk_page2_numRows20000", "params": {"_type": "json", "pageNo": 2, "numOfRows": 20_000}},
        {"name": "candidate_id_matched", "params": {"_type": "json", "pageNo": 1, "numOfRows": 1000, "hr_no": matched_id}},
        {"name": "candidate_id_unmatched", "params": {"_type": "json", "pageNo": 1, "numOfRows": 1000, "hr_no": unmatched_id}},
    ]
    settings = get_settings()
    secret = settings.data_go_kr_service_key
    key = secret.get_secret_value() if secret is not None else None
    attempt_id, attempt_dir = new_attempt()
    results: list[dict[str, Any]] = []
    if key is None:
        results.append({"name": "all", "status": "failed", "exception_chain": [{"type": "RuntimeError", "message": "KRA service key unavailable"}]})
    else:
        with KraApiClient(key, base_url=settings.kra_api_base_url, timeout_seconds=90) as client:
            for probe in probes:
                record: dict[str, Any] = {"name": probe["name"], "public_params": probe["params"]}
                try:
                    page = client._fetch_json(
                        ENDPOINT,
                        OPERATION,
                        probe["params"],
                        service_key_parameter="ServiceKey",
                    )
                    if key.encode("utf-8") in page.body:
                        raise ValueError("API response body contained configured credential; response was not archived")
                    raw_path = attempt_dir / "source_pages" / f"{probe['name']}.json"
                    immutable_write(raw_path, page.body)
                    rows = api_items(page.payload)
                    body = response_body(page.payload)
                    record.update({
                        "status": "completed",
                        "status_code": page.status_code,
                        "requested_at_ms": page.requested_at_ms,
                        "retrieved_at_ms": page.retrieved_at_ms,
                        "response_bytes": len(page.body),
                        "response_sha256": hashlib.sha256(page.body).hexdigest(),
                        "response_file": str(raw_path.relative_to(attempt_dir)),
                        "source_url_without_key": page.source_url,
                        "api_total_count": int(body.get("totalCount") or 0),
                        "api_page_no": int(body.get("pageNo") or probe["params"]["pageNo"]),
                        "api_page_size": int(body.get("numOfRows") or 0),
                        "actual_rows": len(rows),
                        "breed_raw_value_counts": dict(sorted(Counter(str(row.get("breed") or "<missing>").strip() for row in rows).items())),
                        "returned_queried_hr_no": any(str(row.get("hrNo") or "").strip() == str(probe["params"].get("hr_no") or "") for row in rows) if "hr_no" in probe["params"] else None,
                    })
                except Exception as exc:
                    record["status"] = "failed"
                    record["exception_chain"] = safe_error(exc, key)
                results.append(record)
                print(json.dumps({
                    "probe": record["name"],
                    "status": record["status"],
                    "api_total_count": record.get("api_total_count"),
                    "api_page_size": record.get("api_page_size"),
                    "actual_rows": record.get("actual_rows"),
                    "requested_id_found": record.get("returned_queried_hr_no"),
                }), flush=True)
    manifest = {
        "attempt_id": attempt_id,
        "started_at_utc": observed_at,
        "completed_at_utc": datetime.now(UTC).isoformat(),
        "source": "KRA API42_1 totalHorseInfo_1",
        "portal_dataset_id": "15057985",
        "endpoint": ENDPOINT,
        "operation": OPERATION,
        "source_host": settings.kra_api_base_url.split("/")[2],
        "service_key_recorded": False,
        "probe_purpose": "Check whether the initial 100-row bulk list can be paginated and whether candidate horse IDs are retrievable directly.",
        "candidate_hr_no_query_values": {"matched_sample": matched_id, "unmatched_sample": unmatched_id},
        "profile_observation_note": "These profiles are current observations at retrieved_at_ms. No breed result is assigned to historical race dates.",
        "probes": results,
    }
    immutable_write(attempt_dir / "attempt_manifest.json", (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    print(json.dumps({"attempt_id": attempt_id, "attempt_dir": str(attempt_dir.relative_to(PROJECT_ROOT))}, ensure_ascii=False))


if __name__ == "__main__":
    main()
