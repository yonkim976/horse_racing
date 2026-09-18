ALTER TABLE public.jockeys
ALTER COLUMN kra_jockey_id TYPE text;

ALTER TABLE public.trainers
ALTER COLUMN kra_trainer_id TYPE text;

ALTER TABLE public.owners
ALTER COLUMN kra_owner_id TYPE text;

ALTER TABLE public.jockey_changes
ALTER COLUMN jockey_before_id TYPE text,
ALTER COLUMN jockey_after_id TYPE text;

ALTER TABLE public.races
ALTER COLUMN status TYPE text;

ALTER TABLE public.running_trials
ALTER COLUMN track_condition TYPE text;
