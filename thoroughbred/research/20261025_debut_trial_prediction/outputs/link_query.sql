WITH joined AS (
      SELECT r.row_key,t.* FROM r LEFT JOIN t ON t.horse_id=r.horse_id
        AND t.date<=r.cutoff AND t.date>=r.date-INTERVAL 365 DAY
    ) SELECT row_key,count(participant_row_id) AS trial_attempts,
      count(participant_row_id) FILTER(WHERE failed) AS trial_failures,
      count(participant_row_id) FILTER(WHERE practice) AS trial_practices,
      count(participant_row_id) FILTER(WHERE new_reason AND passed) AS new_passes,
      count(participant_row_id) FILTER(WHERE passed) AS trial_passes,
      arg_max(participant_row_id,struct_pack(d:=date,n:=trial_no_num,k:=participant_row_id)) FILTER(WHERE passed) AS selected_trial_id,
      min(finish) FILTER(WHERE passed) AS best_finish,
      arg_min(finish,struct_pack(d:=date,n:=trial_no_num,k:=participant_row_id)) FILTER(WHERE passed AND valid_finish) AS first_pass_finish,
      max(date) AS last_any_trial_date
      FROM joined GROUP BY row_key
