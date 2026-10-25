WITH p AS (
      SELECT f.row_key,s.date AS prior_date,s.top3,s.finish_p,
        row_number() OVER(PARTITION BY f.row_key ORDER BY s.date DESC) AS slot
      FROM field f LEFT JOIN all_starts s ON s.horse_id=f.horse_id AND s.date<=f.cutoff
        AND s.date>=f.date-INTERVAL 730 DAY
    ) SELECT row_key,count(prior_date) AS prior_n5,avg(top3) AS prior_top3_mean5,
      avg(finish_p) AS prior_finish_p5,max(prior_date) AS history_last
      FROM p WHERE slot<=5 GROUP BY row_key
