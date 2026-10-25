-- Applied remote migration version: 20261007051806.
-- Existing immutable annual batches remain unchanged. Later official race-day
-- files need independent hashes/counts instead of overwriting an annual batch.
SET LOCAL lock_timeout = '5s';
ALTER TABLE public.race_point_source_batches
  DROP CONSTRAINT IF EXISTS race_point_source_batches_meet_code_race_year_key;
ALTER TABLE public.race_point_source_batches
  DROP CONSTRAINT IF EXISTS uq_race_point_source_batches_meet_year;
CREATE INDEX IF NOT EXISTS ix_race_point_source_batches_meet_year
  ON public.race_point_source_batches (meet_code, race_year);
