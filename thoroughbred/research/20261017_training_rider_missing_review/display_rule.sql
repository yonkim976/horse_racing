CREATE VIEW daily_training_rider_display AS
SELECT
    linked.*,
    CASE
        WHEN rider_type_raw = '기수'
        AND rider_identity_status = 'exact_event_web_name_link'
        AND NULLIF(TRIM(rider_name_linked), '') IS NOT NULL
        AND rider_identity_status <> 'source_conflict_hold' THEN rider_name_linked
        WHEN rider_type_raw = '기수'
        AND rider_identity_status = 'exact_official_profile_id_name_link'
        AND NULLIF(TRIM(rider_name_linked), '') IS NOT NULL
        AND rider_identity_status <> 'source_conflict_hold' THEN rider_name_linked
        WHEN TRIM(COALESCE(rider_type_raw, '')) IN ('기수', '조교사', '조교보', '조교승인', '기수후보생') THEN rider_type_raw
        ELSE '기승자 미상'
    END AS rider_display_value,
    CASE
        WHEN rider_type_raw = '기수'
        AND rider_identity_status = 'exact_event_web_name_link'
        AND NULLIF(TRIM(rider_name_linked), '') IS NOT NULL
        AND rider_identity_status <> 'source_conflict_hold' OR rider_type_raw = '기수'
        AND rider_identity_status = 'exact_official_profile_id_name_link'
        AND NULLIF(TRIM(rider_name_linked), '') IS NOT NULL
        AND rider_identity_status <> 'source_conflict_hold' THEN 'person_name'
        WHEN TRIM(COALESCE(rider_type_raw, '')) IN ('기수', '조교사', '조교보', '조교승인', '기수후보생') THEN 'role'
        ELSE 'unknown'
    END AS rider_display_kind,
    CASE
        WHEN rider_type_raw = '기수'
        AND rider_identity_status = 'exact_event_web_name_link'
        AND NULLIF(TRIM(rider_name_linked), '') IS NOT NULL
        AND rider_identity_status <> 'source_conflict_hold' THEN rider_identity_status
        WHEN rider_type_raw = '기수'
        AND rider_identity_status = 'exact_official_profile_id_name_link'
        AND NULLIF(TRIM(rider_name_linked), '') IS NOT NULL
        AND rider_identity_status <> 'source_conflict_hold' THEN rider_identity_status
        WHEN TRIM(COALESCE(rider_type_raw, '')) IN ('기수', '조교사', '조교보', '조교승인', '기수후보생') AND TRIM(COALESCE(rider_type_raw, '')) = '기수' THEN 'unconfirmed_jockey_role'
        WHEN TRIM(COALESCE(rider_type_raw, '')) IN ('기수', '조교사', '조교보', '조교승인', '기수후보생') THEN 'rider_type_raw'
        WHEN NULLIF(TRIM(COALESCE(rider_type_raw, '')), '') IS NULL
             OR TRIM(rider_type_raw) = '-' THEN 'rider_type_missing_or_placeholder'
        ELSE 'unrecognized_rider_type_raw'
    END AS rider_display_basis
FROM daily_training_rider_linked AS linked;
