WITH selected AS (
 SELECT t.* FROM daily_training_raw t JOIN training_date_coverage v
 ON v.dataset=t.dataset AND v.meet=t.meet AND v.event_date=t.event_date
 AND v.selected_capture_id=t.capture_id
 WHERE v.coverage_status='complete_rows' AND NOT v.inventory_count_mismatch
 AND t.meet IN ('1','3') AND nullif(t.official_horse_id,'') IS NOT NULL
), keyed AS (
 SELECT meet,official_horse_id AS horse_id,event_date,started_at_raw,ended_at_raw,
 count(*) raw_rows,
 bool_and(qa_flags_json='[]' AND try_cast(duration_seconds_raw AS DOUBLE)>0
 AND try_cast(duration_seconds_raw AS DOUBLE)<=7200) AND count(DISTINCT duration_seconds_raw)=1 AS is_valid,
 max(try_cast(duration_seconds_raw AS DOUBLE))/60.0 AS duration_minutes
 FROM selected GROUP BY meet,horse_id,event_date,started_at_raw,ended_at_raw
)
SELECT cast(meet AS INTEGER) meet,horse_id,event_date,
 count(*) sessions,sum(raw_rows) raw_rows,
 bool_and(is_valid) AS is_valid,
 CASE WHEN bool_and(is_valid) THEN sum(duration_minutes) ELSE NULL END duration_minutes
FROM keyed GROUP BY meet,horse_id,event_date
