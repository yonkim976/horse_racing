PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_artifacts (
    source_artifact_id INTEGER PRIMARY KEY,
    source_family TEXT NOT NULL CHECK (source_family IN ('kra_openapi', 'kra_rpt_txt')),
    source_role TEXT NOT NULL CHECK (source_role IN ('primary', 'supplement', 'validation_only')),
    public_dataset_id TEXT,
    dataset_name TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    operation TEXT NOT NULL,
    attempt_id TEXT NOT NULL,
    request_params_json TEXT NOT NULL,
    source_url_without_key TEXT,
    collected_at_utc TEXT,
    http_status_code INTEGER,
    content_type TEXT,
    raw_relative_path TEXT NOT NULL,
    response_bytes INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    parser_version TEXT,
    created_at_utc TEXT NOT NULL,
    CHECK (length(sha256) = 64)
);

CREATE INDEX IF NOT EXISTS ix_source_artifacts_service_attempt
    ON source_artifacts(operation, attempt_id);

CREATE TABLE IF NOT EXISTS collection_coverage (
    coverage_id INTEGER PRIMARY KEY,
    source_family TEXT NOT NULL,
    operation TEXT NOT NULL,
    year INTEGER NOT NULL,
    attempt_id TEXT NOT NULL,
    status TEXT NOT NULL,
    page_count INTEGER NOT NULL,
    api_total_count INTEGER,
    response_row_count INTEGER NOT NULL,
    first_event_date TEXT,
    last_event_date TEXT,
    breed_label_counts_json TEXT,
    candidate_row_count INTEGER,
    notes TEXT,
    created_at_utc TEXT NOT NULL,
    UNIQUE(source_family, operation, year, attempt_id)
);

CREATE INDEX IF NOT EXISTS ix_collection_coverage_year
    ON collection_coverage(operation, year, status);

CREATE TABLE IF NOT EXISTS api_records (
    api_record_id INTEGER PRIMARY KEY,
    source_artifact_id INTEGER NOT NULL REFERENCES source_artifacts(source_artifact_id),
    record_index INTEGER NOT NULL,
    record_type TEXT NOT NULL,
    natural_key TEXT,
    payload_json TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    UNIQUE(source_artifact_id, record_index)
);

CREATE INDEX IF NOT EXISTS ix_api_records_natural_key
    ON api_records(record_type, natural_key);

CREATE TABLE IF NOT EXISTS race_result_rows (
    api_record_id INTEGER PRIMARY KEY REFERENCES api_records(api_record_id),
    race_date TEXT NOT NULL,
    meet_code INTEGER NOT NULL,
    race_number INTEGER NOT NULL,
    horse_number INTEGER,
    horse_id TEXT,
    horse_name TEXT,
    race_distance_m INTEGER,
    rank_class_raw TEXT,
    race_name_raw TEXT,
    finish_position INTEGER,
    finish_status_raw TEXT,
    finish_time_seconds REAL,
    carried_weight_kg REAL,
    body_weight_raw TEXT,
    jockey_id TEXT,
    jockey_name TEXT,
    trainer_id TEXT,
    trainer_name TEXT,
    owner_id TEXT,
    owner_name TEXT,
    track_raw TEXT,
    weather_raw TEXT,
    breed_label_raw TEXT,
    breed_assessment TEXT NOT NULL CHECK (breed_assessment IN (
        'unresolved', 'rank_class_candidate', 'api_cross_reference_candidate',
        'program_rule_candidate', 'conflict', 'native_confirmed', 'non_native_confirmed'
    )),
    breed_assessment_note TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_race_result_natural_key
    ON race_result_rows(race_date, meet_code, race_number, horse_number);
CREATE INDEX IF NOT EXISTS ix_race_result_horse
    ON race_result_rows(horse_id, race_date);

-- API303 exposes one race-level corner-order record, without a horse ID.
-- Keep the complete source payload in api_records and normalize its exact
-- race key and source fields here for deterministic joins to API4_3 entries.
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

CREATE TABLE IF NOT EXISTS running_trial_rows (
    api_record_id INTEGER PRIMARY KEY REFERENCES api_records(api_record_id),
    trial_date TEXT NOT NULL,
    meet_code INTEGER NOT NULL,
    trial_number INTEGER NOT NULL,
    horse_number INTEGER,
    horse_id TEXT,
    horse_name TEXT,
    finish_position INTEGER,
    finish_status_raw TEXT,
    finish_time_seconds REAL,
    body_weight_kg REAL,
    carried_weight_base_kg REAL,
    jockey_overweight_kg REAL,
    jockey_id TEXT,
    jockey_name TEXT,
    trainer_id TEXT,
    trainer_name TEXT,
    pass_flag_raw TEXT,
    failure_reason_raw TEXT,
    inspection_reason_raw TEXT,
    section_times_json TEXT NOT NULL,
    breed_label_raw TEXT,
    breed_assessment TEXT NOT NULL CHECK (breed_assessment IN (
        'unresolved', 'api_native_label', 'api_non_native_label', 'conflict'
    )),
    breed_assessment_note TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_trial_result_natural_key
    ON running_trial_rows(trial_date, meet_code, trial_number, horse_number);
CREATE INDEX IF NOT EXISTS ix_trial_result_horse
    ON running_trial_rows(horse_id, trial_date);

CREATE TABLE IF NOT EXISTS breed_evidence (
    breed_evidence_id INTEGER PRIMARY KEY,
    horse_id TEXT NOT NULL,
    observed_event_date TEXT,
    breed_label_raw TEXT NOT NULL,
    evidence_kind TEXT NOT NULL,
    source_artifact_id INTEGER NOT NULL REFERENCES source_artifacts(source_artifact_id),
    api_record_id INTEGER REFERENCES api_records(api_record_id),
    timing_basis TEXT NOT NULL,
    notes TEXT
);

CREATE INDEX IF NOT EXISTS ix_breed_evidence_horse_date
    ON breed_evidence(horse_id, observed_event_date);

CREATE TABLE IF NOT EXISTS supplemental_facts (
    supplemental_fact_id INTEGER PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_key TEXT NOT NULL,
    field_name TEXT NOT NULL,
    value_json TEXT NOT NULL,
    source_artifact_id INTEGER NOT NULL REFERENCES source_artifacts(source_artifact_id),
    source_line INTEGER,
    api_field_state TEXT NOT NULL CHECK (api_field_state IN (
        'api_field_absent', 'api_field_null', 'validation_only', 'conflicts_with_api'
    )),
    notes TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_supplemental_facts_entity
    ON supplemental_facts(entity_type, entity_key, field_name);

CREATE TABLE IF NOT EXISTS provenance_issues (
    provenance_issue_id INTEGER PRIMARY KEY,
    issue_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('open', 'quarantined', 'resolved')),
    entity_type TEXT NOT NULL,
    entity_key TEXT NOT NULL,
    api_record_id INTEGER REFERENCES api_records(api_record_id),
    supplemental_artifact_id INTEGER REFERENCES source_artifacts(source_artifact_id),
    api_value_json TEXT,
    supplemental_value_json TEXT,
    summary TEXT NOT NULL,
    detail_json TEXT NOT NULL,
    created_at_utc TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_provenance_issues_status
    ON provenance_issues(status, issue_type);

CREATE VIEW IF NOT EXISTS jeju_race_population_candidates AS
SELECT * FROM race_result_rows
WHERE breed_assessment IN (
    'rank_class_candidate', 'api_cross_reference_candidate', 'program_rule_candidate'
);

-- These are horse-level passing order values already returned in API4_3.
-- Keep them raw: in particular, zero can mean unavailable or inapplicable.
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

-- Race-level coverage join. API303 has no horse key, so it is joined only on
-- the official (date, meet, race number) tuple and remains a separate source.
CREATE VIEW IF NOT EXISTS jeju_race_candidate_passing_with_corner_rank AS
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

CREATE VIEW IF NOT EXISTS api_explicit_jeju_trial_rows AS
SELECT * FROM running_trial_rows
WHERE breed_assessment = 'api_native_label';

INSERT OR REPLACE INTO schema_metadata(key, value) VALUES
    ('schema_version', '1'),
    ('scope', 'API-first raw response and normalized observations; text is supplement or validation only'),
    ('breed_policy', 'Never infer individual breed from race rank; keep direct labels and population rules separate');

-- Current API42_1 profile observations are retrieval-time evidence. They do
-- not provide an event-effective date and must not update historical rows.
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

-- Approved 2026-10-02 website time corrections. API JSON remains immutable.
-- Seed/reapply with jeju/scripts/apply_section_time_website_review.py after raw loading.
CREATE TABLE IF NOT EXISTS race_section_time_reviews (
    api_record_id INTEGER NOT NULL REFERENCES race_result_rows(api_record_id),
    field_name TEXT NOT NULL CHECK (field_name IN ('jeS1fTime','je_1cTime','je_2cTime','je_3cTime','je_4cTime','jeG3fTime','jeG1fTime')),
    review_status TEXT NOT NULL CHECK (review_status IN ('website_corrected','unresolved_official_website_anomaly')),
    api_seconds_at_review REAL NOT NULL,
    api_payload_sha256_at_review TEXT NOT NULL CHECK (length(api_payload_sha256_at_review)=64),
    website_display TEXT NOT NULL,
    website_seconds REAL NOT NULL,
    effective_seconds REAL,
    website_url TEXT NOT NULL,
    checked_date_kst TEXT NOT NULL,
    evidence_relative_path TEXT NOT NULL,
    evidence_sha256 TEXT NOT NULL CHECK (length(evidence_sha256)=64),
    decision_reason TEXT NOT NULL,
    applied_at_utc TEXT NOT NULL,
    PRIMARY KEY(api_record_id, field_name),
    CHECK ((review_status='website_corrected' AND effective_seconds IS NOT NULL AND effective_seconds>0 AND effective_seconds=website_seconds)
        OR (review_status='unresolved_official_website_anomaly' AND effective_seconds IS NULL))
);

CREATE VIEW IF NOT EXISTS jeju_race_section_time_values AS
WITH fields(field_name) AS (VALUES
        ('jeS1fTime'),
        ('je_1cTime'),
        ('je_2cTime'),
        ('je_3cTime'),
        ('je_4cTime'),
        ('jeG3fTime'),
        ('jeG1fTime')
), known_reviews(race_date,meet_code,race_number,horse_number,horse_id,field_name) AS (VALUES
        ('2024-03-02', 2, 3, 9, '3018048', 'jeS1fTime'),
        ('2025-10-17', 2, 7, 8, '3017473', 'jeS1fTime'),
        ('2026-01-17', 2, 5, 8, '3016494', 'jeG1fTime'),
        ('2026-03-06', 2, 8, 6, '3018729', 'jeG1fTime')
), raw_values AS (
    SELECT r.api_record_id, r.race_date, r.meet_code, r.race_number,
           r.horse_number, r.horse_id, r.horse_name AS historical_horse_name_raw,
           f.field_name, json_extract(a.payload_json, '$.' || f.field_name) AS api_value_raw,
           json_type(a.payload_json, '$.' || f.field_name) AS api_value_json_type,
           a.payload_sha256 AS api_payload_sha256,
           a.source_artifact_id AS api_source_artifact_id,
           s.sha256 AS api_source_page_sha256, s.raw_relative_path AS api_source_page_path,
           CASE WHEN k.field_name IS NOT NULL THEN 1 ELSE 0 END AS known_website_review
    FROM jeju_race_population_candidates r
    JOIN api_records a ON a.api_record_id=r.api_record_id
    JOIN source_artifacts s ON s.source_artifact_id=a.source_artifact_id
    CROSS JOIN fields f
    LEFT JOIN known_reviews k
      ON (k.race_date,k.meet_code,k.race_number,k.horse_number,k.horse_id,k.field_name)
       = (r.race_date,r.meet_code,r.race_number,r.horse_number,r.horse_id,f.field_name)
)
SELECT v.*,
       CASE
         WHEN o.api_record_id IS NOT NULL AND o.api_payload_sha256_at_review<>v.api_payload_sha256 THEN NULL
         WHEN o.api_record_id IS NOT NULL THEN o.effective_seconds
         WHEN v.known_website_review=1 THEN NULL
         WHEN v.api_value_json_type IN ('integer','real') AND v.api_value_raw>0 THEN CAST(v.api_value_raw AS REAL)
         ELSE NULL
       END AS time_seconds,
       CASE
         WHEN o.api_record_id IS NOT NULL AND o.api_payload_sha256_at_review<>v.api_payload_sha256 THEN 'api_source_changed_since_review'
         WHEN o.api_record_id IS NOT NULL THEN o.review_status
         WHEN v.known_website_review=1 THEN 'website_review_not_applied'
         WHEN v.api_value_json_type IN ('integer','real') AND v.api_value_raw>0 THEN 'api_positive_unreviewed'
         ELSE 'api_unavailable_or_nonpositive'
       END AS time_status,
       o.website_display, o.website_seconds, o.website_url, o.checked_date_kst,
       o.evidence_relative_path, o.evidence_sha256, o.decision_reason, o.applied_at_utc
FROM raw_values v
LEFT JOIN race_section_time_reviews o
  ON o.api_record_id=v.api_record_id AND o.field_name=v.field_name;

CREATE VIEW IF NOT EXISTS jeju_race_section_times AS
SELECT api_record_id,
       MAX(CASE WHEN field_name='jeS1fTime' THEN time_seconds END) AS s1f_time_seconds,
       MAX(CASE WHEN field_name='jeS1fTime' THEN time_status END) AS s1f_time_status,
       MAX(CASE WHEN field_name='je_1cTime' THEN time_seconds END) AS c1_time_seconds,
       MAX(CASE WHEN field_name='je_1cTime' THEN time_status END) AS c1_time_status,
       MAX(CASE WHEN field_name='je_2cTime' THEN time_seconds END) AS c2_time_seconds,
       MAX(CASE WHEN field_name='je_2cTime' THEN time_status END) AS c2_time_status,
       MAX(CASE WHEN field_name='je_3cTime' THEN time_seconds END) AS c3_time_seconds,
       MAX(CASE WHEN field_name='je_3cTime' THEN time_status END) AS c3_time_status,
       MAX(CASE WHEN field_name='je_4cTime' THEN time_seconds END) AS c4_time_seconds,
       MAX(CASE WHEN field_name='je_4cTime' THEN time_status END) AS c4_time_status,
       MAX(CASE WHEN field_name='jeG3fTime' THEN time_seconds END) AS g3f_time_seconds,
       MAX(CASE WHEN field_name='jeG3fTime' THEN time_status END) AS g3f_time_status,
       MAX(CASE WHEN field_name='jeG1fTime' THEN time_seconds END) AS g1f_time_seconds,
       MAX(CASE WHEN field_name='jeG1fTime' THEN time_status END) AS g1f_time_status,
       SUM(time_status='website_corrected') AS section_time_website_correction_count,
       SUM(time_status IN ('unresolved_official_website_anomaly','website_review_not_applied','api_source_changed_since_review')) AS section_time_review_required_count
FROM jeju_race_section_time_values
GROUP BY api_record_id;

CREATE VIEW IF NOT EXISTS jeju_race_postrace_sections_2026 AS
SELECT a.*,
       s.s1f_time_seconds,
       s.s1f_time_status,
       s.c1_time_seconds,
       s.c1_time_status,
       s.c2_time_seconds,
       s.c2_time_status,
       s.c3_time_seconds,
       s.c3_time_status,
       s.c4_time_seconds,
       s.c4_time_status,
       s.g3f_time_seconds,
       s.g3f_time_status,
       s.g1f_time_seconds,
       s.g1f_time_status,
       s.section_time_website_correction_count,
       s.section_time_review_required_count
FROM jeju_race_analysis_2026 a
LEFT JOIN jeju_race_section_times s ON s.api_record_id=a.api_record_id;

-- User-approved 2026-10-02 official website order corrections. API JSON remains immutable.
-- Reapply the fixed review rows with jeju/scripts/apply_section_order_website_review.py.
CREATE TABLE IF NOT EXISTS race_section_order_reviews (
    api_record_id INTEGER NOT NULL REFERENCES race_result_rows(api_record_id),
    field_name TEXT NOT NULL CHECK (field_name IN (
        'sjS1fOrd','sj_1cOrd','sj_2cOrd','sj_3cOrd','sj_4cOrd','sjG1fOrd'
    )),
    review_status TEXT NOT NULL CHECK (review_status='website_corrected'),
    api_order_at_review INTEGER NOT NULL CHECK (typeof(api_order_at_review)='integer' AND api_order_at_review BETWEEN 1 AND 89),
    api_payload_sha256_at_review TEXT NOT NULL CHECK (length(api_payload_sha256_at_review)=64),
    website_order INTEGER NOT NULL CHECK (typeof(website_order)='integer' AND website_order BETWEEN 1 AND 89),
    effective_order INTEGER NOT NULL CHECK (typeof(effective_order)='integer' AND effective_order BETWEEN 1 AND 89 AND effective_order=website_order),
    website_url TEXT NOT NULL,
    checked_date_kst TEXT NOT NULL,
    evidence_relative_path TEXT NOT NULL,
    evidence_sha256 TEXT NOT NULL CHECK (length(evidence_sha256)=64),
    reason TEXT NOT NULL CHECK (length(trim(reason))>0),
    applied_at TEXT NOT NULL,
    PRIMARY KEY (api_record_id, field_name)
);

CREATE VIEW IF NOT EXISTS jeju_race_section_order_values AS
WITH fields(field_name) AS (VALUES
    ('sjS1fOrd'),
    ('sj_1cOrd'),
    ('sj_2cOrd'),
    ('sj_3cOrd'),
    ('sj_4cOrd'),
    ('sjG1fOrd')
), known_reviews(race_date,meet_code,race_number,horse_number,horse_id,field_name) AS (VALUES
    ('2025-10-17', 2, 7, 7, '3101281', 'sjS1fOrd'),
    ('2025-10-17', 2, 7, 3, '3101725', 'sjS1fOrd'),
    ('2025-10-17', 2, 7, 8, '3017473', 'sjS1fOrd'),
    ('2025-10-17', 2, 7, 8, '3017473', 'sjG1fOrd'),
    ('2025-10-17', 2, 7, 4, '3103920', 'sjS1fOrd'),
    ('2025-10-17', 2, 7, 5, '3103312', 'sjG1fOrd'),
    ('2025-10-17', 2, 7, 10, '3103590', 'sjS1fOrd'),
    ('2025-10-17', 2, 7, 2, '3017660', 'sjG1fOrd'),
    ('2025-10-17', 2, 7, 1, '3102212', 'sjS1fOrd'),
    ('2025-10-17', 2, 7, 9, '3103645', 'sjS1fOrd'),
    ('2026-03-06', 2, 8, 2, '3102938', 'sjG1fOrd'),
    ('2026-03-06', 2, 8, 3, '3015769', 'sjG1fOrd'),
    ('2026-03-06', 2, 8, 4, '3016494', 'sjG1fOrd'),
    ('2026-03-06', 2, 8, 6, '3018729', 'sjG1fOrd')
), raw_values AS (
    SELECT r.api_record_id, r.race_date, r.meet_code, r.race_number,
           r.horse_number, r.horse_id, r.horse_name AS historical_horse_name_raw,
           f.field_name,
           json_extract(a.payload_json, '$.' || f.field_name) AS api_order_raw,
           json_type(a.payload_json, '$.' || f.field_name) AS api_order_json_type,
           a.payload_sha256 AS api_payload_sha256,
           a.source_artifact_id AS api_source_artifact_id,
           s.sha256 AS api_source_page_sha256,
           s.raw_relative_path AS api_source_page_path,
           CASE WHEN k.field_name IS NOT NULL THEN 1 ELSE 0 END AS known_website_review
    FROM jeju_race_population_candidates r
    JOIN api_records a ON a.api_record_id=r.api_record_id
    JOIN source_artifacts s ON s.source_artifact_id=a.source_artifact_id
    CROSS JOIN fields f
    LEFT JOIN known_reviews k
      ON (k.race_date,k.meet_code,k.race_number,k.horse_number,k.horse_id,k.field_name)
       = (r.race_date,r.meet_code,r.race_number,r.horse_number,r.horse_id,f.field_name)
)
SELECT v.*,
       CASE
         WHEN o.api_record_id IS NOT NULL
          AND o.api_payload_sha256_at_review<>v.api_payload_sha256 THEN NULL
         WHEN o.api_record_id IS NOT NULL THEN o.effective_order
         WHEN v.known_website_review=1 THEN NULL
         WHEN v.api_order_json_type IN ('integer','real')
          AND v.api_order_raw BETWEEN 1 AND 89
          AND CAST(v.api_order_raw AS INTEGER)=v.api_order_raw
           THEN CAST(v.api_order_raw AS INTEGER)
         ELSE NULL
       END AS order_value,
       CASE
         WHEN o.api_record_id IS NOT NULL
          AND o.api_payload_sha256_at_review<>v.api_payload_sha256
           THEN 'api_source_changed_since_review'
         WHEN o.api_record_id IS NOT NULL THEN o.review_status
         WHEN v.known_website_review=1 THEN 'website_review_not_applied'
         WHEN v.api_order_json_type IN ('integer','real')
          AND v.api_order_raw BETWEEN 1 AND 89
          AND CAST(v.api_order_raw AS INTEGER)=v.api_order_raw
           THEN 'api_positive_unreviewed'
         ELSE 'api_unavailable_or_nonpositive_or_sentinel'
       END AS order_status,
       o.review_status,
       o.api_order_at_review,
       o.website_order,
       o.effective_order,
       o.website_url,
       o.checked_date_kst,
       o.evidence_relative_path,
       o.evidence_sha256,
       o.reason,
       o.applied_at
FROM raw_values v
LEFT JOIN race_section_order_reviews o
  ON o.api_record_id=v.api_record_id AND o.field_name=v.field_name;

CREATE VIEW IF NOT EXISTS jeju_race_section_orders AS
SELECT api_record_id,
       MAX(CASE WHEN field_name='sjS1fOrd' THEN order_value END) AS s1f_order,
       MAX(CASE WHEN field_name='sjS1fOrd' THEN order_status END) AS s1f_order_status,
       MAX(CASE WHEN field_name='sj_1cOrd' THEN order_value END) AS c1_order,
       MAX(CASE WHEN field_name='sj_1cOrd' THEN order_status END) AS c1_order_status,
       MAX(CASE WHEN field_name='sj_2cOrd' THEN order_value END) AS c2_order,
       MAX(CASE WHEN field_name='sj_2cOrd' THEN order_status END) AS c2_order_status,
       MAX(CASE WHEN field_name='sj_3cOrd' THEN order_value END) AS c3_order,
       MAX(CASE WHEN field_name='sj_3cOrd' THEN order_status END) AS c3_order_status,
       MAX(CASE WHEN field_name='sj_4cOrd' THEN order_value END) AS c4_order,
       MAX(CASE WHEN field_name='sj_4cOrd' THEN order_status END) AS c4_order_status,
       MAX(CASE WHEN field_name='sjG1fOrd' THEN order_value END) AS g1f_order,
       MAX(CASE WHEN field_name='sjG1fOrd' THEN order_status END) AS g1f_order_status,
       SUM(order_status='website_corrected') AS section_order_website_correction_count,
       SUM(order_status IN ('website_review_not_applied','api_source_changed_since_review'))
           AS section_order_review_required_count
FROM jeju_race_section_order_values
GROUP BY api_record_id;

CREATE VIEW IF NOT EXISTS jeju_race_postrace_sections_reviewed_2026 AS
SELECT a.*,
       s.s1f_order,
       s.s1f_order_status,
       s.c1_order,
       s.c1_order_status,
       s.c2_order,
       s.c2_order_status,
       s.c3_order,
       s.c3_order_status,
       s.c4_order,
       s.c4_order_status,
       s.g1f_order,
       s.g1f_order_status,
       s.section_order_website_correction_count,
       s.section_order_review_required_count
FROM jeju_race_postrace_sections_2026 a
LEFT JOIN jeju_race_section_orders s ON s.api_record_id=a.api_record_id;

-- Official sources disagree internally; preserve raw data and mask only audited fields.
CREATE TABLE IF NOT EXISTS section_internal_conflict_reviews (
    api_record_id INTEGER NOT NULL REFERENCES api_records(api_record_id),
    field_name TEXT NOT NULL,
    source_kind TEXT NOT NULL CHECK(source_kind IN ('individual_order','group')),
    raw_value_json_at_review TEXT NOT NULL CHECK(json_valid(raw_value_json_at_review)),
    api_payload_sha256_at_review TEXT NOT NULL CHECK(length(api_payload_sha256_at_review)=64),
    website_url TEXT NOT NULL,
    review_status TEXT NOT NULL CHECK(review_status='unresolved_official_internal_conflict'),
    evidence_relative_path TEXT NOT NULL,
    evidence_sha256 TEXT NOT NULL CHECK(length(evidence_sha256)=64),
    reviewed_at_utc TEXT NOT NULL,
    CHECK((source_kind='individual_order' AND field_name IN ('sjS1fOrd','sj_1cOrd','sj_2cOrd','sj_3cOrd','sj_4cOrd','sjG1fOrd'))
       OR (source_kind='group' AND field_name IN ('corner_7','corner_1','corner_2','corner_3','corner_4','corner_8'))),
    PRIMARY KEY(api_record_id,field_name)
);
CREATE VIEW IF NOT EXISTS jeju_race_section_order_quality_values AS
WITH known(race_date,meet_code,race_number,horse_number,horse_id,field_name) AS (VALUES
    ('2016-09-23',2,1,7,'3016388','sjG1fOrd'),
    ('2016-09-23',2,1,2,'3015381','sjG1fOrd'),
    ('2017-07-08',2,4,3,'3015722','sj_4cOrd'),
    ('2017-07-08',2,4,5,'3015810','sj_4cOrd'),
    ('2017-07-08',2,4,4,'3016291','sj_4cOrd'),
    ('2017-07-08',2,4,1,'3016134','sj_4cOrd'),
    ('2017-07-08',2,4,7,'3016174','sj_4cOrd'),
    ('2017-07-08',2,4,2,'3016054','sj_4cOrd'),
    ('2020-06-25',2,4,5,'3018002','sjG1fOrd'),
    ('2020-06-25',2,4,10,'3017838','sjG1fOrd'),
    ('2020-06-25',2,4,7,'3016252','sjG1fOrd'),
    ('2020-06-25',2,4,1,'3017220','sjG1fOrd'),
    ('2020-06-25',2,4,3,'3017568','sjG1fOrd'),
    ('2020-06-25',2,4,8,'3017189','sjG1fOrd'),
    ('2021-09-03',2,5,7,'3018340','sjG1fOrd'),
    ('2021-09-03',2,5,2,'3017140','sjG1fOrd'),
    ('2021-09-03',2,5,8,'3017781','sjG1fOrd'),
    ('2022-10-28',2,3,1,'3018577','sj_3cOrd'),
    ('2022-10-28',2,3,5,'3102316','sj_3cOrd'),
    ('2023-12-30',2,5,3,'3015769','sj_4cOrd'),
    ('2023-12-30',2,5,4,'3018304','sj_4cOrd'),
    ('2023-12-01',2,5,3,'3018456','sjS1fOrd'),
    ('2023-12-01',2,5,5,'3018810','sjS1fOrd'),
    ('2023-07-21',2,2,10,'3101679','sjG1fOrd'),
    ('2023-07-21',2,2,4,'3102026','sjG1fOrd'),
    ('2023-03-25',2,2,3,'3018884','sjS1fOrd'),
    ('2023-03-25',2,2,4,'3018627','sjS1fOrd'),
    ('2023-03-11',2,3,4,'3102707','sj_4cOrd'),
    ('2023-03-11',2,3,6,'3018884','sj_4cOrd'),
    ('2023-02-11',2,6,4,'3102106','sjS1fOrd'),
    ('2023-02-11',2,6,8,'3018999','sjS1fOrd'),
    ('2023-02-11',2,6,6,'3101281','sjS1fOrd'),
    ('2023-02-11',2,6,7,'3018764','sjS1fOrd'),
    ('2024-07-26',2,5,1,'3018688','sjS1fOrd'),
    ('2024-07-26',2,5,6,'3101800','sjS1fOrd'),
    ('2024-06-22',2,5,10,'3018668','sjS1fOrd'),
    ('2024-06-22',2,5,9,'3019010','sjS1fOrd'),
    ('2025-11-01',2,5,5,'3104811','sj_4cOrd'),
    ('2025-11-01',2,5,3,'3101281','sj_4cOrd'),
    ('2025-11-01',2,5,10,'3017473','sj_4cOrd'),
    ('2025-11-01',2,5,1,'3103920','sj_4cOrd'),
    ('2025-11-01',2,5,7,'3102290','sj_4cOrd'),
    ('2025-11-01',2,5,2,'3018812','sj_4cOrd'),
    ('2025-11-01',2,5,3,'3101281','sjG1fOrd'),
    ('2025-11-01',2,5,6,'3104072','sjG1fOrd'),
    ('2025-11-01',2,5,10,'3017473','sjG1fOrd'),
    ('2025-11-01',2,5,1,'3103920','sjG1fOrd'),
    ('2025-11-01',2,5,7,'3102290','sjG1fOrd'),
    ('2025-11-01',2,5,2,'3018812','sjG1fOrd'),
    ('2025-04-18',2,5,10,'3101520','sjS1fOrd'),
    ('2025-04-18',2,5,4,'3018766','sjS1fOrd'),
    ('2025-03-29',2,7,3,'3015530','sj_4cOrd'),
    ('2025-03-29',2,7,4,'3102483','sj_4cOrd'),
    ('2026-08-28',2,7,6,'3108052','sj_4cOrd'),
    ('2026-08-28',2,7,4,'3104790','sj_4cOrd'),
    ('2026-08-28',2,7,5,'3104752','sj_4cOrd'),
    ('2026-08-28',2,7,3,'3103519','sj_4cOrd'),
    ('2026-08-28',2,7,9,'3105270','sj_4cOrd'),
    ('2026-08-28',2,7,1,'3018038','sj_4cOrd'),
    ('2026-08-28',2,7,2,'3104649','sj_4cOrd'),
    ('2026-08-28',2,7,7,'3018933','sj_4cOrd'),
    ('2026-08-28',2,7,8,'3018748','sj_4cOrd'),
    ('2026-08-28',2,7,10,'3103803','sj_4cOrd'),
    ('2026-02-06',2,2,10,'3103947','sj_3cOrd'),
    ('2026-02-06',2,2,9,'3018784','sj_3cOrd'),
    ('2026-02-06',2,2,7,'3103408','sj_3cOrd'),
    ('2026-01-17',2,5,9,'3104292','sjG1fOrd'),
    ('2026-01-17',2,5,6,'3018668','sjG1fOrd'),
    ('2026-01-17',2,5,8,'3016494','sjG1fOrd'),
    ('2026-01-17',2,5,3,'3103308','sjG1fOrd'))
SELECT v.*,
       CASE WHEN k.field_name IS NOT NULL THEN NULL ELSE v.order_value END AS quality_order_value,
       CASE WHEN k.field_name IS NULL THEN v.order_status
            WHEN f.api_record_id IS NULL THEN 'internal_conflict_review_not_applied'
            WHEN f.api_payload_sha256_at_review<>v.api_payload_sha256 THEN 'api_source_changed_since_conflict_review'
            ELSE f.review_status END AS quality_order_status,
       f.evidence_relative_path AS conflict_evidence_path,
       f.evidence_sha256 AS conflict_evidence_sha256
FROM jeju_race_section_order_values v
LEFT JOIN known k ON (v.race_date,v.meet_code,v.race_number,v.horse_number,v.horse_id,v.field_name)
                   = (k.race_date,k.meet_code,k.race_number,k.horse_number,k.horse_id,k.field_name)
LEFT JOIN section_internal_conflict_reviews f ON f.api_record_id=v.api_record_id AND f.field_name=v.field_name AND f.source_kind='individual_order';
CREATE VIEW IF NOT EXISTS jeju_race_section_order_quality AS
SELECT api_record_id,
    MAX(CASE WHEN field_name='sjS1fOrd' THEN quality_order_value END) AS s1f_order,
    MAX(CASE WHEN field_name='sjS1fOrd' THEN quality_order_status END) AS s1f_order_status,
    MAX(CASE WHEN field_name='sj_1cOrd' THEN quality_order_value END) AS c1_order,
    MAX(CASE WHEN field_name='sj_1cOrd' THEN quality_order_status END) AS c1_order_status,
    MAX(CASE WHEN field_name='sj_2cOrd' THEN quality_order_value END) AS c2_order,
    MAX(CASE WHEN field_name='sj_2cOrd' THEN quality_order_status END) AS c2_order_status,
    MAX(CASE WHEN field_name='sj_3cOrd' THEN quality_order_value END) AS c3_order,
    MAX(CASE WHEN field_name='sj_3cOrd' THEN quality_order_status END) AS c3_order_status,
    MAX(CASE WHEN field_name='sj_4cOrd' THEN quality_order_value END) AS c4_order,
    MAX(CASE WHEN field_name='sj_4cOrd' THEN quality_order_status END) AS c4_order_status,
    MAX(CASE WHEN field_name='sjG1fOrd' THEN quality_order_value END) AS g1f_order,
    MAX(CASE WHEN field_name='sjG1fOrd' THEN quality_order_status END) AS g1f_order_status,
    SUM(quality_order_status IN ('unresolved_official_internal_conflict','internal_conflict_review_not_applied','api_source_changed_since_conflict_review')) AS section_internal_conflict_order_count
FROM jeju_race_section_order_quality_values GROUP BY api_record_id;
CREATE VIEW IF NOT EXISTS jeju_race_section_group_quality_values AS
WITH fields(point,field_name) AS (VALUES ('S1F','corner_7'),
    ('1C','corner_1'),
    ('2C','corner_2'),
    ('3C','corner_3'),
    ('4C','corner_4'),
    ('G1F','corner_8')),
known(race_date,meet_code,race_number,point) AS (VALUES ('2016-09-23',2,1,'G1F'),
    ('2017-07-08',2,4,'4C'),
    ('2020-06-25',2,4,'G1F'),
    ('2021-09-03',2,5,'G1F'),
    ('2022-10-28',2,3,'3C'),
    ('2023-02-11',2,6,'S1F'),
    ('2023-03-11',2,3,'4C'),
    ('2023-03-25',2,2,'S1F'),
    ('2023-07-21',2,2,'G1F'),
    ('2023-12-01',2,5,'S1F'),
    ('2023-12-30',2,5,'4C'),
    ('2024-06-22',2,5,'S1F'),
    ('2024-07-26',2,5,'S1F'),
    ('2025-03-29',2,7,'4C'),
    ('2025-04-18',2,5,'S1F'),
    ('2025-11-01',2,5,'4C'),
    ('2025-11-01',2,5,'G1F'),
    ('2026-01-17',2,5,'G1F'),
    ('2026-02-06',2,2,'3C'),
    ('2026-08-28',2,7,'4C')),
raw AS (
 SELECT r.api_record_id,r.race_date,r.meet_code,r.race_number,p.point,p.field_name,
        json_extract(a.payload_json,'$.'||p.field_name) AS group_raw,
        a.payload_sha256,s.raw_relative_path,s.sha256 AS source_page_sha256
 FROM api303_corner_rank_rows r JOIN api_records a USING(api_record_id)
 JOIN source_artifacts s USING(source_artifact_id) CROSS JOIN fields p WHERE r.meet_code=2
)
SELECT r.*,
       CASE WHEN k.point IS NOT NULL THEN NULL
            WHEN trim(COALESCE(r.group_raw,'')) IN ('','-','0','X') THEN NULL ELSE r.group_raw END AS group_value,
       CASE WHEN k.point IS NOT NULL AND f.api_record_id IS NULL THEN 'internal_conflict_review_not_applied'
            WHEN k.point IS NOT NULL AND f.api_payload_sha256_at_review<>r.payload_sha256 THEN 'api_source_changed_since_conflict_review'
            WHEN k.point IS NOT NULL THEN f.review_status
            WHEN trim(COALESCE(r.group_raw,'')) IN ('','-','0','X') THEN 'api_group_unavailable'
            ELSE 'api_group_unreviewed' END AS group_status,
       f.evidence_relative_path AS conflict_evidence_path,f.evidence_sha256 AS conflict_evidence_sha256
FROM raw r LEFT JOIN known k ON (r.race_date,r.meet_code,r.race_number,r.point)=(k.race_date,k.meet_code,k.race_number,k.point)
LEFT JOIN section_internal_conflict_reviews f ON f.api_record_id=r.api_record_id AND f.field_name=r.field_name AND f.source_kind='group';
CREATE VIEW IF NOT EXISTS jeju_race_section_group_quality AS
SELECT api_record_id,
    MAX(CASE WHEN point='S1F' THEN group_value END) AS s1f_group,
    MAX(CASE WHEN point='S1F' THEN group_status END) AS s1f_group_status,
    MAX(CASE WHEN point='1C' THEN group_value END) AS c1_group,
    MAX(CASE WHEN point='1C' THEN group_status END) AS c1_group_status,
    MAX(CASE WHEN point='2C' THEN group_value END) AS c2_group,
    MAX(CASE WHEN point='2C' THEN group_status END) AS c2_group_status,
    MAX(CASE WHEN point='3C' THEN group_value END) AS c3_group,
    MAX(CASE WHEN point='3C' THEN group_status END) AS c3_group_status,
    MAX(CASE WHEN point='4C' THEN group_value END) AS c4_group,
    MAX(CASE WHEN point='4C' THEN group_status END) AS c4_group_status,
    MAX(CASE WHEN point='G1F' THEN group_value END) AS g1f_group,
    MAX(CASE WHEN point='G1F' THEN group_status END) AS g1f_group_status,
    SUM(group_status IN ('unresolved_official_internal_conflict','internal_conflict_review_not_applied','api_source_changed_since_conflict_review')) AS section_internal_conflict_group_count
FROM jeju_race_section_group_quality_values GROUP BY api_record_id;
CREATE VIEW IF NOT EXISTS jeju_race_postrace_sections_quality_2026 AS
SELECT a.api_record_id,
       a.race_date,
       a.meet_code,
       a.race_number,
       a.horse_number,
       a.horse_id,
       a.horse_name,
       a.historical_horse_name_raw,
       a.race_distance_m,
       a.rank_class_raw,
       a.race_name_raw,
       a.finish_position,
       a.finish_status_raw,
       a.finish_time_seconds,
       a.carried_weight_kg,
       a.body_weight_raw,
       a.jockey_id,
       a.jockey_name,
       a.trainer_id,
       a.trainer_name,
       a.owner_id,
       a.owner_name,
       a.track_raw,
       a.weather_raw,
       a.breed_label_raw,
       a.breed_assessment,
       a.breed_assessment_note,
       a.api4_3_sjS1fOrd_raw,
       a.api4_3_sjS1fOrd_json_type,
       a.api4_3_sjG1fOrd_raw,
       a.api4_3_sjG1fOrd_json_type,
       a.api4_3_sjG3fOrd_raw,
       a.api4_3_sjG3fOrd_json_type,
       a.api4_3_sj_1cOrd_raw,
       a.api4_3_sj_1cOrd_json_type,
       a.api4_3_sj_2cOrd_raw,
       a.api4_3_sj_2cOrd_json_type,
       a.api4_3_sj_3cOrd_raw,
       a.api4_3_sj_3cOrd_json_type,
       a.api4_3_sj_4cOrd_raw,
       a.api4_3_sj_4cOrd_json_type,
       a.api4_3_payload_sha256,
       a.api4_3_source_artifact_id,
       a.api4_3_source_page_sha256,
       a.api4_3_source_page_path,
       a.api303_api_record_id,
       a.api303_meet_raw,
       a.api303_meet_json_type,
       a.api303_corner_1_raw,
       a.api303_corner_1_json_type,
       a.api303_corner_2_raw,
       a.api303_corner_2_json_type,
       a.api303_corner_3_raw,
       a.api303_corner_3_json_type,
       a.api303_corner_4_raw,
       a.api303_corner_4_json_type,
       a.api303_corner_5_raw,
       a.api303_corner_5_json_type,
       a.api303_corner_6_raw,
       a.api303_corner_6_json_type,
       a.api303_corner_7_raw,
       a.api303_corner_7_json_type,
       a.api303_corner_8_raw,
       a.api303_corner_8_json_type,
       a.api303_corner_9_raw,
       a.api303_corner_9_json_type,
       a.api303_passtime_3f_raw,
       a.api303_passtime_3f_json_type,
       a.api303_passtime_4f_raw,
       a.api303_passtime_4f_json_type,
       a.api303_tempo_raw,
       a.api303_tempo_json_type,
       a.api303_payload_sha256,
       a.api303_source_artifact_id,
       a.api303_source_page_sha256,
       a.api303_source_page_path,
       a.birth_date_raw,
       a.birth_year,
       a.age,
       a.age_2026,
       a.age_reference_year,
       a.age_at_race_raw,
       a.age_at_race_json_type,
       a.sex,
       a.sex_at_race_raw,
       a.sex_at_race_json_type,
       a.sex_current_profile,
       a.horse_profile_observation_id,
       a.profile_api_record_id,
       a.profile_age_raw,
       a.profile_observed_at_utc,
       a.profile_observed_kst_date,
       a.profile_payload_json,
       a.profile_payload_sha256,
       a.profile_source_artifact_id,
       a.profile_source_response_sha256,
       a.profile_raw_relative_path,
       a.s1f_time_seconds,
       a.s1f_time_status,
       a.c1_time_seconds,
       a.c1_time_status,
       a.c2_time_seconds,
       a.c2_time_status,
       a.c3_time_seconds,
       a.c3_time_status,
       a.c4_time_seconds,
       a.c4_time_status,
       a.g3f_time_seconds,
       a.g3f_time_status,
       a.g1f_time_seconds,
       a.g1f_time_status,
       a.section_time_website_correction_count,
       a.section_time_review_required_count,
       a.section_order_website_correction_count,
       a.section_order_review_required_count,
       o.s1f_order,
       o.s1f_order_status,
       g.s1f_group,
       g.s1f_group_status,
       o.c1_order,
       o.c1_order_status,
       g.c1_group,
       g.c1_group_status,
       o.c2_order,
       o.c2_order_status,
       g.c2_group,
       g.c2_group_status,
       o.c3_order,
       o.c3_order_status,
       g.c3_group,
       g.c3_group_status,
       o.c4_order,
       o.c4_order_status,
       g.c4_group,
       g.c4_group_status,
       o.g1f_order,
       o.g1f_order_status,
       g.g1f_group,
       g.g1f_group_status,
       o.section_internal_conflict_order_count,
       g.section_internal_conflict_group_count
FROM jeju_race_postrace_sections_reviewed_2026 a
LEFT JOIN jeju_race_section_order_quality o ON o.api_record_id=a.api_record_id
LEFT JOIN jeju_race_section_group_quality g ON g.api_record_id=a.api303_api_record_id;


-- 2026-10-15: daily-training rider identity reference and exact website observations.
CREATE TABLE IF NOT EXISTS training_rider_identity_reviews (
    rider_category_raw TEXT NOT NULL,
    employee_number_raw TEXT NOT NULL,
    rider_name TEXT,
    reference_person_kind TEXT,
    identity_status TEXT NOT NULL,
    training_rows INTEGER NOT NULL CHECK(training_rows > 0),
    first_training_date TEXT NOT NULL,
    last_training_date TEXT NOT NULL,
    witness_api_record_id INTEGER REFERENCES api_records(api_record_id),
    witness_payload_sha256 TEXT,
    evidence_json TEXT NOT NULL,
    PRIMARY KEY (rider_category_raw, employee_number_raw),
    CHECK (rider_name IS NULL OR employee_number_raw NOT IN ('', '-')),
    CHECK ((rider_name IS NULL AND identity_status NOT LIKE 'matched_%') OR
           (rider_name IS NOT NULL AND identity_status LIKE 'matched_%')),
    CHECK (reference_person_kind IS NULL OR reference_person_kind IN ('기수', '조교사', '홈페이지기승자'))
);

CREATE TABLE IF NOT EXISTS training_rider_website_observations (
    daily_training_api_row_id INTEGER PRIMARY KEY REFERENCES daily_training_api_rows(daily_training_api_row_id),
    employee_number_raw TEXT NOT NULL CHECK(employee_number_raw NOT IN ('','-')),
    rider_category_raw TEXT NOT NULL,
    person_name TEXT,
    rider_name_raw TEXT NOT NULL,
    source_path TEXT NOT NULL,
    source_sha256 TEXT NOT NULL CHECK(length(source_sha256)=64),
    source_url TEXT NOT NULL
);

CREATE VIEW IF NOT EXISTS daily_training_riders AS
SELECT d.*,
       CASE WHEN r.witness_api_record_id IS NOT NULL
                  AND a.payload_sha256 IS NOT r.witness_payload_sha256
            THEN NULL ELSE r.rider_name END AS rider_name,
       CASE WHEN d.prNo_raw NOT IN ('', '-') THEN d.prNo_raw END AS rider_employee_number,
       r.reference_person_kind AS rider_reference_person_kind,
       CASE WHEN r.employee_number_raw IS NULL THEN 'identity_review_not_applied'
            WHEN r.witness_api_record_id IS NOT NULL
                 AND a.payload_sha256 IS NOT r.witness_payload_sha256
                 THEN 'identity_reference_source_changed'
            ELSE r.identity_status END AS rider_identity_status,
       r.evidence_json AS rider_identity_evidence_json,
       w.person_name AS rider_name_on_website,
       w.rider_name_raw AS rider_label_on_website_raw,
       CASE WHEN w.person_name IS NOT NULL THEN 1 ELSE 0 END AS rider_name_same_event_website_verified
FROM daily_training_api_rows d
LEFT JOIN training_rider_identity_reviews r
  ON r.rider_category_raw=d.prGubun_raw AND r.employee_number_raw=d.prNo_raw
LEFT JOIN api_records a ON a.api_record_id=r.witness_api_record_id
LEFT JOIN training_rider_website_observations w
  ON w.daily_training_api_row_id=d.daily_training_api_row_id
 AND w.employee_number_raw=d.prNo_raw AND w.rider_category_raw=d.prGubun_raw;

CREATE VIEW IF NOT EXISTS daily_training_riders_analysis_2026 AS
SELECT d.*,
       CASE WHEN r.witness_api_record_id IS NOT NULL
                  AND a.payload_sha256 IS NOT r.witness_payload_sha256
            THEN NULL ELSE r.rider_name END AS rider_name,
       CASE WHEN d.prNo_raw NOT IN ('', '-') THEN d.prNo_raw END AS rider_employee_number,
       r.reference_person_kind AS rider_reference_person_kind,
       CASE WHEN r.employee_number_raw IS NULL THEN 'identity_review_not_applied'
            WHEN r.witness_api_record_id IS NOT NULL
                 AND a.payload_sha256 IS NOT r.witness_payload_sha256
                 THEN 'identity_reference_source_changed'
            ELSE r.identity_status END AS rider_identity_status,
       r.evidence_json AS rider_identity_evidence_json,
       w.person_name AS rider_name_on_website,
       w.rider_name_raw AS rider_label_on_website_raw,
       CASE WHEN w.person_name IS NOT NULL THEN 1 ELSE 0 END AS rider_name_same_event_website_verified
FROM daily_training_api_rows_analysis_2026 d
LEFT JOIN training_rider_identity_reviews r
  ON r.rider_category_raw=d.prGubun_raw AND r.employee_number_raw=d.prNo_raw
LEFT JOIN api_records a ON a.api_record_id=r.witness_api_record_id
LEFT JOIN training_rider_website_observations w
  ON w.daily_training_api_row_id=d.daily_training_api_row_id
 AND w.employee_number_raw=d.prNo_raw AND w.rider_category_raw=d.prGubun_raw;


-- 2026-10-15: event-specific rider types; names only for classified jockeys.
CREATE TABLE IF NOT EXISTS daily_training_rider_type_assignments (
    daily_training_api_row_id INTEGER PRIMARY KEY REFERENCES daily_training_api_rows(daily_training_api_row_id),
    daily_training_api_artifact_id INTEGER NOT NULL REFERENCES daily_training_api_artifacts(daily_training_api_artifact_id),
    prGubun_raw TEXT,
    prNo_raw TEXT,
    horse_id TEXT,
    training_date TEXT NOT NULL,
    start_time_local TEXT,
    end_time_local TEXT,
    duration_seconds INTEGER,
    rider_type TEXT NOT NULL CHECK(rider_type IN ('기수','조교사','조교보','조교승인','기수후보생','주로조교','교육생','기수트랙라이더','미분류')),
    type_status TEXT NOT NULL,
    website_type TEXT,
    website_label_raw TEXT,
    website_jockey_name TEXT,
    website_source_path TEXT,
    website_sha256 TEXT CHECK(website_sha256 IS NULL OR length(website_sha256)=64)
);

CREATE VIEW IF NOT EXISTS daily_training_rider_type_values AS
SELECT d.daily_training_api_row_id,
       CASE WHEN t.daily_training_api_row_id IS NULL THEN '미분류'
            WHEN t.daily_training_api_artifact_id IS NOT d.daily_training_api_artifact_id
              OR t.prGubun_raw IS NOT d.prGubun_raw OR t.prNo_raw IS NOT d.prNo_raw
              OR t.horse_id IS NOT d.horse_id OR t.training_date IS NOT d.training_date
              OR t.start_time_local IS NOT d.start_time_local OR t.end_time_local IS NOT d.end_time_local
              OR t.duration_seconds IS NOT d.duration_seconds THEN '미분류'
            ELSE t.rider_type END AS rider_type,
       CASE WHEN t.daily_training_api_row_id IS NULL THEN 'type_review_not_applied'
            WHEN t.daily_training_api_artifact_id IS NOT d.daily_training_api_artifact_id
              OR t.prGubun_raw IS NOT d.prGubun_raw OR t.prNo_raw IS NOT d.prNo_raw
              OR t.horse_id IS NOT d.horse_id OR t.training_date IS NOT d.training_date
              OR t.start_time_local IS NOT d.start_time_local OR t.end_time_local IS NOT d.end_time_local
              OR t.duration_seconds IS NOT d.duration_seconds THEN 'type_source_fields_changed'
            ELSE t.type_status END AS rider_type_status,
       t.website_type AS rider_type_on_website,
       t.website_label_raw AS rider_label_on_website_raw,
       t.website_jockey_name,
       t.website_source_path AS rider_type_website_source_path,
       t.website_sha256 AS rider_type_website_sha256
FROM daily_training_api_rows d
LEFT JOIN daily_training_rider_type_assignments t USING(daily_training_api_row_id);

CREATE VIEW IF NOT EXISTS daily_training_rider_types AS
SELECT d.*, v.rider_type, v.rider_type_status,
       CASE WHEN v.rider_type='기수' THEN COALESCE(v.website_jockey_name,n.rider_name) END AS jockey_name,
       CASE WHEN v.rider_type<>'기수' THEN 'not_applicable'
            WHEN COALESCE(v.website_jockey_name,n.rider_name) IS NULL THEN 'jockey_name_unresolved'
            ELSE 'jockey_name_available' END AS jockey_name_status,
       v.rider_type_on_website,v.rider_label_on_website_raw,
       v.rider_type_website_source_path,v.rider_type_website_sha256
FROM daily_training_api_rows d
JOIN daily_training_rider_type_values v USING(daily_training_api_row_id)
LEFT JOIN daily_training_riders n USING(daily_training_api_row_id);

CREATE VIEW IF NOT EXISTS daily_training_rider_types_analysis_2026 AS
SELECT d.*, v.rider_type, v.rider_type_status,
       CASE WHEN v.rider_type='기수' THEN COALESCE(v.website_jockey_name,n.rider_name) END AS jockey_name,
       CASE WHEN v.rider_type<>'기수' THEN 'not_applicable'
            WHEN COALESCE(v.website_jockey_name,n.rider_name) IS NULL THEN 'jockey_name_unresolved'
            ELSE 'jockey_name_available' END AS jockey_name_status,
       v.rider_type_on_website,v.rider_label_on_website_raw,
       v.rider_type_website_source_path,v.rider_type_website_sha256
FROM daily_training_api_rows_analysis_2026 d
JOIN daily_training_rider_type_values v USING(daily_training_api_row_id)
LEFT JOIN daily_training_riders n USING(daily_training_api_row_id);
