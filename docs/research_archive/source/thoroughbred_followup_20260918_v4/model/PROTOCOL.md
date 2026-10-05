# Frozen v4/model protocol

Frozen before any v4 model result was inspected. The immutable comparator is v3
`top3_allcore`; `win72_pl` is also reported. Only 2021--2024 development results
may select a model. Results from 2025--2026 are already exposed reference results.

One candidate is allowed and run: `top3_growth_strength`, the v3 direct Top-3
set-energy candidate with all v3 core features plus six numeric features:

1. strict-prior last-five normalized finish OLS slope;
2. strict-prior recent-three versus cumulative-career normalized finish level;
3. strict-prior last-three mean leave-one-out opponent pre-race ELO;
4. the preceding value minus the current card's pre-race mean ELO;
5. current card age minus four;
6. age-minus-four times `log1p(strict-prior starts)`.

Histories use v3's canonical corrected finish order and update after a complete date,
so another result on the same date cannot enter a feature. Current-card opponent
means are leave-one-out and use only pre-race ELO. The candidate uses
the v3 fit/tune/cal/eval windows, seed, 60/120 iteration choice, target-specific
temperature calibration, tie definitions, full-card primary cohort, and exact
joint A/B/C evaluation unchanged.

Selection requires, on pooled 2021--2024 full-card races, log loss no worse than
v3 and top-1 exact hit rate no worse than v3, with at least one strict improvement.
For each of Seoul and Busan separately, log loss must be non-worse in at least
three of four years and top-1 hit rate must be non-worse in at least three of four
years. This gate is applied independently to A, B, and C. Failed targets retain
v3. Ties retain v3. No 2025--2026 value may alter selection.

Amendment before valid results: the first run was interrupted during 2022 after a
code review found that its implementation did not match items 2--3 and used the
preserved raw finish-order column. Its uninspected partial artifacts are retained
under `invalid_attempt_01`; they are ineligible. This clarified protocol and corrected
implementation were re-frozen before the clean run.
