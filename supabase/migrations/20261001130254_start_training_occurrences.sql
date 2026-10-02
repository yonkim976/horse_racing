-- Applied remotely as 20261001130254; occurrence_no is NOT an actual event ID.
SET lock_timeout = '10s';
SET statement_timeout = '120s';
ALTER TABLE public.horse_start_training
  ADD COLUMN occurrence_no integer NOT NULL DEFAULT 1,
  ADD COLUMN source_kind varchar(30) NOT NULL DEFAULT 'legacy_api22',
  ADD COLUMN source_document_id integer,
  ADD COLUMN source_row_no integer,
  ADD COLUMN location_raw text;
WITH ranked AS (
  SELECT id, row_number() OVER (PARTITION BY horse_id, meet_code, training_date_local ORDER BY id)::integer n
  FROM public.horse_start_training
)
UPDATE public.horse_start_training t SET occurrence_no=r.n FROM ranked r WHERE t.id=r.id;
ALTER TABLE public.horse_start_training
  DROP CONSTRAINT uq_horse_start_training_natural,
  ADD CONSTRAINT uq_horse_start_training_occurrence UNIQUE(horse_id,meet_code,training_date_local,occurrence_no),
  ADD CONSTRAINT ck_start_training_positive_occurrence CHECK(occurrence_no>0),
  ADD CONSTRAINT fk_start_training_source_document FOREIGN KEY(source_document_id) REFERENCES public.source_documents(id) ON DELETE RESTRICT;
CREATE INDEX ix_horse_start_training_source ON public.horse_start_training(source_document_id);
-- Preserve the existing private access model; no additional public grants.
