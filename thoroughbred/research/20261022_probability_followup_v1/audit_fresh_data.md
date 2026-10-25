# Fresh-data and prediction-time input audit

Read-only audit on 2026-10-22 for the Seoul/Busan Thoroughbred follow-up. No model was trained, no candidate performance was calculated, no source was collected, and no database was written.

The frozen research dataset still ends at completed races on 2026-09-20. Local post-cutoff results are available separately through 2026-10-18, but the newest candidate work is dated 2026-10-21, after those outcomes were locally accessible. The existing prediction archives give 16 pre-race forecasts for 169 runners; they are a subset of the 79-race refresh results, not 16 additional races. Those forecasts belong to the older registered model and do not contain the current 103-feature candidate contract. This supports a dated retrospective replay only after rebuilding and freezing the candidate inputs; it is not a clean blind holdout for the 2026-10-21 candidate.

## Local post-cutoff result sources

The frozen dataset at thoroughbred/data/dataset_20260929_v1/validation.json reports history from 2010-01-01, model-target data from 2017-01-01, and latest completed race 2026-09-20.

The separate refresh run thoroughbred/refresh/runs/20261017_full_20261016/run_report.json covers 2026-08-18 through 2026-10-16. It reports dry_run_passed, public_through 2026-10-24, 43,685 event rows, zero failed bundles, and active_database_written=false. The staged refresh copy is not the frozen dataset or an update to the active database. Filtering its normalized race_results rows to Seoul (meet 1) and Busan (meet 3) on/after 2026-09-21 gives 79 races and 856 result rows:

| Race date | Venue | Races | Result rows |
|---|---|---:|---:|
| 2026-10-02 | Busan | 9 | 95 |
| 2026-10-03 | Seoul | 10 | 109 |
| 2026-10-04 | Seoul | 11 | 120 |
| 2026-10-05 | Seoul | 10 | 109 |
| 2026-10-09 | Busan | 9 | 92 |
| 2026-10-10 | Seoul | 10 | 108 |
| 2026-10-11 | Seoul | 11 | 121 |
| 2026-10-16 | Busan | 9 | 102 |
| **Total** |  | **79** | **856** |

All 856 normalized result rows have capture times between 2026-10-16 16:34:55.707 UTC and 16:35:01.028 UTC, after their race dates. These files supply outcomes and retrospective event data, not prediction-time card or feature snapshots. The run report says the active database was not written.

Newer row-level Seoul result artifacts are present in data/research/score_point_updates_auto_20261022_091506_1792628106300346000:

| Race date | Races / result rows | Sections | Canonical issues | Local evidence |
|---|---:|---:|---:|---|
| 2026-10-17 Seoul | 10 / 109 | 791 | 7 | canonical.json; post-race receipt reports one uncovered source entry |
| 2026-10-18 Seoul | 11 / 120 | 897 | 1 | canonical.json; one scratched runner has no section |

Both canonical files report zero void races. These snapshots were captured on 2026-10-22 around 09:15 KST, after the races. The 10/17 issues include special finish-status records; keep them in an all-starter outcome view but do not infer normal-finisher status from an unresolved code. I found no Seoul/Busan race-day result partition for 2026-10-19 through 2026-10-21 in the checked refresh, score-point update, or post-race receipt paths. The latest saved Seoul result date is 10/18; the latest Busan result date is 10/16.

The read-only operational SQLite result table has linked results through 2026-10-02; its 10/03–10/05 rows are scheduled without result rows. This differs from the detached refresh and score-point research artifacts above. Its prediction_runs table contains only live runs dated 2026-08-28 and 2026-09-04, and prediction_settlements is empty. The 10/02 and 10/09 local forecast folders are file archives, not database publication records.

## Pre-race forecast archives

Two file archives have pre-race evidence and saved inputs. Both use thoroughbred-main-20260919-v1, not the newer experimental candidates.

| Date and scope | Forecast rows | Frozen input and time evidence | As-of history |
|---|---:|---|---|
| 2026-10-02 Busan races 3–9 | 7 races / 77 runners | Card hash 260e604eb1c4251c2716bf557f60aebe0d0f358e19caf974ff713ebff71fc3f6; feature file 147,109 bytes, 77 rows; metadata frozen 04:12:07 UTC and generated 04:14:14 UTC (13:12–13:14 KST). Busan race 3 was scheduled for 13:25 KST. | Race history through 2026-09-20; trial history through 2026-10-01; cutoff strictly before 10/02. Source-append hash 792a3ed102d03e57bed50f12f484a165723d07d7dd2ddfa67931a61b5bcfa81f. |
| 2026-10-09 Busan races 1–9 | 9 races / 92 runners | Card hash 1336492a65af0cd0241919bf7ffd698141256f75d734317e2d129535b3c262c9; prepared feature hash 6c52b551d6fc57e18440a43143330ae4164a53e893d7886daa021f1e4bffd103; full manual-freeze manifest hash 3d7f483e6674cebd90fbc18160efda178d72409b258536d641f42f2b8286423a. Features were saved 07:29 KST, inference ran 07:59–07:59:35 KST, and race 1 was scheduled for 11:15 KST. | History was cut off strictly before 10/09. The read-only preflight appended 488 result rows over 45 races through 10/02 and 77 trial rows through 10/01. It excludes target-day results and says results/odds were not used. |

For 10/02, the prepared-feature SHA-256 recorded here was computed during this audit; the original metadata records the card and source-append hashes but not a feature-file hash. The stored timestamps and hashes are useful local provenance but are not an external timestamp attestation. The 10/09 inference metadata records the prepared-feature hash and says database_writes=0 and network_writes=0. It also records unavailable current body weight and track moisture and a missing Busan S1F source under the registered feature contract.

Neither archive includes predictions from the newer 89/103-feature research candidates. The 10/02 and 10/09 event outcomes were present in local sources before the 2026-10-21 candidate work. The 10/17–10/18 result rows were also captured in a 10/19 update before the latest candidate date. Therefore these events can be described as post-training-cutoff temporal data only if their labels were excluded from candidate choice; the files do not prove that exclusion. Do not call them an independent blind test for the 10/21 candidate.

## Compatibility with the 103-feature candidate

The full103 contract is stored at thoroughbred/research/20261009_gate_front_late_v1/outputs/feature_contract.json. It specifies 103 model features. The two archived main-model input files contain 183 and 185 total columns, respectively, but direct name matching against the full103 contract finds only distance_m in each archive: 1 of 103 required feature columns. These archive frames are not a drop-in input for full103. This is a column-contract result, not proof that every value is unrecoverable: rebuilding requires the candidate’s historical style/section features, card-relative gate and role interactions, and time-ordered auxiliary front predictions. That derivation has not been attempted here.

The earlier population audit already preserves all-starter flags for the 50,754 evaluation rows through 2026-09-20 at thoroughbred/research/20261022_probability_comparison_v1/outputs/population_flags.parquet. The new canonical result artifacts provide more post-cutoff raw result and section detail, including special statuses, but the 10/17 unmatched source entry and special-status issues still need adjudication before claiming complete roster coverage or normal-finisher labels.

For a clean independent test of a new candidate, freeze its exact model, feature contract, card/roster, input hashes, and outputs before a future Seoul/Busan race. Current post-race result snapshots can extend historical data for future forecasts, but they cannot substitute for that future prediction-time capture. No forecast replay or candidate scoring was run in this audit.

## Key source hashes

- Refresh report: 2dc68cdabaed2f209d167736765b590bb38304615c35b70eecad91477a1e466e
- Refresh collection manifest: 83e9b26821be32fb9fc51fff00d561a0caceec36c78b69b30e054801e28db301
- 2026-10-02 prepared_features.parquet (audit-time hash): b81b114d4ddaeec0cfa15526cb19c83c97b674ac59a33252079d59aa4070bf52
- 2026-10-09 prepared_features.parquet: 6c52b551d6fc57e18440a43143330ae4164a53e893d7886daa021f1e4bffd103
- 2026-10-17 Seoul canonical.json: 2317b92076074b5e69d1f623f0496c0df9f69cfc4906b985f0ca6002490493c3
- 2026-10-18 Seoul canonical.json: 6ed81a76fceea3d9042076d6adf8043443a524e19eed14fc9807f40668e723b4
