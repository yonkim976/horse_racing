# Conditional finish-order head over frozen F1_STYLE6 Top3 sets

Status: frozen research design awaiting root review of the outcome-free source preflight. No conditional-order model has been fitted and no evaluation outcomes or market metrics have been calculated.

## Research question and preservation boundary

Keep the saved `F1_STYLE6` horse scorer fixed. Its raw scores, saved year-specific temperature, runner `P(Top3)`, and unordered exact-Top3 set distribution remain the existing source outputs. Add a conditional order distribution only inside each already-scored three-horse set. The existing standalone pair-ID QPL predictions remain separate and untouched.

For a race with runner set `R`, the frozen unordered Top3 probability for set `T` is

`q(T) = softmax_T(E(T) / tau_Y)`, where `E(T) = sum(sort(score_h for h in T))` and `tau_Y` is the saved `F1_STYLE6_Y/meta.json` temperature. Reproduce the native evaluator's sorted-score energy, canonical horse-number triple ordering, stable energy ranking, and normalization. Do not include `q`, `tau_Y`, or any q-derived probability in H1 or H2 fitting.

For each set `T={i,j,k}`, define runner utility `u_h = betaᵀ z_h` and a Plackett–Luce conditional order law:

`P(i,j,k | T) = exp(u_i)/sum_{h in T}exp(u_h) × exp(u_j)/(exp(u_j)+exp(u_k))`.

The ordered joint is `P(i,j,k)=q(T)P(i,j,k|T)`. The six conditional orders sum to one, so summing over their six orders recovers exactly `q(T)`. Consequently the existing runner Top3 marginals, TLA set probabilities, and q-derived QPL pair-in-Top3 probabilities are unchanged by construction. A zero coefficient vector gives a uniform `1/6` conditional order and joint probability `q(T)/6`.

Derive all four ordered pools only by summing this full ordered joint:

- `WIN(h)`: sum all ordered triples whose first runner is `h`.
- `QNL({a,b})`: sum all ordered triples whose first-two unordered set is `{a,b}`.
- `EXA(a→b)`: sum all ordered triples whose first two runners are `a,b` in that order.
- `TRI(a→b→c)`: the probability of that exact ordered triple.

Each race's event probabilities must sum to one within each pool's categorical event space. The native `F1_STYLE6` unordered q and a standalone pair-ID QPL model are not substitutes for these ordered event probabilities.

## Frozen inputs and temporal folds

Use only the saved `F1_STYLE6_Y/calibration_scores.parquet` and its matching frozen runner features for H1/H2 in evaluation year `Y`; this file contains prior-year OOS scores and labels. Use the matching `evaluation_scores.parquet` only for the evaluation year. Do not combine same `api_record_id` values across score artifacts or folds. The evaluation years are 2024, 2025, and partial 2026, with the frozen cohort of 1,779 races, 17,412 runners, and 269 race dates through 2026-09-19.

For each fold, H1 is January–June of `Y−1`; H2 is July–December of `Y−1`; evaluation is calendar year `Y`. Keep all races on a date together. Purge every H1 race date later than `first_H2_date − 2 calendar days`. Confirm `saved_refit_max ≤ first_H1_date − 2d`, `last_H1_date ≤ first_H2_date − 2d`, and `last_H2_date ≤ first_evaluation_date − 2d`. Expected post-purge H1/H2 race counts are 312/336 for evaluation 2024, 326/311 for 2025, and 329/325 for 2026. Any key, source, date, or count mismatch stops the study.

The actual winning order label is the ordered `finish_position` 1, 2, 3 among the actual Top3 set, used only for H1 conditional-order fitting, H2 temperature calibration, and evaluation after separate root approval. Preflight checks roster and label structure but does not report outcome performance.

## Conditional-order features and fit

The only raw runner inputs are saved raw score and the six existing STYLE6 fields:

`hist_s1f_relpos_mean5`, `hist_s1f_relpos_n`, `hist_s1f_to_c4_forward_mean5`, `hist_s1f_to_c4_pair_n`, `hist_c4_to_g1f_forward_mean5`, `hist_c4_to_g1f_pair_n`.

Add exactly three indicators for missing `mean5` values, for ten transformed inputs total. Do not add horse/jockey IDs, race IDs, odds, new feature groups, or postrace fields. Check each count is an integer in 0..5 and `count=0` exactly when its paired mean is missing. Impute missing mean values to their H1 weighted mean and retain the corresponding indicator and count.

Estimate all transformation means and standard deviations from H1 only, using every H1 runner with weight `1/N_r` so each race has total weight one. For a missing-mean column, use only valid H1 observations to estimate its weighted mean, impute missing entries to that mean, then compute its H1 weighted standard deviation on the complete imputed runner table. Apply the frozen H1 transformation to H2 and evaluation. A standard deviation `≤1e−12` maps that transformed column to zero and is recorded. Standardization uses all H1 runners and no outcome labels.

Fit one shared `beta` per fold on each H1 race's observed finish order conditional on that race's known actual Top3 set. H1 loss is the equal-race average conditional PL negative log likelihood plus fixed ridge:

`L(beta) = mean_r[-log P(order_r | actual_Top3_r; beta)] + 0.5 × 0.01 × ||beta||²`.

Use no intercept. Fix `lambda=0.01` once; do not sweep or retune. Optimize once from `beta=0` with a deterministic analytic-gradient SciPy L-BFGS-B run (`maxiter=500`, `ftol=1e−12`, `gtol=1e−8`). Accept only `success=True`, finite parameters/objective/gradient, and gradient infinity norm `≤1e−6`; otherwise stop without retry.

Fit one positive scalar order temperature per fold on H2 conditional-order labels only, by minimizing equal-race conditional PL NLL for utilities `u/T`. Fix the bounds to `T∈[0.05,20]`, initialize at `T=1`, and use a single deterministic analytic-gradient L-BFGS-B fit (`maxiter=500`, `ftol=1e−12`, `gtol=1e−8`). Accept only a finite successful fit with projected gradient infinity norm `≤1e−6`; otherwise stop. H2 does not update beta or any feature transform. Evaluation outcomes never select or tune the head, temperature, or thresholds.

## Controls, evaluation, and adoption gate

Report two diagnostic controls: uniform conditional order `q(T)/6`, and fixed-score conditional PL with utility equal to the saved raw runner score and temperature 1, with no fit or calibration. These are new, explicitly constructed controls; neither is described as a previously saved native ordered prediction.

The primary probability measure is race-equal categorical NLL of the observed order within the known actual Top3 set, candidate head versus the fixed-score conditional PL control. Since q is identical, the candidate-minus-control full ordered TRI NLL difference is mathematically identical to the conditional-order NLL difference; report both and assert their equality. Report rank-1 conditional-order accuracy only among the three known Top3 runners, clearly labeled as conditional accuracy. Separately report the whole-race rank-1 TRI hit rate from the maximum probability over every ordered triple in the full field. Use the same fixed 2,000 × 269 date bootstrap schedule from the prior direct-pair study for paired confidence intervals.

Secondary metrics are categorical six-order Brier, WIN/QNL/EXA/TRI categorical NLL and multiclass Brier, event rank-1 hit rates, and a same-467-race comparison with the saved `HY_R_FORM` operating predictions. The 467-race comparison is descriptive; it does not replace the fixed-score control or change the primary gate. The 2025 operating comparison is unavailable. Odds and one-ticket postrace EV use only the prior 10 fixed policies and existing pool-specific price scopes; they are secondary postrace analyses and never enter training, H2 calibration, or model selection. Exclude a race from TRI price analysis if any whole-race candidate quote is the `9999.9` sentinel; use the same 222 TRI-complete races and universal 222-race scope as the fixed prior study.

The head is an acceptable research candidate only if source/time/coherence checks pass, the candidate improves conditional-order NLL over fixed-score PL with the paired date-bootstrap 95% interval favoring improvement, and whole-race rank-1 TRI hit rate does not regress against fixed-score PL. Conditional rank-1 accuracy is diagnostic and cannot replace the whole-race guard. Pool-specific WIN/QNL/EXA/TRI metrics are reported as tradeoffs; they do not need to all improve. This is not an automatic production promotion. The existing `HY_R_FORM` evaluation remains fixed and the existing standalone pair-ID QPL results remain unchanged.

No model fit, H2 calibration, evaluation probability table, outcome metric, odds analysis, registry change, database access, network access, production change, or edit to a prior study is authorized before root reviews this plan, input contract, gradient check, and source preflight and separately approves fitting.
