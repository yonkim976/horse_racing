-- Preserve horse_medical.diagnosis_1/2 verbatim. Catalog only distinct,
-- non-placeholder source phrases; clinical synonym merging needs review.
CREATE TABLE public.medical_diagnosis_terms (
    id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    raw_text varchar(200) NOT NULL,
    CONSTRAINT uq_medical_diagnosis_terms_raw_text UNIQUE (raw_text)
);

CREATE TABLE public.horse_medical_diagnoses (
    horse_medical_id integer NOT NULL
        REFERENCES public.horse_medical(id) ON DELETE CASCADE,
    source_slot smallint NOT NULL CHECK (source_slot IN (1, 2)),
    term_id integer NOT NULL
        REFERENCES public.medical_diagnosis_terms(id) ON DELETE RESTRICT,
    CONSTRAINT pk_horse_medical_diagnoses
        PRIMARY KEY (horse_medical_id, source_slot)
);

CREATE INDEX ix_horse_medical_diagnoses_term_id
    ON public.horse_medical_diagnoses (term_id);

INSERT INTO public.medical_diagnosis_terms (raw_text)
SELECT DISTINCT raw_text
FROM (
    SELECT trim(diagnosis_1) AS raw_text FROM public.horse_medical
    UNION ALL
    SELECT trim(diagnosis_2) AS raw_text FROM public.horse_medical
) AS source_terms
WHERE raw_text IS NOT NULL AND raw_text NOT IN ('', '-');

INSERT INTO public.horse_medical_diagnoses
    (horse_medical_id, source_slot, term_id)
SELECT m.id, 1, t.id
FROM public.horse_medical AS m
JOIN public.medical_diagnosis_terms AS t
  ON t.raw_text = trim(m.diagnosis_1)
WHERE m.diagnosis_1 IS NOT NULL
  AND trim(m.diagnosis_1) NOT IN ('', '-');

INSERT INTO public.horse_medical_diagnoses
    (horse_medical_id, source_slot, term_id)
SELECT m.id, 2, t.id
FROM public.horse_medical AS m
JOIN public.medical_diagnosis_terms AS t
  ON t.raw_text = trim(m.diagnosis_2)
WHERE m.diagnosis_2 IS NOT NULL
  AND trim(m.diagnosis_2) NOT IN ('', '-');

-- These internal catalog tables are not browser-facing APIs.
ALTER TABLE public.medical_diagnosis_terms ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.horse_medical_diagnoses ENABLE ROW LEVEL SECURITY;
REVOKE ALL PRIVILEGES ON public.medical_diagnosis_terms
    FROM PUBLIC, anon, authenticated;
REVOKE ALL PRIVILEGES ON public.horse_medical_diagnoses
    FROM PUBLIC, anon, authenticated;
REVOKE ALL PRIVILEGES ON SEQUENCE public.medical_diagnosis_terms_id_seq
    FROM PUBLIC, anon, authenticated;
