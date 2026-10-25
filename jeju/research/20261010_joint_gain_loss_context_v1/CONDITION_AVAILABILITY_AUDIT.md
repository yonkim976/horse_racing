# Gain/loss context cache and interpretation audit

작성: 2026-10-10. This is a read-only inventory of existing local caches plus one supplemental runner-context export. It did not query a database, collect external data, fit a model, or add outcome labels or prediction scores to the supplement.

## Exact-key supplemental data

[`runner_context.csv`](runner_context.csv) contains one row for each of the 17,412 runners in the fixed joint-relationship report cohort, keyed by `api_record_id`, with `race_id` retained as a second key. Its SHA-256 is `8dfbef38f04c52962efee8275cca48ae8f6fa14e59d7816ed50f0b4344642468`.

The target key source is `jeju/research/20261010_joint_relationship_v1/outputs/report/runner_marginals.csv` (SHA-256 `0e6a01607164a7cb54fbbb5fb445e975ea9fbadad21d4e7a842adfc915616a09`). It has 17,412 unique `api_record_id` values, 1,779 races, 269 race dates, and dates 2024-01-05 through 2026-09-19. Every target runner key maps exactly once to `jeju/research/20261008_weight_speed_v2/source_lineage.csv` (SHA-256 `95c44c1571f1ca383b57c5b9e98a8d9c1f32ebb1b9d19763db82ff51d3ed6346`): target coverage is 17,412/17,412, source-key duplicates are zero, and `race_id`, `race_date`, and `horse_number` mismatches are zero.

For race-level source cross-checks, the same IDs are all present in `jeju/research/20261007_track_environment_v1/race_support_rows.json` (SHA-256 `1a8b202da7024c9d42ac51d688dbbe473ad695bdc5c9011672d3a60b861720c5`) through its `source_api_record_ids` arrays. All 1,779 target race IDs agree with the cache's `(race_date, meet_code, race_number)` tuple. `moisture`, `band`, `track_raw`, `field_n`, distance, and raw grade agree with that race cache for every target runner. The frozen F1 race reference `jeju/research/20261010_style_history_ablation_v1/outputs/f1_reproduced_race_metrics.csv` (SHA-256 `89e783d9c2022cf7a91f7effc39a359ebcf755541c8d33073c0ce795e3341c07`) also agrees for date, distance, field size, and grade on all 1,779 target races. Source `month` agrees with the calendar month parsed from `race_date` on every runner.

## Included columns and limits

| Column(s) | Meaning and unit | Target coverage | Timing and interpretation |
|---|---|---:|---|
| `body_kg`, `body_weight_raw`, `reported_body_change_raw` | Same-event body weight in kg; original parenthesized weight string and its reported change text are retained verbatim. | 17,412/17,412; `body_kg` 209–347 kg | The source audit identifies body weight as a retrospective current-race measurement. The parenthetical report is not a prior-start delta. No previous body weight or body-change estimate was added. |
| `carried_weight_kg` | Same-event carried weight, kg. | 17,412/17,412; 51–65.5 kg | Result-side extraction and payload linkage are preserved. A declaration snapshot and its historical publication/revision time were not established by this source. |
| `moisture`, `band`, `track_raw` | Same-race moisture percent, source category, and raw track string. Observed moisture is 2–20%; all values are finite. | 17,412/17,412 | The source's fixed categories are 1–5% dry, 6–9% good, 10–14% wet, 15–19% saturated, and 20% or higher poor. Observed category-to-percent disagreements: 0. Within-race disagreement in moisture, band, or raw track string: 0. A race-result record does not prove when the value was measured or first published. |
| `horse_number` | Result-side runner number, integer 1–12. | 17,412/17,412 | This is a number, not a verified physical gate/stall assignment. It should not be relabeled as gate. |
| `jockey_id` | Official event jockey ID retained as a zero-padded six-character string; 29 IDs occur in this target cohort. | 17,412/17,412 | It comes from the event record. The cache does not establish the pre-race declaration version or change time. The supplement supports identity checks only; it does not invite ranking or selecting among the 29 jockeys. |
| `rank_class_raw`, `month`, `race_distance_m`, `field_n`, date/key fields | Raw race grade; event month; distance in metres; full realized field size; source identifiers and payload hashes. | 17,412/17,412 | Month is derived from `race_date`; date/month are calendar context. Grade and distance match the saved F1 race context. `field_n` is the realized starter field from post-race records, so it is not guaranteed to equal the pre-race declared field after scratches. |
| `history_cutoff`, `api4_3_payload_sha256`, `result_payload_sha256` | Source lineage and payload-version identifiers. | 17,412/17,412 | `history_cutoff` is a historical-feature cutoff, not proof of publication time for current-event conditions. |

All numeric body, carried-weight, moisture, distance, and field values were checked for finiteness and their source-supported ranges. Every target `horse_id` is checked against the excluded ID `3005648`; matches: zero. The supplement contains no labels or prediction scores.

The source row is an exact event-record join, not proof that each same-event value was available by T−2 or even before that race began. Body weight and current moisture are post-event explanatory context. Current burden, jockey, horse number, grade, and realized field size also lack a validated historical declaration/change-time record in this lineage. These fields must not be automatically added to a prospective model.

## Other existing caches

- `jeju/research/20261009_jockey_effects_v1/input01/starts.csv` (SHA-256 `78800c5c91219d58855ce046e39ead6a87729a49c8ba0d58ca9f78765921801a`) and `jeju/research/20261009_jockey_context_stability_v1/forecast01/features_with_form.csv` (SHA-256 `6ede7b62fca343f40d8a61ed9cb2c6e6af2c798e176f9cd7d7e22dd20ac25423`) also carry exact API keys and current-event jockey IDs. They are result-derived snapshots. The latter has historical 90/180/365-day jockey context fields, but it uses the event's observed jockey assignment; that does not establish the assignment's historical pre-race publication version.
- `jeju/research/20261008_weight_speed_v2/pair_lineage.csv` (SHA-256 `685038b521b028662933a2e4e1a47c4ad6f6b396cd5b82355fe287720bf9470d`) is an existing exact-current-key cache: its builder sets `pair_id = current api_record_id`. It contains previous/current body and carried weight plus `body_change_kg` and `burden_change` for 8,960/17,412 target current rows across 1,636/1,779 target races; matching current `race_id` and date had zero discrepancies. This is a selected pair cache only: same horse, exact distance, same year and raw grade, and a 7–60 day gap to the prior selected eligible observation. The prior observation need not be the horse's immediately preceding real-world start. These deltas were not recomputed or added to the all-runner supplement; rows without a pair remain unsupported.
- `data/research/jeju_native_h3_features_v1_20260916/` contains dated declaration-card candidates such as declared burden, horse number, age, grade, and jockey/trainer names. Its builder links with a separate text-dataset `entry_id`, not the target `api_record_id`, so this audit did not assert an exact direct join or coverage for the 1,779 races. The build contract accepts document dates at least two days before the event, but explicitly says actual historical publication and revision time is unproven. The frozen output has 1,094 source documents dated 2003-07-10 through 2026-09-07, 563 unresolved entry/key issues, and 9 cards rejected for late document date. It remains a possible pre-race source only after a separately verified event/key bridge and a cautious publication-time policy.
- The existing `horse_number` values do not validate physical gate mapping. The source variable catalog says the declared number is not a verified stall assignment; the result-side number in this supplement has the same interpretive limit.

The exact-key source lineage and the race-support JSON are sufficient for this supplement. The shared database was not opened. No data was sourced externally.

## Condition-selection and confounding audit

The 50 newly included correct Top3 sets and 34 previously included sets lost are outcome-defined discordant races. They are useful for explaining where the two saved selections differ, but their conditions cannot establish a treatment effect or a predictive rule. Any 84 groups created after inspecting this partition are post-outcome descriptive groups. Show the full chosen group inventory and its denominators; do not select the best-looking cell, tune a threshold, or describe pointwise intervals as confirmatory significance. No new p-values or multiple-testing claims are made here.

The fixed evaluation cohort has uneven year-by-distance support, and 2026 ends on September 19. Race counts are:

| Distance | 2024 | 2025 | 2026 partial |
|---:|---:|---:|---:|
| 800 m | 106 | 43 | 3 |
| 900 m | 48 | 106 | 97 |
| 1,000 m | 170 | 196 | 142 |
| 1,110 m | 178 | 178 | 126 |
| 1,200 m | 103 | 79 | 80 |
| 1,300 m | 8 | 35 | 20 |
| 1,400 m | 24 | 14 | 14 |
| 1,610 m | 0 | 3 | 6 |

So an overall gain/loss contrast can change with year-distance mix. A positive overall difference can coexist with neutral or negative within-distance/year contrasts (a Simpson-type reversal); the smallest cells cannot support stable explanations. Preserve all preselected context counts and `candidate - baseline` race-level differences. Use year-by-distance strata as a descriptive robustness view and standardize to the same fixed cohort mix only if the analysis plan already specifies that calculation. Do not infer a new environment or jockey effect from current-result fields.

## Next hypothesis priority

1. First check whether gain/loss concentration persists within the better-supported distance-year cells and across the already encoded style-history support (`n`); this distinguishes a stable relation adjustment from a result driven by cohort composition or sparse history. Keep it descriptive on this reused cohort.
2. If the signal concentrates in one context, preregister a single pooled, shrinkage-based relationship-by-context comparison for a later untouched period. Distance and grade are already present in the saved race context, so their interaction with the relation correction is a more relevant question than adding them again as raw variables.
3. Treat declared jockey history as a later pre-race candidate only after linking declaration records to exact target events and resolving publication/revision timing. Current body weight, current moisture, and result-side jockey or number remain explanatory annotations until then.

The joint relationship experiment's two primary performance gates already failed. These condition audits do not reverse that verdict or claim a new performance result.
