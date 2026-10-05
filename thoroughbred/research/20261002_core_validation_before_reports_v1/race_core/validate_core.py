"""Read-only QA for the pre-steward-report thoroughbred core snapshot.

The database path, SQL statements, and expected scope are fixed in this file.
All data values used in predicates are passed as DuckDB parameters.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import sys

import duckdb


ROOT = Path(__file__).resolve().parents[4]
BASE = ROOT / "thoroughbred/data/core_api_2010_20260929_v1/backups/20261002_before_steward_reports"
DB = BASE / "thoroughbred_core.duckdb"
SOURCE_MANIFEST = BASE / "manifest.json"
OUTPUT = Path(__file__).resolve().parent / "validation.json"
START_COMPACT = "20100101"
END_COMPACT = "20260929"
START_ISO = "2010-01-01"
END_ISO = "2026-09-29"

EXPECTED_COUNTS = {
    "calendar_days": ("SELECT count(*) FROM calendar_days", 18348),
    "race_plan": ("SELECT count(*) FROM race_plan", 29826),
    "race_plan_full_api": ("SELECT count(*) FROM race_plan_full_api", 29826),
    "race_execution_flags": ("SELECT count(*) FROM race_execution_flags", 29826),
    "race_nonexecution_adjudication": ("SELECT count(*) FROM race_nonexecution_adjudication", 116),
    "race_nonexecution_subtype_review": ("SELECT count(*) FROM race_nonexecution_subtype_review", 29),
    "race_events": ("SELECT count(*) FROM race_events", 29826),
    "runner_results": ("SELECT count(*) FROM runner_results", 331811),
    "confirmed_races": ("SELECT count(*) FROM confirmed_races", 29710),
    "confirmed_runners": ("SELECT count(*) FROM confirmed_runners", 330465),
    "confirmed_races_2017plus": ("SELECT count(*) FROM confirmed_races_2017plus", 16547),
    "confirmed_runners_2017plus": ("SELECT count(*) FROM confirmed_runners_2017plus", 182062),
    "race_execution_adjudicated": ("SELECT count(*) FROM race_execution_adjudicated", 29826),
    "trial_sessions": ("SELECT count(*) FROM trial_sessions", 6199),
    "trial_participants": ("SELECT count(*) FROM trial_participants", 61777),
    "trial_participants_resolved": ("SELECT count(*) FROM trial_participants_resolved", 61777),
    "unresolved_trial_participants": ("SELECT count(*) FROM unresolved_trial_participants", 0),
    "official_closure_intervals": ("SELECT count(*) FROM official_closure_intervals", 81),
    "role_link_exceptions_current": ("SELECT count(*) FROM role_link_exceptions_current", 186),
    "role_link_exceptions_pending": ("SELECT count(*) FROM role_link_exceptions_pending", 0),
    "entity_reference_roster": ("SELECT count(*) FROM entity_reference_roster", 25814),
    "section_measurements_api": ("SELECT count(*) FROM section_measurements_api", 4380065),
    "runner_section_coverage_api": ("SELECT count(*) FROM runner_section_coverage_api", 330465),
    "section_parse_issues_api": ("SELECT count(*) FROM section_parse_issues_api", 0),
    "section_missing_finisher_review": ("SELECT count(*) FROM section_missing_finisher_review", 2),
    "unverified_result_only_keys": ("SELECT count(*) FROM unverified_result_only_keys", 0),
    "trial_trainer_errors_closed": ("SELECT count(*) FROM trial_trainer_errors_closed", 22),
}


def sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def query_one(connection: duckdb.DuckDBPyConnection, sql: str, params: tuple = ()):
    return connection.execute(sql, list(params)).fetchone()[0]


def query_rows(connection: duckdb.DuckDBPyConnection, sql: str, params: tuple = ()):
    return connection.execute(sql, list(params)).fetchall()


def add_check(checks: list[dict], name: str, observed, expected, detail: str = "") -> None:
    checks.append({
        "name": name,
        "status": "PASS" if observed == expected else "FAIL",
        "observed": observed,
        "expected": expected,
        "detail": detail,
    })


def main() -> int:
    if not DB.is_file() or not SOURCE_MANIFEST.is_file():
        raise FileNotFoundError("The fixed backup database or its sibling manifest is missing")
    manifest = json.loads(SOURCE_MANIFEST.read_text(encoding="utf-8"))
    digest_before = sha256_file(DB)
    manifest_digest = manifest.get("database_sha256")

    connection = duckdb.connect(str(DB), read_only=True)
    connection.execute("SET memory_limit='2GB'")
    connection.execute("SET threads=2")
    connection.execute("SET preserve_insertion_order=false")

    checks: list[dict] = []
    counts: dict[str, dict] = {}
    date_inventory: list[dict] = []

    add_check(checks, "database_sha256_matches_manifest", digest_before, manifest_digest,
              "Snapshot bytes match the sibling source manifest.")
    add_check(checks, "manifest_scope", manifest.get("scope"),
              "2010-01-01 through 2026-09-29; Seoul, Busan-Gyeongnam, Yeongcheon; no Jeju")

    object_rows = query_rows(
        connection,
        "SELECT table_name, table_type FROM information_schema.tables "
        "WHERE table_schema='main' ORDER BY table_name",
    )
    db_objects = {row[0]: row[1] for row in object_rows}
    manifest_objects = set(manifest.get("table_and_view_counts", {}))
    uncounted_helper_views = {
        "confirmed_runners_entity_reviewed_before_role_review",
        "trial_participants_entity_reviewed_before_role_review",
    }
    inventory_pass = (
        manifest_objects.issubset(db_objects)
        and set(db_objects) - manifest_objects == uncounted_helper_views
        and len(db_objects) == 180
    )
    checks.append({
        "name": "manifest_object_inventory",
        "status": "PASS" if inventory_pass else "FAIL",
        "observed": {
            "database_object_count": len(db_objects),
            "manifest_count_map_entries": len(manifest_objects),
            "manifest_names_missing_from_database": sorted(manifest_objects - set(db_objects)),
            "database_objects_not_row_counted_in_manifest": sorted(set(db_objects) - manifest_objects),
        },
        "expected": {
            "database_object_count": 180,
            "manifest_count_map_entries": 178,
            "database_objects_not_row_counted_in_manifest": sorted(uncounted_helper_views),
        },
        "detail": "The two additional objects are named pre-role-review helper views.",
    })

    manifest_counts = manifest.get("table_and_view_counts", {})
    for name, (sql, expected) in EXPECTED_COUNTS.items():
        observed = int(query_one(connection, sql))
        manifest_value = manifest_counts.get(name)
        passed = observed == expected and manifest_value == expected
        checks.append({
            "name": f"row_count:{name}",
            "status": "PASS" if passed else "FAIL",
            "observed": observed,
            "expected": expected,
            "manifest": manifest_value,
        })
        counts[name] = {"observed": observed, "expected": expected, "manifest": manifest_value}

    uniqueness_queries = {
        "calendar_venue_date": "SELECT count(*) FROM (SELECT meet,date FROM calendar_days GROUP BY meet,date HAVING count(*)>1)",
        "race_plan_natural_key": "SELECT count(*) FROM (SELECT meet,date,race_no FROM race_plan GROUP BY meet,date,race_no HAVING count(*)>1)",
        "race_plan_full_api_natural_key": "SELECT count(*) FROM (SELECT source_meet,race_date_key,race_no_key FROM race_plan_full_api GROUP BY source_meet,race_date_key,race_no_key HAVING count(*)>1)",
        "race_flags_natural_key": "SELECT count(*) FROM (SELECT meet,date,race_no FROM race_execution_flags GROUP BY meet,date,race_no HAVING count(*)>1)",
        "race_adjudication_natural_key": "SELECT count(*) FROM (SELECT meet,date,race_no FROM race_nonexecution_adjudication GROUP BY meet,date,race_no HAVING count(*)>1)",
        "race_event_natural_key": "SELECT count(*) FROM (SELECT source_meet,result_date_key,result_race_no_key FROM race_events GROUP BY source_meet,result_date_key,result_race_no_key HAVING count(*)>1)",
        "runner_result_natural_key": "SELECT count(*) FROM (SELECT source_meet,result_date,result_race_no,horse_program_no_raw FROM runner_results GROUP BY source_meet,result_date,result_race_no,horse_program_no_raw HAVING count(*)>1)",
        "trial_session_id": "SELECT count(*) FROM (SELECT trial_session_id FROM trial_sessions GROUP BY trial_session_id HAVING count(*)>1)",
        "trial_session_date_meet_number": "SELECT count(*) FROM (SELECT source_meet_query,trial_date,trial_no FROM trial_sessions GROUP BY source_meet_query,trial_date,trial_no HAVING count(*)>1)",
        "trial_participant_id": "SELECT count(*) FROM (SELECT participant_row_id FROM trial_participants GROUP BY participant_row_id HAVING count(*)>1)",
        "trial_participant_source_item": "SELECT count(*) FROM (SELECT trial_session_id,source_item_index FROM trial_participants GROUP BY trial_session_id,source_item_index HAVING count(*)>1)",
        "entity_type_official_id": "SELECT count(*) FROM (SELECT entity_type,entity_id_official_string FROM entity_reference_roster GROUP BY entity_type,entity_id_official_string HAVING count(*)>1)",
        "section_runner_coverage_key": "SELECT count(*) FROM (SELECT meet,race_date,race_no,horse_id,horse_program_no FROM runner_section_coverage_api GROUP BY meet,race_date,race_no,horse_id,horse_program_no HAVING count(*)>1)",
        "section_measurement_source_field_pointer": "SELECT count(*) FROM (SELECT meet,race_date,race_no,source_file,source_item_index,source_field FROM section_measurements_api GROUP BY meet,race_date,race_no,source_file,source_item_index,source_field HAVING count(*)>1)",
    }
    duplicate_rows = {}
    for name, sql in uniqueness_queries.items():
        value = int(query_one(connection, sql))
        duplicate_rows[name] = value
        add_check(checks, f"duplicate_key:{name}", value, 0)

    date_specs = [
        ("race_plan.date", "SELECT count(*) FILTER (WHERE NOT regexp_matches(date,'^[0-9]{8}$') OR try_strptime(date,'%Y%m%d') IS NULL),min(date),max(date) FROM race_plan", "YYYYMMDD", START_COMPACT, END_COMPACT),
        ("race_plan_full_api.race_date_key", "SELECT count(*) FILTER (WHERE NOT regexp_matches(race_date_key,'^[0-9]{8}$') OR try_strptime(race_date_key,'%Y%m%d') IS NULL),min(race_date_key),max(race_date_key) FROM race_plan_full_api", "YYYYMMDD", START_COMPACT, END_COMPACT),
        ("race_events.result_date_key", "SELECT count(*) FILTER (WHERE NOT regexp_matches(result_date_key,'^[0-9]{8}$') OR try_strptime(result_date_key,'%Y%m%d') IS NULL),min(result_date_key),max(result_date_key) FROM race_events", "YYYYMMDD", START_COMPACT, END_COMPACT),
        ("race_events.scheduled_date", "SELECT count(*) FILTER (WHERE NOT regexp_matches(scheduled_date,'^[0-9]{8}$') OR try_strptime(scheduled_date,'%Y%m%d') IS NULL),min(scheduled_date),max(scheduled_date) FROM race_events", "YYYYMMDD", START_COMPACT, END_COMPACT),
        ("runner_results.result_date", "SELECT count(*) FILTER (WHERE NOT regexp_matches(result_date,'^[0-9]{8}$') OR try_strptime(result_date,'%Y%m%d') IS NULL),min(result_date),max(result_date) FROM runner_results", "YYYYMMDD", START_COMPACT, END_COMPACT),
        ("section_coverage.race_date", "SELECT count(*) FILTER (WHERE NOT regexp_matches(race_date,'^[0-9]{8}$') OR try_strptime(race_date,'%Y%m%d') IS NULL),min(race_date),max(race_date) FROM runner_section_coverage_api", "YYYYMMDD", START_COMPACT, END_COMPACT),
        ("calendar_days.date", "SELECT count(*) FILTER (WHERE NOT regexp_matches(date,'^[0-9]{4}-[0-9]{2}-[0-9]{2}$') OR try_strptime(date,'%Y-%m-%d') IS NULL),min(date),max(date) FROM calendar_days", "ISO-8601 date", START_ISO, END_ISO),
        ("trial_sessions.trial_date", "SELECT count(*) FILTER (WHERE NOT regexp_matches(trial_date,'^[0-9]{4}-[0-9]{2}-[0-9]{2}$') OR try_strptime(trial_date,'%Y-%m-%d') IS NULL),min(trial_date),max(trial_date) FROM trial_sessions", "ISO-8601 date", START_ISO, END_ISO),
        ("trial_participants.trial_date", "SELECT count(*) FILTER (WHERE NOT regexp_matches(trial_date,'^[0-9]{4}-[0-9]{2}-[0-9]{2}$') OR try_strptime(trial_date,'%Y-%m-%d') IS NULL),min(trial_date),max(trial_date) FROM trial_participants", "ISO-8601 date", START_ISO, END_ISO),
        ("official_closure_intervals.start_end_date", "SELECT count(*) FILTER (WHERE NOT regexp_matches(start_date,'^[0-9]{4}-[0-9]{2}-[0-9]{2}$') OR try_strptime(start_date,'%Y-%m-%d') IS NULL OR NOT regexp_matches(end_date,'^[0-9]{4}-[0-9]{2}-[0-9]{2}$') OR try_strptime(end_date,'%Y-%m-%d') IS NULL),min(start_date),max(end_date) FROM official_closure_intervals", "ISO-8601 date", START_ISO, END_ISO),
    ]
    date_range_queries = {
        "race_plan.date": ("SELECT count(*) FROM race_plan WHERE date<? OR date>?", (START_COMPACT, END_COMPACT)),
        "race_plan_full_api.race_date_key": ("SELECT count(*) FROM race_plan_full_api WHERE race_date_key<? OR race_date_key>?", (START_COMPACT, END_COMPACT)),
        "race_events.result_date_key": ("SELECT count(*) FROM race_events WHERE result_date_key<? OR result_date_key>?", (START_COMPACT, END_COMPACT)),
        "race_events.scheduled_date": ("SELECT count(*) FROM race_events WHERE scheduled_date<? OR scheduled_date>?", (START_COMPACT, END_COMPACT)),
        "runner_results.result_date": ("SELECT count(*) FROM runner_results WHERE result_date<? OR result_date>?", (START_COMPACT, END_COMPACT)),
        "section_coverage.race_date": ("SELECT count(*) FROM runner_section_coverage_api WHERE race_date<? OR race_date>?", (START_COMPACT, END_COMPACT)),
        "calendar_days.date": ("SELECT count(*) FROM calendar_days WHERE date<? OR date>?", (START_ISO, END_ISO)),
        "trial_sessions.trial_date": ("SELECT count(*) FROM trial_sessions WHERE trial_date<? OR trial_date>?", (START_ISO, END_ISO)),
        "trial_participants.trial_date": ("SELECT count(*) FROM trial_participants WHERE trial_date<? OR trial_date>?", (START_ISO, END_ISO)),
        "official_closure_intervals.start_end_date": ("SELECT count(*) FROM official_closure_intervals WHERE start_date<? OR start_date>? OR end_date<? OR end_date>?", (START_ISO, END_ISO, START_ISO, END_ISO)),
    }
    for name, sql, fmt, lower, upper in date_specs:
        invalid, minimum, maximum = query_rows(connection, sql)[0]
        outside_sql, outside_params = date_range_queries[name]
        outside = int(query_one(connection, outside_sql, outside_params))
        ok = int(invalid) == 0 and outside == 0
        date_inventory.append({
            "field": name,
            "format": fmt,
            "invalid_count": int(invalid),
            "out_of_scope_count": outside,
            "minimum": minimum,
            "maximum": maximum,
        })
        checks.append({
            "name": f"date_format_and_scope:{name}",
            "status": "PASS" if ok else "FAIL",
            "observed": {"invalid_count": int(invalid), "out_of_scope_count": outside, "minimum": minimum, "maximum": maximum},
            "expected": {"invalid_count": 0, "out_of_scope_count": 0, "format": fmt},
        })

    scope_queries = {
        "race_plan_meets": ("SELECT count(*) FROM race_plan WHERE meet NOT IN (?,?,?)", ("1", "3", "4")),
        "race_event_meets": ("SELECT count(*) FROM race_events WHERE source_meet NOT IN (?,?,?)", ("1", "3", "4")),
        "runner_result_meets": ("SELECT count(*) FROM runner_results WHERE source_meet NOT IN (?,?,?)", ("1", "3", "4")),
        "calendar_meets": ("SELECT count(*) FROM calendar_days WHERE meet NOT IN (?,?,?)", ("1", "3", "4")),
        "section_meets": ("SELECT count(*) FROM runner_section_coverage_api WHERE meet NOT IN (?,?,?)", ("1", "3", "4")),
        "trial_source_meets": ("SELECT count(*) FROM trial_sessions WHERE source_meet_query NOT IN (?,?)", ("1", "3")),
    }
    for name, (sql, params) in scope_queries.items():
        add_check(checks, f"scope:{name}", int(query_one(connection, sql, params)), 0,
                  "Seoul=1, Busan/Yeongnam query=3, Yeongcheon=4; Jeju=2 excluded.")

    fk_queries = {
        "full_plan_exactly_matches_plan": "SELECT (SELECT count(*) FROM (SELECT meet,date,race_no FROM race_plan EXCEPT SELECT source_meet,race_date_key,race_no_key FROM race_plan_full_api)) + (SELECT count(*) FROM (SELECT source_meet,race_date_key,race_no_key FROM race_plan_full_api EXCEPT SELECT meet,date,race_no FROM race_plan))",
        "events_have_exact_plan_key_and_date": "SELECT count(*) FROM race_events e LEFT JOIN race_plan p ON p.meet=e.source_meet AND p.date=e.result_date_key AND p.race_no=e.result_race_no_key WHERE p.meet IS NULL OR e.scheduled_in_plan_api<>'1' OR e.scheduled_date<>p.date",
        "runner_rows_have_event_parent": "SELECT count(*) FROM runner_results r LEFT JOIN race_events e ON e.source_meet=r.source_meet AND e.result_date_key=r.result_date AND e.result_race_no_key=r.result_race_no WHERE e.source_meet IS NULL OR r.in_plan_api<>'1'",
        "event_result_item_counts_match_runner_rows": "SELECT count(*) FROM (SELECT e.source_meet,e.result_date_key,e.result_race_no_key,e.result_item_count,count(r.source_item_index) AS rows_found FROM race_events e LEFT JOIN runner_results r ON r.source_meet=e.source_meet AND r.result_date=e.result_date_key AND r.result_race_no=e.result_race_no_key GROUP BY e.source_meet,e.result_date_key,e.result_race_no_key,e.result_item_count HAVING try_cast(e.result_item_count AS INTEGER)<>rows_found)",
        "execution_flags_have_plan_parent": "SELECT count(*) FROM race_execution_flags f LEFT JOIN race_plan p USING(meet,date,race_no) WHERE p.meet IS NULL",
        "trial_participants_have_exact_session_parent": "SELECT count(*) FROM trial_participants p LEFT JOIN trial_sessions s ON s.trial_session_id=p.trial_session_id WHERE s.trial_session_id IS NULL OR p.trial_date<>s.trial_date OR p.trial_no<>s.trial_no OR p.source_meet_query<>s.source_meet_query",
        "section_measurements_have_coverage_parent": "SELECT count(*) FROM section_measurements_api m LEFT JOIN runner_section_coverage_api c ON c.meet=m.meet AND c.race_date=m.race_date AND c.race_no=m.race_no AND c.horse_id=m.horse_id AND c.horse_program_no=m.horse_program_no WHERE c.horse_id IS NULL",
    }
    for name, sql in fk_queries.items():
        add_check(checks, f"foreign_key:{name}", int(query_one(connection, sql)), 0)

    result_spine = query_rows(
        connection,
        "SELECT execution_status,count(*),count(*) FILTER (WHERE positive_finish_evidence='1') "
        "FROM runner_results GROUP BY execution_status ORDER BY execution_status",
    )
    expected_spine = [
        ("executed_plan_and_result", 330465, 324784),
        ("planned_no_execution_evidence", 1346, 0),
    ]
    add_check(checks, "result_runner_partition", [list(row) for row in result_spine],
              [list(row) for row in expected_spine],
              "All result rows partition into confirmed-race runners and planned nonexecution rows.")

    nonexecution_distribution = query_rows(
        connection,
        "SELECT execution_verdict,adjudication_status,count(*) FROM race_nonexecution_adjudication "
        "GROUP BY execution_verdict,adjudication_status ORDER BY execution_verdict,adjudication_status",
    )
    expected_nonexecution = [
        ["no_valid_completed_race", "official_closure_nonexecution", 17],
        ["no_valid_completed_race", "official_day_cancelled", 35],
        ["no_valid_completed_race", "race_cancelled", 51],
        ["no_valid_completed_race", "race_invalid", 2],
        ["no_valid_completed_race", "reported_day_cancelled", 11],
    ]
    add_check(checks, "all_planned_nonexecution_keys_classified", [list(row) for row in nonexecution_distribution], expected_nonexecution)
    subtype_summary = query_rows(
        connection,
        "SELECT previous_status,reviewed_status,count(*) FROM race_nonexecution_subtype_review "
        "GROUP BY previous_status,reviewed_status ORDER BY previous_status,reviewed_status",
    )
    add_check(checks, "29_previously_unclassified_rows_closed_as_cancelled", [list(row) for row in subtype_summary],
              [["reason_recorded_outcome_unclassified", "race_cancelled", 29]])
    add_check(checks, "unresolved_race_days", int(query_one(connection, "SELECT count(*) FROM unresolved_race_days")), 0)
    closure_days = int(query_one(
        connection,
        "SELECT count(DISTINCT d.meet||'|'||d.date) FROM official_closure_intervals i "
        "JOIN calendar_days d ON d.meet=i.meet_code AND d.date BETWEEN i.start_date AND i.end_date",
    ))
    add_check(checks, "documented_closure_venue_days", closure_days, 552)
    closure_execution_conflicts = int(query_one(
        connection,
        "SELECT count(*) FROM official_closure_intervals i JOIN calendar_days d "
        "ON d.meet=i.meet_code AND d.date BETWEEN i.start_date AND i.end_date "
        "JOIN race_execution_flags f ON f.meet=d.meet AND f.date=replace(d.date,'-','') "
        "WHERE f.execution_status='executed_plan_and_result'",
    ))
    add_check(checks, "executed_races_on_documented_closure_dates", closure_execution_conflicts, 0)

    calendar_coverage = query_rows(
        connection,
        "SELECT count(*),count(DISTINCT date),count(DISTINCT meet),min(date),max(date) FROM calendar_days",
    )[0]
    add_check(checks, "calendar_full_date_venue_rectangle", list(calendar_coverage),
              [18348, 6116, 3, START_ISO, END_ISO])

    venue_review = query_rows(
        connection,
        "SELECT count(*),sum(try_cast(participant_rows AS INTEGER)), "
        "count(*) FILTER (WHERE venue_review_status='confirmed_official_plan_and_user_clarification' "
        "AND physical_venue='부산경남' AND reviewed_distance_m=1000 AND api_meet_label='영남') "
        "FROM trial_sessions_venue_reviewed WHERE source_meet_query='3' AND trial_date='2026-09-17'",
    )[0]
    add_check(checks, "reviewed_2026_09_17_yeongnam_trial_scope", list(venue_review), [4, 48, 4])

    identity_methods = query_rows(
        connection,
        "SELECT resolution_method,count(*) FROM trial_horse_identity_links GROUP BY resolution_method ORDER BY resolution_method",
    )
    add_check(checks, "missing_trial_horse_ids_resolved_by_documented_methods", [list(row) for row in identity_methods],
              [["crosschecked_operational_rpt", 99], ["user_confirmed_rpt_profile", 5]])
    add_check(checks, "no_unresolved_trial_horse_ids",
              int(query_one(connection, "SELECT count(*) FROM unresolved_trial_participants")), 0)
    unresolved_trial_id_links = int(query_one(
        connection,
        "SELECT count(*) FROM trial_participants_resolved p LEFT JOIN entity_reference_roster h "
        "ON h.entity_type='horse' AND h.entity_id_official_string=p.resolved_horse_id "
        "WHERE p.resolved_horse_id IS NULL OR p.resolved_horse_id='' OR h.entity_id_official_string IS NULL",
    ))
    add_check(checks, "resolved_trial_horse_ids_match_official_id_roster", unresolved_trial_id_links, 0)

    raw_id_shape = query_rows(
        connection,
        "SELECT count(*) FILTER (WHERE horse_id_raw IS NULL OR length(horse_id_raw)<>7), "
        "count(*) FILTER (WHERE jockey_id_raw IS NULL OR length(jockey_id_raw)<>6), "
        "count(*) FILTER (WHERE trainer_id_raw IS NOT NULL AND trainer_id_raw<>'' "
        "AND trainer_id_raw<>'0AAAAA' AND length(trainer_id_raw)<>6), "
        "count(*) FILTER (WHERE owner_id_raw IS NOT NULL AND owner_id_raw<>'' AND length(owner_id_raw)<>6) "
        "FROM confirmed_runners",
    )[0]
    add_check(checks, "official_runner_id_widths_without_numeric_conversion", list(raw_id_shape), [0, 0, 0, 0],
              "Identifiers remain strings; widths are validated without casting or padding IDs.")

    raw_id_type_fields = [
        ("race_plan", "date"), ("race_events", "result_date_key"), ("race_events", "scheduled_date"),
        ("runner_results", "result_date"), ("calendar_days", "date"), ("trial_sessions", "trial_date"),
        ("trial_participants", "trial_date"), ("runner_section_coverage_api", "race_date"),
        ("runner_results", "horse_id_raw"), ("runner_results", "jockey_id_raw"),
        ("runner_results", "trainer_id_raw"), ("runner_results", "owner_id_raw"),
        ("entity_reference_roster", "entity_id_official_string"),
    ]
    type_results = []
    for table_name, column_name in raw_id_type_fields:
        data_type = query_one(
            connection,
            "SELECT data_type FROM information_schema.columns WHERE table_schema='main' "
            "AND table_name=? AND column_name=?",
            (table_name, column_name),
        )
        type_results.append([table_name, column_name, data_type])
    all_varchar = all(row[2] == "VARCHAR" for row in type_results)
    checks.append({"name": "date_and_official_id_columns_are_varchar", "status": "PASS" if all_varchar else "FAIL",
                   "observed": type_results, "expected": "VARCHAR for every listed date and ID field"})

    roster_groups = query_rows(
        connection,
        "SELECT entity_type,count(*),count(*) FILTER (WHERE left(entity_id_official_string,1)='0') "
        "FROM entity_reference_roster GROUP BY entity_type ORDER BY entity_type",
    )
    expected_roster_groups = [
        ["horse", 23814, 23632], ["jockey", 337, 337], ["owner", 1438, 311], ["trainer", 225, 225],
    ]
    add_check(checks, "official_id_reference_roster_counts_and_zero_prefixes", [list(row) for row in roster_groups],
              expected_roster_groups)
    zero_prefixed_examples = query_rows(
        connection,
        "SELECT entity_type,entity_id_official_string FROM ("
        "SELECT entity_type,entity_id_official_string,row_number() OVER "
        "(PARTITION BY entity_type ORDER BY entity_id_official_string) AS rn "
        "FROM entity_reference_roster WHERE left(entity_id_official_string,1)='0') "
        "WHERE rn<=3 ORDER BY entity_type,rn",
    )

    linked_runner_gaps = query_rows(
        connection,
        "SELECT 'horse',count(*) FROM confirmed_runners_entity_reviewed r LEFT JOIN entity_reference_roster h "
        "ON h.entity_type='horse' AND h.entity_id_official_string=r.horse_id_raw "
        "WHERE r.horse_entity_id IS NULL OR r.horse_entity_id<>r.horse_id_raw OR h.entity_id_official_string IS NULL "
        "UNION ALL SELECT 'jockey',count(*) FROM confirmed_runners_entity_reviewed r LEFT JOIN entity_reference_roster j "
        "ON j.entity_type='jockey' AND j.entity_id_official_string=r.jockey_id_raw "
        "WHERE r.jockey_entity_id IS NULL OR r.jockey_entity_id<>r.jockey_id_raw OR j.entity_id_official_string IS NULL "
        "UNION ALL SELECT 'trainer',count(*) FROM confirmed_runners_entity_reviewed r LEFT JOIN entity_reference_roster t "
        "ON t.entity_type='trainer' AND t.entity_id_official_string=r.trainer_entity_id_with_review "
        "WHERE r.trainer_id_raw NOT IN ('0AAAAA','휴양마') AND r.trainer_entity_id_with_review IS NOT NULL "
        "AND (t.entity_id_official_string IS NULL OR t.entity_id_official_string<>r.trainer_entity_id_with_review) "
        "UNION ALL SELECT 'owner',count(*) FROM confirmed_runners_entity_reviewed r LEFT JOIN entity_reference_roster o "
        "ON o.entity_type='owner' AND o.entity_id_official_string=r.owner_entity_id_with_review "
        "WHERE r.owner_entity_id_with_review IS NULL OR o.entity_id_official_string IS NULL "
        "OR o.entity_id_official_string<>r.owner_entity_id_with_review ORDER BY 1",
    )
    add_check(checks, "confirmed_runner_entity_ids_match_official_roster", [list(row) for row in linked_runner_gaps],
              [["horse", 0], ["jockey", 0], ["owner", 0], ["trainer", 0]])
    trial_role_gaps = query_rows(
        connection,
        "SELECT 'jockey',count(*) FROM trial_participants_entity_reviewed p LEFT JOIN jockey_reference_ids_with_review j "
        "ON j.jockey_id=p.jockey_entity_id_with_review WHERE p.jockey_entity_id_with_review IS NULL "
        "OR j.jockey_id IS NULL UNION ALL SELECT 'trainer',count(*) "
        "FROM trial_participants_entity_reviewed p LEFT JOIN entity_reference_roster t "
        "ON t.entity_type='trainer' AND t.entity_id_official_string=p.trainer_entity_id_with_review "
        "WHERE p.trainer_entity_id_with_review IS NOT NULL AND t.entity_id_official_string IS NULL ORDER BY 1",
    )
    add_check(checks, "reviewed_trial_entity_ids_match_official_roster", [list(row) for row in trial_role_gaps],
              [["jockey", 0], ["trainer", 0]])

    section_value_errors = query_rows(
        connection,
        "SELECT count(*) FILTER (WHERE measure_kind='passing_order' AND "
        "(passing_order IS NULL OR passing_order<1 OR passing_order=99 OR time_ms IS NOT NULL)), "
        "count(*) FILTER (WHERE measure_kind<>'passing_order' AND "
        "(time_ms IS NULL OR time_ms<=0 OR passing_order IS NOT NULL)), "
        "count(*) FILTER (WHERE measure_kind NOT IN ('closing_time','cumulative_time','passing_order','segment_time')) "
        "FROM section_measurements_api",
    )[0]
    add_check(checks, "section_measurement_kind_value_contract", list(section_value_errors), [0, 0, 0])
    section_coverage_consistency = query_rows(
        connection,
        "SELECT count(*) FILTER (WHERE has_section_data<>(time_measurements>0 OR passing_measurements>0)), "
        "count(*) FILTER (WHERE time_measurements<0 OR passing_measurements<0), "
        "sum(time_measurements),sum(passing_measurements),count(*) "
        "FROM runner_section_coverage_api",
    )[0]
    add_check(checks, "section_coverage_flags_and_counts", list(section_coverage_consistency),
              [0, 0, 2617940, 1762125, 330465])
    section_spine_difference = int(query_one(
        connection,
        "SELECT (SELECT count(*) FROM (SELECT source_meet,result_date,result_race_no,horse_id_raw,horse_program_no_raw "
        "FROM confirmed_runners EXCEPT ALL SELECT meet,race_date,race_no,horse_id,horse_program_no "
        "FROM runner_section_coverage_api)) + (SELECT count(*) FROM ("
        "SELECT meet,race_date,race_no,horse_id,horse_program_no FROM runner_section_coverage_api "
        "EXCEPT ALL SELECT source_meet,result_date,result_race_no,horse_id_raw,horse_program_no_raw "
        "FROM confirmed_runners))",
    ))
    add_check(checks, "section_runner_coverage_exactly_matches_confirmed_runners", section_spine_difference, 0)
    no_data_coverage = query_rows(
        connection,
        "SELECT has_section_data,count(*) FROM runner_section_coverage_api GROUP BY has_section_data ORDER BY has_section_data",
    )
    add_check(checks, "section_observed_and_missing_counts", [list(row) for row in no_data_coverage],
              [[False, 4870], [True, 325595]])
    missing_finisher_rows = query_rows(
        connection,
        "SELECT r.source_meet,r.result_date,r.result_race_no,r.horse_program_no_raw,r.horse_id_raw,r.horse_name_raw, "
        "x.reported_record_category,x.reported_text_raw,x.record_source,c.has_section_data,x.section_missing_cause_status "
        "FROM section_missing_finisher_review x JOIN confirmed_runners r "
        "ON r.source_meet=x.meet AND r.result_date=x.race_date AND r.result_race_no=x.race_no "
        "AND r.horse_program_no_raw=x.horse_program_no AND r.horse_id_raw=x.horse_id "
        "JOIN runner_section_coverage_api c ON c.meet=r.source_meet AND c.race_date=r.result_date "
        "AND c.race_no=r.result_race_no AND c.horse_id=r.horse_id_raw "
        "AND c.horse_program_no=r.horse_program_no_raw ORDER BY r.result_date",
    )
    expected_missing_finishers = [
        ["1", "20100704", "6", "10", "0020813", "용왕성", "특이경주", "실격 미처분", "user_provided_2026-09-30", False, "unverified"],
        ["1", "20121006", "9", "9", "0027368", "동촌", "출주정지", "2개월(2012.10.07~2012.12.06); 양 앞다리 질병(양전 제염)", "user_provided_2026-09-30", False, "unverified"],
    ]
    add_check(checks, "two_documented_finisher_section_gaps_remain_unimputed",
              [list(row) for row in missing_finisher_rows], expected_missing_finishers,
              "The user-provided post-race records are retained. Their causal link to the missing API section values remains unverified; no measurement is imputed.")

    role_exception_groups = query_rows(
        connection,
        "SELECT event_type,trainer_exception_class,review_status,count(*) "
        "FROM role_link_exceptions_current GROUP BY event_type,trainer_exception_class,review_status "
        "ORDER BY event_type,trainer_exception_class,review_status",
    )
    expected_role_exceptions = [
        ["race", "confirmed_non_person_placeholder", "placeholder_0AAAAA_web_row_checked", 23],
        ["trial", "confirmed_non_person_placeholder", "confirmed_same_nonperson_placeholder", 140],
        ["trial", "confirmed_non_person_placeholder", "official_row_nonperson_sentinel_for_missing_source_id", 1],
        ["trial", "source_error_unknown_cause", "closed_user_accepted_source_error", 22],
    ]
    add_check(checks, "documented_role_exception_categories", [list(row) for row in role_exception_groups], expected_role_exceptions,
              "The 22 accepted source errors stay ID-null and are reported as closed exceptions, not reopened.")
    closed_error_summary = query_rows(
        connection,
        "SELECT count(*),count(*) FILTER (WHERE trainer_entity_id_with_review IS NULL), "
        "count(*) FILTER (WHERE try_cast(api_rcTime AS DOUBLE)>0), "
        "count(*) FILTER (WHERE try_cast(api_rcTime AS DOUBLE)=0) "
        "FROM trial_participants_entity_reviewed "
        "WHERE trainer_exception_review_status='closed_user_accepted_source_error'",
    )[0]
    add_check(checks, "22_closed_trial_trainer_source_errors_remain_unassigned", list(closed_error_summary), [22, 22, 19, 3])

    raw_exception_summary = query_rows(
        connection,
        "SELECT (SELECT count(*) FROM confirmed_runners WHERE trainer_id_raw IS NULL OR trainer_id_raw=''), "
        "(SELECT count(*) FROM confirmed_runners WHERE owner_id_raw IS NULL OR owner_id_raw=''), "
        "(SELECT count(*) FROM trial_participants WHERE horse_id_missing='true'), "
        "(SELECT count(*) FROM trial_participants WHERE api_jkNo IS NULL OR api_jkNo='' OR api_jkNo='-'), "
        "(SELECT count(*) FROM trial_participants WHERE api_trNo IS NULL OR api_trNo='' OR api_trNo='-')",
    )[0]
    add_check(checks, "known_raw_identifier_gaps", list(raw_exception_summary), [38, 38, 104, 5121, 84])
    jockey_web_counts = query_rows(
        connection,
        "SELECT count(*) FILTER (WHERE official_web_jockey_id_rpt_verified IS NOT NULL), "
        "count(*) FILTER (WHERE official_web_jockey_id_conflict_reviewed IS NOT NULL), "
        "count(*) FILTER (WHERE official_web_jockey_id_scheduled IS NOT NULL), "
        "count(*) FILTER (WHERE official_web_jockey_id_rpt_verified IS NOT NULL AND try_cast(api_rcTime AS DOUBLE)>0), "
        "count(*) FILTER (WHERE official_web_jockey_id_rpt_verified IS NOT NULL AND try_cast(api_rcTime AS DOUBLE)=0) "
        "FROM trial_participants_entity_reviewed",
    )[0]
    add_check(checks, "official_trial_jockey_supplement_partition", list(jockey_web_counts), [5079, 18, 24, 4420, 659])
    actual_completed_trial_jockey_gaps = int(query_one(
        connection,
        "SELECT count(*) FROM trial_participants_entity_reviewed "
        "WHERE try_cast(api_rcTime AS DOUBLE)>0 AND jockey_id_for_completed_trial IS NULL",
    ))
    add_check(checks, "completed_trial_rows_missing_reviewed_jockey_id", actual_completed_trial_jockey_gaps, 0)
    assigned_only_on_positive_time = int(query_one(
        connection,
        "SELECT count(*) FROM trial_participants_entity_reviewed "
        "WHERE try_cast(api_rcTime AS DOUBLE)<=0 AND jockey_id_for_completed_trial IS NOT NULL",
    ))
    add_check(checks, "zero_time_trial_not_counted_as_completed_ride", assigned_only_on_positive_time, 0,
              "A listed or scheduled jockey on a zero-time row is not promoted to an actual ride.")

    blank_owner_names = query_rows(
        connection,
        "SELECT source_meet,result_date,result_race_no,horse_program_no_raw,horse_name_raw,owner_id_raw "
        "FROM confirmed_runners WHERE owner_id_raw IS NOT NULL AND owner_id_raw<>'' "
        "AND (owner_name_raw IS NULL OR owner_name_raw='') ORDER BY result_date,source_meet,result_race_no,horse_program_no_raw",
    )
    add_check(checks, "single_known_owner_name_absence_preserves_official_id", [list(row) for row in blank_owner_names],
              [["1", "20260809", "5", "11", "퀸즈플라잉", "010424"]],
              "Owner identity remains the official ID; no name is inferred.")

    rank_time_summary = query_rows(
        connection,
        "SELECT count(*) FILTER (WHERE result_rank_raw IS NULL OR result_rank_raw=''), "
        "count(*) FILTER (WHERE finish_time_seconds_raw IS NULL OR finish_time_seconds_raw=''), "
        "count(*) FILTER (WHERE result_rank_raw IN ('0','99')), "
        "count(*) FILTER (WHERE positive_finish_evidence='1' AND try_cast(finish_time_seconds_raw AS DOUBLE)<=0) "
        "FROM runner_results",
    )[0]
    add_check(checks, "runner_result_outcome_fields_and_nonfinish_markers", list(rank_time_summary), [0, 0, 1332, 0],
              "Raw rank 0/99 are retained and never treated as positive finishes; 2 such rows are in otherwise executed races.")
    nonfinish_rank_distribution = query_rows(
        connection,
        "SELECT execution_status,result_rank_raw,count(*),count(*) FILTER (WHERE positive_finish_evidence='1') "
        "FROM runner_results WHERE result_rank_raw IN ('0','94','95','98','99') "
        "GROUP BY execution_status,result_rank_raw ORDER BY execution_status,result_rank_raw",
    )
    add_check(checks, "nonfinish_rank_codes_partition", [list(row) for row in nonfinish_rank_distribution],
              [["executed_plan_and_result", "0", 2, 0],
               ["executed_plan_and_result", "94", 1568, 0],
               ["executed_plan_and_result", "95", 2030, 0],
               ["planned_no_execution_evidence", "0", 97, 0],
               ["planned_no_execution_evidence", "94", 1, 0],
               ["planned_no_execution_evidence", "95", 3, 0],
               ["planned_no_execution_evidence", "98", 12, 0],
               ["planned_no_execution_evidence", "99", 1233, 0]])

    result_only_key_count = int(query_one(connection, "SELECT count(*) FROM unverified_result_only_keys"))
    add_check(checks, "unverified_result_only_key_ledger_empty", result_only_key_count, 0)

    digest_after = sha256_file(DB)
    add_check(checks, "database_sha256_unchanged_after_read_only_audit", digest_after, digest_before)
    connection.close()

    failures = [item["name"] for item in checks if item["status"] != "PASS"]
    report = {
        "validation_title": "Pre-steward-report core data QA",
        "validation_status": "PASS" if not failures else "FAIL",
        "validated_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": {
            "date_range": "2010-01-01 through 2026-09-29",
            "venues": {"1": "Seoul", "3": "Busan-Gyeongnam / Yeongnam trial query", "4": "Yeongcheon"},
            "excluded_venue": "Jeju (2)",
            "model_period_start": "2017-01-01",
            "excluded_content": ["steward reports", "penalty/sanction objects"],
        },
        "source": {
            "database": str(DB),
            "sibling_manifest": str(SOURCE_MANIFEST),
            "manifest_built_at_utc": manifest.get("built_at_utc"),
            "database_sha256": digest_before,
            "manifest_database_sha256": manifest_digest,
            "manifest_source_input_count": len(manifest.get("input_files", [])),
            "manifest_status": manifest.get("status"),
            "opened_read_only": True,
        },
        "resource_settings": {"duckdb_memory_limit": "2GB", "duckdb_threads": 2},
        "object_inventory": {
            "database_object_count": len(db_objects),
            "manifest_row_count_entries": len(manifest_objects),
            "not_row_counted_helper_views": sorted(set(db_objects) - manifest_objects),
        },
        "counts": counts,
        "date_format_inventory": date_inventory,
        "duplicate_key_counts": duplicate_rows,
        "official_id_zero_prefix_examples": [list(row) for row in zero_prefixed_examples],
        "result_runner_status_partition": [list(row) for row in result_spine],
        "nonexecution_classification": [list(row) for row in nonexecution_distribution],
        "nonfinish_rank_distribution": [list(row) for row in nonfinish_rank_distribution],
        "role_exception_classification": [list(row) for row in role_exception_groups],
        "section_value_summary": {
            "measure_kind_contract_errors": list(section_value_errors),
            "coverage_flags_and_measurement_sums": list(section_coverage_consistency),
            "rows_by_has_section_data": [list(row) for row in no_data_coverage],
            "known_finisher_gaps": [list(row) for row in missing_finisher_rows],
        },
        "known_exceptions": [
            {"category": "planned races without valid completed-race evidence", "count": 116,
             "classification": "all adjudicated no_valid_completed_race; 29 previously unclassified cases are now race_cancelled"},
            {"category": "runner rows attached to planned nonexecution races", "count": 1346,
             "classification": "retained under planned_no_execution_evidence; zero positive finish rows"},
            {"category": "trainer non-person placeholders", "count": 164,
             "classification": "23 race rows and 141 trial rows; not person IDs"},
            {"category": "closed trial trainer source errors", "count": 22,
             "classification": "unknown cause, user-accepted closed status, trainer ID remains null; not reopened"},
            {"category": "trial API horse IDs absent", "count": 104,
             "classification": "99 crosschecked operational RPT links and 5 user-confirmed links; pending 0"},
            {"category": "trial API jockey IDs absent", "count": 5121,
             "classification": "5079 RPT-verified, 18 official score-table conflict reviews, 24 scheduled-only; zero-time assignments are not actual rides"},
            {"category": "confirmed runner trainer and owner IDs absent in original API fields", "count": 38,
             "classification": "original blanks preserved; official-ID supplements are linked in reviewed columns"},
            {"category": "known owner name absent with official ID retained", "count": 1,
             "example": "2026-08-09 Seoul R5 runner 11, Queen's Flying, owner ID 010424"},
            {"category": "runner section coverage without measurements", "count": 4870,
             "classification": "coverage rows retained; two user-provided post-race records are linked; whether either explains its missing API section values remains unverified; no values are imputed"},
            {"category": "nonfinish rank and status codes", "count": 4946,
             "classification": "ranks 0/94/95/98/99 remain non-positive-finish; 3600 rows occur in otherwise executed races and 1346 rows belong to planned nonexecution races"},
        ],
        "unverified_scope_limits": [
            "The source manifest labels this a staged core, not a frozen final database.",
            "The 81 sourced closure intervals / 552 venue-days are a partial historical closure list; unsourced no-race days are not classified as closures.",
            "The capture/publication as-of time and complete historical source coverage remain unverified.",
            "Section measurements are post-race outcomes and are not validated as pre-race model inputs.",
        ],
        "checks": checks,
        "failed_checks": failures,
    }
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"validation_status": report["validation_status"], "check_count": len(checks),
                      "failed_checks": failures, "output": str(OUTPUT), "database_sha256": digest_after},
                     ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
