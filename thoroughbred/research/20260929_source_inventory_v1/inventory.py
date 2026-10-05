#!/usr/bin/env python3
"""Read-only inventory of locally held Thoroughbred source coverage.

Run from the repository root with `.venv/bin/python
thoroughbred/research/20260929_source_inventory_v1/inventory.py`.
The script reads SQLite with `mode=ro`/`query_only` and DuckDB with
`read_only=True`. It writes only inventory.json and reconciliation.json next
to this script, and refuses to overwrite either output.
"""

from __future__ import annotations

import json
import csv
import sqlite3
import os
import stat
import argparse
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb


ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
TARGET_END = "2026-09-20"
MODEL_START = "2017-01-01"

SOURCE_FILES = {
    "operational_sqlite": ROOT / "data/horse_racing.sqlite3",
    "historical_unified_duckdb": ROOT / "data/research/thoroughbred_unified_20260918/thoroughbred_unified.duckdb",
    "section_points_adjudicated_sqlite": ROOT / "data/research/section_point_db_20260925/section_points_adjudicated.sqlite3",
    "research_dataset_v1_duckdb": ROOT / "thoroughbred/data/dataset_20260929_v1/thoroughbred.duckdb",
    "section_passing_raw_duckdb": ROOT / "thoroughbred/data/section_passing_raw_2010plus_20260929_v1/section_passing_raw.duckdb",
}


def spec(source: str, domain: str, table: str, sql: str, key: str, date_field: str,
         risk: str = "", date_role: str = "event_date") -> dict[str, str]:
    return {"source": source, "domain": domain, "table": table, "sql": sql,
            "key_candidate": key, "date_field": date_field, "risk": risk,
            "date_role": date_role}


# Each SQL projects the same three columns: meet (1/3/4 or NULL), event_date,
# and a compact key candidate. The actual raw columns remain in the input DBs.
SPECS = [
    spec("operational_sqlite", "race_schedule", "races",
         "SELECT rc.kra_meet_code meet, CAST(r.race_date_local AS TEXT) event_date, CAST(r.race_number AS TEXT) source_key FROM races r JOIN racecourses rc ON rc.id=r.racecourse_id WHERE rc.kra_meet_code IN (1,3,4)",
         "(racecourse_id, race_date_local, race_number)", "race_date_local",
         "status rows include non-completed/cancelled records; a missing race date is not proof of a closure."),
    spec("operational_sqlite", "race_entries", "race_entries",
         "SELECT rc.kra_meet_code meet, CAST(r.race_date_local AS TEXT) event_date, CAST(r.race_number AS TEXT)||':'||CAST(e.horse_number AS TEXT) source_key FROM race_entries e JOIN races r ON r.id=e.race_id JOIN racecourses rc ON rc.id=r.racecourse_id WHERE rc.kra_meet_code IN (1,3,4)",
         "(race_id, horse_number); cross-source (meet, date, race_no, horse_number)", "races.race_date_local",
         "horse_id is required, while jockey/trainer/owner IDs may be NULL; keep original names and IDs."),
    spec("operational_sqlite", "race_results", "race_results",
         "SELECT rc.kra_meet_code meet, CAST(r.race_date_local AS TEXT) event_date, CAST(r.race_number AS TEXT)||':'||CAST(e.horse_number AS TEXT) source_key FROM race_results x JOIN race_entries e ON e.id=x.race_entry_id JOIN races r ON r.id=e.race_id JOIN racecourses rc ON rc.id=r.racecourse_id WHERE rc.kra_meet_code IN (1,3,4)",
         "race_entry_id", "races.race_date_local", "one result row may contain a non-finish/special status; finish time alone is not a complete entry roster."),
    spec("operational_sqlite", "trial_schedule", "running_trials",
         "SELECT meet_code meet, CAST(trial_date_local AS TEXT) event_date, CAST(trial_race_number AS TEXT) source_key FROM running_trials WHERE meet_code IN (1,3,4)",
         "(meet_code, trial_date_local, trial_race_number)", "trial_date_local",
         "No meet=4 schedule was found. running_trials has no grade field."),
    spec("operational_sqlite", "trial_entries_results", "running_trial_results",
         "SELECT t.meet_code meet, CAST(t.trial_date_local AS TEXT) event_date, CAST(t.trial_race_number AS TEXT)||':'||CAST(x.horse_number AS TEXT) source_key FROM running_trial_results x JOIN running_trials t ON t.id=x.running_trial_id WHERE t.meet_code IN (1,3,4)",
         "(running_trial_id, horse_number)", "running_trials.trial_date_local",
         "Horse/jockey/trainer IDs are incompletely linked; participant name/number and judgement text are source evidence."),
    spec("operational_sqlite", "horse_entity_master", "horses",
         "SELECT NULL meet, NULL event_date, kra_horse_id source_key FROM horses",
         "kra_horse_id", "no event date; birth_date/profile_observed_at_ms are attributes/snapshots",
         "Global master includes entities outside the target meet scope; scope through verified event links."),
    spec("operational_sqlite", "jockey_entity_master", "jockeys",
         "SELECT NULL meet, NULL event_date, kra_jockey_id source_key FROM jockeys",
         "kra_jockey_id", "no effective-date history in the master table",
         "Names can change or repeat; preserve source ID/name and dated snapshots where present."),
    spec("operational_sqlite", "trainer_entity_master", "trainers",
         "SELECT NULL meet, NULL event_date, kra_trainer_id source_key FROM trainers",
         "kra_trainer_id", "no effective-date history in the master table",
         "Current master identity is not the same as historical affiliation."),
    spec("operational_sqlite", "owner_entity_master", "owners",
         "SELECT NULL meet, NULL event_date, kra_owner_id source_key FROM owners",
         "kra_owner_id", "no effective-date history in the master table",
         "No independent owner_change table was found; entry-time owner ID/name and profile snapshots are the available evidence."),
    spec("operational_sqlite", "horse_profile_snapshots", "horse_profile_snapshots",
         "SELECT meet_code meet, strftime('%Y-%m-%d', observed_at_ms/1000, 'unixepoch', '+9 hours') event_date, CAST(horse_id AS TEXT)||':'||CAST(observed_at_ms AS TEXT) source_key FROM horse_profile_snapshots WHERE meet_code IN (1,3,4)",
         "(horse_id, observed_at_ms)", "observed_at_ms converted to KST observation date; profile observation, not validity interval",
         "Observation date must not be mistaken for attribute effective date; same-day time still needs race-level as-of validation.", "observation_date_kst"),
    spec("operational_sqlite", "jockey_affiliation_and_history", "jockey_changes",
         "SELECT meet_code meet, CAST(race_date_local AS TEXT) event_date, CAST(race_number AS TEXT)||':'||CAST(horse_number AS TEXT) source_key FROM jockey_changes WHERE meet_code IN (1,3,4)",
         "(meet_code, race_date_local, race_number, horse_number, jockey_before_id, jockey_after_id)", "race_date_local",
         "A recorded change is tied to a race entry; observed_at_ms is a separate timestamp."),
    spec("operational_sqlite", "trainer_affiliation_snapshots", "trainer_affiliation_snapshots",
         "SELECT meet_code meet, CAST(observed_on AS TEXT) event_date, CAST(trainer_id AS TEXT)||':'||CAST(observed_on AS TEXT) source_key FROM trainer_affiliation_snapshots WHERE meet_code IN (1,3,4)",
         "(trainer_id, observed_on)", "observed_on; stats_as_of is a different date",
         "Official observed affiliation snapshots currently exist; observed_on is not necessarily effective_from."),
    spec("operational_sqlite", "trainer_historical_regions", "trainer_historical_regions",
         "SELECT CASE region_code WHEN 'SEOUL' THEN 1 WHEN 'YEONGNAM' THEN 3 ELSE NULL END meet, CAST(observed_on AS TEXT) event_date, CAST(trainer_id AS TEXT)||':'||region_code||':'||CAST(observed_on AS TEXT) source_key FROM trainer_historical_regions WHERE region_code IN ('SEOUL','YEONGNAM')",
         "(trainer_id, region_code, observed_on)", "observed_on/source_end_date",
         "Regional history is not detailed trainer-to-stable assignment history."),
    spec("operational_sqlite", "trainer_person_links", "trainer_person_links",
         "SELECT NULL meet, NULL event_date, trainer_ref source_key FROM trainer_person_links",
         "trainer_ref", "no date column on link table; trainer_people.decided_on belongs to the person decision",
         "Keep the stated link basis and evidence; do not treat person decision date as relationship effective date."),
    spec("operational_sqlite", "sectional_results", "race_section_results",
         "SELECT rc.kra_meet_code meet, CAST(r.race_date_local AS TEXT) event_date, CAST(e.id AS TEXT)||':'||s.section_code source_key FROM race_section_results s JOIN race_entries e ON e.id=s.race_entry_id JOIN races r ON r.id=e.race_id JOIN racecourses rc ON rc.id=r.racecourse_id WHERE rc.kra_meet_code IN (1,3,4)",
         "(race_entry_id, section_code)", "races.race_date_local",
         "This table is a different source/representation from race_section_times."),
    spec("operational_sqlite", "sectional_times", "race_section_times",
         "SELECT rc.kra_meet_code meet, CAST(r.race_date_local AS TEXT) event_date, CAST(e.id AS TEXT)||':'||s.point_code||':'||s.time_kind source_key FROM race_section_times s JOIN race_entries e ON e.id=s.race_entry_id JOIN races r ON r.id=e.race_id JOIN racecourses rc ON rc.id=r.racecourse_id WHERE rc.kra_meet_code IN (1,3,4)",
         "(race_entry_id, point_code, time_kind)", "races.race_date_local",
         "Cumulative/closing/segment meanings vary by venue, year and source field."),
    spec("operational_sqlite", "passing_groups", "race_passing_groups",
         "SELECT rc.kra_meet_code meet, CAST(r.race_date_local AS TEXT) event_date, CAST(p.race_id AS TEXT)||':'||p.point_code source_key FROM race_passing_groups p JOIN races r ON r.id=p.race_id JOIN racecourses rc ON rc.id=r.racecourse_id WHERE rc.kra_meet_code IN (1,3,4)",
         "(race_id, point_code)", "races.race_date_local",
         "Race-level group notation; do not expand as horse-level passing order."),
    spec("operational_sqlite", "passing_summaries", "race_passing_summaries",
         "SELECT rc.kra_meet_code meet, CAST(r.race_date_local AS TEXT) event_date, CAST(p.race_id AS TEXT) source_key FROM race_passing_summaries p JOIN races r ON r.id=p.race_id JOIN racecourses rc ON rc.id=r.racecourse_id WHERE rc.kra_meet_code IN (1,3,4)",
         "race_id (unique)", "races.race_date_local",
         "Race-level corner/time summary; source observation time is separately stored."),
    spec("operational_sqlite", "steward_reports", "race_steward_reports",
         "SELECT meet_code meet, CAST(race_date_local AS TEXT) event_date, CAST(race_number AS TEXT) source_key FROM race_steward_reports WHERE meet_code IN (1,3,4)",
         "(meet_code, race_date_local, race_number)", "race_date_local",
         "Local coverage begins in 2025 for Seoul/Busan; older official report coverage is unverified."),
    spec("operational_sqlite", "medical_events", "horse_medical",
         "SELECT meet_code meet, CAST(clinic_date_local AS TEXT) event_date, CAST(horse_id AS TEXT)||':'||CAST(clinic_date_local AS TEXT)||':'||CAST(id AS TEXT) source_key FROM horse_medical WHERE meet_code IN (1,3,4)",
         "source event ID; candidate natural key includes horse, meet, clinic date, facility and diagnoses", "clinic_date_local",
         "The operational table combines historical rows; API vs Text provenance and publication time need source-level separation."),
    spec("operational_sqlite", "daily_training", "horse_training",
         "SELECT meet_code meet, CAST(training_date_local AS TEXT) event_date, CAST(horse_id AS TEXT)||':'||CAST(training_date_local AS TEXT)||':'||CAST(id AS TEXT) source_key FROM horse_training WHERE meet_code IN (1,3,4)",
         "source event ID; candidate (horse_id, meet, date, started_at_raw, ended_at_raw)", "training_date_local",
         "Event date and public/observed availability can differ in historical backfill."),
    spec("operational_sqlite", "start_training", "horse_start_training",
         "SELECT meet_code meet, CAST(training_date_local AS TEXT) event_date, CAST(horse_id AS TEXT)||':'||CAST(training_date_local AS TEXT)||':'||CAST(id AS TEXT) source_key FROM horse_start_training WHERE meet_code IN (1,3,4)",
         "source event ID; candidate includes horse_id, meet, date, stable, rider", "training_date_local",
         "Do not interpret missing pre-source years as zero start-training activity."),
    spec("operational_sqlite", "swim_training", "horse_swim_training",
         "SELECT meet_code meet, CAST(training_date_local AS TEXT) event_date, kra_horse_id_raw||':'||CAST(meet_code AS TEXT)||':'||CAST(training_date_local AS TEXT) source_key FROM horse_swim_training WHERE meet_code IN (1,3,4)",
         "(kra_horse_id_raw, meet_code, training_date_local)", "training_date_local",
         "No Yeongcheon source found; horse_id may be NULL, so preserve raw official horse ID/name."),
    spec("operational_sqlite", "hill_training", "horse_hill_training",
         "SELECT NULL meet, CAST(training_date_local AS TEXT) event_date, CAST(id AS TEXT) source_key FROM horse_hill_training",
         "source_row_hash", "training_date_local",
         "No meet field; in the observed table 3,212/3,576 rows have no linked horse_id."),
    spec("operational_sqlite", "weight_events", "horse_weight_history",
         "SELECT meet_code meet, CAST(race_date_local AS TEXT) event_date, CAST(horse_id AS TEXT)||':'||CAST(race_date_local AS TEXT)||':'||CAST(race_number AS TEXT)||':'||CAST(horse_number AS TEXT) source_key FROM horse_weight_history WHERE meet_code IN (1,3,4)",
         "horse/race date/race number/horse number", "race_date_local",
         "Past public availability time is not established by event date alone."),
    spec("operational_sqlite", "equipment_events", "entry_equipment",
         "SELECT meet_code meet, CAST(race_date_local AS TEXT) event_date, CAST(meet_code AS TEXT)||':'||CAST(race_date_local AS TEXT)||':'||CAST(race_number AS TEXT)||':'||CAST(horse_number AS TEXT) source_key FROM entry_equipment WHERE meet_code IN (1,3,4)",
         "(meet_code, race_date_local, race_number, horse_number)", "race_date_local",
         "Keep raw note and observed_at_ms; historical publication time is unverified."),

    spec("historical_unified_duckdb", "race_schedule_and_result", "race",
         "SELECT CASE venue_code WHEN 'SEOUL' THEN 1 WHEN 'BUSAN' THEN 3 WHEN 'YEONGCHEON' THEN 4 END meet, CAST(race_date AS VARCHAR) event_date, CAST(race_no AS VARCHAR) source_key FROM race WHERE venue_code IN ('SEOUL','BUSAN','YEONGCHEON')",
         "(venue_code, race_date, race_no)", "race_date",
         "Historical source snapshot ends before the operational refresh; compare, do not choose priority from counts."),
    spec("historical_unified_duckdb", "race_entries_and_results", "entry_result",
         "SELECT CASE venue_code WHEN 'SEOUL' THEN 1 WHEN 'BUSAN' THEN 3 WHEN 'YEONGCHEON' THEN 4 END meet, CAST(race_date AS VARCHAR) event_date, CAST(race_no AS VARCHAR)||':'||CAST(chul_no AS VARCHAR) source_key FROM entry_result WHERE venue_code IN ('SEOUL','BUSAN','YEONGCHEON')",
         "(venue_code, race_date, race_no, chul_no); hr_no cross-check", "race_date",
         "Contains raw and normalized names plus source result status; preserve non-finish rows."),
    spec("historical_unified_duckdb", "trial_entries", "trial_entry",
         "SELECT canonical_meet meet, CAST(trial_date AS VARCHAR) event_date, CAST(trial_no AS VARCHAR)||':'||CAST(participant_no AS VARCHAR) source_key FROM trial_entry WHERE canonical_meet IN (1,3,4) OR venue_resolution_status='unresolved_after_yeongcheon_split'",
         "(source_meet, trial_date, trial_no, participant_no)", "trial_date",
         "48 post-split records have unresolved venue; retain with unresolved venue rather than assigning Busan or Yeongcheon."),
    spec("historical_unified_duckdb", "sectional_records", "section",
         "SELECT canonical_meet meet, CAST(race_date AS VARCHAR) event_date, CAST(race_no AS VARCHAR)||':'||CAST(hr_no AS VARCHAR)||':'||CAST(section_code AS VARCHAR)||':'||CAST(source_row AS VARCHAR) source_key FROM section WHERE venue_code IN ('SEOUL','BUSAN','YEONGCHEON')",
         "source path/row plus (venue, date, race, hr_no, section code)", "race_date",
         "Multiple source fields and time bases must remain distinct."),
    spec("historical_unified_duckdb", "daily_and_start_training", "training_event",
         "SELECT CASE training_venue_code WHEN 'SEOUL' THEN 1 WHEN 'BUSAN' THEN 3 WHEN 'YEONGCHEON' THEN 4 END meet, CAST(event_date AS VARCHAR) event_date, CAST(training_event_id AS VARCHAR) source_key FROM training_event WHERE training_venue_code IN ('SEOUL','BUSAN','YEONGCHEON') OR source_meet IN (1,3,4)",
         "training_event_id; raw source row retained", "event_date",
         "source_type separates event categories; event_date does not prove it was publicly observable by that date."),
    spec("historical_unified_duckdb", "medical_events", "medical_event",
         "SELECT CASE source_venue_code WHEN 'SEOUL' THEN 1 WHEN 'BUSAN' THEN 3 WHEN 'YEONGCHEON' THEN 4 END meet, CAST(event_date AS VARCHAR) event_date, CAST(medical_event_id AS VARCHAR) source_key FROM medical_event WHERE source_venue_code IN ('SEOUL','BUSAN','YEONGCHEON') OR source_meet IN (1,3,4)",
         "medical_event_id; raw source row retained", "event_date",
         "API and Text sources differ in identity/publication coverage; unresolved name matches remain unresolved."),
    spec("historical_unified_duckdb", "horse_entity_observation", "horse_dimension",
         "SELECT NULL meet, NULL event_date, hr_no source_key FROM horse_dimension",
         "hr_no", "no point-in-time entity profile date",
         "Dimension is derived from the available race history; not a complete timeless registry."),
    spec("historical_unified_duckdb", "unresolved_identity", "unresolved_identity_ledger",
         "SELECT CASE venue_code WHEN 'SEOUL' THEN 1 WHEN 'BUSAN' THEN 3 WHEN 'YEONGCHEON' THEN 4 END meet, CAST(event_date AS VARCHAR) event_date, CAST(issue_domain AS VARCHAR)||':'||CAST(event_key AS VARCHAR)||':'||CAST(source_row AS VARCHAR) source_key FROM unresolved_identity_ledger WHERE venue_code IN ('SEOUL','BUSAN','YEONGCHEON','YEONGNAM_UNRESOLVED') OR venue_code IS NULL",
         "(issue_domain, event_key, source row)", "event_date",
         "Unresolved/null venue records must remain available to later adjudication."),

    spec("section_points_adjudicated_sqlite", "finish_and_result_rows", "finish_time",
         "SELECT meet_code meet, CAST(race_date AS TEXT) event_date, CAST(race_number AS TEXT)||':'||CAST(horse_number AS TEXT)||':'||CAST(kra_horse_id AS TEXT) source_key FROM finish_time WHERE meet_code IN (1,3,4)",
         "(meet_code, race_date, race_number, kra_horse_id); horse_number cross-check", "race_date",
         "Only completed-result coverage in this table; it is not a complete starter roster."),
    spec("section_points_adjudicated_sqlite", "sectional_time_rows", "section_time",
         "SELECT meet_code meet, CAST(race_date AS TEXT) event_date, CAST(race_number AS TEXT)||':'||CAST(kra_horse_id AS TEXT)||':'||point_code||':'||time_kind||':'||CAST(id AS TEXT) source_key FROM section_time WHERE meet_code IN (1,3,4)",
         "source row ID; natural candidate (meet, date, race, horse ID, point, time_kind)", "race_date",
         "Cumulative, closing and segment times must not be merged without semantic evidence."),
    spec("section_points_adjudicated_sqlite", "point_positions", "point_position",
         "SELECT f.meet_code meet, CAST(f.race_date AS TEXT) event_date, CAST(f.race_number AS TEXT)||':'||CAST(f.kra_horse_id AS TEXT)||':'||p.point_code source_key FROM point_position p LEFT JOIN finish_time f ON f.race_entry_id=p.race_entry_id WHERE f.meet_code IN (1,3,4)",
         "(race_entry_id, point_code)", "via finish_time.race_date",
         "Position/call data is not the same concept as race-level passing group notation."),
    spec("section_points_adjudicated_sqlite", "canonical_points", "common_point",
         "SELECT meet_code meet, CAST(race_date AS TEXT) event_date, CAST(race_number AS TEXT)||':'||CAST(kra_horse_id AS TEXT)||':'||point_code||':'||time_kind source_key FROM common_point WHERE meet_code IN (1,3,4)",
         "(meet_code, date, race, horse ID, point code, time kind)", "race_date",
         "Adjudicated view only; retain source rows and quality/exclusion statuses alongside."),

    spec("research_dataset_v1_duckdb", "race_schedule_and_result", "race",
         "SELECT canonical_meet meet, CAST(race_date AS VARCHAR) event_date, CAST(race_no AS VARCHAR) source_key FROM race WHERE canonical_meet IN (1,3,4)",
         "(venue_code, race_date, race_no)", "race_date",
         "2010+ research snapshot assembled from historical unified plus operational refresh; not an adjudicated final core."),
    spec("research_dataset_v1_duckdb", "race_entries_and_results", "entry_result",
         "SELECT canonical_meet meet, CAST(race_date AS VARCHAR) event_date, CAST(race_no AS VARCHAR)||':'||CAST(chul_no AS VARCHAR) source_key FROM entry_result WHERE canonical_meet IN (1,3,4)",
         "(venue_code, race_date, race_no, chul_no); hr_no cross-check", "race_date",
         "Some runner rows do not join to section DB finish_time; preserve all result states."),
    spec("research_dataset_v1_duckdb", "trial_entries", "trial_entry",
         "SELECT canonical_meet meet, CAST(trial_date AS VARCHAR) event_date, CAST(trial_no AS VARCHAR)||':'||CAST(participant_no AS VARCHAR) source_key FROM trial_entry WHERE canonical_meet IN (1,3,4) OR venue_resolution_status='unresolved_after_yeongcheon_split'",
         "(trial event, participant number, source meet)", "trial_date",
         "Legacy-derived only in v1; not reconciled as separate schedule and result source tables."),
    spec("research_dataset_v1_duckdb", "daily_and_start_training", "training_event",
         "SELECT CASE training_venue_code WHEN 'SEOUL' THEN 1 WHEN 'BUSAN' THEN 3 WHEN 'YEONGCHEON' THEN 4 END meet, CAST(event_date AS VARCHAR) event_date, CAST(training_event_id AS VARCHAR) source_key FROM training_event WHERE training_venue_code IN ('SEOUL','BUSAN','YEONGCHEON') OR source_meet IN (1,3,4)",
         "training_event_id", "event_date",
         "Latest v1 training snapshot is earlier than the operational table; test observed-time eligibility."),
    spec("research_dataset_v1_duckdb", "medical_events", "medical_event",
         "SELECT CASE source_venue_code WHEN 'SEOUL' THEN 1 WHEN 'BUSAN' THEN 3 WHEN 'YEONGCHEON' THEN 4 END meet, CAST(event_date AS VARCHAR) event_date, CAST(medical_event_id AS VARCHAR) source_key FROM medical_event WHERE source_venue_code IN ('SEOUL','BUSAN','YEONGCHEON') OR source_meet IN (1,3,4)",
         "medical_event_id", "event_date", "Source type and identity-resolution status are essential."),
    spec("research_dataset_v1_duckdb", "unresolved_identity", "unresolved_identity_ledger",
         "SELECT CASE venue_code WHEN 'SEOUL' THEN 1 WHEN 'BUSAN' THEN 3 WHEN 'YEONGCHEON' THEN 4 END meet, CAST(event_date AS VARCHAR) event_date, CAST(issue_domain AS VARCHAR)||':'||CAST(event_key AS VARCHAR)||':'||CAST(source_row AS VARCHAR) source_key FROM unresolved_identity_ledger WHERE venue_code IN ('SEOUL','BUSAN','YEONGCHEON','YEONGNAM_UNRESOLVED') OR venue_code IS NULL",
         "issue domain/event key/source row", "event_date", "Do not resolve or drop identities based on name alone."),

    spec("section_passing_raw_duckdb", "section_finish_raw", "spdb_finish_time",
         "SELECT meet_code meet, CAST(race_date AS VARCHAR) event_date, CAST(race_number AS VARCHAR)||':'||CAST(kra_horse_id AS VARCHAR)||':'||CAST(horse_number AS VARCHAR) source_key FROM spdb_finish_time WHERE meet_code IN (1,3,4)",
         "source table original key columns", "race_date", "Raw adjudicated-source rows; preserved source columns."),
    spec("section_passing_raw_duckdb", "section_time_raw", "spdb_section_time",
         "SELECT meet_code meet, CAST(race_date AS VARCHAR) event_date, CAST(race_number AS VARCHAR)||':'||CAST(kra_horse_id AS VARCHAR)||':'||point_code||':'||time_kind||':'||CAST(id AS VARCHAR) source_key FROM spdb_section_time WHERE meet_code IN (1,3,4)",
         "source table id and natural event key", "race_date", "Raw section values; time semantics remain source-specific."),
    spec("section_passing_raw_duckdb", "passing_groups", "op_race_passing_groups",
         "SELECT c.meet_code meet, CAST(c.race_date AS VARCHAR) event_date, CAST(g.race_id AS VARCHAR)||':'||g.point_code source_key FROM op_race_passing_groups g JOIN op_race_context c ON c.race_id=g.race_id WHERE c.meet_code IN (1,3,4)",
         "(race_id, point_code)", "op_race_context.race_date", "Race-level group notation, not horse-level passing order."),
    spec("section_passing_raw_duckdb", "passing_summaries", "op_race_passing_summaries",
         "SELECT c.meet_code meet, CAST(c.race_date AS VARCHAR) event_date, CAST(p.race_id AS VARCHAR)||':'||CAST(p.id AS VARCHAR) source_key FROM op_race_passing_summaries p JOIN op_race_context c ON c.race_id=p.race_id WHERE c.meet_code IN (1,3,4)",
         "source summary ID/race_id", "op_race_context.race_date", "Race-level summaries; observed_at_ms is separate from race date."),
    spec("section_passing_raw_duckdb", "section_results_raw", "op_race_section_results",
         "SELECT e.meet_code meet, CAST(e.race_date AS VARCHAR) event_date, CAST(s.race_entry_id AS VARCHAR)||':'||s.section_code source_key FROM op_race_section_results s JOIN op_entry_context e ON e.race_entry_id=s.race_entry_id WHERE e.meet_code IN (1,3,4)",
         "(race_entry_id, section_code)", "op_entry_context.race_date", "Distinct from normalized point/time records."),
    spec("section_passing_raw_duckdb", "section_times_raw", "op_race_section_times",
         "SELECT e.meet_code meet, CAST(e.race_date AS VARCHAR) event_date, CAST(s.race_entry_id AS VARCHAR)||':'||s.point_code||':'||s.time_kind source_key FROM op_race_section_times s JOIN op_entry_context e ON e.race_entry_id=s.race_entry_id WHERE e.meet_code IN (1,3,4)",
         "(race_entry_id, point_code, time_kind)", "op_entry_context.race_date", "Retain source field/batch; bridge identity match is separately validated."),
]


def open_source(name: str, path: Path):
    if not path.is_file():
        raise FileNotFoundError(f"Required read-only source missing: {path}")
    if path.suffix == ".duckdb":
        return duckdb.connect(str(path), read_only=True), "duckdb"
    con = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    con.execute("PRAGMA query_only=ON")
    return con, "sqlite"


def table_exists(con, kind: str, name: str) -> bool:
    if kind == "sqlite":
        return con.execute("SELECT 1 FROM sqlite_master WHERE name=? AND type IN ('table','view')", (name,)).fetchone() is not None
    return con.execute("SELECT 1 FROM information_schema.tables WHERE table_schema='main' AND table_name=?", [name]).fetchone() is not None


def table_columns(con, kind: str, name: str) -> list[str]:
    if kind == "sqlite":
        return [r[1] for r in con.execute(f'PRAGMA table_info("{name}")').fetchall()]
    return [r[0] for r in con.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='main' AND table_name=? ORDER BY ordinal_position", [name]).fetchall()]


def query_rows(con, sql: str, params=()) -> list[tuple]:
    return con.execute(sql, params).fetchall()


def inventory_one(con, kind: str, s: dict[str, str]) -> dict[str, Any]:
    # One grouped pass per source table supplies both annual and meet coverage.
    base = f"WITH src AS ({s['sql']}) "
    grouped = query_rows(con, base + "SELECT meet, CASE WHEN event_date IS NULL THEN NULL ELSE SUBSTR(event_date,1,4) END year_key, COUNT(*), MIN(event_date), MAX(event_date), SUM(CASE WHEN event_date <= ? THEN 1 ELSE 0 END), SUM(CASE WHEN event_date > ? THEN 1 ELSE 0 END), SUM(CASE WHEN event_date IS NULL THEN 1 ELSE 0 END) FROM src GROUP BY 1,2 ORDER BY 1,2", (TARGET_END, TARGET_END))
    row_count = sum(int(r[2]) for r in grouped)
    first_values = [r[3] for r in grouped if r[3] is not None]
    last_values = [r[4] for r in grouped if r[4] is not None]
    first = min(first_values) if first_values else None
    last = max(last_values) if last_values else None
    cutoff_rows = sum(int(r[5] or 0) for r in grouped)
    after_cutoff = sum(int(r[6] or 0) for r in grouped)
    null_dates = sum(int(r[7] or 0) for r in grouped)
    years_map: dict[str, int] = defaultdict(int)
    meet_map: dict[Any, dict[str, Any]] = {}
    for meet, year, count, lo, hi, within, after, nulls in grouped:
        if year is not None and int(year) <= int(TARGET_END[:4]):
            years_map[str(year)] += int(within or 0)
        mkey = "unassigned" if meet is None else int(meet)
        m = meet_map.setdefault(mkey, {"meet": mkey, "rows": 0, "first": None, "last": None})
        m["rows"] += int(count)
        if lo is not None:
            m["first"] = lo if m["first"] is None else min(m["first"], lo)
        if hi is not None:
            m["last"] = hi if m["last"] is None else max(m["last"], hi)
    years = sorted(years_map.items())
    by_meet = list(meet_map.values())
    year_sum = sum(n for _, n in years)
    if year_sum != int(cutoff_rows):
        raise AssertionError(f"Annual counts do not sum for {s['source']}.{s['table']}: {year_sum} != {cutoff_rows}")
    return {
        "source": s["source"], "domain": s["domain"], "table": s["table"],
        "columns": table_columns(con, kind, s["table"]),
        "key_candidate": s["key_candidate"], "major_date_field": s["date_field"], "date_role": s.get("date_role", "event_date"),
        "rows_in_source_scope": int(row_count), "earliest_event_date": first,
        "latest_event_date": last, "rows_on_or_before_target_cutoff": int(cutoff_rows),
        "target_cutoff": TARGET_END, "rows_after_target_cutoff": int(after_cutoff or 0),
        "rows_without_event_date": int(null_dates or 0),
        "annual_rows_through_cutoff": {str(y): int(n) for y, n in years},
        "annual_sum_check": {"sum": int(year_sum), "equals_cutoff_rows": year_sum == int(cutoff_rows)},
        "coverage_by_meet": sorted(by_meet, key=lambda x: str(x["meet"])),
        "risk": s["risk"],
    }


def venue_from_meet(meet: Any) -> str | None:
    try:
        return {1: "SEOUL", 3: "BUSAN", 4: "YEONGCHEON"}.get(int(meet))
    except (ValueError, TypeError):
        return None


def race_keys(con, kind: str, source: str, period: str) -> set[tuple]:
    if source == "operational_sqlite":
        sql = "SELECT rc.kra_meet_code,r.race_date_local,r.race_number,NULL,NULL FROM races r JOIN racecourses rc ON rc.id=r.racecourse_id WHERE rc.kra_meet_code IN (1,3,4)"
        date_i, meet_i, no_i = 1, 0, 2
    elif source == "historical_unified_duckdb":
        sql = "SELECT CASE venue_code WHEN 'SEOUL' THEN 1 WHEN 'BUSAN' THEN 3 WHEN 'YEONGCHEON' THEN 4 END,race_date,race_no,NULL,NULL FROM race WHERE venue_code IN ('SEOUL','BUSAN','YEONGCHEON')"
        date_i, meet_i, no_i = 1, 0, 2
    else:
        sql = "SELECT canonical_meet,race_date,race_no,NULL,NULL FROM race WHERE canonical_meet IN (1,3,4)"
        date_i, meet_i, no_i = 1, 0, 2
    rows = con.execute(sql).fetchall()
    result = set()
    for r in rows:
        day = str(r[date_i])[:10]
        if day > TARGET_END:
            continue
        if period == "pre_2010" and day >= "2010-01-01":
            continue
        if period == "2010_plus" and day < "2010-01-01":
            continue
        venue = venue_from_meet(r[meet_i])
        if venue:
            result.add((venue, day, int(r[no_i])))
    return result


def entry_keys(con, source: str, period: str) -> dict[tuple, str | None]:
    if source == "operational_sqlite":
        sql = "SELECT rc.kra_meet_code,r.race_date_local,r.race_number,e.horse_number,h.kra_horse_id FROM race_entries e JOIN races r ON r.id=e.race_id JOIN racecourses rc ON rc.id=r.racecourse_id JOIN horses h ON h.id=e.horse_id WHERE rc.kra_meet_code IN (1,3,4)"
    elif source == "historical_unified_duckdb":
        sql = "SELECT CASE venue_code WHEN 'SEOUL' THEN 1 WHEN 'BUSAN' THEN 3 WHEN 'YEONGCHEON' THEN 4 END,race_date,race_no,chul_no,hr_no FROM entry_result WHERE venue_code IN ('SEOUL','BUSAN','YEONGCHEON')"
    else:
        sql = "SELECT canonical_meet,race_date,race_no,chul_no,hr_no FROM entry_result WHERE canonical_meet IN (1,3,4)"
    result = {}
    for meet, day0, no, horse_no, hr_no in con.execute(sql).fetchall():
        day = str(day0)[:10]
        if day > TARGET_END or (period == "pre_2010" and day >= "2010-01-01") or (period == "2010_plus" and day < "2010-01-01"):
            continue
        venue = venue_from_meet(meet)
        if venue and horse_no is not None:
            key = (venue, day, int(no), int(horse_no))
            result[key] = str(hr_no).strip().zfill(7) if hr_no else None
    return result


def compare_sets(left: set | dict, right: set | dict) -> dict[str, Any]:
    lk, rk = set(left), set(right)
    result: dict[str, Any] = {
        "left_count": len(lk), "right_count": len(rk), "matched": len(lk & rk),
        "left_only": len(lk - rk), "right_only": len(rk - lk),
        "left_only_sample": [list(x) for x in sorted(lk - rk)[:20]],
        "right_only_sample": [list(x) for x in sorted(rk - lk)[:20]],
    }
    if isinstance(left, dict) and isinstance(right, dict):
        conflicts = [k for k in lk & rk if left[k] and right[k] and left[k] != right[k]]
        result["shared_entry_horse_id_conflicts"] = len(conflicts)
        result["horse_id_conflict_sample"] = [list(k) + [left[k], right[k]] for k in conflicts[:20]]
    return result


def comparison(connections: dict[str, Any]) -> dict[str, Any]:
    periods = {
        "pre_2010": {"start": "source_start", "end": "2009-12-31"},
        "2010_plus": {"start": "2010-01-01", "end": TARGET_END},
    }
    sources = ["operational_sqlite", "historical_unified_duckdb", "research_dataset_v1_duckdb"]
    out: dict[str, Any] = {"basis": "natural race key (venue,date,race_no); entry key adds horse_number", "periods": {}}
    for period, bounds in periods.items():
        races = {name: race_keys(connections[name][0], connections[name][1], name, period) for name in sources}
        entries = {name: entry_keys(connections[name][0], name, period) for name in sources}
        ref = "operational_sqlite"
        out["periods"][period] = {
            "date_range": bounds,
            "races": {name: {"unique_keys": len(races[name]), **compare_sets(races[name], races[ref])} for name in sources if name != ref},
            "entries": {name: {"unique_keys": len(entries[name]), **compare_sets(entries[name], entries[ref])} for name in sources if name != ref},
            "note": "Counts and differences are descriptive only. This report assigns no source priority or correctness ranking.",
        }
    return out


def operational_status(con) -> dict[str, Any]:
    status_counts = con.execute("SELECT rc.kra_meet_code, r.status, COUNT(*) FROM races r JOIN racecourses rc ON rc.id=r.racecourse_id WHERE rc.kra_meet_code IN (1,3,4) GROUP BY 1,2 ORDER BY 1,2").fetchall()
    names = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()]
    related = [n for n in names if any(token in n.lower() for token in ("holiday", "calendar", "closure", "cancel"))]
    closure_csv = ROOT / "thoroughbred/research/20260929_closure_inventory_v1/closures.csv"
    closure_validation = ROOT / "thoroughbred/research/20260929_closure_inventory_v1/validation.json"
    closure_summary: dict[str, Any]
    if closure_csv.is_file() and closure_validation.is_file():
        with closure_csv.open(newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        validation = json.loads(closure_validation.read_text(encoding="utf-8"))
        closure_summary = {
            "status": "verified_partial_official_plan_list",
            "csv_path": str(closure_csv.relative_to(ROOT)),
            "validation_path": str(closure_validation.relative_to(ROOT)),
            "source_rows": len(rows),
            "rows_by_meet": {str(k): int(v) for k, v in validation.get("rows_by_meet", {}).items()},
            "rows_by_year": {str(k): int(v) for k, v in validation.get("rows_by_year", {}).items()},
            "race_rows_inside_closures": int(validation.get("race_rows_inside_closures", -1)),
            "conflicts": validation.get("conflicts", []),
            "cutoff": validation.get("cutoff"),
            "is_complete_historical_calendar": False,
            "evidence": "official annual/revised racing plans; 50 Seoul/Busan-Gyeongnam interval rows",
        }
        if closure_summary["source_rows"] != int(validation.get("source_rows", -1)):
            raise AssertionError("Closure CSV and its validation.json row counts differ")
        if closure_summary["race_rows_inside_closures"] != 0 or closure_summary["conflicts"]:
            raise AssertionError("Official closure list has a race-row conflict; inspect its validation.json")
    else:
        closure_summary = {"status": "not_found"}
    return {
        "race_status_counts_by_meet": [{"meet": int(m), "status": str(s), "rows": int(n)} for m, s, n in status_counts],
        "table_names_matching_holiday_calendar_closure_cancel": related,
        "separate_official_closure_evidence": closure_summary,
        "interpretation": "A local partial official closure-plan list is linked above; it is not a complete historical calendar. An explicit cancelled/void race row/status may be retained as evidence. No meeting row/entries alone does not prove a scheduled closure or holiday.",
    }


def raw_file_inventory() -> dict[str, Any]:
    raw_root = ROOT / "data/raw"
    if not raw_root.is_dir():
        return {"status": "raw_directory_not_found", "path": "data/raw"}
    counts: dict[str, int] = defaultdict(int)
    sizes: dict[str, int] = defaultdict(int)
    total_count = total_bytes = 0
    for dirpath, _, filenames in os.walk(raw_root, followlinks=False):
        base = Path(dirpath)
        for filename in filenames:
            p = base / filename
            try:
                st = p.lstat()
            except OSError:
                continue
            if not stat.S_ISREG(st.st_mode):
                continue
            rel = p.relative_to(raw_root)
            family = rel.parts[0] if rel.parts else "unclassified"
            counts[family] += 1
            sizes[family] += st.st_size
            total_count += 1
            total_bytes += st.st_size
    return {
        "status": "file_metadata_only_no_content_or_hash_read",
        "path": "data/raw",
        "total_regular_files": total_count,
        "total_bytes": total_bytes,
        "families": {k: {"files": counts[k], "bytes": sizes[k]} for k in sorted(counts)},
        "scope_note": "File counts/sizes do not establish source dates, completeness, or whether each file is Thoroughbred/meet 1, 3 or 4; filename/content provenance remains unverified.",
    }


def identity_linkage(con) -> dict[str, Any]:
    race = con.execute("""
        SELECT rc.kra_meet_code, COUNT(*),
               SUM(CASE WHEN e.horse_id IS NULL THEN 1 ELSE 0 END),
               SUM(CASE WHEN e.jockey_id IS NULL THEN 1 ELSE 0 END),
               SUM(CASE WHEN e.trainer_id IS NULL THEN 1 ELSE 0 END),
               SUM(CASE WHEN e.owner_id IS NULL THEN 1 ELSE 0 END)
        FROM race_entries e JOIN races r ON r.id=e.race_id
        JOIN racecourses rc ON rc.id=r.racecourse_id
        WHERE rc.kra_meet_code IN (1,3,4) AND r.race_date_local <= ?
        GROUP BY rc.kra_meet_code ORDER BY rc.kra_meet_code
    """, (TARGET_END,)).fetchall()
    trials = con.execute("""
        SELECT t.meet_code, COUNT(*),
               SUM(CASE WHEN x.horse_id IS NULL THEN 1 ELSE 0 END),
               SUM(CASE WHEN x.jockey_id IS NULL THEN 1 ELSE 0 END),
               SUM(CASE WHEN x.trainer_id IS NULL THEN 1 ELSE 0 END)
        FROM running_trial_results x JOIN running_trials t ON t.id=x.running_trial_id
        WHERE t.meet_code IN (1,3,4) AND t.trial_date_local <= ?
        GROUP BY t.meet_code ORDER BY t.meet_code
    """, (TARGET_END,)).fetchall()
    hill = con.execute("SELECT COUNT(*), SUM(CASE WHEN horse_id IS NULL THEN 1 ELSE 0 END) FROM horse_hill_training").fetchone()
    return {
        "scope_cutoff": TARGET_END,
        "race_entry_linkage_by_meet": [{"meet": int(r[0]), "rows": int(r[1]), "horse_id_null": int(r[2] or 0), "jockey_id_null": int(r[3] or 0), "trainer_id_null": int(r[4] or 0), "owner_id_null": int(r[5] or 0)} for r in race],
        "trial_entry_linkage_by_meet": [{"meet": int(r[0]), "rows": int(r[1]), "horse_id_null": int(r[2] or 0), "jockey_id_null": int(r[3] or 0), "trainer_id_null": int(r[4] or 0)} for r in trials],
        "hill_training": {"rows": int(hill[0]), "horse_id_null": int(hill[1] or 0), "venue_key_available": False},
        "entity_master_date_note": "Master rows without event/observation date are counted as reference inventories; zero rows on/before cutoff means date is not applicable, not that the entity data is unusable.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replace-output", action="store_true", help="replace this script's generated JSON outputs after all checks pass")
    args = parser.parse_args()
    output_paths = [OUT / "inventory.json", OUT / "reconciliation.json"]
    if not args.replace_output and any(path.exists() for path in output_paths):
        raise FileExistsError(f"Refusing to overwrite existing inventory output in {OUT}")
    connections = {}
    try:
        for name, path in SOURCE_FILES.items():
            con, kind = open_source(name, path)
            connections[name] = (con, kind)
        inventories = []
        for s in SPECS:
            con, kind = connections[s["source"]]
            if not table_exists(con, kind, s["table"]):
                inventories.append({"source": s["source"], "domain": s["domain"], "table": s["table"], "status": "table_not_present", "key_candidate": s["key_candidate"], "major_date_field": s["date_field"], "risk": s["risk"]})
                continue
            inventories.append(inventory_one(con, kind, s))

        source_meta = {}
        for name, path in SOURCE_FILES.items():
            stat = path.stat()
            source_meta[name] = {"path": str(path.relative_to(ROOT)), "bytes": stat.st_size,
                                 "modified_local": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                                 "open_mode": "read_only"}

        result = {
            "inventory_version": "2026-09-29-source-inventory-v1",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "scope": {"included_meets": {"1": "SEOUL", "3": "BUSAN_GYEONGNAM", "4": "YEONGCHEON"},
                      "excluded_meets": {"2": "JEJU"}, "target_event_date_cutoff": TARGET_END,
                      "model_start_date": MODEL_START,
                      "history_policy": "Preserve each source from its observed first record through the target cutoff; pre-2017 race rows are history only. Preserve event date separately from published/observed/ingested timestamps."},
            "sources": source_meta,
            "table_inventory": inventories,
            "calendar_and_cancellation_evidence": operational_status(connections["operational_sqlite"][0]),
            "identity_linkage_risks": identity_linkage(connections["operational_sqlite"][0]),
            "raw_file_tree_inventory": raw_file_inventory(),
            "validation": {
                "all_date_tables_annual_sums_checked": all(x.get("annual_sum_check", {}).get("equals_cutoff_rows", True) for x in inventories),
                "source_database_hashes": "not computed; broad file hashing intentionally avoided",
                "read_only": True,
            },
        }
        comp = comparison(connections)
        comp["sources"] = source_meta
        comp["target_cutoff"] = TARGET_END
        comp["validation"] = {"sets_use_unique_natural_keys": True, "source_priority_assigned": False}
        # Publish only after both products have been computed successfully.
        payloads = [json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n",
                    json.dumps(comp, ensure_ascii=False, indent=2, default=str) + "\n"]
        temp_paths = []
        try:
            for path, payload in zip(output_paths, payloads):
                tmp = path.with_name(path.name + ".tmp")
                tmp.write_text(payload, encoding="utf-8")
                temp_paths.append(tmp)
            for tmp, path in zip(temp_paths, output_paths):
                os.replace(tmp, path)
        finally:
            for tmp in temp_paths:
                if tmp.exists():
                    tmp.unlink()
        print(json.dumps({"inventory": str((OUT / "inventory.json").relative_to(ROOT)),
                          "reconciliation": str((OUT / "reconciliation.json").relative_to(ROOT)),
                          "table_specs": len(inventories),
                          "annual_sum_checks_passed": result["validation"]["all_date_tables_annual_sums_checked"]}, ensure_ascii=False))
    finally:
        for con, kind in connections.values():
            con.close()


if __name__ == "__main__":
    main()
