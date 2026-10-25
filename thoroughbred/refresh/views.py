"""Current research views over the immutable core and accepted refresh rows.

The builders here only emit SQL.  They do not open or mutate a database.  The
caller installs the views on the refresh database (normally a working copy of
the frozen core) after ``refresh_event_records`` has been created.  Existing
core tables and views are never renamed, dropped, or replaced by this module.

Baseline projections deliberately use the reviewed source relations named in
the inventory.  New rows are exposed only when their disposition is exactly
``accepted``; correction holds and exclusions stay queryable in the evidence
table but do not enter a current view.
"""

from __future__ import annotations

import re
from typing import Any


_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_WEIGHT_PATTERN = "^[[:space:]]*([1-9][0-9]*)[[:space:]]*([(]([+-]?[0-9]+)[)])?$"
_FAMILY_ORDER = (
    "race_schedule",
    "race_results",
    "passing_groups",
    "trial_results",
    "public_cards",
    "entry_sheets",
    "body_weights",
    "steward_reports",
    "sanctions",
    "daily_training",
    "start_training",
    "swim_training",
    "starting_exam",
    "medical",
    "horse_profile",
    "jockey_profile",
    "trainer_profile",
    "owner_profile",
)


def _id(value: str) -> str:
    """Quote only static identifiers after validating their allowlist shape."""
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"unsafe SQL identifier: {value!r}")
    return f'"{value}"'


def _date(expr: str) -> str:
    """Parse either an ISO date or the APIs' compact YYYYMMDD representation."""
    return (
        f"COALESCE(TRY_CAST(CAST({expr} AS VARCHAR) AS DATE), "
        f"TRY_CAST(TRY_STRPTIME(CAST({expr} AS VARCHAR), '%Y%m%d') AS DATE))"
    )


def _baseline_weight_component(expr: str, group: int, sql_type: str) -> str:
    """Parse one component only when the whole source string is a valid weight."""
    raw = f"regexp_extract(CAST({expr} AS VARCHAR), '{_WEIGHT_PATTERN}', {group})"
    if sql_type == "VARCHAR":
        value = f"NULLIF({raw}, '')"
    else:
        value = f"TRY_CAST({raw} AS {sql_type})"
    return (
        f"CASE WHEN regexp_full_match(CAST({expr} AS VARCHAR), '{_WEIGHT_PATTERN}') "
        f"THEN {value} END"
    )


def _json_field(alias: str, field: str, sql_type: str) -> str:
    """Read a known normalized JSON field and preserve nulls on bad values."""
    if field == "@equipment_field_present":
        raw = (
            f"CASE WHEN json_extract_string({alias}.fields_json, '$.equipment_value_state') "
            "= 'field_missing' THEN 'false' ELSE 'true' END"
        )
    elif field == "@equipment_is_null":
        raw = (
            f"CASE WHEN json_extract_string({alias}.fields_json, '$.equipment_value_state') "
            "= 'null' THEN 'true' ELSE 'false' END"
        )
    elif field == "@race_level_api303":
        raw = "'race_level_api303_record'"
    elif field == "@verified_existing_rider_name":
        rider_id = f"json_extract_string({alias}.fields_json, '$.rider_id')"
        raw = (
            "(SELECT CASE WHEN COUNT(*) = 1 THEN MAX(name_snapshot) END "
            f"FROM rider_name_links WHERE rider_id_raw = {rider_id})"
        )
    elif field == "@rider_identity_status":
        rider_id = f"NULLIF(TRIM(json_extract_string({alias}.fields_json, '$.rider_id')), '')"
        raw = (
            f"CASE WHEN {rider_id} IS NULL THEN '_pr_no_absent' "
            f"WHEN (SELECT COUNT(*) FROM rider_name_links WHERE rider_id_raw = {rider_id}) = 1 "
            "THEN '_exact_existing_official_id_name_link' "
            "ELSE '_profile_id_unmatched' END"
        )
    elif field.startswith("payload:"):
        payload_path = "$." + field.removeprefix("payload:")
        raw = f"json_extract_string({alias}.payload_json, '{payload_path}')"
    else:
        path = "$." + field
        raw = f"json_extract_string({alias}.fields_json, '{path}')"
    if sql_type == "VARCHAR":
        return raw
    return f"TRY_CAST({raw} AS {sql_type})"


# Each field entry is (name, SQL type, immutable-baseline expression,
# normalized-refresh JSON field).  All expressions and names are source-code
# constants; no captured data can become SQL text.
_FAMILIES: dict[str, dict[str, Any]] = {
    "race_schedule": {
        "relation": "race_plan_full_api",
        "row_id": "CAST(source_file AS VARCHAR) || '#' || CAST(source_item_index AS VARCHAR)",
        "event_date": _date("race_date_key"),
        "meet": "CAST(source_meet AS VARCHAR)",
        "race_no": "CAST(race_no_key AS VARCHAR)",
        "source_file": "source_file",
        "source_sha": "source_file_sha256",
        "source_row": "TRY_CAST(source_item_index AS BIGINT)",
        "captured_at": "NULL::VARCHAR",
        "availability": "NULL::VARCHAR",
        "payload": "source_record_json",
        "key_json": "NULL::VARCHAR",
        "fields": (
            ("race_distance_m", "INTEGER", "TRY_CAST(api_rcDist AS INTEGER)", "distance_m"),
            ("race_name", "VARCHAR", "api_rcName", "race_name_raw"),
            ("grade", "VARCHAR", "api_rank", "grade_raw"),
            ("scheduled_start_raw", "VARCHAR", "api_schStTime", "scheduled_start_raw"),
            ("age_condition", "VARCHAR", "api_ageCond", "age_condition"),
            ("sex_condition", "VARCHAR", "api_sexCond", "sex_condition"),
            ("start_rating", "VARCHAR", "api_stRating", "start_rating"),
            ("speed_rating", "VARCHAR", "api_spRating", "speed_rating"),
            ("race_status_raw", "VARCHAR", "api_ilsu", "race_status_raw"),
        ),
    },
    "race_results": {
        "relation": "confirmed_runners",
        "row_id": "CAST(source_file AS VARCHAR) || '#' || CAST(source_item_index AS VARCHAR)",
        "event_date": _date("result_date"),
        "meet": "CAST(source_meet AS VARCHAR)",
        "race_no": "CAST(result_race_no AS VARCHAR)",
        "horse_id": "horse_id_raw",
        "horse_no": "TRY_CAST(horse_program_no_raw AS INTEGER)",
        "source_file": "source_file",
        "source_sha": "NULL::VARCHAR",
        "source_row": "TRY_CAST(source_item_index AS BIGINT)",
        "captured_at": "NULL::VARCHAR",
        "availability": "execution_status",
        "payload": "NULL::VARCHAR",
        "key_json": "NULL::VARCHAR",
        "fields": (
            ("horse_name", "VARCHAR", "horse_name_raw", "horse_name_raw"),
            ("horse_name_en", "VARCHAR", "horse_name_en_raw", "horse_name_en_raw"),
            ("horse_age", "INTEGER", "TRY_CAST(horse_age_raw AS INTEGER)", "payload:age"),
            ("horse_sex", "VARCHAR", "horse_sex_raw", "payload:sex"),
            ("horse_origin", "VARCHAR", "horse_origin_raw", "payload:name"),
            ("jockey_id", "VARCHAR", "jockey_id_raw", "jockey_id_raw"),
            ("jockey_name", "VARCHAR", "jockey_name_raw", "jockey_name_raw"),
            ("trainer_id", "VARCHAR", "trainer_id_raw", "trainer_id_raw"),
            ("trainer_name", "VARCHAR", "trainer_name_raw", "trainer_name_raw"),
            ("owner_id", "VARCHAR", "owner_id_raw", "payload:owNo"),
            ("owner_name", "VARCHAR", "owner_name_raw", "payload:owName"),
            ("finish_position", "INTEGER", "TRY_CAST(result_rank_raw AS INTEGER)", "result_rank"),
            ("finish_time_seconds", "DOUBLE", "TRY_CAST(finish_time_seconds_raw AS DOUBLE)", "finish_time"),
            ("finish_time_raw", "VARCHAR", "finish_time_seconds_raw", "finish_time_raw"),
            ("finish_margin_raw", "VARCHAR", "finish_margin_raw", "finish_margin_raw"),
            ("carried_weight_kg", "DOUBLE", "TRY_CAST(carried_weight_raw AS DOUBLE)", "carried_weight_kg"),
            ("carried_weight_raw", "VARCHAR", "carried_weight_raw", "carried_weight_raw"),
            ("horse_weight_kg", "DOUBLE", _baseline_weight_component("horse_weight_raw", 1, "DOUBLE"), "horse_weight_kg"),
            ("horse_weight_raw", "VARCHAR", "horse_weight_raw", "horse_weight_raw"),
            ("body_weight_change_kg", "DOUBLE", _baseline_weight_component("horse_weight_raw", 3, "DOUBLE"), "body_weight_change"),
            ("body_weight_change_raw", "VARCHAR", _baseline_weight_component("horse_weight_raw", 3, "VARCHAR"), "body_weight_change_raw"),
            ("win_odds", "DOUBLE", "TRY_CAST(odds_win_raw AS DOUBLE)", "win_odds"),
            ("place_odds", "DOUBLE", "TRY_CAST(odds_place_raw AS DOUBLE)", "place_odds"),
            ("race_distance_m", "INTEGER", "TRY_CAST(race_distance_m_raw AS INTEGER)", "distance_m"),
            ("race_name", "VARCHAR", "race_name_raw", "race_name_raw"),
            ("grade", "VARCHAR", "grade_raw", "grade_raw"),
            ("track_condition", "VARCHAR", "track_condition_raw", "track_condition_raw"),
            ("weather", "VARCHAR", "weather_raw", "weather_raw"),
        ),
    },
    "passing_groups": {
        "relation": "race_passing_groups",
        "row_id": "CAST(actual_meet_code AS VARCHAR) || '#' || CAST(event_date AS VARCHAR) || '#' || CAST(race_no AS VARCHAR) || '#' || COALESCE(canonical_point_code, '')",
        "event_date": _date("event_date"),
        "meet": "CAST(actual_meet_code AS VARCHAR)",
        "race_no": "CAST(race_no AS VARCHAR)",
        "source_file": "NULL::VARCHAR",
        "source_sha": "NULL::VARCHAR",
        "source_row": "NULL::BIGINT",
        "captured_at": "NULL::VARCHAR",
        "availability": "selection_status",
        "payload": "to_json(struct_pack(api_notation_values := api_notation_values_json, api_source_paths := api_source_paths_json, rpt_notation_values := rpt_notation_values_json, rpt_source_paths := rpt_source_paths_json))",
        "key_json": "NULL::VARCHAR",
        "fields": (
            ("canonical_point_code", "VARCHAR", "canonical_point_code", "canonical_point_code"),
            ("notation_raw", "VARCHAR", "notation_raw", "notation_raw"),
            ("selected_source", "VARCHAR", "selected_source", "selected_source"),
            ("selection_status", "VARCHAR", "selection_status", "selection_status"),
            ("record_granularity", "VARCHAR", "'reviewed_canonical_point'", "@race_level_api303"),
            ("passing_group_values_raw", "VARCHAR", "CAST(api_notation_values_json AS VARCHAR)", "passing_group_values_raw"),
        ),
    },
    "trial_results": {
        "relation": "trial_participants_entity_reviewed",
        "row_id": "participant_row_id",
        "event_date": _date("trial_date"),
        "meet": "CASE WHEN lower(CAST(api_meet AS VARCHAR)) IN ('1','서울') THEN '1' WHEN lower(CAST(api_meet AS VARCHAR)) IN ('3','부산','부경','부산경남','영남') THEN '3' WHEN lower(CAST(api_meet AS VARCHAR)) IN ('4','영천') THEN '4' ELSE CAST(api_meet AS VARCHAR) END",
        "race_no": "NULL::VARCHAR",
        "trial_no": "CAST(trial_no AS VARCHAR)",
        "horse_id": "COALESCE(resolved_horse_id, horse_id)",
        "horse_no": "TRY_CAST(api_chulNo AS INTEGER)",
        "source_file": "source_file",
        "source_sha": "source_file_sha256",
        "source_row": "TRY_CAST(source_item_index AS BIGINT)",
        "captured_at": "NULL::VARCHAR",
        "availability": "horse_identity_resolution",
        "payload": "source_record_json",
        "key_json": "NULL::VARCHAR",
        "fields": (
            ("trial_time_seconds", "DOUBLE", "TRY_CAST(api_rcTime AS DOUBLE)", "trial_time"),
            ("horse_name", "VARCHAR", "COALESCE(resolved_horse_name, horse_name)", "horse_name_raw"),
            ("jockey_id", "VARCHAR", "jockey_id_for_completed_trial", "jockey_id_raw"),
            ("jockey_name", "VARCHAR", "jockey_name_with_review", "jockey_name_raw"),
            ("trainer_id", "VARCHAR", "trainer_entity_id_with_review", "trainer_id_raw"),
            ("trainer_name", "VARCHAR", "trainer_name_with_review", "trainer_name_raw"),
            ("program_no", "INTEGER", "TRY_CAST(api_chulNo AS INTEGER)", "horse_no"),
            ("finish_position", "INTEGER", "TRY_CAST(api_ord AS INTEGER)", "result_rank"),
            ("pass_flag", "VARCHAR", "api_passFlag", "pass_flag"),
            ("track", "VARCHAR", "api_track", "track_condition_raw"),
            ("weather", "VARCHAR", "api_weather", "weather_raw"),
            ("horse_weight_kg", "DOUBLE", "TRY_CAST(api_wgHr AS DOUBLE)", "horse_weight_kg"),
        ),
    },
    "public_cards": {
        "relation": "equipment_api78_latest_card_observations",
        "row_id": "observation_id",
        "event_date": _date("event_date"),
        "meet": "CAST(meet AS VARCHAR)",
        "race_no": "CAST(race_no AS VARCHAR)",
        "horse_id": "linked_core_horse_id",
        "horse_no": "TRY_CAST(horse_no AS INTEGER)",
        "source_file": "COALESCE(source_document_path, source_document_ref)",
        "source_sha": "source_sha256",
        "source_row": "TRY_CAST(source_index_in_batch AS BIGINT)",
        "captured_at": "capture_retrieved_at_kst",
        "availability": "availability_status",
        "payload": "to_json(struct_pack(api_horse_name_raw := api_horse_name_raw, equipment_raw := equipment_raw, equipment_field_present := equipment_field_present, equipment_is_null := equipment_is_null, equipment_value_state := equipment_value_state, physical_wear_status := physical_wear_status, link_status := link_status))",
        "key_json": "NULL::VARCHAR",
        "fields": (
            ("horse_name", "VARCHAR", "api_horse_name_raw", "horse_name_raw"),
            ("equipment_raw", "VARCHAR", "equipment_raw", "equipment_raw"),
            ("equipment_field_present", "BOOLEAN", "equipment_field_present", "@equipment_field_present"),
            ("equipment_is_null", "BOOLEAN", "equipment_is_null", "@equipment_is_null"),
            ("equipment_value_state", "VARCHAR", "equipment_value_state", "equipment_value_state"),
            ("equipment_field_state", "VARCHAR", "equipment_field_state", "equipment_field_state"),
            ("physical_wear_status", "VARCHAR", "physical_wear_status", "physical_wear_status"),
            ("link_status", "VARCHAR", "link_status", "link_status"),
            ("link_method", "VARCHAR", "link_method", "link_method"),
            ("link_reason", "VARCHAR", "link_reason", "link_reason"),
        ),
    },
    "entry_sheets": {
        "relation": None,
        "fields": (
            ("horse_name", "VARCHAR", "NULL::VARCHAR", "horse_name_raw"),
            ("jockey_id", "VARCHAR", "NULL::VARCHAR", "jockey_id_raw"),
            ("jockey_name", "VARCHAR", "NULL::VARCHAR", "jockey_name_raw"),
            ("trainer_id", "VARCHAR", "NULL::VARCHAR", "trainer_id_raw"),
            ("trainer_name", "VARCHAR", "NULL::VARCHAR", "trainer_name_raw"),
            ("horse_weight_kg", "DOUBLE", "NULL::DOUBLE", "horse_weight_kg"),
            ("horse_weight_raw", "VARCHAR", "NULL::VARCHAR", "horse_weight_raw"),
            ("body_weight_change_kg", "DOUBLE", "NULL::DOUBLE", "body_weight_change"),
            ("body_weight_change_raw", "VARCHAR", "NULL::VARCHAR", "body_weight_change_raw"),
            ("carried_weight_kg", "DOUBLE", "NULL::DOUBLE", "carried_weight_kg"),
            ("carried_weight_raw", "VARCHAR", "NULL::VARCHAR", "carried_weight_raw"),
            ("win_odds", "DOUBLE", "NULL::DOUBLE", "win_odds"),
            ("place_odds", "DOUBLE", "NULL::DOUBLE", "place_odds"),
            ("race_name", "VARCHAR", "NULL::VARCHAR", "race_name_raw"),
            ("race_distance_m", "INTEGER", "NULL::INTEGER", "distance_m"),
            ("grade", "VARCHAR", "NULL::VARCHAR", "grade_raw"),
        ),
    },
    "body_weights": {
        "relation": None,
        "fields": (
            ("horse_name", "VARCHAR", "NULL::VARCHAR", "horse_name_raw"),
            ("jockey_id", "VARCHAR", "NULL::VARCHAR", "jockey_id_raw"),
            ("jockey_name", "VARCHAR", "NULL::VARCHAR", "jockey_name_raw"),
            ("trainer_id", "VARCHAR", "NULL::VARCHAR", "trainer_id_raw"),
            ("trainer_name", "VARCHAR", "NULL::VARCHAR", "trainer_name_raw"),
            ("horse_weight_kg", "DOUBLE", "NULL::DOUBLE", "horse_weight_kg"),
            ("horse_weight_raw", "VARCHAR", "NULL::VARCHAR", "horse_weight_raw"),
            ("body_weight_change_kg", "DOUBLE", "NULL::DOUBLE", "body_weight_change"),
            ("body_weight_change_raw", "VARCHAR", "NULL::VARCHAR", "body_weight_change_raw"),
            ("carried_weight_kg", "DOUBLE", "NULL::DOUBLE", "carried_weight_kg"),
            ("carried_weight_raw", "VARCHAR", "NULL::VARCHAR", "carried_weight_raw"),
            ("win_odds", "DOUBLE", "NULL::DOUBLE", "win_odds"),
            ("place_odds", "DOUBLE", "NULL::DOUBLE", "place_odds"),
            ("race_name", "VARCHAR", "NULL::VARCHAR", "race_name_raw"),
            ("race_distance_m", "INTEGER", "NULL::INTEGER", "distance_m"),
            ("grade", "VARCHAR", "NULL::VARCHAR", "grade_raw"),
        ),
    },
    "steward_reports": {
        "relation": "steward_report_observations",
        "row_id": "observation_locator",
        "event_date": _date("race_date_iso"),
        "meet": "CASE WHEN lower(CAST(meet AS VARCHAR)) IN ('1','서울') THEN '1' WHEN lower(CAST(meet AS VARCHAR)) IN ('3','부산','부경','부산경남','영남') THEN '3' WHEN lower(CAST(meet AS VARCHAR)) IN ('4','영천') THEN '4' ELSE CAST(meet AS VARCHAR) END",
        "race_no": "CAST(rcNo AS VARCHAR)",
        "horse_id": "horse_id",
        "horse_no": "TRY_CAST(chulNo AS INTEGER)",
        "source_file": "source_path",
        "source_sha": "page_sha256",
        "source_row": "TRY_CAST(row_no AS BIGINT)",
        "captured_at": "source_captured_at_utc",
        "availability": "row_scope_status",
        "payload": "raw_item_json",
        "key_json": "NULL::VARCHAR",
        "fields": (
            ("judgement", "VARCHAR", "judgement", "steward_text_raw"),
            ("supplemental_steward_text", "VARCHAR", "addJudgement", "supplemental_steward_text_raw"),
            ("jockey_change", "VARCHAR", "jkChange", "jockey_change_raw"),
            ("subject_class", "VARCHAR", "subject_class", "sanction_subject_class_raw"),
            ("subject_id", "VARCHAR", "subject_id", "sanction_subject_id_raw"),
            ("horse_name", "VARCHAR", "prName", "horse_name_raw"),
            ("jockey_id", "VARCHAR", "jockey_id", "jockey_id_raw"),
            ("kind", "VARCHAR", "kind", "sanction_type_raw"),
            ("fine", "VARCHAR", "fine", "sanction_fine_raw"),
            ("reason", "VARCHAR", "reason", "sanction_reason_raw"),
        ),
    },
    "sanctions": {
        "relation": "steward_sanction_observations",
        "row_id": "observation_locator",
        "event_date": _date("race_date_iso"),
        "meet": "CASE WHEN lower(CAST(meet AS VARCHAR)) IN ('1','서울') THEN '1' WHEN lower(CAST(meet AS VARCHAR)) IN ('3','부산','부경','부산경남','영남') THEN '3' WHEN lower(CAST(meet AS VARCHAR)) IN ('4','영천') THEN '4' ELSE CAST(meet AS VARCHAR) END",
        "race_no": "CAST(rcNo AS VARCHAR)",
        "horse_id": "horse_id",
        "horse_no": "TRY_CAST(chulNo AS INTEGER)",
        "source_file": "source_path",
        "source_sha": "page_sha256",
        "source_row": "TRY_CAST(row_no AS BIGINT)",
        "captured_at": "source_captured_at_utc",
        "availability": "row_scope_status",
        "payload": "raw_item_json",
        "key_json": "NULL::VARCHAR",
        "fields": (
            ("judgement", "VARCHAR", "judgement", "steward_text_raw"),
            ("subject_class", "VARCHAR", "subject_class", "sanction_subject_class_raw"),
            ("subject_id", "VARCHAR", "subject_id", "sanction_subject_id_raw"),
            ("horse_name", "VARCHAR", "prName", "horse_name_raw"),
            ("jockey_id", "VARCHAR", "jockey_id", "jockey_id_raw"),
            ("kind", "VARCHAR", "kind", "sanction_type_raw"),
            ("fine", "VARCHAR", "fine", "sanction_fine_raw"),
            ("reason", "VARCHAR", "reason", "sanction_reason_raw"),
            ("sanction_date_raw", "VARCHAR", "spDate", "sanction_date_raw"),
            ("sanction_start_date_raw", "VARCHAR", "stDate", "sanction_start_date_raw"),
        ),
    },
    "daily_training": {
        "relation": "daily_training_rider_linked",
        "row_id": "observation_id",
        "event_date": "event_date",
        "meet": "CAST(meet AS VARCHAR)",
        "race_no": "NULL::VARCHAR",
        "horse_id": "official_horse_id",
        "source_file": "raw_path",
        "source_sha": "raw_sha256",
        "source_row": "TRY_CAST(source_row_no AS BIGINT)",
        "captured_at": "CAST(source_captured_at AS VARCHAR)",
        "availability": "availability_status",
        "payload": "raw_payload_json",
        "key_json": "NULL::VARCHAR",
        "fields": (
            ("horse_name", "VARCHAR", "horse_name_raw", "horse_name"),
            ("stable_part", "VARCHAR", "stable_part_raw", "stable_part"),
            ("stable_number", "VARCHAR", "stable_number_raw", "stable_number"),
            ("trainer_name", "VARCHAR", "trainer_name_raw", "trainer_name"),
            ("rider_type", "VARCHAR", "rider_type_raw", "rider_type"),
            ("rider_id", "VARCHAR", "rider_id_raw", "rider_id"),
            ("rider_name", "VARCHAR", "rider_name_linked", "@verified_existing_rider_name"),
            ("rider_name_linked", "VARCHAR", "rider_name_linked", "rider_name_linked"),
            ("rider_identity_status", "VARCHAR", "rider_identity_status", "@rider_identity_status"),
            ("duration_seconds", "INTEGER", "TRY_CAST(duration_seconds_raw AS INTEGER)", "duration_seconds"),
            ("canter_count", "INTEGER", "TRY_CAST(canter_count_raw AS INTEGER)", "canter_count"),
            ("gallop_count", "INTEGER", "TRY_CAST(gallop_count_raw AS INTEGER)", "gallop_count"),
            ("started_at_raw", "VARCHAR", "started_at_raw", "started_at_raw"),
            ("ended_at_raw", "VARCHAR", "ended_at_raw", "ended_at_raw"),
            ("entry_plan", "VARCHAR", "entry_plan_raw", "entry_plan"),
            ("event_verification_status", "VARCHAR", "event_verification_status", "event_verification_status"),
        ),
    },
    "start_training": {
        "relation": "start_training_raw",
        "row_id": "observation_id",
        "event_date": "event_date",
        "meet": "CAST(meet AS VARCHAR)",
        "race_no": "NULL::VARCHAR",
        "horse_id": "official_horse_id",
        "source_file": "raw_path",
        "source_sha": "raw_sha256",
        "source_row": "TRY_CAST(source_row_no AS BIGINT)",
        "captured_at": "CAST(source_captured_at AS VARCHAR)",
        "availability": "availability_status",
        "payload": "raw_payload_json",
        "key_json": "NULL::VARCHAR",
        "fields": (
            ("horse_name", "VARCHAR", "horse_name_raw", "horse_name"),
            ("stable_part", "VARCHAR", "stable_part_raw", "stable_part"),
            ("stable_number", "VARCHAR", "stable_number_raw", "stable_number"),
            ("rider_name", "VARCHAR", "rider_name_raw", "rider_name"),
            ("remark", "VARCHAR", "remark_raw", "remark"),
        ),
    },
    "swim_training": {
        "relation": "swim_training_raw",
        "row_id": "observation_id",
        "event_date": "event_date",
        "meet": "CAST(meet AS VARCHAR)",
        "race_no": "NULL::VARCHAR",
        "horse_id": "official_horse_id",
        "source_file": "raw_path",
        "source_sha": "raw_sha256",
        "source_row": "TRY_CAST(source_row_no AS BIGINT)",
        "captured_at": "CAST(source_captured_at AS VARCHAR)",
        "availability": "availability_status",
        "payload": "raw_payload_json",
        "key_json": "NULL::VARCHAR",
        "fields": (
            ("horse_name", "VARCHAR", "horse_name_raw", "horse_name"),
            ("swim_count", "INTEGER", "TRY_CAST(cnt_raw AS INTEGER)", "swim_count"),
            ("swim_count_raw", "VARCHAR", "cnt_raw", "swim_count_raw"),
            ("stable_part", "INTEGER", "TRY_CAST(horsepart_raw AS INTEGER)", "stable_part"),
            ("stable_note", "VARCHAR", "horsepart_memo_raw", "stable_note"),
            ("trainer_part", "INTEGER", "TRY_CAST(trpart_raw AS INTEGER)", "trainer_part"),
            ("trainer_name", "VARCHAR", "trainer_name_raw", "trainer_name"),
            ("count_unit_status", "VARCHAR", "cnt_unit_status", "count_unit_status"),
        ),
    },
    "starting_exam": {
        "relation": "starting_exam_results",
        "row_id": "observation_id",
        "event_date": "event_date",
        "meet": "CAST(meet AS VARCHAR)",
        "race_no": "NULL::VARCHAR",
        "horse_id": "COALESCE(source_horse_id, official_horse_id)",
        "source_file": "raw_path",
        "source_sha": "raw_sha256",
        "source_row": "TRY_CAST(source_row_no AS BIGINT)",
        "captured_at": "CAST(source_captured_at AS VARCHAR)",
        "availability": "availability_status",
        "payload": "raw_payload_json",
        "key_json": "NULL::VARCHAR",
        "fields": (
            ("day_serial", "VARCHAR", "CAST(day_serial_raw_json AS VARCHAR)", "day_serial"),
            ("test_no", "VARCHAR", "CAST(train_no_raw_json AS VARCHAR)", "test_no"),
            ("program_no", "INTEGER", "TRY_CAST(json_extract_string(CAST(horse_program_no_raw_json AS VARCHAR), '$') AS INTEGER)", "program_no"),
            ("horse_name", "VARCHAR", "json_extract_string(CAST(horse_name_raw_json AS VARCHAR), '$')", "horse_name"),
            ("origin_country", "VARCHAR", "json_extract_string(CAST(country_name_raw_json AS VARCHAR), '$')", "origin_country"),
            ("sex", "VARCHAR", "json_extract_string(CAST(sex_raw_json AS VARCHAR), '$')", "sex"),
            ("age", "INTEGER", "TRY_CAST(json_extract_string(CAST(age_raw_json AS VARCHAR), '$') AS INTEGER)", "age"),
            ("rider_name", "VARCHAR", "rider_text", "rider_name"),
            ("trainer_name", "VARCHAR", "source_trainer_name", "trainer_name"),
            ("trainer_id", "VARCHAR", "source_trainer_id", "trainer_id"),
            ("owner_name", "VARCHAR", "source_owner_name", "owner_name"),
            ("owner_id", "VARCHAR", "source_owner_id", "owner_id"),
            ("pass_flag", "VARCHAR", "json_extract_string(CAST(pass_flag_raw_json AS VARCHAR), '$')", "pass_flag"),
            ("reason", "VARCHAR", "json_extract_string(CAST(reason_raw_json AS VARCHAR), '$')", "reason"),
            ("no_pass_reason", "VARCHAR", "json_extract_string(CAST(no_pass_reason_raw_json AS VARCHAR), '$')", "no_pass_reason"),
            ("raw_fields", "VARCHAR", "raw_payload_json", "raw_fields"),
        ),
    },
    "medical": {
        "relation": "medical_observations",
        "row_id": "COALESCE(source_row_hash, source_path || '#' || COALESCE(CAST(row_no AS VARCHAR), CAST(line_no AS VARCHAR), CAST(page_no AS VARCHAR)))",
        "event_date": _date("event_date"),
        "meet": "CAST(meet_code AS VARCHAR)",
        "race_no": "NULL::VARCHAR",
        "horse_id": "hr_no_raw",
        "source_file": "source_path",
        "source_sha": "source_sha256",
        "source_row": "TRY_CAST(row_no AS BIGINT)",
        "captured_at": "source_captured_at_utc",
        "availability": "'historical_publication_unverified'",
        "payload": "raw_payload_json",
        "key_json": "NULL::VARCHAR",
        "fields": (
            ("horse_name", "VARCHAR", "horse_name_raw", "horse_name"),
            ("stable_part", "VARCHAR", "part_raw", "stable_part"),
            ("hospital_name", "VARCHAR", "hospital_name_raw", "hospital_name"),
            ("diagnosis_1", "VARCHAR", "ill_name1_raw", "diagnosis_1"),
            ("diagnosis_2", "VARCHAR", "ill_name2_raw", "diagnosis_2"),
            ("source_kind", "VARCHAR", "source_kind", "source_kind"),
            ("source_cohort", "VARCHAR", "source_cohort", "source_cohort"),
            ("capture_timestamp_basis", "VARCHAR", "capture_timestamp_basis", "capture_timestamp_basis"),
            ("diagnosis_rpt_raw", "VARCHAR", "diagnosis_rpt_raw", "diagnosis_rpt_raw"),
        ),
    },
    "horse_profile": {
        "relation": "horse_profile_snapshot_membership",
        "row_id": "CAST(capture_date AS VARCHAR) || '#' || CAST(meet_query AS VARCHAR) || '#' || CAST(horse_id_raw_string AS VARCHAR)",
        "event_date": _date("capture_date"),
        "meet": "CAST(meet_query AS VARCHAR)",
        "race_no": "NULL::VARCHAR",
        "horse_id": "horse_id_raw_string",
        "profile_scope_meet": "CAST(meet_query AS VARCHAR)",
        "official_id": "NULL::VARCHAR",
        "source_file": "source_file",
        "source_sha": "source_sha256",
        "source_row": "TRY_CAST(source_item_index_within_page AS BIGINT)",
        "captured_at": "NULL::VARCHAR",
        "availability": "NULL::VARCHAR",
        "payload": "NULL::VARCHAR",
        "key_json": "NULL::VARCHAR",
        "fields": (
            ("profile_observed_date", "DATE", _date("capture_date"), "profile_observed_date"),
            ("relationship_time_rule", "VARCHAR", "'current_profile_snapshot_only'", "relationship_time_rule"),
            ("horse_name", "VARCHAR", "horse_name_snapshot", "horse_name"),
            ("birth_date", "VARCHAR", "birthday_raw", "birth_date"),
            ("sex", "VARCHAR", "sex_raw", "sex"),
            ("origin_country", "VARCHAR", "origin_raw", "origin_country"),
            ("sire_id", "VARCHAR", "sire_id_raw_string", "sire_id"),
            ("sire_name", "VARCHAR", "sire_name_raw", "sire_name"),
            ("dam_id", "VARCHAR", "dam_id_raw_string", "dam_id"),
            ("dam_name", "VARCHAR", "dam_name_raw", "dam_name"),
            ("trainer_id", "VARCHAR", "current_trainer_id_snapshot_raw_string", "trainer_id"),
            ("trainer_name", "VARCHAR", "current_trainer_name_snapshot_raw", "trainer_name"),
            ("owner_id", "VARCHAR", "current_owner_id_snapshot_raw_string", "owner_id"),
            ("owner_name", "VARCHAR", "current_owner_name_snapshot_raw", "owner_name"),
            ("grade", "VARCHAR", "current_grade_snapshot_raw", "grade"),
            ("rating", "INTEGER", "NULL::INTEGER", "rating"),
        ),
    },
    "jockey_profile": {
        "relation": "person_reference_profile_snapshots",
        "where": "entity_type = 'jockey'",
        "row_id": "CAST(capture_date AS VARCHAR) || '#' || CAST(meet_query AS VARCHAR) || '#' || CAST(official_id_raw_string AS VARCHAR)",
        "event_date": _date("capture_date"),
        "meet": "CAST(meet_query AS VARCHAR)",
        "race_no": "NULL::VARCHAR",
        "profile_scope_meet": "CAST(meet_query AS VARCHAR)",
        "official_id": "official_id_raw_string",
        "source_file": "source_file",
        "source_sha": "source_sha256",
        "source_row": "TRY_CAST(source_item_index_within_page AS BIGINT)",
        "captured_at": "NULL::VARCHAR",
        "availability": "NULL::VARCHAR",
        "payload": "NULL::VARCHAR",
        "key_json": "NULL::VARCHAR",
        "fields": (
            ("profile_observed_date", "DATE", _date("capture_date"), "profile_observed_date"),
            ("relationship_time_rule", "VARCHAR", "relationship_time_rule", "relationship_time_rule"),
            ("meet_label_raw", "VARCHAR", "meet_label_raw", "meet_label_raw"),
            ("name", "VARCHAR", "name_snapshot", "name"),
            ("english_name", "VARCHAR", "english_name_snapshot", "english_name"),
            ("debut_date_raw", "VARCHAR", "profile_start_date_raw", "debut_date_raw"),
            ("end_date_raw", "VARCHAR", "profile_end_date_raw", "end_date_raw"),
            ("part_raw", "VARCHAR", "profile_part_raw", "part_raw"),
        ),
    },
    "trainer_profile": {
        "relation": "person_reference_profile_snapshots",
        "where": "entity_type = 'trainer'",
        "row_id": "CAST(capture_date AS VARCHAR) || '#' || CAST(meet_query AS VARCHAR) || '#' || CAST(official_id_raw_string AS VARCHAR)",
        "event_date": _date("capture_date"),
        "meet": "CAST(meet_query AS VARCHAR)",
        "race_no": "NULL::VARCHAR",
        "profile_scope_meet": "CAST(meet_query AS VARCHAR)",
        "official_id": "official_id_raw_string",
        "source_file": "source_file",
        "source_sha": "source_sha256",
        "source_row": "TRY_CAST(source_item_index_within_page AS BIGINT)",
        "captured_at": "NULL::VARCHAR",
        "availability": "NULL::VARCHAR",
        "payload": "NULL::VARCHAR",
        "key_json": "NULL::VARCHAR",
        "fields": (
            ("profile_observed_date", "DATE", _date("capture_date"), "profile_observed_date"),
            ("relationship_time_rule", "VARCHAR", "relationship_time_rule", "relationship_time_rule"),
            ("meet_label_raw", "VARCHAR", "meet_label_raw", "meet_label_raw"),
            ("name", "VARCHAR", "name_snapshot", "name"),
            ("english_name", "VARCHAR", "english_name_snapshot", "english_name"),
            ("start_date_raw", "VARCHAR", "profile_start_date_raw", "start_date_raw"),
            ("end_date_raw", "VARCHAR", "profile_end_date_raw", "end_date_raw"),
            ("part_raw", "VARCHAR", "profile_part_raw", "part_raw"),
        ),
    },
    "owner_profile": {
        "relation": "person_reference_profile_snapshots",
        "where": "entity_type = 'owner'",
        "row_id": "CAST(capture_date AS VARCHAR) || '#' || CAST(meet_query AS VARCHAR) || '#' || CAST(official_id_raw_string AS VARCHAR)",
        "event_date": _date("capture_date"),
        "meet": "CAST(meet_query AS VARCHAR)",
        "race_no": "NULL::VARCHAR",
        "profile_scope_meet": "CAST(meet_query AS VARCHAR)",
        "official_id": "official_id_raw_string",
        "source_file": "source_file",
        "source_sha": "source_sha256",
        "source_row": "TRY_CAST(source_item_index_within_page AS BIGINT)",
        "captured_at": "NULL::VARCHAR",
        "availability": "NULL::VARCHAR",
        "payload": "NULL::VARCHAR",
        "key_json": "NULL::VARCHAR",
        "fields": (
            ("profile_observed_date", "DATE", _date("capture_date"), "profile_observed_date"),
            ("relationship_time_rule", "VARCHAR", "relationship_time_rule", "relationship_time_rule"),
            ("meet_label_raw", "VARCHAR", "meet_label_raw", "meet_label_raw"),
            ("name", "VARCHAR", "name_snapshot", "name"),
            ("english_name", "VARCHAR", "english_name_snapshot", "english_name"),
            ("registration_date_raw", "VARCHAR", "profile_start_date_raw", "registration_date_raw"),
        ),
    },
}


def _base_expression(spec: dict[str, Any], key: str, fallback: str) -> str:
    value = spec.get(key)
    return value if value is not None else fallback


def _baseline_select(family: str, spec: dict[str, Any]) -> str | None:
    relation = spec.get("relation")
    if relation is None:
        return None
    event_date = _base_expression(spec, "event_date", "NULL::DATE")
    meet = _base_expression(spec, "meet", "NULL::VARCHAR")
    race_no = _base_expression(spec, "race_no", "NULL::VARCHAR")
    horse_id = _base_expression(spec, "horse_id", "NULL::VARCHAR")
    horse_no = _base_expression(spec, "horse_no", "NULL::INTEGER")
    trial_no = _base_expression(spec, "trial_no", "NULL::VARCHAR")
    profile_scope = _base_expression(spec, "profile_scope_meet", "NULL::VARCHAR")
    official_id = _base_expression(spec, "official_id", "NULL::VARCHAR")
    fields = spec["fields"]
    typed = ",\n            ".join(
        f"CAST({base_expr} AS {sql_type}) AS {_id(name)}"
        for name, sql_type, base_expr, _ in fields
    )
    structured = ", ".join(
        f"{_id(name)} := CAST({base_expr} AS {sql_type})"
        for name, sql_type, base_expr, _ in fields
    )
    where = f" WHERE {spec['where']}" if spec.get("where") else ""
    return f"""SELECT
            '{family}'::VARCHAR AS family,
            CAST({spec.get('row_id', 'NULL::VARCHAR')} AS VARCHAR) AS record_id,
            CAST({spec.get('key_json', 'NULL::VARCHAR')} AS VARCHAR) AS key_json,
            TRY_CAST({event_date} AS DATE) AS event_date,
            CAST({meet} AS VARCHAR) AS meet,
            CAST({race_no} AS VARCHAR) AS race_no,
            CAST({horse_id} AS VARCHAR) AS horse_id,
            TRY_CAST({horse_no} AS INTEGER) AS horse_no,
            CAST({trial_no} AS VARCHAR) AS trial_no,
            CAST({profile_scope} AS VARCHAR) AS profile_scope_meet,
            CAST({official_id} AS VARCHAR) AS official_id,
            CAST({spec.get('source_file', 'NULL::VARCHAR')} AS VARCHAR) AS source_file,
            CAST({spec.get('source_sha', 'NULL::VARCHAR')} AS VARCHAR) AS source_sha256,
            TRY_CAST({spec.get('source_row', 'NULL::BIGINT')} AS BIGINT) AS source_row_no,
            CAST({spec.get('captured_at', 'NULL::VARCHAR')} AS VARCHAR) AS captured_at_utc,
            CAST({spec.get('availability', 'NULL::VARCHAR')} AS VARCHAR) AS availability_status,
            'immutable_core_baseline'::VARCHAR AS row_source,
            'baseline'::VARCHAR AS disposition,
            NULL::VARCHAR AS payload_sha256,
            NULL::INTEGER AS occurrence_no,
            CAST({spec.get('payload', 'NULL::VARCHAR')} AS VARCHAR) AS payload_json,
            CAST(to_json(struct_pack({structured})) AS VARCHAR) AS fields_json,
            {typed}
        FROM {_id(relation)}{where}"""


def _incremental_select(family: str, spec: dict[str, Any]) -> str:
    fields = spec["fields"]
    typed = ",\n            ".join(
        f"CAST({_json_field('r', json_field, sql_type)} AS {sql_type}) AS {_id(name)}"
        for name, sql_type, _, json_field in fields
    )
    return f"""SELECT
            r.family,
            CAST(r.record_id AS VARCHAR) AS record_id,
            CAST(r.key_json AS VARCHAR) AS key_json,
            TRY_CAST(r.event_date AS DATE) AS event_date,
            CAST(r.meet AS VARCHAR) AS meet,
            CAST(r.race_no AS VARCHAR) AS race_no,
            CAST(r.horse_id AS VARCHAR) AS horse_id,
            TRY_CAST(json_extract_string(r.fields_json, '$.horse_no') AS INTEGER) AS horse_no,
            TRY_CAST(json_extract_string(r.fields_json, '$.trial_no_raw') AS VARCHAR) AS trial_no,
            TRY_CAST(json_extract_string(r.fields_json, '$.profile_scope_meet') AS VARCHAR) AS profile_scope_meet,
            TRY_CAST(json_extract_string(r.fields_json, '$.official_id') AS VARCHAR) AS official_id,
            CAST(r.source_file AS VARCHAR) AS source_file,
            CAST(r.source_sha256 AS VARCHAR) AS source_sha256,
            TRY_CAST(r.source_row_no AS BIGINT) AS source_row_no,
            CAST(r.captured_at_utc AS VARCHAR) AS captured_at_utc,
            CAST(r.availability_status AS VARCHAR) AS availability_status,
            'incremental_refresh'::VARCHAR AS row_source,
            CAST(r.disposition AS VARCHAR) AS disposition,
            CAST(r.payload_sha256 AS VARCHAR) AS payload_sha256,
            TRY_CAST(r.occurrence_no AS INTEGER) AS occurrence_no,
            CAST(r.payload_json AS VARCHAR) AS payload_json,
            CAST(r.fields_json AS VARCHAR) AS fields_json,
            {typed}
        FROM refresh_event_records AS r
        WHERE r.family = '{family}'
          AND r.disposition = 'accepted'"""


def _family_view(family: str, spec: dict[str, Any]) -> str:
    baseline = _baseline_select(family, spec)
    incremental = _incremental_select(family, spec)
    if baseline is None:
        body = incremental
    else:
        body = baseline + "\n        UNION ALL\n        " + incremental
    view_name = (
        "research_current_passing_group_observations"
        if family == "passing_groups"
        else "research_current_" + family
    )
    return f"CREATE OR REPLACE VIEW {_id(view_name)} AS\n{body}"


def _derived_sections() -> str:
    return f"""CREATE OR REPLACE VIEW research_current_sections AS
        SELECT
            'immutable_core_baseline'::VARCHAR AS row_source,
            CAST(meet AS VARCHAR) AS meet,
            {_date('race_date')} AS event_date,
            TRY_CAST(race_no AS VARCHAR) AS race_no,
            CAST(horse_id AS VARCHAR) AS horse_id,
            TRY_CAST(horse_program_no AS INTEGER) AS horse_no,
            CAST(point_code AS VARCHAR) AS point_code,
            CAST(measure_kind AS VARCHAR) AS measure_kind,
            CAST(source_field AS VARCHAR) AS source_field,
            CAST(raw_value AS VARCHAR) AS raw_value,
            TRY_CAST(time_ms AS INTEGER) AS time_ms,
            TRY_CAST(passing_order AS INTEGER) AS passing_order,
            CAST(source_file AS VARCHAR) AS source_file,
            NULL::VARCHAR AS source_sha256,
            TRY_CAST(source_item_index AS BIGINT) AS source_row_no,
            NULL::VARCHAR AS captured_at_utc,
            'baseline'::VARCHAR AS disposition
        FROM section_measurements_api
        UNION ALL
        SELECT
            'incremental_refresh'::VARCHAR AS row_source,
            CAST(r.meet AS VARCHAR) AS meet,
            TRY_CAST(r.event_date AS DATE) AS event_date,
            CAST(r.race_no AS VARCHAR) AS race_no,
            CAST(r.horse_id AS VARCHAR) AS horse_id,
            TRY_CAST(json_extract_string(r.fields_json, '$.horse_no') AS INTEGER) AS horse_no,
            json_extract_string(j.value, '$.point_code') AS point_code,
            json_extract_string(j.value, '$.measure_kind') AS measure_kind,
            json_extract_string(j.value, '$.source_field') AS source_field,
            json_extract_string(j.value, '$.raw_value') AS raw_value,
            TRY_CAST(json_extract_string(j.value, '$.time_ms') AS INTEGER) AS time_ms,
            TRY_CAST(json_extract_string(j.value, '$.passing_order') AS INTEGER) AS passing_order,
            CAST(r.source_file AS VARCHAR) AS source_file,
            CAST(r.source_sha256 AS VARCHAR) AS source_sha256,
            TRY_CAST(r.source_row_no AS BIGINT) AS source_row_no,
            CAST(r.captured_at_utc AS VARCHAR) AS captured_at_utc,
            CAST(r.disposition AS VARCHAR) AS disposition
        FROM refresh_event_records AS r,
             LATERAL json_each(json_extract(r.fields_json, '$.section_measurements')) AS j
        WHERE r.family = 'race_results'
          AND r.disposition = 'accepted'
          AND json_type(r.fields_json, '$.section_measurements') = 'ARRAY'"""


def _derived_section_parse_issues() -> str:
    return """CREATE OR REPLACE VIEW research_current_section_parse_issues AS
        SELECT
            CAST(r.record_id AS VARCHAR) || '#section-issue:' || CAST(j.key AS VARCHAR) AS record_id,
            TRY_CAST(r.event_date AS DATE) AS event_date,
            CAST(r.meet AS VARCHAR) AS meet,
            CAST(r.race_no AS VARCHAR) AS race_no,
            CAST(r.horse_id AS VARCHAR) AS horse_id,
            json_extract_string(j.value, '$.source_field') AS source_field,
            json_extract_string(j.value, '$.raw_value') AS raw_value,
            CAST(j.value AS VARCHAR) AS issue_json,
            CAST(r.source_file AS VARCHAR) AS source_file,
            CAST(r.source_sha256 AS VARCHAR) AS source_sha256,
            TRY_CAST(r.source_row_no AS BIGINT) AS source_row_no,
            CAST(r.captured_at_utc AS VARCHAR) AS captured_at_utc,
            CAST(r.disposition AS VARCHAR) AS disposition
        FROM refresh_event_records AS r,
             LATERAL json_each(json_extract(r.fields_json, '$.section_parse_issues')) AS j
        WHERE r.family = 'race_results'
          AND r.disposition = 'accepted'
          AND json_type(r.fields_json, '$.section_parse_issues') = 'ARRAY'"""


def _derived_passing_orders() -> str:
    return f"""CREATE OR REPLACE VIEW research_current_passing_orders AS
        SELECT
            'immutable_core_baseline'::VARCHAR AS row_source,
            CAST(meet AS VARCHAR) AS meet,
            {_date('race_date')} AS event_date,
            TRY_CAST(race_no AS VARCHAR) AS race_no,
            CAST(horse_id AS VARCHAR) AS horse_id,
            TRY_CAST(horse_program_no AS INTEGER) AS horse_no,
            CAST(point_code AS VARCHAR) AS point_code,
            CAST(source_field AS VARCHAR) AS source_field,
            CAST(raw_value AS VARCHAR) AS raw_value,
            TRY_CAST(passing_order AS INTEGER) AS passing_order,
            CAST(source_file AS VARCHAR) AS source_file,
            NULL::VARCHAR AS source_sha256,
            TRY_CAST(source_item_index AS BIGINT) AS source_row_no,
            NULL::VARCHAR AS captured_at_utc,
            'baseline'::VARCHAR AS disposition
        FROM section_measurements_api
        WHERE passing_order IS NOT NULL
        UNION ALL
        SELECT
            'incremental_refresh'::VARCHAR AS row_source,
            CAST(r.meet AS VARCHAR) AS meet,
            TRY_CAST(r.event_date AS DATE) AS event_date,
            CAST(r.race_no AS VARCHAR) AS race_no,
            CAST(r.horse_id AS VARCHAR) AS horse_id,
            TRY_CAST(json_extract_string(r.fields_json, '$.horse_no') AS INTEGER) AS horse_no,
            json_extract_string(j.value, '$.point_code') AS point_code,
            json_extract_string(j.value, '$.source_field') AS source_field,
            json_extract_string(j.value, '$.raw_value') AS raw_value,
            TRY_CAST(json_extract_string(j.value, '$.passing_order') AS INTEGER) AS passing_order,
            CAST(r.source_file AS VARCHAR) AS source_file,
            CAST(r.source_sha256 AS VARCHAR) AS source_sha256,
            TRY_CAST(r.source_row_no AS BIGINT) AS source_row_no,
            CAST(r.captured_at_utc AS VARCHAR) AS captured_at_utc,
            CAST(r.disposition AS VARCHAR) AS disposition
        FROM refresh_event_records AS r,
             LATERAL json_each(json_extract(r.fields_json, '$.section_measurements')) AS j
        WHERE r.family = 'race_results'
          AND r.disposition = 'accepted'
          AND json_type(r.fields_json, '$.section_measurements') = 'ARRAY'
          AND TRY_CAST(json_extract_string(j.value, '$.passing_order') AS INTEGER) IS NOT NULL"""


def _derived_passing_api_records() -> str:
    return f"""CREATE OR REPLACE VIEW research_current_passing_api_records AS
        SELECT
            CAST(observation_locator AS VARCHAR) AS record_id,
            {_date('event_date')} AS event_date,
            CAST(actual_meet_code AS VARCHAR) AS meet,
            CAST(race_no AS VARCHAR) AS race_no,
            'api_point_observation'::VARCHAR AS record_granularity,
            CAST(source_point_label_raw AS VARCHAR) AS source_point_label_raw,
            CAST(canonical_point_code AS VARCHAR) AS canonical_point_code,
            CAST(mapping_status AS VARCHAR) AS mapping_status,
            CAST(notation_raw AS VARCHAR) AS notation_raw,
            NULL::VARCHAR AS corner_values_raw_json,
            NULL::VARCHAR AS validated_passing_points_json,
            NULL::VARCHAR AS passing_point_holds_json,
            CAST(raw_item_json AS VARCHAR) AS payload_json,
            CAST(to_json(struct_pack(source_point_label_raw := source_point_label_raw, canonical_point_code := canonical_point_code, mapping_status := mapping_status, notation_raw := notation_raw)) AS VARCHAR) AS fields_json,
            CAST(source_path AS VARCHAR) AS source_file,
            CAST(source_sha256 AS VARCHAR) AS source_sha256,
            TRY_CAST(row_no AS BIGINT) AS source_row_no,
            CAST(source_captured_at_utc AS VARCHAR) AS captured_at_utc,
            CAST(mapping_status AS VARCHAR) AS availability_status,
            'baseline'::VARCHAR AS disposition
        FROM passing_api_point_observations
        UNION ALL
        SELECT
            CAST(r.record_id AS VARCHAR) AS record_id,
            TRY_CAST(r.event_date AS DATE) AS event_date,
            CAST(r.meet AS VARCHAR) AS meet,
            CAST(r.race_no AS VARCHAR) AS race_no,
            'race_level_api303_record'::VARCHAR AS record_granularity,
            NULL::VARCHAR AS source_point_label_raw,
            NULL::VARCHAR AS canonical_point_code,
            'unmapped_api303_race_level'::VARCHAR AS mapping_status,
            NULL::VARCHAR AS notation_raw,
            CAST(json_extract(r.fields_json, '$.passing_group_values_raw') AS VARCHAR) AS corner_values_raw_json,
            CAST(json_extract(r.fields_json, '$.passing_points') AS VARCHAR) AS validated_passing_points_json,
            CAST(json_extract(r.fields_json, '$.passing_point_holds') AS VARCHAR) AS passing_point_holds_json,
            CAST(r.payload_json AS VARCHAR) AS payload_json,
            CAST(r.fields_json AS VARCHAR) AS fields_json,
            CAST(r.source_file AS VARCHAR) AS source_file,
            CAST(r.source_sha256 AS VARCHAR) AS source_sha256,
            TRY_CAST(r.source_row_no AS BIGINT) AS source_row_no,
            CAST(r.captured_at_utc AS VARCHAR) AS captured_at_utc,
            CAST(r.availability_status AS VARCHAR) AS availability_status,
            CAST(r.disposition AS VARCHAR) AS disposition
        FROM refresh_event_records AS r
        WHERE r.family = 'passing_groups'
          AND r.disposition = 'accepted'"""


def _derived_mapped_passing_groups() -> str:
    return f"""CREATE OR REPLACE VIEW research_current_mapped_passing_groups AS
        SELECT
            CAST(actual_meet_code AS VARCHAR) || '#' || CAST(event_date AS VARCHAR) || '#' ||
                CAST(race_no AS VARCHAR) || '#' || COALESCE(canonical_point_code, '') AS record_id,
            CAST(actual_meet_code AS VARCHAR) AS meet,
            {_date('event_date')} AS event_date,
            CAST(race_no AS VARCHAR) AS race_no,
            CAST(canonical_point_code AS VARCHAR) AS canonical_point_code,
            CAST(notation_raw AS VARCHAR) AS notation_raw,
            CAST(selected_source AS VARCHAR) AS selected_source,
            CAST(selection_status AS VARCHAR) AS selection_status,
            'reviewed_canonical_point'::VARCHAR AS record_granularity,
            CAST(to_json(struct_pack(canonical_point_code := canonical_point_code, notation_raw := notation_raw, selected_source := selected_source, selection_status := selection_status)) AS VARCHAR) AS fields_json,
            CAST(to_json(struct_pack(api_observation_locators := api_observation_locators_json, rpt_observation_locators := rpt_observation_locators_json, api_notation_values := api_notation_values_json, rpt_notation_values := rpt_notation_values_json)) AS VARCHAR) AS payload_json,
            NULL::VARCHAR AS source_file,
            NULL::VARCHAR AS source_sha256,
            NULL::BIGINT AS source_row_no,
            NULL::VARCHAR AS captured_at_utc,
            'baseline'::VARCHAR AS disposition
        FROM race_passing_groups
        WHERE canonical_point_code IS NOT NULL
        UNION ALL
        SELECT
            CAST(r.record_id AS VARCHAR) || '#point:' || CAST(j.key AS VARCHAR) AS record_id,
            CAST(r.meet AS VARCHAR) AS meet,
            TRY_CAST(r.event_date AS DATE) AS event_date,
            CAST(r.race_no AS VARCHAR) AS race_no,
            json_extract_string(j.value, '$.canonical_point') AS canonical_point_code,
            json_extract_string(j.value, '$.notation') AS notation_raw,
            COALESCE(json_extract_string(j.value, '$.selected_source'), 'API303') AS selected_source,
            json_extract_string(j.value, '$.mapping_status') AS selection_status,
            'validated_api303_passing_point'::VARCHAR AS record_granularity,
            CAST(j.value AS VARCHAR) AS fields_json,
            CAST(r.payload_json AS VARCHAR) AS payload_json,
            COALESCE(json_extract_string(j.value, '$.source_file'), json_extract_string(j.value, '$.source_path'), CAST(r.source_file AS VARCHAR)) AS source_file,
            COALESCE(json_extract_string(j.value, '$.source_sha256'), json_extract_string(j.value, '$.source_sha'), CAST(r.source_sha256 AS VARCHAR)) AS source_sha256,
            COALESCE(TRY_CAST(json_extract_string(j.value, '$.source_row_no') AS BIGINT), TRY_CAST(json_extract_string(j.value, '$.source_line_no') AS BIGINT), TRY_CAST(json_extract_string(j.value, '$.line_no') AS BIGINT), TRY_CAST(json_extract_string(j.value, '$.row_no') AS BIGINT), TRY_CAST(r.source_row_no AS BIGINT)) AS source_row_no,
            CAST(r.captured_at_utc AS VARCHAR) AS captured_at_utc,
            CAST(r.disposition AS VARCHAR) AS disposition
        FROM refresh_event_records AS r,
             LATERAL json_each(json_extract(r.fields_json, '$.passing_points')) AS j
        WHERE r.family = 'passing_groups'
          AND r.disposition = 'accepted'
          AND json_type(r.fields_json, '$.passing_points') = 'ARRAY'
          AND json_extract_string(j.value, '$.canonical_point') IS NOT NULL
        UNION ALL
        SELECT
            CAST(e.record_id AS VARCHAR) || '#rpt-resolution:' || CAST(p.source_field AS VARCHAR) || ':' || CAST(p.canonical_point_code AS VARCHAR) AS record_id,
            CAST(e.meet AS VARCHAR) AS meet,
            TRY_CAST(e.event_date AS DATE) AS event_date,
            CAST(e.race_no AS VARCHAR) AS race_no,
            CAST(p.canonical_point_code AS VARCHAR) AS canonical_point_code,
            CAST(p.notation_raw AS VARCHAR) AS notation_raw,
            'RPT_Dacom11'::VARCHAR AS selected_source,
            CAST(p.mapping_status AS VARCHAR) AS selection_status,
            'resolved_rpt_passing_point'::VARCHAR AS record_granularity,
            CAST(to_json(struct_pack(
                source_field := p.source_field,
                canonical_point_code := p.canonical_point_code,
                notation_raw := p.notation_raw,
                mapping_status := p.mapping_status,
                selected_source := 'RPT_Dacom11',
                source_file := p.source_file,
                source_sha256 := p.source_sha256,
                line_no := p.line_no,
                byte_offset := p.byte_offset,
                raw_line := p.raw_line,
                captured_at_utc := p.captured_at_utc,
                run_id := p.run_id
            )) AS VARCHAR) AS fields_json,
            CAST(to_json(struct_pack(
                source_file := p.source_file,
                source_sha256 := p.source_sha256,
                line_no := p.line_no,
                byte_offset := p.byte_offset,
                raw_line := p.raw_line
            )) AS VARCHAR) AS payload_json,
            CAST(p.source_file AS VARCHAR) AS source_file,
            CAST(p.source_sha256 AS VARCHAR) AS source_sha256,
            TRY_CAST(p.line_no AS BIGINT) AS source_row_no,
            CAST(p.captured_at_utc AS VARCHAR) AS captured_at_utc,
            CAST(e.disposition AS VARCHAR) AS disposition
        FROM refresh_passing_point_resolutions AS p
        JOIN refresh_event_records AS e ON e.record_id = p.record_id
        WHERE e.family = 'passing_groups'
          AND e.disposition = 'accepted'"""


def _derived_confirmed_races() -> str:
    return """CREATE OR REPLACE VIEW research_current_confirmed_races AS
        WITH race_results AS (
            SELECT
                meet,
                event_date,
                race_no,
                COUNT(*) AS runner_count,
                COUNT(*) FILTER (WHERE finish_position > 0) AS positive_finish_count
            FROM research_current_race_results
            GROUP BY meet, event_date, race_no
            HAVING COUNT(*) FILTER (WHERE finish_position > 0) >= 1
        )
        SELECT
            rr.meet,
            rr.event_date,
            rr.race_no,
            rr.runner_count,
            rr.positive_finish_count,
            'positive_finish_evidence'::VARCHAR AS confirmation_basis,
            s.record_id AS schedule_record_id,
            s.race_name,
            s.race_distance_m,
            s.grade,
            s.scheduled_start_raw,
            s.age_condition,
            s.sex_condition,
            s.race_status_raw,
            s.source_file AS schedule_source_file,
            s.source_sha256 AS schedule_source_sha256,
            s.availability_status AS schedule_availability_status
        FROM race_results AS rr
        LEFT JOIN research_latest_race_schedule AS s
          ON s.meet = rr.meet
         AND s.event_date = rr.event_date
         AND s.race_no = rr.race_no"""


def _derived_passing_point_holds() -> str:
    return """CREATE OR REPLACE VIEW research_current_passing_point_holds AS
        SELECT
            CAST(h.source_record_id AS VARCHAR) || '#passing-hold:' || CAST(h.hold_index AS VARCHAR) AS record_id,
            h.event_date,
            h.meet,
            h.race_no,
            h.canonical_point_candidate,
            h.notation_raw,
            h.source_field,
            h.hold_status,
            h.hold_json,
            h.payload_json,
            h.source_file,
            h.source_sha256,
            h.source_row_no,
            h.captured_at_utc,
            h.disposition
        FROM (
            SELECT
                CAST(r.record_id AS VARCHAR) AS source_record_id,
                CAST(j.key AS VARCHAR) AS hold_index,
                TRY_CAST(r.event_date AS DATE) AS event_date,
                CAST(r.meet AS VARCHAR) AS meet,
                CAST(r.race_no AS VARCHAR) AS race_no,
                json_extract_string(j.value, '$.canonical_point') AS canonical_point_candidate,
                json_extract_string(j.value, '$.notation') AS notation_raw,
                json_extract_string(j.value, '$.source_field') AS source_field,
                json_extract_string(j.value, '$.mapping_status') AS hold_status,
                CAST(j.value AS VARCHAR) AS hold_json,
                CAST(r.payload_json AS VARCHAR) AS payload_json,
                CAST(r.source_file AS VARCHAR) AS source_file,
                CAST(r.source_sha256 AS VARCHAR) AS source_sha256,
                TRY_CAST(r.source_row_no AS BIGINT) AS source_row_no,
                CAST(r.captured_at_utc AS VARCHAR) AS captured_at_utc,
                CAST(r.disposition AS VARCHAR) AS disposition
            FROM refresh_event_records AS r,
                 LATERAL json_each(json_extract(r.fields_json, '$.passing_point_holds')) AS j
            WHERE r.family = 'passing_groups'
              AND r.disposition = 'accepted'
              AND json_type(r.fields_json, '$.passing_point_holds') = 'ARRAY'
        ) AS h
        WHERE NOT EXISTS (
            SELECT 1
            FROM refresh_passing_point_resolutions AS p
            WHERE p.record_id = h.source_record_id
              AND p.source_field = h.source_field
              AND p.canonical_point_code = h.canonical_point_candidate
        )"""


def _derived_equipment() -> str:
    return """CREATE OR REPLACE VIEW research_current_equipment AS
        SELECT
            record_id, row_source, event_date, meet, race_no, horse_no, horse_id,
            horse_name, equipment_raw, equipment_field_present, equipment_is_null,
            equipment_value_state, equipment_field_state, physical_wear_status,
            link_status, link_method, link_reason, source_file, source_sha256,
            source_row_no, captured_at_utc, availability_status, disposition,
            payload_json, fields_json
        FROM research_latest_public_cards"""


def _derived_bodyweight_observations() -> str:
    return """CREATE OR REPLACE VIEW research_current_bodyweight_observations AS
        SELECT
            record_id, 'race_results'::VARCHAR AS observation_family,
            event_date, meet, race_no, horse_no, horse_id, horse_name,
            horse_weight_kg, horse_weight_raw,
            body_weight_change_kg, carried_weight_kg, source_file, source_sha256,
            source_row_no, captured_at_utc, availability_status, row_source,
            disposition, payload_json, fields_json
        FROM research_current_race_results
        UNION ALL
        SELECT
            record_id, 'body_weights'::VARCHAR AS observation_family,
            event_date, meet, race_no, horse_no, horse_id, horse_name,
            horse_weight_kg, CAST(json_extract_string(fields_json, '$.horse_weight_raw') AS VARCHAR) AS horse_weight_raw,
            body_weight_change_kg, carried_weight_kg, source_file, source_sha256,
            source_row_no, captured_at_utc, availability_status, row_source,
            disposition, payload_json, fields_json
        FROM research_current_body_weights"""


def _derived_bodyweight_current() -> str:
    return """CREATE OR REPLACE VIEW research_current_bodyweight AS
        SELECT * EXCLUDE (priority_rank)
        FROM (
            SELECT
                observation_family, event_date, meet, race_no, horse_no, horse_id,
                horse_name, horse_weight_kg, horse_weight_raw, body_weight_change_kg,
                carried_weight_kg, source_file, source_sha256, source_row_no,
                captured_at_utc, availability_status, row_source, disposition,
                record_id, payload_json, fields_json,
                ROW_NUMBER() OVER (
                    PARTITION BY meet, event_date, race_no,
                                 COALESCE(CAST(horse_no AS VARCHAR), 'horse_id:' || COALESCE(horse_id, ''))
                    ORDER BY
                        CASE WHEN observation_family = 'body_weights'
                                  AND horse_weight_kg > 0 THEN 1 ELSE 0 END DESC,
                        CASE WHEN horse_weight_kg > 0 THEN 1 ELSE 0 END DESC,
                        captured_at_utc DESC NULLS LAST,
                        CASE WHEN observation_family = 'race_results' THEN 1 ELSE 0 END DESC,
                        record_id DESC
                ) AS priority_rank
            FROM research_current_bodyweight_observations
        )
        WHERE priority_rank = 1"""


def _latest_profile_view(entity: str, identity_column: str) -> str:
    source = _id(f"research_current_{entity}_profile")
    view = _id(f"research_latest_{entity}_profile")
    identity = _id(identity_column)
    return f"""CREATE OR REPLACE VIEW {view} AS
        SELECT * EXCLUDE (latest_rank)
        FROM (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY {identity}, profile_scope_meet
                ORDER BY event_date DESC, captured_at_utc DESC NULLS LAST, record_id DESC
            ) AS latest_rank
            FROM {source}
        ) AS ranked
        WHERE latest_rank = 1"""


def _latest_event_view(view_name: str, source_view: str, partition_columns: tuple[str, ...]) -> str:
    partition = ", ".join(_id(column) for column in partition_columns)
    return f"""CREATE OR REPLACE VIEW {_id(view_name)} AS
        SELECT * EXCLUDE (latest_rank)
        FROM (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY {partition}
                ORDER BY captured_at_utc DESC NULLS LAST, record_id DESC
            ) AS latest_rank
            FROM {_id(source_view)}
        ) AS ranked
        WHERE latest_rank = 1"""


def view_statements() -> list[str]:
    """Return ordered SQL for the 18 current families and 17 derived views.

    Baseline rows use the exact reviewed source relations recorded in the
    inventory.  The adapter-provided natural key remains available as
    ``key_json`` on refresh rows; baseline key components are exposed as
    typed event/identity columns rather than reconstructed with a different
    serialization contract.
    """
    statements = [_family_view(family, _FAMILIES[family]) for family in _FAMILY_ORDER]
    statements.extend(
        [
            _latest_event_view(
                "research_latest_public_cards",
                "research_current_public_cards",
                ("meet", "event_date", "race_no", "horse_no"),
            ),
            _latest_event_view(
                "research_latest_entry_sheets",
                "research_current_entry_sheets",
                ("meet", "event_date", "race_no", "horse_no"),
            ),
            _latest_event_view(
                "research_latest_race_schedule",
                "research_current_race_schedule",
                ("meet", "event_date", "race_no"),
            ),
        ]
    )
    statements.extend(
        [
            _derived_sections(),
            _derived_section_parse_issues(),
            _derived_passing_orders(),
            _derived_passing_api_records(),
            _derived_passing_point_holds(),
            _derived_mapped_passing_groups(),
            _derived_equipment(),
            _derived_bodyweight_observations(),
            _derived_bodyweight_current(),
            _derived_confirmed_races(),
            _latest_profile_view("horse", "horse_id"),
            _latest_profile_view("jockey", "official_id"),
            _latest_profile_view("trainer", "official_id"),
            _latest_profile_view("owner", "official_id"),
        ]
    )
    return statements


def current_view_catalog() -> dict[str, str]:
    """Map semantic family/derivative names to the new registered views."""
    return {
        **{
            family: "research_current_" + family
            for family in _FAMILY_ORDER
            if family != "passing_groups"
        },
        "passing_groups": "research_current_mapped_passing_groups",
        "passing_group_observations": "research_current_passing_group_observations",
        "confirmed_races": "research_current_confirmed_races",
        "sections": "research_current_sections",
        "section_parse_issues": "research_current_section_parse_issues",
        "passing_orders": "research_current_passing_orders",
        "passing_api_records": "research_current_passing_api_records",
        "passing_point_holds": "research_current_passing_point_holds",
        "equipment": "research_current_equipment",
        "bodyweight_observations": "research_current_bodyweight_observations",
        "bodyweight": "research_current_bodyweight",
        "latest_horse_profile": "research_latest_horse_profile",
        "latest_jockey_profile": "research_latest_jockey_profile",
        "latest_trainer_profile": "research_latest_trainer_profile",
        "latest_owner_profile": "research_latest_owner_profile",
        "latest_public_cards": "research_latest_public_cards",
        "latest_entry_sheets": "research_latest_entry_sheets",
        "latest_race_schedule": "research_latest_race_schedule",
    }


def install_current_views(connection: Any) -> None:
    """Install the new ``research_current_*`` and ``research_latest_*`` views.

    The caller is responsible for choosing a writable refresh database that
    already contains the immutable baseline relations and
    ``refresh_event_records``.  This function does not attach databases,
    create tables, or touch the original legacy views.
    """
    for statement in view_statements():
        connection.execute(statement)

