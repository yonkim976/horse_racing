
WITH w AS (
 SELECT a.anchor_id,
 count(t.event_date) FILTER(WHERE t.event_date>=a.cutoff-INTERVAL 6 DAY) train_days7,
 count(t.event_date) FILTER(WHERE t.event_date>=a.cutoff-INTERVAL 13 DAY) train_days14,
 count(t.event_date) train_days28,
 CASE WHEN bool_and(t.is_valid) FILTER(WHERE t.event_date>=a.cutoff-INTERVAL 6 DAY)
 THEN sum(t.duration_minutes) FILTER(WHERE t.event_date>=a.cutoff-INTERVAL 6 DAY) END train_minutes7,
 CASE WHEN bool_and(t.is_valid) FILTER(WHERE t.event_date>=a.cutoff-INTERVAL 13 DAY)
 THEN sum(t.duration_minutes) FILTER(WHERE t.event_date>=a.cutoff-INTERVAL 13 DAY) END train_minutes14,
 CASE WHEN bool_and(t.is_valid) THEN sum(t.duration_minutes) END train_minutes28,
 count(t.event_date) FILTER(WHERE NOT t.is_valid) train_qa_days28,
 max(t.event_date) training_source_max_date
 FROM anchors a LEFT JOIN study_daily t ON a.horse_id=t.horse_id AND a.meet=t.meet
 AND t.event_date BETWEEN a.cutoff-INTERVAL 27 DAY AND a.cutoff GROUP BY a.anchor_id
), coverage AS (
 SELECT a.anchor_id,count(v.event_date) FILTER(WHERE v.coverage_status IN ('complete_rows','complete_zero_rows')
 AND NOT v.inventory_count_mismatch)/28.0 train_coverage28
 FROM anchors a LEFT JOIN training_date_coverage v ON v.dataset='daily_training' AND cast(v.meet AS INTEGER)=a.meet
 AND v.event_date BETWEEN a.cutoff-INTERVAL 27 DAY AND a.cutoff GROUP BY a.anchor_id
) SELECT * FROM w JOIN coverage USING(anchor_id) ORDER BY anchor_id
