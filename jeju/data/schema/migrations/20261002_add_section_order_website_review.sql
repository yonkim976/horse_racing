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
