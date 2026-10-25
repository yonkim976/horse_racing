# Frozen first-start running-trial models on a disjoint later date period

## Status

`FINAL_EVALUATION_COMPLETE_NO_PROMOTION`. Root froze the source/cohort, locked the pre-score protocol, and issued `ROOT_RELEASE.json` before fresh predictions. Evaluation used only the two saved 2026 model artifacts and their saved vocabularies/temperatures. Training, calibration, feature tuning, threshold tuning, and automatic promotion were not performed.

## Frozen comparisons

- Baseline: saved `F1_STYLE6_2026` model, exactly 30 existing input columns, saved vocabulary and `tau`.
- Candidate: saved `F1_STYLE6_DEBUT_TRIAL4_2026` model, the exact same 30 columns followed by the four frozen trial columns, saved vocabulary and `tau`.
- Both saved `top3.txt` files and their matching `meta.json` files are immutable reference artifacts. Their release hashes and the root release are recorded in [fresh_evaluation_receipt.json](outputs/fresh_evaluation_receipt.json).
- Do not refit, recalibrate, retune, change tree count, expand category vocabularies, change feature semantics or promote either study model.

The exact 30-input order is in [the earlier trial contract](../20261018_debut_trial_ablation_v1/CONTRACT.md); its prior-period values are saved in the `F1_STYLE6` feature table. Their generation sources and contracts are the baseline run script, finish-history preparation, and style-history preparation cited in [PLAN.md](PLAN.md).

## Disjoint later-period scope and cohort

The target window is 2026-09-20–2026-10-17, with 2026-10-17 as the latest complete local Jeju card verified by the independent source review. Actual local raw race data are available on seven dates: 2026-10-02, 03, 05, 09, 10, 16, and 17. No local race rows are present for 2026-09-20–10-01; this is not evidence that no races occurred then. The source freeze manifest SHA256 is `c3e08c29c6acd8c263b64649e4816e287427338464af966c103623084f56e44a`. The prior study ended on 2026-09-19 and does not overlap this cohort.

The audited source contains 49 races/464 raw entrants. The inherited full-roster/rank-sequence screen retains 45 races/426 entrants; Oct03 R2, Oct05 R3, Oct09 R2, and Oct10 R2 are held. The frozen `observed_starts == 0` cohort contains 14 entrants in six races on six dates (Oct02, 03, 05, 09, 10, 17), all at 900m. Result/status fields were used by the unchanged race-quality eligibility contract. For that reason, cohort construction is not described as fully outcome-blind, although fresh model predictions were not paired with outcomes and no performance metric was calculated until the source, feature, and protocol locks and root release were in place.

The primary cold cohort consists of runners in the confirmed period whose original 30-input history definition yields `observed_starts == 0` at race date T−2. The term means no started result observed under that history query as of the cutoff; it does not certify lifetime debut. Every eligible cold runner remains in the denominator regardless of trial coverage or whether any trial feature has a valid value. Experienced runners are retained for the pooled model and supplementary analysis, with all four added inputs NULL.

For each target, race history may roll forward only through calendar date T−2, inclusive. New target races can contribute to later target histories only when that race is itself on or before the later target's T−2 cutoff. History values cannot include post-cutoff outcomes. Rolling history updates do not change model weights, vocabulary, `tau`, or training.

## Frozen trial input definitions

The four added columns are the exact ones documented in the earlier [debut-trial contract](../20261018_debut_trial_ablation_v1/CONTRACT.md). Their source remains API20 `ridingTestResult_1` with explicit Jeju labels and official horse IDs. Same-event peer time is relative to eligible non-target peers; raw seconds are never pooled between trial events. A fixed latest-three registered-event window includes unusable records and never backfills with an older event. The cutoff is T−2. Trial date is not proof of public availability by that date.

No arbitrary zero fill or added penalty is allowed for missing warm-up history. A zero count is used only where the frozen column definition says count is genuinely zero; means remain NULL when there is no qualifying observation. Any cold/experienced distinction is from the frozen 30-input `observed_starts`, not an inferred lifetime debut.

## Outcomes and metric definitions

After source and roster locks, score every target race with both frozen models using the same frozen 30-column frame and the candidate's frozen four extra columns. The 426×34 model inputs are value-for-value equal to root's independently frozen input table. The 121-row API20 peer source produces trial4 values for all 14 cold targets and is exact against root's independent feature-core result. The root released only the frozen 2026 model evaluation; its release and model hashes are recorded in the evaluation receipt.

Primary outcomes are runner-binary Top3 log loss and Brier for cold runners. First average each metric within each race over its cold runners; then give each race with at least one cold runner equal weight. Difference is candidate minus baseline. This is a saved-model temporal evaluation and uses no fitting or calibration.

Secondary analyses are:

- Full cohort runner-binary Top3 log loss and Brier, race-equal after within-race mean.
- Experienced-runners-only loss, with candidate extra columns NULL, to show pooled-model changes for experienced runners.
- Up to six canonical tickets generated by the existing F1_STYLE6 scoring and ranking rule in cold-containing races. Keep the rule unchanged for both models.
- Cold-runner within-race raw-score concordance, limited to races with both a Top3-positive and a Top3-negative cold runner. An exact raw-score tie scores 0.5; average pairs within race before equal-race aggregation.
- Cohort support and missingness, including race days with no cold runner, with the locked total cohort counts.

The old 269-day bootstrap schedule was not reused. Uncertainty uses 20,000 paired calendar-date bootstrap draws with seed `20261018`; frozen schedules are shared across models and metrics. Cold K is six dates; each draw resamples six cold-containing dates and computes the ratio of summed cold-race losses to summed cold-race counts, giving races equal weight. Secondary all-cohort and experienced-runner analyses use the seven observed dates. The pre-registered `K < 5` flag does not apply, but six dates and 14 cold runners still provide limited precision.

## Locked fresh-period results

Lower log loss and Brier are better. Differences below are candidate minus baseline; confidence intervals use the paired date bootstrap.

| Scope | Rows / races / dates | Log loss baseline → candidate | Δ log loss (95% CI) | Brier baseline → candidate | Δ Brier (95% CI) |
|---|---:|---:|---:|---:|---:|
| Cold (`observed_starts=0`) | 14 / 6 / 6 | 0.63056 → 0.70622 | +0.07567 (−0.16623, +0.34457) | 0.22106 → 0.25245 | +0.03139 (−0.07463, +0.14538) |
| Full cohort | 426 / 45 / 7 | 0.57908 → 0.57938 | +0.00030 (−0.00676, +0.00842) | 0.19700 → 0.19725 | +0.00025 (−0.00284, +0.00351) |
| Experienced guard | 412 / 45 / 7 | 0.57633 → 0.57594 | −0.00039 (−0.00409, +0.00460) | 0.19599 → 0.19590 | −0.00009 (−0.00156, +0.00187) |

Both primary cold point estimates are worse for the candidate, and both intervals include zero. In the six cold-containing races, both models hit 2/6 frozen six-combination selections; in all 45 eligible races both hit 7/45. Within-cold raw-score concordance is 0.5 for each model, based on only three races and four positive/negative pairs. These are descriptive results, not promotion criteria. The new cold sample is all 900m and does not establish generalization to other distances. Keep it separate from the earlier 661-cold-runner/252-race evaluation.

Independent root replay agrees on runner predictions, race metrics, canonical six-ticket probabilities, and all 120,000 paired-bootstrap values. Runner/race/ticket maximum numeric difference is below `1.1e-15`; bootstrap maximum difference is `4.2e-16`; row keys and discrete decisions are exact. See [independent crosscheck in the evaluation receipt](outputs/fresh_evaluation_receipt.json), [scope summary](outputs/fresh_scope_summary.json), and the row-level outputs linked in [README.md](README.md).

## Guardrails

All new files and outputs belong in this research directory. The frozen source audit used read-only DB access and scoped source fingerprints; no database was opened during feature scoring or model evaluation. Do not edit prior studies, shared database, production model, model resolver, registry or website. Do not collect new web data under this task. Historical public availability at each target's T−2 cutoff remains unverified for some API20 records. Do not interpret the prior 661 starts/252 races as part of the new-period sample.
