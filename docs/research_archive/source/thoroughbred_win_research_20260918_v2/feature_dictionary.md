# V2 research feature dictionary

`prepared_v2.parquet` preserves every v1 row, key, label, and all 38 executable
v1 features.  The 34 columns below are additions.  Every history value is a
snapshot from confirmed races dated strictly before the target card date.  A
missing speed or rating value remains null; it is never encoded as fake zero.

## Form

| Feature | Meaning | Null / zero contract |
|---|---|---|
| `research_form_finish_pct_last` | Latest valid finish percentile, 1 best and 0 last | Null without a prior valid finish |
| `research_form_finish_pct_avg3` | Mean of latest three valid finish percentiles | Null without a prior valid finish |
| `research_form_finish_pct_avg5` | Mean of latest five valid finish percentiles | Null without a prior valid finish |
| `research_form_wins3` | Wins among latest three valid finishes | Zero without history |
| `research_form_wins5` | Wins among latest five valid finishes | Zero without history |
| `research_form_top3_3` | Top-three results among latest three valid finishes | Zero without history |
| `research_form_top3_5` | Top-three results among latest five valid finishes | Zero without history |
| `research_form_prior_valid_finishes` | Count of all prior valid ranked finishes | Zero for a debutant |
| `research_form_last_burden_delta_kg` | Current assigned weight minus previous start's assigned weight | Null without both weights |
| `research_form_last_distance_delta_m` | Current distance minus previous start distance | Null without a prior start |
| `research_form_dnf_count5` | DNF count among latest five confirmed starts | Zero without prior starts |
| `research_form_dnf_rate5` | DNF share among latest five confirmed starts | Null without prior starts |

Valid finish means a positive official rank and excludes cancelled, scratched,
DNF, disqualified, and excluded rows.  DNF history is deliberately separate.

## Ability

| Feature | Meaning | Null / zero contract |
|---|---|---|
| `research_elo_global` | Pre-card multiplayer Elo over all valid prior finishes | 1500 prior |
| `research_elo_global_starts` | Prior races that updated global Elo | Zero for unseen horse |
| `research_elo_context` | Pre-card Elo for exact venue and exact distance | 1500 prior |
| `research_elo_context_starts` | Prior updates in exact venue-distance context | Zero for unseen context |
| `research_elo_uncertainty` | `1/sqrt(global starts + 1)` | One for unseen horse |
| `research_speed_last` | Latest valid adjusted speed figure | Null without valid speed history |
| `research_speed_avg3` | Mean latest three valid speed figures | Null without valid speed history |
| `research_speed_median5` | Median latest five valid speed figures | Null without valid speed history |
| `research_speed_best5` | Best latest-five speed figure | Null without valid speed history |
| `research_speed_trend` | Latest two mean minus earlier up-to-three mean | Null until four figures |
| `research_speed_count5` | Valid figures in latest-five window | Zero without valid history |
| `research_speed_censored_rate5` | Share of latest-five figures lower-censored for eased tail finishes | Null without valid history |
| `research_speed_exact_distance_avg5` | Mean latest five valid figures at current exact distance | Null without exact-distance history |
| `research_speed_exact_distance_count5` | Valid exact-distance figures, capped at five | Zero without exact-distance history |
| `research_speed_has_valid_history` | Availability flag for any valid speed figure | Zero or one |

Elo uses prior 1500, K=32 globally, K=28 for exact venue-distance context,
and a 730-day half-life toward 1500.  Every race on a date is scored from the
same opening state and states update after all races on that date.  Pairwise
scores use only valid ranked finishers.

Speed is `100*log(actual speed / adjusted par)`.  The par uses the preceding
730 days at course and exact distance, preferring matching going with 12 races
and otherwise requiring 20 course-distance races.  A venue-day variant may use
all completed races on that historical day, but the resulting observation is
available only on later dates.  Invalid source times are quarantined in
`invalid_speed_source_audit.csv`.

## Current-field relative values

| Feature | Meaning | Null / zero contract |
|---|---|---|
| `research_elo_vs_field` | Horse global Elo minus opponent mean | Zero for sole runner |
| `research_context_elo_vs_field` | Horse context Elo minus opponent mean | Zero for sole runner |
| `research_rating_vs_field` | Current official rating minus available opponent mean | Null if self or all opponent ratings missing |
| `research_speed_vs_field` | Latest speed figure minus available opponent mean | Null if self or all opponent speeds missing |
| `research_field_competitor_count` | Other rows on current full card | Zero for sole runner |
| `research_field_rating_available_count` | Opponents with current official rating | Zero when none |
| `research_field_speed_available_count` | Opponents with a valid prior speed figure | Zero when none |

The executable group lists are frozen in `new_feature_groups.json`.  The two
explicit simple ability baselines are `research_elo_global` and
`research_speed_avg3`.

## Live-card API

`code/features_v2.py` exports:

```python
derive_features(history_df, cards_df) -> list[dict]
```

Required card fields are `race_id`, `race_date`, `hr_no`, `venue_code`, and
`distance_m`; full output also uses `chul_no`, `burden_weight_kg`, and
`rating_raw`.  Required history fields are the same identity and race context
plus `finish_order`, `result_status`, `is_rank_label`, and `race_time_s`.
Official IDs remain strings.
