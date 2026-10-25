SELECT w.row_key,w.window,count(p.horse_id_raw) AS history_n,
      (coalesce(sum(CASE WHEN p.result_rank_raw='1' THEN 1 ELSE 0 END),0)+2)/(count(p.horse_id_raw)+20.0) AS prior_win,
      (coalesce(sum(CASE WHEN try_cast(p.result_rank_raw AS INTEGER) BETWEEN 1 AND 3 THEN 1 ELSE 0 END),0)+5)/(count(p.horse_id_raw)+20.0) AS prior_top3,
      max(p.result_date) AS history_last
      FROM w LEFT JOIN confirmed_runners p ON p.jockey_id_raw=w.trial_jockey_id
      AND p.result_date<=strftime(w.history_cutoff,'%Y%m%d')
      AND p.result_date>=strftime(w.anchor-INTERVAL 365 DAY,'%Y%m%d')
      AND (try_cast(p.result_rank_raw AS INTEGER) BETWEEN 1 AND 89 OR p.result_rank_raw IN ('91','92'))
      GROUP BY w.row_key,w.window
