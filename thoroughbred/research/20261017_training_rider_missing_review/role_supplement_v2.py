"""SQL generators for supplementary jockey-role evidence in daily training.

This module does not connect to DuckDB. The caller stages and applies the
returned SQL. The supplement preserves the observed ``'-'`` role and records
the inferred role separately, using official jockey profile date evidence.
"""

from __future__ import annotations

import re


SUPPLEMENT_TABLE = "daily_training_rider_role_supplements"
INFERRED_STATUS = "inferred_jockey_by_official_id_and_profile_period"
BOUNDARY_HOLD_STATUS = "profile_period_boundary_hold"


def create_table_sql() -> str:
    """Return DDL for one auditable supplement row per observation."""
    return f"""CREATE TABLE {SUPPLEMENT_TABLE} (
    observation_id VARCHAR PRIMARY KEY,
    raw_role VARCHAR NOT NULL CHECK (raw_role = '-'),
    role_supplement VARCHAR,
    role_supplement_status VARCHAR NOT NULL CHECK (
        role_supplement_status IN (
            '{INFERRED_STATUS}',
            '{BOUNDARY_HOLD_STATUS}'
        )
    ),
    rider_id VARCHAR NOT NULL,
    rider_name VARCHAR NOT NULL,
    event_date DATE NOT NULL,
    profile_start_date DATE,
    profile_end_date DATE,
    profile_evidence_json JSON NOT NULL,
    CHECK (
        (role_supplement_status = '{INFERRED_STATUS}' AND role_supplement = '기수')
        OR
        (role_supplement_status = '{BOUNDARY_HOLD_STATUS}' AND role_supplement IS NULL)
    )
);"""


def _population_select_sql() -> str:
    """Return the deterministic, read-only source SELECT used for insertion."""
    return f"""WITH profile_rows AS (
    SELECT
        p.*,
        TRY_STRPTIME(NULLIF(TRIM(p.profile_start_date_raw), ''), '%Y%m%d')::DATE
            AS parsed_profile_start_date,
        TRY_STRPTIME(NULLIF(TRIM(p.profile_end_date_raw), ''), '%Y%m%d')::DATE
            AS parsed_profile_end_date
    FROM person_reference_profile_snapshots AS p
    WHERE p.entity_type = 'jockey'
), profile_bounds AS (
    SELECT
        official_id_raw_string,
        MIN(parsed_profile_start_date) AS profile_start_date,
        MAX(parsed_profile_end_date) AS profile_end_date,
        TO_JSON(LIST(
            STRUCT_PACK(
                entity_type := entity_type,
                official_id_raw_string := official_id_raw_string,
                name_snapshot := name_snapshot,
                english_name_snapshot := english_name_snapshot,
                meet_query := meet_query,
                meet_label_raw := meet_label_raw,
                profile_start_date_raw := profile_start_date_raw,
                parsed_profile_start_date := parsed_profile_start_date,
                profile_end_date_raw := profile_end_date_raw,
                parsed_profile_end_date := parsed_profile_end_date,
                profile_part_raw := profile_part_raw,
                source_service := source_service,
                capture_date := capture_date,
                source_file := source_file,
                source_sha256 := source_sha256,
                source_page_no := source_page_no,
                source_item_index_within_page := source_item_index_within_page,
                relationship_time_rule := relationship_time_rule
            )
            ORDER BY source_service, capture_date, meet_query, source_file,
                     source_page_no, source_item_index_within_page
        )) AS profile_evidence_json
    FROM profile_rows
    GROUP BY official_id_raw_string
), candidates AS (
    SELECT
        d.observation_id,
        d.rider_type_raw AS raw_role,
        CASE
            WHEN b.profile_start_date IS NOT NULL
             AND d.event_date >= b.profile_start_date
             AND (b.profile_end_date IS NULL OR d.event_date <= b.profile_end_date)
                THEN '기수'
            ELSE NULL
        END AS role_supplement,
        CASE
            WHEN b.profile_start_date IS NOT NULL
             AND d.event_date >= b.profile_start_date
             AND (b.profile_end_date IS NULL OR d.event_date <= b.profile_end_date)
                THEN '{INFERRED_STATUS}'
            ELSE '{BOUNDARY_HOLD_STATUS}'
        END AS role_supplement_status,
        d.rider_id_raw AS rider_id,
        d.rider_name_linked AS rider_name,
        d.event_date,
        b.profile_start_date,
        b.profile_end_date,
        b.profile_evidence_json
    FROM daily_training_rider_display AS d
    JOIN profile_bounds AS b
      ON b.official_id_raw_string = d.rider_official_id_linked
    WHERE d.rider_display_kind = 'unknown'
      AND d.rider_type_raw = '-'
      AND d.rider_identity_status = 'exact_official_profile_id_name_link'
      AND NULLIF(TRIM(d.rider_id_raw), '') IS NOT NULL
      AND d.rider_id_raw = d.rider_official_id_linked
      AND NULLIF(TRIM(d.rider_name_linked), '') IS NOT NULL
)
SELECT
    observation_id,
    raw_role,
    role_supplement,
    role_supplement_status,
    rider_id,
    rider_name,
    event_date,
    profile_start_date,
    profile_end_date,
    profile_evidence_json
FROM candidates"""


def populate_table_sql() -> str:
    """Return INSERT SQL for eligible in-period rows and boundary holds."""
    return f"""INSERT INTO {SUPPLEMENT_TABLE} (
    observation_id,
    raw_role,
    role_supplement,
    role_supplement_status,
    rider_id,
    rider_name,
    event_date,
    profile_start_date,
    profile_end_date,
    profile_evidence_json
)
{_population_select_sql()};"""


def create_display_view_sql(original_display_sql: str) -> str:
    """Wrap the pinned display query, replacing its three display columns.

    ``original_display_sql`` must be the trusted SQL returned by the current
    ``display_rule.create_view_sql()``. Wrapping that query preserves all of
    its existing display policy; the supplemental status only overrides rows
    present in the dedicated evidence table.
    """
    match = re.match(
        r"(?is)^\s*CREATE\s+(?:OR\s+REPLACE\s+)?VIEW\s+"
        r"daily_training_rider_display\s+AS\s+",
        original_display_sql,
    )
    if match is None:
        raise ValueError(
            "original_display_sql must define daily_training_rider_display"
        )
    original_select = original_display_sql[match.end():].strip()
    if original_select.endswith(";"):
        original_select = original_select[:-1].rstrip()
    if not original_select:
        raise ValueError("original_display_sql has an empty SELECT body")

    return f"""CREATE OR REPLACE VIEW daily_training_rider_display AS
WITH base AS (
    {original_select}
)
SELECT
    base.* EXCLUDE (rider_display_value, rider_display_kind, rider_display_basis),
    CASE
        WHEN supplements.role_supplement_status = '{INFERRED_STATUS}'
         AND NULLIF(TRIM(supplements.rider_name), '') IS NOT NULL
            THEN supplements.rider_name
        ELSE base.rider_display_value
    END AS rider_display_value,
    CASE
        WHEN supplements.role_supplement_status = '{INFERRED_STATUS}'
         AND NULLIF(TRIM(supplements.rider_name), '') IS NOT NULL
            THEN 'person_name'
        ELSE base.rider_display_kind
    END AS rider_display_kind,
    CASE
        WHEN supplements.role_supplement_status IN (
            '{INFERRED_STATUS}', '{BOUNDARY_HOLD_STATUS}'
        ) THEN supplements.role_supplement_status
        ELSE base.rider_display_basis
    END AS rider_display_basis,
    supplements.role_supplement AS rider_role_supplement,
    supplements.role_supplement_status AS rider_role_supplement_status,
    COALESCE(
        supplements.role_supplement,
        NULLIF(NULLIF(TRIM(base.rider_type_raw), '-'), '')
    )
        AS rider_type_effective
FROM base
LEFT JOIN {SUPPLEMENT_TABLE} AS supplements USING (observation_id);"""


__all__ = [
    "BOUNDARY_HOLD_STATUS",
    "INFERRED_STATUS",
    "SUPPLEMENT_TABLE",
    "create_display_view_sql",
    "create_table_sql",
    "populate_table_sql",
]
