-- Additive API78 equipment-history schema. Existing core objects are untouched.

CREATE TABLE equipment_api78_source_documents (
    source_inventory_row_id VARCHAR PRIMARY KEY,
    source_kind VARCHAR NOT NULL,
    source_document_ref VARCHAR NOT NULL,
    source_document_id VARCHAR NOT NULL,
    source_document_id_raw VARCHAR,
    ingestion_run_id VARCHAR,
    event_date VARCHAR,
    meet VARCHAR,
    page_no INTEGER,
    raw_path VARCHAR,
    sha256_expected VARCHAR,
    raw_sha256 VARCHAR,
    file_hash_valid BOOLEAN NOT NULL,
    payload_valid BOOLEAN NOT NULL,
    page_total_count BIGINT,
    page_size BIGINT,
    item_count BIGINT,
    requested_at_ms BIGINT,
    retrieved_at_ms BIGINT,
    http_status_code INTEGER,
    response_bytes BIGINT,
    run_source VARCHAR,
    run_data_type VARCHAR,
    run_started_at_ms BIGINT,
    run_completed_at_ms BIGINT,
    ingestion_status VARCHAR,
    request_identity_basis VARCHAR,
    observed_time_basis VARCHAR,
    validation_error VARCHAR,
    selected_for_canonical_snapshot BOOLEAN NOT NULL
);

CREATE TABLE equipment_api78_capture_batches (
    batch_id VARCHAR PRIMARY KEY,
    meet VARCHAR NOT NULL,
    race_date VARCHAR NOT NULL,
    ingestion_run_id VARCHAR,
    ingestion_status VARCHAR NOT NULL,
    source_document_refs VARCHAR NOT NULL,
    is_complete BOOLEAN NOT NULL,
    page_count INTEGER NOT NULL,
    page_numbers VARCHAR NOT NULL,
    api_total_count BIGINT,
    source_runner_count BIGINT NOT NULL,
    runner_rows_exported BIGINT NOT NULL,
    equipment_field_missing_count BIGINT NOT NULL,
    equipment_null_count BIGINT NOT NULL,
    equipment_blank_count BIGINT NOT NULL,
    equipment_nonblank_count BIGINT NOT NULL,
    observed_empty_count BIGINT NOT NULL,
    observed_value_count BIGINT NOT NULL,
    observed_unknown_count BIGINT NOT NULL,
    explicit_added_mark_count BIGINT NOT NULL,
    explicit_removed_mark_count BIGINT NOT NULL,
    linked_op_id_corroborated_count BIGINT NOT NULL,
    linked_core_key_name_only_count BIGINT NOT NULL,
    unresolved_identity_count BIGINT NOT NULL,
    validation_errors VARCHAR NOT NULL,
    requested_at_ms BIGINT,
    requested_at_kst VARCHAR,
    retrieved_at_ms BIGINT,
    retrieved_at_kst VARCHAR,
    capture_time_basis VARCHAR NOT NULL,
    selection_rule VARCHAR NOT NULL
);

CREATE TABLE equipment_api78_capture_pages (
    source_document_ref VARCHAR PRIMARY KEY,
    batch_id VARCHAR NOT NULL,
    meet VARCHAR NOT NULL,
    event_date VARCHAR NOT NULL,
    source_kind VARCHAR NOT NULL,
    source_document_id VARCHAR NOT NULL,
    ingestion_run_id VARCHAR,
    ingestion_run_status VARCHAR NOT NULL,
    page_no INTEGER NOT NULL,
    raw_path VARCHAR NOT NULL,
    raw_sha256 VARCHAR NOT NULL,
    requested_at_ms BIGINT,
    requested_at_kst VARCHAR,
    retrieved_at_ms BIGINT NOT NULL,
    retrieved_at_kst VARCHAR NOT NULL,
    http_status_code INTEGER NOT NULL,
    response_bytes BIGINT NOT NULL,
    request_identity_basis VARCHAR NOT NULL,
    observed_time_basis VARCHAR NOT NULL,
    total_count BIGINT,
    item_count BIGINT NOT NULL
);

CREATE TABLE equipment_api78_card_observations (
    observation_id VARCHAR PRIMARY KEY,
    batch_id VARCHAR NOT NULL,
    source_kind VARCHAR NOT NULL,
    source_document_ref VARCHAR NOT NULL,
    source_document_id VARCHAR NOT NULL,
    ingestion_run_id VARCHAR,
    ingestion_run_status VARCHAR NOT NULL,
    source_sha256 VARCHAR NOT NULL,
    page_no INTEGER NOT NULL,
    source_index_in_batch INTEGER NOT NULL,
    event_date VARCHAR NOT NULL,
    meet VARCHAR NOT NULL,
    race_no VARCHAR NOT NULL,
    horse_no VARCHAR NOT NULL,
    api_horse_name_raw VARCHAR NOT NULL,
    api_horse_name_normalized VARCHAR NOT NULL,
    equipment_raw VARCHAR,
    equipment_field_present BOOLEAN NOT NULL,
    equipment_is_null BOOLEAN NOT NULL,
    equipment_value_state VARCHAR NOT NULL,
    equipment_field_state VARCHAR NOT NULL,
    source_endpoint VARCHAR NOT NULL,
    capture_retrieved_at_ms BIGINT NOT NULL,
    capture_retrieved_at_kst VARCHAR NOT NULL,
    observed_time_basis VARCHAR NOT NULL,
    availability_status VARCHAR NOT NULL,
    physical_wear_status VARCHAR NOT NULL,
    link_status VARCHAR NOT NULL,
    link_method VARCHAR,
    link_reason VARCHAR,
    core_key_candidate_count INTEGER NOT NULL,
    core_key_name_match_count INTEGER NOT NULL,
    operational_key_candidate_count INTEGER NOT NULL,
    operational_key_name_match_count INTEGER NOT NULL,
    core_horse_name_raw_candidate VARCHAR,
    core_horse_name_normalized_candidate VARCHAR,
    operational_horse_name_raw_candidate VARCHAR,
    operational_horse_id_candidate VARCHAR,
    linked_core_meet VARCHAR,
    linked_core_event_date VARCHAR,
    linked_core_race_no VARCHAR,
    linked_core_horse_no VARCHAR,
    linked_core_horse_id VARCHAR,
    source_document_path VARCHAR NOT NULL,
    identity_match_evidence VARCHAR
);

CREATE TABLE equipment_api78_core_runner_ledger (
    core_meet VARCHAR NOT NULL,
    core_event_date VARCHAR NOT NULL,
    core_race_no VARCHAR NOT NULL,
    core_horse_no VARCHAR NOT NULL,
    core_horse_id VARCHAR NOT NULL,
    core_horse_name_raw VARCHAR NOT NULL,
    core_horse_name_normalized VARCHAR NOT NULL,
    equipment_observation_state VARCHAR NOT NULL,
    selected_batch_id VARCHAR,
    selected_batch_source_kind VARCHAR,
    selected_batch_run_status VARCHAR,
    api78_observation_id_candidate VARCHAR,
    api78_link_status_candidate VARCHAR,
    api78_link_reason_candidate VARCHAR,
    api78_horse_name_raw_candidate VARCHAR,
    api78_equipment_raw_candidate VARCHAR,
    api78_equipment_value_state_candidate VARCHAR,
    api78_source_document_ref_candidate VARCHAR,
    api78_source_sha256_candidate VARCHAR,
    PRIMARY KEY (core_meet, core_event_date, core_race_no, core_horse_no, core_horse_id)
);

CREATE TABLE equipment_api78_card_tokens (
    observation_id VARCHAR NOT NULL,
    token_position INTEGER NOT NULL,
    token_raw VARCHAR NOT NULL,
    equipment_name_raw VARCHAR NOT NULL,
    mark_status VARCHAR NOT NULL,
    PRIMARY KEY (observation_id, token_position)
);

CREATE TABLE equipment_api78_identity_conflicts (
    observation_id VARCHAR PRIMARY KEY,
    meet VARCHAR NOT NULL,
    event_date VARCHAR NOT NULL,
    race_no VARCHAR NOT NULL,
    horse_no VARCHAR NOT NULL,
    api_horse_name_raw VARCHAR NOT NULL,
    link_status VARCHAR NOT NULL,
    link_method VARCHAR,
    link_reason VARCHAR,
    conflict_class VARCHAR NOT NULL,
    core_key_candidate_count INTEGER NOT NULL,
    core_key_name_match_count INTEGER NOT NULL,
    operational_key_candidate_count INTEGER NOT NULL,
    operational_key_name_match_count INTEGER NOT NULL,
    operational_horse_id_candidate VARCHAR,
    identity_match_evidence VARCHAR,
    source_document_ref VARCHAR NOT NULL,
    source_document_path VARCHAR NOT NULL,
    source_sha256 VARCHAR NOT NULL
);

CREATE VIEW equipment_api78_latest_card_observations AS
SELECT *
FROM equipment_api78_card_observations;

CREATE VIEW equipment_api78_active_declared AS
SELECT
    o.observation_id,
    o.meet,
    o.event_date AS result_date,
    o.race_no,
    o.horse_no,
    o.linked_core_horse_id AS horse_id,
    t.token_position,
    t.token_raw,
    t.equipment_name_raw,
    t.mark_status,
    o.equipment_raw,
    o.capture_retrieved_at_kst AS observed_at_kst,
    o.observed_time_basis AS observed_at_basis,
    o.source_document_path AS raw_path,
    o.source_sha256 AS raw_sha256,
    o.link_status AS identity_match_status,
    o.link_method AS identity_match_method,
    o.identity_match_evidence,
    o.availability_status,
    o.physical_wear_status,
    o.source_endpoint
FROM equipment_api78_latest_card_observations AS o
JOIN equipment_api78_card_tokens AS t USING (observation_id)
WHERE t.mark_status <> 'removed';

CREATE VIEW equipment_core_coverage AS
WITH api78_latest AS (
    SELECT *
    FROM equipment_api78_latest_card_observations
    WHERE linked_core_horse_id IS NOT NULL
      AND link_status IN ('linked_op_id_corroborated', 'linked_core_key_name_only')
),
joined AS (
    SELECT
        c.source_meet AS meet,
        c.result_date,
        c.result_race_no AS race_no,
        c.horse_program_no_raw AS horse_no,
        c.horse_id_raw AS horse_id,
        c.horse_name_raw AS horse_name_raw,
        l.equipment_observation_state AS core_ledger_state,
        l.api78_observation_id_candidate,
        l.api78_link_status_candidate,
        l.api78_link_reason_candidate,
        l.api78_horse_name_raw_candidate,
        l.api78_equipment_raw_candidate,
        a.observation_id AS api78_observation_id,
        a.equipment_raw AS api78_equipment_raw,
        a.equipment_field_present AS api78_equipment_field_present,
        a.equipment_is_null AS api78_equipment_is_null,
        a.equipment_value_state AS api78_equipment_value_state,
        a.equipment_field_state AS api78_equipment_field_state,
        a.capture_retrieved_at_kst AS api78_observed_at_kst,
        a.observed_time_basis AS api78_observed_time_basis,
        a.availability_status AS api78_availability_status,
        a.physical_wear_status AS api78_physical_wear_status,
        a.source_endpoint AS api78_source_endpoint,
        a.source_document_path AS api78_raw_path,
        a.source_sha256 AS api78_raw_sha256,
        s.meet AS score_fallback_meet,
        s.equipment_raw AS score_fallback_equipment_raw,
        s.observed_at_kst AS score_fallback_observed_at_kst,
        s.observed_at_basis AS score_fallback_observed_time_basis,
        s.raw_path AS score_fallback_raw_path,
        s.raw_sha256 AS score_fallback_raw_sha256,
        s.availability_status AS score_fallback_availability_status,
        s.source_url AS score_fallback_source_endpoint
    FROM confirmed_runners AS c
    LEFT JOIN equipment_api78_core_runner_ledger AS l
      ON l.core_meet = c.source_meet
     AND l.core_event_date = c.result_date
     AND l.core_race_no = c.result_race_no
     AND l.core_horse_no = c.horse_program_no_raw
     AND l.core_horse_id = c.horse_id_raw
    LEFT JOIN api78_latest AS a
      ON a.linked_core_meet = c.source_meet
     AND a.linked_core_event_date = c.result_date
     AND a.linked_core_race_no = c.result_race_no
     AND a.linked_core_horse_no = c.horse_program_no_raw
     AND a.linked_core_horse_id = c.horse_id_raw
    LEFT JOIN equipment_score_supplement AS s
      ON s.meet = c.source_meet
     AND s.result_date = c.result_date
     AND s.race_no = c.result_race_no
     AND s.horse_no = c.horse_program_no_raw
     AND s.horse_id = c.horse_id_raw
)
SELECT
    *,
    CASE
        WHEN api78_observation_id IS NOT NULL AND api78_equipment_field_state = 'observed_empty'
            THEN 'api78_observed_empty'
        WHEN api78_observation_id IS NOT NULL AND api78_equipment_field_state = 'observed_value'
            THEN 'api78_observed_value'
        WHEN api78_observation_id IS NOT NULL AND api78_equipment_field_state = 'dash_placeholder'
            THEN 'api78_observed_dash_placeholder'
        WHEN api78_observation_id IS NOT NULL AND api78_equipment_field_state = 'json_null'
            THEN 'api78_observed_null'
        WHEN api78_observation_id IS NOT NULL AND api78_equipment_field_state = 'field_missing'
            THEN 'api78_observed_field_missing'
        WHEN api78_observation_id IS NOT NULL
            THEN 'api78_observed_unknown'
        WHEN score_fallback_meet IS NOT NULL
            THEN 'api78_unobserved_official_score_fallback'
        WHEN core_ledger_state = 'unresolved_api78_identity_candidate'
            THEN 'api78_identity_unresolved_candidate'
        WHEN core_ledger_state = 'ambiguous_api78_exact_key'
            THEN 'api78_ambiguous_exact_key'
        WHEN core_ledger_state = 'runner_absent_from_complete_api78_card'
            THEN 'api78_runner_absent_from_complete_card'
        WHEN core_ledger_state = 'no_complete_api78_batch_for_date_meet'
            THEN 'api78_no_complete_batch_for_date_meet'
        ELSE 'api78_unobserved'
    END AS coverage_status,
    core_ledger_state AS source_coverage_state,
    CASE
        WHEN api78_observation_id IS NOT NULL THEN 'API78'
        WHEN score_fallback_meet IS NOT NULL THEN 'KRA_official_score_html'
        ELSE NULL
    END AS selected_source,
    CASE
        WHEN api78_observation_id IS NOT NULL THEN api78_equipment_raw
        WHEN score_fallback_meet IS NOT NULL THEN score_fallback_equipment_raw
        ELSE NULL
    END AS selected_equipment_raw,
    CASE
        WHEN api78_observation_id IS NOT NULL THEN api78_observed_at_kst
        WHEN score_fallback_meet IS NOT NULL THEN score_fallback_observed_at_kst
        ELSE NULL
    END AS selected_observed_at_kst,
    CASE
        WHEN api78_observation_id IS NOT NULL THEN api78_observed_time_basis
        WHEN score_fallback_meet IS NOT NULL THEN score_fallback_observed_time_basis
        ELSE NULL
    END AS selected_observed_time_basis,
    CASE
        WHEN api78_observation_id IS NOT NULL THEN api78_raw_path
        WHEN score_fallback_meet IS NOT NULL THEN score_fallback_raw_path
        ELSE NULL
    END AS selected_raw_path,
    CASE
        WHEN api78_observation_id IS NOT NULL THEN api78_raw_sha256
        WHEN score_fallback_meet IS NOT NULL THEN score_fallback_raw_sha256
        ELSE NULL
    END AS selected_raw_sha256,
    CASE
        WHEN api78_observation_id IS NOT NULL THEN api78_availability_status
        WHEN score_fallback_meet IS NOT NULL THEN score_fallback_availability_status
        ELSE 'unobserved'
    END AS availability_status,
    CASE
        WHEN api78_observation_id IS NOT NULL THEN api78_physical_wear_status
        ELSE 'unknown'
    END AS physical_wear_status,
    CASE
        WHEN api78_observation_id IS NOT NULL THEN api78_source_endpoint
        WHEN score_fallback_meet IS NOT NULL THEN score_fallback_source_endpoint
        ELSE NULL
    END AS selected_source_endpoint
FROM joined;

CREATE VIEW equipment_declared_union_fallback AS
SELECT
    'API78' AS source,
    a.meet,
    a.result_date,
    a.race_no,
    a.horse_no,
    a.horse_id,
    a.token_position,
    a.token_raw,
    a.equipment_name_raw,
    a.mark_status,
    a.equipment_raw,
    a.observed_at_kst,
    a.observed_at_basis,
    a.raw_path,
    a.raw_sha256,
    a.observation_id AS source_observation_id,
    a.availability_status,
    a.physical_wear_status,
    a.source_endpoint
FROM equipment_api78_active_declared AS a
WHERE a.horse_id IS NOT NULL
UNION ALL
SELECT
    'KRA_official_score_html' AS source,
    s.meet,
    s.result_date,
    s.race_no,
    s.horse_no,
    s.horse_id,
    s.token_position,
    s.token_raw,
    s.equipment_name_raw,
    s.mark_status,
    o.equipment_raw,
    s.observed_at_kst,
    s.observed_at_basis,
    s.raw_path,
    s.raw_sha256,
    NULL::VARCHAR AS source_observation_id,
    o.availability_status,
    'unknown' AS physical_wear_status,
    o.source_url AS source_endpoint
FROM equipment_score_supplement_active_declared AS s
JOIN equipment_score_supplement AS o
  ON o.meet = s.meet
 AND o.result_date = s.result_date
 AND o.race_no = s.race_no
 AND o.horse_no = s.horse_no
 AND o.horse_id = s.horse_id
WHERE NOT EXISTS (
    SELECT 1
    FROM equipment_api78_latest_card_observations AS a
    WHERE a.link_status IN ('linked_op_id_corroborated', 'linked_core_key_name_only')
      AND a.linked_core_meet = s.meet
      AND a.linked_core_event_date = s.result_date
      AND a.linked_core_race_no = s.race_no
      AND a.linked_core_horse_no = s.horse_no
      AND a.linked_core_horse_id = s.horse_id
);
