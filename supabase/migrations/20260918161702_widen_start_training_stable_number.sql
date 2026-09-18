ALTER TABLE public.horse_start_training
ALTER COLUMN stable_number TYPE text
USING stable_number::text;
