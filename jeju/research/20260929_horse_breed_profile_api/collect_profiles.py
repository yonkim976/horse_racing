"""Archive KRA API42_1 horse profile pages and crosswalk race candidates.

API42_1 is a current profile lookup. Profile observations are timestamped when
retrieved and are not treated as breed evidence effective on historical race
dates.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from horse_racing.collectors.kra_api import KraApiClient, response_body
from horse_racing.config import get_settings


ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parents[2]
RESULT_RUN_2002_2025 = PROJECT_ROOT / "jeju/research/20260929_api4_3_history_backfill/attempts/20260929T132522.134266Z"
RESULT_RUN_2026 = PROJECT_ROOT / "jeju/research/20260929_core_collection_inventory/raw/2026/attempts/20260929T132618.518555Z"
ENDPOINT = "/API42_1/totalHorseInfo_1"
OPERATION = "totalHorseInfo_1"
PAGE_SIZE = 1000


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


def create_attempt() -> tuple[str, Path]:
    base = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    attempts = ROOT / "attempts"
    attempts.mkdir(parents=True, exist_ok=True)
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


def api_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    body = response_body(payload)
    wrapped = body.get("items") or {}
    value = wrapped.get("item") if isinstance(wrapped, dict) else None
    if value is None:
        return []
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list) and all(isinstance(row, dict) for row in value):
        return value
    raise ValueError("Unexpected API42_1 item structure")


def clean(value: Any) -> str:
    return "" if value is None else str(value).strip()


def read_candidate_ids() -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    candidates: dict[str, dict[str, Any]] = {}
    source_pages: list[dict[str, Any]] = []
    candidate_rows = 0
    missing_id_rows = 0
    malformed_id_rows = 0

    for year in range(2002, 2026):
        manifest_path = RESULT_RUN_2002_2025 / str(year) / "attempt_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for page in manifest.get("source_pages", []):
            path = RESULT_RUN_2002_2025 / page["response_file"]
            raw = path.read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            if digest != page["response_sha256"]:
                raise ValueError(f"Prior result page SHA mismatch: {path.relative_to(PROJECT_ROOT)}")
            payload = json.loads(raw)
            rows = api_items(payload)
            if len(rows) != int(page.get("actual_page_rows", -1)):
                raise ValueError(f"Prior result page row count mismatch: {path.relative_to(PROJECT_ROOT)}")
            source_pages.append({"year": year, "sha256": digest, "rows": len(rows)})
            candidate_rows += _accumulate_candidates(rows, candidates)
            missing_id_rows += sum(
                _is_candidate(row) and not clean(row.get("hrNo")) for row in rows
            )
            malformed_id_rows += sum(
                _is_candidate(row)
                and bool(clean(row.get("hrNo")))
                and not re.fullmatch(r"\d{7}", clean(row.get("hrNo")))
                for row in rows
            )

    manifest_2026 = json.loads((RESULT_RUN_2026 / "attempt_manifest.json").read_text(encoding="utf-8"))
    for page in manifest_2026.get("source_pages", []):
        path = RESULT_RUN_2026 / page["response_file"]
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest != page["response_sha256"]:
            raise ValueError(f"2026 result page SHA mismatch: {path.relative_to(PROJECT_ROOT)}")
        payload = json.loads(raw)
        rows = api_items(payload)
        if len(rows) != int(page.get("upstream_rows", -1)):
            raise ValueError(f"2026 result page row count mismatch: {path.relative_to(PROJECT_ROOT)}")
        source_pages.append({"year": 2026, "sha256": digest, "rows": len(rows)})
        candidate_rows += _accumulate_candidates(rows, candidates)
        missing_id_rows += sum(
            _is_candidate(row) and not clean(row.get("hrNo")) for row in rows
        )
        malformed_id_rows += sum(
            _is_candidate(row)
            and bool(clean(row.get("hrNo")))
            and not re.fullmatch(r"\d{7}", clean(row.get("hrNo")))
            for row in rows
        )
    source_summary = {
        "sources": [
            {
                "path": str(RESULT_RUN_2002_2025.relative_to(PROJECT_ROOT)),
                "years": [2002, 2025],
            },
            {
                "path": str(RESULT_RUN_2026.relative_to(PROJECT_ROOT)),
                "years": [2026, 2026],
                "through_date": "20260919",
            },
        ],
        "source_page_count": len(source_pages),
        "source_page_sha256_valid": True,
        "candidate_result_rows": candidate_rows,
        "candidate_unique_hr_no": len(candidates),
        "candidate_rows_missing_hr_no": missing_id_rows,
        "candidate_rows_malformed_hr_no": malformed_id_rows,
    }
    return candidates, source_summary


def _is_candidate(row: dict[str, Any]) -> bool:
    return clean(row.get("meet")) == "제주" and clean(row.get("rank")).startswith("제")


def _accumulate_candidates(
    rows: list[dict[str, Any]],
    candidates: dict[str, dict[str, Any]],
) -> int:
    count = 0
    for row in rows:
        if not _is_candidate(row):
            continue
        count += 1
        horse_id = clean(row.get("hrNo"))
        if not horse_id:
            continue
        record = candidates.setdefault(
            horse_id,
            {"race_result_rows": 0, "first_race_date": None, "last_race_date": None},
        )
        record["race_result_rows"] += 1
        race_date = clean(row.get("rcDate"))
        if race_date:
            record["first_race_date"] = min(race_date, record["first_race_date"] or race_date)
            record["last_race_date"] = max(race_date, record["last_race_date"] or race_date)
    return count


def safe_error(exc: BaseException, service_key: str | None) -> list[dict[str, str]]:
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
    started_at = datetime.now(UTC).isoformat()
    candidates, source_summary = read_candidate_ids()
    settings = get_settings()
    secret = settings.data_go_kr_service_key
    service_key = secret.get_secret_value() if secret is not None else None
    attempt_id, attempt_dir = create_attempt()
    page_dir = attempt_dir / "source_pages"
    page_audit: list[dict[str, Any]] = []
    profiles: list[tuple[dict[str, Any], int]] = []
    total_counts: set[int] = set()
    page_sizes: set[int] = set()
    failed: BaseException | None = None

    try:
        if service_key is None:
            raise RuntimeError("KRA service key unavailable")
        with KraApiClient(service_key, base_url=settings.kra_api_base_url, timeout_seconds=90) as client:
            for page_no, page in enumerate(
                client.iter_pages(
                    endpoint=ENDPOINT,
                    operation=OPERATION,
                    public_params={"_type": "json"},
                    page_size=PAGE_SIZE,
                    service_key_parameter="ServiceKey",
                ),
                start=1,
            ):
                if service_key.encode("utf-8") in page.body:
                    raise ValueError("API response body contained configured credential; response was not archived")
                response_path = page_dir / f"page_{page_no:04d}.json"
                immutable_write(response_path, page.body)
                batch = api_items(page.payload)
                body = response_body(page.payload)
                total_count = int(body.get("totalCount") or 0)
                page_size = int(body.get("numOfRows") or PAGE_SIZE)
                total_counts.add(total_count)
                page_sizes.add(page_size)
                for row in batch:
                    profiles.append((row, page.retrieved_at_ms))
                page_audit.append({
                    "page_no": page_no,
                    "status_code": page.status_code,
                    "content_type": page.content_type,
                    "requested_at_ms": page.requested_at_ms,
                    "retrieved_at_ms": page.retrieved_at_ms,
                    "response_bytes": len(page.body),
                    "response_sha256": hashlib.sha256(page.body).hexdigest(),
                    "response_file": str(response_path.relative_to(attempt_dir)),
                    "source_url_without_key": page.source_url,
                    "api_total_count": total_count,
                    "api_page_no": int(body.get("pageNo") or page_no),
                    "api_page_size": page_size,
                    "api_expected_page_count": max(1, math.ceil(total_count / max(page_size, 1))),
                    "actual_page_rows": len(batch),
                })
                print(json.dumps({
                    "page_no": page_no,
                    "actual_rows": len(batch),
                    "api_total_count": total_count,
                }), flush=True)
    except Exception as exc:
        failed = exc

    page_expected_count = max(
        1,
        math.ceil(next(iter(total_counts), 0) / max(next(iter(page_sizes), PAGE_SIZE), 1)),
    )
    profile_ids: Counter[str] = Counter()
    breed_values: Counter[str] = Counter()
    profiles_by_id: dict[str, list[tuple[dict[str, Any], int]]] = defaultdict(list)
    missing_profile_ids = malformed_profile_ids = missing_breed = 0
    field_names: Counter[str] = Counter()
    for profile, observed_at_ms in profiles:
        field_names.update(profile.keys())
        horse_id = clean(profile.get("hrNo"))
        if not horse_id:
            missing_profile_ids += 1
            continue
        profile_ids[horse_id] += 1
        profiles_by_id[horse_id].append((profile, observed_at_ms))
        if not re.fullmatch(r"\d{7}", horse_id):
            malformed_profile_ids += 1
        breed = clean(profile.get("breed"))
        breed_values[breed if breed else "<missing>"] += 1
        if not breed:
            missing_breed += 1

    crosswalk_lines: list[bytes] = []
    matched_ids = matched_rows = matched_candidate_rows = 0
    candidate_breed_values: Counter[str] = Counter()
    unmatched_ids: list[str] = []
    ambiguous_ids = 0
    for horse_id, candidate in sorted(candidates.items()):
        matches = profiles_by_id.get(horse_id, [])
        profile = matches[0][0] if len(matches) == 1 else None
        observed_at_ms = matches[0][1] if len(matches) == 1 else None
        breed = clean(profile.get("breed")) if profile is not None else ""
        if matches:
            matched_ids += 1
            matched_rows += len(matches)
            matched_candidate_rows += int(candidate["race_result_rows"])
            if len(matches) > 1:
                ambiguous_ids += 1
            candidate_breed_values[breed if breed else "<missing>"] += 1
        else:
            unmatched_ids.append(horse_id)
        crosswalk_lines.append((json.dumps({
            "hrNo": horse_id,
            **candidate,
            "profile_match_count": len(matches),
            "profile_observed_at_ms": observed_at_ms,
            "breed_raw": breed if profile is not None else None,
            "profile_name": clean(profile.get("hrNm")) if profile is not None else None,
        }, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"))

    candidate_id_content = b"".join(
        (json.dumps({"hrNo": horse_id, **record}, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        for horse_id, record in sorted(candidates.items())
    )
    crosswalk_content = b"".join(crosswalk_lines)
    immutable_write(attempt_dir / "candidate_horse_ids.jsonl", candidate_id_content)
    immutable_write(attempt_dir / "candidate_profile_crosswalk.jsonl", crosswalk_content)

    total_count = next(iter(total_counts), 0)
    actual_profile_rows = len(profiles)
    status = "completed" if failed is None else "failed"
    if failed is None and (
        len(total_counts) != 1
        or len(page_sizes) != 1
        or len(page_audit) != page_expected_count
        or actual_profile_rows != total_count
    ):
        status = "completed_with_count_mismatch"

    manifest = {
        "attempt_id": attempt_id,
        "started_at_utc": started_at,
        "completed_at_utc": datetime.now(UTC).isoformat(),
        "status": status,
        "source": "KRA API42_1 totalHorseInfo_1",
        "portal_dataset_id": "15057985",
        "endpoint": ENDPOINT,
        "operation": OPERATION,
        "source_host": urlparse(settings.kra_api_base_url).hostname,
        "public_params": {"_type": "json", "page_size": PAGE_SIZE},
        "service_key_recorded": False,
        "artifacts_are_immutable": True,
        "source_page_storage": "source_pages/page_NNNN.json (response body bytes as returned)",
        "profile_observation_note": "Each profile row is observed at its page retrieved_at_ms. The API profile has no verified historical effective date; current breed is not assigned to historical race dates.",
        "candidate_result_source": source_summary,
        "profile_total_count": total_count,
        "profile_actual_page_count": len(page_audit),
        "profile_expected_page_count": page_expected_count,
        "profile_actual_row_count": actual_profile_rows,
        "profile_unique_hr_no_count": len(profile_ids),
        "profile_duplicate_hr_no_groups": sum(n > 1 for n in profile_ids.values()),
        "profile_duplicate_hr_no_excess_rows": sum(n - 1 for n in profile_ids.values() if n > 1),
        "profile_missing_hr_no_rows": missing_profile_ids,
        "profile_malformed_hr_no_rows_not_7_digits": malformed_profile_ids,
        "profile_missing_breed_rows": missing_breed,
        "profile_breed_raw_value_counts": dict(sorted(breed_values.items())),
        "profile_field_names": sorted(field_names),
        "candidate_unique_hr_no_count": len(candidates),
        "candidate_profile_matched_hr_no_count": matched_ids,
        "candidate_profile_unmatched_hr_no_count": len(unmatched_ids),
        "candidate_profile_ambiguous_hr_no_count": ambiguous_ids,
        "candidate_profile_unique_id_coverage": round(matched_ids / len(candidates), 8) if candidates else None,
        "candidate_result_rows_matched_by_current_profile": matched_candidate_rows,
        "candidate_result_row_coverage": round(matched_candidate_rows / source_summary["candidate_result_rows"], 8) if source_summary["candidate_result_rows"] else None,
        "candidate_profile_breed_raw_value_counts_by_unique_id": dict(sorted(candidate_breed_values.items())),
        "candidate_horse_ids_sha256": hashlib.sha256(candidate_id_content).hexdigest(),
        "candidate_profile_crosswalk_sha256": hashlib.sha256(crosswalk_content).hexdigest(),
        "source_pages": page_audit,
        "persisted_response_files": [page["response_file"] for page in page_audit],
    }
    if failed is not None:
        manifest["exception_chain"] = safe_error(failed, service_key)
        manifest["partial_source_page_count"] = len(page_audit)
    immutable_write(
        attempt_dir / "attempt_manifest.json",
        (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )
    print(json.dumps({
        "attempt_id": attempt_id,
        "status": status,
        "candidate_unique_ids": len(candidates),
        "profile_rows": actual_profile_rows,
        "matched_candidate_ids": matched_ids,
        "unmatched_candidate_ids": len(unmatched_ids),
        "breed_value_counts": dict(sorted(candidate_breed_values.items())),
        "attempt_dir": str(attempt_dir.relative_to(PROJECT_ROOT)),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
