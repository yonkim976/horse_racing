-- Additive API21_1 starting-exam research schema.

CREATE TABLE starting_exam_observations (
    dataset VARCHAR NOT NULL,
    observation_id VARCHAR NOT NULL,
    event_date DATE NOT NULL,
    meet VARCHAR NOT NULL,
    official_horse_id VARCHAR,
    raw_name VARCHAR,
    raw_path VARCHAR NOT NULL,
    raw_sha256 VARCHAR NOT NULL,
    source_page_no INTEGER NOT NULL,
    source_row_no INTEGER NOT NULL,
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

CREATE TABLE starting_exam_source_files (
    dataset VARCHAR NOT NULL,
    meet VARCHAR NOT NULL,
    capture_year INTEGER NOT NULL,
    capture_id VARCHAR NOT NULL,
    source_page_no INTEGER,
    raw_path VARCHAR,
    raw_sha256 VARCHAR,
    source_row_count BIGINT NOT NULL,
    page_total_count BIGINT,
    page_item_count BIGINT,
    page_size BIGINT,
    requested_at_utc TIMESTAMP,
    retrieved_at_utc TIMESTAMP,
    source_captured_at_utc TIMESTAMP,
    status_code INTEGER,
    result_code VARCHAR,
    failure_class VARCHAR,
    is_selected BOOLEAN NOT NULL,
    hash_check_status VARCHAR NOT NULL,
    source_metadata_json VARCHAR NOT NULL
);

CREATE TABLE starting_exam_partition_coverage (
    dataset VARCHAR NOT NULL,
    capture_year INTEGER NOT NULL,
    meet VARCHAR NOT NULL,
    coverage_status VARCHAR NOT NULL,
    selected_capture_id VARCHAR,
    expected_rows BIGINT,
    observed_rows BIGINT NOT NULL,
    page_size BIGINT,
    page_count BIGINT NOT NULL,
    failure_class VARCHAR,
    started_at_utc TIMESTAMP,
    finished_at_utc TIMESTAMP,
    coverage_basis VARCHAR NOT NULL
);

CREATE VIEW starting_exam_results AS
WITH raw AS (
    SELECT
        o.*,
        json_extract(o.typed_fields_json, '$.meet') AS source_meet_raw_json,
        json_extract(o.typed_fields_json, '$.trainDate') AS train_date_raw_json,
        json_extract(o.typed_fields_json, '$.daySerial') AS day_serial_raw_json,
        json_extract(o.typed_fields_json, '$.trainNo') AS train_no_raw_json,
        json_extract(o.typed_fields_json, '$.chulNo') AS horse_program_no_raw_json,
        json_extract(o.typed_fields_json, '$.hrName') AS horse_name_raw_json,
        json_extract(o.typed_fields_json, '$.hrNo') AS horse_id_raw_json,
        json_extract(o.typed_fields_json, '$.name') AS country_name_raw_json,
        json_extract(o.typed_fields_json, '$.sex') AS sex_raw_json,
        json_extract(o.typed_fields_json, '$.age') AS age_raw_json,
        json_extract(o.typed_fields_json, '$.rider') AS rider_text_raw_json,
        json_extract(o.typed_fields_json, '$.trName') AS trainer_name_raw_json,
        json_extract(o.typed_fields_json, '$.trNo') AS trainer_id_raw_json,
        json_extract(o.typed_fields_json, '$.owName') AS owner_name_raw_json,
        json_extract(o.typed_fields_json, '$.owNo') AS owner_id_raw_json,
        json_extract(o.typed_fields_json, '$.passFlag') AS pass_flag_raw_json,
        json_extract(o.typed_fields_json, '$.reason') AS reason_raw_json,
        json_extract(o.typed_fields_json, '$.nopassReason') AS no_pass_reason_raw_json,
        json_extract_string(o.typed_fields_json, '$.hrNo') AS source_horse_id,
        json_extract_string(o.typed_fields_json, '$.trNo') AS source_trainer_id,
        json_extract_string(o.typed_fields_json, '$.trName') AS source_trainer_name,
        json_extract_string(o.typed_fields_json, '$.owNo') AS source_owner_id,
        json_extract_string(o.typed_fields_json, '$.owName') AS source_owner_name,
        json_extract_string(o.typed_fields_json, '$.rider') AS rider_text
    FROM starting_exam_observations AS o
    WHERE o.dataset = 'starting_exam'
)
SELECT
    r.*,
    CASE WHEN h.entity_id_official_string IS NOT NULL
         THEN 'exact_core_roster_match'
         WHEN r.official_horse_id IS NULL OR r.official_horse_id = ''
         THEN 'missing_official_id'
         ELSE 'unmatched_official_id' END AS horse_entity_link_status,
    CASE WHEN r.source_trainer_id IS NULL OR r.source_trainer_id = ''
         THEN 'missing_official_id'
         WHEN r.source_trainer_id = '-' OR r.source_trainer_id = '0AAAAA'
              OR r.source_trainer_name = '휴양마'
         THEN 'placeholder_source_value'
         WHEN t.entity_id_official_string IS NOT NULL
         THEN 'exact_core_roster_match'
         ELSE 'unmatched_official_id' END AS trainer_entity_link_status,
    CASE WHEN r.source_trainer_id = '-' OR r.source_trainer_id = '0AAAAA'
              OR r.source_trainer_name = '휴양마'
         THEN 'placeholder_source_value'
         WHEN r.source_trainer_id IS NULL OR r.source_trainer_id = ''
         THEN 'missing_source_id'
         ELSE 'not_placeholder' END AS trainer_placeholder_status,
    CASE WHEN r.source_owner_id IS NULL OR r.source_owner_id = ''
         THEN 'missing_official_id'
         WHEN r.source_owner_id = '-' OR r.source_owner_name = '-'
         THEN 'placeholder_source_value'
         WHEN ow.entity_id_official_string IS NOT NULL
         THEN 'exact_core_roster_match'
         ELSE 'unmatched_official_id' END AS owner_entity_link_status,
    CASE WHEN r.source_owner_id = '-' OR r.source_owner_name = '-'
         THEN 'placeholder_source_value'
         WHEN r.source_owner_id IS NULL OR r.source_owner_id = ''
         THEN 'missing_source_id'
         ELSE 'not_placeholder' END AS owner_placeholder_status,
    'rider_text_only_no_official_jockey_id_link' AS rider_link_status,
    'retrospective_starting_exam_not_verified_pre_race' AS availability_status_label,
    FALSE AS pass_flag_adjudication_performed,
    FALSE AS physical_venue_adjudicated
FROM raw AS r
LEFT JOIN entity_reference_roster AS h
  ON h.entity_type='horse' AND h.entity_id_official_string=r.official_horse_id
LEFT JOIN entity_reference_roster AS t
  ON t.entity_type='trainer' AND t.entity_id_official_string=r.source_trainer_id
LEFT JOIN entity_reference_roster AS ow
  ON ow.entity_type='owner' AND ow.entity_id_official_string=r.source_owner_id;

CREATE VIEW starting_exam_sessions AS
SELECT
    event_date,
    meet,
    json_extract_string(typed_fields_json, '$.daySerial') AS day_serial_raw,
    json_extract_string(typed_fields_json, '$.trainNo') AS train_no_raw,
    count(*) AS observation_rows,
    count(DISTINCT official_horse_id) AS distinct_horse_ids,
    'source date/meet/daySerial/trainNo grouping only, not a race' AS grouping_semantics
FROM starting_exam_observations
WHERE dataset='starting_exam'
GROUP BY event_date, meet,
         json_extract_string(typed_fields_json, '$.daySerial'),
         json_extract_string(typed_fields_json, '$.trainNo');

CREATE VIEW starting_exam_qa AS
SELECT
    observation_id, event_date, meet, official_horse_id, raw_name,
    raw_path, raw_sha256, source_page_no, source_row_no, source_captured_at,
    capture_id, link_status, linked_core_horse_id, qa_flags_json,
    json_object('meet', json_extract(typed_fields_json, '$.meet'),
                'trainDate', json_extract(typed_fields_json, '$.trainDate'),
                'daySerial', json_extract(typed_fields_json, '$.daySerial'),
                'trainNo', json_extract(typed_fields_json, '$.trainNo'),
                'chulNo', json_extract(typed_fields_json, '$.chulNo'),
                'hrNo', json_extract(typed_fields_json, '$.hrNo')) AS source_natural_key_json,
    json_extract(typed_fields_json, '$.passFlag') AS pass_flag_raw_json,
    availability_status, historical_prerace_eligibility_verified,
    physical_venue_status,
    'raw judgment values retained without pass/fail promotion' AS judgment_qa_basis
FROM starting_exam_observations
WHERE dataset='starting_exam';

CREATE VIEW starting_exam_date_coverage AS
WITH calendar AS (
    SELECT gs::DATE AS event_date, meet::VARCHAR AS meet
    FROM generate_series(DATE '2010-01-01', DATE '2026-09-29', INTERVAL 1 DAY) AS d(gs)
    CROSS JOIN (VALUES ('1'), ('3')) AS m(meet)
), daily AS (
    SELECT event_date, meet, count(*) AS actual_rows
    FROM starting_exam_observations
    WHERE dataset='starting_exam'
    GROUP BY event_date, meet
)
SELECT
    c.event_date,
    c.meet,
    extract(year FROM c.event_date)::INTEGER AS capture_year,
    p.coverage_status AS partition_coverage_status,
    coalesce(d.actual_rows, 0) AS observed_rows,
    CASE WHEN p.coverage_status='complete' AND coalesce(d.actual_rows,0)>0 THEN 'complete_rows'
         WHEN p.coverage_status IN ('complete','zero') AND coalesce(d.actual_rows,0)=0 THEN 'complete_zero_rows'
         ELSE 'incomplete_capture' END AS coverage_status,
    p.selected_capture_id,
    p.coverage_basis
FROM calendar AS c
LEFT JOIN starting_exam_partition_coverage AS p
  ON p.capture_year=extract(year FROM c.event_date)::INTEGER AND p.meet=c.meet
LEFT JOIN daily AS d
  ON d.event_date=c.event_date AND d.meet=c.meet;

CREATE VIEW starting_exam_entity_links AS
SELECT
    o.observation_id, o.event_date, o.meet, 'horse' AS entity_role,
    o.raw_name AS source_name, o.official_horse_id AS source_official_id,
    o.link_status AS link_status, o.linked_core_horse_id AS linked_core_official_id
FROM starting_exam_observations AS o WHERE o.dataset='starting_exam'
UNION ALL
SELECT
    o.observation_id, o.event_date, o.meet, 'trainer' AS entity_role,
    json_extract_string(o.typed_fields_json, '$.trName') AS source_name,
    json_extract_string(o.typed_fields_json, '$.trNo') AS source_official_id,
    r.trainer_entity_link_status AS link_status,
    CASE WHEN r.trainer_entity_link_status='exact_core_roster_match'
         THEN r.source_trainer_id ELSE NULL END AS linked_core_official_id
FROM starting_exam_observations AS o
JOIN starting_exam_results AS r USING (observation_id)
WHERE o.dataset='starting_exam'
UNION ALL
SELECT
    o.observation_id, o.event_date, o.meet, 'owner' AS entity_role,
    json_extract_string(o.typed_fields_json, '$.owName') AS source_name,
    json_extract_string(o.typed_fields_json, '$.owNo') AS source_official_id,
    r.owner_entity_link_status AS link_status,
    CASE WHEN r.owner_entity_link_status='exact_core_roster_match'
         THEN r.source_owner_id ELSE NULL END AS linked_core_official_id
FROM starting_exam_observations AS o
JOIN starting_exam_results AS r USING (observation_id)
WHERE o.dataset='starting_exam';
