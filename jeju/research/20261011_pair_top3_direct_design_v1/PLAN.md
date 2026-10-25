# Direct pair-in-Top3 learner: frozen design

Status: independent review memo, 2026-10-11; no fit or outcome calculation. The execution-authoritative plan and input contract are `jeju/research/20261011_pair_top3_direct_v1/PLAN.md` and `INPUT_CONTRACT.md`. This memo records the design review and source-based rationale only; it is not a second execution contract. If details differ, the authoritative research folder controls.

## Question and target

For each race, select one unordered pair `{i,j}` and estimate whether both runners belong to the actual Top3. The pair label is `y_ij = 1` exactly when both `finish_position_i <= 3` and `finish_position_j <= 3`. Each eligible complete normal-finish race must have exactly three Top3 runners, hence exactly three positive pair labels and `C(N,2)` total pair examples. The current data include races with field sizes from 7 to 12.

This model estimates pair-in-Top3 events. It does not estimate exact first/second place, a pair-plus-third combination, any ordered result, or a normalized distribution over all Top3 pairs. Exact-Top2 is omitted from the study; it is not a secondary label. The study does not compute or score combination tickets.

## Fixed baseline and single direct model

Within each fold and race, use the saved `F1_STYLE6` raw runner scores `s_i` without refitting or changing them. For each unordered triple `T`, define `E_0(T) = math.fsum(s_i for i in T)` in ascending horse-number order and `q_0(T) = softmax_T(E_0(T))`, which fixes the additive distribution temperature at `tau=1`. Compute the softmax with stable exponentiation after subtracting the maximum energy and `math.fsum` over canonical triple order. Do not use any saved full-year temperature. The baseline pair probability is `p_0(i,j) = math.fsum(q_0(T) for T in canonical_order if i,j in T)`.

For positive `w_i=exp(s_i)`, the unnormalized mass of pair `{i,j}` is `w_i w_j * sum_{k != i,j} w_k`. Thus for `N>=4` a maximum-`p_0` pair is the two highest raw runner scores, with the same horse-number tie rule. The outcome-free preflight must verify this parity for every source race using the canonical sums above; a mismatch fails closed. These are one policy under two representations, not two independent performance comparisons.

For every pair, the direct model uses an offset logit `logit(p_0(i,j))` plus one fitted correction, `p_1(i,j) = sigmoid(logit(p_0(i,j)) + betaᵀ x(i,j))`. There is no additional fitted intercept in this H1 correction. `p_0` is a coherent baseline from a full Top3-set distribution and sums to 3 over all pairs in a race. `p_1` is an independent binary-model output: it is not guaranteed to sum to 3 or to correspond to any shared Top3-set distribution. Do not renormalize or clip the fitted predictions to force that identity.

The fixed 20-dimensional symmetric feature basis uses seven runner values—raw F1 score, the three style-history means, and their three support counts. For each of the seven values, add pair sum and absolute difference (14 columns). For each of the three means, add `either_missing` and `both_missing` indicators (6 columns). Means are valid exactly when the corresponding count is an integer in `1..5` and the mean is finite; count 0 must pair with a null mean. The pair feature is invariant to swapping horses. Set a missing mean to zero after H1-only runner standardization, and retain the two missingness indicators. IDs, race number, horse number, result labels, and any market or current-race post-result data are prohibited as predictors.

Compute runner-value means and population standard deviations from H1 only, with race-equal runner weights `1/N_r`; for style means, use valid observations only. A zero-variance feature maps to zero and is recorded. Standardization metadata is frozen per fold and applied unchanged to H2 and evaluation data.

Fit one coefficient vector from H1 with no class resampling or positive-class weighting. Let `M_r=C(N_r,2)`, `eta_ij=logit(p_0(i,j))+betaᵀx_ij`. Minimize the race-equal binary cross-entropy with fixed ridge penalty `lambda=1.0`:

`L(beta) = (1/R) sum_r [(1/M_r) sum_{i<j} (log(1+exp(eta_ij)) - y_ij eta_ij)] + 0.5 ||beta||²`.

Initialize `beta=0` and use one deterministic L-BFGS-B fit with an analytic gradient, `maxiter=500`, `ftol=1e-12`, and `gtol=1e-8`. A failed fit is reported as failed; do not retry with another optimizer, penalty, basis, or model. The natural class frequency is retained because class balancing changes probability semantics.

## Calendar folds and calibration

For each evaluation year `Y ∈ {2024, 2025, 2026}`, use that year's saved `F1_STYLE6_Y/calibration_scores.parquet` and matching `features.parquet` rows for H1/H2 in Y−1. H1 is January 1 through June 30; H2 is July 1 through December 31. Keep every race and all its runners together. Purge H1 races whose date is later than `min(H2 race_date)-2 days`. Require `max(H2 race_date) <= min(evaluation race_date)-2 days` and `F1 refit_max <= min(H1 race_date)-2 days`. Evaluation uses the same fold's saved `evaluation_scores.parquet` and runner rows in Y. See the exact path hashes and source date ranges in [SOURCE_AUDIT.md](SOURCE_AUDIT.md).

Use H2 labels only for a fixed positive-slope Platt calibration of logits: `sigmoid(a + b*eta)`, with unpenalized intercept `a` and `b >= 0`, minimizing the same race-equal pair BCE. Fit this calibrator separately for raw `p_0` and the direct candidate. The same deterministic optimization and H2 pairs apply to both. If `beta=0`, the candidate raw logits equal the baseline raw logits, so the two calibrated outputs must also match. H2 labels must not change the pair feature basis or H1 coefficients. Evaluation-year labels are held out until the frozen report.

The fold identity includes both `evaluation_year` and score artifact path. In particular, the same `api_record_id` and race date can appear in a later fold's calibration file and an earlier fold's evaluation file with different saved F1 model scores. Never join or deduplicate those records across fold paths.

## Comparisons and metrics

For each evaluation race, select one pair by maximum calibrated pair probability. Exact score ties resolve by ascending numeric `(horse_number_i, horse_number_j)`. The primary comparator is the pair of the two highest saved F1 raw runner scores, with ties by ascending horse number. The primary outcome is the difference in one-pair Top3 hit rate (direct model minus raw-score top-two). Report both hit counts and race-level paired-date bootstrap 95% intervals using 2,000 resamples and seed `20261011`; all racers on a date stay together.

Report these same-race fixed probability/selection references without choosing among them after seeing results:

- The `tau=1` additive baseline `p_0`; its maximum-probability pair is a structural alias of the raw-score top-two pair described above.
- The maximum-joint pair from both saved `matched_baseline` and `candidate` arms, with pair event probability from the saved triple distribution.
- The pair made from the two highest candidate Top3 runner marginals, with its pair probability from the same saved candidate distribution.

The maximum-pair selector for a saved arm uses the pair with largest summed probability mass over all triples containing it; ties use ascending numeric pair. The marginal reference ranks individual candidate Top3 marginals and uses horse-number ties. Label all prior joint outputs exploratory because they reuse the cohort and the prior joint candidate failed its registered gates.

Secondary probability evaluations are all-pair race-equal Brier and log loss, one-selected-pair-per-race Brier/log loss and fixed-width reliability bins with counts. Compare direct calibrated probabilities with `p_0` and the saved joint probability references where available. Also report, per race, `sum_{i<j} p_1(i,j)-3` before and after H2 calibration, with mean absolute deviation, median, 95th percentile, and maximum absolute deviation. This is a coherence diagnostic, not a correction or pass gate. Do not force the sum to 3.

The pair-event label and metrics do not answer a combination objective. Do not use a selected pair as an anchor for a third-horse choice, compute triple ticket accuracy, or call pair probability a ticket probability. Do not use exact finish ranks to evaluate exact-Top2.

## Interpretation and stopping rules

Every report must state the complete-normal-finish cohort, 2026 partial coverage, repeated historical labels, and lack of reconstructed historical public release times. Treat the 2024–2026 results as retrospective development evidence. A positive primary estimate does not establish independent future performance, operational improvement, or a causal relation between a pair's style histories. The research question and all thresholds, features, optimizer settings, comparison rules, and bootstrap settings remain fixed after outcomes are opened.

No fitting, outcome calculation, database read/write, network access, model registry change, current-model change, or publication is authorized by this design document. Run only an outcome-free source/structure preflight before separate root authorization for fitting.
