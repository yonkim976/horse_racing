# Frozen input source and cohort audit

Built 2026-10-22 under supervisor/DESIGN_CONTRACT.md. The builder is inputs/prepare.py; output locks and per-file hashes are in inputs/input_manifest.json. Source files are referenced in place and were not copied. No database was opened, and no model fitting, prediction, calibration, or performance evaluation was run.

## Frozen inputs and cohort lineage

The 10/08 frozen raw snapshot is 92,513 rows / 9,494 races, SHA-256 c2307afe79c4ca3a1c4a1ab46159be93450ca03450f8fd51063dd2318ed49403. Its inclusion ledger is 5,901 races / 423,625 bytes, SHA-256 959274837a1eafe627851b505e271402b5c969f2aa31d7195824dc0112f28eb5. The 10/08 derived features.parquet was used only for ID, key and cohort verification; no derived feature was read into the new inputs. The current horse exclusion file was checked by hash (5a88a0f19880a5b19ed7bfdec5a2465cb6652cff4b91c5cbe255fff377bcf84a, 349 bytes).

The frozen ledger has 5,901 candidate races from 2017 onward (59,042 rows). It marks 5,206 races / 52,155 runners as normal, complete unique-rank races. All included rows were independently checked for supported distance, positive finite time, integer ranks exactly 1..N, unique horses and positive unique integer program numbers, and a constant race class. Their raw keys match the 10/08 feature metadata exactly. The remaining 695 candidates are excluded as recorded in the frozen ledger. Its reason counts overlap: 510 have a non-normal/nonpositive-time reason, 135 an unsupported-distance reason, and 569 a non-complete-rank reason. The frozen partial_vs_stored_result test depended on the original full-result reference; this run did not reopen the DB to repeat it. The 3,593 pre-2017 races are inferred by subtracting the 5,901 ledger races from 9,494 total races, not counted from a separate date query.

The 10/21 frozen observations.parquet contains 56,618 rows / 5,693 races (SHA-256 bcf056ea788f2637c17a6b404013a7718fa3ed6f2042f6693cf6f167dfaf83c7). Its runner IDs and identity columns match the started roster in the 10/08 snapshot. It supplies valid S1F and G1F group observations for historical features; the 4,463 rows outside the strict target cohort can contribute history only. Group labels require api_group_unreviewed, a parseable notation, unique program numbers and exact roster equality. Recovery additionally requires an integer usable G1F official order and normal integer finish rank. The label-only columns y_s1f, y_last200_recovery, and y_count in the 10/21 reference matrix were used only to independently check reconstruction across all 56,618 observations; engineered features were not read.

## Contracted output and temporal checks

model_inputs.parquet has 52,155 strict-cohort runner rows and 27 ordered A features; its runner-phase allowlist has 35 columns. race_inputs.parquet has one row per 5,206 strict races and 8 ordered Z features. Both include strict_cohort and nullable label-only target columns. history_lineage.parquet holds 208,620 channel-level diagnostic rows outside either model feature list. Hashes and byte counts are in the manifest.

The four history channels are rank-normal-score and within-race log median-time margin from normal complete historical races, plus quality-usable S1F first-pack membership and G1F-to-finish improvement of at least two positions. Per target runner, features use only same-horse events from 2017-01-01 through T−2 inclusive, within 730 calendar days, weighted by 2**(-age_days/365). Exact-distance deviation shrinks toward the all-distance mean; variance is population weighted variance around the unshrunk weighted mean and is NULL with fewer than two observations. No-history numeric support is zero, while the mean/deviation/variance/age remain NULL. Publication timestamps are unavailable, so T−2 is an event-date boundary, not proof the source was public before a wager. The final recorded roster is retrospective.

Reconstructed labels match the frozen label-only reference on all 56,618 observation rows. On strict targets, early is known for 52,095 runners, recovery for 52,116 runners, and Z for 5,200 races; the remaining labels stay unknown. Phase-fold target and calibration rows are limited to the same 5,206-race cohort. Every 2019–2026 annual fold meets the fixed minimum of 50 positive and 50 negative training labels and 10 of each in calibration for all three heads; full counts are in phase_fold_support.json.

The evaluation key set is 1,779 races / 17,412 runners / 269 dates, split 637 / 654 / 488 by 2024 / 2025 / 2026. The separate PLC outcome pool remains 1,743 races with 36 unknown opening-field-size races quarantined. Exact runner/race key hashes and their encoding are recorded in the input manifest.

## Source references

- 10/08 inclusion logic and frozen race ledger: jeju/research/20261008_horse_profile_baseline_v1/run.py:72-102, outputs_v2/race_inclusion_ledger.csv.
- 10/21 source roster and group/label quality logic: jeju/research/20261021_phase_pace_prediction_v1/build.py:11-110.
- Sole feature, temporal, cohort and fold contract: supervisor/DESIGN_CONTRACT.md.
- Frozen source hashes, input hashes, ordered features, label availability, evaluation keys and run status: inputs/input_manifest.json.
