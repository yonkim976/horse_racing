"""Archive the complete 2026 Jeju meet result response from KRA OpenAPI."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from horse_racing.collectors.kra_api import (
    RACE_RESULT_WITH_SECTIONS_ENDPOINT,
    RACE_RESULT_WITH_SECTIONS_OPERATION,
    KraApiClient,
    response_body,
)
from horse_racing.config import get_settings


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "raw" / "2026"
THROUGH_DATE = 20260919


def items(payload: dict) -> list[dict]:
    wrapped = response_body(payload).get("items") or {}
    rows = wrapped.get("item") if isinstance(wrapped, dict) else None
    if rows is None:
        return []
    if isinstance(rows, dict):
        return [rows]
    if isinstance(rows, list) and all(isinstance(row, dict) for row in rows):
        return rows
    raise ValueError("Unexpected result item structure")


def atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        # Linking is atomic and fails if an artifact with this name already exists.
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def create_attempt_dir() -> tuple[str, Path]:
    attempts = OUTPUT / "attempts"
    attempts.mkdir(parents=True, exist_ok=True)
    base = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    attempt_id = base
    suffix = 1
    while True:
        path = attempts / attempt_id
        try:
            path.mkdir()
            return attempt_id, path
        except FileExistsError:
            suffix += 1
            attempt_id = f"{base}-{suffix}"


def error_record(exc: Exception, service_key: str | None) -> dict:
    chain: list[dict[str, str]] = []
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        message = str(current)
        if service_key:
            message = message.replace(service_key, "[REDACTED]")
        message = re.sub(
            r"(?i)(servicekey|service_key)=([^&\s]+)",
            r"\1=[REDACTED]",
            message,
        )
        chain.append({"type": type(current).__name__, "message": message})
        current = current.__cause__ or current.__context__
    return {"exception_chain": chain}


def main() -> None:
    settings = get_settings()
    service_key = (
        settings.data_go_kr_service_key.get_secret_value()
        if settings.data_go_kr_service_key is not None
        else None
    )
    attempt_id, attempt_dir = create_attempt_dir()
    started_at = datetime.now(UTC).isoformat()
    source_pages_dir = attempt_dir / "source_pages"
    grouped: dict[tuple[int, int], list[dict]] = defaultdict(list)
    page_audit: list[dict] = []
    upstream_rows = candidate_rows_after_cutoff = 0
    upstream_total_count = 0
    output_manifest_path = attempt_dir / "attempt_manifest.json"
    base_manifest = {
        "attempt_id": attempt_id,
        "started_at_utc": started_at,
        "requested_scope": {
            "meet": 2,
            "endpoint": RACE_RESULT_WITH_SECTIONS_ENDPOINT,
            "public_params": {"meet": 2, "rc_year": "2026", "_type": "json"},
            "through_date": str(THROUGH_DATE),
        },
        "source": "KRA API4_3 raceResult_3",
        "source_host": urlparse(settings.kra_api_base_url).hostname,
        "artifacts_are_immutable": True,
        "retry_policy": {"max_attempts_per_page": 6, "backoff_seconds": "1..30 exponential"},
        "source_page_storage": "source_pages/page_NNNN.json (response body bytes as returned)",
        "classification_note": (
            "No rank-prefix filter is applied. meet=제주 identifies the venue, not individual breed. "
            "The API is the primary result source; any post-2023 Jeju-only population rule is recorded separately."
        ),
    }

    try:
        if service_key is None:
            raise RuntimeError("KRA service key unavailable")

        with KraApiClient(
            service_key,
            base_url=settings.kra_api_base_url,
            timeout_seconds=90,
        ) as client:
            for page_no, page in enumerate(client.iter_pages(
                endpoint=RACE_RESULT_WITH_SECTIONS_ENDPOINT,
                operation=RACE_RESULT_WITH_SECTIONS_OPERATION,
                public_params={"meet": 2, "rc_year": "2026", "_type": "json"},
                page_size=20_000,
                service_key_parameter="ServiceKey",
            ), start=1):
                # Preserve the unmodified response before parsing or filtering it.
                raw_path = source_pages_dir / f"page_{page_no:04d}.json"
                atomic_write(raw_path, page.body)
                page_record = {
                    "status_code": page.status_code,
                    "requested_at_ms": page.requested_at_ms,
                    "retrieved_at_ms": page.retrieved_at_ms,
                    "response_bytes": len(page.body),
                    "response_sha256": hashlib.sha256(page.body).hexdigest(),
                    "response_file": str(raw_path.relative_to(attempt_dir)),
                    "source_url_without_key": page.source_url,
                }
                page_audit.append(page_record)
                batch = items(page.payload)
                upstream_rows += len(batch)
                upstream_total_count = int(response_body(page.payload).get("totalCount") or 0)
                candidate_rows = 0
                for row in batch:
                    race_date = int(row["rcDate"])
                    if race_date // 10_000 != 2026 or row.get("meet") != "제주":
                        raise ValueError("Unexpected meet or year in meet=2 2026 API response")
                    if race_date > THROUGH_DATE:
                        candidate_rows_after_cutoff += 1
                        continue
                    grouped[(race_date, int(row["rcNo"]))].append(row)
                    candidate_rows += 1
                page_record.update({
                    "upstream_total_count": upstream_total_count,
                    "upstream_rows": len(batch),
                    "api_result_rows_through_cutoff": candidate_rows,
                })

        if not page_audit:
            raise ValueError("API returned no response pages")
        if upstream_rows != upstream_total_count:
            raise ValueError(f"Incomplete API result pages: {upstream_rows}/{upstream_total_count}")

        for key, rows in grouped.items():
            if len({(row.get("rank"), row.get("rcDist")) for row in rows}) != 1:
                raise ValueError(f"Inconsistent candidate race: {key}")
            horse_ids = [str(row.get("hrNo") or "").strip() for row in rows]
            if any(not value for value in horse_ids) or len(set(horse_ids)) != len(rows):
                raise ValueError(f"Missing or duplicate horse ID: {key}")

        records = [row for key in sorted(grouped) for row in grouped[key]]
        content = b"".join(
            (json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
            for row in records
        )
        first_date = min((key[0] for key in grouped), default=None)
        last_date = max((key[0] for key in grouped), default=None)
        manifest = {
            **base_manifest,
            "status": "completed_api_result_rows",
            "completed_at_utc": datetime.now(UTC).isoformat(),
            "upstream_total_count": upstream_total_count,
            "upstream_mixed_rows_seen": upstream_rows,
            "api_rows_after_cutoff": candidate_rows_after_cutoff,
            "api_races_through_cutoff": len(grouped),
            "api_rows_through_cutoff": len(records),
            "first_race_date": str(first_date) if first_date else None,
            "last_race_date": str(last_date) if last_date else None,
            "api_rows_sha256": hashlib.sha256(content).hexdigest(),
            "source_pages": page_audit,
            "response_page_count": len(page_audit),
            "persisted_response_files": [page["response_file"] for page in page_audit],
            "source_population_note": (
                "These are all API rows returned for meet=2 through 2026-09-19. No rank-prefix filter was applied. "
                "The race-result API response has no individual breed field; any 2023-onward population rule is "
                "kept separate from response fields."
            ),
        }
        atomic_write(attempt_dir / "api_result_rows_2026_through_20260919.jsonl", content)
        atomic_write(
            output_manifest_path,
            (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        )
        print(json.dumps({
            "attempt_id": attempt_id,
            "status": manifest["status"],
            "api_races": manifest["api_races_through_cutoff"],
            "api_rows": manifest["api_rows_through_cutoff"],
            "source_page_count": manifest["response_page_count"],
            "attempt_dir": str(attempt_dir.relative_to(ROOT.parents[2])),
        }, ensure_ascii=False))
    except Exception as exc:
        manifest = {
            **base_manifest,
            "status": "failed",
            "failed_at_utc": datetime.now(UTC).isoformat(),
            "completed_source_pages": page_audit,
            "persisted_response_files": [
                {
                    "path": str(path.relative_to(attempt_dir)),
                    "bytes": path.stat().st_size,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
                for path in sorted(source_pages_dir.glob("*.json"))
            ] if source_pages_dir.exists() else [],
            **error_record(exc, service_key),
            "existing_attempt_artifacts_overwritten": False,
        }
        atomic_write(
            output_manifest_path,
            (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        )
        print(json.dumps({"attempt_id": attempt_id, "status": "failed", "attempt_manifest": str(output_manifest_path)}, ensure_ascii=False))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
