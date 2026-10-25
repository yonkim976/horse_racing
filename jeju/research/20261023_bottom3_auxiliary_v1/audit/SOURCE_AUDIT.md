# Bottom3 source audit

2026-10-23 · **PASS: source/cohort audit only.** This review verified frozen source hashes, schema, joins, role/year partitions, label support, and the existing date bootstrap. It did not fit Bottom3, rank or select S scores, produce probabilities, or calculate new performance metrics. No DB access or source copies were used.

The frozen design contract is `supervisor/DESIGN_CONTRACT.md` (SHA-256 `ff6e3af2d454cd30edb56df1251700320b01de3478939c98199e0886bf22f084`). Full source paths, byte sizes, and hashes for 26 references are in `SOURCE_AUDIT.json`; the reusable audit is `source_audit.py`.

## Inputs and time roles

The input candidate contract has **40 ordered columns**: the 30 F1_STYLE6 fields plus the 10 sealed S rank/distance-state fields. F1 and S state rows join one-to-one on `api_record_id` (52,155 keys); race ID, race date, and inclusive T−2 cutoff agree. Existing sealed state and lineage checks pass; all state history dates are at or before cutoff. The state table was referenced, not rebuilt.

F1_STYLE6 is frozen and its source audit reports 6,269 full-roster races / 62,248 started rows with zero roster ID or count mismatches. Its target cohort contains 5,206 races / 52,155 runner rows. S provider scores are raw `score` values from `candidate_oos_scores.parquet`, filtered to `arm == "S"`, `role in {calibration, evaluation}`, and provider years 2024–2026. Each role has finite scores and exactly matches F1 API IDs, race IDs, dates, horse numbers, and field sizes. Calibration is provider Y−1; evaluation is calendar Y. These are existing S Top3-provider scores, not Bottom3 probabilities. Under the frozen contract the L comparator uses `u_L = -score`; no score ordering was computed in this audit.

| Provider | Role | Calendar year | Races | Runners | Bottom3 labels supported |
|---:|---|---:|---:|---:|---:|
| 2024 | calibration | 2023 | 657 | 6,506 | 1,971 |
| 2024 | evaluation | 2024 | 637 | 6,329 | 1,911 |
| 2025 | calibration | 2024 | 637 | 6,329 | 1,911 |
| 2025 | evaluation | 2025 | 654 | 6,410 | 1,962 |
| 2026 | calibration | 2025 | 654 | 6,410 | 1,962 |
| 2026 | evaluation | 2026 through Sep 19 | 488 | 4,673 | 1,464 |

The contracted training phases use the common F1 cohort only. For provider Y, initial training is 2017..Y−3, early stop is Y−2, refit is 2017..Y−2, calibration is Y−1, and evaluation is Y. Per-year race, runner, and label counts for every phase are preserved in the JSON census.

## Cohort and limitations

The frozen label is `1[finish_position >= field_n - 2]`: exactly three Bottom3 labels per complete race. The full cohort supports 15,618 labels over 5,206 races. The reused 2024-01-05..2026-09-19 evaluation set has **1,779 races, 17,412 runners, 269 race days, and 5,337 supported labels** (2024: 637/6,329/1,911; 2025: 654/6,410/1,962; partial 2026: 488/4,673/1,464; each triplet is races/runners/labels).

These labels describe the last three finishers among horses in a retrospective normal-finish, complete-field cohort. They are not “non-place” labels for 4th and lower as a broad group, and they do not assign outcomes to DNF, disqualified, tied, cancelled, or otherwise ambiguous runners. The 2024–2026 window has been reused by prior studies and is not a fresh holdout. Source event-date features honor T−2 inclusive, but publication timestamps and the actual pre-race roster are unverified. These checks establish data compatibility and label support, not Bottom3 model quality or deployability.

The existing paired-date bootstrap schedule is referenced in place (2,000 × 269); its frozen date inventory matches the evaluation cohort. No new schedule or data asset was created.
