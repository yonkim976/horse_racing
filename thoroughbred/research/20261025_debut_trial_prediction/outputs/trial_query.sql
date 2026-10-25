SELECT e.participant_row_id,e.trial_session_id,e.trial_date,e.trial_no,
      e.source_meet_query,e.resolved_horse_id,e.resolved_horse_name,e.horse_identity_resolution,
      e.source_file,e.source_item_index,e.source_file_sha256,e.api_age,e.api_sex,
      e.api_reason,e.api_passFlag,e.api_track,e.api_wgBudam,e.api_wgHr,
      e.api_rcTime,e.api_rcTimeS1f,e.api_rcTimeG3f,e.api_rcTimeG1f,e.api_rcTimeG400,
      e.api_ord,e.api_s1f,e.api_g1f,e.api_g3f_4c,e.jockey_id_for_completed_trial,
      v.physical_venue,v.reviewed_distance_m
      FROM trial_participants_entity_reviewed e JOIN trial_participants_venue_reviewed v
      USING(participant_row_id)
