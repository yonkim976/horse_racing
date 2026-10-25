CREATE TABLE daily_training_rider_role_supplements (
    observation_id VARCHAR PRIMARY KEY,
    raw_role VARCHAR NOT NULL CHECK (raw_role = '-'),
    role_supplement VARCHAR,
    role_supplement_status VARCHAR NOT NULL CHECK (
        role_supplement_status IN (
            'inferred_jockey_by_official_id_and_profile_period',
            'profile_period_boundary_hold'
        )
    ),
    rider_id VARCHAR NOT NULL,
    rider_name VARCHAR NOT NULL,
    event_date DATE NOT NULL,
    profile_start_date DATE,
    profile_end_date DATE,
    profile_evidence_json JSON NOT NULL,
    CHECK (
        (role_supplement_status = 'inferred_jockey_by_official_id_and_profile_period' AND role_supplement = '기수')
        OR
        (role_supplement_status = 'profile_period_boundary_hold' AND role_supplement IS NULL)
    )
);

INSERT INTO daily_training_rider_role_supplements (
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
WITH profile_rows AS (
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
                THEN 'inferred_jockey_by_official_id_and_profile_period'
            ELSE 'profile_period_boundary_hold'
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
FROM candidates;

CREATE OR REPLACE VIEW daily_training_rider_display AS
WITH base AS (
    SELECT linked.*, CASE  WHEN (((rider_type_raw = '기수') AND (rider_identity_status = 'exact_event_web_name_link') AND ("nullif"(main."trim"(rider_name_linked), '') IS NOT NULL) AND (rider_identity_status != 'source_conflict_hold'))) THEN (rider_name_linked) WHEN (((rider_type_raw = '기수') AND (rider_identity_status = 'exact_official_profile_id_name_link') AND ("nullif"(main."trim"(rider_name_linked), '') IS NOT NULL) AND (rider_identity_status != 'source_conflict_hold'))) THEN (rider_name_linked) WHEN ((main."trim"(COALESCE(rider_type_raw, '')) IN ('기수', '조교사', '조교보', '조교승인', '기수후보생'))) THEN (rider_type_raw) ELSE '기승자 미상' END AS rider_display_value, CASE  WHEN ((((rider_type_raw = '기수') AND (rider_identity_status = 'exact_event_web_name_link') AND ("nullif"(main."trim"(rider_name_linked), '') IS NOT NULL) AND (rider_identity_status != 'source_conflict_hold')) OR ((rider_type_raw = '기수') AND (rider_identity_status = 'exact_official_profile_id_name_link') AND ("nullif"(main."trim"(rider_name_linked), '') IS NOT NULL) AND (rider_identity_status != 'source_conflict_hold')))) THEN ('person_name') WHEN ((main."trim"(COALESCE(rider_type_raw, '')) IN ('기수', '조교사', '조교보', '조교승인', '기수후보생'))) THEN ('role') ELSE 'unknown' END AS rider_display_kind, CASE  WHEN (((rider_type_raw = '기수') AND (rider_identity_status = 'exact_event_web_name_link') AND ("nullif"(main."trim"(rider_name_linked), '') IS NOT NULL) AND (rider_identity_status != 'source_conflict_hold'))) THEN (rider_identity_status) WHEN (((rider_type_raw = '기수') AND (rider_identity_status = 'exact_official_profile_id_name_link') AND ("nullif"(main."trim"(rider_name_linked), '') IS NOT NULL) AND (rider_identity_status != 'source_conflict_hold'))) THEN (rider_identity_status) WHEN (((main."trim"(COALESCE(rider_type_raw, '')) IN ('기수', '조교사', '조교보', '조교승인', '기수후보생')) AND (main."trim"(COALESCE(rider_type_raw, '')) = '기수'))) THEN ('unconfirmed_jockey_role') WHEN ((main."trim"(COALESCE(rider_type_raw, '')) IN ('기수', '조교사', '조교보', '조교승인', '기수후보생'))) THEN ('rider_type_raw') WHEN ((("nullif"(main."trim"(COALESCE(rider_type_raw, '')), '') IS NULL) OR (main."trim"(rider_type_raw) = '-'))) THEN ('rider_type_missing_or_placeholder') ELSE 'unrecognized_rider_type_raw' END AS rider_display_basis FROM daily_training_rider_linked AS linked
)
SELECT
    base.* EXCLUDE (rider_display_value, rider_display_kind, rider_display_basis),
    CASE
        WHEN supplements.role_supplement_status = 'inferred_jockey_by_official_id_and_profile_period'
         AND NULLIF(TRIM(supplements.rider_name), '') IS NOT NULL
            THEN supplements.rider_name
        ELSE base.rider_display_value
    END AS rider_display_value,
    CASE
        WHEN supplements.role_supplement_status = 'inferred_jockey_by_official_id_and_profile_period'
         AND NULLIF(TRIM(supplements.rider_name), '') IS NOT NULL
            THEN 'person_name'
        ELSE base.rider_display_kind
    END AS rider_display_kind,
    CASE
        WHEN supplements.role_supplement_status IN (
            'inferred_jockey_by_official_id_and_profile_period', 'profile_period_boundary_hold'
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
LEFT JOIN daily_training_rider_role_supplements AS supplements USING (observation_id);
