#!/usr/bin/env python3
"""Stage archived API18 daily-training rows in the Jeju native database.

The loader makes no network requests. It follows the source selector and
page-verification functions in research/20261001_training_audit, verifies all
input hashes, stores every verified Jeju-profile match with its source item
position, and records excluded row counts on the source-page artifacts.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable


HERE = Path(__file__).resolve().parent
JEJU_ROOT = HERE.parents[1]
AUDIT_DIR = JEJU_ROOT / "research/20261001_training_audit"
AUDIT_SCRIPT = AUDIT_DIR / "audit_training_sources.py"
AUDIT_SUMMARY = AUDIT_DIR / "audit_summary.json"
MONTHLY_DIR = JEJU_ROOT / "research/20260929_api_monthly_history"
MONTHLY_LEDGER = MONTHLY_DIR / "ledger.json"
DEFAULT_DB = JEJU_ROOT / "data/jeju_native_core.sqlite3"

ARTIFACT_TABLE = "daily_training_api_artifacts"
ROW_TABLE = "daily_training_api_rows"
ANALYSIS_VIEW = "daily_training_api_rows_analysis_2026"
SCHEMA_VERSION = 1
CUTOFF_DATE = "2026-09-19"
REFERENCE_YEAR = 2026
BATCH_SIZE = 500
PROGRESS_EVERY_PAGES = 50

EXPECTED_PAGE_COUNT = 337
EXPECTED_NONEMPTY_PAGE_COUNT = 263
EXPECTED_EMPTY_PAGE_COUNT = 74
EXPECTED_SOURCE_ROW_COUNT = 1_444_319
EXPECTED_PROFILE_ROW_COUNT = 908_316
EXPECTED_PROFILE_HORSE_COUNT = 4_545
EXPECTED_INVALID_ID_ROW_COUNT = 3
EXPECTED_PROFILE_ROWS_THROUGH_CUTOFF = 907_389
EXPECTED_PROFILE_ROWS_AFTER_CUTOFF = 927
EXPECTED_PROFILE_COUNT = 4_617

RAW_FIELDS = (
    "hrNo", "hrName", "meet", "trDate", "trTerm", "stTime", "spTime",
    "run1Cnt", "run2Cnt", "prGubun", "prNo", "part", "partNo",
    "trName", "chulGubun",
)
RAW_COLUMNS = tuple(f"{field}_raw" for field in RAW_FIELDS)
ROW_COLUMNS = (
    "daily_training_api_artifact_id", "source_row_index",
    *RAW_COLUMNS, "raw_row_json", "horse_id", "horse_profile_observation_id",
    "profile_match_status", "training_date", "start_time_local",
    "start_time_status", "end_time_local", "end_time_status",
    "time_order_status", "duration_seconds", "duration_status",
    "run1_count", "run1_count_status", "run2_count", "run2_count_status",
)
ROW_COMPARE_COLUMNS = ROW_COLUMNS[1:]
ARTIFACT_COMPARE_COLUMNS = (
    "artifact_key", "source_partition_key", "source_page_kind", "page_no",
    "source_file_path", "source_sha256", "ledger_sha256",
    "audit_script_sha256", "audit_summary_sha256", "archive_manifest_path",
    "archive_manifest_sha256", "profile_snapshot_sha256", "source_url_without_key",
    "requested_at_ms", "retrieved_at_ms", "status_code", "api_result_code",
    "raw_item_count", "profile_matched_row_count",
    "excluded_nonprofile_row_count", "quarantined_invalid_id_count",
    "id_status_counts_json", "quality_status_counts_json", "event_date_min",
    "event_date_max",
)


class LoadError(ValueError):
    """A source, schema, or safety validation failure."""


def fail(message: str) -> "NoReturn":
    raise LoadError(message)


def canonical_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        fail(f"source JSON value is not safely serializable: {exc}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_jeju_child(base: Path, relative: str, label: str) -> Path:
    if not isinstance(relative, str) or not relative:
        fail(f"{label} must be a nonempty relative path")
    rel = Path(relative)
    if rel.is_absolute():
        fail(f"{label} must be relative to the archived source directory")
    try:
        base_real = base.resolve(strict=True)
        jeju_real = JEJU_ROOT.resolve(strict=True)
        candidate = (base_real / rel).resolve(strict=True)
        candidate.relative_to(jeju_real)
    except (OSError, ValueError) as exc:
        fail(f"{label} is missing or escapes the Jeju source root: {relative}")
    if not candidate.is_file():
        fail(f"{label} is not a regular file: {relative}")
    return candidate


def safe_relative(path: Path) -> str:
    try:
        return path.resolve(strict=True).relative_to(JEJU_ROOT.resolve(strict=True)).as_posix()
    except (OSError, ValueError):
        fail("resolved source path is outside the Jeju root")


def text_value(value: Any) -> str | None:
    """Store raw scalar values as text; raw_row_json retains original JSON types."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return json.dumps(value, ensure_ascii=False, allow_nan=False)
    fail("daily-training raw field is not a JSON scalar")


def official_id_text(value: Any) -> tuple[str | None, str]:
    """Match integer IDs by their decimal ID spelling and strings without trimming."""
    if isinstance(value, bool) or value is None:
        return None, "invalid_raw_horse_id_format"
    if isinstance(value, int):
        candidate = str(value)
    elif isinstance(value, str):
        candidate = value
    else:
        return None, "invalid_raw_horse_id_format"
    if not candidate or not candidate.isascii() or not candidate.isdigit() or candidate == "0":
        return None, "invalid_raw_horse_id_format"
    return candidate, "valid_id_not_in_profile"


def parse_event_date(value: Any, partition: str, label: str) -> tuple[str, str]:
    raw = text_value(value)
    if raw is None or not re.fullmatch(r"[0-9]{8}", raw, flags=re.ASCII):
        fail(f"invalid event date in {label}")
    try:
        parsed = datetime.strptime(raw, "%Y%m%d").date()
    except ValueError:
        fail(f"invalid calendar date in {label}")
    if len(partition) == 6 and raw[:6] != partition:
        fail(f"event date does not match monthly source partition in {label}")
    if len(partition) == 8 and raw != partition:
        fail(f"event date does not match daily fallback partition in {label}")
    if len(partition) not in (6, 8):
        fail(f"unsupported source partition key in {label}")
    if raw < "20071001" or raw > "20260928":
        fail(f"event date is outside the audited observation range in {label}")
    return raw, parsed.isoformat()


def parse_api_time(value: Any, event_date: str) -> tuple[str | None, str]:
    raw = text_value(value)
    if raw is None or raw in ("", "-"):
        return None, "missing"
    if not re.fullmatch(r"[0-9]{14}", raw, flags=re.ASCII):
        return None, "invalid_format_or_calendar"
    try:
        parsed = datetime.strptime(raw, "%Y%m%d%H%M%S")
    except ValueError:
        return None, "invalid_format_or_calendar"
    if raw[:8] != event_date:
        return None, "date_mismatch"
    return parsed.strftime("%Y-%m-%d %H:%M:%S"), "valid_same_event_date"


def parse_integer_raw(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and re.fullmatch(r"-?[0-9]+", value, flags=re.ASCII):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def normalize_row(row: dict[str, Any], partition: str, source_label: str,
                  profiles: dict[str, dict[str, Any]], artifact_id: int | None = None,
                  item_index: int = 0) -> tuple[dict[str, Any], str, str, dict[str, int]]:
    if not isinstance(row, dict):
        fail(f"API item is not a JSON object in {source_label}")
    unknown = set(row) - set(RAW_FIELDS)
    if unknown:
        fail(f"API item has unexpected raw fields in {source_label}")
    raw_id = row.get("hrNo")
    candidate, id_status = official_id_text(raw_id)
    profile = profiles.get(candidate) if candidate else None
    if profile is not None:
        id_status = "verified_jeju_profile_id"
    elif id_status == "valid_id_not_in_profile":
        id_status = "profile_not_found"

    raw_meet = row.get("meet")
    if raw_meet != "제주":
        fail(f"daily-training source item is not from the Jeju meet in {source_label}")
    date_raw, training_date = parse_event_date(row.get("trDate"), partition, source_label)
    start_local, start_status = parse_api_time(row.get("stTime"), date_raw)
    end_local, end_status = parse_api_time(row.get("spTime"), date_raw)
    start_dt = datetime.strptime(start_local, "%Y-%m-%d %H:%M:%S") if start_local else None
    end_dt = datetime.strptime(end_local, "%Y-%m-%d %H:%M:%S") if end_local else None
    if start_dt is None or end_dt is None:
        order_status = "unavailable"
    elif end_dt < start_dt:
        order_status = "reversed"
    else:
        order_status = "ordered"

    term = parse_integer_raw(row.get("trTerm"))
    duration_seconds: int | None = None
    if term == 0:
        duration_status = "raw_zero_unavailable"
    elif term is None or term < 0:
        duration_status = "missing_or_invalid_raw"
    elif start_dt is None or end_dt is None or order_status != "ordered":
        duration_status = "positive_without_valid_times"
    else:
        delta = int((end_dt - start_dt).total_seconds())
        if delta == term:
            duration_seconds = term
            duration_status = "positive_matches_valid_times"
        else:
            duration_status = "positive_time_mismatch"

    # The audited run-count fields are all zero and are unavailable as counts.
    run1 = parse_integer_raw(row.get("run1Cnt"))
    run2 = parse_integer_raw(row.get("run2Cnt"))
    run1_count = run2_count = None
    run1_status = "all_zero_unavailable" if run1 == 0 else "unvalidated_null"
    run2_status = "all_zero_unavailable" if run2 == 0 else "unvalidated_null"

    quality = Counter({
        f"start_time:{start_status}": 1,
        f"end_time:{end_status}": 1,
        f"time_order:{order_status}": 1,
        f"duration:{duration_status}": 1,
        f"run1_count:{run1_status}": 1,
        f"run2_count:{run2_status}": 1,
    })
    if profile is None:
        return {}, id_status, training_date, dict(quality)

    persisted = {
        "daily_training_api_artifact_id": artifact_id,
        "source_row_index": item_index,
        **{f"{field}_raw": text_value(row.get(field)) for field in RAW_FIELDS},
        "raw_row_json": canonical_json(row),
        "horse_id": candidate,
        "horse_profile_observation_id": profile["horse_profile_observation_id"],
        "profile_match_status": "verified_jeju_profile_id",
        "training_date": training_date,
        "start_time_local": start_local,
        "start_time_status": start_status,
        "end_time_local": end_local,
        "end_time_status": end_status,
        "time_order_status": order_status,
        "duration_seconds": duration_seconds,
        "duration_status": duration_status,
        "run1_count": run1_count,
        "run1_count_status": run1_status,
        "run2_count": run2_count,
        "run2_count_status": run2_status,
    }
    return persisted, id_status, training_date, dict(quality)


def load_profiles(conn: sqlite3.Connection) -> tuple[dict[str, dict[str, Any]], str]:
    rows = conn.execute("""
        WITH ranked AS (
            SELECT horse_id, horse_profile_observation_id, horse_name_raw,
                   birth_date_raw, breed_label_raw,
                   row_number() OVER (
                       PARTITION BY horse_id
                       ORDER BY observed_at_utc DESC, api_record_id DESC
                   ) AS profile_rank
            FROM horse_profile_observations
        )
        SELECT horse_id, horse_profile_observation_id, horse_name_raw,
               birth_date_raw, breed_label_raw
        FROM ranked WHERE profile_rank=1 ORDER BY horse_id
    """).fetchall()
    profiles = {
        row[0]: {
            "horse_profile_observation_id": row[1],
            "horse_name_raw": row[2],
            "birth_date_raw": row[3],
            "breed_label_raw": row[4],
        }
        for row in rows
    }
    if len(profiles) != EXPECTED_PROFILE_COUNT or set(profiles) != {row[0] for row in rows}:
        fail(f"latest API42 profile population must contain {EXPECTED_PROFILE_COUNT} unique horses")
    if any(profile["breed_label_raw"] != "제주마" for profile in profiles.values()):
        fail("latest API42 profile population contains a non-Jeju horse")
    identity = [
        [horse_id, p["horse_profile_observation_id"], p["horse_name_raw"],
         p["birth_date_raw"], p["breed_label_raw"]]
        for horse_id, p in sorted(profiles.items())
    ]
    fingerprint = hashlib.sha256(canonical_json(identity).encode("utf-8")).hexdigest()
    return profiles, fingerprint


def read_source_manifest_hashes() -> dict[str, str]:
    hashes = {
        "daily_training_monthly_ledger": sha256_file(MONTHLY_LEDGER),
        "training_audit_script": sha256_file(AUDIT_SCRIPT),
        "training_audit_summary": sha256_file(AUDIT_SUMMARY),
    }
    return hashes


def import_audit_reference():
    if not AUDIT_SCRIPT.is_file():
        fail("the training audit source selector is missing")
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location("jeju_training_audit_reference", AUDIT_SCRIPT)
    if spec is None or spec.loader is None:
        fail("could not load the training audit source selector")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def archive_manifest_for_month(month: str, ledger: dict[str, Any]) -> tuple[str | None, str | None]:
    partition = ledger.get("partitions", {}).get(f"daily_training:{month}", {})
    prior = partition.get("prior_official_api_archive")
    manifest_rel = prior.get("manifest") if isinstance(prior, dict) else None
    if not manifest_rel:
        return None, None
    path = resolve_jeju_child(MONTHLY_DIR, manifest_rel, "sibling archive manifest")
    return safe_relative(path), sha256_file(path)


def sanitized_source_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    # This archived field is already named "without_key"; drop any credential-like
    # parameter defensively before storing it in a DB or plan report.
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
    parsed = urlsplit(value)
    safe_query = [
        (key, item) for key, item in parse_qsl(parsed.query, keep_blank_values=True)
        if not any(token in key.casefold() for token in ("key", "token", "secret", "credential"))
    ]
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(safe_query), ""))


def source_artifacts(audit_module, ledger: dict[str, Any], input_hashes: dict[str, str],
                     profiles: dict[str, dict[str, Any]],
                     profile_fingerprint: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    selected = None
    for dataset, pages in audit_module.pages_for_sources():
        if dataset == "daily_training":
            selected = pages
            break
    if selected is None:
        fail("audit selector returned no daily-training source")
    if len(selected) != EXPECTED_PAGE_COUNT:
        fail(f"audit selector returned {len(selected)} pages; expected {EXPECTED_PAGE_COUNT}")

    artifacts: list[dict[str, Any]] = []
    overall_rows = matched_rows = invalid_ids = matched_after_cutoff = 0
    matched_horses: set[str] = set()
    nonempty_pages = 0
    all_quality: Counter[str] = Counter()
    native_quality: Counter[str] = Counter()
    id_counts: Counter[str] = Counter()
    payload_bytes = 0
    overall_date_min: str | None = None
    overall_date_max: str | None = None
    archive_manifest_cache: dict[str, tuple[str | None, str | None]] = {}
    for page_number, (base, partition, meta) in enumerate(selected, 1):
        source_label = str(meta.get("response_file", "unknown source page"))
        rows, location = audit_module.checked_rows(base, partition, meta)
        if meta.get("status_code") != 200:
            fail(f"source page is not an HTTP 200 response: {source_label}")
        if len(rows) != meta.get("actual_page_rows"):
            fail(f"verified page row count changed: {source_label}")
        source_hash = location["source_sha256"]
        if source_hash != meta.get("response_sha256"):
            fail(f"page SHA-256 differs from its ledger entry: {source_label}")
        source_path = resolve_jeju_child(base, meta["response_file"], "daily-training page")
        if safe_relative(source_path) != location["source_file"]:
            fail(f"audit selector and checked page paths differ: {source_label}")
        page_no = int(meta.get("page_no", 0))
        if page_no < 1:
            fail(f"invalid source page number: {source_label}")
        public_params = meta.get("public_params") or {}
        fallback_date = public_params.get("tr_date")
        if isinstance(fallback_date, str) and re.fullmatch(r"[0-9]{8}", fallback_date, flags=re.ASCII):
            source_partition_key = fallback_date
            page_kind = "daily_date_fallback"
            if source_partition_key[:6] != partition:
                fail(f"daily fallback date does not match its month partition: {source_label}")
        elif meta["response_file"].startswith("../"):
            source_partition_key = partition
            page_kind = "sibling_month_archive"
            if len(partition) != 6:
                fail(f"sibling archive page has a non-month source partition: {source_label}")
        else:
            source_partition_key = partition
            page_kind = "monthly_archive"
        archive_path, archive_hash = (None, None)
        if page_kind == "sibling_month_archive":
            if partition not in archive_manifest_cache:
                archive_manifest_cache[partition] = archive_manifest_for_month(partition, ledger)
            archive_path, archive_hash = archive_manifest_cache[partition]
            if not archive_path or not archive_hash:
                fail(f"sibling archive manifest is missing for partition {partition}")
        raw_count = len(rows)
        profile_count = excluded_count = quarantine_count = 0
        page_ids: Counter[str] = Counter()
        page_quality: Counter[str] = Counter()
        date_min: str | None = None
        date_max: str | None = None
        for item_index, row in enumerate(rows, 1):
            normalized, id_status, training_date, quality = normalize_row(
                row, source_partition_key, source_label, profiles
            )
            candidate, _ = official_id_text(row.get("hrNo"))
            if normalized:
                profile_count += 1
                matched_horses.add(candidate)
                native_quality.update(quality)
                if training_date <= CUTOFF_DATE:
                    matched_after_cutoff += 1
            else:
                excluded_count += 1
                if id_status == "invalid_raw_horse_id_format":
                    quarantine_count += 1
            page_ids[id_status] += 1
            page_quality.update(quality)
            date_min = training_date if date_min is None else min(date_min, training_date)
            date_max = training_date if date_max is None else max(date_max, training_date)
            overall_date_min = training_date if overall_date_min is None else min(overall_date_min, training_date)
            overall_date_max = training_date if overall_date_max is None else max(overall_date_max, training_date)
            overall_rows += 1
            payload_bytes += len(canonical_json(row).encode("utf-8"))
        matched_rows += profile_count
        invalid_ids += quarantine_count
        all_quality.update(page_quality)
        id_counts.update(page_ids)
        if raw_count:
            nonempty_pages += 1
        artifact_key = f"daily_training:{source_partition_key}:page:{page_no}"
        artifact = {
            "artifact_key": artifact_key,
            "source_partition_key": source_partition_key,
            "source_page_kind": page_kind,
            "page_no": page_no,
            "source_file_path": location["source_file"],
            "source_sha256": source_hash,
            "ledger_sha256": input_hashes["daily_training_monthly_ledger"],
            "audit_script_sha256": input_hashes["training_audit_script"],
            "audit_summary_sha256": input_hashes["training_audit_summary"],
            "archive_manifest_path": archive_path,
            "archive_manifest_sha256": archive_hash,
            "profile_snapshot_sha256": profile_fingerprint,
            "source_url_without_key": sanitized_source_url(meta.get("source_url_without_key")),
            "requested_at_ms": meta.get("requested_at_ms"),
            "retrieved_at_ms": meta.get("retrieved_at_ms"),
            "status_code": meta.get("status_code"),
            "api_result_code": "00",
            "raw_item_count": raw_count,
            "profile_matched_row_count": profile_count,
            "excluded_nonprofile_row_count": excluded_count,
            "quarantined_invalid_id_count": quarantine_count,
            "id_status_counts_json": canonical_json(dict(sorted(page_ids.items()))),
            "quality_status_counts_json": canonical_json(dict(sorted(page_quality.items()))),
            "event_date_min": date_min,
            "event_date_max": date_max,
            "_base": base,
            "_meta": meta,
            "_selector_partition": partition,
        }
        artifacts.append(artifact)
        if page_number % PROGRESS_EVERY_PAGES == 0 or page_number == len(selected):
            print(
                f"source scan: {page_number}/{len(selected)} pages; "
                f"{overall_rows:,} raw rows, {matched_rows:,} profile matches",
                file=sys.stderr, flush=True,
            )

    if overall_rows != EXPECTED_SOURCE_ROW_COUNT:
        fail(f"source scan found {overall_rows:,} rows; expected {EXPECTED_SOURCE_ROW_COUNT:,}")
    if matched_rows != EXPECTED_PROFILE_ROW_COUNT:
        fail(f"profile matching found {matched_rows:,} rows; expected {EXPECTED_PROFILE_ROW_COUNT:,}")
    if len(matched_horses) != EXPECTED_PROFILE_HORSE_COUNT:
        fail(f"profile matching found {len(matched_horses):,} horses; expected {EXPECTED_PROFILE_HORSE_COUNT:,}")
    if invalid_ids != EXPECTED_INVALID_ID_ROW_COUNT:
        fail(f"invalid raw horse ID count is {invalid_ids}; expected {EXPECTED_INVALID_ID_ROW_COUNT}")
    if matched_after_cutoff != EXPECTED_PROFILE_ROWS_THROUGH_CUTOFF:
        fail(f"profile matches through cutoff are {matched_after_cutoff:,}; expected {EXPECTED_PROFILE_ROWS_THROUGH_CUTOFF:,}")
    after_cutoff = matched_rows - matched_after_cutoff
    if after_cutoff != EXPECTED_PROFILE_ROWS_AFTER_CUTOFF:
        fail(f"profile matches after cutoff are {after_cutoff:,}; expected {EXPECTED_PROFILE_ROWS_AFTER_CUTOFF:,}")
    if nonempty_pages != EXPECTED_NONEMPTY_PAGE_COUNT:
        fail(f"nonempty source pages are {nonempty_pages}; expected {EXPECTED_NONEMPTY_PAGE_COUNT}")
    if len(artifacts) - nonempty_pages != EXPECTED_EMPTY_PAGE_COUNT:
        fail("source empty-page count differs from the audited coverage inventory")
    if id_counts["verified_jeju_profile_id"] != EXPECTED_PROFILE_ROW_COUNT:
        fail("source ID status totals disagree with the matched-row count")
    if id_counts["invalid_raw_horse_id_format"] != EXPECTED_INVALID_ID_ROW_COUNT:
        fail("source quarantine status totals disagree with the invalid-ID count")
    if overall_date_min != "2007-10-01" or overall_date_max != "2026-09-28":
        fail("source event-date range differs from the audited daily-training archive")
    if native_quality["duration:positive_matches_valid_times"] != 890_288:
        fail("native positive-duration validation count differs from the independent audit")
    if native_quality["duration:raw_zero_unavailable"] != 18_028:
        fail("native zero-duration unavailable count differs from the independent audit")
    if all_quality["duration:positive_matches_valid_times"] != 1_364_791:
        fail("source positive-duration validation count differs from the independent audit")
    if all_quality["duration:raw_zero_unavailable"] != 79_528:
        fail("source zero-duration count differs from the independent audit")
    fallback_pages = [a for a in artifacts if a["source_page_kind"] == "daily_date_fallback"]
    sibling_pages = [a for a in artifacts if a["source_page_kind"] == "sibling_month_archive"]
    if len(fallback_pages) != 30 or any(a["source_partition_key"][:6] != "201506" for a in fallback_pages):
        fail("the 201506 daily-date fallback page selection differs from the audited source")
    if len(sibling_pages) != 6 or any(a["source_partition_key"] != "202609" for a in sibling_pages):
        fail("the 202609 sibling archive boundary selection differs from the audited source")

    summary = {
        "pages": len(artifacts),
        "nonempty_pages": nonempty_pages,
        "empty_coverage_pages": len(artifacts) - nonempty_pages,
        "source_rows": overall_rows,
        "profile_matched_rows": matched_rows,
        "profile_matched_horses": len(matched_horses),
        "excluded_nonprofile_rows": overall_rows - matched_rows,
        "quarantined_invalid_id_rows": invalid_ids,
        "profile_rows_through_2026_09_19": matched_after_cutoff,
        "profile_rows_after_2026_09_19": after_cutoff,
        "profile_rows_with_usable_duration": native_quality["duration:positive_matches_valid_times"],
        "profile_rows_with_unavailable_zero_duration": native_quality["duration:raw_zero_unavailable"],
        "id_status_counts": dict(sorted(id_counts.items())),
        "quality_status_counts": dict(sorted(all_quality.items())),
        "profile_quality_status_counts": dict(sorted(native_quality.items())),
        "estimated_raw_payload_bytes": payload_bytes,
    }
    return artifacts, summary


def profile_age_sql() -> str:
    return f"""CASE
        WHEN length(trim(profile.birth_date_raw)) >= 4
         AND substr(trim(profile.birth_date_raw), 1, 4) NOT GLOB '*[^0-9]*'
         AND CAST(substr(trim(profile.birth_date_raw), 1, 4) AS INTEGER) BETWEEN 1 AND {REFERENCE_YEAR}
        THEN {REFERENCE_YEAR} - CAST(substr(trim(profile.birth_date_raw), 1, 4) AS INTEGER)
    END"""


def validate_existing_schema(conn: sqlite3.Connection) -> None:
    for name, required in (
        (ARTIFACT_TABLE, set(ARTIFACT_COMPARE_COLUMNS) | {
            "daily_training_api_artifact_id", "inserted_at_utc",
        }),
        (ROW_TABLE, set(ROW_COLUMNS) | {"daily_training_api_row_id"}),
    ):
        found = conn.execute(
            "SELECT type FROM sqlite_master WHERE name=?", (name,)
        ).fetchone()
        if found:
            if found[0] != "table":
                fail(f"existing object {name} is not a table")
            columns = {row[1] for row in conn.execute(f"PRAGMA table_info({name})")}
            if not required.issubset(columns):
                fail(f"existing {name} schema is incompatible with loader version {SCHEMA_VERSION}")
    view = conn.execute(
        "SELECT type FROM sqlite_master WHERE name=?", (ANALYSIS_VIEW,)
    ).fetchone()
    if view and view[0] != "view":
        fail(f"existing object {ANALYSIS_VIEW} is not a view")


def create_schema(conn: sqlite3.Connection) -> None:
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {ARTIFACT_TABLE} (
            daily_training_api_artifact_id INTEGER PRIMARY KEY,
            artifact_key TEXT NOT NULL UNIQUE,
            source_partition_key TEXT NOT NULL,
            source_page_kind TEXT NOT NULL CHECK(source_page_kind IN
                ('monthly_archive','daily_date_fallback','sibling_month_archive')),
            page_no INTEGER NOT NULL CHECK(page_no > 0),
            source_file_path TEXT NOT NULL,
            source_sha256 TEXT NOT NULL CHECK(length(source_sha256)=64),
            ledger_sha256 TEXT NOT NULL CHECK(length(ledger_sha256)=64),
            audit_script_sha256 TEXT NOT NULL CHECK(length(audit_script_sha256)=64),
            audit_summary_sha256 TEXT NOT NULL CHECK(length(audit_summary_sha256)=64),
            archive_manifest_path TEXT,
            archive_manifest_sha256 TEXT,
            profile_snapshot_sha256 TEXT NOT NULL CHECK(length(profile_snapshot_sha256)=64),
            source_url_without_key TEXT,
            requested_at_ms INTEGER,
            retrieved_at_ms INTEGER,
            status_code INTEGER,
            api_result_code TEXT NOT NULL,
            raw_item_count INTEGER NOT NULL CHECK(raw_item_count >= 0),
            profile_matched_row_count INTEGER NOT NULL CHECK(profile_matched_row_count >= 0),
            excluded_nonprofile_row_count INTEGER NOT NULL CHECK(excluded_nonprofile_row_count >= 0),
            quarantined_invalid_id_count INTEGER NOT NULL CHECK(quarantined_invalid_id_count >= 0),
            id_status_counts_json TEXT NOT NULL,
            quality_status_counts_json TEXT NOT NULL,
            event_date_min TEXT,
            event_date_max TEXT,
            inserted_at_utc TEXT NOT NULL,
            UNIQUE(source_partition_key, page_no),
            CHECK(raw_item_count = profile_matched_row_count + excluded_nonprofile_row_count),
            CHECK(quarantined_invalid_id_count <= excluded_nonprofile_row_count),
            CHECK((archive_manifest_path IS NULL AND archive_manifest_sha256 IS NULL) OR
                  (archive_manifest_path IS NOT NULL AND length(archive_manifest_sha256)=64))
        )
    """)
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {ROW_TABLE} (
            daily_training_api_row_id INTEGER PRIMARY KEY,
            daily_training_api_artifact_id INTEGER NOT NULL
                REFERENCES {ARTIFACT_TABLE}(daily_training_api_artifact_id),
            source_row_index INTEGER NOT NULL CHECK(source_row_index > 0),
            hrNo_raw TEXT,
            hrName_raw TEXT,
            meet_raw TEXT,
            trDate_raw TEXT,
            trTerm_raw TEXT,
            stTime_raw TEXT,
            spTime_raw TEXT,
            run1Cnt_raw TEXT,
            run2Cnt_raw TEXT,
            prGubun_raw TEXT,
            prNo_raw TEXT,
            part_raw TEXT,
            partNo_raw TEXT,
            trName_raw TEXT,
            chulGubun_raw TEXT,
            raw_row_json TEXT NOT NULL,
            horse_id TEXT NOT NULL,
            horse_profile_observation_id INTEGER NOT NULL
                REFERENCES horse_profile_observations(horse_profile_observation_id),
            profile_match_status TEXT NOT NULL CHECK(profile_match_status='verified_jeju_profile_id'),
            training_date TEXT NOT NULL CHECK(length(training_date)=10),
            start_time_local TEXT,
            start_time_status TEXT NOT NULL CHECK(start_time_status IN
                ('missing','valid_same_event_date','invalid_format_or_calendar','date_mismatch')),
            end_time_local TEXT,
            end_time_status TEXT NOT NULL CHECK(end_time_status IN
                ('missing','valid_same_event_date','invalid_format_or_calendar','date_mismatch')),
            time_order_status TEXT NOT NULL CHECK(time_order_status IN ('unavailable','ordered','reversed')),
            duration_seconds INTEGER CHECK(duration_seconds IS NULL OR duration_seconds > 0),
            duration_status TEXT NOT NULL CHECK(duration_status IN (
                'raw_zero_unavailable','positive_matches_valid_times','positive_time_mismatch',
                'positive_without_valid_times','missing_or_invalid_raw')),
            run1_count INTEGER,
            run1_count_status TEXT NOT NULL,
            run2_count INTEGER,
            run2_count_status TEXT NOT NULL,
            UNIQUE(daily_training_api_artifact_id, source_row_index),
            CHECK((duration_seconds IS NULL) = (duration_status <> 'positive_matches_valid_times')),
            CHECK(run1_count IS NULL AND run2_count IS NULL)
        )
    """)
    conn.execute(f"CREATE INDEX IF NOT EXISTS idx_daily_training_api_artifacts_partition_page ON {ARTIFACT_TABLE}(source_partition_key, page_no)")
    conn.execute(f"CREATE INDEX IF NOT EXISTS idx_daily_training_api_rows_horse_date ON {ROW_TABLE}(horse_id, training_date)")
    conn.execute(f"CREATE INDEX IF NOT EXISTS idx_daily_training_api_rows_artifact_order ON {ROW_TABLE}(daily_training_api_artifact_id, source_row_index)")
    age_sql = profile_age_sql()
    view_sql = f"""
        CREATE VIEW {ANALYSIS_VIEW} AS
        WITH profile_ranked AS (
            SELECT horse_id, horse_name_raw, birth_date_raw,
                   row_number() OVER (
                       PARTITION BY horse_id
                       ORDER BY observed_at_utc DESC, api_record_id DESC
                   ) AS profile_rank
            FROM horse_profile_observations
        ), profile_current AS (
            SELECT horse_id, horse_name_raw, birth_date_raw,
                   CASE
                     WHEN length(trim(birth_date_raw)) >= 4
                      AND substr(trim(birth_date_raw), 1, 4) NOT GLOB '*[^0-9]*'
                      AND CAST(substr(trim(birth_date_raw), 1, 4) AS INTEGER) BETWEEN 1 AND {REFERENCE_YEAR}
                     THEN CAST(substr(trim(birth_date_raw), 1, 4) AS INTEGER)
                   END AS current_horse_birth_year
            FROM profile_ranked WHERE profile_rank=1
        )
        SELECT r.daily_training_api_row_id, r.daily_training_api_artifact_id,
               r.source_row_index, r.horse_id, profile.horse_name_raw AS current_horse_name,
               profile.current_horse_birth_year,
               {age_sql} AS current_horse_age_2026,
               {REFERENCE_YEAR} AS current_horse_age_reference_year,
               r.training_date, r.hrName_raw AS horse_name_raw,
               r.trTerm_raw AS tr_term_raw, r.duration_seconds,
               CASE WHEN r.duration_seconds IS NOT NULL THEN r.duration_seconds / 60.0 END AS duration_minutes,
               r.duration_status, r.start_time_local, r.end_time_local,
               r.start_time_status, r.end_time_status, r.time_order_status,
               r.run1Cnt_raw, r.run1_count, r.run1_count_status,
               r.run2Cnt_raw, r.run2_count, r.run2_count_status,
               r.prGubun_raw, r.prNo_raw, r.part_raw, r.partNo_raw, r.trName_raw,
               r.chulGubun_raw, r.meet_raw, r.profile_match_status,
               r.horse_profile_observation_id, r.raw_row_json,
               a.source_partition_key, a.source_page_kind, a.page_no,
               a.source_file_path, a.source_sha256, a.requested_at_ms, a.retrieved_at_ms
        FROM {ROW_TABLE} r
        JOIN {ARTIFACT_TABLE} a USING (daily_training_api_artifact_id)
        LEFT JOIN profile_current profile ON profile.horse_id=r.horse_id
        WHERE r.training_date <= '{CUTOFF_DATE}'
    """
    existing = conn.execute("SELECT sql FROM sqlite_master WHERE type='view' AND name=?", (ANALYSIS_VIEW,)).fetchone()
    if existing:
        normalize = lambda value: re.sub(r"\s+", " ", value).strip().lower()
        expected = normalize(view_sql)
        actual = normalize(existing[0])
        if actual != expected:
            fail(f"existing {ANALYSIS_VIEW} definition differs from this loader")
    else:
        conn.execute(view_sql)


def artifact_tuple(artifact: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(artifact[name] for name in ARTIFACT_COMPARE_COLUMNS)


def existing_artifact(conn: sqlite3.Connection, artifact: dict[str, Any]) -> sqlite3.Row | None:
    return conn.execute(
        f"SELECT daily_training_api_artifact_id, {', '.join(ARTIFACT_COMPARE_COLUMNS)} "
        f"FROM {ARTIFACT_TABLE} WHERE artifact_key=?", (artifact["artifact_key"],)
    ).fetchone()


def expected_row_tuple(row: dict[str, Any], artifact_id: int) -> tuple[Any, ...]:
    row["daily_training_api_artifact_id"] = artifact_id
    return tuple(row[name] for name in ROW_COMPARE_COLUMNS)


def stored_rows_for_artifact(conn: sqlite3.Connection, artifact_id: int) -> list[tuple[Any, ...]]:
    query_cols = ", ".join(ROW_COMPARE_COLUMNS)
    result = conn.execute(
        f"SELECT {query_cols} FROM {ROW_TABLE} WHERE daily_training_api_artifact_id=? ORDER BY source_row_index",
        (artifact_id,),
    ).fetchall()
    return [tuple(row) for row in result]


def source_rows_for_artifact(artifact: dict[str, Any], audit_module,
                             profiles: dict[str, dict[str, Any]],
                             artifact_id: int | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    meta = artifact["_meta"]
    rows, location = audit_module.checked_rows(artifact["_base"], artifact["_selector_partition"], meta)
    if location["source_sha256"] != artifact["source_sha256"]:
        fail(f"source page changed after the planning scan: {artifact['source_file_path']}")
    output_rows: list[dict[str, Any]] = []
    page_ids: Counter[str] = Counter()
    page_quality: Counter[str] = Counter()
    for item_index, row in enumerate(rows, 1):
        normalized, id_status, _, quality = normalize_row(
            row, artifact["source_partition_key"], artifact["source_file_path"],
            profiles, artifact_id, item_index,
        )
        page_ids[id_status] += 1
        page_quality.update(quality)
        if normalized:
            output_rows.append(normalized)
    current_metadata = (
        len(rows), len(output_rows), len(rows) - len(output_rows),
        page_ids["invalid_raw_horse_id_format"],
        canonical_json(dict(sorted(page_ids.items()))),
        canonical_json(dict(sorted(page_quality.items()))),
    )
    expected_metadata = (
        artifact["raw_item_count"], artifact["profile_matched_row_count"],
        artifact["excluded_nonprofile_row_count"], artifact["quarantined_invalid_id_count"],
        artifact["id_status_counts_json"], artifact["quality_status_counts_json"],
    )
    if current_metadata != expected_metadata:
        fail(f"source page metadata changed after planning: {artifact['source_file_path']}")
    return output_rows, {"page_ids": page_ids, "page_quality": page_quality}


def verify_replay(conn: sqlite3.Connection, artifact: dict[str, Any], audit_module,
                  profiles: dict[str, dict[str, Any]]) -> bool:
    stored = existing_artifact(conn, artifact)
    if stored is None:
        return False
    artifact_id = stored[0]
    if tuple(stored[1:]) != artifact_tuple(artifact):
        fail(f"artifact identity or metadata conflicts with existing DB row: {artifact['artifact_key']}")
    expected_rows, _ = source_rows_for_artifact(artifact, audit_module, profiles, artifact_id)
    expected_tuples = [expected_row_tuple(row, artifact_id) for row in expected_rows]
    stored_tuples = stored_rows_for_artifact(conn, artifact_id)
    if stored_tuples != expected_tuples:
        fail(f"existing raw/normalized rows differ from source page: {artifact['artifact_key']}")
    return True


def create_backup(conn: sqlite3.Connection, database: Path, required_bytes: int) -> Path:
    free = shutil.disk_usage(database.parent).free
    if free < required_bytes:
        fail(f"insufficient free space for a safe DB backup and import ({free:,} < {required_bytes:,} bytes)")
    stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%S.%fZ")
    backup = database.with_name(database.name + f".pre_daily_training_api_{stamp}.bak")
    if backup.exists():
        fail("backup destination already exists; refusing to overwrite it")
    target = sqlite3.connect(str(backup))
    try:
        conn.backup(target)
        target.commit()
    finally:
        target.close()
    if not backup.is_file() or backup.stat().st_size == 0:
        fail("database backup was not created")
    check = sqlite3.connect(backup.as_uri() + "?mode=ro", uri=True)
    try:
        result = check.execute("PRAGMA quick_check").fetchone()
        if not result or result[0] != "ok":
            fail("database backup did not pass SQLite quick_check")
    finally:
        check.close()
    return backup


def expected_backup_space(database: Path, plan: dict[str, Any]) -> int:
    db_bytes = database.stat().st_size
    payload = int(plan["source_summary"]["estimated_raw_payload_bytes"])
    estimated_growth = max(payload * 4, 128 * 1024 * 1024)
    return db_bytes + estimated_growth + 128 * 1024 * 1024


def insert_artifact(conn: sqlite3.Connection, artifact: dict[str, Any]) -> int:
    names = (*ARTIFACT_COMPARE_COLUMNS, "inserted_at_utc")
    cursor = conn.execute(
        f"INSERT INTO {ARTIFACT_TABLE}({', '.join(names)}) VALUES({','.join('?' for _ in names)})",
        (*artifact_tuple(artifact), datetime.utcnow().isoformat(timespec="microseconds") + "Z"),
    )
    return int(cursor.lastrowid)


def insert_rows(conn: sqlite3.Connection, rows: Iterable[dict[str, Any]]) -> int:
    names = ROW_COLUMNS
    sql = f"INSERT INTO {ROW_TABLE}({', '.join(names)}) VALUES({','.join('?' for _ in names)})"
    batch: list[tuple[Any, ...]] = []
    count = 0
    for row in rows:
        batch.append(tuple(row[name] for name in names))
        if len(batch) >= BATCH_SIZE:
            conn.executemany(sql, batch)
            count += len(batch)
            batch.clear()
    if batch:
        conn.executemany(sql, batch)
        count += len(batch)
    return count


def apply_plan(database: Path, artifacts: list[dict[str, Any]], audit_module,
               profiles: dict[str, dict[str, Any]], plan: dict[str, Any]) -> dict[str, Any]:
    if not database.is_file():
        fail(f"database must be an existing file: {database}")
    conn = sqlite3.connect(str(database), timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    backup_path: str | None = None
    added_artifacts = added_rows = replayed_artifacts = replayed_rows = 0
    try:
        validate_existing_schema(conn)
        present_count = 0
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (ARTIFACT_TABLE,)).fetchone():
            for artifact in artifacts:
                if existing_artifact(conn, artifact) is not None:
                    present_count += 1
        if present_count == len(artifacts):
            # Full source and row comparison on an exact replay; no backup or DB write.
            for index, artifact in enumerate(artifacts, 1):
                if not verify_replay(conn, artifact, audit_module, profiles):
                    fail("artifact disappeared during replay validation")
                replayed_artifacts += 1
                replayed_rows += artifact["profile_matched_row_count"]
                if index % PROGRESS_EVERY_PAGES == 0 or index == len(artifacts):
                    print(f"replay check: {index}/{len(artifacts)} pages", file=sys.stderr, flush=True)
            return {
                "database_write": "no-op_exact_replay",
                "backup_path": None,
                "artifacts_added": 0,
                "rows_added": 0,
                "artifacts_replayed_unchanged": replayed_artifacts,
                "rows_replayed_unchanged": replayed_rows,
            }

        required_bytes = expected_backup_space(database, plan)
        backup_path = str(create_backup(conn, database, required_bytes))
        conn.execute("BEGIN IMMEDIATE")
        validate_existing_schema(conn)
        create_schema(conn)
        for index, artifact in enumerate(artifacts, 1):
            stored = existing_artifact(conn, artifact)
            if stored is not None:
                artifact_id = stored[0]
                if tuple(stored[1:]) != artifact_tuple(artifact):
                    fail(f"artifact identity or metadata conflicts with existing DB row: {artifact['artifact_key']}")
                expected_rows, _ = source_rows_for_artifact(artifact, audit_module, profiles, artifact_id)
                expected_tuples = [expected_row_tuple(row, artifact_id) for row in expected_rows]
                if stored_rows_for_artifact(conn, artifact_id) != expected_tuples:
                    fail(f"existing raw/normalized rows differ from source page: {artifact['artifact_key']}")
                replayed_artifacts += 1
                replayed_rows += len(expected_rows)
            else:
                artifact_id = insert_artifact(conn, artifact)
                expected_rows, _ = source_rows_for_artifact(artifact, audit_module, profiles, artifact_id)
                added = insert_rows(conn, expected_rows)
                if added != artifact["profile_matched_row_count"]:
                    fail(f"insert row count changed for artifact {artifact['artifact_key']}")
                added_artifacts += 1
                added_rows += added
            if index % PROGRESS_EVERY_PAGES == 0 or index == len(artifacts):
                print(
                    f"database load: {index}/{len(artifacts)} pages; "
                    f"{added_rows:,} rows added, {replayed_rows:,} replayed",
                    file=sys.stderr, flush=True,
                )
        bad = conn.execute(f"PRAGMA foreign_key_check({ROW_TABLE})").fetchall()
        if bad:
            fail(f"foreign-key check failed for inserted daily-training rows: {len(bad)} violation(s)")
        counts = conn.execute(f"SELECT COUNT(*) FROM {ROW_TABLE}").fetchone()[0]
        if counts < EXPECTED_PROFILE_ROW_COUNT:
            fail("daily-training table row count is below the audited matched-row population")
        conn.commit()
        return {
            "database_write": "committed",
            "backup_path": backup_path,
            "artifacts_added": added_artifacts,
            "rows_added": added_rows,
            "artifacts_replayed_unchanged": replayed_artifacts,
            "rows_replayed_unchanged": replayed_rows,
            "daily_training_api_rows_total": counts,
        }
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise
    finally:
        conn.close()


def build_plan(database: Path) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any], dict[str, dict[str, Any]], Any]:
    if not database.is_file():
        fail(f"database must be an existing file: {database}")
    if not AUDIT_SUMMARY.is_file() or not MONTHLY_LEDGER.is_file():
        fail("daily-training audit summary or monthly ledger is missing")
    input_hashes = read_source_manifest_hashes()
    audit_module = import_audit_reference()
    audit_summary = json.loads(AUDIT_SUMMARY.read_text(encoding="utf-8"))
    recorded_ledger_hash = audit_summary.get("source_manifest_sha256", {}).get("monthly_ledger")
    if recorded_ledger_hash != input_hashes["daily_training_monthly_ledger"]:
        fail("monthly ledger hash differs from the source audit summary")
    read_conn = sqlite3.connect(database.resolve(strict=True).as_uri() + "?mode=ro", uri=True)
    try:
        profiles, profile_fingerprint = load_profiles(read_conn)
    finally:
        read_conn.close()
    ledger = json.loads(MONTHLY_LEDGER.read_text(encoding="utf-8"))
    artifacts, source_summary = source_artifacts(
        audit_module, ledger, input_hashes, profiles, profile_fingerprint
    )
    page_report = [
        {name: artifact[name] for name in ARTIFACT_COMPARE_COLUMNS}
        for artifact in artifacts
    ]
    plan = {
        "schema_version": SCHEMA_VERSION,
        "dataset": "daily_training",
        "endpoint": "/API18_1/dailyTraining_1",
        "operation": "dailyTraining_1",
        "source_selector": "research/20261001_training_audit/audit_training_sources.py:pages_for_sources",
        "source_page_verifier": "research/20261001_training_audit/audit_training_sources.py:checked_rows",
        "run_type": "apply_ready" if artifacts else "no_pages",
        "database_write": "not_performed_dry_run",
        "database_path": str(database),
        "analysis_cutoff_date_inclusive": CUTOFF_DATE,
        "public_time_status": "event dates and clock times are source fields; first publication time is unknown",
        "model_input_promotion": False,
        "source_manifest_sha256": input_hashes,
        "profile_snapshot_sha256": profile_fingerprint,
        "profile_count": len(profiles),
        "source_summary": source_summary,
        "pages": page_report,
    }
    return artifacts, plan, source_summary, profiles, audit_module


def write_report(path: Path, report: dict[str, Any]) -> None:
    if path.exists():
        fail(f"report output already exists; refusing overwrite: {path}")
    parent = path.parent.resolve(strict=True)
    destination = parent / path.name
    if destination.is_symlink():
        fail("report output must not be a symlink")
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, destination)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path,
                        help="existing Jeju SQLite database or staged database copy")
    parser.add_argument("--apply", action="store_true",
                        help="back up the specified DB and append the verified artifacts and rows")
    parser.add_argument("--report-out", type=Path,
                        help="write the aggregate plan/result JSON to a new path")
    args = parser.parse_args()
    try:
        database = args.db.resolve(strict=True)
        artifacts, report, summary, profiles, audit_module = build_plan(database)
        if args.apply:
            apply_result = apply_plan(database, artifacts, audit_module, profiles, report)
            report.update(apply_result)
        else:
            report["database_write"] = "not_performed_dry_run"
        report["summary"] = summary
        if args.report_out:
            write_report(args.report_out, report)
        print(json.dumps({
            "database_path": report["database_path"],
            "database_write": report["database_write"],
            "summary": summary,
            **({key: report[key] for key in (
                "backup_path", "artifacts_added", "rows_added",
                "artifacts_replayed_unchanged", "rows_replayed_unchanged",
                "daily_training_api_rows_total",
            ) if key in report}),
            "report_out": str(args.report_out) if args.report_out else None,
        }, ensure_ascii=False, sort_keys=True, indent=2))
        return 0
    except (LoadError, OSError, sqlite3.Error, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
