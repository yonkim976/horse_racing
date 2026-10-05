-- Static 2026 analysis policy views.
-- Event source values stay raw; profile name and fixed 2026 age are exposed
-- alongside them, with explicit profile and source provenance.
CREATE VIEW IF NOT EXISTS horse_analysis_2026 AS
WITH profile_current AS (
    SELECT hpl.*,
           CASE
             WHEN length(trim(hpl.birth_date_raw)) >= 4
              AND substr(trim(hpl.birth_date_raw), 1, 4) NOT GLOB '*[^0-9]*'
              AND CAST(substr(trim(hpl.birth_date_raw), 1, 4) AS INTEGER) BETWEEN 1 AND 2026
             THEN CAST(substr(trim(hpl.birth_date_raw), 1, 4) AS INTEGER)
             ELSE NULL
           END AS birth_year
    FROM horse_profile_latest hpl
)
SELECT pc.horse_id,
       pc.horse_name_raw AS horse_name,
       pc.age_raw AS profile_age_raw,
       pc.birth_date_raw,
       pc.birth_year,
       CASE WHEN pc.birth_year IS NOT NULL THEN 2026 - pc.birth_year END AS age,
       CASE WHEN pc.birth_year IS NOT NULL THEN 2026 - pc.birth_year END AS age_2026,
       2026 AS age_reference_year,
       pc.sex_raw AS sex_current_profile,
       pc.breed_label_raw AS profile_breed_label_raw,
       pc.color_raw AS profile_color_raw,
       pc.production_country_raw AS profile_production_country_raw,
       pc.horse_profile_observation_id,
       pc.api_record_id AS profile_api_record_id,
       pc.observed_at_utc AS profile_observed_at_utc,
       pc.observed_kst_date AS profile_observed_kst_date,
       pc.payload_json AS profile_payload_json,
       pc.payload_sha256 AS profile_payload_sha256,
       pc.source_artifact_id AS profile_source_artifact_id,
       pc.source_response_sha256 AS profile_source_response_sha256,
       pc.raw_relative_path AS profile_raw_relative_path
FROM profile_current pc;

CREATE VIEW IF NOT EXISTS jeju_race_analysis_2026 AS
WITH profile_current AS (
    SELECT hpl.*,
           CASE
             WHEN length(trim(hpl.birth_date_raw)) >= 4
              AND substr(trim(hpl.birth_date_raw), 1, 4) NOT GLOB '*[^0-9]*'
              AND CAST(substr(trim(hpl.birth_date_raw), 1, 4) AS INTEGER) BETWEEN 1 AND 2026
             THEN CAST(substr(trim(hpl.birth_date_raw), 1, 4) AS INTEGER)
             ELSE NULL
           END AS birth_year
    FROM horse_profile_latest hpl
)
SELECT p.api_record_id,
       p.race_date,
       p.meet_code,
       p.race_number,
       p.horse_number,
       p.horse_id,
       coalesce(nullif(trim(pc.horse_name_raw), ''), p.horse_name) AS horse_name,
       p.horse_name AS historical_horse_name_raw,
       p.race_distance_m,
       p.rank_class_raw,
       p.race_name_raw,
       p.finish_position,
       p.finish_status_raw,
       p.finish_time_seconds,
       p.carried_weight_kg,
       p.body_weight_raw,
       p.jockey_id,
       p.jockey_name,
       p.trainer_id,
       p.trainer_name,
       p.owner_id,
       p.owner_name,
       p.track_raw,
       p.weather_raw,
       p.breed_label_raw,
       p.breed_assessment,
       p.breed_assessment_note,
       p.api4_3_sjS1fOrd_raw,
       p.api4_3_sjS1fOrd_json_type,
       p.api4_3_sjG1fOrd_raw,
       p.api4_3_sjG1fOrd_json_type,
       p.api4_3_sjG3fOrd_raw,
       p.api4_3_sjG3fOrd_json_type,
       p.api4_3_sj_1cOrd_raw,
       p.api4_3_sj_1cOrd_json_type,
       p.api4_3_sj_2cOrd_raw,
       p.api4_3_sj_2cOrd_json_type,
       p.api4_3_sj_3cOrd_raw,
       p.api4_3_sj_3cOrd_json_type,
       p.api4_3_sj_4cOrd_raw,
       p.api4_3_sj_4cOrd_json_type,
       p.api4_3_payload_sha256,
       p.api4_3_source_artifact_id,
       p.api4_3_source_page_sha256,
       p.api4_3_source_page_path,
       p.api303_api_record_id,
       p.api303_meet_raw,
       p.api303_meet_json_type,
       p.api303_corner_1_raw,
       p.api303_corner_1_json_type,
       p.api303_corner_2_raw,
       p.api303_corner_2_json_type,
       p.api303_corner_3_raw,
       p.api303_corner_3_json_type,
       p.api303_corner_4_raw,
       p.api303_corner_4_json_type,
       p.api303_corner_5_raw,
       p.api303_corner_5_json_type,
       p.api303_corner_6_raw,
       p.api303_corner_6_json_type,
       p.api303_corner_7_raw,
       p.api303_corner_7_json_type,
       p.api303_corner_8_raw,
       p.api303_corner_8_json_type,
       p.api303_corner_9_raw,
       p.api303_corner_9_json_type,
       p.api303_passtime_3f_raw,
       p.api303_passtime_3f_json_type,
       p.api303_passtime_4f_raw,
       p.api303_passtime_4f_json_type,
       p.api303_tempo_raw,
       p.api303_tempo_json_type,
       p.api303_payload_sha256,
       p.api303_source_artifact_id,
       p.api303_source_page_sha256,
       p.api303_source_page_path,
       pc.birth_date_raw,
       pc.birth_year,
       CASE WHEN pc.birth_year IS NOT NULL THEN 2026 - pc.birth_year END AS age,
       CASE WHEN pc.birth_year IS NOT NULL THEN 2026 - pc.birth_year END AS age_2026,
       2026 AS age_reference_year,
       json_extract(api4.payload_json, '$.age') AS age_at_race_raw,
       json_type(api4.payload_json, '$.age') AS age_at_race_json_type,
       json_extract(api4.payload_json, '$.sex') AS sex,
       json_extract(api4.payload_json, '$.sex') AS sex_at_race_raw,
       json_type(api4.payload_json, '$.sex') AS sex_at_race_json_type,
       pc.sex_raw AS sex_current_profile,
       pc.horse_profile_observation_id,
       pc.api_record_id AS profile_api_record_id,
       pc.age_raw AS profile_age_raw,
       pc.observed_at_utc AS profile_observed_at_utc,
       pc.observed_kst_date AS profile_observed_kst_date,
       pc.payload_json AS profile_payload_json,
       pc.payload_sha256 AS profile_payload_sha256,
       pc.source_artifact_id AS profile_source_artifact_id,
       pc.source_response_sha256 AS profile_source_response_sha256,
       pc.raw_relative_path AS profile_raw_relative_path
FROM jeju_race_candidate_passing_with_corner_rank p
LEFT JOIN profile_current pc ON pc.horse_id = p.horse_id
LEFT JOIN api_records api4 ON api4.api_record_id = p.api_record_id;

CREATE VIEW IF NOT EXISTS jeju_trial_analysis_2026 AS
WITH profile_current AS (
    SELECT hpl.*,
           CASE
             WHEN length(trim(hpl.birth_date_raw)) >= 4
              AND substr(trim(hpl.birth_date_raw), 1, 4) NOT GLOB '*[^0-9]*'
              AND CAST(substr(trim(hpl.birth_date_raw), 1, 4) AS INTEGER) BETWEEN 1 AND 2026
             THEN CAST(substr(trim(hpl.birth_date_raw), 1, 4) AS INTEGER)
             ELSE NULL
           END AS birth_year
    FROM horse_profile_latest hpl
)
SELECT t.api_record_id,
       t.trial_date,
       t.meet_code,
       t.trial_number,
       t.horse_number,
       t.horse_id,
       coalesce(nullif(trim(pc.horse_name_raw), ''), t.horse_name) AS horse_name,
       t.horse_name AS historical_horse_name_raw,
       t.finish_position,
       t.finish_status_raw,
       t.finish_time_seconds,
       t.body_weight_kg,
       t.carried_weight_base_kg,
       t.jockey_overweight_kg,
       t.jockey_id,
       t.jockey_name,
       t.trainer_id,
       t.trainer_name,
       t.pass_flag_raw,
       t.failure_reason_raw,
       t.inspection_reason_raw,
       t.section_times_json,
       t.breed_label_raw,
       t.breed_assessment,
       t.breed_assessment_note,
       pc.birth_date_raw,
       pc.birth_year,
       CASE WHEN pc.birth_year IS NOT NULL THEN 2026 - pc.birth_year END AS age,
       CASE WHEN pc.birth_year IS NOT NULL THEN 2026 - pc.birth_year END AS age_2026,
       2026 AS age_reference_year,
       json_extract(api20.payload_json, '$.age') AS age_at_trial_raw,
       json_type(api20.payload_json, '$.age') AS age_at_trial_json_type,
       json_extract(api20.payload_json, '$.sex') AS sex,
       json_extract(api20.payload_json, '$.sex') AS sex_at_trial_raw,
       json_type(api20.payload_json, '$.sex') AS sex_at_trial_json_type,
       pc.sex_raw AS sex_current_profile,
       pc.horse_profile_observation_id,
       pc.api_record_id AS profile_api_record_id,
       pc.age_raw AS profile_age_raw,
       pc.observed_at_utc AS profile_observed_at_utc,
       pc.observed_kst_date AS profile_observed_kst_date,
       pc.payload_json AS profile_payload_json,
       pc.payload_sha256 AS profile_payload_sha256,
       pc.source_artifact_id AS profile_source_artifact_id,
       pc.source_response_sha256 AS profile_source_response_sha256,
       pc.raw_relative_path AS profile_raw_relative_path,
       api20.payload_sha256 AS api20_payload_sha256,
       api20.source_artifact_id AS api20_source_artifact_id,
       api20_source.sha256 AS api20_source_response_sha256,
       api20_source.raw_relative_path AS api20_raw_relative_path
FROM api_explicit_jeju_trial_rows t
LEFT JOIN profile_current pc ON pc.horse_id = t.horse_id
LEFT JOIN api_records api20 ON api20.api_record_id = t.api_record_id
LEFT JOIN source_artifacts api20_source
  ON api20_source.source_artifact_id = api20.source_artifact_id;

INSERT OR IGNORE INTO schema_metadata(key, value) VALUES
    ('analysis_horse_name_policy',
     'Use the latest API42 horse name by horse_id in 2026 analysis views; preserve each historical event name in historical_horse_name_raw and use it only when no profile name is available.'),
    ('analysis_age_policy',
     'The fixed reference year is 2026. age and age_2026 equal 2026 minus a validated four-digit profile birth year in 1..2026; invalid or missing years yield NULL. Preserve event ages in age_at_race_raw and age_at_trial_raw.'),
    ('analysis_sex_policy',
     'Preserve API4 race sex and API20 trial sex in source-specific raw columns; expose API42 current-profile sex separately. Never overwrite event-source sex.'),
    ('analysis_profile_selection_policy',
     'Select the latest API42 profile observation by observed_at_utc descending, then api_record_id descending; apply current profile name and fixed 2026 age only in the named analysis views.');

INSERT INTO provenance_issues(
    issue_type, severity, status, entity_type, entity_key, api_record_id,
    supplemental_artifact_id, api_value_json, supplemental_value_json,
    summary, detail_json, created_at_utc
)
SELECT
    'current_profile_vs_historical_race_sex_conflict',
    'medium',
    'open',
    'horse',
    '3005897',
    race.api_record_id,
    NULL,
    json_object(
        'race_date', race_row.race_date,
        'race_number', race_row.race_number,
        'horse_number', race_row.horse_number,
        'sex_raw', json_extract(race.payload_json, '$.sex'),
        'age_raw', json_extract(race.payload_json, '$.age')
    ),
    NULL,
    'Preserve the API4 historical race sex (수) alongside the current API42 profile and pre-race API20 trial sex (암); do not harmonize the event record.',
    json_object(
        'historical_api4_race', json_object(
            'api_record_id', race.api_record_id,
            'race_date', race_row.race_date,
            'race_number', race_row.race_number,
            'horse_number', race_row.horse_number,
            'sex_raw', json_extract(race.payload_json, '$.sex'),
            'age_raw', json_extract(race.payload_json, '$.age'),
            'payload_sha256', race.payload_sha256,
            'raw_relative_path', race_source.raw_relative_path
        ),
        'current_api42_profile', json_object(
            'api_record_id', profile.api_record_id,
            'sex_raw', profile.sex_raw,
            'observed_at_utc', profile.observed_at_utc,
            'payload_sha256', profile.payload_sha256,
            'source_response_sha256', profile.source_response_sha256,
            'raw_relative_path', profile.raw_relative_path
        ),
        'pre_race_api20_trial', json_object(
            'api_record_id', trial.api_record_id,
            'trial_date', trial_row.trial_date,
            'sex_raw', json_extract(trial.payload_json, '$.sex'),
            'payload_sha256', trial.payload_sha256,
            'raw_relative_path', trial_source.raw_relative_path
        ),
        'user_decision', 'retain_existing_record_without_correction',
        'decision_date', '2026-10-01',
        'cause_status', 'unconfirmed',
        'policy', 'Preserve event and current-profile observations as source-specific values; do not correct either source.'
    ),
    strftime('%Y-%m-%dT%H:%M:%f+00:00', 'now')
FROM race_result_rows race_row
JOIN api_records race ON race.api_record_id = race_row.api_record_id
JOIN source_artifacts race_source ON race_source.source_artifact_id = race.source_artifact_id
JOIN horse_profile_latest profile ON profile.horse_id = race_row.horse_id
JOIN api_explicit_jeju_trial_rows trial_row
  ON trial_row.horse_id = race_row.horse_id
 AND trial_row.trial_date = '2002-11-22'
 AND trial_row.api_record_id = (
     SELECT min(trial_choice.api_record_id)
     FROM api_explicit_jeju_trial_rows trial_choice
     WHERE trial_choice.horse_id = race_row.horse_id
       AND trial_choice.trial_date = '2002-11-22'
 )
JOIN api_records trial ON trial.api_record_id = trial_row.api_record_id
JOIN source_artifacts trial_source ON trial_source.source_artifact_id = trial.source_artifact_id
WHERE race_row.race_date = '2002-12-14'
  AND race_row.race_number = 3
  AND race_row.horse_number = 2
  AND race_row.horse_id = '3005897'
  AND json_extract(race.payload_json, '$.sex') = '수'
  AND profile.sex_raw = '암'
  AND json_extract(trial.payload_json, '$.sex') = '암'
  AND NOT EXISTS (
      SELECT 1
      FROM provenance_issues existing
      WHERE existing.issue_type = 'current_profile_vs_historical_race_sex_conflict'
        AND existing.entity_key = '3005897'
  );
