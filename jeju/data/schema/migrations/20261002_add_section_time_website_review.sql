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
