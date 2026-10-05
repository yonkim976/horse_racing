-- Add race-level API303 corner-rank evidence beside the existing API4_3
-- horse-level passing-order values. Existing source and result rows are intact.
CREATE TABLE IF NOT EXISTS api303_corner_rank_rows (
    api_record_id INTEGER PRIMARY KEY REFERENCES api_records(api_record_id),
    race_date TEXT NOT NULL,
    meet_code INTEGER NOT NULL,
    race_number INTEGER NOT NULL,
    api_meet_raw TEXT,
    corner_1_raw TEXT,
    corner_2_raw TEXT,
    corner_3_raw TEXT,
    corner_4_raw TEXT,
    corner_5_raw TEXT,
    corner_6_raw TEXT,
    corner_7_raw TEXT,
    corner_8_raw TEXT,
    corner_9_raw TEXT,
    passtime_3f_raw TEXT,
    passtime_4f_raw TEXT,
    tempo_raw TEXT,
    UNIQUE(race_date, meet_code, race_number)
);

CREATE INDEX IF NOT EXISTS ix_api303_corner_rank_natural_key
    ON api303_corner_rank_rows(race_date, meet_code, race_number);

CREATE VIEW IF NOT EXISTS jeju_race_population_candidate_passing_orders AS
SELECT c.*,
       json_extract(a.payload_json, '$.sjS1fOrd') AS api4_3_sjS1fOrd_raw,
       json_type(a.payload_json, '$.sjS1fOrd') AS api4_3_sjS1fOrd_json_type,
       json_extract(a.payload_json, '$.sjG1fOrd') AS api4_3_sjG1fOrd_raw,
       json_type(a.payload_json, '$.sjG1fOrd') AS api4_3_sjG1fOrd_json_type,
       json_extract(a.payload_json, '$.sjG3fOrd') AS api4_3_sjG3fOrd_raw,
       json_type(a.payload_json, '$.sjG3fOrd') AS api4_3_sjG3fOrd_json_type,
       json_extract(a.payload_json, '$.sj_1cOrd') AS api4_3_sj_1cOrd_raw,
       json_type(a.payload_json, '$.sj_1cOrd') AS api4_3_sj_1cOrd_json_type,
       json_extract(a.payload_json, '$.sj_2cOrd') AS api4_3_sj_2cOrd_raw,
       json_type(a.payload_json, '$.sj_2cOrd') AS api4_3_sj_2cOrd_json_type,
       json_extract(a.payload_json, '$.sj_3cOrd') AS api4_3_sj_3cOrd_raw,
       json_type(a.payload_json, '$.sj_3cOrd') AS api4_3_sj_3cOrd_json_type,
       json_extract(a.payload_json, '$.sj_4cOrd') AS api4_3_sj_4cOrd_raw,
       json_type(a.payload_json, '$.sj_4cOrd') AS api4_3_sj_4cOrd_json_type,
       a.payload_sha256 AS api4_3_payload_sha256,
       sa.source_artifact_id AS api4_3_source_artifact_id,
       sa.sha256 AS api4_3_source_page_sha256,
       sa.raw_relative_path AS api4_3_source_page_path
FROM jeju_race_population_candidates c
JOIN api_records a ON a.api_record_id = c.api_record_id
JOIN source_artifacts sa ON sa.source_artifact_id = a.source_artifact_id;

-- Refresh the new joined view when this additive migration is rerun, reading
-- scalars from payload_json so SQLite preserves each source JSON type.
DROP VIEW IF EXISTS jeju_race_candidate_passing_with_corner_rank;
CREATE VIEW jeju_race_candidate_passing_with_corner_rank AS
SELECT p.*,
       cr.api_record_id AS api303_api_record_id,
       json_extract(cra.payload_json, '$.meet') AS api303_meet_raw,
       json_type(cra.payload_json, '$.meet') AS api303_meet_json_type,
       json_extract(cra.payload_json, '$.corner_1') AS api303_corner_1_raw,
       json_type(cra.payload_json, '$.corner_1') AS api303_corner_1_json_type,
       json_extract(cra.payload_json, '$.corner_2') AS api303_corner_2_raw,
       json_type(cra.payload_json, '$.corner_2') AS api303_corner_2_json_type,
       json_extract(cra.payload_json, '$.corner_3') AS api303_corner_3_raw,
       json_type(cra.payload_json, '$.corner_3') AS api303_corner_3_json_type,
       json_extract(cra.payload_json, '$.corner_4') AS api303_corner_4_raw,
       json_type(cra.payload_json, '$.corner_4') AS api303_corner_4_json_type,
       json_extract(cra.payload_json, '$.corner_5') AS api303_corner_5_raw,
       json_type(cra.payload_json, '$.corner_5') AS api303_corner_5_json_type,
       json_extract(cra.payload_json, '$.corner_6') AS api303_corner_6_raw,
       json_type(cra.payload_json, '$.corner_6') AS api303_corner_6_json_type,
       json_extract(cra.payload_json, '$.corner_7') AS api303_corner_7_raw,
       json_type(cra.payload_json, '$.corner_7') AS api303_corner_7_json_type,
       json_extract(cra.payload_json, '$.corner_8') AS api303_corner_8_raw,
       json_type(cra.payload_json, '$.corner_8') AS api303_corner_8_json_type,
       json_extract(cra.payload_json, '$.corner_9') AS api303_corner_9_raw,
       json_type(cra.payload_json, '$.corner_9') AS api303_corner_9_json_type,
       json_extract(cra.payload_json, '$.passtime_3f') AS api303_passtime_3f_raw,
       json_type(cra.payload_json, '$.passtime_3f') AS api303_passtime_3f_json_type,
       json_extract(cra.payload_json, '$.passtime_4f') AS api303_passtime_4f_raw,
       json_type(cra.payload_json, '$.passtime_4f') AS api303_passtime_4f_json_type,
       json_extract(cra.payload_json, '$.tempo') AS api303_tempo_raw,
       json_type(cra.payload_json, '$.tempo') AS api303_tempo_json_type,
       cra.payload_sha256 AS api303_payload_sha256,
       sa.source_artifact_id AS api303_source_artifact_id,
       sa.sha256 AS api303_source_page_sha256,
       sa.raw_relative_path AS api303_source_page_path
FROM jeju_race_population_candidate_passing_orders p
LEFT JOIN api303_corner_rank_rows cr
  ON cr.race_date = p.race_date
 AND cr.meet_code = p.meet_code
 AND cr.race_number = p.race_number
LEFT JOIN api_records cra ON cra.api_record_id = cr.api_record_id
LEFT JOIN source_artifacts sa ON sa.source_artifact_id = cra.source_artifact_id;

CREATE VIEW IF NOT EXISTS jeju_race_candidate_corner_rank_coverage AS
SELECT c.race_date, c.meet_code, c.race_number,
       count(*) AS candidate_horse_rows,
       cr.api_record_id AS api303_api_record_id,
       CASE WHEN cr.api_record_id IS NULL THEN 0 ELSE 1 END AS api303_present,
       CASE WHEN cr.api_record_id IS NOT NULL AND (
           coalesce(trim(cr.corner_1_raw), '') NOT IN ('', '-', 'X') OR
           coalesce(trim(cr.corner_2_raw), '') NOT IN ('', '-', 'X') OR
           coalesce(trim(cr.corner_3_raw), '') NOT IN ('', '-', 'X') OR
           coalesce(trim(cr.corner_4_raw), '') NOT IN ('', '-', 'X') OR
           coalesce(trim(cr.corner_5_raw), '') NOT IN ('', '-', 'X') OR
           coalesce(trim(cr.corner_6_raw), '') NOT IN ('', '-', 'X') OR
           coalesce(trim(cr.corner_7_raw), '') NOT IN ('', '-', 'X') OR
           coalesce(trim(cr.corner_8_raw), '') NOT IN ('', '-', 'X') OR
           coalesce(trim(cr.corner_9_raw), '') NOT IN ('', '-', 'X')
       ) THEN 1 ELSE 0 END AS api303_has_corner_order_content,
       CASE WHEN cr.api_record_id IS NOT NULL AND (
           coalesce(trim(cr.passtime_3f_raw), '') NOT IN ('', '0:00.0', '0:00') OR
           coalesce(trim(cr.passtime_4f_raw), '') NOT IN ('', '0:00.0', '0:00')
       ) THEN 1 ELSE 0 END AS api303_has_nonzero_passing_time,
       cra.payload_sha256 AS api303_payload_sha256,
       sa.sha256 AS api303_source_page_sha256,
       sa.raw_relative_path AS api303_source_page_path
FROM jeju_race_population_candidates c
LEFT JOIN api303_corner_rank_rows cr
  ON cr.race_date = c.race_date
 AND cr.meet_code = c.meet_code
 AND cr.race_number = c.race_number
LEFT JOIN api_records cra ON cra.api_record_id = cr.api_record_id
LEFT JOIN source_artifacts sa ON sa.source_artifact_id = cra.source_artifact_id
GROUP BY c.race_date, c.meet_code, c.race_number;
