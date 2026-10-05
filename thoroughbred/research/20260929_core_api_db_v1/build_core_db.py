"""Build a staged, API-first thoroughbred research DuckDB from verified CSV exports."""

from __future__ import annotations

import hashlib
import json
import os
import csv
import gzip
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from extract_full_plan import main as extract_full_plan
from role_review_integration import REVIEW as ROLE_REVIEW, load_role_reviews, verify_role_reviews
from role_review_integration import ERROR_REVIEW, verify_source_error_decisions
from calendar_review_integration import REVIEW as CALENDAR_REVIEW, build_review_exports


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
CAL = ROOT / "thoroughbred/research/20260929_calendar_api_v1"
RACE = ROOT / "thoroughbred/research/20260929_race_results_api_v1"
TRIAL = ROOT / "thoroughbred/research/20260929_trial_results_api_v1"
TRIAL_IDENTITY = ROOT / "thoroughbred/research/20260930_trial_horse_identity_v1"
TRIAL_VENUE = ROOT / "thoroughbred/research/20261001_yeongnam_trial_venue_recheck_v2"
VENUE_RPT = ROOT / "data/raw/kra_text/dacom23/meet=3/year=2026/month=09/day=17/20260917dacom23.rpt"
SECTION = ROOT / "thoroughbred/data/section_api_2010_20260929_v1"
SECTION_RESEARCH = ROOT / "thoroughbred/research/20260930_section_api_v1"
ENTITY = ROOT / "thoroughbred/research/20260930_entity_reference_audit_v1/exports"
RACE_ROLE_GAP = ROOT / "thoroughbred/research/20260930_missing_entity_source_audit_v1/race_role_gap_audit.jsonl"
TRIAL_JOCKEY_GAP = ROOT / "thoroughbred/research/20260930_trial_jockey_gap_audit_v1/trial_jockey_missing_audit.jsonl"
TRIAL_JOCKEY_GAP_MANIFEST = ROOT / "thoroughbred/research/20260930_trial_jockey_gap_audit_v1/manifest.json"
TRIAL_WEB_24 = ROOT / "thoroughbred/research/20260930_trial_jockey_gap_audit_v1/official_web_missing_24.jsonl"
TRIAL_WEB_24_MANIFEST = ROOT / "thoroughbred/research/20260930_trial_jockey_gap_audit_v1/official_web_missing_24_manifest.json"
TRIAL_WEB_18 = ROOT / "thoroughbred/research/20260930_trial_jockey_gap_audit_v1/official_web_name_conflicts_18.jsonl"
TRIAL_WEB_18_MANIFEST = ROOT / "thoroughbred/research/20260930_trial_jockey_gap_audit_v1/official_web_name_conflicts_18_manifest.json"
TRIAL_RPT_NAME_REVIEW = ROOT / "thoroughbred/research/20260930_trial_jockey_gap_audit_v1/rpt_name_discrepancy_review.jsonl"
TRIAL_RPT_NAME_REVIEW_MANIFEST = ROOT / "thoroughbred/research/20260930_trial_jockey_gap_audit_v1/rpt_name_discrepancy_review_manifest.json"
TRIAL_WEB_5079 = ROOT / "thoroughbred/research/20260930_trial_jockey_gap_audit_v1/official_web_jockey_ids_5079.jsonl"
TRIAL_WEB_5079_MANIFEST = ROOT / "thoroughbred/research/20260930_trial_jockey_gap_audit_v1/official_web_jockey_ids_5079_manifest.json"
JOCKEY_PROFILE_SUPPLEMENT = ROOT / "thoroughbred/research/20260930_trial_jockey_gap_audit_v1/official_jockey_profile_supplement.jsonl"
JOCKEY_PROFILE_SUPPLEMENT_MANIFEST = ROOT / "thoroughbred/research/20260930_trial_jockey_gap_audit_v1/official_jockey_profile_supplement_manifest.json"
CLOSURE = ROOT / "thoroughbred/research/20260929_closure_inventory_v1"
OUT = ROOT / "thoroughbred/data/core_api_2010_20260929_v1"
DB = OUT / "thoroughbred_core.duckdb"
CSV_TABLES = {
    "calendar_days": CALENDAR_REVIEW / "daily_calendar.csv",
    "annual_summary": CALENDAR_REVIEW / "annual_summary.csv",
    "calendar_days_prior_review": CAL / "daily_calendar.csv",
    "annual_summary_prior_review": CAL / "annual_summary.csv",
    "race_plan": CAL / "race_plan.csv",
    "race_plan_full_api": HERE / "race_plan_full_api.csv",
    "race_execution_flags": CAL / "race_execution_flags.csv",
    "race_nonexecution_adjudication": CALENDAR_REVIEW / "race_nonexecution_adjudication.csv",
    "race_nonexecution_adjudication_prior_review": CAL / "race_nonexecution_adjudication.csv",
    "race_nonexecution_subtype_review": CALENDAR_REVIEW / "subtype_decisions.csv",
    "closure_boundary_review": CALENDAR_REVIEW / "closure_boundary_review.csv",
    "reported_closure_interval_leads": CALENDAR_REVIEW / "reported_closure_interval_leads.csv",
    "closure_gap_review_candidates": CALENDAR_REVIEW / "closure_gap_review_candidates.csv",
    "closure_plan_amendment_review": CALENDAR_REVIEW / "closure_plan_amendment_review.csv",
    "closure_review_questions": CALENDAR_REVIEW / "closure_review_questions.csv",
    "section_missing_finisher_review": SECTION_RESEARCH / "missing_finisher_section_review.csv",
    "race_events": RACE / "race_events.csv",
    "runner_results": RACE / "runner_results.csv",
    "trial_sessions": TRIAL / "sessions.csv",
    "trial_participants": TRIAL / "participants.csv",
    "unidentified_trial_participants": TRIAL / "unidentified_participants.csv",
    "trial_horse_identity_links": TRIAL_IDENTITY / "identity_links.csv",
    "trial_horse_identity_pending": TRIAL_IDENTITY / "pending_review.csv",
    "trial_horse_identity_user_confirmations": TRIAL_IDENTITY / "user_confirmations.csv",
    "trial_venue_review": TRIAL_VENUE / "venue_review.csv",
    "trial_trainer_source_error_decisions": ERROR_REVIEW / "source_error_decisions.csv",
    "unverified_result_only_keys": RACE / "unverified_result_only_keys.csv",
    "official_cancelled_days": CAL / "official_nonexecution_addendum.csv",
    "prior_unresolved_race_day_review": CAL / "unresolved_race_day_review.csv",
    "official_annual_stats_crosscheck": CAL / "official_annual_stats_crosscheck.csv",
}
SECTION_TABLES = {
    "section_measurements_api": SECTION / "section_measurements.parquet",
    "runner_section_coverage_api": SECTION / "runner_section_coverage.parquet",
    "section_parse_issues_api": SECTION / "section_parse_issues.parquet",
}
ENTITY_TABLES = {
    name.removesuffix(".csv"): ENTITY / name
    for name in (
        "entity_reference_roster.csv",
        "entity_name_observations.csv",
        "unresolved_entity_references.csv",
        "entity_reference_summary.csv",
        "entity_profile_coverage.csv",
        "entity_profile_coverage_gaps.csv",
        "horse_profile_snapshot_membership.csv",
        "person_reference_profile_snapshots.csv",
        "trial_horse_id_source_exceptions.csv",
        "non_person_placeholder_observations.csv",
        "horse_profile_page_manifest.csv",
        "person_profile_page_manifest.csv",
    )
}
EXPECTED = {
    "calendar_days": 18348,
    "annual_summary": 51,
    "calendar_days_prior_review": 18348,
    "annual_summary_prior_review": 51,
    "race_plan": 29826,
    "race_plan_full_api": 29826,
    "race_execution_flags": 29826,
    "race_nonexecution_adjudication": 116,
    "race_nonexecution_adjudication_prior_review": 116,
    "race_nonexecution_subtype_review": 29,
    "section_missing_finisher_review": 2,
    "race_events": 29826,
    "runner_results": 331811,
    "trial_sessions": 6199,
    "trial_participants": 61777,
    "trial_jockey_gap_audit": 5121,
    "trial_jockey_official_web_missing_24": 24,
    "trial_jockey_official_web_conflict_18": 18,
    "trial_rpt_name_review_18": 18,
    "trial_jockey_official_web_rpt_5079": 5079,
    "trial_jockey_official_profile_supplement": 1,
    "jockey_reference_ids_with_review": 338,
    "race_role_gap_audit": 38,
    "race_trainer_owner_review": 60,
    "trial_trainer_review": 224,
    "unidentified_trial_participants": 104,
    "trial_horse_identity_links": 104,
    "trial_horse_identity_pending": 0,
    "trial_horse_identity_user_confirmations": 5,
    "trial_venue_review": 1,
    "trial_trainer_source_error_decisions": 22,
    "trial_trainer_errors_closed": 22,
    "role_link_exceptions_pending": 0,
    "trial_sessions_venue_reviewed": 6199,
    "trial_participants_venue_reviewed": 61777,
    "unverified_result_only_keys": 0,
    "official_cancelled_days": 4,
    "prior_unresolved_race_day_review": 2,
    "official_annual_stats_crosscheck": 10,
    "confirmed_races": 29710,
    "confirmed_runners_entity_reviewed": 330465,
    "trial_participants_entity_reviewed": 61777,
    "race_execution_adjudicated": 29826,
    "section_measurements_api": 4380065,
    "runner_section_coverage_api": 330465,
    "section_parse_issues_api": 0,
}


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def verify_export_manifests() -> None:
    race = json.loads((RACE / "manifest.json").read_text(encoding="utf-8"))
    trial = json.loads((TRIAL / "validation.json").read_text(encoding="utf-8"))
    if not trial["passed"] or not all(race["validation"].values()):
        raise ValueError("A source export has failed validation")
    for filename, record in race["outputs"].items():
        if sha(RACE / filename) != record["sha256"]:
            raise ValueError(f"Changed race export: {filename}")
    for filename, digest in trial["output_file_sha256"].items():
        if sha(TRIAL / filename) != digest:
            raise ValueError(f"Changed trial export: {filename}")
    section = json.loads((SECTION / "manifest.json").read_text(encoding="utf-8"))
    if sha(RACE / "runner_results.csv") != section["runner_spine_sha256"]:
        raise ValueError("Section export does not match the current result export")
    if not all(section["checks"].values()):
        raise ValueError("Section source export has failed validation")
    for filename, record in section["output_files"].items():
        if sha(SECTION / filename) != record["sha256"]:
            raise ValueError(f"Changed section export: {filename}")
    entity = json.loads((ENTITY / "manifest.json").read_text(encoding="utf-8"))
    if not all(entity["validation"].values()):
        raise ValueError("Entity reference export has failed validation")
    if set(entity["exports"]) != {path.name for path in ENTITY_TABLES.values()}:
        raise ValueError("Unexpected entity reference exports")
    for filename, record in entity["exports"].items():
        path = ENTITY / filename
        if sha(path) != record["sha256"]:
            raise ValueError(f"Changed entity reference export: {filename}")
        with path.open(newline="", encoding="utf-8-sig") as stream:
            rows = sum(1 for _ in csv.DictReader(stream))
        if rows != record["row_count"]:
            raise ValueError(f"Changed entity reference row count: {filename}")
    spine = entity.get("source_spine_sha256", {})
    if spine.get("runner_results.csv", {}).get("sha256") != sha(RACE / "runner_results.csv"):
        raise ValueError("Entity roster does not match current runner results")
    if spine.get("participants.csv", {}).get("sha256") != sha(TRIAL / "participants.csv"):
        raise ValueError("Entity roster does not match current trial participants")
    with (TRIAL_VENUE / "venue_review.csv").open(newline="", encoding="utf-8") as stream:
        venue_rows = list(csv.DictReader(stream))
    if len(venue_rows) != 1:
        raise ValueError("Expected one 2026-09-17 trial venue review")
    venue_row = venue_rows[0]
    if venue_row["rpt_source_file"] != rel(VENUE_RPT):
        raise ValueError("Unexpected trial venue review RPT source")
    if sha(VENUE_RPT) != venue_row["rpt_sha256"]:
        raise ValueError("Changed official trial RPT for venue review")
    venue_manifest = json.loads((TRIAL_VENUE / "manifest.json").read_text(encoding="utf-8"))
    for record in venue_manifest["pinned_files"]:
        path = (ROOT / record["path"]).resolve()
        if not path.is_relative_to(ROOT.resolve()) or sha(path) != record["sha256"]:
            raise ValueError("Changed trial venue review evidence")
    if (venue_row["source_meet_query"] != "3" or venue_row["trial_date"] != "2026-09-17"
            or venue_row["physical_venue"] != "부산경남"
            or venue_row["reviewed_distance_m"] != "1000"
            or venue_row["venue_review_status"] != "confirmed_official_plan_and_user_clarification"):
        raise ValueError("Unexpected official-plan trial venue decision")
    jockey_gap = json.loads(TRIAL_JOCKEY_GAP_MANIFEST.read_text(encoding="utf-8"))
    if not jockey_gap["validation"]["passed"]:
        raise ValueError("Trial jockey gap audit failed validation")
    if jockey_gap["output"]["sha256"] != sha(TRIAL_JOCKEY_GAP):
        raise ValueError("Changed trial jockey gap audit")
    web_24 = json.loads(TRIAL_WEB_24_MANIFEST.read_text(encoding="utf-8"))
    if web_24["source_sha256"] != sha(TRIAL_JOCKEY_GAP) or web_24["output_sha256"] != sha(TRIAL_WEB_24):
        raise ValueError("Changed official trial web recheck input or output")
    for capture in web_24["captures"]:
        path = (ROOT / capture["source_file"]).resolve()
        if not path.is_relative_to(ROOT.resolve()) or sha(path) != capture["sha256"]:
            raise ValueError(f"Changed official trial score page: {capture['source_file']}")
    web_18 = json.loads(TRIAL_WEB_18_MANIFEST.read_text(encoding="utf-8"))
    if web_18["source_sha256"] != sha(TRIAL_JOCKEY_GAP) or web_18["output_sha256"] != sha(TRIAL_WEB_18):
        raise ValueError("Changed official trial name-conflict web recheck input or output")
    for capture in web_18["captures"]:
        path = (ROOT / capture["source_file"]).resolve()
        if not path.is_relative_to(ROOT.resolve()) or sha(path) != capture["sha256"]:
            raise ValueError(f"Changed official trial name-conflict page: {capture['source_file']}")
    name_review = json.loads(TRIAL_RPT_NAME_REVIEW_MANIFEST.read_text(encoding="utf-8"))
    if (name_review["source_web_rows_sha256"] != sha(TRIAL_WEB_18)
            or name_review["output_sha256"] != sha(TRIAL_RPT_NAME_REVIEW)
            or (name_review["rows"], name_review["confirmed_name_change_rows"],
                name_review["confirmed_distinct_name_changes"], name_review["unresolved_rows"])
            != (18, 13, 9, 5)):
        raise ValueError("Changed official db7 name-change review input or output")
    for evidence in name_review["official_db7_files"]:
        path = (ROOT / evidence["path"]).resolve()
        if not path.is_relative_to(ROOT.resolve()) or sha(path) != evidence["sha256"]:
            raise ValueError(f"Changed official db7 source: {evidence['path']}")
    web_5079 = json.loads(TRIAL_WEB_5079_MANIFEST.read_text(encoding="utf-8"))
    if (web_5079["source_sha256"] != sha(TRIAL_JOCKEY_GAP)
            or web_5079["output_sha256"] != sha(TRIAL_WEB_5079)
            or web_5079["expected_targets"] != 5079
            or web_5079["observations"] != 5079
            or web_5079["errors"] != 0
            or web_5079["completed_trial_riders"] + web_5079["assigned_only"] != 5079
            or len(web_5079["captures"]) != web_5079["expected_sessions"]):
        raise ValueError("Official trial jockey ID source incomplete or changed")
    for capture in web_5079["captures"]:
        path = (ROOT / capture["source_file"]).resolve()
        if (not path.is_relative_to(ROOT.resolve())
                or sha(path) != capture["compressed_sha256"]
                or hashlib.sha256(gzip.decompress(path.read_bytes())).hexdigest()
                != capture["sha256"]):
            raise ValueError(f"Changed official trial score page: {capture['source_file']}")
    profile = json.loads(JOCKEY_PROFILE_SUPPLEMENT_MANIFEST.read_text(encoding="utf-8"))
    profile_path = (ROOT / profile["profile_source_file"]).resolve()
    if (profile["rows"] != 1 or profile["output_sha256"] != sha(JOCKEY_PROFILE_SUPPLEMENT)
            or not profile_path.is_relative_to(ROOT.resolve())
            or profile["profile_source_sha256"] != sha(profile_path)):
        raise ValueError("Official cross-venue jockey profile evidence changed")
    for name, digest in jockey_gap["source_api"]["source_file_sha256"].items():
        path = (ROOT / name).resolve()
        if not path.is_relative_to(ROOT.resolve()) or sha(path) != digest:
            raise ValueError(f"Changed trial jockey API evidence: {name}")
    for name, digest in jockey_gap["source_rpt"]["rpt_source_file_sha256_for_matched_rows"].items():
        path = (ROOT / name).resolve()
        if not path.is_relative_to(ROOT.resolve()) or sha(path) != digest:
            raise ValueError(f"Changed trial jockey RPT evidence: {name}")
    with RACE_ROLE_GAP.open(encoding="utf-8") as stream:
        race_gap_rows = [json.loads(line) for line in stream]
    if len(race_gap_rows) != 38:
        raise ValueError("Unexpected race role gap audit size")
    race_evidence_hashes = {}
    for row in race_gap_rows:
        for path_key, hash_key in (
            ("api4_3_source_file", "api4_3_source_sha256"),
            ("api26_recheck_source_file", "api26_recheck_sha256"),
        ):
            race_evidence_hashes[row[path_key]] = row[hash_key]
        if row["rpt_evidence"]:
            race_evidence_hashes[row["rpt_evidence"]["source_file"]] = row["rpt_evidence"]["sha256"]
        for evidence in row["archived_api26_populated_matches"]:
            race_evidence_hashes[evidence["source_file"]] = evidence["sha256"]
    for name, digest in race_evidence_hashes.items():
        path = (ROOT / name).resolve()
        if not path.is_relative_to(ROOT.resolve()) or sha(path) != digest:
            raise ValueError(f"Changed race role gap evidence: {name}")


def main() -> None:
    verify_export_manifests()
    verify_role_reviews()
    verify_source_error_decisions()
    calendar_review = build_review_exports()
    extract_full_plan()
    OUT.mkdir(parents=True, exist_ok=True)
    temp = OUT / "thoroughbred_core.building.duckdb"
    if temp.exists():
        temp.unlink()
    connection = duckdb.connect(str(temp))
    inputs = []
    counts = {}
    try:
        for table, path in CSV_TABLES.items():
            connection.execute(f"CREATE TABLE {table} AS SELECT * FROM read_csv(?, header=true, all_varchar=true)", [str(path)])
            counts[table] = connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            inputs.append({"table": table, "path": rel(path), "sha256": sha(path), "rows": counts[table]})
        for table, path in SECTION_TABLES.items():
            connection.execute(f"CREATE TABLE {table} AS SELECT * FROM read_parquet(?)", [str(path)])
            counts[table] = connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            inputs.append({"table": table, "path": rel(path), "sha256": sha(path), "rows": counts[table]})
        for table, path in ENTITY_TABLES.items():
            connection.execute(f"CREATE TABLE {table} AS SELECT * FROM read_csv(?, header=true, all_varchar=true)", [str(path)])
            counts[table] = connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            inputs.append({"table": table, "path": rel(path), "sha256": sha(path), "rows": counts[table]})
        connection.execute("CREATE TABLE race_role_gap_audit AS "
                           "SELECT * FROM read_json_auto(?, format='newline_delimited')", [str(RACE_ROLE_GAP)])
        counts["race_role_gap_audit"] = connection.execute(
            "SELECT count(*) FROM race_role_gap_audit").fetchone()[0]
        inputs.append({"table": "race_role_gap_audit", "path": rel(RACE_ROLE_GAP),
                       "sha256": sha(RACE_ROLE_GAP), "rows": counts["race_role_gap_audit"]})
        connection.execute("CREATE TABLE trial_jockey_gap_audit AS "
                           "SELECT * FROM read_json_auto(?, format='newline_delimited')", [str(TRIAL_JOCKEY_GAP)])
        counts["trial_jockey_gap_audit"] = connection.execute(
            "SELECT count(*) FROM trial_jockey_gap_audit").fetchone()[0]
        inputs.append({"table": "trial_jockey_gap_audit", "path": rel(TRIAL_JOCKEY_GAP),
                       "sha256": sha(TRIAL_JOCKEY_GAP), "rows": counts["trial_jockey_gap_audit"]})
        connection.execute("CREATE TABLE trial_jockey_official_web_missing_24 AS "
                           "SELECT * FROM read_json_auto(?, format='newline_delimited')", [str(TRIAL_WEB_24)])
        counts["trial_jockey_official_web_missing_24"] = connection.execute(
            "SELECT count(*) FROM trial_jockey_official_web_missing_24").fetchone()[0]
        inputs.append({"table": "trial_jockey_official_web_missing_24", "path": rel(TRIAL_WEB_24),
                       "sha256": sha(TRIAL_WEB_24),
                       "rows": counts["trial_jockey_official_web_missing_24"]})
        connection.execute("CREATE TABLE trial_jockey_official_web_conflict_18 AS "
                           "SELECT * FROM read_json_auto(?, format='newline_delimited')", [str(TRIAL_WEB_18)])
        counts["trial_jockey_official_web_conflict_18"] = connection.execute(
            "SELECT count(*) FROM trial_jockey_official_web_conflict_18").fetchone()[0]
        inputs.append({"table": "trial_jockey_official_web_conflict_18", "path": rel(TRIAL_WEB_18),
                       "sha256": sha(TRIAL_WEB_18),
                       "rows": counts["trial_jockey_official_web_conflict_18"]})
        connection.execute("CREATE TABLE trial_rpt_name_review_18 AS "
                           "SELECT * FROM read_json_auto(?, format='newline_delimited')",
                           [str(TRIAL_RPT_NAME_REVIEW)])
        counts["trial_rpt_name_review_18"] = connection.execute(
            "SELECT count(*) FROM trial_rpt_name_review_18").fetchone()[0]
        inputs.append({"table": "trial_rpt_name_review_18", "path": rel(TRIAL_RPT_NAME_REVIEW),
                       "sha256": sha(TRIAL_RPT_NAME_REVIEW),
                       "rows": counts["trial_rpt_name_review_18"]})
        connection.execute("CREATE TABLE trial_jockey_official_web_rpt_5079 AS "
                           "SELECT * FROM read_json_auto(?, format='newline_delimited')",
                           [str(TRIAL_WEB_5079)])
        counts["trial_jockey_official_web_rpt_5079"] = connection.execute(
            "SELECT count(*) FROM trial_jockey_official_web_rpt_5079").fetchone()[0]
        inputs.append({"table": "trial_jockey_official_web_rpt_5079", "path": rel(TRIAL_WEB_5079),
                       "sha256": sha(TRIAL_WEB_5079),
                       "rows": counts["trial_jockey_official_web_rpt_5079"]})
        connection.execute("CREATE TABLE trial_jockey_official_profile_supplement AS "
                           "SELECT * FROM read_json_auto(?, format='newline_delimited')",
                           [str(JOCKEY_PROFILE_SUPPLEMENT)])
        counts["trial_jockey_official_profile_supplement"] = connection.execute(
            "SELECT count(*) FROM trial_jockey_official_profile_supplement").fetchone()[0]
        inputs.append({"table": "trial_jockey_official_profile_supplement",
                       "path": rel(JOCKEY_PROFILE_SUPPLEMENT),
                       "sha256": sha(JOCKEY_PROFILE_SUPPLEMENT),
                       "rows": counts["trial_jockey_official_profile_supplement"]})
        closure_export = CALENDAR_REVIEW / "official_closure_intervals.csv"
        connection.execute("CREATE TABLE official_closure_intervals AS "
                           "SELECT * FROM read_csv(?, header=true, all_varchar=true)",
                           [str(closure_export)])
        counts["official_closure_intervals"] = connection.execute(
            "SELECT count(*) FROM official_closure_intervals").fetchone()[0]
        inputs.append({"table": "official_closure_intervals", "path": rel(closure_export),
                       "sha256": sha(closure_export), "rows": counts["official_closure_intervals"]})
        if counts["official_closure_intervals"] != calendar_review["closure_intervals"]:
            raise ValueError("Reviewed closure count does not match its manifest")
        connection.execute("CREATE VIEW confirmed_races AS "
                           "SELECT *, strptime(result_date_key, '%Y%m%d')::DATE AS race_date "
                           "FROM race_events WHERE execution_status_from_prior_ledger='executed_plan_and_result' "
                           "AND scheduled_in_plan_api='1'")
        connection.execute("CREATE VIEW confirmed_runners AS "
                           "SELECT r.* FROM runner_results r JOIN confirmed_races e "
                           "ON r.source_meet=e.source_meet AND r.result_date=e.result_date_key "
                           "AND r.result_race_no=e.result_race_no_key")
        connection.execute("CREATE VIEW confirmed_races_2017plus AS "
                           "SELECT * FROM confirmed_races WHERE result_date_key >= '20170101'")
        connection.execute("CREATE VIEW confirmed_runners_2017plus AS "
                           "SELECT r.* FROM confirmed_runners r "
                           "WHERE r.result_date >= '20170101'")
        connection.execute("CREATE VIEW race_execution_adjudicated AS "
                           "SELECT f.*, a.execution_verdict, a.adjudication_status, "
                           "a.nonexecution_scope, a.reason_text, a.supporting_reason, "
                           "a.evidence_files, a.evidence_urls, a.evidence_kind "
                           "FROM race_execution_flags f LEFT JOIN race_nonexecution_adjudication a "
                           "USING(meet,date,race_no)")
        connection.execute("CREATE VIEW unresolved_race_days AS "
                           "SELECT p.* FROM prior_unresolved_race_day_review p "
                           "WHERE NOT EXISTS (SELECT 1 FROM race_nonexecution_adjudication a "
                           "WHERE a.meet=p.meet AND a.date=replace(p.date, '-', ''))")
        connection.execute("CREATE VIEW trial_participants_resolved AS "
                           "SELECT p.*, "
                           "coalesce(nullif(p.horse_id, ''), l.official_horse_id) AS resolved_horse_id, "
                           "coalesce(nullif(p.horse_name, ''), l.horse_name) AS resolved_horse_name, "
                           "CASE WHEN p.horse_id IS NOT NULL AND p.horse_id<>'' THEN 'api_direct' "
                           "WHEN l.resolution_method='crosschecked_operational_rpt' "
                           "THEN 'crosschecked_link' "
                           "WHEN l.resolution_method='user_confirmed_rpt_profile' "
                           "THEN 'user_confirmed_link' "
                           "ELSE 'pending_review' END AS horse_identity_resolution "
                           "FROM trial_participants p LEFT JOIN trial_horse_identity_links l "
                           "USING(participant_row_id)")
        connection.execute("CREATE VIEW unresolved_trial_participants AS "
                           "SELECT * FROM trial_participants_resolved "
                           "WHERE horse_identity_resolution='pending_review'")
        connection.execute("CREATE VIEW trial_sessions_venue_reviewed AS "
                           "SELECT s.*, v.physical_venue, v.venue_review_status, "
                           "v.official_plan_url AS venue_evidence_url, "
                           "try_cast(v.reviewed_distance_m AS INTEGER) AS reviewed_distance_m, "
                           "v.distance_review_status, v.decision_basis AS venue_decision_basis "
                           "FROM trial_sessions s LEFT JOIN trial_venue_review v "
                           "ON s.source_meet_query=v.source_meet_query AND s.trial_date=v.trial_date")
        connection.execute("CREATE VIEW trial_participants_venue_reviewed AS "
                           "SELECT p.*, s.physical_venue, s.venue_review_status, "
                           "s.reviewed_distance_m, s.distance_review_status, s.venue_evidence_url "
                           "FROM trial_participants p JOIN trial_sessions_venue_reviewed s "
                           "ON p.trial_session_id=s.trial_session_id")
        connection.execute("CREATE VIEW confirmed_runners_entity_linked AS "
                           "SELECT r.*, h.entity_id_official_string AS horse_entity_id, "
                           "j.entity_id_official_string AS jockey_entity_id, "
                           "t.entity_id_official_string AS trainer_entity_id, "
                           "o.entity_id_official_string AS owner_entity_id, "
                           "CASE WHEN r.trainer_id_raw='0AAAAA' THEN 'source_placeholder' "
                           "WHEN nullif(r.trainer_id_raw, '') IS NULL THEN 'source_missing' "
                           "WHEN t.entity_id_official_string IS NOT NULL THEN 'official_id' "
                           "ELSE 'id_unmatched' END AS trainer_link_status, "
                           "CASE WHEN nullif(r.owner_id_raw, '') IS NULL THEN 'source_missing' "
                           "WHEN o.entity_id_official_string IS NOT NULL THEN 'official_id' "
                           "ELSE 'id_unmatched' END AS owner_link_status "
                           "FROM confirmed_runners r "
                           "LEFT JOIN entity_reference_roster h ON h.entity_type='horse' "
                           "AND h.entity_id_official_string=r.horse_id_raw "
                           "LEFT JOIN entity_reference_roster j ON j.entity_type='jockey' "
                           "AND j.entity_id_official_string=r.jockey_id_raw "
                           "LEFT JOIN entity_reference_roster t ON t.entity_type='trainer' "
                           "AND t.entity_id_official_string=r.trainer_id_raw "
                           "LEFT JOIN entity_reference_roster o ON o.entity_type='owner' "
                           "AND o.entity_id_official_string=r.owner_id_raw")
        connection.execute("CREATE VIEW trial_participants_entity_linked AS "
                           "SELECT p.*, h.entity_id_official_string AS horse_entity_id, "
                           "j.entity_id_official_string AS jockey_entity_id, "
                           "t.entity_id_official_string AS trainer_entity_id, "
                           "CASE WHEN nullif(p.api_jkNo, '') IS NULL OR p.api_jkNo='-' "
                           "THEN 'source_missing' "
                           "WHEN j.entity_id_official_string IS NOT NULL THEN 'official_id' "
                           "ELSE 'id_unmatched' END AS jockey_link_status, "
                           "CASE WHEN p.api_trNo='0AAAAA' THEN 'source_placeholder' "
                           "WHEN nullif(p.api_trNo, '') IS NULL OR p.api_trNo='-' "
                           "THEN 'source_missing' "
                           "WHEN t.entity_id_official_string IS NOT NULL THEN 'official_id' "
                           "ELSE 'id_unmatched' END AS trainer_link_status "
                           "FROM trial_participants_resolved p "
                           "LEFT JOIN entity_reference_roster h ON h.entity_type='horse' "
                           "AND h.entity_id_official_string=p.resolved_horse_id "
                           "LEFT JOIN entity_reference_roster j ON j.entity_type='jockey' "
                           "AND j.entity_id_official_string=p.api_jkNo "
                           "LEFT JOIN entity_reference_roster t ON t.entity_type='trainer' "
                           "AND t.entity_id_official_string=p.api_trNo")
        connection.execute("CREATE VIEW jockey_reference_ids_with_review AS "
                           "SELECT entity_id_official_string AS jockey_id, "
                           "'api_observed_roster' AS reference_source "
                           "FROM entity_reference_roster WHERE entity_type='jockey' "
                           "UNION ALL SELECT official_jockey_id AS jockey_id, "
                           "'official_cross_venue_profile' AS reference_source "
                           "FROM trial_jockey_official_profile_supplement")
        connection.execute("CREATE VIEW confirmed_runners_entity_reviewed_before_role_review AS "
                           "SELECT r.*, a.official_id_recovery_status AS role_gap_review_status, "
                           "a.archived_api26_populated_matches[1].trainer_id AS reviewed_trainer_id, "
                           "a.archived_api26_populated_matches[1].owner_id AS reviewed_owner_id, "
                           "a.archived_api26_populated_matches[1].trainer_name AS reviewed_trainer_name, "
                           "a.archived_api26_populated_matches[1].owner_name AS reviewed_owner_name, "
                           "coalesce(r.trainer_entity_id, "
                           "a.archived_api26_populated_matches[1].trainer_id) "
                           "AS trainer_entity_id_with_review, "
                           "coalesce(r.owner_entity_id, "
                           "a.archived_api26_populated_matches[1].owner_id) "
                           "AS owner_entity_id_with_review "
                           "FROM confirmed_runners_entity_linked r "
                           "LEFT JOIN race_role_gap_audit a "
                           "ON a.meet=r.source_meet AND a.race_date=r.result_date "
                           "AND a.race_no=r.result_race_no "
                           "AND a.horse_program_no=r.horse_program_no_raw "
                           "AND a.horse_id=r.horse_id_raw")
        connection.execute("CREATE VIEW trial_participants_entity_reviewed_before_role_review AS "
                           "SELECT p.*, a.rpt_jockey_name AS rpt_jockey_name_supplemental, "
                           "a.rpt_jockey_supplement_status AS jockey_name_evidence_status, "
                           "a.jockey_id_resolution_status AS jockey_id_review_status, "
                           "w.official_web_jockey_name AS official_web_jockey_name_scheduled, "
                           "w.official_web_jockey_id AS official_web_jockey_id_scheduled, "
                           "w.resolution_status AS official_web_jockey_review_status, "
                           "c.official_jockey_name AS official_web_jockey_name_conflict_reviewed, "
                           "c.official_jockey_id AS official_web_jockey_id_conflict_reviewed, "
                           "c.jockey_semantics AS official_web_conflict_jockey_semantics, "
                           "v.official_jockey_name AS official_web_jockey_name_rpt_verified, "
                           "v.official_jockey_id AS official_web_jockey_id_rpt_verified, "
                           "v.jockey_semantics AS official_web_rpt_jockey_semantics, "
                           "v.jockey_name_review_status "
                           "AS official_web_rpt_jockey_name_review_status, "
                           "coalesce(p.jockey_entity_id, v.official_jockey_id, "
                           "c.official_jockey_id, w.official_web_jockey_id) "
                           "AS jockey_entity_id_with_review, "
                           "CASE WHEN try_cast(p.api_rcTime AS DOUBLE)>0 "
                           "THEN coalesce(p.jockey_entity_id, v.official_jockey_id, "
                           "c.official_jockey_id, w.official_web_jockey_id) END "
                           "AS jockey_id_for_completed_trial, "
                           "CASE WHEN try_cast(p.api_rcTime AS DOUBLE)=0 "
                           "THEN coalesce(p.jockey_entity_id, v.official_jockey_id, "
                           "c.official_jockey_id, w.official_web_jockey_id) END "
                           "AS jockey_id_listed_without_completed_time, "
                           "coalesce(CASE WHEN v.jockey_semantics="
                           "'assigned_jockey_only_actual_ride_not_confirmed' "
                           "THEN v.official_jockey_id END, "
                           "CASE WHEN c.jockey_semantics="
                           "'assigned_jockey_only_actual_ride_not_confirmed' "
                           "THEN c.official_jockey_id END, "
                           "w.official_web_jockey_id) AS assigned_jockey_id_reviewed, "
                           "CASE WHEN p.jockey_entity_id IS NOT NULL THEN 'api_direct' "
                           "WHEN v.official_jockey_id IS NOT NULL THEN v.jockey_semantics "
                           "WHEN c.official_jockey_id IS NOT NULL THEN c.jockey_semantics "
                           "WHEN w.official_web_jockey_id IS NOT NULL "
                           "THEN 'assigned_jockey_only_actual_ride_not_confirmed' "
                           "ELSE a.jockey_id_resolution_status END "
                           "AS jockey_id_review_status_with_official_web, "
                           "n.rpt_horse_name_historical_candidate AS rpt_horse_name_review_candidate, "
                           "n.review_status AS rpt_horse_name_review_status, "
                           "n.official_db7_change_date AS rpt_horse_name_change_date_db7, "
                           "coalesce(nullif(p.api_jkName, ''), v.official_jockey_name, "
                           "c.official_jockey_name, w.official_web_jockey_name, "
                           "a.rpt_jockey_name) "
                           "AS jockey_name_with_review, "
                           "CASE WHEN nullif(p.api_jkName, '') IS NOT NULL THEN 'api_direct' "
                           "WHEN v.official_jockey_name IS NOT NULL "
                           "THEN 'official_web_rpt_row_reviewed' "
                           "WHEN c.official_jockey_name IS NOT NULL THEN 'official_web_conflict_reviewed' "
                           "WHEN w.official_web_jockey_name IS NOT NULL "
                           "THEN 'official_web_assignment_no_finish' "
                           "WHEN a.rpt_jockey_name IS NOT NULL THEN 'local_rpt_verified' "
                           "ELSE 'unresolved' END AS jockey_name_review_source "
                           "FROM trial_participants_entity_linked p "
                           "LEFT JOIN trial_jockey_gap_audit a USING(participant_row_id) "
                           "LEFT JOIN trial_jockey_official_web_missing_24 w USING(participant_row_id) "
                           "LEFT JOIN trial_jockey_official_web_conflict_18 c USING(participant_row_id) "
                           "LEFT JOIN trial_rpt_name_review_18 n USING(participant_row_id) "
                           "LEFT JOIN trial_jockey_official_web_rpt_5079 v USING(participant_row_id)")
        role_checks = load_role_reviews(connection, inputs, counts)
        counts["confirmed_races"] = connection.execute("SELECT count(*) FROM confirmed_races").fetchone()[0]
        counts["confirmed_runners"] = connection.execute("SELECT count(*) FROM confirmed_runners").fetchone()[0]
        counts["confirmed_races_2017plus"] = connection.execute(
            "SELECT count(*) FROM confirmed_races_2017plus").fetchone()[0]
        counts["confirmed_runners_2017plus"] = connection.execute(
            "SELECT count(*) FROM confirmed_runners_2017plus").fetchone()[0]
        counts["unresolved_race_days"] = connection.execute(
            "SELECT count(*) FROM unresolved_race_days").fetchone()[0]
        counts["race_execution_adjudicated"] = connection.execute(
            "SELECT count(*) FROM race_execution_adjudicated").fetchone()[0]
        counts["trial_participants_resolved"] = connection.execute(
            "SELECT count(*) FROM trial_participants_resolved").fetchone()[0]
        counts["unresolved_trial_participants"] = connection.execute(
            "SELECT count(*) FROM unresolved_trial_participants").fetchone()[0]
        counts["trial_sessions_venue_reviewed"] = connection.execute(
            "SELECT count(*) FROM trial_sessions_venue_reviewed").fetchone()[0]
        counts["trial_participants_venue_reviewed"] = connection.execute(
            "SELECT count(*) FROM trial_participants_venue_reviewed").fetchone()[0]
        counts["confirmed_runners_entity_linked"] = connection.execute(
            "SELECT count(*) FROM confirmed_runners_entity_linked").fetchone()[0]
        counts["trial_participants_entity_linked"] = connection.execute(
            "SELECT count(*) FROM trial_participants_entity_linked").fetchone()[0]
        counts["confirmed_runners_entity_reviewed"] = connection.execute(
            "SELECT count(*) FROM confirmed_runners_entity_reviewed").fetchone()[0]
        counts["trial_participants_entity_reviewed"] = connection.execute(
            "SELECT count(*) FROM trial_participants_entity_reviewed").fetchone()[0]
        counts["jockey_reference_ids_with_review"] = connection.execute(
            "SELECT count(*) FROM jockey_reference_ids_with_review").fetchone()[0]
        for table, expected in EXPECTED.items():
            if counts[table] != expected:
                raise ValueError(f"{table}: {counts[table]} != expected {expected}")
        checks = {
            "calendar_unique_venue_date": connection.execute(
                "SELECT count(*)=count(DISTINCT meet||'|'||date) FROM calendar_days").fetchone()[0],
            "race_event_unique_natural_key": connection.execute(
                "SELECT count(*)=count(DISTINCT source_meet||'|'||result_date_key||'|'||result_race_no_key) FROM race_events").fetchone()[0],
            "full_plan_keys_match_calendar_plan": connection.execute(
                "SELECT (SELECT count(*) FROM ("
                "SELECT meet,date,race_no FROM race_plan EXCEPT "
                "SELECT source_meet,race_date_key,race_no_key FROM race_plan_full_api))=0 "
                "AND (SELECT count(*) FROM race_plan)=(SELECT count(*) FROM race_plan_full_api)").fetchone()[0],
            "full_plan_unique_natural_key": connection.execute(
                "SELECT count(*)=count(DISTINCT source_meet||'|'||race_date_key||'|'||race_no_key) "
                "FROM race_plan_full_api").fetchone()[0],
            "trial_session_unique_id": connection.execute(
                "SELECT count(*)=count(DISTINCT trial_session_id) FROM trial_sessions").fetchone()[0],
            "trial_venue_review_matches_four_sessions": connection.execute(
                "SELECT count(*)=4 AND sum(try_cast(participant_rows AS INTEGER))=48 "
                "AND count(*) FILTER (WHERE venue_review_status='confirmed_official_plan_and_user_clarification' "
                "AND physical_venue='부산경남' AND reviewed_distance_m=1000 AND api_meet_label='영남')=4 "
                "FROM trial_sessions_venue_reviewed "
                "WHERE source_meet_query='3' AND trial_date='2026-09-17'").fetchone()[0],
            "trial_venue_review_unique_day": connection.execute(
                "SELECT count(*)=count(DISTINCT source_meet_query||'|'||trial_date) "
                "AND count(*)=1 AND min(reviewed_session_count)='4' "
                "AND min(reviewed_participant_rows)='48' "
                "FROM trial_venue_review").fetchone()[0],
            "trial_venue_participants_exact_scope": connection.execute(
                "SELECT count(*)=61777 AND count(DISTINCT participant_row_id)=61777 "
                "AND count(*) FILTER (WHERE physical_venue='부산경남' AND reviewed_distance_m=1000 "
                "AND source_meet_query='3' AND trial_date='2026-09-17')=48 "
                "AND count(*) FILTER (WHERE physical_venue IS NOT NULL)=48 "
                "FROM trial_participants_venue_reviewed").fetchone()[0],
            "trial_participants_have_session": connection.execute(
                "SELECT count(*)=0 FROM trial_participants p LEFT JOIN trial_sessions s "
                "ON p.trial_session_id=s.trial_session_id WHERE s.trial_session_id IS NULL").fetchone()[0],
            "trial_identity_links_unique": connection.execute(
                "SELECT count(*)=104 AND count(DISTINCT participant_row_id)=104 "
                "AND count(official_horse_id)=104 AND count(horse_name)=104 "
                "AND count(*) FILTER (WHERE rpt_horse_name=horse_name)=104 "
                "AND count(*) FILTER (WHERE resolution_method='crosschecked_operational_rpt')=99 "
                "AND count(*) FILTER (WHERE resolution_method='user_confirmed_rpt_profile')=5 "
                "FROM trial_horse_identity_links").fetchone()[0],
            "trial_identity_links_target_missing_api_rows": connection.execute(
                "SELECT count(*)=0 FROM trial_horse_identity_links l "
                "LEFT JOIN trial_participants p USING(participant_row_id) "
                "WHERE p.participant_row_id IS NULL OR p.horse_id_missing<>'true' "
                "OR p.trial_date<>l.trial_date OR p.source_meet_query<>l.source_meet_query "
                "OR p.trial_no<>l.trial_no OR p.api_chulNo<>l.api_chulNo").fetchone()[0],
            "trial_identity_104_partitioned": connection.execute(
                "SELECT count(*)=104 AND count(*) FILTER (WHERE l.participant_row_id IS NOT NULL)=104 "
                "AND count(*) FILTER (WHERE q.participant_row_id IS NOT NULL)=0 "
                "AND count(*) FILTER (WHERE l.participant_row_id IS NOT NULL "
                "AND q.participant_row_id IS NOT NULL)=0 "
                "AND count(*) FILTER (WHERE l.participant_row_id IS NULL "
                "AND q.participant_row_id IS NULL)=0 "
                "FROM unidentified_trial_participants p "
                "LEFT JOIN trial_horse_identity_links l USING(participant_row_id) "
                "LEFT JOIN trial_horse_identity_pending q USING(participant_row_id)").fetchone()[0],
            "trial_identity_pending_none": connection.execute(
                "SELECT count(*)=0 "
                "FROM trial_horse_identity_pending").fetchone()[0],
            "trial_identity_user_confirmations_linked": connection.execute(
                "SELECT count(*)=0 FROM trial_horse_identity_user_confirmations u "
                "LEFT JOIN trial_horse_identity_links l "
                "ON u.source_meet_query=l.source_meet_query AND u.trial_date=l.trial_date "
                "AND u.trial_no=l.trial_no AND u.api_chulNo=l.api_chulNo "
                "WHERE l.official_horse_id IS NULL OR l.official_horse_id<>u.official_horse_id "
                "OR l.horse_name<>u.horse_name "
                "OR l.resolution_method<>'user_confirmed_rpt_profile'").fetchone()[0],
            "trial_resolved_identity_coverage": connection.execute(
                "SELECT count(*)=61777 AND "
                "count(*) FILTER (WHERE horse_identity_resolution='crosschecked_link')=99 "
                "AND count(*) FILTER (WHERE horse_identity_resolution='user_confirmed_link')=5 "
                "AND count(*) FILTER (WHERE horse_identity_resolution='pending_review')=0 "
                "AND count(*) FILTER (WHERE resolved_horse_id IS NULL)=0 "
                "FROM trial_participants_resolved").fetchone()[0],
            "confirmed_runner_rows_not_unverified": connection.execute(
                "SELECT count(*)=0 FROM confirmed_runners WHERE in_plan_api!='1' "
                "OR execution_status!='executed_plan_and_result'").fetchone()[0],
            "official_annual_stats_match": connection.execute(
                "SELECT count(*)=0 FROM official_annual_stats_crosscheck WHERE matches!='1'").fetchone()[0],
            "no_verified_execution_on_documented_closure": connection.execute(
                "SELECT count(*)=0 FROM calendar_days WHERE official_closure_source_url!='' "
                "AND executed_race_count!='0'").fetchone()[0],
            "calendar_event_counts_preserved": connection.execute(
                "SELECT count(*)=0 FROM calendar_days c JOIN calendar_days_prior_review p USING(meet,date) "
                "WHERE c.scheduled_race_count IS DISTINCT FROM p.scheduled_race_count "
                "OR c.executed_race_count IS DISTINCT FROM p.executed_race_count "
                "OR c.trial_session_count_by_source_meet IS DISTINCT FROM p.trial_session_count_by_source_meet "
                "OR c.planned_race_without_finish_count IS DISTINCT FROM p.planned_race_without_finish_count"
            ).fetchone()[0],
            "subtype_review_original_29_exact_keys": connection.execute(
                "SELECT count(*)=29 AND count(DISTINCT r.meet||'|'||r.date||'|'||r.race_no)=29 "
                "AND count(*) FILTER (WHERE p.adjudication_status='reason_recorded_outcome_unclassified' "
                "AND r.previous_status=p.adjudication_status AND r.reviewed_status=a.adjudication_status)=29 "
                "FROM race_nonexecution_subtype_review r "
                "JOIN race_nonexecution_adjudication_prior_review p USING(meet,date,race_no) "
                "JOIN race_nonexecution_adjudication a USING(meet,date,race_no)"
            ).fetchone()[0],
            "nonexecution_verdicts_and_spine_preserved": connection.execute(
                "SELECT count(*)=116 AND count(*) FILTER (WHERE a.execution_verdict=p.execution_verdict "
                "AND a.reason_text IS NOT DISTINCT FROM p.reason_text "
                "AND a.source_result_rows=p.source_result_rows AND a.positive_finish_rows=p.positive_finish_rows)=116 "
                "FROM race_nonexecution_adjudication a JOIN race_nonexecution_adjudication_prior_review p USING(meet,date,race_no)"
            ).fetchone()[0],
            "nonexecution_116_exactly_adjudicated": connection.execute(
                "SELECT (SELECT count(*) FROM race_nonexecution_adjudication)=116 AND "
                "(SELECT count(*) FROM race_execution_adjudicated "
                "WHERE execution_status='planned_no_execution_evidence' "
                "AND execution_verdict='no_valid_completed_race')=116 AND "
                "(SELECT count(*) FROM race_execution_adjudicated "
                "WHERE execution_status='executed_plan_and_result' "
                "AND execution_verdict IS NOT NULL)=0").fetchone()[0],
            "no_unresolved_race_days": connection.execute(
                "SELECT count(*)=0 FROM unresolved_race_days").fetchone()[0],
            "section_coverage_equals_confirmed_runners": connection.execute(
                "SELECT (SELECT count(*) FROM runner_section_coverage_api)="
                "(SELECT count(*) FROM confirmed_runners) AND "
                "(SELECT count(*) FROM runner_section_coverage_api s LEFT JOIN confirmed_runners r "
                "ON s.source_file=r.source_file AND s.source_item_index=try_cast(r.source_item_index AS INTEGER) "
                "WHERE r.source_file IS NULL)=0").fetchone()[0],
            "section_measurements_have_runner": connection.execute(
                "SELECT count(*)=0 FROM section_measurements_api s LEFT JOIN runner_section_coverage_api r "
                "ON s.source_file=r.source_file AND s.source_item_index=r.source_item_index "
                "WHERE r.source_file IS NULL").fetchone()[0],
            "all_finishers_missing_sections_reviewed": connection.execute(
                "SELECT count(*)=0 FROM runner_section_coverage_api s "
                "JOIN confirmed_runners r ON s.source_file=r.source_file "
                "AND s.source_item_index=try_cast(r.source_item_index AS INTEGER) "
                "LEFT JOIN section_missing_finisher_review v ON cast(s.meet AS VARCHAR)=v.meet "
                "AND s.race_date=v.race_date AND cast(s.race_no AS VARCHAR)=v.race_no "
                "AND s.horse_id=v.horse_id AND cast(s.horse_program_no AS VARCHAR)=v.horse_program_no "
                "WHERE s.has_section_data=false AND r.positive_finish_evidence='1' "
                "AND v.horse_id IS NULL").fetchone()[0],
            "reviewed_missing_sections_are_confirmed_finishers": connection.execute(
                "SELECT count(*)=0 FROM section_missing_finisher_review v "
                "LEFT JOIN runner_section_coverage_api s ON cast(s.meet AS VARCHAR)=v.meet "
                "AND s.race_date=v.race_date AND cast(s.race_no AS VARCHAR)=v.race_no "
                "AND s.horse_id=v.horse_id AND cast(s.horse_program_no AS VARCHAR)=v.horse_program_no "
                "LEFT JOIN confirmed_runners r ON s.source_file=r.source_file "
                "AND s.source_item_index=try_cast(r.source_item_index AS INTEGER) "
                "WHERE s.horse_id IS NULL OR s.has_section_data=true "
                "OR r.positive_finish_evidence IS DISTINCT FROM '1'").fetchone()[0],
            "entity_roster_unique_official_id": connection.execute(
                "SELECT count(*)=count(DISTINCT entity_type||'|'||entity_id_official_string) "
                "AND count(*) FILTER (WHERE entity_id_official_string IN ('', '-', '0AAAAA'))=0 "
                "FROM entity_reference_roster").fetchone()[0],
            "entity_race_join_cardinality": connection.execute(
                "SELECT count(*)=330465 AND count(horse_entity_id)=330465 "
                "AND count(jockey_entity_id)=330465 "
                "AND count(*) FILTER (WHERE trainer_link_status='source_missing')=38 "
                "AND count(*) FILTER (WHERE trainer_link_status='source_placeholder')=23 "
                "AND count(*) FILTER (WHERE owner_link_status='source_missing')=38 "
                "AND count(*) FILTER (WHERE trainer_link_status='id_unmatched' "
                "OR owner_link_status='id_unmatched')=0 "
                "FROM confirmed_runners_entity_linked").fetchone()[0],
            "entity_race_missing_trainer_owner_same_rows": connection.execute(
                "SELECT count(*)=0 FROM confirmed_runners_entity_linked "
                "WHERE (trainer_link_status='source_missing') "
                "IS DISTINCT FROM (owner_link_status='source_missing')").fetchone()[0],
            "race_role_gap_audit_exact_source_rows": connection.execute(
                "SELECT count(*)=38 "
                "AND count(DISTINCT meet||'|'||race_date||'|'||race_no||'|'||horse_program_no||'|'||horse_id)=38 "
                "AND count(*) FILTER (WHERE rank_raw='95' AND race_time_raw='0' "
                "AND api4_3_role_fields='all_four_keys_absent')=38 "
                "AND count(*) FILTER (WHERE rpt_evidence IS NOT NULL)=21 "
                "AND count(*) FILTER (WHERE official_id_recovery_status="
                "'crosschecked_archived_api26_exact_event_key')=1 "
                "FROM race_role_gap_audit").fetchone()[0],
            "race_role_gap_reviewed_join_cardinality": connection.execute(
                "SELECT count(*)=330465 AND count(*) FILTER (WHERE role_gap_review_status IS NOT NULL)=38 "
                "AND count(reviewed_trainer_id)=1 AND count(reviewed_owner_id)=1 "
                "AND count(trainer_entity_id_with_review)=330405 "
                "AND count(owner_entity_id_with_review)=330428 "
                "FROM confirmed_runners_entity_reviewed_before_role_review").fetchone()[0],
            "race_role_gap_reviewed_ids_in_roster": connection.execute(
                "SELECT count(*)=0 FROM confirmed_runners_entity_reviewed r "
                "WHERE (reviewed_trainer_id IS NOT NULL AND NOT EXISTS ("
                "SELECT 1 FROM entity_reference_roster e WHERE e.entity_type='trainer' "
                "AND e.entity_id_official_string=r.reviewed_trainer_id)) "
                "OR (reviewed_owner_id IS NOT NULL AND NOT EXISTS ("
                "SELECT 1 FROM entity_reference_roster e WHERE e.entity_type='owner' "
                "AND e.entity_id_official_string=r.reviewed_owner_id))").fetchone()[0],
            "entity_trial_join_cardinality": connection.execute(
                "SELECT count(*)=61777 AND count(horse_entity_id)=61777 "
                "AND count(*) FILTER (WHERE jockey_link_status='source_missing')=5121 "
                "AND count(*) FILTER (WHERE trainer_link_status='source_missing')=84 "
                "AND count(*) FILTER (WHERE trainer_link_status='source_placeholder')=140 "
                "AND count(*) FILTER (WHERE jockey_link_status='id_unmatched' "
                "OR trainer_link_status='id_unmatched')=0 "
                "FROM trial_participants_entity_linked").fetchone()[0],
            "trial_jockey_gap_audit_exact_source_rows": connection.execute(
                "SELECT count(*)=5121 AND count(DISTINCT participant_row_id)=5121 "
                "AND count(*) FILTER (WHERE api_raw_jockey_keys_present.jkNo=false "
                "AND api_raw_jockey_keys_present.jkName=false "
                "AND api_jkNo IS NULL AND api_jkName IS NULL "
                "AND jockey_id_resolution_status="
                "'unresolved_no_official_jockey_id_in_rpt_do_not_infer_by_name')=5121 "
                "FROM trial_jockey_gap_audit").fetchone()[0],
            "trial_jockey_official_web_24_exact_keys": connection.execute(
                "SELECT count(*)=24 AND count(DISTINCT w.participant_row_id)=24 "
                "AND count(*) FILTER (WHERE w.official_web_horse_id=p.api_hrNo "
                "AND w.api_horse_id=p.api_hrNo "
                "AND w.official_web_horse_name=p.api_hrName "
                "AND w.date=p.api_trainDate "
                "AND cast(w.meet AS VARCHAR)=p.source_meet_query "
                "AND cast(w.trial_no AS VARCHAR)=p.api_trainNo "
                "AND cast(w.horse_program_no AS VARCHAR)=p.api_chulNo "
                "AND nullif(w.official_web_jockey_name, '') IS NOT NULL "
                "AND nullif(w.official_web_jockey_id, '') IS NOT NULL "
                "AND p.api_jkNo IS NULL AND p.api_jkName IS NULL)=24 "
                "FROM trial_jockey_official_web_missing_24 w "
                "JOIN trial_participants p USING(participant_row_id)").fetchone()[0],
            "trial_jockey_official_web_24_ids_in_roster": connection.execute(
                "SELECT count(*)=0 FROM trial_jockey_official_web_missing_24 w "
                "WHERE NOT EXISTS (SELECT 1 FROM entity_reference_roster e "
                "WHERE e.entity_type='jockey' "
                "AND e.entity_id_official_string=w.official_web_jockey_id) "
                "OR NOT EXISTS (SELECT 1 FROM entity_name_observations n "
                "WHERE n.entity_type='jockey' AND n.entity_id=w.official_web_jockey_id "
                "AND n.name_raw=w.official_web_jockey_name)").fetchone()[0],
            "trial_jockey_official_web_18_exact_keys": connection.execute(
                "SELECT count(*)=18 AND count(DISTINCT w.participant_row_id)=18 "
                "AND count(*) FILTER (WHERE w.official_horse_id=p.api_hrNo "
                "AND w.api_horse_id=p.api_hrNo "
                "AND w.official_horse_name=p.api_hrName "
                "AND w.date=p.api_trainDate "
                "AND cast(w.meet AS VARCHAR)=p.source_meet_query "
                "AND cast(w.trial_no AS VARCHAR)=p.api_trainNo "
                "AND cast(w.horse_program_no AS VARCHAR)=p.api_chulNo "
                "AND nullif(w.official_jockey_name, '') IS NOT NULL "
                "AND nullif(w.official_jockey_id, '') IS NOT NULL "
                "AND p.api_jkNo IS NULL AND p.api_jkName IS NULL)=18 "
                "AND count(*) FILTER (WHERE w.jockey_semantics='official_completed_trial_rider')=16 "
                "AND count(*) FILTER (WHERE w.jockey_semantics="
                "'assigned_jockey_only_actual_ride_not_confirmed')=2 "
                "FROM trial_jockey_official_web_conflict_18 w "
                "JOIN trial_participants p USING(participant_row_id)").fetchone()[0],
            "trial_jockey_official_web_18_ids_in_roster": connection.execute(
                "SELECT count(*)=0 FROM trial_jockey_official_web_conflict_18 w "
                "WHERE NOT EXISTS (SELECT 1 FROM entity_reference_roster e "
                "WHERE e.entity_type='jockey' "
                "AND e.entity_id_official_string=w.official_jockey_id) "
                "OR NOT EXISTS (SELECT 1 FROM entity_name_observations n "
                "WHERE n.entity_type='jockey' AND n.entity_id=w.official_jockey_id "
                "AND n.name_raw=w.official_jockey_name)").fetchone()[0],
            "trial_rpt_name_review_api_canonical_and_status": connection.execute(
                "SELECT count(*)=18 AND count(DISTINCT n.participant_row_id)=18 "
                "AND count(*) FILTER (WHERE n.api_horse_id=p.api_hrNo "
                "AND n.api_horse_name_canonical=p.api_hrName "
                "AND n.rpt_horse_name_historical_candidate<>p.api_hrName)=18 "
                "AND count(*) FILTER (WHERE n.review_status='official_db7_name_change_confirmed' "
                "AND n.official_db7_change_date IS NOT NULL)=13 "
                "AND count(*) FILTER (WHERE n.review_status='name_difference_unresolved_no_individual_db7_proof' "
                "AND n.official_db7_change_date IS NULL)=5 "
                "FROM trial_rpt_name_review_18 n "
                "JOIN trial_participants p USING(participant_row_id)").fetchone()[0],
            "trial_web_5079_exact_event_horse_and_time": connection.execute(
                "SELECT count(*)=5079 AND count(DISTINCT w.participant_row_id)=5079 "
                "AND count(*) FILTER (WHERE cast(w.meet AS VARCHAR)=p.source_meet_query "
                "AND w.date=p.api_trainDate "
                "AND cast(w.trial_no AS VARCHAR)=p.api_trainNo "
                "AND cast(w.horse_program_no AS VARCHAR)=p.api_chulNo "
                "AND w.horse_id_reviewed=p.resolved_horse_id "
                "AND w.official_horse_id=p.resolved_horse_id "
                "AND round(w.api_time_seconds,1)=round(try_cast(p.api_rcTime AS DOUBLE),1) "
                "AND (round(w.official_time_seconds,1)=round(try_cast(p.api_rcTime AS DOUBLE),1) "
                "OR (w.official_time_seconds IS NULL AND try_cast(p.api_rcTime AS DOUBLE)=0)) "
                "AND w.official_jockey_id IS NOT NULL "
                "AND w.official_jockey_name IS NOT NULL)=5079 "
                "AND count(*) FILTER (WHERE w.jockey_semantics="
                "'official_completed_trial_rider' AND w.api_time_seconds>0)=4420 "
                "AND count(*) FILTER (WHERE w.jockey_semantics="
                "'assigned_jockey_only_actual_ride_not_confirmed' "
                "AND w.api_time_seconds=0)=659 "
                "AND count(*) FILTER (WHERE w.jockey_name_review_status='exact')=4903 "
                "AND count(*) FILTER (WHERE w.jockey_name_review_status="
                "'rpt_short_name_official_full_name' AND w.rpt_jockey_name='이쿠' "
                "AND w.official_jockey_name='이쿠야스' "
                "AND w.official_jockey_id='080426')=142 "
                "AND count(*) FILTER (WHERE w.jockey_name_review_status="
                "'rpt_historical_name_official_current_name_crosswalk_unconfirmed' "
                "AND w.rpt_jockey_name='정형래' "
                "AND w.official_jockey_name='정우주' "
                "AND w.official_jockey_id='080588')=34 "
                "FROM trial_jockey_official_web_rpt_5079 w "
                "JOIN trial_participants_resolved p USING(participant_row_id)").fetchone()[0],
            "trial_web_5079_jockey_ids_in_roster": connection.execute(
                "SELECT count(*)=0 FROM trial_jockey_official_web_rpt_5079 w "
                "WHERE NOT EXISTS (SELECT 1 FROM jockey_reference_ids_with_review e "
                "WHERE e.jockey_id=w.official_jockey_id)").fetchone()[0],
            "jockey_reference_supplement_exact": connection.execute(
                "SELECT count(*)=1 AND min(official_jockey_id)='003097' "
                "AND min(official_jockey_name)='김동규' AND min(profile_meet)=2 "
                "FROM trial_jockey_official_profile_supplement").fetchone()[0],
            "jockey_reference_reviewed_unique": connection.execute(
                "SELECT count(*)=338 AND count(DISTINCT jockey_id)=338 "
                "FROM jockey_reference_ids_with_review").fetchone()[0],
            "all_trial_jockey_ids_in_reviewed_reference": connection.execute(
                "SELECT count(*)=0 FROM trial_participants_entity_reviewed p "
                "WHERE NOT EXISTS (SELECT 1 FROM jockey_reference_ids_with_review j "
                "WHERE j.jockey_id=p.jockey_entity_id_with_review)").fetchone()[0],
            "trial_jockey_gap_reviewed_join_cardinality": connection.execute(
                "SELECT count(*)=61777 "
                "AND count(jockey_name_evidence_status)=5121 "
                "AND count(jockey_id_review_status)=5121 "
                "AND count(jockey_entity_id)=56656 "
                "AND count(jockey_name_with_review)=61777 "
                "AND count(official_web_jockey_name_scheduled)=24 "
                "AND count(official_web_jockey_id_scheduled)=24 "
                "AND count(official_web_jockey_name_conflict_reviewed)=18 "
                "AND count(official_web_jockey_id_conflict_reviewed)=18 "
                "AND count(official_web_jockey_name_rpt_verified)=5079 "
                "AND count(official_web_jockey_id_rpt_verified)=5079 "
                "AND count(jockey_entity_id_with_review)=61777 "
                "AND count(jockey_id_for_completed_trial)=54502 "
                "AND count(jockey_id_listed_without_completed_time)=7275 "
                "AND count(*) FILTER (WHERE jockey_id_for_completed_trial IS NOT NULL "
                "AND jockey_id_listed_without_completed_time IS NOT NULL)=0 "
                "AND count(assigned_jockey_id_reviewed)=685 "
                "AND count(*) FILTER (WHERE jockey_name_review_source='api_direct')=56656 "
                "AND count(*) FILTER (WHERE jockey_name_review_source="
                "'official_web_rpt_row_reviewed')=5079 "
                "AND count(*) FILTER (WHERE jockey_name_review_source="
                "'official_web_conflict_reviewed')=18 "
                "AND count(*) FILTER (WHERE jockey_name_review_source="
                "'official_web_assignment_no_finish')=24 "
                "AND count(*) FILTER (WHERE official_web_jockey_review_status IS NOT NULL "
                "AND jockey_name_evidence_status<>'unavailable_no_local_rpt_day')=0 "
                "AND count(*) FILTER (WHERE official_web_conflict_jockey_semantics IS NOT NULL "
                "AND jockey_name_evidence_status<>'excluded_unresolved_horse_name_mismatch')=0 "
                "AND count(*) FILTER (WHERE jockey_name_evidence_status IS NOT NULL "
                "AND jockey_link_status<>'source_missing')=0 "
                "AND count(*) FILTER (WHERE rpt_jockey_name_supplemental IS NOT NULL "
                "AND jockey_name_evidence_status NOT IN ("
                "'verified_api_horse_name_exact_rpt_match', "
                "'verified_resolved_horse_link_exact_rpt_match'))=0 "
                "AND count(rpt_jockey_name_supplemental)=5079 "
                "AND count(*) FILTER (WHERE jockey_name_evidence_status="
                "'excluded_unresolved_horse_name_mismatch')=18 "
                "AND count(*) FILTER (WHERE jockey_name_evidence_status="
                "'unavailable_no_local_rpt_day')=24 "
                "FROM trial_participants_entity_reviewed").fetchone()[0],
            "entity_unresolved_ledger_partition": connection.execute(
                "SELECT count(*)=5548 "
                "AND count(*) FILTER (WHERE entity_type='horse' AND source_observation='trial_api' "
                "AND resolution_status='source_api_id_missing_but_separate_core_linkage_reviewed')=104 "
                "AND count(*) FILTER (WHERE entity_type='jockey' AND source_observation='trial_api')=5121 "
                "AND count(*) FILTER (WHERE entity_type='trainer' AND source_observation='race_result')=61 "
                "AND count(*) FILTER (WHERE entity_type='trainer' AND source_observation='trial_api')=224 "
                "AND count(*) FILTER (WHERE entity_type='owner' AND source_observation='race_result')=38 "
                "FROM unresolved_entity_references").fetchone()[0],
        }
        checks.update(role_checks)
        if not all(checks.values()):
            raise ValueError(f"Core DB check failed: {checks}")
        connection.execute("CREATE TABLE source_manifests(name VARCHAR, json_text VARCHAR)")
        for name, path in (
            ("calendar_api", CAL / "manifest.json"),
            ("calendar_summary", CAL / "daily_calendar_summary.json"),
            ("race_results", RACE / "manifest.json"),
            ("trial_results", TRIAL / "source_manifest.json"),
            ("trial_validation", TRIAL / "validation.json"),
            ("trial_identity_validation", TRIAL_IDENTITY / "validation.json"),
            ("section_api", SECTION / "manifest.json"),
            ("entity_reference", ENTITY / "manifest.json"),
            ("trial_jockey_gap_audit", TRIAL_JOCKEY_GAP_MANIFEST),
            ("trial_jockey_official_web_missing_24", TRIAL_WEB_24_MANIFEST),
            ("trial_jockey_official_web_conflict_18", TRIAL_WEB_18_MANIFEST),
            ("trial_rpt_name_review_18", TRIAL_RPT_NAME_REVIEW_MANIFEST),
            ("trial_jockey_official_web_rpt_5079", TRIAL_WEB_5079_MANIFEST),
            ("trial_jockey_official_profile_supplement", JOCKEY_PROFILE_SUPPLEMENT_MANIFEST),
            ("trainer_owner_exception_review", ROLE_REVIEW / "manifest.json"),
            ("trial_venue_recheck", TRIAL_VENUE / "manifest.json"),
            ("trial_trainer_source_error_disposition", ERROR_REVIEW / "resolution_manifest.json"),
            ("calendar_closure_subtype_review", CALENDAR_REVIEW / "manifest.json"),
            ("calendar_closure_subtype_review_v2", ROOT / "thoroughbred/research/20261001_calendar_core_review_v2/manifest.json"),
            ("calendar_closure_subtype_review_v3", ROOT / "thoroughbred/research/20261001_remaining_closure_cancel_v3/core_review/manifest.json"),
        ):
            connection.execute("INSERT INTO source_manifests VALUES (?, ?)",
                               [name, path.read_text(encoding="utf-8")])
            inputs.append({"table": "source_manifests", "path": rel(path),
                           "sha256": sha(path), "rows": None})
        inputs.append({"table": "trial_venue_review_evidence", "path": rel(VENUE_RPT),
                       "sha256": sha(VENUE_RPT), "rows": None})
        inputs.append({"table": "calendar_review_approved_inputs", "path": rel(CALENDAR_REVIEW / "approved_inputs.json"),
                       "sha256": sha(CALENDAR_REVIEW / "approved_inputs.json"), "rows": None})
        for record in calendar_review["pinned_files"]:
            inputs.append({"table": "calendar_review_evidence", "path": record["path"],
                           "sha256": record["sha256"], "rows": None})
        for record in json.loads((TRIAL_VENUE / "manifest.json").read_text(encoding="utf-8"))["pinned_files"]:
            inputs.append({"table": "trial_venue_review_evidence", "path": record["path"],
                           "sha256": record["sha256"], "rows": None})
        connection.execute("CHECKPOINT")
    finally:
        connection.close()
    os.replace(temp, DB)
    manifest = {"version": 1, "built_at_utc": datetime.now(timezone.utc).isoformat(),
                "scope": "2010-01-01 through 2026-09-29; Seoul, Busan-Gyeongnam, Yeongcheon; no Jeju",
                "database": rel(DB), "database_sha256": sha(DB),
                "input_files": inputs, "table_and_view_counts": counts, "checks": checks,
                "status": (
                    "staged_core_not_frozen; closure coverage " + calendar_review["closure_coverage_status"]
                    + "; 22 trial trainer source errors closed without IDs; "
                    + str(calendar_review["adjudication_status_counts"].get("reason_recorded_outcome_unclassified", 0))
                    + " noncompletion subtypes qualified")}
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                                       encoding="utf-8")
    print(json.dumps({"database": str(DB), "counts": counts, "checks": checks}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
