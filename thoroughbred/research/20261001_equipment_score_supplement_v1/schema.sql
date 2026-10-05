-- Additive, source-separated append schema. IDs and ranks stay text.
CREATE TABLE equipment_score_supplement (
    meet VARCHAR NOT NULL,
    result_date VARCHAR NOT NULL,
    race_no VARCHAR NOT NULL,
    horse_no VARCHAR NOT NULL,
    horse_id VARCHAR NOT NULL,
    horse_name_raw VARCHAR NOT NULL,
    normalrank VARCHAR NOT NULL,
    equipment_raw VARCHAR NOT NULL,
    source VARCHAR NOT NULL,
    source_url VARCHAR NOT NULL,
    observed_at_kst VARCHAR NOT NULL,
    observed_at_basis VARCHAR NOT NULL,
    raw_path VARCHAR NOT NULL,
    raw_sha256 VARCHAR NOT NULL,
    availability_status VARCHAR NOT NULL,
    api78_status VARCHAR NOT NULL,
    PRIMARY KEY (meet, result_date, race_no, horse_no, horse_id)
);

CREATE TABLE equipment_score_supplement_tokens (
    meet VARCHAR NOT NULL,
    result_date VARCHAR NOT NULL,
    race_no VARCHAR NOT NULL,
    horse_no VARCHAR NOT NULL,
    horse_id VARCHAR NOT NULL,
    token_position INTEGER NOT NULL,
    token_raw VARCHAR NOT NULL,
    equipment_name_raw VARCHAR NOT NULL,
    mark_status VARCHAR NOT NULL,
    source VARCHAR NOT NULL,
    source_url VARCHAR NOT NULL,
    observed_at_kst VARCHAR NOT NULL,
    observed_at_basis VARCHAR NOT NULL,
    raw_path VARCHAR NOT NULL,
    raw_sha256 VARCHAR NOT NULL,
    availability_status VARCHAR NOT NULL,
    api78_status VARCHAR NOT NULL,
    PRIMARY KEY (meet, result_date, race_no, horse_no, horse_id, token_position)
);

-- This exposes only score-table declarations with no removal marker.
-- It does not claim that the equipment was physically worn.
CREATE VIEW equipment_score_supplement_active_declared AS
SELECT *
FROM equipment_score_supplement_tokens
WHERE mark_status IN ('unmarked', 'new');
