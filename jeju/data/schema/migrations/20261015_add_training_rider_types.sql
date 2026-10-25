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
