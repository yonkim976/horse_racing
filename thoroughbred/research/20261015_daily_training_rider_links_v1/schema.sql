-- Additive rider identity evidence. Existing source objects are never altered.

CREATE TABLE rider_name_links (
    rider_id_raw VARCHAR PRIMARY KEY,
    official_jockey_id_raw_string VARCHAR NOT NULL,
    name_snapshot VARCHAR NOT NULL,
    english_name_snapshot VARCHAR,
    name_basis VARCHAR NOT NULL,
    source_service VARCHAR NOT NULL,
    source_capture_date DATE NOT NULL,
    source_file VARCHAR NOT NULL,
    source_sha256 VARCHAR NOT NULL,
    source_page_no VARCHAR,
    source_item_index_within_page VARCHAR,
    entity_reference_roster_official_id VARCHAR,
    identity_limit VARCHAR NOT NULL
);

CREATE TABLE rider_identity_conflict_holds (
    observation_id VARCHAR PRIMARY KEY,
    rider_id_raw VARCHAR NOT NULL,
    rider_type_raw VARCHAR,
    event_date DATE NOT NULL,
    meet_raw VARCHAR NOT NULL,
    official_horse_id VARCHAR,
    horse_name_raw VARCHAR,
    started_at_raw VARCHAR,
    ended_at_raw VARCHAR,
    api_profile_name_candidate VARCHAR NOT NULL,
    web_rider_display_raw VARCHAR NOT NULL,
    api_raw_path VARCHAR NOT NULL,
    api_raw_sha256 VARCHAR NOT NULL,
    api_source_row_no INTEGER,
    profile_source_service VARCHAR NOT NULL,
    profile_capture_date DATE NOT NULL,
    profile_source_file VARCHAR NOT NULL,
    profile_source_sha256 VARCHAR NOT NULL,
    web_source_html_sha256 VARCHAR NOT NULL,
    web_event_rows_path VARCHAR NOT NULL,
    web_event_rows_sha256 VARCHAR NOT NULL,
    web_verification_path VARCHAR NOT NULL,
    web_verification_sha256 VARCHAR NOT NULL,
    hold_reason VARCHAR NOT NULL,
    evidence_json VARCHAR NOT NULL
);

CREATE TABLE rider_unmatched_ids (
    rider_id_raw VARCHAR PRIMARY KEY,
    daily_training_rows BIGINT NOT NULL,
    first_event_date DATE NOT NULL,
    last_event_date DATE NOT NULL,
    distinct_horse_count BIGINT NOT NULL,
    observed_meets_json VARCHAR NOT NULL,
    observed_rider_types_json VARCHAR NOT NULL,
    identity_status VARCHAR NOT NULL,
    review_note VARCHAR NOT NULL
);

CREATE TABLE rider_web_event_verification (
    observation_id VARCHAR PRIMARY KEY,
    event_date DATE NOT NULL,
    meet_raw VARCHAR NOT NULL,
    official_horse_id VARCHAR NOT NULL,
    api_rider_id_raw VARCHAR,
    api_rider_type_raw VARCHAR,
    api_started_at_raw VARCHAR,
    api_ended_at_raw VARCHAR,
    web_row_no VARCHAR,
    web_rider_display_raw VARCHAR,
    web_person_name_present BOOLEAN NOT NULL,
    web_name_matches_profile_exact_id BOOLEAN,
    web_name_differs_only_by_literal_suffix BOOLEAN NOT NULL,
    stable_metadata_differs BOOLEAN NOT NULL,
    event_verification_status VARCHAR NOT NULL,
    web_html_sha256 VARCHAR NOT NULL,
    api_raw_path VARCHAR NOT NULL,
    api_raw_sha256 VARCHAR NOT NULL,
    api_source_row_no INTEGER,
    matching_rule VARCHAR NOT NULL,
    time_precision_note VARCHAR NOT NULL,
    source_record_json VARCHAR NOT NULL
);

CREATE VIEW daily_training_rider_linked AS
SELECT
    d.*,
    m.name_snapshot AS rider_name_candidate,
    CASE WHEN h.observation_id IS NULL THEN m.name_snapshot ELSE NULL END AS rider_name_linked,
    m.official_jockey_id_raw_string AS rider_official_id_candidate,
    CASE WHEN h.observation_id IS NULL THEN m.official_jockey_id_raw_string ELSE NULL END AS rider_official_id_linked,
    CASE
        WHEN h.observation_id IS NOT NULL THEN 'source_conflict_hold'
        WHEN m.rider_id_raw IS NOT NULL THEN 'exact_official_profile_id_name_link'
        WHEN d.rider_id_raw = '-' THEN 'pr_no_absent'
        ELSE 'profile_id_unmatched'
    END AS rider_identity_status,
    m.name_basis AS rider_name_basis,
    COALESCE(w.event_verification_status, 'not_individually_verified') AS event_verification_status,
    w.web_rider_display_raw AS event_verification_web_rider_display_raw,
    h.hold_reason AS rider_link_hold_reason,
    m.source_service AS rider_profile_source_service,
    m.source_capture_date AS rider_profile_capture_date,
    m.source_file AS rider_profile_source_file,
    m.source_sha256 AS rider_profile_source_sha256,
    m.entity_reference_roster_official_id
FROM daily_training_raw AS d
LEFT JOIN rider_name_links AS m
  ON d.rider_id_raw = m.rider_id_raw
LEFT JOIN rider_identity_conflict_holds AS h
  ON d.observation_id = h.observation_id
LEFT JOIN rider_web_event_verification AS w
  ON d.observation_id = w.observation_id;
