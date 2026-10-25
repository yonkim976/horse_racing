# Supplemental context and lifetime-history analysis

## Status

This is a fixed, retrospective descriptive addendum to the already completed gain/loss audit. The 2024–2026 races and outcomes have already been reused in earlier development and in the core analysis. This addendum is not a preregistration, confirmatory test, independent holdout, or evidence that the measured context was available to a prediction system at the intended decision time. It does not train a model, tune thresholds, alter coefficients, or propose a deployable gate.

The existing `INPUT_CONTRACT.json` and `outputs/` are frozen. This addendum has a separate input contract and writes only to `outputs_supplemental/`.

## Locked calculations

1. Join the fixed `runner_context.csv` only to the saved runner/features and outcome data by unique `api_record_id`; verify one-to-one exact target coverage (17,412 runners; 1,779 races). Check race IDs/date match after joining. Never join on horse number, horse name, or jockey.
2. Make one race-level context row per race. Verify `band` and numeric moisture are constant within race. Use the five source-defined bands in source order: dry, good, wet, saturated, poor. For each band and the complete cohort, report the full 1,779-race denominator share, race-date count, gained, lost, net, both-hit/both-miss, each arm's hit rate, difference, and the same 2,000-draw paired-date bootstrap interval/seed as the core audit. Bands are descriptive source categories; do not choose or merge cutpoints based on outcomes.
3. Aggregate each race's roster into means and population standard deviations (`ddof=0`) of observed body mass (kg), carried weight (kg), and runner-level carried-weight/body-mass ratio (`carried_weight_kg / body_kg`). Preserve nonmissing counts and missing shares for all three. Then summarize these race-level vectors across full cohort and the four outcome classes with race counts and nonmissing race counts, mean, median, and quartiles. Race is the unit; do not treat runners as independent replications. Do not impute missing values. No per-jockey analysis.
4. Separately describe the actual finishers in the 84 gained/lost races using the saved `y_top3` label (three rows/race), joined to the same-event context by `api_record_id`. Export the exact runner rows and group summaries by gained/lost with race-cluster support counts. This is a post-outcome, same-event diagnostic and is not used as a predictor summary.
5. Add `same_starts` and `same_valid_times` from the already hash-locked feature parquet to a separate history-extension table. Summarize these lifetime same-distance counts by full cohort and hit class, at runner-level first and then race-level roster mean/median/count summaries. Keep them distinct from `same_distance_last5_actual_n` and `same_distance_last5_normal_n`, which count support in the most recent five-slot history window. Do not alter the frozen core outputs or original contract.

## Availability and interpretation limits

The context extract is result-side, same-event information. Its source audit verifies row/key coverage, source lineage, value ranges, and internal race consistency, but does not verify publication timestamps before prediction. Therefore same-event moisture, body mass, carried weight and their ratio are retrospective explanatory context only, not validated prediction-time features. Current field size and grade are also post-race descriptors in the core audit. `horse_number` is not a verified physical gate; `jockey_id` is excluded from subgroup/rule exploration. The selected prior-pair weight/burden lineage is an incomplete selected subset and is not incorporated here; no missing records are filled with zero.

All uncertainty intervals are pointwise descriptive intervals across many comparisons. Small band/date support and multiple comparisons limit interpretation. The outcome-defined groups and actual-top3 subsets are post hoc. Any useful pattern can only motivate a bounded hypothesis for a separately designed training/validation study after verifying feature publication time and complete-history availability.

## Outputs

- `outputs_supplemental/moisture_band_condition_summary.csv`: five source bands plus full cohort, all with full-cohort denominator share and paired-date interval.
- `outputs_supplemental/race_context_vectors.csv`: one row per race with race-level roster summaries and missingness.
- `outputs_supplemental/race_context_by_outcome.csv`: descriptive outcome-class summaries of the race-level vectors.
- `outputs_supplemental/actual_top3_context_84_races.csv`: the saved actual Top3 runners in gained/lost races, keyed by API record ID.
- `outputs_supplemental/actual_top3_context_summary.csv`: descriptive same-event top-three summaries by gained/lost.
- `outputs_supplemental/lifetime_same_distance_support.csv`: separate lifetime counts and five-slot counts, with runner and race-level supports.
- `outputs_supplemental/supplemental_receipt.json`: source/helper hash checks, join checks, counts, and output hashes.

