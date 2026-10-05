# Context feature audit

Status: **pass**

`prepared_context.parquet` preserves all 410,168 v2 rows and every v2 column, then appends 54 typed context features. All verified-core histories update only after every card snapshot on a date.

## Groups

| Group | Features | Availability |
|---|---:|---|
| `gate` | 8 | `verified_core_strict_prior_date` |
| `condition` | 16 | `verified_core_strict_prior_date` |
| `pace` | 8 | `verified_sections_seoul_and_yeongcheon_only_strict_prior_date` |
| `historical_event_unverified` | 10 | `retrospective_only_selection_ineligible_posting_time_unverified` |
| `late_info_unverified` | 12 | `retrospective_only_selection_ineligible_current_condition_availability_unverified` |

## Source decisions

- Gate effects use exact Plackett–Luce top-three inclusion expectations from pre-race v2 Elo; tie-compatible observed mass sums to the available top-three slots.
- Seoul and the first Yeongcheon meeting supply verified S1F positions. All Busan section rows are excluded because their semantics are unverified.
- Training and trial features are retrospective-only. Trial linkage admits explicit confirmed historical text and documented corroborated links, always with `trial_date < race_date`.
- Current body weight, weather, track state, and moisture stay in `late_info_unverified`; they are selection-ineligible and are not live-readiness evidence.
- Body-weight values describe historical/current deviation from an observed prior median. They do not identify a causal or optimal weight.
- No verified sand-maintenance or steward/trouble effect field exists in the unified source, so neither is featured.

## Verification

- v2/context rows: 410,168 / 410,168
- duplicate keys: 0
- mismatches across every inherited v2 column: 0
- non-string official ID rows: 0
- range/count invariant violations: 0
- Per-feature missingness, coverage, minimum, and maximum are in `feature_coverage.csv`.

## Excluded or limited sources

- Busan section rows excluded: 2,565,960
- Audited trial rows admitted only to retrospective features: 76,215
- Current-race results, odds, sections, and any same-date outcome are never inputs.
