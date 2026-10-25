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
