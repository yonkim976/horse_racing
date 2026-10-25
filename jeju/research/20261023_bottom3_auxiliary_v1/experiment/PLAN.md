# Bottom3 auxiliary classifier — experiment plan

State: implementation and synthetic/structural checks only until the supervisor writes a hash-bound one-run approval. No fitting or Bottom3 probability/performance calculation is allowed before that approval. This is one fixed candidate and one fixed baseline comparison under `supervisor/DESIGN_CONTRACT.md` (SHA-256 `ff6e3af2d454cd30edb56df1251700320b01de3478939c98199e0886bf22f084`).

## Candidate and reference

- **L:** Reuse the saved raw S score for the same provider-year and invert its sign: `u_L = -score_S`. L is a low-S-score selection reference, not an S model trained on Bottom3.
- **B:** Train one annual binary LightGBM scorer using the same 40 S input columns, preprocessing, category vocabulary, split, weights, and hyperparameters. Only the target changes to `1[finish_position >= field_n - 2]`. Higher raw B score indicates higher Bottom3 risk.
- For either utility vector and positive temperature `T`, assign every unordered exact-three-horse subset A probability `softmax(sum(u_i/T), |A|=3)`, normalized over all `C(N,3)` subsets. Fit a separate L and B temperature for each evaluation vintage on that vintage's prior-year OOS scores and Bottom3 set-NLL. Bounds are `[0.35,4]`; evaluate both endpoints and the bounded optimum. The S Top3 PL temperatures are not reused.

## Cohort and temporal protocol

Use the frozen 2017+ normal-complete cohort: 52,155 runner rows across 5,206 races. Evaluation is the fixed 2024–2026-09-19 cohort: 17,412 runners, 1,779 races, 269 dates (637/654/488 races by year). Require `field_n >= 3`, a complete unique roster, exact ranks `1..N`, and exactly three Bottom3 labels per race. No DNF, ties, cancellation, or incomplete fields are relabeled as last place.

For each vintage Y in 2024/2025/2026, train on 2017..Y−3, early-stop on Y−2, refit through Y−2 at the selected iteration, calibrate on Y−1, and evaluate on Y. Category vocabularies come from the initial train window only and stay fixed for refit, as in S. All rows from a race remain together. S score rows are restricted to `arm=S` with provider year Y and `role=calibration` for Y−1 or `role=evaluation` for Y. Do not use another provider's score for the same race.

The training label set has 15,618 Bottom3 positives; the fixed evaluation set has 5,337. Fit exactly three initial B models and three refits (six LightGBM calls total), and calibrate six temperatures (L/B × three years). Do not add seeds, hyperparameter search, checkpoints, or alternate targets.

## Metrics and fixed gates

For each race and arm save categorical Bottom3 set NLL and one-hot Brier sum, plus mean-per-runner binary Bottom3 log loss and Brier. Save per-runner marginal `p_bottom3`, with each race's probabilities summing to 3. The set distribution must sum to 1 over all unordered size-three subsets; never derive subset probability from products of marginals and never use `1-p_bottom3` as Top3 probability.

For selection, choose three runners sequentially by highest raw utility, using `1e-12` as a fixed numerical tie tolerance and horse number as the tie-break. Save the selected and actual Bottom3 horse numbers, captured count 0..3, precision/recall, exact-set match, Top3 exclusion count/any flag, all-Top3-retained flag, and winner-excluded flag. This is an exclusion analysis, not a ticket model.

Paired bootstrap resamples the frozen dates, resampling the same dates for both arms and normalizing by race count. The **prediction research gate** requires B−L set-NLL 95% bootstrap upper bound `<0`, set Brier difference `<=0`, and runner binary log loss and Brier differences `<=0`. The separate **exclusion auxiliary gate** additionally requires the point differences for any-Top3-excluded rate and winner-excluded rate to be `<=0`. The latter is not a statistical noninferiority claim or authorization to exclude runners in practice. Both the overall prediction and exclusion statuses must be explicit; do not conflate them with execution completion or feature availability.

Reliability uses the frozen 16 bins separately for unordered-set events and runner events, with ALL/year periods and event-count weighting. Proper losses are race-equal. Report the full-cohort results and fixed annual summaries; do not select favorable subgroups after seeing outcomes.

## Sources, output, and approval

Read-only inputs are F1 frozen features, the previously audited S `state_features` and lineage, S provider-year OOS raw scores, S metadata/code/manifests, and the frozen 2,000×269 date bootstrap schedule. Their SHA-256 pins are recorded in the structural `outputs/source_preflight.json` and approved source list. Do not read the DB, copy input tables, mutate existing studies, or persist all `C(N,3)` probabilities.

After approval, write B calibration/evaluation raw scores, L/B evaluation runner marginals, race-level metrics/selection ledger, set/runner reliability bins, paired bootstrap draws, summary/parameters/run receipt, and three text B models. Keep every write under this `experiment/` directory, use exclusive create semantics, and refuse a second execution after the first run claim. Save feature names, train-only category vocabularies, model metadata, annual split counts, temperature objective/endpoint diagnostics, hashes, and environment so the fixed run can be replayed. The total study cap is 30,000,000 bytes.
