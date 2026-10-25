# Conditional order head input contract

Status: frozen candidate contract for source preflight; root review pending. The preflight reads only these fixed files, verifies their hashes before parsing, and writes only inside this new study directory. No database, network, registry, current operating model file, or refreshed database is accessed.

## Pinned sources

| Role | Path | SHA-256 |
|---|---|---|
| Frozen F1_STYLE6 feature rows, keys, labels, and six existing style fields | `jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet` | `036939bd6d518a9e53d458a2f4eb2bf30bfecfa4bb80e21c78edd1f7f44f028f` |
| Frozen STYLE6 history lineage | `jeju/research/20261010_style_history_ablation_v1/outputs/style_history_lineage.parquet` | `679501dc29cecdf82cf24946cfff3ba43728bfdfdcf69647425f823b40be86e8` |
| Frozen STYLE6 saved runner probabilities for q-to-marginal check | `jeju/research/20261010_style_history_ablation_v1/outputs/report/runner_predictions.parquet` | `706bca01e5f5e780a8ffbe9e2ad4553fea9e3d76df097b4c9648d7aabac44e56` |
| STYLE6 feature and time contract | `jeju/research/20261010_style_history_ablation_v1/CONTRACT.md` | `c10aac8f6faa6e841afd9ef829bfa0b29ada2dceabcbb5405fdfad9c12536bf9` |
| STYLE6 source/artifact manifest | `jeju/research/20261010_style_history_ablation_v1/ARTIFACT_MANIFEST.json` | `6afc0e8f73ec086052fad4cde4d7edcd62fdf1bbc782108da89732dc3a5b4a4e` |
| F1_STYLE6_2024 prior-year OOS calibration scores | `jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_2024/calibration_scores.parquet` | `360cc559b1ab19cde177e0bb23206fd36f123b707714fbcb63547fdb9bed05b2` |
| F1_STYLE6_2025 prior-year OOS calibration scores | `jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_2025/calibration_scores.parquet` | `b092d28f0cbd45dd3a184a4a8ab89e9b5b5a78eef8068c45fda3de92734a3755` |
| F1_STYLE6_2026 prior-year OOS calibration scores | `jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_2026/calibration_scores.parquet` | `6a7ed320e59add698faafd9008c882dc8a83a84f9198094371525f4c4ebd37d8` |
| F1_STYLE6_2024 evaluation scores and meta | `jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_2024/evaluation_scores.parquet` | `b9541396c81e307f99f6c8eff4441594b181b9a0398120a4fa5f529add55cd60` |
| F1_STYLE6_2025 evaluation scores and meta | `jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_2025/evaluation_scores.parquet` | `45247f00f286197067957d25ee46e0594f2ef0d26089c6b6081592272651eb12` |
| F1_STYLE6_2026 evaluation scores and meta | `jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_2026/evaluation_scores.parquet` | `0ccae2475fc1ea87ddf62b054572961ab32fed26b332070907853ebbd412989a` |
| F1_STYLE6_2024 fold meta | `jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_2024/meta.json` | `15acbf959654da82d2240027e7b7d768bb9226af18395dac9ec92a68a4471726` |
| F1_STYLE6_2025 fold meta | `jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_2025/meta.json` | `23c4b0684477f34fbb2e99c22d0037cd903d5459db369f084773ec25c640f4a8` |
| F1_STYLE6_2026 fold meta | `jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_2026/meta.json` | `e9dbfe5226571cb29e34b352a4ad8808a735d70929e66b42efb41b3e807ff06d` |
| Existing native unordered Top3 set probabilities for q parity | `jeju/research/20261015_research_other_pool_support_v1/tla_set_probabilities.parquet` | `7c7bafcb315a9f9595e06aa1ee12ca0affbcf3abcc13426e90e079261d29b382` |
| Native TLA derivation report | `jeju/research/20261015_research_other_pool_support_v1/REPORT.json` | `e2f3e99d2af8d247fa6448708c39f95d4786d1e5e9321411d7d02fec77df99a4` |
| Native TLA source manifest | `jeju/research/20261015_research_other_pool_support_v1/SOURCE_MANIFEST.json` | `bab791f8bc5f73b0c3b155b3befaa4ecd443d8deff4f9cd5d67f64cc2ae33096` |
| Fixed 467-race operating/research cohort | `jeju/research/20261015_operating_postrace_value_comparison_v1/cohort.csv` | `4f87d05e0f7e2db48f1029dbf1fc78c393ba3804eb20ccb8d28cf6e20e73983f` |
| Fixed paired date bootstrap schedule, 2,000 × 269 | `jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy` | `d141b0c3f9a463cbfc9d1f4c61228b58757c31aee4ec74b79f41c5baeadaccbd` |
| Fixed bootstrap schedule receipt | `jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.json` | `6bdcf550065a2e6bb5038fc8d02eb070f026ba0efe5d3ebf1c3530a4e53c397e` |
| Independent root feature/key/time source proof | `jeju/research/20261017_order_head_rootreview_v1/ROOT_SOURCE_PREFLIGHT.json` | `a8a605ab2130702ea5b37a02c9b1a6bf0fc6e52ef4f61cb924ac4b2b07e3bf0d` |

The three score sources have exactly `api_record_id:int64, score:double`; each score file is joined only to features of its own fold year. Repeated IDs across adjacent fold files remain fold-qualified and are never deduplicated or merged across models. Saved `tau_Y` is read only to reproduce the original unordered q for evaluation-year Y; it is not an H1 feature, order utility offset, or fit/calibration input.

## Join, cohort, and no-leakage checks

Use `api_record_id` for score-to-feature joins; use `(race_id, horse_number)` as runner key and `race_id` as race key. Verify unique keys, exact score-to-year-feature key coverage, finite scores, complete `field_n` rosters, and exactly one each of official finish positions 1, 2, and 3. Labels are audited as source structure only during preflight. Check each style `mean5`/count missingness pair, count range 0..5, finite observed means, feature `history_cutoff=race_date−2 days`, and `latest_history_date≤history_cutoff` when present. Join lineage targets back to frozen feature keys and verify target date/cutoff/horse/distance identity, per-target slot uniqueness, and every source race date at or before its target T−2 cutoff. Do not read a database to refresh or compare these files.

Expected evaluation counts by year are 2024: 6,329 runners/637 races/2024-01-05 through 2024-12-28; 2025: 6,410/654/2025-01-03 through 2025-12-27; 2026: 4,673/488/2026-01-02 through 2026-09-19. Total is 17,412 runners/1,779 races/269 dates. The 2026 fold is partial.

For each fold, check H1/H2 race counts after T−2 purge against 312/336, 326/311, and 329/325. Check every date boundary listed in `PLAN.md`. The preflight reports per-feature missing and valid support by H1/H2/evaluation split; it does not compute outcomes, probability metrics, model parameters, or control predictions.

## Native q and fixed uncertainty schedule

On the 467-race common 2026 cohort, reconstruct the saved F1_STYLE6 q from evaluation scores and saved `tau_2026`, with the original sorted-score triple energy and native stable energy ordering. Compare every exact set key, set probability, and native energy rank to the pinned TLA artifact within absolute tolerance `1e−12`; also compare reconstructed runner Top3 marginals to the pinned saved F1 runner predictions. These are source/coherence checks only and do not evaluate the order head.

Use the already frozen 2,000 × 269 date-resampling schedule for every paired confidence interval. Do not create a new schedule after evaluation outcomes are inspected. The common operating comparison uses only the exact 467 race IDs from the pinned cohort file; odds analysis follows the prior fixed source contract and remains secondary.

## Restricted actions

The preflight may read only the pinned files and may write only new files under `jeju/research/20261017_conditional_order_head_v1/`. It must not access database files or APIs, network sources, current registry/model artifacts, unpinned old-study files, or Thoroughbred sources. Before separate root fit approval, do not fit beta or temperature, derive actual conditional-order control predictions, calculate outcome metrics or pool probabilities, inspect odds for selection, or produce any evaluation performance result.
