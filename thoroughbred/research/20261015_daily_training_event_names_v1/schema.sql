-- Additive, observation-level official web display-name evidence.
-- The raw daily_training_raw row and global rider_name_links mapping remain untouched.

CREATE TABLE daily_training_rider_event_name_links (
    observation_id VARCHAR PRIMARY KEY,
    rider_id_raw VARCHAR NOT NULL,
    event_date DATE NOT NULL,
    meet_raw VARCHAR NOT NULL,
    official_horse_id VARCHAR NOT NULL,
    horse_name_raw VARCHAR NOT NULL,
    rider_type_raw VARCHAR NOT NULL,
    started_at_raw VARCHAR NOT NULL,
    ended_at_raw VARCHAR NOT NULL,
    event_name VARCHAR NOT NULL CHECK (event_name = '다비드'),
    event_name_basis VARCHAR NOT NULL,
    source_service VARCHAR NOT NULL,
    source_file VARCHAR NOT NULL,
    source_sha256 VARCHAR NOT NULL CHECK (length(source_sha256) = 64),
    evidence_file VARCHAR NOT NULL,
    evidence_sha256 VARCHAR NOT NULL CHECK (length(evidence_sha256) = 64),
    matching_method VARCHAR NOT NULL,
    web_row_no VARCHAR NOT NULL,
    web_started_at_display VARCHAR NOT NULL,
    web_ended_at_display VARCHAR NOT NULL,
    identity_limit VARCHAR NOT NULL
);

-- Preserve the prior columns in their original order. Event evidence may supply
-- a display name, but it never supplies an official jockey ID or profile source.
CREATE VIEW daily_training_rider_linked AS
SELECT
    d.*,
    CASE
        WHEN h.observation_id IS NOT NULL THEN m.name_snapshot
        WHEN e.observation_id IS NOT NULL THEN e.event_name
        ELSE m.name_snapshot
    END AS rider_name_candidate,
    CASE
        WHEN h.observation_id IS NOT NULL THEN NULL
        WHEN e.observation_id IS NOT NULL THEN e.event_name
        ELSE m.name_snapshot
    END AS rider_name_linked,
    m.official_jockey_id_raw_string AS rider_official_id_candidate,
    CASE WHEN h.observation_id IS NOT NULL THEN NULL
         ELSE m.official_jockey_id_raw_string END AS rider_official_id_linked,
    CASE
        WHEN h.observation_id IS NOT NULL THEN 'source_conflict_hold'
        WHEN e.observation_id IS NOT NULL THEN 'exact_event_web_name_link'
        WHEN m.rider_id_raw IS NOT NULL THEN 'exact_official_profile_id_name_link'
        WHEN d.rider_id_raw = '-' THEN 'pr_no_absent'
        ELSE 'profile_id_unmatched'
    END AS rider_identity_status,
    CASE WHEN h.observation_id IS NOT NULL THEN m.name_basis
         WHEN e.observation_id IS NOT NULL THEN e.event_name_basis
         ELSE m.name_basis END AS rider_name_basis,
    CASE WHEN e.observation_id IS NOT NULL
         THEN 'exact_event_web_name_verified_profile_id_unmatched'
         ELSE COALESCE(w.event_verification_status, 'not_individually_verified')
    END AS event_verification_status,
    CASE WHEN e.observation_id IS NOT NULL THEN e.event_name
         ELSE w.web_rider_display_raw END AS event_verification_web_rider_display_raw,
    h.hold_reason AS rider_link_hold_reason,
    m.source_service AS rider_profile_source_service,
    m.source_capture_date AS rider_profile_capture_date,
    m.source_file AS rider_profile_source_file,
    m.source_sha256 AS rider_profile_source_sha256,
    m.entity_reference_roster_official_id,
    e.source_service AS event_name_source_service,
    e.source_file AS event_name_source_file,
    e.source_sha256 AS event_name_source_sha256,
    e.evidence_file AS event_name_evidence_file,
    e.evidence_sha256 AS event_name_evidence_sha256,
    e.matching_method AS event_name_matching_method,
    e.web_row_no AS event_name_web_row_no
FROM daily_training_raw AS d
LEFT JOIN rider_name_links AS m
  ON d.rider_id_raw = m.rider_id_raw
LEFT JOIN rider_identity_conflict_holds AS h
  ON d.observation_id = h.observation_id
LEFT JOIN rider_web_event_verification AS w
  ON d.observation_id = w.observation_id
LEFT JOIN daily_training_rider_event_name_links AS e
  ON d.observation_id = e.observation_id;
