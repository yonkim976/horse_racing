-- Append current API42_1 horse-profile observations without changing any
-- race-result, trial-result, breed-assessment, or existing metadata rows.
CREATE TABLE IF NOT EXISTS horse_profile_observations (
    horse_profile_observation_id INTEGER PRIMARY KEY,
    api_record_id INTEGER NOT NULL UNIQUE REFERENCES api_records(api_record_id),
    horse_id TEXT NOT NULL,
    observed_at_utc TEXT NOT NULL,
    observed_kst_date TEXT NOT NULL,
    horse_name_raw TEXT,
    birth_date_raw TEXT,
    age_raw TEXT,
    breed_label_raw TEXT NOT NULL,
    sex_raw TEXT,
    color_raw TEXT,
    production_country_raw TEXT,
    UNIQUE(horse_id, observed_at_utc)
);

CREATE INDEX IF NOT EXISTS ix_horse_profile_observations_horse_time
    ON horse_profile_observations(horse_id, observed_at_utc DESC, api_record_id DESC);

CREATE INDEX IF NOT EXISTS ix_horse_profile_observations_kst_date
    ON horse_profile_observations(observed_kst_date, horse_id);

CREATE VIEW IF NOT EXISTS horse_profile_latest AS
WITH ranked AS (
    SELECT hpo.*,
           row_number() OVER (
               PARTITION BY hpo.horse_id
               ORDER BY hpo.observed_at_utc DESC, hpo.api_record_id DESC
           ) AS observation_rank
    FROM horse_profile_observations hpo
)
SELECT r.horse_profile_observation_id,
       r.api_record_id,
       r.horse_id,
       r.observed_at_utc,
       r.observed_kst_date,
       r.horse_name_raw,
       r.birth_date_raw,
       r.age_raw,
       r.breed_label_raw,
       r.sex_raw,
       r.color_raw,
       r.production_country_raw,
       a.payload_json,
       a.payload_sha256,
       sa.source_artifact_id,
       sa.sha256 AS source_response_sha256,
       sa.raw_relative_path
FROM ranked r
JOIN api_records a ON a.api_record_id = r.api_record_id
JOIN source_artifacts sa ON sa.source_artifact_id = a.source_artifact_id
WHERE r.observation_rank = 1;
