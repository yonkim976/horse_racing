SELECT r.row_key,
      count(t.participant_row_id) FILTER(WHERE t.jockey_id_for_completed_trial=r.jockey_id_raw) AS any_same_completed_count,
      max(cast(t.trial_date AS DATE)) FILTER(WHERE t.jockey_id_for_completed_trial=r.jockey_id_raw) AS last_same_completed_date,
      arg_max(t.jockey_id_for_completed_trial,struct_pack(d:=cast(t.trial_date AS DATE),n:=try_cast(t.trial_no AS INTEGER),k:=t.participant_row_id)) AS last_completed_jockey_id,
      max(cast(t.trial_date AS DATE)) AS last_completed_date
      FROM r LEFT JOIN trial_participants_entity_reviewed t ON lpad(t.resolved_horse_id,7,'0')=r.horse_id
      AND cast(t.trial_date AS DATE)<=r.cutoff AND cast(t.trial_date AS DATE)>=r.date-INTERVAL 365 DAY
      AND try_cast(t.api_rcTime AS DOUBLE)>0 AND t.jockey_id_for_completed_trial IS NOT NULL
      GROUP BY r.row_key
