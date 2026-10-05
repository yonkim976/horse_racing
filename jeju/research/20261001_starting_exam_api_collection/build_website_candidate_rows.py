"""Join verified starting-exam website observations to current API42 profiles.

The output is a source-specific research candidate file, not an API21 import and
not a database write. Website row order and repeated observations are retained.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any


ROOT = Path(__file__).resolve().parent
WEBSITE_DIR = ROOT / "website_validation"
OBSERVATIONS_PATH = WEBSITE_DIR / "website_observations.json"
DATABASE = ROOT.parents[1] / "data" / "jeju_native_core.sqlite3"
OUTPUT_PATH = ROOT / "website_native_candidate_rows.jsonl"
SUMMARY_PATH = ROOT / "website_candidate_summary.json"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_api42_profile(raw: bytes, expected_id: str) -> dict[str, Any]:
    payload = json.loads(raw)
    response = payload.get("response", payload)
    header = response.get("header", {})
    body = response.get("body", {})
    if str(header.get("resultCode") or "") not in {"00", "0000"}:
        raise ValueError(f"API42 response failed for horse_id={expected_id}")
    items = (body.get("items") or {}).get("item")
    if isinstance(items, dict):
        items = [items]
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        raise ValueError(f"API42 item is malformed for horse_id={expected_id}")
    exact = [item for item in items if str(item.get("hrNo") or "").strip() == expected_id]
    if len(exact) != 1:
        raise ValueError(f"API42 returned {len(exact)} exact profiles for horse_id={expected_id}")
    return exact[0]


def verified_birth_year(raw: Any) -> tuple[int | None, str]:
    value = "" if raw is None else str(raw).strip()
    if not re.fullmatch(r"\d{8}", value):
        return None, "not_yyyymmdd"
    try:
        parsed = datetime.strptime(value, "%Y%m%d")
    except ValueError:
        return None, "invalid_calendar_date"
    if parsed.strftime("%Y%m%d") != value or parsed.year < 1900 or parsed.year > 2026:
        return None, "outside_supported_birth_date_range"
    return parsed.year, "validated_yyyymmdd"


def outcome_category(judgement: Any) -> str:
    raw = "" if judgement is None else str(judgement).strip()
    return {
        "합격": "pass",
        "불합격": "fail",
        "1차합격": "first_stage_pass",
    }.get(raw, "unclassified")


def build(api42_attempt: str | None = None) -> dict[str, Any]:
    observations = read_json(OBSERVATIONS_PATH)
    website_rows: list[dict[str, Any]] = observations["rows"]
    artifacts = observations.get("artifacts", [])

    artifact_by_name: dict[str, dict[str, Any]] = {}
    for item in artifacts:
        rel = PurePosixPath(str(item["path"]))
        if rel.is_absolute() or any(part in {"", ".", ".."} for part in rel.parts):
            raise ValueError("Website artifact path is unsafe")
        path = WEBSITE_DIR.joinpath(*rel.parts)
        raw = path.read_bytes()
        actual_hash = sha256_bytes(raw)
        if actual_hash != item.get("sha256"):
            raise ValueError(f"Website artifact hash mismatch: {item['path']}")
        artifact_by_name[rel.name] = {**item, "verified_sha256": actual_hash}
    missing_pages = sorted({str(row.get("source_path") or "") for row in website_rows} - set(artifact_by_name))
    if missing_pages:
        raise ValueError(f"Website row references unverified pages: {missing_pages}")

    all_attempts = sorted((ROOT / "raw" / "api42_followup" / "attempts").glob("*/attempt_manifest.json"))
    if api42_attempt:
        if not re.fullmatch(r"\d{8}T\d{6}\.\d{6}Z", api42_attempt):
            raise ValueError("--api42-attempt must be a UTC attempt ID")
        manifest_path = ROOT / "raw" / "api42_followup" / "attempts" / api42_attempt / "attempt_manifest.json"
        if not manifest_path.exists():
            raise ValueError(f"API42 follow-up attempt not found: {api42_attempt}")
    elif all_attempts:
        manifest_path = all_attempts[-1]
    else:
        raise ValueError("No API42 follow-up attempt manifest exists")
    api42_manifest = read_json(manifest_path)
    followup_profiles: dict[str, dict[str, Any]] = {}
    for record in api42_manifest.get("probes", []):
        if record.get("status") != "completed":
            continue
        response_rel = PurePosixPath(str(record["response_file"]))
        if response_rel.is_absolute() or any(part in {"", ".", ".."} for part in response_rel.parts):
            raise ValueError("API42 response path in manifest is unsafe")
        response_path = (manifest_path.parent / Path(*response_rel.parts)).resolve(strict=True)
        response_path.relative_to(manifest_path.parent.resolve(strict=True))
        response_bytes = response_path.read_bytes()
        actual_hash = sha256_bytes(response_bytes)
        if actual_hash != record.get("response_sha256"):
            raise ValueError(f"API42 follow-up response hash mismatch for {record['queried_hr_no']}")
        profile = read_api42_profile(response_bytes, str(record["queried_hr_no"]))
        followup_profiles[str(record["queried_hr_no"])] = {
            "profile": profile,
            "raw_path": response_path.relative_to(ROOT).as_posix(),
            "response_sha256": actual_hash,
            "attempt_started_at_utc": api42_manifest.get("started_at_utc"),
            "attempt_completed_at_utc": api42_manifest.get("completed_at_utc"),
        }

    db = sqlite3.connect(f"file:{DATABASE}?mode=ro", uri=True, timeout=60)
    db.row_factory = sqlite3.Row
    try:
        db.execute("PRAGMA query_only=ON")
        existing_profiles = {
            str(row["horse_id"]).strip(): dict(row)
            for row in db.execute(
                """SELECT horse_id, breed_label_raw, birth_date_raw,
                          observed_at_utc, horse_profile_observation_id,
                          api_record_id, payload_sha256, source_response_sha256,
                          raw_relative_path
                   FROM horse_profile_latest"""
            ).fetchall()
        }
    finally:
        db.close()

    output_rows: list[dict[str, Any]] = []
    page_row_numbers: Counter[str] = Counter()
    outcome_counts: Counter[str] = Counter()
    profile_source_counts: Counter[str] = Counter()
    judgement_raw_counts: Counter[str] = Counter()
    inspection_reason_counts: Counter[str] = Counter()
    failure_reason_counts: Counter[str] = Counter()
    event_date_counts: Counter[str] = Counter()
    profile_ids_by_source: dict[str, set[str]] = defaultdict(set)
    exact_content: Counter[str] = Counter()
    source_keys: Counter[str] = Counter()
    unlinked: list[dict[str, Any]] = []

    for observation_order, website_row in enumerate(website_rows, start=1):
        horse_id = str(website_row.get("horse_id") or "").strip()
        page_name = str(website_row.get("source_path") or "")
        page_row_numbers[page_name] += 1
        raw_existing = existing_profiles.get(horse_id)
        if raw_existing and raw_existing.get("breed_label_raw") == "제주마":
            source = "existing_api42_database_profile"
            profile = {
                "horse_id": horse_id,
                "breed": raw_existing.get("breed_label_raw"),
                "birthDt": raw_existing.get("birth_date_raw"),
            }
            profile_observed = raw_existing.get("observed_at_utc")
            profile_window = {"observed_at_utc": profile_observed}
            profile_hash = raw_existing.get("source_response_sha256") or raw_existing.get("payload_sha256")
            profile_path = raw_existing.get("raw_relative_path")
            profile_api_record_id = raw_existing.get("api_record_id")
            profile_observation_id = raw_existing.get("horse_profile_observation_id")
        elif horse_id in followup_profiles:
            source = "new_api42_followup_profile"
            latest = followup_profiles[horse_id]
            profile = latest["profile"]
            profile_observed = None
            profile_window = {
                "attempt_started_at_utc": latest["attempt_started_at_utc"],
                "attempt_completed_at_utc": latest["attempt_completed_at_utc"],
            }
            profile_hash = latest["response_sha256"]
            profile_path = latest["raw_path"]
            profile_api_record_id = None
            profile_observation_id = None
        else:
            unlinked.append({"observation_order": observation_order, "horse_id": horse_id, "source_path": page_name})
            source = "unlinked"
            profile = {}
            profile_observed = None
            profile_window = None
            profile_hash = None
            profile_path = None
            profile_api_record_id = None
            profile_observation_id = None

        breed = str(profile.get("breed") or "").strip() or None
        birth_raw = profile.get("birthDt")
        birth_year, birth_validation = verified_birth_year(birth_raw)
        age_2026 = 2026 - birth_year if birth_year is not None else None
        judgement_raw = website_row.get("judgement")
        category = outcome_category(judgement_raw)
        outcome_counts[category] += 1
        profile_source_counts[source] += 1
        judgement_raw_counts[str(judgement_raw).strip() if judgement_raw not in (None, "") else "<blank>"] += 1
        inspection_reason_counts[
            str(website_row.get("inspection_reason") or "").strip() or "<blank>"
        ] += 1
        failure_reason_counts[
            str(website_row.get("failure_reason") or "").strip() or "<blank>"
        ] += 1
        event_date_counts[str(website_row.get("date") or "<blank>")] += 1
        profile_ids_by_source[source].add(horse_id)

        page_artifact = artifact_by_name[page_name]
        row_payload = {
            "source_observation_order": observation_order,
            "website_source_page": (PurePosixPath("website_validation") / page_name).as_posix(),
            "website_source_page_sha256": page_artifact["verified_sha256"],
            "website_source_row_no": page_row_numbers[page_name],
            "event_date_raw": website_row.get("date"),
            "inspection_round_raw": website_row.get("round"),
            "horse_number_raw": website_row.get("horse_number"),
            "official_horse_id_raw": horse_id,
            "horse_name_raw": website_row.get("horse_name"),
            "sex_raw": website_row.get("sex"),
            "age_on_website_raw": website_row.get("age"),
            "rider_raw": website_row.get("rider"),
            "trainer_raw": website_row.get("trainer"),
            "owner_raw": website_row.get("owner"),
            "inspection_reason_raw": website_row.get("inspection_reason"),
            "website_judgement_raw": judgement_raw,
            "website_judgement_category": category,
            "failure_reason_raw": website_row.get("failure_reason"),
            "horse_id_link_basis": "official horse ID extracted from KRA website horse link; no name matching",
            "meet2_is_breed_filter": False,
            "current_api42_breed_raw": breed,
            "current_api42_breed_status": "current_profile_says_jeju_ma" if breed == "제주마" else "not_confirmed_jeju_ma",
            "api42_profile_source": source,
            "api42_profile_observed_at_utc": profile_observed,
            "api42_profile_observation_window_utc": profile_window,
            "api42_profile_response_sha256": profile_hash,
            "api42_profile_raw_path": profile_path,
            "api42_profile_api_record_id": profile_api_record_id,
            "api42_profile_observation_id": profile_observation_id,
            "birth_date_raw": birth_raw,
            "birth_date_validation": birth_validation,
            "birth_year_from_profile": birth_year,
            "age_2026_from_current_api42_birth_date": age_2026,
            "historical_breed_at_exam_date_established": False,
            "website_observation_raw": website_row,
        }
        output_rows.append(row_payload)

        content_fingerprint = sha256_bytes(
            json.dumps(website_row, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        )
        exact_content[content_fingerprint] += 1
        source_key = "|".join(
            [str(website_row.get("date") or ""), str(website_row.get("round") or ""),
             str(website_row.get("horse_number") or ""), horse_id]
        )
        source_keys[source_key] += 1

    if unlinked:
        raise ValueError(f"API42 crosswalk still has {len(unlinked)} unlinked website rows")
    OUTPUT_PATH.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in output_rows),
        encoding="utf-8",
    )

    duplicate_groups = [
        {"content_sha256": digest, "copies": count}
        for digest, count in sorted(exact_content.items())
        if count > 1
    ]
    duplicate_source_keys = [
        {"source_key": key, "copies": count}
        for key, count in sorted(source_keys.items())
        if count > 1
    ]
    summary = {
        "created_at_local_date": "2026-10-02",
        "candidate_source": "KRA starting-exam website observations + current API42 profile observations",
        "api21_source_status": "no_successful_result_rows; service_key_not_registered_error_30",
        "website_source_rows": len(website_rows),
        "candidate_jsonl_rows": len(output_rows),
        "distinct_official_horse_ids": len({str(row.get("horse_id") or "").strip() for row in website_rows}),
        "website_pages_hash_verified": len(artifact_by_name),
        "current_api42_jeju_breed_confirmed_rows": sum(row["current_api42_breed_status"] == "current_profile_says_jeju_ma" for row in output_rows),
        "current_profile_source_row_counts": dict(sorted(profile_source_counts.items())),
        "current_profile_source_distinct_horse_ids": {
            key: len(value) for key, value in sorted(profile_ids_by_source.items())
        },
        "website_event_date_row_counts": dict(sorted(event_date_counts.items())),
        "first_website_event_date": min(event_date_counts) if event_date_counts else None,
        "last_website_event_date": max(event_date_counts) if event_date_counts else None,
        "website_judgement_raw_counts": dict(sorted(judgement_raw_counts.items())),
        "website_judgement_category_counts": dict(sorted(outcome_counts.items())),
        "website_inspection_reason_raw_counts": dict(sorted(inspection_reason_counts.items())),
        "website_failure_reason_raw_counts": dict(sorted(failure_reason_counts.items())),
        "final_pass_only_count": outcome_counts.get("pass", 0),
        "interim_first_stage_pass_count": outcome_counts.get("first_stage_pass", 0),
        "source_key_duplicate_groups": duplicate_source_keys,
        "exact_content_duplicate_groups_preserved": duplicate_groups,
        "duplicates_removed": 0,
        "age_2026_derived_rows": sum(row["age_2026_from_current_api42_birth_date"] is not None for row in output_rows),
        "invalid_birth_date_rows_age_omitted": sum(row["age_2026_from_current_api42_birth_date"] is None for row in output_rows),
        "data_interpretation": "Rows are current-profile-linked website observations, not API21 output. Current API42 breed is not asserted as historically effective on the exam date.",
        "database_write_performed": False,
        "api42_followup_attempt_manifest": manifest_path.relative_to(ROOT).as_posix(),
        "output_file": OUTPUT_PATH.relative_to(ROOT).as_posix(),
        "output_sha256": sha256_bytes(OUTPUT_PATH.read_bytes()),
    }
    SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api42-attempt", help="Use a specific raw/api42_followup attempt ID.")
    args = parser.parse_args()
    build(args.api42_attempt)


if __name__ == "__main__":
    main()
