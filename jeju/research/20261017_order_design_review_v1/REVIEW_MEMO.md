# Conditional finishing-order head: independent design review

Review date: 2026-10-17. This was a read-only source and design review. I read saved research artifacts and locally joined the frozen Parquet sources for identity and label checks. No database or network source was accessed; no model was fit and no outcome metric was calculated.

## Data support

The frozen runner source is `jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet` (52,155 rows). Its key columns are `api_record_id`, `race_id`, `race_date`, `horse_id`, `horse_number`, `field_n`, and `finish_position`; the six style inputs are:

- `hist_s1f_relpos_mean5`, `hist_s1f_relpos_n`
- `hist_s1f_to_c4_forward_mean5`, `hist_s1f_to_c4_pair_n`
- `hist_c4_to_g1f_forward_mean5`, `hist_c4_to_g1f_pair_n`

The three means are NULL exactly when their corresponding count is zero; counts are integer values from 0 through 5. The style-history contract describes these as historical same-distance S1F/C4/G1F position summaries using T−2 eligible source data. They are not current-race outcomes.

I joined the 52,155 feature rows to `jeju/research/20261008_horse_profile_baseline_v1/outputs_v2/source_snapshot.parquet`. Both keys were unique; all 52,155 feature rows matched; race ID, date, horse ID, horse number, and finish position matched exactly; and every matched snapshot row was `started=True`. I then joined all six fold-specific score files to the feature table. Each join was complete and one-to-one, and all 3,727 race-record occurrences across those files had complete official finish positions exactly `1..N` (some race dates recur under different fold-specific score artifacts).

Each raw score Parquet has exactly `api_record_id, score`. Keep every path fold-qualified: a date and `api_record_id` can recur under a different saved refit model. Existing `20261011_pair_top3_direct_design_v1/SOURCE_AUDIT.md` records the per-fold split counts, runner counts, date ranges, T−2 checks, and refit cutoffs:

| Evaluation fold | H1 after T−2 purge | H2 temperature calibration | Evaluation |
|---:|---:|---:|---:|
| 2024 | 3,089 runners / 312 races / 47 dates | 3,327 / 336 / 50 | 6,329 / 637 / 98 |
| 2025 | 3,244 / 326 / 50 | 3,085 / 311 / 48 | 6,410 / 654 / 98 |
| 2026 | 3,238 / 329 / 50 | 3,172 / 325 / 48 | 4,673 / 488 / 73 |

Use only `F1_STYLE6_Y/calibration_scores.parquet` for H1/H2 of evaluation fold Y, and its matching `evaluation_scores.parquet` for that fold's test year. The score source is raw OOS output from the saved refit model; `meta.json` records refit maxima 2022-12-24, 2023-12-30, and 2024-12-28. Keep the existing calendar split and T−2 purges; do not concatenate fold score files or alter the split after seeing results.

## Minimal conditional model

For each H1 race, use only the three horses whose labels are official finish positions 1, 2, and 3. Fit one shared runner utility from seven pre-race numeric inputs—raw saved score and the six frozen style fields—plus three mean-missing flags. Train one Plackett–Luce distribution for the observed order 1→2→3 within that true Top3 set. A race contributes one conditional ranking likelihood, the sum of its three successive choice terms. This identifies probabilities for all six permutations of that set. A position-specific three-head utility would add parameters without being necessary to express a conditional order distribution.

Estimate numeric means and scales using H1 only, with runner weights `1/N_r` so each race contributes equal standardization weight. For a missing mean, use its H1 centering value (standardized zero) and retain its explicit flag. Keep the three count inputs as numeric features. Document whether flags are left as 0/1 or scaled, and how H1-degenerate features are handled, before opening evaluation outcomes. Use no race/horse identifier, current finish label, saved Top3 marginal, or post-race field in the utility. A utility intercept is unidentifiable because it cancels from every within-race PL choice.

Fit coefficients on H1 only with the already root-fixed ridge `λ=0.01`, one deterministic optimizer run and a convergence check. Fit H2's single positive global utility temperature by conditional order likelihood only. H2 must not alter the H1 coefficient fit or select a feature set. Uniform order and a score-only conditional PL are appropriate fixed controls; keep them diagnostic and do not use evaluation results for architecture or hyperparameter choice.

## Preserve the native unordered Top3 distribution

For evaluation, reconstruct each race's native F1_STYLE6 set distribution from that fold's evaluation raw scores and its saved `meta.json['tau']` (`1.1006448744`, `1.1156577765`, and `0.9719459584` for 2024, 2025, and 2026). Follow the existing evaluator's canonical set enumeration, score summation, and softmax implementation in `jeju/research/20261010_style_history_review_v1/replay_saved_f1.py`; do not substitute another joint arm's q or the fixed-temperature pair negative control. The full-year saved tau is an output-calibration parameter for the future evaluation year. It is not an input to H1 coefficient fitting or H2 order-temperature fitting.

For every unordered triple `T`, construct the six conditional PL order probabilities and set `P(T,π)=q(T)P(π|T)`. Assert that the six probabilities sum to 1 for each T, that their joint sum is 1 per race, and that summing back over the six orders reproduces the original `q(T)` within the declared floating-point tolerance. This guarantees unchanged unordered Top3 set probabilities and any set-only derivative such as Top3 runner marginals or wide/trio events. Win, unordered first-two, exact first-two, and exact ordered Top3 probabilities can change through the conditional order head.

## Evaluation contract and limits

Use race-equal categorical losses over each complete outcome space: one winner over all runners (WIN), one unordered first-two pair (QNL), one ordered first-two pair (EXA), and one ordered Top3 sequence (TRI). Each race has one realized event in each space, so categorical NLL and multiclass Brier avoid a zero-dominated average of binary losses over all non-events. Report order-conditional NLL/Brier on the true Top3 set as a focused diagnostic; distinguish this from the deployment-style most-probable ordered triple hit computed over the complete q×PL distribution. Set-only outcomes should match native F1_STYLE6 by construction.

These are repeated historical development years, with 2026 partial through 2026-09-19. A rolling temporal split is leakage control, not an independent future holdout. The saved source contract does not reconstruct historical public release times; report that limitation. Do not interpret an order-head result as a change to the selected production model or to the unchanged Top3 set distribution.

## Existing precedents

- `jeju/research/20261011_pair_top3_direct_design_v1/SOURCE_AUDIT.md` and `INPUT_CONTRACT.md` document score joins, split inventories, T−2 checks, and exact finish completeness for the STYLE6 cohort.
- `jeju/research/20261010_style_history_review_v1/replay_saved_f1.py` defines the native F1 set softmax and shows the score/tau replay path.
- `docs/research_archive/source/thoroughbred_offline_20260918_v5/conditional_order/README.md` records an earlier conditional-order workflow in Thoroughbred research. It is design precedent only; its coefficients and feature definitions do not transfer to Jeju.
