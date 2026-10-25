"""Prepare, validate, and optionally append reviewed daily-training rider links.

Preparation and dry-run modes only read the core DuckDB. ``--apply`` requires
the pre-existing, hash-verified root backup and a passing dry-run report.
"""

from __future__ import annotations

import argparse
import csv
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any

import duckdb


ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
INPUT = OUT / "input"
REPORTS = OUT / "reports"
SCRATCH = OUT / "loader_scratch"
CORE_DIR = ROOT / "thoroughbred/data/core_api_2010_20260929_v1"
CORE_DB = CORE_DIR / "thoroughbred_core.duckdb"
CORE_MANIFEST = CORE_DIR / "manifest.json"
BACKUP_DIR = CORE_DIR / "backups/20261015_before_daily_training_rider_links"
BACKUP_DB = BACKUP_DIR / CORE_DB.name
BACKUP_MANIFEST = BACKUP_DIR / CORE_MANIFEST.name
BACKUP_ATTESTATION = BACKUP_DIR / "backup_pair_attestation.json"
REVIEW = ROOT / "thoroughbred/research/20261015_daily_training_rider_identity_review_v1"
REVIEW_SUMMARY = REVIEW / "summary.json"
REVIEW_INVENTORY = REVIEW / "local_inventory/daily_training_rider_identity_inventory.json"
WEB_ROWS_SOURCE = REVIEW / "web_API_exact_event_rows.jsonl"
WEB_REVIEW_SOURCE = REVIEW / "web_API_exact_event_verification.json"
WEB_CAPTURE_MANIFEST = REVIEW / "official_web/capture_manifest.jsonl"
ROOT_EXPECTED = OUT / "root_expected_mapping_and_unmatched.json"
SCHEMA_SQL = OUT / "schema.sql"
SOURCE_MANIFEST_NAME = "daily_training_rider_name_links_v1"
BASE_DB_SHA256 = "c46286df4773a7ffcea4c7bc431e2cd2a8fc03a4c38fdaa4403bd8f39c2a1668"
BASE_MANIFEST_SHA256 = "6f9c194529709b3db4862ffba0aa34dcda4f58af54d5d322333d6af3ccff7e52"
CONFLICT_OBSERVATION_ID = (
    "api18_1:api18-monthly-m1-202609-fresh-8667fb7f6c:"
    "7c2ef0c7e449dc216e246dd4b6a05eeba3bc806e6239dea181603bf34f305bed:p1:r1345"
)
EXPECTED_COUNTS = {
    "daily_training_rows": 5_173_033,
    "pr_no_absent_rows": 3_383_170,
    "pr_no_present_rows": 1_789_863,
    "distinct_pr_no_present": 352,
    "profile_exact_ids": 282,
    "profile_exact_candidate_rows": 1_599_488,
    "profile_unmatched_ids": 70,
    "profile_unmatched_rows": 190_375,
    "profile_exact_name_linked_rows_after_hold": 1_599_487,
    "conflict_hold_rows": 1,
    "web_exact_event_rows": 1_247,
    "web_exact_name_rows": 347,
    "web_literal_suffix_rows": 51,
    "web_person_name_conflicts": 1,
    "web_role_only_rows": 848,
    "main_objects_before": 208,
    "main_objects_after": 213,
    "source_manifests_before": 27,
    "source_manifests_after": 28,
}
LINK_CSV = "rider_name_links.csv"
LINK_JSON = "rider_name_links.json"
HOLD_CSV = "rider_identity_conflict_holds.csv"
HOLD_JSON = "rider_identity_conflict_holds.json"
UNMATCHED_CSV = "rider_unmatched_ids.csv"
UNMATCHED_JSON = "rider_unmatched_ids.json"
WEB_CSV = "rider_web_event_verification.csv"
WEB_JSON = "rider_web_event_verification.json"
GROUP_CSV = "rider_unmatched_role_region_groups.csv"
GROUP_JSON = "rider_unmatched_role_region_groups.json"
BY_MEET_CSV = "rider_unmatched_by_meet.csv"
BY_MEET_JSON = "rider_unmatched_by_meet.json"
BY_TYPE_CSV = "rider_unmatched_by_rider_type.csv"
BY_TYPE_JSON = "rider_unmatched_by_rider_type.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def write_text_atomic(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", dir=path.parent,
                                     prefix=f".{path.name}.", delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def write_json_atomic(path: Path, value: Any) -> None:
    write_text_atomic(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def write_csv_atomic(path: Path, rows: list[dict[str, Any]], fields: list[str] | None = None) -> None:
    if fields is None:
        fields = list(rows[0]) if rows else []
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8-sig", newline="", dir=path.parent,
                                     prefix=f".{path.name}.", delete=False) as stream:
        temporary = Path(stream.name)
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="raise")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: csv_value(row.get(field)) for field in fields})
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def csv_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return canonical_json(value)
    return str(value)


def write_json_and_csv(stem: str, rows: list[dict[str, Any]]) -> None:
    write_json_atomic(INPUT / f"{stem}.json", rows)
    write_csv_atomic(INPUT / f"{stem}.csv", rows)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def iso_date(value: Any) -> str:
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def sql_placeholders(count: int) -> str:
    if count < 1:
        raise ValueError("expected at least one bound value")
    return ",".join("?" for _ in range(count))


def current_database_identity() -> tuple[str, str, dict[str, Any]]:
    db_hash = sha256_file(CORE_DB)
    manifest_hash = sha256_file(CORE_MANIFEST)
    manifest = load_json(CORE_MANIFEST)
    if db_hash != BASE_DB_SHA256:
        raise ValueError(f"core database differs from pinned baseline: {db_hash}")
    if manifest_hash != BASE_MANIFEST_SHA256:
        raise ValueError(f"core manifest differs from pinned baseline: {manifest_hash}")
    if manifest.get("database_sha256") != BASE_DB_SHA256:
        raise ValueError("core manifest database_sha256 does not match pinned database baseline")
    return db_hash, manifest_hash, manifest


def profile_snapshot_rows(connection: duckdb.DuckDBPyConnection) -> dict[str, dict[str, Any]]:
    rows = connection.execute("""
        SELECT official_id_raw_string, id_json_type, name_snapshot, english_name_snapshot,
               source_service, capture_date, source_file, source_sha256,
               source_page_no, source_item_index_within_page
        FROM person_reference_profile_snapshots
        WHERE entity_type='jockey'
        ORDER BY official_id_raw_string, source_file, source_page_no, source_item_index_within_page
    """).fetchall()
    by_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        record = dict(zip((
            "official_id_raw_string", "id_json_type", "name_snapshot", "english_name_snapshot",
            "source_service", "capture_date", "source_file", "source_sha256",
            "source_page_no", "source_item_index_within_page",
        ), row))
        official_id = record["official_id_raw_string"]
        if not isinstance(official_id, str):
            raise ValueError("official profile ID is not stored as a string")
        if official_id in by_id:
            raise ValueError(f"duplicate jockey profile official ID snapshot: {official_id}")
        by_id[official_id] = record
    return by_id


def source_identifier_stats(connection: duckdb.DuckDBPyConnection,
                            profile_ids: set[str]) -> list[dict[str, Any]]:
    rows = connection.execute("""
        SELECT rider_id_raw, count(*) AS daily_training_rows,
               min(event_date)::VARCHAR AS first_event_date,
               max(event_date)::VARCHAR AS last_event_date,
               count(DISTINCT official_horse_id) AS distinct_horse_count,
               to_json(list_sort(list_distinct(list(meet)))) AS observed_meets_json,
               to_json(list_sort(list_distinct(list(rider_type_raw)))) AS observed_rider_types_json
        FROM daily_training_raw
        WHERE rider_id_raw <> '-'
        GROUP BY rider_id_raw
        ORDER BY rider_id_raw
    """).fetchall()
    stats: list[dict[str, Any]] = []
    for rider_id, rows_n, first_day, last_day, horse_n, meets_raw, types_raw in rows:
        if not isinstance(rider_id, str):
            raise ValueError("daily training prNo is not stored as a string")
        stats.append({
            "rider_id_raw": rider_id,
            "daily_training_rows": int(rows_n),
            "first_event_date": str(first_day),
            "last_event_date": str(last_day),
            "distinct_horse_count": int(horse_n),
            "observed_meets": json.loads(meets_raw),
            "observed_rider_types": json.loads(types_raw),
            "profile_id_matched": rider_id in profile_ids,
        })
    return stats


def unmatched_role_region_groups(connection: duckdb.DuckDBPyConnection,
                                 unmatched_ids: list[str]) -> list[dict[str, Any]]:
    sql = f"""
        SELECT rider_id_raw, rider_type_raw, meet AS meet_raw, count(*) AS row_count,
               min(event_date)::VARCHAR AS first_event_date,
               max(event_date)::VARCHAR AS last_event_date
        FROM daily_training_raw
        WHERE rider_id_raw IN ({sql_placeholders(len(unmatched_ids))})
        GROUP BY rider_id_raw, rider_type_raw, meet
        ORDER BY rider_id_raw, rider_type_raw NULLS FIRST, meet
    """
    rows = connection.execute(sql, unmatched_ids).fetchall()
    return [
        {
            "rider_id_raw": row[0], "rider_type_raw": row[1], "meet_raw": row[2],
            "row_count": int(row[3]), "first_event_date": str(row[4]), "last_event_date": str(row[5]),
        }
        for row in rows
    ]


def aggregate_unmatched(groups: list[dict[str, Any]], key: str, output_key: str) -> list[dict[str, Any]]:
    totals: dict[Any, dict[str, Any]] = {}
    for group in groups:
        value = group[key]
        row = totals.setdefault(value, {output_key: value, "daily_training_rows": 0, "distinct_rider_ids": set()})
        row["daily_training_rows"] += group["row_count"]
        row["distinct_rider_ids"].add(group["rider_id_raw"])
    results = []
    for value, row in sorted(totals.items(), key=lambda item: (item[0] is not None, "" if item[0] is None else str(item[0]))):
        results.append({
            output_key: value,
            "daily_training_rows": row["daily_training_rows"],
            "distinct_rider_ids": len(row["distinct_rider_ids"]),
        })
    return results


def proof_file_records() -> list[dict[str, Any]]:
    paths = [REVIEW_SUMMARY, REVIEW_INVENTORY, WEB_REVIEW_SOURCE, WEB_ROWS_SOURCE, WEB_CAPTURE_MANIFEST]
    records = []
    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(f"missing pinned review proof: {path}")
        records.append({"path": path.relative_to(ROOT).as_posix(), "sha256": sha256_file(path)})
    summary = load_json(REVIEW_SUMMARY)
    expected = {item["path"]: item["sha256"] for item in summary.get("proof_files", [])}
    for record in records:
        if record["path"] in expected and record["sha256"] != expected[record["path"]]:
            raise ValueError(f"review proof hash differs from summary: {record['path']}")
    return records


def prepare_inputs() -> dict[str, Any]:
    db_hash, manifest_hash, _ = current_database_identity()
    INPUT.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(str(CORE_DB), read_only=True)
    try:
        configure_duckdb(connection)
        profiles = profile_snapshot_rows(connection)
        roster_ids = {
            row[0] for row in connection.execute("""
                SELECT entity_id_official_string FROM entity_reference_roster
                WHERE entity_type='jockey'
            """).fetchall()
        }
        daily_ids = {
            row[0] for row in connection.execute("""
                SELECT DISTINCT rider_id_raw FROM daily_training_raw WHERE rider_id_raw <> '-'
            """).fetchall()
        }
        stats = source_identifier_stats(connection, set(profiles))
        stats_by_id = {row["rider_id_raw"]: row for row in stats}
        matched_ids = sorted(daily_ids & profiles.keys())
        unmatched_ids = sorted(daily_ids - profiles.keys())
        if len(daily_ids) != EXPECTED_COUNTS["distinct_pr_no_present"]:
            raise ValueError(f"unexpected count of daily-training prNo values: {len(daily_ids)}")

        mapping_rows = []
        for rider_id in matched_ids:
            profile = profiles[rider_id]
            stat = stats_by_id[rider_id]
            if not profile["name_snapshot"] or not str(profile["name_snapshot"]).strip():
                raise ValueError(f"matched profile name is blank: {rider_id}")
            if profile["source_service"] != "API307/jockeyInfo":
                raise ValueError(f"unexpected profile source for {rider_id}: {profile['source_service']}")
            if profile["source_sha256"] is None or len(profile["source_sha256"]) != 64:
                raise ValueError(f"invalid profile snapshot SHA-256 for {rider_id}")
            if profile["official_id_raw_string"] != rider_id:
                raise ValueError(f"profile identity is not an exact string match: {rider_id}")
            mapping_rows.append({
                "rider_id_raw": rider_id,
                **profile,
                "daily_training_rows": stat["daily_training_rows"],
                "first_event_date": stat["first_event_date"],
                "last_event_date": stat["last_event_date"],
                "distinct_horse_count": stat["distinct_horse_count"],
                "observed_meets": stat["observed_meets"],
                "observed_rider_types": stat["observed_rider_types"],
                "name_basis": "exact string equality: daily_training_raw.rider_id_raw = API307/jockeyInfo profile official_id_raw_string",
                "entity_reference_roster_official_id": rider_id if rider_id in roster_ids else None,
                "identity_limit": "profile name identifies the official ID; it does not establish the rider's role or profile status on the training date",
            })

        unmatched_summary = []
        for rider_id in unmatched_ids:
            stat = stats_by_id[rider_id]
            unmatched_summary.append({
                "rider_id_raw": rider_id,
                "daily_training_rows": stat["daily_training_rows"],
                "first_event_date": stat["first_event_date"],
                "last_event_date": stat["last_event_date"],
                "distinct_horse_count": stat["distinct_horse_count"],
                "observed_meets": stat["observed_meets"],
                "observed_rider_types": stat["observed_rider_types"],
                "identity_status": "profile_id_unmatched",
                "review_note": "No exact API307 official jockey profile ID match; preserve raw prNo, prGubun, and trName without inferring identity or role.",
            })

        event_rows = []
        for line in WEB_ROWS_SOURCE.read_text(encoding="utf-8").splitlines():
            if line.strip():
                event_rows.append(json.loads(line))
        if len(event_rows) != EXPECTED_COUNTS["web_exact_event_rows"]:
            raise ValueError(f"web event proof has {len(event_rows)} rows, expected 1247")
        event_ids = [row.get("observation_id") for row in event_rows]
        if len(set(event_ids)) != len(event_ids) or any(not value for value in event_ids):
            raise ValueError("web event evidence observation IDs are missing or duplicated")
        if CONFLICT_OBSERVATION_ID not in set(event_ids):
            raise ValueError("the approved source conflict observation is absent from web evidence")
        link_by_id = {row["rider_id_raw"]: row for row in mapping_rows}
        conflict_event = next(row for row in event_rows if row["observation_id"] == CONFLICT_OBSERVATION_ID)
        profile_candidate = link_by_id.get(conflict_event["rider_id_raw"])
        if not profile_candidate:
            raise ValueError("conflict prNo does not have the expected exact profile candidate")
        if (conflict_event["rider_id_raw"] != "080608"
                or profile_candidate["name_snapshot"] != "오수철"
                or conflict_event["web_rider_display_raw"] != "유승완"
                or conflict_event["horse_name_raw"] != "송당스카이"
                or conflict_event["meet"] != "1"
                or conflict_event["started_at_raw"] != "20260928061000"
                or conflict_event["ended_at_raw"] != "20260928062200"):
            raise ValueError(" 송당스카이 conflict evidence differs from the reviewed single-event exception")

        hold_row = {
            "observation_id": CONFLICT_OBSERVATION_ID,
            "rider_id_raw": conflict_event["rider_id_raw"],
            "rider_type_raw": conflict_event["rider_type_raw"],
            "event_date": conflict_event["event_date"],
            "meet_raw": conflict_event["meet"],
            "official_horse_id": conflict_event["official_horse_id"],
            "horse_name_raw": conflict_event["horse_name_raw"],
            "started_at_raw": conflict_event["started_at_raw"],
            "ended_at_raw": conflict_event["ended_at_raw"],
            "api_profile_name_candidate": profile_candidate["name_snapshot"],
            "web_rider_display_raw": conflict_event["web_rider_display_raw"],
            "api_raw_path": conflict_event["raw_path"],
            "api_raw_sha256": conflict_event["raw_sha256"],
            "api_source_row_no": conflict_event["source_row_no"],
            "profile_source_service": profile_candidate["source_service"],
            "profile_capture_date": profile_candidate["capture_date"],
            "profile_source_file": profile_candidate["source_file"],
            "profile_source_sha256": profile_candidate["source_sha256"],
            "web_source_html_sha256": conflict_event["source_HTML_sha256"],
            "web_event_rows_path": WEB_ROWS_SOURCE.relative_to(ROOT).as_posix(),
            "web_verification_path": WEB_REVIEW_SOURCE.relative_to(ROOT).as_posix(),
            "hold_reason": "One event only: API prNo 080608 matches profile candidate 오수철 while the official daily-training page displays 유승완; source conflict is unresolved.",
            "evidence": {
                "api_observation": conflict_event,
                "profile_candidate": profile_candidate,
                "web_verification_issue": {
                    "type": "web_person_name_vs_exact_ID_profile_conflict",
                    "web": "유승완",
                    "profile_names": ["오수철"],
                },
            },
        }
        event_file_hash = sha256_file(WEB_ROWS_SOURCE)
        verification_file_hash = sha256_file(WEB_REVIEW_SOURCE)
        hold_row["web_event_rows_sha256"] = event_file_hash
        hold_row["web_verification_sha256"] = verification_file_hash
        hold_rows = [hold_row]

        group_rows = unmatched_role_region_groups(connection, unmatched_ids)
        by_meet = aggregate_unmatched(group_rows, "meet_raw", "meet_raw")
        by_type = aggregate_unmatched(group_rows, "rider_type_raw", "rider_type_raw")
        write_json_and_csv("rider_name_links", mapping_rows)
        write_json_and_csv("rider_identity_conflict_holds", hold_rows)
        write_json_and_csv("rider_unmatched_ids", unmatched_summary)
        write_json_and_csv("rider_unmatched_role_region_groups", group_rows)
        write_json_and_csv("rider_unmatched_by_meet", by_meet)
        write_json_and_csv("rider_unmatched_by_rider_type", by_type)
        write_json_atomic(INPUT / WEB_JSON, event_rows)
        write_csv_atomic(INPUT / WEB_CSV, event_rows)
    finally:
        connection.close()

    # Keep the original evidence row file byte-for-byte under the new input directory.
    copied_web_rows = INPUT / "web_API_exact_event_rows.jsonl"
    shutil.copyfile(WEB_ROWS_SOURCE, copied_web_rows)
    if sha256_file(copied_web_rows) != sha256_file(WEB_ROWS_SOURCE):
        raise ValueError("byte-for-byte copy of the original web/API JSONL proof failed")
    proof_files = proof_file_records()
    artifact_names = (
        LINK_JSON, LINK_CSV, HOLD_JSON, HOLD_CSV, UNMATCHED_JSON, UNMATCHED_CSV,
        GROUP_JSON, GROUP_CSV, BY_MEET_JSON, BY_MEET_CSV, BY_TYPE_JSON, BY_TYPE_CSV,
        WEB_JSON, WEB_CSV, "web_API_exact_event_rows.jsonl",
    )
    artifact_paths = [INPUT / name for name in artifact_names]
    missing_artifacts = [path.name for path in artifact_paths if not path.is_file()]
    if missing_artifacts:
        raise FileNotFoundError(f"prepared input artifacts are missing: {missing_artifacts}")
    input_manifest = {
        "schema_version": "daily_training_rider_links_v1",
        "prepared_date": "2026-10-15",
        "source_database": CORE_DB.relative_to(ROOT).as_posix(),
        "baseline_database_sha256": db_hash,
        "baseline_core_manifest_sha256": manifest_hash,
        "identity_join_rule": "Exact string equality only: raw daily-training prNo to API307/jockeyInfo profile official_id_raw_string; no casts, trimming, name joins, owner/trainer substitution, or guessed IDs.",
        "source_identity_columns": ["daily_training_raw.rider_id_raw", "daily_training_raw.rider_type_raw", "daily_training_raw.trainer_name_raw"],
        "source_profile_snapshot": "person_reference_profile_snapshots (entity_type=jockey); the snapshot rows and source file/hash metadata are retained in the input mapping because the original API307 payload files are not included as loader inputs.",
        "source_tables": ["daily_training_raw", "person_reference_profile_snapshots", "entity_reference_roster"],
        "row_counts": {
            "daily_training_rows": EXPECTED_COUNTS["daily_training_rows"],
            "daily_training_distinct_non_sentinel_pr_no": len(daily_ids),
            "name_link_candidates": len(mapping_rows),
            "unmatched_pr_no": len(unmatched_summary),
            "conflict_holds": len(hold_rows),
            "web_event_verification_rows": len(event_rows),
            "unmatched_role_region_groups": len(group_rows),
        },
        "evidence_files": proof_files,
        "files": [],
    }
    for path in artifact_paths:
        input_manifest["files"].append({
            "path": path.relative_to(ROOT).as_posix(),
            "sha256": sha256_file(path),
            "rows": file_row_count(path),
        })
    write_json_atomic(INPUT / "rider_link_input_manifest.json", input_manifest)
    return {
        "status": "inputs_prepared",
        "applied": False,
        "database_sha256": db_hash,
        "manifest_sha256": manifest_hash,
        "input_manifest": (INPUT / "rider_link_input_manifest.json").relative_to(ROOT).as_posix(),
        "input_files": input_manifest["files"],
        "proof_files": proof_files,
        "mapping_rows": len(mapping_rows),
        "unmatched_ids": len(unmatched_summary),
        "conflict_holds": len(hold_rows),
        "web_event_rows": len(event_rows),
    }


def file_row_count(path: Path) -> int | None:
    if path.suffix == ".jsonl":
        return sum(1 for line in path.open(encoding="utf-8") if line.strip())
    if path.suffix == ".json":
        value = load_json(path)
        return len(value) if isinstance(value, list) else None
    if path.suffix == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as stream:
            return max(0, sum(1 for _ in csv.reader(stream)) - 1)
    return None


def verify_csv_mirror(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        actual = list(csv.DictReader(stream))
    expected = [{key: csv_value(value) for key, value in row.items()} for row in rows]
    if actual != expected:
        raise ValueError(f"CSV mirror differs from its JSON rows: {path.name}")


def load_inputs() -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    input_manifest = load_json(INPUT / "rider_link_input_manifest.json")
    if input_manifest.get("baseline_database_sha256") != BASE_DB_SHA256:
        raise ValueError("input manifest is pinned to a different core database")
    for item in input_manifest.get("files", []):
        path = pinned_root_file(item.get("path"))
        if not path.is_file() or sha256_file(path) != item["sha256"]:
            raise ValueError(f"pinned input file hash mismatch: {item['path']}")
        if file_row_count(path) != item["rows"]:
            raise ValueError(f"pinned input row-count mismatch: {item['path']}")
    for item in input_manifest.get("evidence_files", []):
        path = pinned_root_file(item.get("path"))
        if not path.is_file() or sha256_file(path) != item["sha256"]:
            raise ValueError(f"review evidence hash mismatch: {item['path']}")
    sources: dict[str, list[dict[str, Any]]] = {}
    for stem in (
        "rider_name_links", "rider_identity_conflict_holds", "rider_unmatched_ids",
        "rider_unmatched_role_region_groups", "rider_unmatched_by_meet",
        "rider_unmatched_by_rider_type",
    ):
        rows = load_json(INPUT / f"{stem}.json")
        if not isinstance(rows, list):
            raise ValueError(f"expected a row list: {stem}.json")
        verify_csv_mirror(INPUT / f"{stem}.csv", rows)
        sources[stem] = rows
    event_rows = load_json(INPUT / WEB_JSON)
    if not isinstance(event_rows, list):
        raise ValueError("web event JSON input is not an array")
    verify_csv_mirror(INPUT / WEB_CSV, event_rows)
    original_jsonl = INPUT / "web_API_exact_event_rows.jsonl"
    if not original_jsonl.is_file() or sha256_file(original_jsonl) != sha256_file(WEB_ROWS_SOURCE):
        raise ValueError("byte-for-byte copy of the original web/API JSONL proof is absent or changed")
    if len(sources["rider_name_links"]) != 282 or len(sources["rider_unmatched_ids"]) != 70:
        raise ValueError("expected mapping/unmatched input rows are not 282/70")
    if len(sources["rider_identity_conflict_holds"]) != 1 or len(event_rows) != 1247:
        raise ValueError("expected conflict/web event input rows are not 1/1247")
    all_prnos = {row["rider_id_raw"] for row in sources["rider_name_links"]}
    all_prnos |= {row["rider_id_raw"] for row in sources["rider_unmatched_ids"]}
    if len(all_prnos) != 352:
        raise ValueError("mapping and unmatched prNo lists are not disjoint/exhaustive")
    if not all(row["rider_id_raw"] == row["official_id_raw_string"] for row in sources["rider_name_links"]):
        raise ValueError("one or more candidate IDs were not copied as exact strings")
    if any(not isinstance(row["rider_id_raw"], str) for row in sources["rider_name_links"] + sources["rider_unmatched_ids"]):
        raise ValueError("prNo input values must remain strings")
    return input_manifest, sources, event_rows


def root_expected_comparison(input_rows: dict[str, list[dict[str, Any]]],
                             group_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    if not ROOT_EXPECTED.is_file():
        raise FileNotFoundError(f"root's independent expected output is missing: {ROOT_EXPECTED}")
    expected = load_json(ROOT_EXPECTED)
    if expected.get("baseline_sha256") != BASE_DB_SHA256:
        raise ValueError("root expected output is pinned to a different database baseline")
    actual_by_id: dict[str, dict[str, Any]] = {}
    for row in input_rows["rider_name_links"]:
        actual_by_id[row["rider_id_raw"]] = {
            "kind": "mapping", "rows": row["daily_training_rows"],
            "first_date": row["first_event_date"], "last_date": row["last_event_date"],
            "roles": row["observed_rider_types"], "source_meets": row["observed_meets"],
            "name": row["name_snapshot"],
        }
    for row in input_rows["rider_unmatched_ids"]:
        actual_by_id[row["rider_id_raw"]] = {
            "kind": "unmatched", "rows": row["daily_training_rows"],
            "first_date": row["first_event_date"], "last_date": row["last_event_date"],
            "roles": row["observed_rider_types"], "source_meets": row["observed_meets"],
            "name": None,
        }
    per_id = []
    mismatches = 0
    for kind, group in (("mapping", expected.get("mapping", [])), ("unmatched", expected.get("unmatched", []))):
        for row in group:
            number = row["number"]
            actual = actual_by_id.get(number)
            matches = bool(actual and actual["kind"] == kind
                           and actual["rows"] == row["rows"]
                           and actual["first_date"] == row["first_date"]
                           and actual["last_date"] == row["last_date"]
                           and sorted(actual["roles"], key=lambda x: "" if x is None else str(x))
                               == sorted(row["roles"], key=lambda x: "" if x is None else str(x))
                           and sorted(actual["source_meets"]) == sorted(row["source_meets"])
                           and actual["name"] == row.get("name"))
            if not matches:
                mismatches += 1
            per_id.append({
                "rider_id_raw": number,
                "status": "match" if matches else "mismatch_or_missing",
                "kind": kind,
                "expected_rows": row["rows"], "actual_rows": actual["rows"] if actual else None,
                "expected_first_date": row["first_date"], "actual_first_date": actual["first_date"] if actual else None,
                "expected_last_date": row["last_date"], "actual_last_date": actual["last_date"] if actual else None,
                "expected_roles_json": row["roles"], "actual_roles_json": actual["roles"] if actual else None,
                "expected_meets_json": row["source_meets"], "actual_meets_json": actual["source_meets"] if actual else None,
                "expected_name": row.get("name"), "actual_name": actual["name"] if actual else None,
            })
    if len(actual_by_id) != len(expected.get("mapping", [])) + len(expected.get("unmatched", [])):
        mismatches += abs(len(actual_by_id) - len(per_id))
    expected_groups = {
        (row["rider_id_raw"], row["rider_type_raw"], row["meet"], int(row["n"]), row["first_date"], row["last_date"])
        for row in expected.get("unmatched_role_region_groups", [])
    }
    actual_groups = {
        (row["rider_id_raw"], row["rider_type_raw"], row["meet_raw"], row["row_count"], row["first_event_date"], row["last_event_date"])
        for row in group_rows
    }
    group_comp = []
    for key in sorted(expected_groups | actual_groups, key=lambda x: tuple("" if v is None else str(v) for v in x)):
        in_expected, in_actual = key in expected_groups, key in actual_groups
        group_comp.append({
            "rider_id_raw": key[0], "rider_type_raw": key[1], "meet_raw": key[2],
            "row_count": key[3], "first_event_date": key[4], "last_event_date": key[5],
            "expected_present": in_expected, "actual_present": in_actual,
            "status": "match" if in_expected and in_actual else "missing_from_expected_or_actual",
        })
    group_mismatches = sum(1 for row in group_comp if row["status"] != "match")
    return per_id, group_comp, {
        "status": "passed" if mismatches == 0 and group_mismatches == 0 else "failed",
        "expected_file": ROOT_EXPECTED.relative_to(ROOT).as_posix(),
        "expected_file_sha256": sha256_file(ROOT_EXPECTED),
        "mapping_rows_expected": len(expected.get("mapping", [])),
        "unmatched_rows_expected": len(expected.get("unmatched", [])),
        "role_region_groups_expected": len(expected.get("unmatched_role_region_groups", [])),
        "mapping_unmatched_mismatches": mismatches,
        "role_region_group_mismatches": group_mismatches,
    }


def expected_event_status(row: dict[str, Any]) -> str:
    if row["observation_id"] == CONFLICT_OBSERVATION_ID:
        return "exact_event_web_name_conflicts_profile_hold"
    if not row.get("web_person_name_present"):
        return "exact_event_web_role_only_no_person_name"
    if row.get("web_name_differs_only_by_literal_suffix"):
        return "exact_event_web_name_differs_by_literal_suffix"
    if row.get("web_name_in_profile_exact_ID_candidates"):
        return "exact_event_web_person_name_matches_profile"
    return "exact_event_web_name_not_resolved_to_profile"


def insert_staged_rows(connection: duckdb.DuckDBPyConnection,
                       sources: dict[str, list[dict[str, Any]]],
                       event_rows: list[dict[str, Any]]) -> None:
    mappings = sources["rider_name_links"]
    mapping_columns = [
        "rider_id_raw", "official_id_raw_string", "name_snapshot", "english_name_snapshot",
        "name_basis", "source_service", "capture_date", "source_file", "source_sha256",
        "source_page_no", "source_item_index_within_page", "entity_reference_roster_official_id", "identity_limit",
    ]
    mapping_values = [(
        row["rider_id_raw"], row["official_id_raw_string"], row["name_snapshot"], row["english_name_snapshot"],
        row["name_basis"], row["source_service"], date.fromisoformat(row["capture_date"]), row["source_file"],
        row["source_sha256"], row["source_page_no"], row["source_item_index_within_page"],
        row["entity_reference_roster_official_id"], row["identity_limit"],
    ) for row in mappings]
    insert_values(connection, "rider_name_links", [
        "rider_id_raw", "official_jockey_id_raw_string", "name_snapshot", "english_name_snapshot", "name_basis",
        "source_service", "source_capture_date", "source_file", "source_sha256", "source_page_no",
        "source_item_index_within_page", "entity_reference_roster_official_id", "identity_limit",
    ], mapping_values)

    hold_rows = sources["rider_identity_conflict_holds"]
    hold_columns = [
        "observation_id", "rider_id_raw", "rider_type_raw", "event_date", "meet_raw", "official_horse_id",
        "horse_name_raw", "started_at_raw", "ended_at_raw", "api_profile_name_candidate", "web_rider_display_raw",
        "api_raw_path", "api_raw_sha256", "api_source_row_no", "profile_source_service", "profile_capture_date",
        "profile_source_file", "profile_source_sha256", "web_source_html_sha256", "web_event_rows_path",
        "web_event_rows_sha256", "web_verification_path", "web_verification_sha256", "hold_reason", "evidence_json",
    ]
    hold_values = [(
        row["observation_id"], row["rider_id_raw"], row["rider_type_raw"], date.fromisoformat(row["event_date"]),
        row["meet_raw"], row["official_horse_id"], row["horse_name_raw"], row["started_at_raw"], row["ended_at_raw"],
        row["api_profile_name_candidate"], row["web_rider_display_raw"], row["api_raw_path"], row["api_raw_sha256"],
        row["api_source_row_no"], row["profile_source_service"], date.fromisoformat(row["profile_capture_date"]),
        row["profile_source_file"], row["profile_source_sha256"], row["web_source_html_sha256"],
        row["web_event_rows_path"], row["web_event_rows_sha256"], row["web_verification_path"],
        row["web_verification_sha256"], row["hold_reason"], canonical_json(row["evidence"]),
    ) for row in hold_rows]
    insert_values(connection, "rider_identity_conflict_holds", hold_columns, hold_values)

    unmatched = sources["rider_unmatched_ids"]
    unmatched_columns = [
        "rider_id_raw", "daily_training_rows", "first_event_date", "last_event_date", "distinct_horse_count",
        "observed_meets_json", "observed_rider_types_json", "identity_status", "review_note",
    ]
    unmatched_values = [(
        row["rider_id_raw"], row["daily_training_rows"], date.fromisoformat(row["first_event_date"]),
        date.fromisoformat(row["last_event_date"]), row["distinct_horse_count"], canonical_json(row["observed_meets"]),
        canonical_json(row["observed_rider_types"]), row["identity_status"], row["review_note"],
    ) for row in unmatched]
    insert_values(connection, "rider_unmatched_ids", unmatched_columns, unmatched_values)

    web_columns = [
        "observation_id", "event_date", "meet_raw", "official_horse_id", "api_rider_id_raw", "api_rider_type_raw",
        "api_started_at_raw", "api_ended_at_raw", "web_row_no", "web_rider_display_raw", "web_person_name_present",
        "web_name_matches_profile_exact_id", "web_name_differs_only_by_literal_suffix", "stable_metadata_differs",
        "event_verification_status", "web_html_sha256", "api_raw_path", "api_raw_sha256", "api_source_row_no",
        "matching_rule", "time_precision_note", "source_record_json",
    ]
    web_values = [(
        row["observation_id"], date.fromisoformat(row["event_date"]), row["meet"], row["official_horse_id"],
        row.get("rider_id_raw"), row.get("rider_type_raw"), row.get("started_at_raw"), row.get("ended_at_raw"),
        row.get("web_row_no"), row.get("web_rider_display_raw"), bool(row.get("web_person_name_present")),
        row.get("web_name_in_profile_exact_ID_candidates"), bool(row.get("web_name_differs_only_by_literal_suffix")),
        bool(row.get("stable_metadata_differs")), expected_event_status(row), row["source_HTML_sha256"],
        row["raw_path"], row["raw_sha256"], row["source_row_no"], row["matching_rule"], row["time_precision_note"],
        canonical_json(row),
    ) for row in event_rows]
    insert_values(connection, "rider_web_event_verification", web_columns, web_values)


def insert_values(connection: duckdb.DuckDBPyConnection, table: str,
                  columns: list[str], values: list[tuple[Any, ...]]) -> None:
    column_sql = ", ".join(f'"{column}"' for column in columns)
    placeholders = sql_placeholders(len(columns))
    connection.executemany(f"INSERT INTO {table} ({column_sql}) VALUES ({placeholders})", values)


def create_schema(connection: duckdb.DuckDBPyConnection) -> None:
    sql_text = SCHEMA_SQL.read_text(encoding="utf-8")
    for statement in (part.strip() for part in sql_text.split(";")):
        if statement:
            connection.execute(statement)


def object_catalog(connection: duckdb.DuckDBPyConnection) -> dict[str, str]:
    rows = connection.execute("""
        SELECT table_schema, table_name, table_type
        FROM information_schema.tables
        WHERE table_catalog=current_database() AND table_schema='main'
        ORDER BY table_schema, table_name
    """).fetchall()
    return {f"{schema}.{name}": kind for schema, name, kind in rows}


def catalog_signature(connection: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    objects = object_catalog(connection)
    columns: dict[str, list[tuple[Any, ...]]] = {}
    for schema, name, _kind in connection.execute("""
        SELECT table_schema, table_name, table_type FROM information_schema.tables
        WHERE table_catalog=current_database() AND table_schema='main'
        ORDER BY table_schema, table_name
    """).fetchall():
        rows = connection.execute("""
            SELECT column_name, data_type, is_nullable, ordinal_position
            FROM information_schema.columns
            WHERE table_catalog=current_database() AND table_schema=? AND table_name=?
            ORDER BY ordinal_position
        """, [schema, name]).fetchall()
        columns[f"{schema}.{name}"] = rows
    view_sql = connection.execute("""
        SELECT schema_name, view_name, sql FROM duckdb_views()
        WHERE database_name=current_database() AND schema_name='main' AND NOT internal
        ORDER BY schema_name, view_name
    """).fetchall()
    return {"objects": objects, "columns": columns, "view_sql": view_sql}


def check(connection: duckdb.DuckDBPyConnection, checks: list[dict[str, Any]],
          name: str, expected: Any, actual: Any) -> None:
    checks.append({"name": name, "status": "passed" if actual == expected else "failed",
                   "expected": expected, "actual": actual})


def populate_memory_and_validate(input_manifest: dict[str, Any],
                                 sources: dict[str, list[dict[str, Any]]],
                                 event_rows: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    connection = duckdb.connect(":memory:")
    try:
        configure_duckdb(connection)
        connection.execute(f"ATTACH DATABASE {sql_literal(str(CORE_DB.resolve()))} AS core_db (READ_ONLY)")
        connection.execute("CREATE TEMP VIEW daily_training_raw AS SELECT * FROM core_db.daily_training_raw")
        connection.execute("CREATE TEMP VIEW person_reference_profile_snapshots AS SELECT * FROM core_db.person_reference_profile_snapshots")
        connection.execute("CREATE TEMP VIEW entity_reference_roster AS SELECT * FROM core_db.entity_reference_roster")
        create_schema(connection)
        insert_staged_rows(connection, sources, event_rows)
        metrics, checks = validate_loaded_state(connection, sources, event_rows, input_manifest)
        source_objects = int(connection.execute("""
            SELECT count(*) FROM information_schema.tables
            WHERE table_catalog='core_db' AND table_schema='main'
        """).fetchone()[0])
        source_manifest_rows = int(connection.execute("SELECT count(*) FROM core_db.source_manifests").fetchone()[0])
        check(connection, checks, "source_main_object_count_before", 208, source_objects)
        check(connection, checks, "source_manifest_rows_before", 27, source_manifest_rows)
        metrics["source_main_objects_before"] = source_objects
        metrics["source_manifests_before"] = source_manifest_rows
        return metrics, checks
    finally:
        connection.close()


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def configure_duckdb(connection: duckdb.DuckDBPyConnection) -> None:
    SCRATCH.mkdir(parents=True, exist_ok=True)
    connection.execute("SET threads=2")
    connection.execute("SET memory_limit='2GB'")
    connection.execute(f"SET temp_directory={sql_literal(str(SCRATCH.resolve()))}")


def pinned_root_file(relative_path: Any) -> Path:
    if not isinstance(relative_path, str) or not relative_path:
        raise ValueError("input manifest paths must be non-empty relative strings")
    relative = Path(relative_path)
    if relative.is_absolute():
        raise ValueError(f"input manifest path must be relative to repository root: {relative_path}")
    root = ROOT.resolve()
    candidate = (root / relative).resolve(strict=True)
    if not candidate.is_relative_to(root):
        raise ValueError(f"input manifest path escapes repository root: {relative_path}")
    return candidate


def validate_loaded_state(connection: duckdb.DuckDBPyConnection,
                          sources: dict[str, list[dict[str, Any]]],
                          event_rows: list[dict[str, Any]],
                          input_manifest: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    checks: list[dict[str, Any]] = []
    counts = {
        "daily_training_rows": connection.execute("SELECT count(*) FROM daily_training_raw").fetchone()[0],
        "pr_no_absent_rows": connection.execute("SELECT count(*) FROM daily_training_raw WHERE rider_id_raw='-'").fetchone()[0],
        "pr_no_present_rows": connection.execute("SELECT count(*) FROM daily_training_raw WHERE rider_id_raw<>'-'").fetchone()[0],
        "distinct_pr_no_present": connection.execute("SELECT count(DISTINCT rider_id_raw) FROM daily_training_raw WHERE rider_id_raw<>'-'").fetchone()[0],
        "profile_exact_ids": connection.execute("SELECT count(*) FROM rider_name_links").fetchone()[0],
        "profile_exact_candidate_rows": connection.execute("SELECT count(*) FROM daily_training_rider_linked WHERE rider_name_candidate IS NOT NULL").fetchone()[0],
        "profile_unmatched_ids": connection.execute("SELECT count(*) FROM rider_unmatched_ids").fetchone()[0],
        "profile_unmatched_rows": connection.execute("SELECT count(*) FROM daily_training_rider_linked WHERE rider_identity_status='profile_id_unmatched'").fetchone()[0],
        "profile_exact_name_linked_rows_after_hold": connection.execute("SELECT count(*) FROM daily_training_rider_linked WHERE rider_name_linked IS NOT NULL").fetchone()[0],
        "conflict_hold_rows": connection.execute("SELECT count(*) FROM rider_identity_conflict_holds").fetchone()[0],
        "web_exact_event_rows": connection.execute("SELECT count(*) FROM rider_web_event_verification").fetchone()[0],
        "web_exact_name_rows": connection.execute("SELECT count(*) FROM rider_web_event_verification WHERE web_person_name_present AND web_name_matches_profile_exact_id AND NOT web_name_differs_only_by_literal_suffix").fetchone()[0],
        "web_literal_suffix_rows": connection.execute("SELECT count(*) FROM rider_web_event_verification WHERE web_name_differs_only_by_literal_suffix").fetchone()[0],
        "web_person_name_conflicts": connection.execute("SELECT count(*) FROM rider_web_event_verification WHERE event_verification_status='exact_event_web_name_conflicts_profile_hold'").fetchone()[0],
        "web_role_only_rows": connection.execute("SELECT count(*) FROM rider_web_event_verification WHERE NOT web_person_name_present").fetchone()[0],
    }
    for key, expected in EXPECTED_COUNTS.items():
        if key in counts:
            check(connection, checks, key, expected, int(counts[key]))
    unique = int(connection.execute("SELECT count(*)-count(DISTINCT observation_id) FROM daily_training_raw").fetchone()[0])
    check(connection, checks, "daily_training_observation_id_duplicates", 0, unique)
    web_duplicates = int(connection.execute("SELECT count(*)-count(DISTINCT observation_id) FROM rider_web_event_verification").fetchone()[0])
    check(connection, checks, "web_event_observation_id_duplicates", 0, web_duplicates)
    id_mismatches = int(connection.execute("""
        SELECT count(*) FROM rider_name_links
        WHERE rider_id_raw IS DISTINCT FROM official_jockey_id_raw_string
    """).fetchone()[0])
    check(connection, checks, "all_profile_ids_are_exact_raw_string_matches", 0, id_mismatches)
    profile_bad = int(connection.execute("""
        SELECT count(*) FROM rider_name_links
        WHERE name_snapshot IS NULL OR name_snapshot='' OR source_service<>'API307/jockeyInfo'
           OR source_capture_date<>DATE '2026-09-30'
    """).fetchone()[0])
    check(connection, checks, "profile_name_source_capture_valid", 0, profile_bad)
    profile_snapshot_mismatches = int(connection.execute("""
        SELECT count(*)
        FROM rider_name_links AS link
        LEFT JOIN person_reference_profile_snapshots AS profile
          ON profile.entity_type='jockey'
         AND profile.official_id_raw_string=link.rider_id_raw
        WHERE profile.official_id_raw_string IS NULL
           OR link.name_snapshot IS DISTINCT FROM profile.name_snapshot
           OR link.source_service IS DISTINCT FROM profile.source_service
           OR link.source_capture_date IS DISTINCT FROM CAST(profile.capture_date AS DATE)
           OR link.source_file IS DISTINCT FROM profile.source_file
           OR link.source_sha256 IS DISTINCT FROM profile.source_sha256
    """).fetchone()[0])
    check(connection, checks, "mapping_rows_match_official_profile_snapshot", 0, profile_snapshot_mismatches)
    unmatched_profile_overlaps = int(connection.execute("""
        SELECT count(*) FROM rider_unmatched_ids AS unmatched
        JOIN person_reference_profile_snapshots AS profile
          ON profile.entity_type='jockey'
         AND profile.official_id_raw_string=unmatched.rider_id_raw
    """).fetchone()[0])
    check(connection, checks, "unmatched_ids_have_no_exact_profile_match", 0, unmatched_profile_overlaps)
    connection.execute("""
        CREATE TEMP TABLE raw_identity_fingerprints AS
        SELECT sha256(to_json(struct_pack(
            observation_id := observation_id,
            rider_id_raw := rider_id_raw,
            rider_type_raw := rider_type_raw,
            trainer_name_raw := trainer_name_raw,
            raw_sha256 := raw_sha256,
            raw_payload_json := raw_payload_json
        ))) AS row_sha256
        FROM daily_training_raw
    """)
    connection.execute("""
        CREATE TEMP TABLE linked_identity_fingerprints AS
        SELECT sha256(to_json(struct_pack(
            observation_id := observation_id,
            rider_id_raw := rider_id_raw,
            rider_type_raw := rider_type_raw,
            trainer_name_raw := trainer_name_raw,
            raw_sha256 := raw_sha256,
            raw_payload_json := raw_payload_json
        ))) AS row_sha256
        FROM daily_training_rider_linked
    """)
    raw_delta = int(connection.execute("""
        SELECT count(*) FROM (
            (SELECT row_sha256 FROM raw_identity_fingerprints
             EXCEPT ALL
             SELECT row_sha256 FROM linked_identity_fingerprints)
            UNION ALL
            (SELECT row_sha256 FROM linked_identity_fingerprints
             EXCEPT ALL
             SELECT row_sha256 FROM raw_identity_fingerprints)
        )
    """).fetchone()[0])
    check(connection, checks, "raw_prno_prgubun_trname_payload_and_hash_preserved", 0, raw_delta)
    connection.execute("DROP TABLE temp.main.raw_identity_fingerprints")
    connection.execute("DROP TABLE temp.main.linked_identity_fingerprints")
    hold = connection.execute("""
        SELECT h.observation_id, h.rider_id_raw, h.api_profile_name_candidate, h.web_rider_display_raw,
               v.rider_name_candidate, v.rider_name_linked, v.rider_official_id_candidate,
               v.rider_official_id_linked, v.event_verification_status
        FROM rider_identity_conflict_holds h
        JOIN daily_training_rider_linked v USING (observation_id)
    """).fetchall()
    expected_hold = [(
        CONFLICT_OBSERVATION_ID, "080608", "오수철", "유승완", "오수철", None,
        "080608", None, "exact_event_web_name_conflicts_profile_hold",
    )]
    check(connection, checks, "songdang_sky_single_observation_conflict_hold", expected_hold, hold)
    other_080608 = connection.execute("""
        SELECT count(*) FILTER (WHERE rider_name_linked IS NOT NULL),
               count(*) FILTER (WHERE rider_name_linked IS NULL),
               count(*)
        FROM daily_training_rider_linked
        WHERE rider_id_raw='080608' AND observation_id<>?
    """, [CONFLICT_OBSERVATION_ID]).fetchone()
    check(connection, checks, "other_080608_rows_remain_linked", int(other_080608[2]), int(other_080608[0]))
    check(connection, checks, "other_080608_rows_not_held", 0, int(other_080608[1]))
    unmatched_table_ids = {row[0] for row in connection.execute("SELECT rider_id_raw FROM rider_unmatched_ids").fetchall()}
    exact_table_ids = {row[0] for row in connection.execute("SELECT rider_id_raw FROM rider_name_links").fetchall()}
    check(connection, checks, "profile_unmatched_ids_disjoint_from_linked", 0, len(unmatched_table_ids & exact_table_ids))
    check(connection, checks, "prno_absent_status_rows", EXPECTED_COUNTS["pr_no_absent_rows"],
          int(connection.execute("SELECT count(*) FROM daily_training_rider_linked WHERE rider_identity_status='pr_no_absent'").fetchone()[0]))
    role_total = sum(row["daily_training_rows"] for row in sources["rider_unmatched_by_rider_type"])
    meet_total = sum(row["daily_training_rows"] for row in sources["rider_unmatched_by_meet"])
    check(connection, checks, "unmatched_role_distribution_rows", EXPECTED_COUNTS["profile_unmatched_rows"], role_total)
    check(connection, checks, "unmatched_meet_distribution_rows", EXPECTED_COUNTS["profile_unmatched_rows"], meet_total)
    row_count_view = int(connection.execute("SELECT count(*) FROM daily_training_rider_linked").fetchone()[0])
    check(connection, checks, "linked_view_row_count_equals_raw", EXPECTED_COUNTS["daily_training_rows"], row_count_view)
    check(connection, checks, "input_mapping_unmatched_counts", {"mapping": 282, "unmatched": 70},
          {"mapping": len(sources["rider_name_links"]), "unmatched": len(sources["rider_unmatched_ids"])})
    status_counts = connection.execute("""
        SELECT rider_identity_status, count(*) FROM daily_training_rider_linked
        GROUP BY rider_identity_status ORDER BY rider_identity_status
    """).fetchall()
    source_counts = connection.execute("""
        SELECT count(*), min(event_date)::VARCHAR, max(event_date)::VARCHAR FROM daily_training_raw
    """).fetchone()
    metrics = {
        "counts": counts,
        "linked_view_rows": row_count_view,
        "identity_status_rows": {key: int(value) for key, value in status_counts},
        "source_event_date_min": source_counts[1],
        "source_event_date_max": source_counts[2],
        "unmatched_role_distribution": sources["rider_unmatched_by_rider_type"],
        "unmatched_meet_distribution": sources["rider_unmatched_by_meet"],
        "web_status_counts": {
            key: int(value) for key, value in connection.execute("""
                SELECT event_verification_status, count(*) FROM rider_web_event_verification
                GROUP BY event_verification_status ORDER BY event_verification_status
            """).fetchall()
        },
        "input_row_counts": input_manifest["row_counts"],
    }
    return metrics, checks


def run_dry_run() -> dict[str, Any]:
    db_hash, manifest_hash, _manifest = current_database_identity()
    input_manifest, sources, event_rows = load_inputs()
    metrics, checks = populate_memory_and_validate(input_manifest, sources, event_rows)
    comparison_ids, comparison_groups, root_compare = root_expected_comparison(
        sources, sources["rider_unmatched_role_region_groups"])
    checks.append({"name": "root_independent_mapping_and_unmatched_comparison",
                   "status": root_compare["status"], "expected": "passed", "actual": root_compare["status"]})
    checks.append({"name": "root_independent_role_region_group_comparison",
                   "status": root_compare["status"], "expected": "passed", "actual": root_compare["status"]})
    write_csv_atomic(REPORTS / "root_expected_mapping_unmatched_comparison.csv", comparison_ids)
    write_csv_atomic(REPORTS / "root_expected_role_region_comparison.csv", comparison_groups)
    write_csv_atomic(REPORTS / "unmatched_rider_ids.csv", sources["rider_unmatched_ids"])
    write_csv_atomic(REPORTS / "unmatched_role_region_groups.csv", sources["rider_unmatched_role_region_groups"])
    write_csv_atomic(REPORTS / "unmatched_by_rider_type.csv", sources["rider_unmatched_by_rider_type"])
    write_csv_atomic(REPORTS / "unmatched_by_meet.csv", sources["rider_unmatched_by_meet"])

    input_hashes = {item["path"]: item["sha256"] for item in input_manifest["files"]}
    input_hashes[(INPUT / "rider_link_input_manifest.json").relative_to(ROOT).as_posix()] = sha256_file(INPUT / "rider_link_input_manifest.json")
    input_hashes[SCHEMA_SQL.relative_to(ROOT).as_posix()] = sha256_file(SCHEMA_SQL)
    input_hashes[Path(__file__).resolve().relative_to(ROOT).as_posix()] = sha256_file(Path(__file__).resolve())
    input_hashes[ROOT_EXPECTED.relative_to(ROOT).as_posix()] = root_compare["expected_file_sha256"]
    input_hashes.update({item["path"]: item["sha256"] for item in input_manifest["evidence_files"]})
    object_counts = {
        "tables": 4,
        "views": 1,
        "total_new_objects": 5,
        "expected_main_objects_after_apply": EXPECTED_COUNTS["main_objects_after"],
    }
    all_passed = all(row["status"] == "passed" for row in checks)
    report = {
        "status": "dry_run_passed" if all_passed else "dry_run_failed",
        "applied": False,
        "database_path": CORE_DB.relative_to(ROOT).as_posix(),
        "database_sha256_before": db_hash,
        "core_manifest_sha256_before": manifest_hash,
        "source_manifests_before": EXPECTED_COUNTS["source_manifests_before"],
        "main_objects_before": EXPECTED_COUNTS["main_objects_before"],
        "expected_source_manifests_after_apply": EXPECTED_COUNTS["source_manifests_after"],
        "proposed_objects": [
            {"name": "rider_name_links", "type": "BASE TABLE", "rows": 282},
            {"name": "rider_identity_conflict_holds", "type": "BASE TABLE", "rows": 1},
            {"name": "rider_unmatched_ids", "type": "BASE TABLE", "rows": 70},
            {"name": "rider_web_event_verification", "type": "BASE TABLE", "rows": 1247},
            {"name": "daily_training_rider_linked", "type": "VIEW", "rows": 5_173_033},
        ],
        "object_counts": object_counts,
        "metrics": metrics,
        "root_independent_comparison": root_compare,
        "input_hashes": input_hashes,
        "checks": checks,
        "backup_gate": {
            "backup_directory": BACKUP_DIR.relative_to(ROOT).as_posix(),
            "backup_pair_attestation_required": True,
            "apply_not_executed_by_this_run": True,
        },
        "identity_limits": [
            "Only exact official profile ID string matches receive a name candidate.",
            "The profile name is a 2026-09-30 snapshot and does not infer historical role or status.",
            "Raw prNo, prGubun, trName, source payload, and source hashes remain unchanged.",
            "Only the single 송당스카이 conflict observation is held; other 080608 rows remain linked.",
            "The literal (트) display suffix is retained verbatim in event evidence; it is not interpreted as a qualification.",
            "The unmatched 70 IDs remain unresolved; no ID, name, owner, trainer, or role is guessed.",
        ],
        "outputs": [
            (REPORTS / "dry_run_report.json").relative_to(ROOT).as_posix(),
            (REPORTS / "root_expected_mapping_unmatched_comparison.csv").relative_to(ROOT).as_posix(),
            (REPORTS / "root_expected_role_region_comparison.csv").relative_to(ROOT).as_posix(),
            (REPORTS / "unmatched_rider_ids.csv").relative_to(ROOT).as_posix(),
            (REPORTS / "unmatched_role_region_groups.csv").relative_to(ROOT).as_posix(),
            (REPORTS / "unmatched_by_rider_type.csv").relative_to(ROOT).as_posix(),
            (REPORTS / "unmatched_by_meet.csv").relative_to(ROOT).as_posix(),
        ],
    }
    write_json_atomic(REPORTS / "dry_run_report.json", report)
    return report


def apply_manifest_update(before: dict[str, Any], after_hash: str,
                          input_manifest: dict[str, Any], source_manifest: dict[str, Any]) -> dict[str, Any]:
    updated = json.loads(json.dumps(before))
    updated["database_sha256"] = after_hash
    input_files = updated.setdefault("input_files", [])
    known = {row.get("path") for row in input_files if isinstance(row, dict)}
    extra_files = list(input_manifest["files"]) + [
        {"path": (INPUT / "rider_link_input_manifest.json").relative_to(ROOT).as_posix(),
         "sha256": sha256_file(INPUT / "rider_link_input_manifest.json"), "rows": None},
        {"path": SCHEMA_SQL.relative_to(ROOT).as_posix(), "sha256": sha256_file(SCHEMA_SQL), "rows": None},
        {"path": Path(__file__).resolve().relative_to(ROOT).as_posix(), "sha256": sha256_file(Path(__file__).resolve()), "rows": None},
        {"path": ROOT_EXPECTED.relative_to(ROOT).as_posix(), "sha256": sha256_file(ROOT_EXPECTED), "rows": None},
    ]
    for item in extra_files:
        if item["path"] not in known:
            input_files.append({"table": "daily_training_rider_links_input", **item})
            known.add(item["path"])
    counts = updated.setdefault("table_and_view_counts", {})
    counts.update({
        "rider_name_links": 282,
        "rider_identity_conflict_holds": 1,
        "rider_unmatched_ids": 70,
        "rider_web_event_verification": 1247,
        "daily_training_rider_linked": 5_173_033,
        "source_manifests": 28,
    })
    loads = updated.setdefault("supplement_loads", [])
    if any(item.get("name") == SOURCE_MANIFEST_NAME for item in loads if isinstance(item, dict)):
        raise ValueError("the core manifest already records this rider-link append")
    loads.append({
        "name": SOURCE_MANIFEST_NAME,
        "applied_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "baseline_database_sha256": BASE_DB_SHA256,
        "database_sha256_after": after_hash,
        "backup_database": BACKUP_DB.relative_to(ROOT).as_posix(),
        "backup_manifest": BACKUP_MANIFEST.relative_to(ROOT).as_posix(),
        "backup_pair_attestation": BACKUP_ATTESTATION.relative_to(ROOT).as_posix(),
        "source_manifest_name": SOURCE_MANIFEST_NAME,
        "new_main_object_counts": {
            "rider_name_links": 282,
            "rider_identity_conflict_holds": 1,
            "rider_unmatched_ids": 70,
            "rider_web_event_verification": 1247,
            "daily_training_rider_linked": 5_173_033,
            "main_objects_after": 213,
            "source_manifests_after": 28,
        },
        "source_manifest_sha256": hashlib.sha256(canonical_json(source_manifest).encode("utf-8")).hexdigest(),
    })
    return updated


def verify_backup_pair() -> dict[str, Any]:
    for path in (BACKUP_DB, BACKUP_MANIFEST, BACKUP_ATTESTATION):
        if not path.is_file():
            raise FileNotFoundError(f"required root backup file is missing: {path}")
    attestation = load_json(BACKUP_ATTESTATION)
    if attestation.get("verified_equal") is not True or attestation.get("source_unchanged") is not True:
        raise ValueError("root backup-pair attestation is not verified_equal/source_unchanged")
    if attestation.get("baseline_db_sha256") != BASE_DB_SHA256 or attestation.get("backup_db_sha256") != BASE_DB_SHA256:
        raise ValueError("root backup-pair attestation has a different DB baseline hash")
    if attestation.get("baseline_manifest_sha256") != BASE_MANIFEST_SHA256 or attestation.get("backup_manifest_sha256") != BASE_MANIFEST_SHA256:
        raise ValueError("root backup-pair attestation has a different manifest baseline hash")
    backup_db_hash = sha256_file(BACKUP_DB)
    backup_manifest_hash = sha256_file(BACKUP_MANIFEST)
    if backup_db_hash != BASE_DB_SHA256 or backup_manifest_hash != BASE_MANIFEST_SHA256:
        raise ValueError("root backup files no longer match their attested baseline hashes")
    return {
        "attestation_path": BACKUP_ATTESTATION.relative_to(ROOT).as_posix(),
        "attestation_sha256": sha256_file(BACKUP_ATTESTATION),
        "database_sha256": backup_db_hash,
        "manifest_sha256": backup_manifest_hash,
        "verified_equal": True,
    }


def run_apply() -> dict[str, Any]:
    report_path = REPORTS / "dry_run_report.json"
    if not report_path.is_file():
        raise ValueError("a passing --dry-run report is required before --apply")
    dry_run_report = load_json(report_path)
    if dry_run_report.get("status") != "dry_run_passed" or dry_run_report.get("applied") is not False:
        raise ValueError("the latest dry-run report did not pass or was already applied")
    db_hash, manifest_hash, manifest_before = current_database_identity()
    if db_hash != dry_run_report.get("database_sha256_before") or manifest_hash != dry_run_report.get("core_manifest_sha256_before"):
        raise ValueError("core DB or manifest changed after dry-run; refusing to append")
    input_manifest, sources, event_rows = load_inputs()
    current_hashes = dry_run_report.get("input_hashes", {})
    for path in (SCHEMA_SQL, Path(__file__).resolve(), ROOT_EXPECTED, INPUT / "rider_link_input_manifest.json"):
        rel = path.relative_to(ROOT).as_posix()
        if current_hashes.get(rel) != sha256_file(path):
            raise ValueError(f"apply input/code hash differs from passing dry-run: {rel}")
    backup_verification = verify_backup_pair()

    connection = duckdb.connect(str(CORE_DB), read_only=False)
    committed = False
    original_signature: dict[str, Any] | None = None
    try:
        configure_duckdb(connection)
        original_signature = catalog_signature(connection)
        if len(original_signature["objects"]) != EXPECTED_COUNTS["main_objects_before"]:
            raise ValueError(f"main object count changed before apply: {len(original_signature['objects'])}")
        if int(connection.execute("SELECT count(*) FROM source_manifests").fetchone()[0]) != EXPECTED_COUNTS["source_manifests_before"]:
            raise ValueError("source_manifests row count changed before apply")
        if connection.execute("SELECT count(*) FROM source_manifests WHERE name=?", [SOURCE_MANIFEST_NAME]).fetchone()[0]:
            raise ValueError("source manifest name already exists; refusing duplicate append")
        if any(f"main.{name}" in original_signature["objects"] for name in (
            "rider_name_links", "rider_identity_conflict_holds", "rider_unmatched_ids",
            "rider_web_event_verification", "daily_training_rider_linked",
        )):
            raise ValueError("one or more proposed core objects already exist")
        connection.execute("BEGIN TRANSACTION")
        create_schema(connection)
        insert_staged_rows(connection, sources, event_rows)
        metrics, checks = validate_loaded_state(connection, sources, event_rows, input_manifest)
        failed = [row for row in checks if row["status"] != "passed"]
        if failed:
            raise ValueError(f"pre-commit validation failed: {[row['name'] for row in failed]}")
        source_manifest = source_manifest_value(input_manifest)
        source_text = json.dumps(source_manifest, ensure_ascii=False, sort_keys=True)
        connection.execute("INSERT INTO source_manifests(name,json_text) VALUES (?,?)",
                           [SOURCE_MANIFEST_NAME, source_text])
        after_signature = catalog_signature(connection)
        expected_objects = dict(original_signature["objects"])
        expected_objects.update({
            "main.rider_name_links": "BASE TABLE",
            "main.rider_identity_conflict_holds": "BASE TABLE",
            "main.rider_unmatched_ids": "BASE TABLE",
            "main.rider_web_event_verification": "BASE TABLE",
            "main.daily_training_rider_linked": "VIEW",
        })
        if after_signature["objects"] != expected_objects:
            raise ValueError("core catalog changed beyond the five declared new objects")
        for key, value in original_signature["columns"].items():
            if after_signature["columns"].get(key) != value:
                raise ValueError(f"existing object schema changed: {key}")
        before_views = {row[:2]: row[2] for row in original_signature["view_sql"]}
        after_views = {row[:2]: row[2] for row in after_signature["view_sql"]}
        if any(after_views.get(key) != sql for key, sql in before_views.items()):
            raise ValueError("an existing view definition changed")
        source_rows_after = int(connection.execute("SELECT count(*) FROM source_manifests").fetchone()[0])
        if source_rows_after != EXPECTED_COUNTS["source_manifests_after"]:
            raise ValueError(f"source_manifests count after append is {source_rows_after}, expected 28")
        connection.execute("COMMIT")
        committed = True
    except Exception:
        if not committed:
            try:
                connection.execute("ROLLBACK")
            except Exception:
                pass
        connection.close()
        raise
    connection.close()

    try:
        updated_db_hash = sha256_file(CORE_DB)
        updated_manifest = apply_manifest_update(manifest_before, updated_db_hash, input_manifest, source_manifest)
        manifest_bytes_before = BACKUP_MANIFEST.read_bytes()
        write_json_atomic(CORE_MANIFEST, updated_manifest)
        if sha256_file(CORE_MANIFEST) == hashlib.sha256(manifest_bytes_before).hexdigest():
            raise ValueError("external core manifest did not change after successful apply")
        if load_json(CORE_MANIFEST).get("database_sha256") != updated_db_hash:
            raise ValueError("external core manifest database_sha256 failed post-apply verification")
        report = {
            "status": "applied_and_verified",
            "applied": True,
            "database_sha256_before": BASE_DB_SHA256,
            "database_sha256_after": updated_db_hash,
            "core_manifest_sha256_after": sha256_file(CORE_MANIFEST),
            "source_manifest_name": SOURCE_MANIFEST_NAME,
            "source_manifests_after": 28,
            "main_objects_after": 213,
            "metrics": metrics,
            "checks": checks,
            "backup_verification": backup_verification,
            "manifest_update": "database_sha256, input_files, table_and_view_counts, supplement_loads",
        }
        write_json_atomic(REPORTS / "apply_report.json", report)
        return report
    except Exception as exc:
        # A post-commit failure restores the root-provided paired snapshot before returning.
        restore_error = None
        try:
            shutil.copy2(BACKUP_DB, CORE_DB)
            shutil.copy2(BACKUP_MANIFEST, CORE_MANIFEST)
            if sha256_file(CORE_DB) != BASE_DB_SHA256 or sha256_file(CORE_MANIFEST) != BASE_MANIFEST_SHA256:
                raise ValueError("restored DB/manifest hashes do not match the root backup pair")
        except Exception as restore_exc:  # pragma: no cover - recovery failure path
            restore_error = f"{type(restore_exc).__name__}: {restore_exc}"
        failure = {
            "status": "apply_failed_restored_from_backup" if restore_error is None else "apply_failed_restore_required",
            "applied": False if restore_error is None else "unknown_until_restore",
            "error": f"{type(exc).__name__}: {exc}",
            "restore_error": restore_error,
            "backup_verification": backup_verification,
            "additional_writes_allowed": False,
        }
        write_json_atomic(REPORTS / "apply_failure.json", failure)
        raise RuntimeError(canonical_json(failure)) from exc


def source_manifest_value(input_manifest: dict[str, Any]) -> dict[str, Any]:
    input_files = list(input_manifest["files"])
    for path in (SCHEMA_SQL, Path(__file__).resolve(), ROOT_EXPECTED, INPUT / "rider_link_input_manifest.json"):
        input_files.append({
            "path": path.relative_to(ROOT).as_posix(), "sha256": sha256_file(path),
            "rows": file_row_count(path),
        })
    input_files.extend(input_manifest["evidence_files"])
    return {
        "name": SOURCE_MANIFEST_NAME,
        "schema_version": "daily_training_rider_links_v1",
        "baseline_database_sha256": BASE_DB_SHA256,
        "baseline_manifest_sha256": BASE_MANIFEST_SHA256,
        "scope": {"event_date_start": "2010-01-01", "event_date_end_exclusive": "2026-09-30"},
        "source_tables": ["daily_training_raw", "person_reference_profile_snapshots", "entity_reference_roster"],
        "identity_rule": "Exact string equality of prNo to API307/jockeyInfo official jockey profile ID; no casts or other entity-name joins.",
        "identity_limit": "The 2026-09-30 snapshot name is not an event-date role or profile-status assertion.",
        "raw_fields_preserved": ["rider_id_raw", "rider_type_raw", "trainer_name_raw", "raw_payload_json", "raw_sha256"],
        "name_link_rows": 282,
        "conflict_hold_rows": 1,
        "unmatched_ids": 70,
        "unmatched_rows": 190375,
        "pr_no_absent_rows": 3383170,
        "profile_exact_candidate_rows": 1599488,
        "profile_exact_name_linked_rows_after_hold": 1599487,
        "web_event_verification_rows": 1247,
        "files": input_files,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--prepare-inputs", action="store_true", help="extract hash-pinned CSV/JSON inputs from the read-only core")
    group.add_argument("--dry-run", action="store_true", help="validate the proposed append in an in-memory DuckDB")
    group.add_argument("--apply", action="store_true", help="append only after dry-run and verified root backup")
    args = parser.parse_args()
    if args.prepare_inputs:
        report = prepare_inputs()
    elif args.dry_run:
        report = run_dry_run()
    else:
        report = run_apply()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("status") in {"inputs_prepared", "dry_run_passed", "applied_and_verified"} else 1


if __name__ == "__main__":
    sys.exit(main())
