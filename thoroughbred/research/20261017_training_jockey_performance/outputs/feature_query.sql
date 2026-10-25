
    WITH t AS (
      SELECT t.* FROM daily_training_rider_linked t
      JOIN training_date_coverage c ON c.dataset=t.dataset AND c.event_date=t.event_date
        AND c.meet=t.meet AND c.selected_capture_id=t.capture_id
      WHERE t.meet IN ('1','3') AND t.event_date >= DATE '2017-12-01'
        AND c.coverage_status='complete_rows' AND NOT c.inventory_count_mismatch
    ), a AS (
      SELECT r.row_key, w.days AS window_days,
        count(t.observation_id) AS training_rows,
        count(DISTINCT t.event_date) AS training_days,
        count(t.observation_id) FILTER(WHERE t.rider_type_raw='기수') AS jockey_rows,
        count(DISTINCT t.event_date) FILTER(WHERE t.rider_type_raw='기수') AS jockey_days,
        count(t.observation_id) FILTER(WHERE coalesce(trim(t.rider_type_raw),'') IN ('','-')) AS unknown_role_rows,
        count(t.observation_id) FILTER(WHERE t.rider_type_raw='기수' AND t.rider_official_id_linked=r.jockey_id
          AND r.jockey_id!='') AS race_jockey_rows,
        count(DISTINCT t.event_date) FILTER(WHERE t.rider_type_raw='기수' AND t.rider_official_id_linked=r.jockey_id
          AND r.jockey_id!='') AS race_jockey_days,
        count(t.observation_id) FILTER(WHERE t.rider_type_raw='기수' AND t.rider_official_id_linked IS NULL) AS jockey_unlinked_rows,
        sum(try_cast(t.duration_seconds_raw AS DOUBLE)) AS duration_seconds,
        count(try_cast(t.duration_seconds_raw AS DOUBLE)) AS duration_observed_rows,
        sum(try_cast(t.canter_count_raw AS DOUBLE)) AS canter_count,
        sum(try_cast(t.gallop_count_raw AS DOUBLE)) AS gallop_count,
        min(t.event_date) AS first_training_date, max(t.event_date) AS last_training_date
      FROM r CROSS JOIN (VALUES (14),(28)) w(days)
      LEFT JOIN t ON t.official_horse_id=r.horse_id AND t.meet=r.meet_code
        AND t.event_date>=r.date-w.days*INTERVAL 1 DAY AND t.event_date<r.date
      GROUP BY r.row_key,w.days
    ), c AS (
      SELECT r.row_key,w.days AS window_days,
        count(c.event_date) FILTER(WHERE c.coverage_status IN ('complete_rows','complete_zero_rows')
          AND NOT c.inventory_count_mismatch) AS supported_calendar_days
      FROM r CROSS JOIN (VALUES (14),(28)) w(days)
      LEFT JOIN training_date_coverage c ON c.dataset='daily_training' AND c.meet=r.meet_code
        AND c.event_date>=r.date-w.days*INTERVAL 1 DAY AND c.event_date<r.date
      GROUP BY r.row_key,w.days
    ) SELECT * FROM a JOIN c USING(row_key,window_days)
    