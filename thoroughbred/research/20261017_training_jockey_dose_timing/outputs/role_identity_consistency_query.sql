SELECT r.year,r.meet,t.rider_type_raw,count(*) AS events,count(DISTINCT r.row_key) AS starts
      FROM r JOIN daily_training_rider_linked t ON t.official_horse_id=r.horse_id AND t.meet=r.meet_code
      AND t.event_date>=r.date-INTERVAL 14 DAY AND t.event_date<r.date
      AND t.rider_official_id_linked=r.jockey_id AND r.jockey_id!=''
      JOIN training_date_coverage c ON c.dataset=t.dataset AND c.event_date=t.event_date AND c.meet=t.meet
      AND c.selected_capture_id=t.capture_id WHERE c.coverage_status='complete_rows' AND NOT c.inventory_count_mismatch
      AND coalesce(trim(t.rider_type_raw),'')!='기수' GROUP BY ALL ORDER BY 1,2,3
