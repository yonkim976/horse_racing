# F1_STYLE6 first-start running-trial ablation contract

## Status and scope

This is a pre-registered, retrospective comparison of the saved 30-input `F1_STYLE6` baseline and one 34-input candidate, `F1_STYLE6_DEBUT_TRIAL4`. The baseline is preserved as saved. Its three models are replayed only; they are never refit. Candidate fitting is prohibited until the root reviewer has inspected the exact source lock, prepared feature table, baseline replay, preflight receipt, and code hashes, then written `outputs/root_fit_approval.json` with the required approval fields. The fit runner enforces that receipt and refuses a repeat fit. It does not publish, register, or promote a model.

Only API20 `ridingTestResult_1` running-trial records are in scope. API21 starting exams, starting training, daily training, current horse profile columns, horse names, and race-result facts from the target event are excluded from candidate inputs. The source audit reads SQLite through read-only/query-only mode, records scoped source hashes rather than a whole-database hash, and preserves raw payload and collection provenance. No database write is part of this study.

The saved F1 cohort contains 52,155 runners in 5,206 races from 2017-01-13 through 2026-09-19. The evaluation cohort contains 17,412 runners in 1,779 races over 269 race dates from 2024-01-01 through 2026-09-19. The 1,946 rows with frozen-baseline `observed_starts == 0` are the first-start/no-observed-start cohort under that history definition; this does not prove lifetime debut. The evaluation subset contains 661 such runners in 252 races: 2024 224/90, 2025 246/89, and 2026 191/73. Distance support is 800m 415 runners/135 races, 900m 238/110, and 1000m 8/7; the primary cohort uses all distances.

The linked API20 source snapshot contains 8,824 exact native-label Jeju participant rows across 961 validated events and 3,194 distinct horses, dated 2016-01-21 through 2026-09-09. It includes 3,500 target-horse event records through each target's T−2 cutoff for all 1,946 target horses. All 961 events have invariant raw `daySerial`, consistent `(trial_date, meet=2, trial_number)` keys, exact Jeju native labels, and no duplicate horse or natural-key rows. The event roster has 6–12 rows. The source snapshot used for this work has no explicit `rcDist` payload key.

## Exact model inputs

The candidate uses these 30 original input columns, in this order, with their saved values and row order unchanged:

```text
distance_m
grade_raw
field_n
observed_starts
days_since_start
previous_age
previous_sex
same_starts
same_valid_times
days_since_same
last_time_s
mean5_s
valid_n5
opp_mean5_valid_n
opp_mean5_valid_fraction
opp_mean5_median_s
mean5_minus_opp_mean_s
mean5_minus_opp_median_s
mean5_minus_opp_fast2mean_s
opp_mean5_faster_n
mean5_rank_fraction
previous_finish_relative_rank
previous_top3
previous_result_status
hist_s1f_relpos_mean5
hist_s1f_relpos_n
hist_s1f_to_c4_forward_mean5
hist_s1f_to_c4_pair_n
hist_c4_to_g1f_forward_mean5
hist_c4_to_g1f_pair_n
```

Append this one fixed four-column bundle, in this order:

| Feature | Definition |
|---|---|
| `trial_peer_relative_time_mean3` | Arithmetic mean of usable values among the latest three registered target horse-event records through T−2. Each value is `(target rcTime − median(rcTime of other eligible exact-Jeju horses in the same event)) / that peer median`. The target is excluded from its peer set. If no selected slot is usable, NULL. |
| `trial_peer_relative_time_n3` | Number of usable relative-time values among those fixed latest-three event records, 0–3. |
| `trial_days_since_latest_event_pre` | Race date minus date of the latest registered target horse-event record through T−2, in calendar days. Unusable and canceled records still determine recency. NULL when there is no registered record. |
| `trial_event_count_pre` | Count of distinct registered target horse-event keys through T−2, including canceled or unperformed records. This is a record count, not a claim that every event was performed. NULL is never used for a cold row; no record gives 0. |

The within-event time signal is eligible only when raw `rcTime` is finite and positive, raw `ord` is an integer from 1 through 89, and raw `passFlag` belongs to the source-audited known-judgment set `{합격, 불합격, 주행불합격, 출발불합격, 불합격(능검), 발주불합격, 불합격(발검)}`. Special ordinal codes and non-allowlisted judgment values remain raw and held. They remain in the event count, recency, and latest-three lineage but cannot contribute a relative time. A target value additionally needs at least two other eligible exact-Jeju participants in that same event. API20 has no distance field in this source snapshot, so raw seconds are never pooled across events or combined with race times.

For each frozen baseline row with `observed_starts == 0`, include all eligible API20 records with `trial_date <= race_date − 2 calendar days`, including the cutoff date. Sort by trial date, trial number, and source API row ID as a deterministic tie-break. Select the latest three actual records; do not backfill an invalid slot with an older valid event. Every model input added here is NULL for every row with `observed_starts > 0`, including its counts. The source audit records 3,413/3,500 target records meeting time/order/judgment eligibility; 3,168/3,240 latest-three records are eligible. The core and candidate preflight independently verify all four feature values against the root's separately reconstructed reference for all 1,946 targets.

The event date is not a publication timestamp. Historical public availability is unverified; applying T−2 is a retrospective cutoff, not proof that records were visible at that time. The trial event ordering is by date and `trial_number`; it is not treated as within-day clock time.

## Fitting and evaluation protocol

The candidate has exactly 34 model inputs: the unchanged 30 baseline inputs followed by the four fields above. It uses the saved STYLE6 parameters, seed 20261008, training-year categorical vocabularies, field-size weights `1 / field_n`, existing split boundaries, and the existing Top3 temperature calibration. Candidate fit is limited to the 2024, 2025, and 2026 folds: two LightGBM training calls per fold (six total) and one temperature optimization per fold (three total). There are no additional model variants, tuning, or post-result refits.

The primary outcome is runner-binary Top3 log loss and Brier score in the 252 cold-containing evaluation races. Within each race, first average losses across that race's cold runners; then give each race equal weight. The primary group includes all 661 cold runners, including rows without a usable trial signal. Compare candidate minus saved-baseline loss. Use the common date bootstrap schedule `jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy` with its locked 2,000 × 269 draws and SHA-256 `d141b0c3f9a463cbfc9d1f4c61228b58757c31aee4ec74b79f41c5baeadaccbd`. Dates without cold evaluation races contribute zero loss sum and zero race count.

The pre-set gate requires both cold-subset point estimates to be below zero and at least one paired 95% fixed-date bootstrap upper bound below zero. Secondary diagnostics include full-cohort metrics, experienced-only metrics, year and distance groups, Top5 and canonical top-six combination summaries, signal coverage, and within-race cold raw-score concordance. Concordance uses the 118 eligible races and 398 cross-label cold pairs; a positive–negative pair scores 1 if the positive's raw score is higher, 0.5 for an exact tie, and 0 otherwise, then pair-average and equal-race-average. It is descriptive, not a gate. Raw scores define ties to avoid probability-sum rounding.

No automatic promotion or production change is permitted. A candidate fit can alter experienced-horse raw scores even though all four added columns are NULL for those rows; report this as a separate diagnostic and do not claim experienced scores are frozen. Results are retrospective, development-period comparisons and do not establish future performance or contemporaneous trial-data availability.
