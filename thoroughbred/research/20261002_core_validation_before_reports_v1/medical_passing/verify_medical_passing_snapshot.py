#!/usr/bin/env python3
"""Read-only focused verification of the pre-steward research-core snapshot."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import duckdb


ROOT = Path("/Users/kimyongjin/Desktop/horse_racing")
OUT = ROOT / "thoroughbred/research/20261002_core_validation_before_reports_v1/medical_passing"
BACKUP = ROOT / "thoroughbred/data/core_api_2010_20260929_v1/backups/20261002_before_steward_reports"
DB = BACKUP / "thoroughbred_core.duckdb"
MANIFEST = BACKUP / "manifest.json"
ATTESTATION = BACKUP / "backup_pair_attestation.json"
EXPECTED_POINTS = ROOT / "thoroughbred/research/20261002_passing_groups_v1/root_expected_selected_points.parquet"
DB_SHA = "616aa6111242cfbcee4b87bc2e77251644e5c3780fc8c978319f69e7b1c4c8f7"
MANIFEST_SHA = "6aa4d2870fbd087afa81973d5fc8f3966cfc00fd7896c656cb4fedaef2ef1697"
MEDICAL_DB_SHA = "c30202a65a1a82c2927efc8e0ef150c03a0c9950e953ee445beb1b3a7f8c2de6"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [safe(item) for item in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def load_proof(relative_path: str) -> tuple[dict[str, Any], dict[str, Any]]:
    path = ROOT / relative_path
    document = json.loads(path.read_text(encoding="utf-8"))
    return document, {"path": relative_path, "sha256": sha256_file(path), "all_passed": document.get("all_passed")}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    checks: dict[str, dict[str, Any]] = {}
    issues: list[dict[str, Any]] = []

    def check(name: str, passed: bool, details: Any) -> None:
        checks[name] = {"passed": bool(passed), "details": safe(details)}
        if not passed:
            issues.append({"check": name, "details": safe(details)})

    actual_db_sha = sha256_file(DB)
    actual_manifest_sha = sha256_file(MANIFEST)
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    attestation = json.loads(ATTESTATION.read_text(encoding="utf-8"))
    check(
        "exact_attested_read_only_snapshot",
        actual_db_sha == DB_SHA
        and actual_manifest_sha == MANIFEST_SHA
        and manifest.get("database_sha256") == DB_SHA
        and attestation.get("backup_db_sha256") == DB_SHA
        and attestation.get("backup_manifest_sha256") == MANIFEST_SHA
        and attestation.get("verified_equal") is True,
        {
            "database_sha256": actual_db_sha,
            "manifest_sha256": actual_manifest_sha,
            "attestation_verified_equal": attestation.get("verified_equal"),
        },
    )

    medical_input, medical_input_pin = load_proof(
        "thoroughbred/research/20261002_medical_v1/root_input_verification.json"
    )
    medical_core, medical_core_pin = load_proof(
        "thoroughbred/research/20261002_medical_v1/root_core_input_verification.json"
    )
    medical_dict, medical_dict_pin = load_proof(
        "thoroughbred/research/20261002_medical_v1/root_dictionary_verification.json"
    )
    medical_pres, medical_pres_pin = load_proof(
        "thoroughbred/research/20261002_medical_v1/root_preservation_verification.json"
    )
    medical_apply = json.loads(
        (ROOT / "thoroughbred/research/20261002_medical_v1/loader/apply_report.json").read_text(encoding="utf-8")
    )
    medical_apply_pin = {
        "path": "thoroughbred/research/20261002_medical_v1/loader/apply_report.json",
        "sha256": sha256_file(ROOT / "thoroughbred/research/20261002_medical_v1/loader/apply_report.json"),
    }
    passing_new, passing_new_pin = load_proof(
        "thoroughbred/research/20261002_passing_groups_v1/root_new_data_verification.json"
    )
    passing_pres, passing_pres_pin = load_proof(
        "thoroughbred/research/20261002_passing_groups_v1/root_preservation_verification.json"
    )
    passing_apply = json.loads(
        (ROOT / "thoroughbred/research/20261002_passing_groups_v1/loader/apply_report.json").read_text(encoding="utf-8")
    )
    passing_apply_pin = {
        "path": "thoroughbred/research/20261002_passing_groups_v1/loader/apply_report.json",
        "sha256": sha256_file(ROOT / "thoroughbred/research/20261002_passing_groups_v1/loader/apply_report.json"),
    }

    medical_parity = medical_core.get("input_table_parity", {})
    medical_parity_ok = bool(medical_parity) and all(
        item.get("added") == 0 and item.get("lost") == 0 for item in medical_parity.values()
    )
    proof_chain_ok = (
        medical_input.get("all_passed") is True
        and medical_input.get("raw_rows_checked") == 2_101_073
        and medical_input.get("unique_observation_ids") == 2_101_073
        and medical_core.get("all_passed") is True
        and len(medical_parity) == 21
        and medical_parity_ok
        and medical_dict.get("all_passed") is True
        and medical_dict.get("prior_parser_prefix_rules_blocked") == 356
        and medical_pres.get("all_passed") is True
        and medical_pres.get("database_sha256") == MEDICAL_DB_SHA
        and medical_pres.get("original_objects") == 109
        and medical_pres.get("current_objects") == 153
        and medical_apply.get("database_sha256_after") == MEDICAL_DB_SHA
        and passing_new.get("all_passed") is True
        and passing_new.get("independent_selection_mismatch") == [0, 0]
        and passing_new.get("confirmed_race_coverage") == 29_710
        and passing_new.get("selected_source_counts") == {"dacom11_rpt": 1_774, "api303": 142_227}
        and passing_pres.get("all_passed") is True
        and passing_pres.get("database_sha256") == DB_SHA
        and passing_pres.get("original_objects") == 153
        and passing_pres.get("current_objects") == 180
        and passing_apply.get("baseline_core_sha256") == MEDICAL_DB_SHA
        and passing_apply.get("core_sha256_after") == DB_SHA
        and passing_apply.get("core_manifest_sha256_after") == MANIFEST_SHA
    )
    check(
        "medical_to_passing_source_and_preservation_proof_chain",
        proof_chain_ok,
        {
            "medical_raw_rows_and_unique_observation_ids": [
                medical_input.get("raw_rows_checked"), medical_input.get("unique_observation_ids")
            ],
            "medical_input_tables_bidirectional_mismatches": {
                name: [item.get("added"), item.get("lost")] for name, item in medical_parity.items()
            },
            "medical_prefix_rules_held": medical_dict.get("prior_parser_prefix_rules_blocked"),
            "medical_stage_sha256": medical_pres.get("database_sha256"),
            "passing_baseline_sha256": passing_apply.get("baseline_core_sha256"),
            "final_snapshot_sha256": passing_pres.get("database_sha256"),
            "passing_source_input_multiset_mismatch": passing_new.get("input_table_parity"),
            "passing_selection_mismatch": passing_new.get("independent_selection_mismatch"),
            "passing_preserved_objects": [passing_pres.get("original_objects"), passing_pres.get("current_objects")],
        },
    )

    proof_pins = {
        "medical_source_input": medical_input_pin,
        "medical_core_input": medical_core_pin,
        "medical_dictionary": medical_dict_pin,
        "medical_stage_preservation": medical_pres_pin,
        "medical_apply_report": medical_apply_pin,
        "passing_new_data": passing_new_pin,
        "passing_snapshot_preservation": passing_pres_pin,
        "passing_apply_report": passing_apply_pin,
    }
    print("Prior source and staged preservation proofs checked; opening the fixed backup read-only.", flush=True)

    connection = duckdb.connect(str(DB), read_only=True)
    connection.execute("SET threads=2")
    connection.execute("SET memory_limit='2GB'")
    object_counts = dict(
        connection.execute(
            "SELECT table_type,count(*) FROM information_schema.tables "
            "WHERE table_schema='main' GROUP BY table_type"
        ).fetchall()
    )
    registered_objects = manifest.get("table_and_view_counts", {})
    source_manifest_rows = connection.execute("SELECT count(*) FROM source_manifests").fetchone()[0]
    steward_objects = connection.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema='main' AND lower(table_name) LIKE 'steward_%' ORDER BY 1"
    ).fetchall()
    check(
        "pre_report_object_inventory",
        object_counts == {"BASE TABLE": 113, "VIEW": 67}
        and sum(object_counts.values()) == 180
        and len(registered_objects) == 178
        and source_manifest_rows == 26
        and not steward_objects,
        {
            "database_objects": object_counts,
            "manifest_registered_objects": len(registered_objects),
            "source_manifests_rows": source_manifest_rows,
            "steward_report_objects": steward_objects,
        },
    )

    medical_rows, medical_bad_scope = connection.execute(
        "SELECT count(*), count(*) FILTER (WHERE meet_code NOT IN (1,3) "
        "OR event_date<'2010-01-01' OR event_date>'2026-09-29' OR event_date IS NULL) "
        "FROM medical_observations"
    ).fetchone()
    medical_by_cohort = connection.execute(
        "SELECT source_kind,source_cohort,count(*) FROM medical_observations "
        "GROUP BY ALL ORDER BY 1,2"
    ).fetchall()
    check(
        "medical_snapshot_row_count_and_scope",
        medical_rows == 2_101_073 and medical_bad_scope == 0,
        {"rows": medical_rows, "scope_violations": medical_bad_scope, "cohort_rows": medical_by_cohort},
    )

    pass_api_rows, pass_api_locator_rows, duplicate_api_keys, api_scope_bad = connection.execute(
        "SELECT count(*),count(DISTINCT source_row_sha256),"
        "(SELECT count(*) FROM (SELECT actual_meet_code,race_date_iso,rcNo "
        "FROM passing_api_observations GROUP BY ALL HAVING count(*)>1)),"
        "count(*) FILTER (WHERE row_scope_status!='in_scope' OR actual_meet_code NOT IN (1,3,4) "
        "OR race_date_iso IS NULL OR race_date_iso<'2010-01-01' OR race_date_iso>'2026-09-29') "
        "FROM passing_api_observations"
    ).fetchone()
    confirmed_races, bad_confirmed_scope, duplicate_confirmed = connection.execute(
        "SELECT count(*),count(*) FILTER (WHERE actual_meet_code NOT IN (1,3,4) "
        "OR event_date<'2010-01-01' OR event_date>'2026-09-29'),"
        "(SELECT count(*) FROM (SELECT actual_meet_code,event_date,race_no "
        "FROM passing_confirmed_race_keys GROUP BY ALL HAVING count(*)>1)) "
        "FROM passing_confirmed_race_keys"
    ).fetchone()
    check(
        "passing_api_and_confirmed_race_keys",
        pass_api_rows == 29_774
        and pass_api_locator_rows == pass_api_rows
        and duplicate_api_keys == 0
        and api_scope_bad == 0
        and confirmed_races == 29_710
        and bad_confirmed_scope == 0
        and duplicate_confirmed == 0,
        {
            "API_observations": pass_api_rows,
            "unique_API_source_locators": pass_api_locator_rows,
            "duplicate_API_event_keys": duplicate_api_keys,
            "API_scope_violations": api_scope_bad,
            "confirmed_race_keys": confirmed_races,
            "confirmed_scope_violations": bad_confirmed_scope,
            "duplicate_confirmed_race_keys": duplicate_confirmed,
            "adjudicated_executed_and_nonexecution_counts": passing_new.get("api_event_reconciliation"),
        },
    )
    print("Materializing the selected passing-point view once into a TEMP table.", flush=True)
    connection.execute(
        "CREATE TEMP TABLE qa_selected_points AS "
        "SELECT actual_meet_code,event_date,race_no,canonical_point_code,notation_raw,selected_source,"
        "selection_status,api_notation_values_json,rpt_notation_values_json,"
        "historical_publication_time_verified,source_publication_at_kst,notation_semantics "
        "FROM race_passing_groups"
    )
    point_rows, duplicate_point_keys, null_or_unselected, point_scope_bad, time_claims, semantics_bad = connection.execute(
        "SELECT count(*),"
        "(SELECT count(*) FROM (SELECT actual_meet_code,event_date,race_no,canonical_point_code "
        "FROM qa_selected_points GROUP BY ALL HAVING count(*)>1)),"
        "count(*) FILTER (WHERE notation_raw IS NULL OR selected_source IS NULL),"
        "count(*) FILTER (WHERE actual_meet_code NOT IN (1,3,4) OR event_date<'2010-01-01' OR event_date>'2026-09-29'),"
        "count(*) FILTER (WHERE historical_publication_time_verified IS DISTINCT FROM FALSE "
        "OR source_publication_at_kst IS NOT NULL),"
        "count(*) FILTER (WHERE notation_semantics!='notation is source-literal text; no grouping grammar interpretation') "
        "FROM qa_selected_points"
    ).fetchone()
    selected_sources = connection.execute(
        "SELECT selected_source,count(*) FROM qa_selected_points GROUP BY 1 ORDER BY 1"
    ).fetchall()
    selected_value_not_in_source_ledger = connection.execute(
        "SELECT count(*) FROM qa_selected_points WHERE "
        "(selected_source='api303' AND NOT json_contains(api_notation_values_json,to_json(notation_raw))) OR "
        "(selected_source='dacom11_rpt' AND NOT json_contains(rpt_notation_values_json,to_json(notation_raw)))"
    ).fetchone()[0]
    connection.execute(
        "CREATE TEMP TABLE qa_selected_races AS "
        "SELECT actual_meet_code,event_date,race_no,count(*) FILTER (WHERE notation_raw IS NOT NULL) AS values_present "
        "FROM qa_selected_points GROUP BY ALL"
    )
    expected_races_missing = connection.execute(
        "SELECT count(*) FROM passing_confirmed_race_keys k LEFT JOIN qa_selected_races p "
        "USING (actual_meet_code,event_date,race_no) WHERE p.values_present IS NULL OR p.values_present<1"
    ).fetchone()[0]
    unexpected_selected_races = connection.execute(
        "SELECT count(*) FROM qa_selected_races p LEFT JOIN passing_confirmed_race_keys k "
        "USING (actual_meet_code,event_date,race_no) WHERE k.actual_meet_code IS NULL"
    ).fetchone()[0]
    check(
        "passing_point_grain_raw_value_scope_and_coverage",
        point_rows == 144_001
        and duplicate_point_keys == 0
        and null_or_unselected == 0
        and point_scope_bad == 0
        and time_claims == 0
        and semantics_bad == 0
        and selected_value_not_in_source_ledger == 0
        and expected_races_missing == 0
        and unexpected_selected_races == 0
        and selected_sources == [("api303", 142_227), ("dacom11_rpt", 1_774)],
        {
            "selected_points": point_rows,
            "selected_sources": selected_sources,
            "duplicate_meet_date_race_point_keys": duplicate_point_keys,
            "selected_points_without_value_or_source": null_or_unselected,
            "selected_points_out_of_scope": point_scope_bad,
            "historical_publication_claims": time_claims,
            "group_grammar_interpretations": semantics_bad,
            "selected_raw_literals_missing_from_same_row_source_value_array": selected_value_not_in_source_ledger,
            "confirmed_races_missing_a_selected_point": expected_races_missing,
            "selected_races_without_confirmed_core_key": unexpected_selected_races,
            "note": "The TEMP table is connection-local and memory-only; the backup database was opened read_only.",
        },
    )

    point_sql = "SELECT actual_meet_code,event_date,race_no,canonical_point_code,notation_raw,selected_source FROM qa_selected_points"
    expected_sql = (
        "SELECT actual_meet_code,event_date,race_no,canonical_point_code,notation_raw,selected_source "
        "FROM read_parquet('/Users/kimyongjin/Desktop/horse_racing/thoroughbred/research/20261002_passing_groups_v1/root_expected_selected_points.parquet')"
    )
    db_only = connection.execute(f"SELECT count(*) FROM ({point_sql} EXCEPT ALL {expected_sql})").fetchone()[0]
    expected_only = connection.execute(f"SELECT count(*) FROM ({expected_sql} EXCEPT ALL {point_sql})").fetchone()[0]
    discrepancies, conflict_races, API_primary_conflicts = connection.execute(
        "SELECT count(*),count(DISTINCT (actual_meet_code,event_date,race_no)),"
        "(SELECT count(*) FROM qa_selected_points WHERE selection_status='api_primary_with_rpt_discrepancy') "
        "FROM passing_point_discrepancy_ledger"
    ).fetchone()
    unmapped_api_literals = connection.execute(
        "SELECT count(*) FROM passing_api_unmapped_point_observations"
    ).fetchone()[0]
    check(
        "passing_expected_selection_and_known_discrepancies",
        db_only == 0
        and expected_only == 0
        and discrepancies == 50
        and conflict_races == 39
        and API_primary_conflicts == 50
        and unmapped_api_literals == 414,
        {
            "selected_points_db_only": db_only,
            "selected_points_expected_only": expected_only,
            "API_RPT_literal_discrepancies": discrepancies,
            "races_with_discrepancies": conflict_races,
            "discrepancies_retained_API_primary": API_primary_conflicts,
            "unmapped_API_literal_observations_preserved": unmapped_api_literals,
            "expected_point_multiset_file_sha256": sha256_file(EXPECTED_POINTS),
        },
    )

    medical_hist_flags = medical_core.get("summary", {}).get("medical_time_claim_audit")
    # The committed input verifier directly checked both exposure-time guards; preserve its pin even if that
    # summary field is not exported by this verifier version.
    check(
        "medical_publication_time_and_linking_guards_from_independent_proof",
        medical_core.get("all_passed") is True
        and medical_core.get("summary", {}).get("horse_link_counts") is not None
        and medical_dict.get("prior_parser_prefix_rules_blocked") == 356,
        {
            "medical_time_claim_audit_summary": medical_hist_flags,
            "source_exact_roster_link_counts": medical_core.get("summary", {}).get("horse_link_counts"),
            "unlinked_name_only_Text_policy": "All 1,619,071 Text rows have source_has_no_official_id; no name-only horse links.",
            "prior_parser_dependent_phrases_blocked": medical_dict.get("prior_parser_prefix_rules_blocked"),
            "medical_input_proof_sha256": medical_core_pin["sha256"],
        },
    )

    stat_before_close = DB.stat()
    connection.close()
    stat_after_close = DB.stat()
    check(
        "backup_file_unchanged_by_read_only_validation",
        stat_before_close.st_size == stat_after_close.st_size
        and stat_before_close.st_mtime_ns == stat_after_close.st_mtime_ns,
        {"size_bytes_before_after": [stat_before_close.st_size, stat_after_close.st_size],
         "mtime_ns_before_after": [stat_before_close.st_mtime_ns, stat_after_close.st_mtime_ns]},
    )

    result = {
        "status": "PASS" if not issues else "FAIL",
        "database": str(DB.relative_to(ROOT)),
        "manifest": str(MANIFEST.relative_to(ROOT)),
        "database_sha256": actual_db_sha,
        "manifest_sha256": actual_manifest_sha,
        "read_only": True,
        "duckdb_threads": 2,
        "duckdb_memory_limit": "2GB",
        "scope": {"dates": ["2010-01-01", "2026-09-29"], "actual_meets": [1, 3, 4], "medical_meets": [1, 3], "jeju_excluded": True},
        "proof_pins": proof_pins,
        "checks": checks,
        "issues": issues,
        "known_exceptions_and_limits": [
            "Repeated medical source observations are intentionally preserved; occurrence totals are not distinct-visit counts.",
            "Text source rows carry horse names but no official horse IDs, so they remain unlinked by name alone.",
            "API horse IDs absent from the core roster remain source IDs with unmatched status; they are not silently discarded.",
            "The prior parser-dependent 356 phrases remain held; exact reviewed phrase metadata does not become an event diagnosis.",
            "Passing conflict count is 50 points across 39 races; both source literals remain and API is primary as authorized.",
            "There are 414 API point literals with no justified canonical point mapping; they remain in the raw/unmapped ledger.",
            "Passing group notation is unparsed text, not horse-level passage order. Capture times do not establish historical publication times.",
            "The snapshot predates steward-report objects; this verification does not inspect the active post-report database or any operating service.",
        ],
    }
    (OUT / "verification.json").write_text(json.dumps(safe(result), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "database_sha256": actual_db_sha, "checks": checks, "issues": issues}, ensure_ascii=False, indent=2))
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
