CREATE TABLE api6_section_distance_reviews(
 api_record_id INTEGER NOT NULL REFERENCES refresh_section_records(api_record_id),
 furlong_index INTEGER NOT NULL CHECK(furlong_index BETWEEN 1 AND 10),
 race_date TEXT NOT NULL, meet_code INTEGER NOT NULL, race_number INTEGER NOT NULL,
 race_distance_m_at_review INTEGER NOT NULL,
 api_payload_sha256_at_review TEXT NOT NULL CHECK(length(api_payload_sha256_at_review)=64),
 api_source_artifact_id_at_review INTEGER NOT NULL REFERENCES source_artifacts(source_artifact_id),
 api_source_page_sha256_at_review TEXT NOT NULL CHECK(length(api_source_page_sha256_at_review)=64),
 api_distance_m_at_review INTEGER NOT NULL,
 website_distance_m INTEGER NOT NULL CHECK(website_distance_m>0),
 effective_distance_m INTEGER NOT NULL CHECK(effective_distance_m=website_distance_m),
 review_status TEXT NOT NULL CHECK(review_status='website_corrected'),
 website_url TEXT NOT NULL, checked_date_kst TEXT NOT NULL,
 website_relative_path TEXT NOT NULL, website_sha256 TEXT NOT NULL CHECK(length(website_sha256)=64),
 evidence_relative_path TEXT NOT NULL, evidence_sha256 TEXT NOT NULL CHECK(length(evidence_sha256)=64),
 decision_reason TEXT NOT NULL, applied_at_utc TEXT NOT NULL,
 PRIMARY KEY(api_record_id,furlong_index));

CREATE VIEW api6_section_points_current AS
WITH indices(furlong_index) AS (VALUES(1),(2),(3),(4),(5),(6),(7),(8),(9),(10)),
raw AS (
 SELECT x.*,i.furlong_index,
 json_extract(payload_json,'$.rcDist') AS race_distance_m_raw,
 json_extract(payload_json,'$.dist_'||i.furlong_index||'f') AS api_distance_m_raw,
 json_type(payload_json,'$.dist_'||i.furlong_index||'f') AS api_distance_json_type,
 json_extract(payload_json,'$.time_'||i.furlong_index||'f') AS interval_time_raw,
 json_type(payload_json,'$.time_'||i.furlong_index||'f') AS interval_time_json_type,
 json_extract(payload_json,'$.passtime_'||i.furlong_index||'f') AS cumulative_time_raw,
 json_type(payload_json,'$.passtime_'||i.furlong_index||'f') AS cumulative_time_json_type
 FROM api6_section_records_current x CROSS JOIN indices i
), reviewed AS (
 SELECT b.*,r.website_distance_m,r.website_url,r.website_relative_path,r.website_sha256,
 r.evidence_relative_path,r.evidence_sha256,
 CASE WHEN b.race_date='2026-10-17' AND b.meet_code=2 AND b.race_number=5 AND b.furlong_index<=6
           AND r.api_record_id IS NULL THEN 'website_review_not_applied'
      WHEN r.api_record_id IS NOT NULL AND NOT(
       r.race_date IS b.race_date AND r.meet_code IS b.meet_code AND r.race_number IS b.race_number
       AND r.race_distance_m_at_review IS b.race_distance_m_raw
       AND r.api_payload_sha256_at_review IS b.payload_sha256
       AND r.api_source_artifact_id_at_review IS b.source_artifact_id
       AND r.api_source_page_sha256_at_review IS b.artifact_sha256
       AND r.api_distance_m_at_review IS b.api_distance_m_raw
       AND b.api_distance_json_type IN ('integer','real')
       AND r.effective_distance_m IS r.website_distance_m AND r.review_status='website_corrected'
      ) THEN 'api_source_changed_since_review'
      WHEN r.api_record_id IS NOT NULL THEN 'website_corrected'
      WHEN b.api_distance_json_type IN ('integer','real') AND b.api_distance_m_raw>0
           THEN 'api_positive_unreviewed' ELSE 'missing_or_nonpositive' END AS distance_status
 FROM raw b LEFT JOIN api6_section_distance_reviews r
 ON r.api_record_id=b.api_record_id AND r.furlong_index=b.furlong_index
 WHERE (b.api_distance_json_type IN ('integer','real') AND b.api_distance_m_raw>0)
    OR (b.interval_time_json_type IN ('integer','real') AND b.interval_time_raw>0)
    OR (b.cumulative_time_json_type IN ('integer','real') AND b.cumulative_time_raw>0)
    OR (b.race_date='2026-10-17' AND b.meet_code=2 AND b.race_number=5 AND b.furlong_index<=6)
)
SELECT *, CASE WHEN distance_status='website_corrected' THEN website_distance_m
               WHEN distance_status='api_positive_unreviewed' THEN api_distance_m_raw END AS distance_m,
 CASE WHEN interval_time_json_type IN ('integer','real') AND interval_time_raw>0 THEN interval_time_raw END AS interval_seconds,
 CASE WHEN cumulative_time_json_type IN ('integer','real') AND cumulative_time_raw>0 THEN cumulative_time_raw END AS cumulative_seconds
FROM reviewed;
