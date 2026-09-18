-- Cover foreign keys that are not the leading columns of an existing index.
CREATE INDEX ix_jockey_changes_horse_id
ON public.jockey_changes (horse_id);

CREATE INDEX ix_model_predictions_race_entry_id
ON public.model_predictions (race_entry_id);

CREATE INDEX ix_race_entries_owner_id
ON public.race_entries (owner_id);

CREATE INDEX ix_race_entries_trainer_id
ON public.race_entries (trainer_id);

CREATE INDEX ix_race_scratches_horse_id
ON public.race_scratches (horse_id);

CREATE INDEX ix_running_trial_results_jockey_id
ON public.running_trial_results (jockey_id);

CREATE INDEX ix_running_trial_results_trainer_id
ON public.running_trial_results (trainer_id);

CREATE INDEX ix_running_trials_source_document_id
ON public.running_trials (source_document_id);
