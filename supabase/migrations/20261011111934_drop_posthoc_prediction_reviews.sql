-- Remove known-result review scenarios at the operator's request.
-- Original prediction runs, probabilities, and settlements remain untouched.
SET LOCAL lock_timeout = '3s';
SET LOCAL statement_timeout = '15s';
DROP TABLE IF EXISTS public.posthoc_prediction_reviews;
