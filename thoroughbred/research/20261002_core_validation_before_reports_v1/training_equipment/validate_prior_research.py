#!/usr/bin/env python3
"""Read-only focused QA of the pre-steward research additions in the pinned backup."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parent
DB = ROOT / "thoroughbred/data/core_api_2010_20260929_v1/backups/20261002_before_steward_reports/thoroughbred_core.duckdb"
MANIFEST = DB.with_name("manifest.json")
ATTESTATION = DB.with_name("backup_pair_attestation.json")
START_DATE = "2010-01-01"
END_DATE = "2026-09-29"
MODEL_START = "2017-01-01"
MEETS_TRAIN_EXAM = ["1", "3"]
EXPECTED_OBJECTS = {
    "equipment_api78_full_v1",
    "training_three_api18_api22_api216_v1",
    "starting_exam_api21_1_v1",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def scalar(conn: duckdb.DuckDBPyConnection, sql: str, params: tuple[Any, ...] = ()) -> Any:
    return conn.execute(sql, params).fetchone()[0]


def rows(conn: duckdb.DuckDBPyConnection, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    cursor = conn.execute(sql, params)
    names = [item[0] for item in cursor.description]
    return [dict(zip(names, item)) for item in cursor.fetchall()]


report: dict[str, Any] = {
    "schema_version": 1,
    "created_at_utc": datetime.now(timezone.utc).isoformat(),
    "scope": {
        "event_dates": [START_DATE, END_DATE],
        "model_window_start": MODEL_START,
        "training_and_starting_exam_source_meets": MEETS_TRAIN_EXAM,
        "equipment_api78_meets": ["1", "3", "4"],
        "jeju_meet_2_excluded": True,
    },
    "database": {
        "path": str(DB),
        "read_only": True,
        "memory_limit": "2GB",
        "threads": 2,
    },
    "checks": [],
    "known_limitations": [],
    "summaries": {},
}


def check(name: str, expected: Any, actual: Any, ok: bool, *, detail: str | None = None, samples: Any = None) -> None:
    item: dict[str, Any] = {
        "name": name,
        "status": "pass" if ok else "fail",
        "expected": expected,
        "actual": actual,
    }
    if detail:
        item["detail"] = detail
    if samples:
        item["samples"] = samples
    report["checks"].append(item)


manifest = json_load(MANIFEST)
attestation = json_load(ATTESTATION)
manifest_sha = sha256_file(MANIFEST)
db_sha = sha256_file(DB)
report["database"].update({
    "sha256": db_sha,
    "manifest_sha256": manifest_sha,
    "manifest_status": manifest.get("status"),
    "backup_pair_verified_equal": attestation.get("verified_equal"),
})
check("backup_database_hash_matches_manifest", manifest.get("database_sha256"), db_sha,
      manifest.get("database_sha256") == db_sha)
check("backup_database_hash_matches_pair_attestation", attestation.get("backup_db_sha256"), db_sha,
      attestation.get("backup_db_sha256") == db_sha)
check("backup_manifest_hash_matches_pair_attestation", attestation.get("baseline_manifest_sha256"), manifest_sha,
      attestation.get("baseline_manifest_sha256") == manifest_sha)
check("backup_pair_attested_equal", True, attestation.get("verified_equal"),
      attestation.get("verified_equal") is True)

conn = duckdb.connect(str(DB), read_only=True, config={"memory_limit": "2GB", "threads": "2"})
try:
    # The source catalog must contain the research batches under review.
    source_names = [r[0] for r in conn.execute("SELECT name FROM source_manifests ORDER BY name").fetchall()]
    present = sorted(EXPECTED_OBJECTS.intersection(source_names))
    check("research_source_manifest_rows_present", sorted(EXPECTED_OBJECTS), present,
          set(present) == EXPECTED_OBJECTS)

    object_catalog = rows(conn, """
        SELECT table_name, table_type
        FROM information_schema.tables
        WHERE table_schema='main'
        ORDER BY table_name
    """)
    actual_object_map = {r["table_name"]: r["table_type"] for r in object_catalog}
    object_counts = rows(conn, """
        SELECT table_type, count(*) AS object_count
        FROM information_schema.tables WHERE table_schema='main'
        GROUP BY table_type ORDER BY table_type
    """)
    report["summaries"]["database_object_counts"] = object_counts
    declared_objects = manifest.get("table_and_view_counts")
    if isinstance(declared_objects, dict):
        declared_names = set(declared_objects)
        actual_names = set(actual_object_map)
        expected_unregistered_views = {
            "confirmed_runners_entity_reviewed_before_role_review",
            "trial_participants_entity_reviewed_before_role_review",
        }
        unregistered_names = actual_names - declared_names
        check("manifest_object_inventory_matches_backup",
              {"declared_object_count": len(declared_names),
               "allowed_unregistered_intermediate_views": sorted(expected_unregistered_views)},
              {"object_count": len(actual_names), "missing": sorted(declared_names - actual_names),
               "unexpected": sorted(unregistered_names)},
              declared_names.issubset(actual_names)
              and unregistered_names == expected_unregistered_views
              and all(actual_object_map[name] == "VIEW" for name in expected_unregistered_views))

    # Exact official-ID roster identity; names and current profile relationships are never used as joins.
    duplicate_roster_ids = rows(conn, """
        SELECT entity_type, entity_id_official_string, count(*) AS row_count
        FROM entity_reference_roster
        GROUP BY entity_type, entity_id_official_string
        HAVING count(*) > 1 ORDER BY row_count DESC, entity_type, entity_id_official_string
        LIMIT 20
    """)
    check("official_entity_roster_key_unique", 0, len(duplicate_roster_ids), not duplicate_roster_ids,
          samples=duplicate_roster_ids)
    report["summaries"]["roster_relationship_rule_counts"] = rows(conn, """
        SELECT relationship_rule, count(*) AS row_count
        FROM entity_reference_roster GROUP BY relationship_rule ORDER BY relationship_rule
    """)

    # Equipment API78: full selected card population, 3 venue codes, exact key/name corroboration.
    equip_counts = rows(conn, """
        SELECT meet, count(*) AS row_count, min(race_date) AS first_date, max(race_date) AS last_date
        FROM equipment_api78_capture_batches GROUP BY meet ORDER BY meet
    """)
    equip_rows_by_meet = {r["meet"]: r["row_count"] for r in equip_counts}
    report["summaries"]["equipment_batches_by_meet"] = equip_counts
    check("equipment_batches_scope_and_count", {"1": 1562, "3": 1553, "4": 2}, equip_rows_by_meet,
          equip_rows_by_meet == {"1": 1562, "3": 1553, "4": 2})
    check("equipment_batch_date_bounds", ["20100108", "20260920"],
          [scalar(conn, "SELECT min(race_date) FROM equipment_api78_capture_batches"),
           scalar(conn, "SELECT max(race_date) FROM equipment_api78_capture_batches")],
          scalar(conn, "SELECT count(*) FROM equipment_api78_capture_batches WHERE race_date < '20100101' OR race_date > '20260929'") == 0,
          detail="Capture dates can postdate the requested last event date when no later in-scope card exists; event rows are separately bounded.")
    batch_scope_bad = scalar(conn, """
        SELECT count(*) FROM equipment_api78_capture_batches
        WHERE meet NOT IN ('1','3','4') OR race_date < '20100101' OR race_date > '20260929'
    """)
    check("equipment_batch_meet_and_event_scope", 0, batch_scope_bad, batch_scope_bad == 0)
    batch_incomplete = scalar(conn, "SELECT count(*) FROM equipment_api78_capture_batches WHERE NOT is_complete")
    check("equipment_selected_batches_complete", 0, batch_incomplete, batch_incomplete == 0)
    equipment_row_count = scalar(conn, "SELECT count(*) FROM equipment_api78_card_observations")
    check("equipment_observation_count", 331450, equipment_row_count, equipment_row_count == 331450)
    equipment_scope_bad = scalar(conn, """
        SELECT count(*) FROM equipment_api78_card_observations
        WHERE meet NOT IN ('1','3','4') OR event_date < '20100101' OR event_date > '20260929'
    """)
    check("equipment_observation_scope", 0, equipment_scope_bad, equipment_scope_bad == 0)
    equip_ids = conn.execute("SELECT count(*), count(DISTINCT observation_id) FROM equipment_api78_card_observations").fetchone()
    check("equipment_observation_primary_key_unique", equip_ids[0], equip_ids[1], equip_ids[0] == equip_ids[1])
    equip_locator_dupes = rows(conn, """
        SELECT source_document_ref, page_no, source_index_in_batch, count(*) AS row_count
        FROM equipment_api78_card_observations
        GROUP BY source_document_ref, page_no, source_index_in_batch
        HAVING count(*) > 1 ORDER BY row_count DESC LIMIT 10
    """)
    check("equipment_source_locator_unique", 0, len(equip_locator_dupes), not equip_locator_dupes,
          samples=equip_locator_dupes)
    equip_orphan_pages = scalar(conn, """
        SELECT count(*) FROM equipment_api78_card_observations o
        LEFT JOIN equipment_api78_capture_pages p
          ON p.source_document_ref=o.source_document_ref
         AND p.raw_sha256=o.source_sha256 AND p.page_no=o.page_no
        WHERE p.source_document_ref IS NULL
    """)
    check("equipment_observations_trace_to_page_manifest", 0, equip_orphan_pages, equip_orphan_pages == 0)
    equip_states = rows(conn, """
        SELECT equipment_value_state, equipment_field_state, count(*) AS row_count
        FROM equipment_api78_card_observations
        GROUP BY equipment_value_state, equipment_field_state ORDER BY 1,2
    """)
    report["summaries"]["equipment_field_states"] = equip_states
    equip_state_bad = scalar(conn, """
        SELECT count(*) FROM equipment_api78_card_observations
        WHERE (equipment_value_state='blank' AND (equipment_raw IS NULL OR trim(equipment_raw)<>'' OR NOT equipment_field_present OR equipment_is_null))
           OR (equipment_value_state='nonblank' AND (equipment_raw IS NULL OR trim(equipment_raw)='' OR NOT equipment_field_present OR equipment_is_null))
           OR equipment_value_state NOT IN ('blank','nonblank')
           OR (equipment_is_null AND NOT equipment_field_present)
    """)
    check("equipment_raw_field_state_consistent", 0, equip_state_bad, equip_state_bad == 0)
    equipment_time_wear = rows(conn, """
        SELECT availability_status, physical_wear_status, observed_time_basis, count(*) AS row_count
        FROM equipment_api78_card_observations
        GROUP BY ALL ORDER BY availability_status, physical_wear_status, observed_time_basis
    """)
    report["summaries"]["equipment_time_and_wear_status"] = equipment_time_wear
    equip_unknown_bad = scalar(conn, """
        SELECT count(*) FROM equipment_api78_card_observations
        WHERE availability_status <> 'retrospective_api78_observation_not_verified_pre_race'
           OR physical_wear_status <> 'unknown'
    """)
    check("equipment_is_retrospective_and_wear_unknown", 0, equip_unknown_bad, equip_unknown_bad == 0)
    token_mark_counts = rows(conn, "SELECT mark_status, count(*) AS row_count FROM equipment_api78_card_tokens GROUP BY mark_status ORDER BY mark_status")
    report["summaries"]["equipment_token_marks"] = token_mark_counts
    token_bad = scalar(conn, """
        SELECT count(*) FROM equipment_api78_card_tokens
        WHERE (mark_status='new' AND (right(token_raw,1)<>'+' OR equipment_name_raw<>trim(left(token_raw,length(token_raw)-1))))
           OR (mark_status='removed' AND (right(token_raw,1)<>'-' OR equipment_name_raw<>trim(left(token_raw,length(token_raw)-1))))
           OR (mark_status='unmarked' AND right(token_raw,1) IN ('+','-'))
           OR mark_status NOT IN ('new','removed','unmarked')
    """)
    check("equipment_plus_minus_marks_preserve_raw_semantics", 0, token_bad, token_bad == 0,
          detail="A trailing + means new; a trailing - means removed; all other tokens are unmarked.")
    token_reconstruction = conn.execute("""
        WITH expected AS (
          SELECT o.observation_id, x.pos::INTEGER AS token_position, x.raw_token,
                 trim(CASE WHEN right(x.raw_token,1) IN ('+','-')
                           THEN left(x.raw_token,length(x.raw_token)-1) ELSE x.raw_token END) AS expected_name,
                 CASE right(x.raw_token,1) WHEN '+' THEN 'new' WHEN '-' THEN 'removed' ELSE 'unmarked' END AS expected_mark
          FROM equipment_api78_card_observations o,
               UNNEST(string_split(o.equipment_raw, ',')) WITH ORDINALITY AS x(raw_token,pos)
          WHERE o.equipment_raw IS NOT NULL AND trim(o.equipment_raw)<>'' AND trim(x.raw_token)<>''
        )
        SELECT count(*) AS expected_token_rows,
               count(*) FILTER (WHERE t.observation_id IS NULL) AS missing_token_rows,
               count(*) FILTER (WHERE e.raw_token IS DISTINCT FROM t.token_raw) AS raw_token_mismatches,
               count(*) FILTER (WHERE e.expected_name IS DISTINCT FROM t.equipment_name_raw) AS name_mismatches,
               count(*) FILTER (WHERE e.expected_mark IS DISTINCT FROM t.mark_status) AS mark_mismatches
        FROM expected e FULL OUTER JOIN equipment_api78_card_tokens t
          ON t.observation_id=e.observation_id AND t.token_position=e.token_position
    """).fetchone()
    token_reconstruction_actual = {
        "expected_token_rows": token_reconstruction[0],
        "missing_token_rows": token_reconstruction[1],
        "raw_token_mismatches": token_reconstruction[2],
        "name_mismatches": token_reconstruction[3],
        "mark_mismatches": token_reconstruction[4],
    }
    report["summaries"]["equipment_token_reconstruction"] = token_reconstruction_actual
    check("equipment_tokens_reconstruct_exactly_from_raw_field", 326385,
          token_reconstruction_actual,
          token_reconstruction_actual == {
              "expected_token_rows": 326385, "missing_token_rows": 0,
              "raw_token_mismatches": 0, "name_mismatches": 0, "mark_mismatches": 0,
          })
    active_removed = scalar(conn, "SELECT count(*) FROM equipment_api78_active_declared WHERE mark_status='removed'")
    check("equipment_removed_tokens_excluded_from_active_declared_view", 0, active_removed, active_removed == 0)
    active_count = scalar(conn, "SELECT count(*) FROM equipment_api78_active_declared")
    expected_active = scalar(conn, "SELECT count(*) FROM equipment_api78_card_tokens WHERE mark_status<>'removed'")
    check("equipment_active_declared_view_retains_all_nonremoved_tokens", expected_active, active_count,
          expected_active == active_count)
    core_ledger_summary = conn.execute("""
        SELECT count(*), count(DISTINCT (core_meet,core_event_date,core_race_no,core_horse_no,core_horse_id))
        FROM equipment_api78_core_runner_ledger
    """).fetchone()
    check("equipment_core_runner_ledger_five_key_unique", [330465,330465], list(core_ledger_summary),
          core_ledger_summary == (330465,330465))
    coverage_rows = scalar(conn, "SELECT count(*) FROM equipment_core_coverage")
    coverage_distinct = scalar(conn, """
        SELECT count(DISTINCT (meet,result_date,race_no,horse_no,horse_id)) FROM equipment_core_coverage
    """)
    check("equipment_core_coverage_has_each_confirmed_runner_once", [330465,330465], [coverage_rows,coverage_distinct],
          [coverage_rows,coverage_distinct] == [330465,330465])
    coverage_source_counts = rows(conn, "SELECT selected_source, coverage_status, source_coverage_state, count(*) AS row_count FROM equipment_core_coverage GROUP BY ALL ORDER BY 1,2,3")
    report["summaries"]["equipment_core_coverage"] = coverage_source_counts
    core_key_gaps = scalar(conn, """
        SELECT
          (SELECT count(*) FROM confirmed_runners c
           LEFT JOIN equipment_api78_core_runner_ledger l
             ON l.core_meet=c.source_meet AND l.core_event_date=c.result_date
            AND l.core_race_no=c.result_race_no AND l.core_horse_no=c.horse_program_no_raw
            AND l.core_horse_id=c.horse_id_raw
           WHERE l.core_horse_id IS NULL)
        +
          (SELECT count(*) FROM equipment_api78_core_runner_ledger l
           LEFT JOIN confirmed_runners c
             ON c.source_meet=l.core_meet AND c.result_date=l.core_event_date
            AND c.result_race_no=l.core_race_no AND c.horse_program_no_raw=l.core_horse_no
            AND c.horse_id_raw=l.core_horse_id
           WHERE c.horse_id_raw IS NULL)
    """)
    check("equipment_runner_ledger_exact_confirmed_runner_keyset", 0, core_key_gaps, core_key_gaps == 0)
    api78_link_candidates_bad = scalar(conn, """
        SELECT count(*) FROM equipment_api78_card_observations
        WHERE linked_core_horse_id IS NOT NULL
          AND (core_key_candidate_count<>1 OR core_key_name_match_count<>1)
    """)
    check("equipment_link_requires_one_core_key_and_name_match", 0, api78_link_candidates_bad,
          api78_link_candidates_bad == 0)
    fallback_priority_bad = scalar(conn, """
        SELECT count(*) FROM equipment_core_coverage
        WHERE (api78_observation_id IS NOT NULL AND selected_source IS DISTINCT FROM 'API78')
           OR (selected_source='API78' AND api78_observation_id IS NULL)
           OR (selected_source='KRA_official_score_html' AND api78_observation_id IS NOT NULL)
    """)
    check("equipment_api78_priority_and_score_fallback_separation", 0, fallback_priority_bad,
          fallback_priority_bad == 0)
    declared_union_count = scalar(conn, "SELECT count(*) FROM equipment_declared_union_fallback")
    removed_in_union = scalar(conn, "SELECT count(*) FROM equipment_declared_union_fallback WHERE mark_status='removed'")
    check("equipment_declared_union_fallback_preserves_api_priority_and_excludes_removed",
          {"rows":311790,"removed_rows":0}, {"rows":declared_union_count,"removed_rows":removed_in_union},
          declared_union_count == 311790 and removed_in_union == 0)
    link_counts = rows(conn, "SELECT link_status,count(*) AS row_count FROM equipment_api78_card_observations GROUP BY link_status ORDER BY link_status")
    report["summaries"]["equipment_link_status"] = link_counts
    equipment_linked_bad = scalar(conn, """
        SELECT count(*) FROM equipment_api78_card_observations o
        LEFT JOIN equipment_api78_core_runner_ledger l
          ON l.core_meet=o.linked_core_meet AND l.core_event_date=o.linked_core_event_date
         AND l.core_race_no=o.linked_core_race_no AND l.core_horse_no=o.linked_core_horse_no
         AND l.core_horse_id=o.linked_core_horse_id
        LEFT JOIN confirmed_runners c
          ON c.source_meet=o.linked_core_meet AND c.result_date=o.linked_core_event_date
         AND c.result_race_no=o.linked_core_race_no AND c.horse_program_no_raw=o.linked_core_horse_no
         AND c.horse_id_raw=o.linked_core_horse_id
        LEFT JOIN entity_reference_roster r
          ON r.entity_type='horse' AND r.entity_id_official_string=o.linked_core_horse_id
        WHERE o.linked_core_horse_id IS NOT NULL
          AND (l.core_horse_id IS NULL OR c.horse_id_raw IS NULL OR r.entity_id_official_string IS NULL
               OR o.api_horse_name_normalized<>l.core_horse_name_normalized)
    """)
    check("equipment_links_resolve_by_exact_runner_key_and_normalized_name", 0, equipment_linked_bad,
          equipment_linked_bad == 0)
    equipment_link_distinct = scalar(conn, """
        SELECT count(DISTINCT (linked_core_meet,linked_core_event_date,linked_core_race_no,linked_core_horse_no,linked_core_horse_id))
        FROM equipment_api78_card_observations WHERE linked_core_horse_id IS NOT NULL
    """)
    linked_count = scalar(conn, "SELECT count(*) FROM equipment_api78_card_observations WHERE linked_core_horse_id IS NOT NULL")
    check("equipment_linked_observations_map_one_to_one_to_core_runner", [330106,330106], [linked_count,equipment_link_distinct],
          [linked_count,equipment_link_distinct] == [330106,330106])

    # Three training APIs: exact-ID-only roster links, row-level locator uniqueness, complete date x meet inventory.
    expected_training = {"daily_training": 5173033, "start_training": 431517, "swim_training": 459604}
    training_summary = rows(conn, """
        SELECT dataset, count(*) AS row_count, min(event_date) AS first_event_date, max(event_date) AS last_event_date,
               count(*) FILTER (WHERE event_date < DATE '2017-01-01') AS pre_2017_rows,
               count(*) FILTER (WHERE event_date >= DATE '2017-01-01') AS model_window_rows,
               count(*) FILTER (WHERE source_captured_at IS NULL) AS capture_time_null_rows,
               count(*) FILTER (WHERE historical_prerace_eligibility_verified) AS prerace_verified_rows
        FROM training_raw_observations GROUP BY dataset ORDER BY dataset
    """)
    report["summaries"]["training_dataset_counts"] = training_summary
    got_training = {r["dataset"]: r["row_count"] for r in training_summary}
    check("training_observation_counts", expected_training, got_training, got_training == expected_training)
    training_scope_bad = scalar(conn, """
        SELECT count(*) FROM training_raw_observations
        WHERE dataset NOT IN ('daily_training','start_training','swim_training')
           OR meet NOT IN ('1','3') OR event_date < DATE '2010-01-01' OR event_date > DATE '2026-09-29'
    """)
    check("training_meet_and_date_scope", 0, training_scope_bad, training_scope_bad == 0)
    training_id_counts = conn.execute("SELECT count(*),count(DISTINCT observation_id) FROM training_raw_observations").fetchone()
    check("training_observation_id_primary_key_unique", training_id_counts[0],training_id_counts[1],training_id_counts[0]==training_id_counts[1])
    training_locator_dupes = rows(conn, """
        SELECT dataset, raw_path, source_page_no, source_row_no, count(*) AS row_count
        FROM training_raw_observations GROUP BY dataset,raw_path,source_page_no,source_row_no
        HAVING count(*)>1 ORDER BY row_count DESC,dataset LIMIT 10
    """)
    check("training_same_source_locator_unique", 0, len(training_locator_dupes), not training_locator_dupes,
          samples=training_locator_dupes)
    training_locator_nulls = scalar(conn, """
        SELECT count(*) FROM training_raw_observations
        WHERE raw_path IS NULL OR raw_sha256 IS NULL OR source_page_no IS NULL OR source_row_no IS NULL
           OR capture_id IS NULL OR raw_payload_json IS NULL OR typed_fields_json IS NULL
    """)
    check("training_source_locator_and_raw_fields_present", 0, training_locator_nulls, training_locator_nulls == 0)
    training_orphan_sources = scalar(conn, """
        SELECT count(*) FROM training_raw_observations o
        LEFT JOIN training_source_files s
          ON s.dataset=o.dataset AND s.raw_path=o.raw_path AND s.raw_sha256=o.raw_sha256
         AND s.source_page_no=o.source_page_no AND s.capture_id=o.capture_id AND s.is_selected
        WHERE s.raw_path IS NULL
    """)
    check("training_observations_trace_to_selected_source_files", 0, training_orphan_sources,
          training_orphan_sources == 0)
    training_coverage = rows(conn, """
        SELECT dataset, count(*) AS coverage_rows,
               count(*) FILTER (WHERE coverage_status='complete_rows') AS complete_rows_cells,
               count(*) FILTER (WHERE coverage_status='complete_zero_rows') AS complete_zero_cells,
               count(*) FILTER (WHERE coverage_status IN ('missing_capture','incomplete_capture')) AS missing_or_incomplete_cells
        FROM training_date_coverage GROUP BY dataset ORDER BY dataset
    """)
    report["summaries"]["training_date_coverage"] = training_coverage
    expected_cov = {
        "daily_training": (12232,10211,2021,0),
        "start_training": (12232,5688,6544,0),
        "swim_training": (12232,5691,6541,0),
    }
    actual_cov = {r["dataset"]:(r["coverage_rows"],r["complete_rows_cells"],r["complete_zero_cells"],r["missing_or_incomplete_cells"]) for r in training_coverage}
    check("training_full_date_meet_coverage_matches_contract", expected_cov, actual_cov, actual_cov == expected_cov)
    training_coverage_mismatches = scalar(conn, "SELECT count(*) FROM training_date_coverage WHERE inventory_count_mismatch")
    check("training_coverage_rows_match_observation_counts", 0, training_coverage_mismatches,
          training_coverage_mismatches == 0)
    training_cov_scope_bad = scalar(conn, """
        SELECT count(*) FROM training_capture_coverage
        WHERE dataset NOT IN ('daily_training','start_training','swim_training') OR meet NOT IN ('1','3')
           OR event_date < DATE '2010-01-01' OR event_date > DATE '2026-09-29'
    """)
    check("training_coverage_scope", 0, training_cov_scope_bad, training_cov_scope_bad == 0)
    training_link_counts = rows(conn, "SELECT dataset,link_status,count(*) AS row_count FROM training_raw_observations GROUP BY dataset,link_status ORDER BY dataset,link_status")
    report["summaries"]["training_link_status"] = training_link_counts
    report["summaries"]["unmatched_id_examples"] = {
        "training": rows(conn, """
            SELECT dataset,official_horse_id,raw_name,event_date,raw_path,source_page_no,source_row_no
            FROM training_raw_observations WHERE link_status='unmatched_official_id'
            ORDER BY dataset,event_date,official_horse_id LIMIT 10
        """),
        "starting_exam_horse": rows(conn, """
            SELECT link_status,official_horse_id,raw_name,event_date,raw_path,source_page_no,source_row_no
            FROM starting_exam_observations WHERE link_status IN ('unmatched_official_id','missing_official_id')
            ORDER BY link_status,event_date,official_horse_id LIMIT 10
        """),
        "starting_exam_person_roles": rows(conn, """
            SELECT l.entity_role,l.link_status,l.source_official_id,l.source_name,o.event_date,o.raw_path,
                   o.source_page_no,o.source_row_no
            FROM starting_exam_entity_links l JOIN starting_exam_observations o USING (observation_id)
            WHERE l.entity_role IN ('trainer','owner')
              AND l.link_status IN ('unmatched_official_id','missing_official_id','placeholder_source_value')
            ORDER BY l.entity_role,l.link_status,o.event_date LIMIT 10
        """),
    }
    training_link_bad = scalar(conn, """
        SELECT count(*) FROM training_raw_observations o
        LEFT JOIN entity_reference_roster r
          ON r.entity_type='horse' AND r.entity_id_official_string=o.official_horse_id
        WHERE (o.link_status='exact_core_roster_match'
               AND (r.entity_id_official_string IS NULL OR o.linked_core_horse_id IS DISTINCT FROM o.official_horse_id))
           OR (o.link_status='unmatched_official_id'
               AND (o.linked_core_horse_id IS NOT NULL OR r.entity_id_official_string IS NOT NULL))
           OR (o.link_status='missing_official_id' AND (o.official_horse_id IS NOT NULL OR o.linked_core_horse_id IS NOT NULL))
           OR o.link_status NOT IN ('exact_core_roster_match','unmatched_official_id','missing_official_id')
    """)
    check("training_horse_links_are_exact_official_id_only", 0, training_link_bad, training_link_bad == 0)
    training_labels_bad = scalar(conn, """
        SELECT count(*) FROM training_raw_observations
        WHERE availability_status<>'retrospective_training_observation_not_verified_pre_race'
           OR historical_prerace_eligibility_verified
           OR physical_venue_status<>'raw_venue_not_adjudicated'
    """)
    check("training_retro_availability_and_unadjudicated_venue_flags", 0, training_labels_bad, training_labels_bad == 0)
    training_view_counts = {
        "daily_training_raw": scalar(conn,"SELECT count(*) FROM daily_training_raw"),
        "start_training_raw": scalar(conn,"SELECT count(*) FROM start_training_raw"),
        "swim_training_raw": scalar(conn,"SELECT count(*) FROM swim_training_raw"),
        "training_observation_qa": scalar(conn,"SELECT count(*) FROM training_observation_qa"),
        "training_date_coverage": scalar(conn,"SELECT count(*) FROM training_date_coverage"),
    }
    report["summaries"]["training_view_counts"] = training_view_counts
    expected_training_view_counts = {
        "daily_training_raw":5173033,"start_training_raw":431517,"swim_training_raw":459604,
        "training_observation_qa":6064154,"training_date_coverage":36696,
    }
    check("training_views_preserve_base_rows",expected_training_view_counts,training_view_counts,
          training_view_counts==expected_training_view_counts)
    training_json_invalid = rows(conn,"""
        SELECT dataset,count(*) FILTER (WHERE NOT json_valid(raw_payload_json) OR NOT json_valid(typed_fields_json)) AS invalid_json_rows
        FROM training_raw_observations GROUP BY dataset ORDER BY dataset
    """)
    report["summaries"]["training_source_json_validity"] = training_json_invalid
    check("training_source_payload_json_valid",0,sum(r["invalid_json_rows"] for r in training_json_invalid),
          sum(r["invalid_json_rows"] for r in training_json_invalid)==0)

    # Daily training's documented natural key collisions and raw duration anomalies are flagged, not corrected.
    daily_natural = rows(conn, """
        WITH keyed AS (
          SELECT official_horse_id, meet, event_date,
                 coalesce(json_extract_string(typed_fields_json,'$.stTime'),'') AS st_time,
                 coalesce(json_extract_string(typed_fields_json,'$.spTime'),'') AS sp_time,
                 count(*) AS n, count(DISTINCT raw_payload_json) AS payload_versions
          FROM training_raw_observations WHERE dataset='daily_training'
          GROUP BY official_horse_id,meet,event_date,st_time,sp_time HAVING count(*)>1
        )
        SELECT count(*) AS repeated_groups, coalesce(sum(n),0) AS affected_rows,
               coalesce(sum(n-1),0) AS excess_rows,
               count(*) FILTER (WHERE payload_versions>1) AS nonidentical_groups,
               coalesce(sum(n) FILTER (WHERE payload_versions>1),0) AS nonidentical_rows
        FROM keyed
    """)
    report["summaries"]["daily_training_natural_key_repeats"] = daily_natural[0]
    expected_daily_natural = {"repeated_groups":8,"affected_rows":16,"excess_rows":8,"nonidentical_groups":8,"nonidentical_rows":16}
    check("daily_training_known_nonidentical_natural_key_variants", expected_daily_natural,daily_natural[0],daily_natural[0]==expected_daily_natural)
    daily_flag_counts = rows(conn, """
        SELECT flag, count(*) AS row_count FROM (
          SELECT unnest(list_filter(['duration_negative','duration_zero','end_before_start','duration_differs_from_raw_time_delta','nonidentical_natural_key_variant'],
             f -> contains(qa_flags_json, f))) AS flag
          FROM training_raw_observations WHERE dataset='daily_training'
        ) GROUP BY flag ORDER BY flag
    """)
    report["summaries"]["daily_training_qa_flag_counts"] = daily_flag_counts
    daily_flag_map = {r["flag"]:r["row_count"] for r in daily_flag_counts}
    expected_daily_flags = {"duration_negative":8,"duration_zero":11,"end_before_start":9,"duration_differs_from_raw_time_delta":337,"nonidentical_natural_key_variant":16}
    check("daily_training_existing_raw_value_qa_flags", expected_daily_flags,daily_flag_map,daily_flag_map==expected_daily_flags)

    # Whole-payload repeats are an observation QA fact, never an implied workout count.
    exact_payload_repeats = rows(conn, """
        WITH groups AS (
          SELECT dataset,event_date,meet,official_horse_id,raw_payload_json,count(*) AS n
          FROM training_raw_observations
          GROUP BY dataset,event_date,meet,official_horse_id,raw_payload_json HAVING count(*)>1
        )
        SELECT dataset,count(*) AS duplicate_groups,coalesce(sum(n),0) AS affected_rows,
               coalesce(sum(n-1),0) AS duplicate_excess_rows
        FROM groups GROUP BY dataset ORDER BY dataset
    """)
    report["summaries"]["training_exact_payload_repeats"] = exact_payload_repeats
    repeat_map = {r["dataset"]:(r["duplicate_groups"],r["affected_rows"],r["duplicate_excess_rows"]) for r in exact_payload_repeats}
    expected_repeat_map = {"swim_training":(8,24,16)}
    check("training_exact_payload_repeats_match_existing_qa", expected_repeat_map,repeat_map,repeat_map==expected_repeat_map,
          detail="Repeated source payload rows are preserved as QA observations and are not interpreted as real training-session counts.")
    start_ordinal_bad = scalar(conn, """
        SELECT count(*) FROM start_training_raw
        WHERE occurrence_no_is_event_id OR occurrence_no_is_chronological
    """)
    check("api22_occurrence_order_not_promoted_to_event_or_chronology",0,start_ordinal_bad,start_ordinal_bad==0)
    swim_cnt_summary = conn.execute("""
        SELECT count(*) FILTER (WHERE try_cast(cnt_raw AS DOUBLE)=0) AS zero_rows,
               count(*) FILTER (WHERE try_cast(cnt_raw AS DOUBLE)>=20) AS twenty_plus_rows,
               count(*) FILTER (WHERE cnt_unit_status<>'count_unit_unresolved') AS resolved_unit_rows
        FROM swim_training_raw
    """).fetchone()
    actual_swim_cnt = {"zero_rows":swim_cnt_summary[0],"twenty_plus_rows":swim_cnt_summary[1],"resolved_unit_rows":swim_cnt_summary[2]}
    check("swim_raw_counts_preserved_and_unit_unresolved",{"zero_rows":3,"twenty_plus_rows":33,"resolved_unit_rows":0},actual_swim_cnt,
          actual_swim_cnt=={"zero_rows":3,"twenty_plus_rows":33,"resolved_unit_rows":0})

    # Starting exam: source natural key duplicates are exact observations; keep status and role exceptions distinct.
    exam_summary = rows(conn, """
        SELECT meet,count(*) AS row_count,min(event_date) AS first_event_date,max(event_date) AS last_event_date,
               count(*) FILTER (WHERE event_date < DATE '2017-01-01') AS pre_2017_rows,
               count(*) FILTER (WHERE event_date >= DATE '2017-01-01') AS model_window_rows,
               count(*) FILTER (WHERE source_captured_at IS NULL) AS capture_time_null_rows,
               count(*) FILTER (WHERE historical_prerace_eligibility_verified) AS prerace_verified_rows
        FROM starting_exam_observations GROUP BY meet ORDER BY meet
    """)
    report["summaries"]["starting_exam_by_meet"] = exam_summary
    exam_total = scalar(conn, "SELECT count(*) FROM starting_exam_observations")
    check("starting_exam_observation_count",52325,exam_total,exam_total==52325)
    exam_scope_bad = scalar(conn,"""
        SELECT count(*) FROM starting_exam_observations
        WHERE dataset<>'starting_exam' OR meet NOT IN ('1','3')
           OR event_date<DATE '2010-01-01' OR event_date>DATE '2026-09-29'
    """)
    check("starting_exam_meet_and_date_scope",0,exam_scope_bad,exam_scope_bad==0)
    exam_ids = conn.execute("SELECT count(*),count(DISTINCT observation_id) FROM starting_exam_observations").fetchone()
    check("starting_exam_observation_primary_key_unique",exam_ids[0],exam_ids[1],exam_ids[0]==exam_ids[1])
    exam_locator_dupes = rows(conn,"""
        SELECT raw_path,source_page_no,source_row_no,count(*) AS row_count
        FROM starting_exam_observations GROUP BY raw_path,source_page_no,source_row_no
        HAVING count(*)>1 ORDER BY row_count DESC LIMIT 10
    """)
    check("starting_exam_source_locator_unique",0,len(exam_locator_dupes),not exam_locator_dupes,samples=exam_locator_dupes)
    exam_orphan_sources = scalar(conn,"""
        SELECT count(*) FROM starting_exam_observations o
        LEFT JOIN starting_exam_source_files s
          ON s.dataset=o.dataset AND s.meet=o.meet AND s.capture_id=o.capture_id
         AND s.source_page_no=o.source_page_no AND s.raw_path=o.raw_path AND s.raw_sha256=o.raw_sha256 AND s.is_selected
        WHERE s.capture_id IS NULL
    """)
    check("starting_exam_observations_trace_to_selected_source_files",0,exam_orphan_sources,exam_orphan_sources==0)
    exam_coverage = rows(conn,"""
        SELECT count(*) AS day_meet_cells,
               count(*) FILTER (WHERE coverage_status='complete_rows') AS complete_rows_cells,
               count(*) FILTER (WHERE coverage_status='complete_zero_rows') AS complete_zero_cells,
               count(*) FILTER (WHERE coverage_status='incomplete_capture') AS incomplete_cells,
               count(*) FILTER (WHERE event_date<DATE '2010-01-01' OR event_date>DATE '2026-09-29' OR meet NOT IN ('1','3')) AS out_of_scope_cells
        FROM starting_exam_date_coverage
    """)
    report["summaries"]["starting_exam_date_coverage"] = exam_coverage[0]
    check("starting_exam_daily_coverage",12232,exam_coverage[0]["day_meet_cells"],exam_coverage[0]["day_meet_cells"]==12232 and exam_coverage[0]["incomplete_cells"]==0 and exam_coverage[0]["out_of_scope_cells"]==0)
    partition_summary = rows(conn,"SELECT coverage_status,count(*) AS row_count FROM starting_exam_partition_coverage GROUP BY coverage_status ORDER BY coverage_status")
    report["summaries"]["starting_exam_partitions"] = partition_summary
    partition_bad = scalar(conn,"""
        SELECT count(*) FROM starting_exam_partition_coverage
        WHERE dataset<>'starting_exam' OR meet NOT IN ('1','3') OR capture_year<2010 OR capture_year>2026
           OR coverage_status<>'complete' OR observed_rows<0
    """)
    check("starting_exam_all_34_year_meet_partitions_complete",34,scalar(conn,"SELECT count(*) FROM starting_exam_partition_coverage"),
          scalar(conn,"SELECT count(*) FROM starting_exam_partition_coverage")==34 and partition_bad==0)
    exam_key_stats = rows(conn,"""
        WITH raw_keys AS (
          SELECT json_extract_string(typed_fields_json,'$.meet') AS source_meet,
                 json_extract_string(typed_fields_json,'$.trainDate') AS train_date,
                 json_extract_string(typed_fields_json,'$.daySerial') AS day_serial,
                 json_extract_string(typed_fields_json,'$.trainNo') AS train_no,
                 json_extract_string(typed_fields_json,'$.chulNo') AS horse_program_no,
                 json_extract_string(typed_fields_json,'$.hrNo') AS horse_id,
                 raw_payload_json
          FROM starting_exam_observations
        ), valid AS (
          SELECT *, count(*) OVER (PARTITION BY source_meet,train_date,day_serial,train_no,horse_program_no,horse_id) AS n,
                    count(DISTINCT raw_payload_json) OVER (PARTITION BY source_meet,train_date,day_serial,train_no,horse_program_no,horse_id) AS payload_versions
          FROM raw_keys
          WHERE coalesce(source_meet,'')<>'' AND coalesce(train_date,'')<>'' AND coalesce(day_serial,'')<>''
            AND coalesce(train_no,'')<>'' AND coalesce(horse_program_no,'')<>'' AND coalesce(horse_id,'')<>''
        ), repeated AS (
          SELECT DISTINCT source_meet,train_date,day_serial,train_no,horse_program_no,horse_id,n,payload_versions
          FROM valid WHERE n>1
        )
        SELECT count(*) AS repeated_key_groups, coalesce(sum(n),0) AS repeated_key_rows,
               coalesce(sum(n-1),0) AS repeated_excess_rows,
               count(*) FILTER (WHERE payload_versions=1) AS exact_repeat_groups,
               count(*) FILTER (WHERE payload_versions>1) AS nonidentical_groups
        FROM repeated
    """)
    report["summaries"]["starting_exam_natural_key_repeats"] = exam_key_stats[0]
    expected_exam_key_stats = {"repeated_key_groups":8,"repeated_key_rows":16,"repeated_excess_rows":8,"exact_repeat_groups":8,"nonidentical_groups":0}
    check("starting_exam_exact_repeat_keys_preserved",expected_exam_key_stats,exam_key_stats[0],exam_key_stats[0]==expected_exam_key_stats)
    exam_missing_key_rows = scalar(conn,"""
        SELECT count(*) FROM starting_exam_observations
        WHERE coalesce(json_extract_string(typed_fields_json,'$.meet'),'')=''
           OR coalesce(json_extract_string(typed_fields_json,'$.trainDate'),'')=''
           OR coalesce(json_extract_string(typed_fields_json,'$.daySerial'),'')=''
           OR coalesce(json_extract_string(typed_fields_json,'$.trainNo'),'')=''
           OR coalesce(json_extract_string(typed_fields_json,'$.chulNo'),'')=''
           OR coalesce(json_extract_string(typed_fields_json,'$.hrNo'),'')=''
    """)
    check("starting_exam_missing_natural_key_components_retained",128,exam_missing_key_rows,exam_missing_key_rows==128,
          detail="Rows missing a source key component are retained and not force-linked.")
    judgment_counts = rows(conn,"""
        SELECT coalesce(json_extract_string(typed_fields_json,'$.passFlag'),'<missing>') AS raw_pass_flag,
               count(*) AS row_count
        FROM starting_exam_observations GROUP BY raw_pass_flag ORDER BY raw_pass_flag
    """)
    report["summaries"]["starting_exam_raw_judgment_counts"] = judgment_counts
    exam_link_status_counts = rows(conn,"SELECT link_status,count(*) AS row_count FROM starting_exam_observations GROUP BY link_status ORDER BY link_status")
    report["summaries"]["starting_exam_horse_link_status"] = exam_link_status_counts
    report["summaries"]["equipment_unmatched_runner_examples"] = rows(conn, """
        SELECT conflict_class,link_reason,meet,event_date,race_no,horse_no,api_horse_name_raw,
               core_key_candidate_count,core_key_name_match_count,source_document_ref
        FROM equipment_api78_identity_conflicts
        ORDER BY conflict_class,meet,event_date,race_no,horse_no LIMIT 10
    """)
    report["summaries"]["equipment_core_api78_absence_examples"] = rows(conn, """
        SELECT core_meet,core_event_date,core_race_no,core_horse_no,core_horse_id,core_horse_name_raw,
               equipment_observation_state,api78_link_reason_candidate
        FROM equipment_api78_core_runner_ledger
        WHERE equipment_observation_state='runner_absent_from_complete_api78_card'
        ORDER BY core_meet,core_event_date,core_race_no,core_horse_no LIMIT 10
    """)
    exam_link_bad = scalar(conn,"""
        SELECT count(*) FROM starting_exam_observations o
        LEFT JOIN entity_reference_roster r
          ON r.entity_type='horse' AND r.entity_id_official_string=o.official_horse_id
        WHERE (o.link_status='exact_core_roster_match'
               AND (r.entity_id_official_string IS NULL OR o.linked_core_horse_id IS DISTINCT FROM o.official_horse_id))
           OR (o.link_status='unmatched_official_id'
               AND (o.linked_core_horse_id IS NOT NULL OR r.entity_id_official_string IS NOT NULL))
           OR (o.link_status='missing_official_id' AND (o.official_horse_id IS NOT NULL OR o.linked_core_horse_id IS NOT NULL))
           OR o.link_status NOT IN ('exact_core_roster_match','unmatched_official_id','missing_official_id')
    """)
    check("starting_exam_horse_link_exact_id_and_unmatched_ledger",0,exam_link_bad,exam_link_bad==0)
    role_counts = rows(conn,"SELECT entity_role,link_status,count(*) AS row_count FROM starting_exam_entity_links GROUP BY entity_role,link_status ORDER BY entity_role,link_status")
    report["summaries"]["starting_exam_role_link_status"] = role_counts
    role_link_rows = scalar(conn,"SELECT count(*) FROM starting_exam_entity_links")
    check("starting_exam_role_link_view_cardinality",156975,role_link_rows,role_link_rows==156975)
    exam_role_link_bad = scalar(conn,"""
        SELECT count(*) FROM starting_exam_entity_links l
        LEFT JOIN entity_reference_roster r
          ON r.entity_type=l.entity_role AND r.entity_id_official_string=l.source_official_id
        WHERE (l.link_status='exact_core_roster_match'
               AND (r.entity_id_official_string IS NULL OR l.linked_core_official_id IS DISTINCT FROM l.source_official_id))
           OR (l.link_status IN ('unmatched_official_id','missing_official_id','placeholder_source_value')
               AND l.linked_core_official_id IS NOT NULL)
           OR (l.link_status='unmatched_official_id' AND r.entity_id_official_string IS NOT NULL)
           OR (l.link_status='missing_official_id' AND (l.source_official_id IS NOT NULL OR r.entity_id_official_string IS NOT NULL))
    """)
    check("starting_exam_person_role_links_use_exact_source_ids",0,exam_role_link_bad,exam_role_link_bad==0)
    rider_link_rows = scalar(conn,"SELECT count(*) FROM starting_exam_entity_links WHERE entity_role='rider'")
    check("starting_exam_rider_names_not_linked_as_jockey_ids",0,rider_link_rows,rider_link_rows==0)
    exam_labels_bad = scalar(conn,"""
        SELECT count(*) FROM starting_exam_observations
        WHERE availability_status<>'retrospective_starting_exam_not_verified_pre_race'
           OR historical_prerace_eligibility_verified
           OR physical_venue_status<>'raw_meet_preserved_physical_venue_unadjudicated'
    """)
    check("starting_exam_retro_availability_and_venue_flags",0,exam_labels_bad,exam_labels_bad==0)
    exam_view_counts = {
        "starting_exam_results":scalar(conn,"SELECT count(*) FROM starting_exam_results"),
        "starting_exam_qa":scalar(conn,"SELECT count(*) FROM starting_exam_qa"),
        "starting_exam_sessions":scalar(conn,"SELECT count(*) FROM starting_exam_sessions"),
        "starting_exam_date_coverage":scalar(conn,"SELECT count(*) FROM starting_exam_date_coverage"),
        "starting_exam_entity_links":role_link_rows,
    }
    report["summaries"]["starting_exam_view_counts"] = exam_view_counts
    expected_exam_view_counts = {
        "starting_exam_results":52325,"starting_exam_qa":52325,"starting_exam_sessions":3538,
        "starting_exam_date_coverage":12232,"starting_exam_entity_links":156975,
    }
    check("starting_exam_view_cardinalities",expected_exam_view_counts,exam_view_counts,
          exam_view_counts==expected_exam_view_counts)
    exam_json_invalid = scalar(conn,"""
        SELECT count(*) FROM starting_exam_observations
        WHERE NOT json_valid(raw_payload_json) OR NOT json_valid(typed_fields_json)
    """)
    check("starting_exam_source_payload_json_valid",0,exam_json_invalid,exam_json_invalid==0)

    # Model window counts remain separate from full retrospective archive counts.
    model_counts = {
        "training": {r["dataset"]:{"pre_2017":r["pre_2017_rows"],"2017_plus":r["model_window_rows"]} for r in training_summary},
        "starting_exam": {r["meet"]:{"pre_2017":r["pre_2017_rows"],"2017_plus":r["model_window_rows"]} for r in exam_summary},
        "equipment_api78": rows(conn,"""
            SELECT meet,count(*) FILTER (WHERE left(event_date,4)<'2017') AS pre_2017_rows,
                   count(*) FILTER (WHERE left(event_date,4)>='2017') AS model_window_rows
            FROM equipment_api78_card_observations GROUP BY meet ORDER BY meet
        """),
    }
    report["summaries"]["full_archive_vs_model_window"] = model_counts

    report["known_limitations"] = [
        {
            "id":"training_and_starting_exam_meet3_is_integrated_region",
            "status":"documented_source_limit",
            "detail":"API18_1/API22_1/API216 and API21_1 provide meet 1 and raw meet 3 only. Meet 3 remains the source's Yeongnam region label and cannot be split into Busan meet 3 and Yeongcheon meet 4; no meet 4 rows are present in these datasets.",
            "evidence": "The source contracts and READMEs define meets 1/3 and prohibit physical-venue inference; API78 separately has meets 1/3/4."
        },
        {
            "id":"all_three_sources_are_retrospective",
            "status":"documented_model_eligibility_limit",
            "detail":"The source captures do not establish historical pre-race availability. Every row retains a retrospective/unverified status. The 2017+ row counts are reported separately; passing this QA does not approve feature use."
        },
        {
            "id":"training_payload_repeats_are_not_session_counts",
            "status":"documented_aggregation_limit",
            "detail":"Identical repeated source payloads, especially the 24-row/8-group swim repeat set, remain observations and must not be interpreted as additional real workouts without a separate aggregation rule. API22 occurrence order is anonymous storage order, not an event ID or chronology."
        },
        {
            "id":"entity_reference_roster_is_exact_id_reference_only",
            "status":"documented_identity_limit",
            "detail":"Horse, trainer and owner links use exact source official IDs. Names are not join keys; current profile trainer/owner values are not backfilled into historical rows. Unmatched and missing source IDs remain separate exceptions."
        },
        {
            "id":"two_manifest_unregistered_intermediate_views",
            "status":"confirmed_intentional_intermediate_views",
            "detail":"The backup contains confirmed_runners_entity_reviewed_before_role_review and trial_participants_entity_reviewed_before_role_review outside the manifest object-count map. The coordinator confirmed these two helper views are intentional unregistered intermediates; all other declared object names match."
        },
    ]
finally:
    conn.close()

db_sha_after = sha256_file(DB)
report["database"]["sha256_after_readonly_audit"] = db_sha_after
check("database_hash_unchanged_after_readonly_audit", db_sha, db_sha_after, db_sha_after == db_sha)

report["failed_check_count"] = sum(c["status"] == "fail" for c in report["checks"])
report["passed_check_count"] = sum(c["status"] == "pass" for c in report["checks"])
report["status"] = "passed_with_documented_limitations" if report["failed_check_count"] == 0 else "failed"

out_json = OUT / "validation_report.json"
out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")

lines = [
    "# Training and equipment pre-report validation",
    "",
    f"Status: **{report['status']}** ({report['passed_check_count']} pass, {report['failed_check_count']} fail).",
    "",
    f"Database: `{DB}` (read-only; SHA-256 `{db_sha}`).",
    "",
    "Scope: event dates 2010-01-01 through 2026-09-29; model window starts 2017-01-01. API78 includes meets 1/3/4. Training and starting-exam source records include API meets 1/3.",
    "",
    "## Checks",
    "",
]
for item in report["checks"]:
    lines.append(f"- **{item['status'].upper()}** `{item['name']}` — expected `{item['expected']}`, actual `{item['actual']}`.")
    if item.get("detail"):
        lines.append(f"  {item['detail']}")
lines += ["", "## Source and scope limitations", ""]
for item in report["known_limitations"]:
    lines.append(f"- **{item['id']}** — {item['detail']}")
lines += ["", "## Output", "", "The JSON report retains counts, grouped statuses, provenance hash checks, and any failed check details.", ""]
(OUT / "validation_report.md").write_text("\n".join(lines), encoding="utf-8")
print(json.dumps({
    "status": report["status"],
    "passed_check_count": report["passed_check_count"],
    "failed_check_count": report["failed_check_count"],
    "report": str(out_json),
    "database_sha256": db_sha,
}, ensure_ascii=False))
