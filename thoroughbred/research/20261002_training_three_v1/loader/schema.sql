-- Additive retrospective training observation schema. Existing core objects stay untouched.

CREATE TABLE training_raw_observations (
    dataset VARCHAR NOT NULL,
    observation_id VARCHAR NOT NULL,
    event_date DATE NOT NULL,
    meet VARCHAR NOT NULL,
    official_horse_id VARCHAR,
    raw_name VARCHAR,
    raw_path VARCHAR NOT NULL,
    raw_sha256 VARCHAR NOT NULL,
    source_page_no INTEGER,
    source_row_no INTEGER,
    source_captured_at TIMESTAMP,
    capture_basis VARCHAR NOT NULL,
    endpoint VARCHAR NOT NULL,
    raw_payload_json VARCHAR NOT NULL,
    typed_fields_json VARCHAR NOT NULL,
    link_status VARCHAR NOT NULL,
    linked_core_horse_id VARCHAR,
    qa_flags_json VARCHAR NOT NULL,
    capture_id VARCHAR NOT NULL,
    availability_status VARCHAR NOT NULL,
    historical_prerace_eligibility_verified BOOLEAN NOT NULL,
    physical_venue_status VARCHAR NOT NULL
);

CREATE TABLE training_capture_coverage (
    dataset VARCHAR NOT NULL,
    event_date DATE NOT NULL,
    meet VARCHAR NOT NULL,
    coverage_status VARCHAR NOT NULL,
    selected_capture_id VARCHAR,
    selection_rule VARCHAR NOT NULL,
    coverage_basis VARCHAR NOT NULL,
    expected_rows BIGINT,
    observed_rows BIGINT NOT NULL
);

CREATE TABLE training_source_files (
    dataset VARCHAR NOT NULL,
    raw_path VARCHAR NOT NULL,
    raw_sha256 VARCHAR NOT NULL,
    source_page_no INTEGER,
    source_row_count BIGINT NOT NULL,
    page_total_count BIGINT,
    page_item_count BIGINT,
    capture_id VARCHAR NOT NULL,
    source_captured_at_utc TIMESTAMP,
    requested_at_utc TIMESTAMP,
    retrieved_at_utc TIMESTAMP,
    capture_basis VARCHAR NOT NULL,
    endpoint VARCHAR NOT NULL,
    is_selected BOOLEAN NOT NULL,
    hash_check_status VARCHAR NOT NULL,
    source_metadata_json VARCHAR NOT NULL
);

CREATE VIEW daily_training_raw AS
SELECT
    o.*,
    json_extract_string(o.typed_fields_json, '$.hrNo') AS horse_id_raw,
    json_extract_string(o.typed_fields_json, '$.hrName') AS horse_name_raw,
    json_extract_string(o.typed_fields_json, '$.meet') AS meet_raw,
    json_extract_string(o.typed_fields_json, '$.trDate') AS training_date_raw,
    json_extract_string(o.typed_fields_json, '$.part') AS stable_part_raw,
    json_extract_string(o.typed_fields_json, '$.partNo') AS stable_number_raw,
    json_extract_string(o.typed_fields_json, '$.trName') AS trainer_name_raw,
    json_extract_string(o.typed_fields_json, '$.prGubun') AS rider_type_raw,
    json_extract_string(o.typed_fields_json, '$.prNo') AS rider_id_raw,
    json_extract_string(o.typed_fields_json, '$.stTime') AS started_at_raw,
    json_extract_string(o.typed_fields_json, '$.spTime') AS ended_at_raw,
    json_extract_string(o.typed_fields_json, '$.trTerm') AS duration_seconds_raw,
    json_extract(o.typed_fields_json, '$.trTerm') AS duration_seconds_raw_json,
    json_exists(o.typed_fields_json, '$.trTerm') AS duration_seconds_field_present,
    json_type(o.typed_fields_json, '$.trTerm') AS duration_seconds_json_type,
    json_extract_string(o.typed_fields_json, '$.run1Cnt') AS canter_count_raw,
    json_extract(o.typed_fields_json, '$.run1Cnt') AS canter_count_raw_json,
    json_exists(o.typed_fields_json, '$.run1Cnt') AS canter_count_field_present,
    json_type(o.typed_fields_json, '$.run1Cnt') AS canter_count_json_type,
    json_extract_string(o.typed_fields_json, '$.run2Cnt') AS gallop_count_raw,
    json_extract(o.typed_fields_json, '$.run2Cnt') AS gallop_count_raw_json,
    json_exists(o.typed_fields_json, '$.run2Cnt') AS gallop_count_field_present,
    json_type(o.typed_fields_json, '$.run2Cnt') AS gallop_count_json_type,
    json_extract_string(o.typed_fields_json, '$.chulGubun') AS entry_plan_raw,
    'retrospective_training_observation_not_verified_pre_race' AS availability_status_label,
    FALSE AS historical_14_00_publication_inferred
FROM training_raw_observations AS o
WHERE o.dataset = 'daily_training';

CREATE VIEW start_training_raw AS
SELECT
    o.*,
    json_extract_string(o.typed_fields_json, '$.hrNo') AS horse_id_raw,
    json_extract_string(o.typed_fields_json, '$.hrName') AS horse_name_raw,
    json_extract_string(o.typed_fields_json, '$.meet') AS meet_raw,
    json_extract_string(o.typed_fields_json, '$.trDate') AS training_date_raw,
    json_extract_string(o.typed_fields_json, '$.part') AS stable_part_raw,
    json_extract_string(o.typed_fields_json, '$.partNo') AS stable_number_raw,
    json_extract_string(o.typed_fields_json, '$.prName') AS rider_name_raw,
    json_extract_string(o.typed_fields_json, '$.remark') AS remark_raw,
    json_extract_string(o.typed_fields_json, '$.anonymous_occurrence_ordinal') AS anonymous_occurrence_no,
    FALSE AS occurrence_no_is_event_id,
    FALSE AS occurrence_no_is_chronological,
    'retrospective_training_observation_not_verified_pre_race' AS availability_status_label,
    FALSE AS historical_14_00_publication_inferred
FROM training_raw_observations AS o
WHERE o.dataset = 'start_training';

CREATE VIEW swim_training_raw AS
SELECT
    o.*,
    json_extract_string(o.typed_fields_json, '$.hrNo') AS horse_id_raw,
    json_extract_string(o.typed_fields_json, '$.hrName') AS horse_name_raw,
    json_extract_string(o.typed_fields_json, '$.meet') AS meet_raw,
    json_extract_string(o.typed_fields_json, '$.trDate') AS training_date_raw,
    json_extract_string(o.typed_fields_json, '$.cnt') AS cnt_raw,
    json_extract(o.typed_fields_json, '$.cnt') AS cnt_raw_json,
    json_exists(o.typed_fields_json, '$.cnt') AS cnt_field_present,
    json_type(o.typed_fields_json, '$.cnt') AS cnt_json_type,
    json_extract_string(o.typed_fields_json, '$.horsepart') AS horsepart_raw,
    json_extract_string(o.typed_fields_json, '$.horsepartMemo') AS horsepart_memo_raw,
    json_extract_string(o.typed_fields_json, '$.trpart') AS trpart_raw,
    json_extract_string(o.typed_fields_json, '$.trName') AS trainer_name_raw,
    'count_unit_unresolved' AS cnt_unit_status,
    'retrospective_training_observation_not_verified_pre_race' AS availability_status_label,
    FALSE AS historical_14_00_publication_inferred
FROM training_raw_observations AS o
WHERE o.dataset = 'swim_training';

CREATE VIEW training_observation_qa AS
SELECT
    o.dataset,
    o.observation_id,
    o.event_date,
    o.meet,
    o.official_horse_id,
    o.raw_name,
    o.raw_path,
    o.raw_sha256,
    o.source_page_no,
    o.source_row_no,
    o.source_captured_at,
    o.capture_basis,
    o.endpoint,
    o.link_status,
    o.linked_core_horse_id,
    o.qa_flags_json,
    o.availability_status,
    o.historical_prerace_eligibility_verified,
    o.physical_venue_status,
    json_extract(qa_flags_json, '$') AS qa_flags_json_value,
    CASE
        WHEN o.dataset = 'daily_training' THEN json_object(
            'official_horse_id', o.official_horse_id,
            'meet', o.meet,
            'event_date', CAST(o.event_date AS VARCHAR),
            'stTime', json_extract(o.typed_fields_json, '$.stTime'),
            'spTime', json_extract(o.typed_fields_json, '$.spTime')
        )
        ELSE NULL
    END AS natural_key_json,
    CASE
        WHEN o.dataset = 'start_training' THEN 'api22_storage_occurrence_not_event_identity'
        WHEN o.dataset = 'swim_training' THEN 'api216_source_key_review_required'
        WHEN o.dataset = 'daily_training' THEN 'api18_source_time_key_review_required'
        ELSE 'unknown_dataset'
    END AS natural_key_qa_basis,
    CASE
        WHEN o.dataset IN ('start_training', 'swim_training') THEN json_object(
            'official_horse_id', o.official_horse_id,
            'meet', o.meet,
            'event_date', CAST(o.event_date AS VARCHAR)
        )
        ELSE NULL
    END AS observation_group_json,
    CASE
        WHEN o.dataset = 'start_training' THEN 'horse_meet_date_observation_group_only'
        WHEN o.dataset = 'swim_training' THEN 'horse_meet_date_observation_group_only'
        ELSE NULL
    END AS observation_group_status,
    'retrospective_training_observation_not_verified_pre_race' AS availability_status_label,
    FALSE AS historical_14_00_publication_inferred
FROM training_raw_observations AS o;

CREATE VIEW training_date_coverage AS
WITH actual AS (
    SELECT dataset, event_date, meet, count(*) AS actual_observation_rows
    FROM training_raw_observations
    GROUP BY dataset, event_date, meet
)
SELECT
    c.dataset,
    c.event_date,
    c.meet,
    c.coverage_status,
    c.selected_capture_id,
    c.selection_rule,
    c.coverage_basis,
    c.expected_rows,
    c.observed_rows AS inventory_observed_rows,
    coalesce(a.actual_observation_rows, 0) AS actual_observation_rows,
    c.observed_rows <> coalesce(a.actual_observation_rows, 0) AS inventory_count_mismatch
FROM training_capture_coverage AS c
LEFT JOIN actual AS a USING (dataset, event_date, meet);

CREATE VIEW training_source_entities AS
SELECT
    dataset,
    official_horse_id,
    raw_name,
    linked_core_horse_id,
    link_status,
    count(*) AS observation_rows,
    min(event_date) AS first_event_date,
    max(event_date) AS last_event_date,
    count(DISTINCT meet) AS observed_meets
FROM training_raw_observations
GROUP BY dataset, official_horse_id, raw_name, linked_core_horse_id, link_status;
