# F1_STYLE6 direct Top5 selector: frozen source audit

Status: source audit is complete; model fitting and candidate-outcome evaluation have not run. The independent source audit is `../20261025_top5_direct_learning_rootreview_v1/ROOT_SOURCE_AUDIT.json` (SHA-256 `b263703aae9e7d5eca2bda394d4c20de67144bcaf78e959f5add9efffc8310f8`). This study keeps only paths and hashes; it does not copy source tables or models.

## Fixed inputs

| Purpose | Read-only source | SHA-256 | Use |
|---|---|---|---|
| F1_STYLE6 runner features and historic finish ranks | `20261010_style_history_ablation_v1/outputs/features.parquet` | `036939bd6d518a9e53d458a2f4eb2bf30bfecfa4bb80e21c78edd1f7f44f028f` | Fit-only runner inputs; train labels are read only for years earlier than the evaluation fold |
| Frozen 2024–2026 runner roster and raw score | `20261019_distance_section_relative_evaluation_v1/outputs/baseline_runner_predictions.parquet` | `c3fc8a2bf10d3fa1678ab3c5463209089021f51f6d0bf500fc2db6006fda13c1` | Candidate selection allowlist: keys, race metadata and `score`; outcome columns are reserved for the separately gated report |
| Existing date-cluster bootstrap | `20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy` | `d141b0c3f9a463cbfc9d1f4c61228b58757c31aee4ec74b79f41c5baeadaccbd` | Outcome report only; 2,000 × 269 frozen date draws |

Training raw scores are OOS calibration scores, with no calibrated probabilities:

| Label year | Score provider | Rows / races | `refit_max` | Score SHA-256 |
|---:|---|---:|---|---|
| 2019 | `20261011_pair_top3_oos_expansion_v1/outputs/F1_STYLE6_2020/calibration_scores.parquet` | 5,890 / 576 | 2018-12-29 | `277595cfe5d9976d24a8dc1c0c0e302a9fd58e467046e337a9af13d3c7287cdc` |
| 2020 | `20261011_pair_top3_oos_expansion_v1/outputs/F1_STYLE6_2021/calibration_scores.parquet` | 3,290 / 329 | 2019-12-28 | `ca2254c97e54a102954f706433864be8e5715d142ebf8237610311e4cbaa4c50` |
| 2021 | `20261011_pair_top3_oos_expansion_v1/outputs/F1_STYLE6_2022/calibration_scores.parquet` | 4,331 / 418 | 2020-12-20 | `3665e2039946362b97fe4fa72e50d2e13c8fb3b77f9f71225a9ae9d5c4b84ee9` |
| 2022 | `20261011_pair_top3_oos_expansion_v1/outputs/F1_STYLE6_2023/calibration_scores.parquet` | 5,261 / 512 | 2021-12-25 | `35c38b4acf6a5ca3236c41a85ba851577ab3053e92abb741a1e135f68942aa71` |
| 2023 | `20261010_style_history_ablation_v1/outputs/F1_STYLE6_2024/calibration_scores.parquet` | 6,506 / 657 | 2022-12-24 | `360cc559b1ab19cde177e0bb23206fd36f123b707714fbcb63547fdb9bed05b2` |
| 2024 | `20261010_style_history_ablation_v1/outputs/F1_STYLE6_2025/calibration_scores.parquet` | 6,329 / 637 | 2023-12-30 | `b092d28f0cbd45dd3a184a4a8ab89e9b5b5a78eef8068c45fda3de92734a3755` |
| 2025 | `20261010_style_history_ablation_v1/outputs/F1_STYLE6_2026/calibration_scores.parquet` | 6,410 / 654 | 2024-12-28 | `6a7ed320e59add698faafd9008c882dc8a83a84f9198094371525f4c4ebd37d8` |

The raw score files contain `api_record_id, score`; labels and F1_STYLE6 inputs are joined by the unique API record ID. Provider metadata is checked per year, and every provider must finish at least two days before each scored race. The score provider for label year `c` is fixed to fold `c+1`; temperature-fitted or in-year calibrated probabilities are not used.

## Population and source checks

- The frozen evaluation cohort has 17,412 runners, 1,779 complete races and 269 dates from 2024-01-05 through 2026-09-19. The primary 900/1000/1110/1200m cohort has 1,503 races. The entire period is repeated-use historical development data, not a new holdout.
- The feature file has 52,155 rows and 5,206 races from 2017-01-13 through 2026-09-19. The independent source-only audit confirmed unique runner keys, `history_cutoff = race_date − 2 days`, no `latest_history_date` after cutoff, no excluded horse `3005648`, exact OOS score-key coverage, and row-wise provider `refit_max ≤ race_date − 2 days`. That audit did **not** read `finish_position` or evaluation outcomes, so it did not verify training finish-rank labels.
- After root approves fitting, `fit_selector.py` will read only historical label rows before each evaluation year and fail closed unless every training race has a complete `1..N` finishing rank and exactly three Top3 labels. This is a separate label-validation stage in the fit receipt; no claim about its result is made before execution.
- Expanding training windows contain 2,492 / 3,129 / 3,783 races for evaluation years 2024 / 2025 / 2026. Historical field sizes range from 7 to 13; the largest candidate space has 1,287 five-runner sets per race. The whole fit-fold candidate counts are 769,121 / 925,207 / 1,076,359. Candidate matrices remain in memory only and are processed fold-wise; no full candidate table is persisted.
- The three style means are NULL exactly when their paired support count is zero; `support > 0` with a NULL mean and `support = 0` with a non-NULL mean both occurred zero times in the audited 52,155 rows. Their support counts therefore encode their missingness. `mean5_rank_fraction` receives a separate missing flag. The fixed 11-input basis has near-collinear inputs (`same_starts` vs `same_valid_times` correlation 0.999961; three style-support log counts approximately 0.9990–0.99966); L2 regularization is retained and individual coefficient signs/magnitudes will not be interpreted.
- The baseline score was exactly equal to the saved F1_STYLE6 evaluation raw score on all 17,412 evaluation runner keys. Selector code uses a strict column allowlist and does not read `y`, `p_top3`, `log_loss`, `brier`, finish ranks or result-status fields.

## Limits

The primary label is all three actual Top3 horses contained in a selected five-set. No odds, favorite, new source, database, model registry or operational model is an input. The source audit establishes lineage and cohort compatibility; it does not claim that the new head improves coverage. The selector's fitted Gibbs mass over correct five-sets is a stochastic training surrogate, not the deterministic selector's real-world coverage probability and not a calibrated probability.
