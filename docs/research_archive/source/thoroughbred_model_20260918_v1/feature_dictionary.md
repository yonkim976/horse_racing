# Primary feature dictionary

`features.json` is the executable allowlist. Columns present in `prepared.parquet` but absent from that allowlist are metadata, labels, audits, or explicitly excluded variables. Every official ID remains a categorical string.

## Executable feature schema

| Feature | Exact prepared type / role | Meaning | Availability status |
|---|---|---|---|
| `venue_code` | VARCHAR/categorical | Actual venue | `scheduled_card` |
| `race_type` | VARCHAR/categorical | Official race type | `scheduled_card` |
| `race_class` | VARCHAR/categorical | Official race class | `scheduled_card` |
| `burden_type` | VARCHAR/categorical | Assigned-weight rule | `scheduled_card` |
| `rating_condition_raw` | VARCHAR/categorical | Raw rating condition | `scheduled_card` |
| `origin_raw` | VARCHAR/categorical | Horse origin | `pre_race_profile` |
| `sex_raw` | VARCHAR/categorical | Horse sex | `pre_race_profile` |
| `hr_no` | VARCHAR/categorical | Official horse ID | `scheduled_card` |
| `jockey_no` | VARCHAR/categorical | Official jockey ID | `scheduled_card` |
| `trainer_no` | VARCHAR/categorical | Official trainer ID | `scheduled_card` |
| `owner_no` | VARCHAR/categorical | Official owner ID | `scheduled_card` |
| `hist_previous_race_venue` | VARCHAR/categorical | Venue on latest confirmed earlier race date | `strict_prior_date_confirmed_history` |
| `venue_distance_class` | VARCHAR/categorical | venue|distance|class interaction | `scheduled_card` |
| `distance_m` | INTEGER/numeric | Race distance in metres | `scheduled_card` |
| `field_size_full_card` | INTEGER/numeric | All preserved card rows in race | `scheduled_card_full_card` |
| `chul_no` | INTEGER/numeric | Declared entry number | `scheduled_card` |
| `age_raw` | INTEGER/numeric | Horse age | `pre_race_profile` |
| `rating_raw` | DOUBLE/numeric | Official pre-race rating | `scheduled_card` |
| `burden_weight_kg` | DOUBLE/numeric | Assigned burden weight | `scheduled_card` |
| `hist_prior_starts_all` | BIGINT/numeric | Prior confirmed entry rows | `strict_prior_date_confirmed_history` |
| `hist_prior_finished_all` | BIGINT/numeric | Prior confirmed rank-labelled finishes | `strict_prior_date_confirmed_history` |
| `hist_prior_wins_all` | BIGINT/numeric | Prior confirmed wins | `strict_prior_date_confirmed_history` |
| `hist_prior_top3_all` | BIGINT/numeric | Prior confirmed top-three finishes | `strict_prior_date_confirmed_history` |
| `hist_prior_starts_at_venue` | BIGINT/numeric | Prior confirmed entry rows at venue | `strict_prior_date_confirmed_history` |
| `hist_prior_finished_at_venue` | BIGINT/numeric | Prior confirmed finishes at venue | `strict_prior_date_confirmed_history` |
| `hist_prior_wins_at_venue` | BIGINT/numeric | Prior confirmed wins at venue | `strict_prior_date_confirmed_history` |
| `hist_prior_starts_other_venue` | BIGINT/numeric | Prior confirmed entry rows at other venues | `strict_prior_date_confirmed_history` |
| `hist_days_since_last_race` | BIGINT/numeric | Days since latest confirmed earlier race date | `strict_prior_date_confirmed_history` |
| `hist_venue_changed_since_last_start` | TINYINT/numeric | Current venue differs from prior unique venue | `strict_prior_date_confirmed_history` |
| `hist_first_start_at_venue` | TINYINT/numeric | No confirmed earlier row at venue | `strict_prior_date_confirmed_history` |
| `hist_away_from_first_observed_venue` | TINYINT/numeric | Current venue differs from first confirmed venue | `strict_prior_date_confirmed_history` |
| `smoothed_historic_win_rate` | DOUBLE/numeric | (prior wins + 1)/(prior finishes + 10) | `strict_prior_date_confirmed_history_fixed_prior` |
| `smoothed_historic_top3_rate` | DOUBLE/numeric | (prior top3 + 3)/(prior finishes + 10) | `strict_prior_date_confirmed_history_fixed_prior` |
| `prior_starts_venue_distance_class` | BIGINT/numeric | Prior confirmed rows at exact venue-distance-class | `strict_prior_date_confirmed_history` |
| `prior_wins_venue_distance_class` | BIGINT/numeric | Prior confirmed wins at exact venue-distance-class | `strict_prior_date_confirmed_history` |
| `smoothed_win_rate_venue_distance_class` | DOUBLE/numeric | (prior VDC wins + 1)/(prior VDC rows + 20) | `strict_prior_date_confirmed_history_fixed_prior` |
| `race_month_sin` | DOUBLE/numeric | Sine of scheduled month | `scheduled_date` |
| `race_month_cos` | DOUBLE/numeric | Cosine of scheduled month | `scheduled_date` |

## Labels, population, and split

- `source_target_finish_order`: untouched `model_training_entry.target_finish_order`. It is NULL for all 54 Yeongcheon rows because of an upstream normalization defect.
- `target_finish_order`: source target when present; for the 54 official finished Yeongcheon rows only, the audited numeric `model_target_entry.finish_raw` integer. `target_finish_order_raw_evidence` preserves that raw value.
- `target_win_mass`: `1 / race_winner_count` for every official first-place horse and explicit zero for every other card row, including rows without a finish rank. It is `NULL` only if an entire race truly has no normalized winner.
- `starter_eligible`: true only for `finished`, `disqualified`, and `did_not_finish`. All rows remain in the full-card table.
- `split`: `train` through 2022-12-31, `validation` for 2023-2024, and `test` from 2025 onward.

## Explicitly excluded feature families

- Every target/result field, current-race result status, time, and derived target.
- Odds, result details, current race weather/track, race-day body weight, and equipment.
- Training aggregates: every source event has `availability_unverified`; negative and over-24-hour durations also exist. They are fully audited but not treated as model input.
- Medical aggregates: API posting time is unverified and Text data are retrospective-only with incomplete identity linkage. Missing coverage is not encoded as zero evidence of no care.
- Original `prior_*` columns are metadata. Strict-date `hist_*` replacements are used by the allowlist.
- Unconfirmed races are excluded from all derived histories. This removes the 2026-08-26 `special_only_unresolved` cross-venue rows while retaining confirmed pre-2006 warm-up history. Any remaining confirmed horse/date with multiple venues receives a missing previous-venue category rather than an arbitrary venue.
