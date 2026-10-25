-- Known-result research scenarios must never enter the immutable prediction ledger.
CREATE TABLE public.posthoc_prediction_reviews (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    review_public_id uuid NOT NULL,
    source_prediction_run_id integer NOT NULL REFERENCES public.prediction_runs(id) ON DELETE RESTRICT,
    race_id integer NOT NULL REFERENCES public.races(id) ON DELETE RESTRICT,
    race_date date NOT NULL,
    review_kind text NOT NULL CHECK (review_kind = 'posthoc_result_fit'),
    method text NOT NULL CHECK (method = 'known_result_joint_mixture_top4_v1'),
    uses_known_results boolean NOT NULL CHECK (uses_known_results IS TRUE),
    counts_as_prediction boolean NOT NULL CHECK (counts_as_prediction IS FALSE),
    source_observed_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    source_publication_hash text NOT NULL CHECK (source_publication_hash ~ '^[0-9a-f]{64}$'),
    source_results_hash text NOT NULL CHECK (source_results_hash ~ '^[0-9a-f]{64}$'),
    content_sha256 text NOT NULL UNIQUE CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
    oracle_mix_alpha double precision NOT NULL CHECK (oracle_mix_alpha >= 0 AND oracle_mix_alpha <= 1),
    original_podium_in_top4 boolean NOT NULL,
    scenario_podium_in_top4 boolean NOT NULL CHECK (scenario_podium_in_top4 IS TRUE),
    source_results jsonb NOT NULL CHECK (jsonb_typeof(source_results) = 'array'),
    scenario_runners jsonb NOT NULL CHECK (jsonb_typeof(scenario_runners) = 'array' AND jsonb_array_length(scenario_runners) >= 3),
    UNIQUE (review_public_id, race_id)
);
CREATE INDEX posthoc_prediction_reviews_source_run_idx ON public.posthoc_prediction_reviews(source_prediction_run_id);
CREATE INDEX posthoc_prediction_reviews_race_idx ON public.posthoc_prediction_reviews(race_id);
COMMENT ON TABLE public.posthoc_prediction_reviews IS
    'Known-result, in-sample research scenarios. Not forecasts, calibration estimates, live publications, or model evaluation records. Original prediction ledger is preserved.';
COMMENT ON COLUMN public.posthoc_prediction_reviews.scenario_runners IS
    'Original runner probabilities alongside known-result mixture weights; scenario weights must not be presented as pre-race predictions.';
ALTER TABLE public.posthoc_prediction_reviews ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.posthoc_prediction_reviews FROM PUBLIC, anon, authenticated;
REVOKE ALL ON SEQUENCE public.posthoc_prediction_reviews_id_seq FROM PUBLIC, anon, authenticated;
