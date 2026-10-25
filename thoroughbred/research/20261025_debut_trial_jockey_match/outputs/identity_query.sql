SELECT r.row_key,t.jockey_id_for_completed_trial AS trial_jockey_id,
      t.jockey_name_with_review AS trial_jockey_name,t.api_jkNo AS trial_jockey_raw_id,
      t.jockey_id_review_status_with_official_web AS trial_jockey_identity_status,
      t.source_file AS identity_source_file,t.source_item_index AS identity_source_item_index,
      t.api_rcTime AS identity_source_time
      FROM r JOIN trial_participants_entity_reviewed t ON r.selected_trial_id=t.participant_row_id
