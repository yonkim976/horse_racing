# Frozen v5 windows protocol

Frozen before any v5 candidate result is computed or inspected.

## Question and fixed candidates

This is a pure training-window/recency ablation of v4 `top3_growth_strength`.
The feature set, target construction, model family, hyperparameters, tuning,
calibration, probability construction, and frozen v2 win ordering score remain
fixed. The 110 model features are obtained by an exact-key one-to-one join of
v3 `prepared_context.parquet` and v4/model `strict_features.parquet` on
`race_id`, `hr_no`, and `race_date`. No historical feature is recomputed from
labels.

Exactly four candidates are admitted:

1. `rolling_all`: all eligible fit history from 2006-01-01 through the fold fit cutoff.
2. `rolling_3y`: fit rows in the trailing three years through the fit cutoff, inclusive.
3. `rolling_5y`: fit rows in the trailing five years through the fit cutoff, inclusive.
4. `rolling_decay2y`: the same history as `rolling_all`, with the original
   race-balanced row weight multiplied by `exp(-ln(2) * age_days / 730.5)`,
   where `age_days = fit_cutoff - race_date`. The decay factors are normalized
   to mean one across FIT races before multiplication. This holds total race
   weight, and therefore the LightGBM regularization scale, equal to
   `rolling_all`; normalization is a constant factor and preserves relative
   exponential weights exactly.

Date-window candidates retain whole calendar dates. The lower bound is the day
after `fit_cutoff - DateOffset(years=N)` so the window has exactly N years of
eligible dates ending on the cutoff. All candidates use Seoul and Busan only.

## Half-year walk-forward folds

Evaluation folds are 2021H1 through 2026H2; 2026H2 ends 2026-09-13.

For H1 evaluation starting January 1 of year Y:

- FIT ends Y-1 June 30;
- TUNE is Y-1 Q3;
- CAL is Y-1 Q4.

For H2 evaluation starting July 1 of year Y:

- FIT ends Y-1 December 31;
- TUNE is Y Q1;
- CAL is Y Q2.

Evaluation is full-card primary. Final-starter evaluation is supplemental when
the cohort has at least three eligible runners. The frozen v2 annual
`H3_relative` win-score bundle for year Y orders horses within each predicted
podium set for both Y half-years. This annual win bundle was trained before all
Y evaluation parts. Its stored venue temperature is used; an unknown venue uses
1.0. The direct Top-3 set-energy bundle is trained to 120 rounds, tuned between
60 and 120 on B log loss, trimmed to the selected iteration, and calibrated on
the fixed CAL quarter. Categorical vocabularies are learned on FIT only and are
never refit.

## Selection and reference isolation

The primary decision target is A (per-horse Top-3 inclusion), matching the
user's top-one focus through A race-top1 hit. Development uses only full-card
2021-2024 folds, pooled over both half-years. A candidate qualifies only if:

- pooled A race-top1 hit is at least the current target baseline and pooled A
  log loss is at most that baseline, with at least one strict improvement;
- in each of Seoul and Busan separately, annual A log loss is non-worse in at
  least three of four years and annual A race-top1 hit is non-worse in at least
  three of four years.

Qualified candidates rank by pooled A hit descending, then pooled A log loss
ascending, then the fixed candidate order above. If none qualifies, the current
target baseline is retained. The current A target baseline is v3
`top3_allcore`; the current B and C target baselines are v4
`top3_growth_strength`. Both are reported for all three targets. Comparisons use
the exact same races. To isolate the half-year schedule from the window choice, the
three recency candidates are also compared directly with `rolling_all` on exact
same half-year races.

Selection is frozen after all 2021-2024 development outputs and before any v5
2025-2026 reference aggregate is produced or inspected. Existing exposed
2025-2026 v3/v4 files may be read only after this freeze for reporting.

## Outputs and invariants

Store fold bundles, vocabularies, selected iterations, temperatures, calibration
support, split support, horse-level A probabilities, Top-10 B/C predictions,
and long race metrics with `race_id`, `race_date`, `venue_code`, `year`, half,
target, candidate, log loss, Brier score, and hit. Report annual, half-year,
calibration, A-threshold, and B/C Top-K summaries. Every evaluated race must
retain the complete normalized support over all unordered and ordered podium
triples; A sums to 3, B and C sum to 1, C marginalizes to B, and B marginalizes
to A within 1e-10.

The output directory is create-once. The runner refuses to overwrite model or
result artifacts. A reusable inference adapter and a final-H2-2026 bundle may be
exported only for the selected candidate. A complete fixed September 19/20 v4
card may be exported only if a v5 candidate is selected; no forecast is required
for an unselected candidate.
