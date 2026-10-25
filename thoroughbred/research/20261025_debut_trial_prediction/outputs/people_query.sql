SELECT r.row_key,count(p.row_key) AS history_n,
      (coalesce(sum(p.win),0)+2)/(count(p.row_key)+20.0) AS prior_win,
      (coalesce(sum(p.top3),0)+5)/(count(p.row_key)+20.0) AS prior_top3,max(p.date) AS history_last
      FROM r LEFT JOIN all_starts p ON p.jockey_id_raw=r.jockey_id_raw
      AND r.jockey_id_raw!='' AND p.date<=r.cutoff AND p.date>=r.date-INTERVAL 365 DAY
      GROUP BY r.row_key
