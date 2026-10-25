"""SQL for the rider-facing display projection over linked daily training.

This module only returns SQL text. It never opens a database or changes data.
The source view remains the record of raw values, links, evidence, and holds.
"""

from __future__ import annotations


def create_view_sql() -> str:
    """Return SQL for a display view that preserves all linked-view columns.

    A person's name is displayable only for a jockey row with one of the two
    explicitly accepted name evidence statuses and a non-empty name. Conflict
    holds remain non-personal displays even if inconsistent evidence appears.
    """
    profile_person = """rider_type_raw = '기수'
        AND rider_identity_status = 'exact_official_profile_id_name_link'
        AND NULLIF(TRIM(rider_name_linked), '') IS NOT NULL
        AND rider_identity_status <> 'source_conflict_hold'"""
    event_person = """rider_type_raw = '기수'
        AND rider_identity_status = 'exact_event_web_name_link'
        AND NULLIF(TRIM(rider_name_linked), '') IS NOT NULL
        AND rider_identity_status <> 'source_conflict_hold'"""
    known_role = "TRIM(COALESCE(rider_type_raw, '')) IN ('기수', '조교사', '조교보', '조교승인', '기수후보생')"
    role_is_jockey = "TRIM(COALESCE(rider_type_raw, '')) = '기수'"

    return f"""CREATE VIEW daily_training_rider_display AS
SELECT
    linked.*,
    CASE
        WHEN {event_person} THEN rider_name_linked
        WHEN {profile_person} THEN rider_name_linked
        WHEN {known_role} THEN rider_type_raw
        ELSE '기승자 미상'
    END AS rider_display_value,
    CASE
        WHEN {event_person} OR {profile_person} THEN 'person_name'
        WHEN {known_role} THEN 'role'
        ELSE 'unknown'
    END AS rider_display_kind,
    CASE
        WHEN {event_person} THEN rider_identity_status
        WHEN {profile_person} THEN rider_identity_status
        WHEN {known_role} AND {role_is_jockey} THEN 'unconfirmed_jockey_role'
        WHEN {known_role} THEN 'rider_type_raw'
        WHEN NULLIF(TRIM(COALESCE(rider_type_raw, '')), '') IS NULL
             OR TRIM(rider_type_raw) = '-' THEN 'rider_type_missing_or_placeholder'
        ELSE 'unrecognized_rider_type_raw'
    END AS rider_display_basis
FROM daily_training_rider_linked AS linked;"""


__all__ = ["create_view_sql"]
