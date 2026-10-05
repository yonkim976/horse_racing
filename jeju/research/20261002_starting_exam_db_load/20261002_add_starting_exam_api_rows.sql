-- Preserve source item rows from KRA API21_1 startingTestResult_1.
-- API42 profile observations are stored in the existing horse_profile_observations table.
CREATE TABLE IF NOT EXISTS starting_exam_api_rows (
    starting_exam_api_row_id INTEGER PRIMARY KEY,
    api_record_id INTEGER NOT NULL UNIQUE REFERENCES api_records(api_record_id),
    source_artifact_id INTEGER NOT NULL REFERENCES source_artifacts(source_artifact_id),
    source_row_no INTEGER NOT NULL CHECK (source_row_no >= 1),
    event_key TEXT NOT NULL,
    exam_date TEXT NOT NULL,
    horse_id TEXT NOT NULL,
    meet_raw TEXT,
    train_date_raw TEXT,
    day_serial_raw TEXT,
    train_no_raw TEXT,
    chul_no_raw TEXT,
    hr_name_raw TEXT,
    hr_no_raw TEXT,
    name_raw TEXT,
    sex_raw TEXT,
    age_raw TEXT,
    rider_raw TEXT,
    tr_name_raw TEXT,
    tr_no_raw TEXT,
    trainer_id_normalized TEXT,
    ow_name_raw TEXT,
    ow_no_raw TEXT,
    pass_flag_raw TEXT,
    judgment_label_normalized TEXT,
    judgment_status TEXT NOT NULL CHECK (judgment_status IN ('observed', 'unknown')),
    reason_raw TEXT,
    nopass_reason_raw TEXT,
    raw_key_presence_json TEXT NOT NULL,
    raw_key_absence_json TEXT NOT NULL,
    UNIQUE(source_artifact_id, source_row_no)
);

CREATE INDEX IF NOT EXISTS ix_starting_exam_api_rows_horse_date
    ON starting_exam_api_rows(horse_id, exam_date, train_no_raw);
CREATE INDEX IF NOT EXISTS ix_starting_exam_api_rows_event_key
    ON starting_exam_api_rows(event_key);
CREATE INDEX IF NOT EXISTS ix_starting_exam_api_rows_exam_date
    ON starting_exam_api_rows(exam_date, horse_id);

CREATE VIEW IF NOT EXISTS starting_exam_api_rows_analysis_2026 AS
WITH current_profiles AS MATERIALIZED (
    SELECT horse_id, horse_name, age_2026, sex_current_profile,
           profile_breed_label_raw, profile_observed_at_utc
    FROM horse_analysis_2026
)
SELECT se.starting_exam_api_row_id,
       se.api_record_id,
       se.source_artifact_id,
       se.source_row_no,
       se.event_key,
       se.exam_date,
       se.horse_id,
       se.meet_raw,
       se.train_date_raw,
       se.day_serial_raw,
       se.train_no_raw,
       se.chul_no_raw,
       se.hr_name_raw,
       se.hr_no_raw,
       se.name_raw,
       se.sex_raw AS sex_at_exam_raw,
       se.age_raw AS age_at_exam_raw,
       se.rider_raw,
       se.tr_name_raw,
       se.tr_no_raw,
       se.trainer_id_normalized,
       se.ow_name_raw,
       se.ow_no_raw,
       se.pass_flag_raw,
       se.judgment_label_normalized,
       se.judgment_status,
       se.reason_raw,
       se.nopass_reason_raw,
       se.raw_key_presence_json,
       se.raw_key_absence_json,
       ha.horse_name AS current_horse_name,
       ha.age_2026 AS current_horse_age_2026,
       ha.sex_current_profile,
       ha.profile_breed_label_raw AS current_profile_breed_label_raw,
       ha.profile_observed_at_utc AS current_profile_observed_at_utc,
       ar.payload_json AS source_item_payload_json,
       ar.payload_sha256 AS source_item_payload_sha256,
       sa.sha256 AS source_page_sha256,
       sa.raw_relative_path AS source_page_raw_relative_path,
       sa.collected_at_utc AS source_page_observed_at_utc
FROM starting_exam_api_rows se
JOIN api_records ar
  ON ar.api_record_id = se.api_record_id
 AND ar.source_artifact_id = se.source_artifact_id
 AND ar.record_index = se.source_row_no
JOIN source_artifacts sa
  ON sa.source_artifact_id = se.source_artifact_id
JOIN current_profiles ha
  ON ha.horse_id = se.horse_id
WHERE se.exam_date <= '2026-09-19';
