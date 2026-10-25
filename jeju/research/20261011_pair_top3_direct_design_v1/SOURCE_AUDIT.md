# Read-only source audit

Audit date: 2026-10-11. Inspection was limited to saved artifacts in the repository. No database, network, model fit, or outcome metric was used. The execution-authoritative plan and input contract are in `jeju/research/20261011_pair_top3_direct_v1/`; this source audit is an independent review record.

## Available pair-learning inputs

`20261010_style_history_ablation_v1/outputs/features.parquet` has 52,155 runner rows and provides `api_record_id`, race ID/date, horse number, field size, finish label, and the six frozen style-history fields. Its SHA-256 is `036939bd6d518a9e53d458a2f4eb2bf30bfecfa4bb80e21c78edd1f7f44f028f`. The six fields are three mean positions and their observation counts; their definitions, source-status rules, and T−2 history cutoff are in the frozen style-history contract and prepared lock.

Each `F1_STYLE6_Y` fold contains a two-column raw-score artifact keyed by `api_record_id` for its calibration year and evaluation year. The score writer sets `raw_score=True`; the saved yearly `tau` is fit on the full calibration year and is excluded from H1. The direct model must use the fold-specific score path shown below. A race/date can appear in another fold's different score artifact, so `api_record_id` alone is not a sufficient identity across fold paths.

| Evaluation fold | Pair-fit/calibration score source (Y−1) | H1 after T−2 purge | H2 calibration | Evaluation score source (Y) |
|---|---|---:|---:|---|
| 2024 | `F1_STYLE6_2024/calibration_scores.parquet` | 3,089 rows; 312 races; 47 dates, 2023-01-06–2023-06-24 | 3,327 rows; 336 races; 50 dates, 2023-07-01–2023-12-30 | `F1_STYLE6_2024/evaluation_scores.parquet`: 6,329 rows; 637 races; 98 dates |
| 2025 | `F1_STYLE6_2025/calibration_scores.parquet` | 3,244 rows; 326 races; 50 dates, 2024-01-05–2024-06-29 | 3,085 rows; 311 races; 48 dates, 2024-07-05–2024-12-28 | `F1_STYLE6_2025/evaluation_scores.parquet`: 6,410 rows; 654 races; 98 dates |
| 2026 | `F1_STYLE6_2026/calibration_scores.parquet` | 3,238 rows; 329 races; 50 dates, 2025-01-03–2025-06-28 | 3,172 rows; 325 races; 48 dates, 2025-07-04–2025-12-27 | `F1_STYLE6_2026/evaluation_scores.parquet`: 4,673 rows; 488 races; 73 dates, through 2026-09-19 |

The calibration-year score files contain 6,506, 6,329, and 6,410 rows for folds 2024, 2025, and 2026. The evaluation cohort totals 1,779 races, 17,412 runners, and 269 dates; 2026 is partial. The source joins checked in this audit had unique `api_record_id` keys on both sides and one-to-one matches with no missing feature rows. The feature table schema contains the needed pair fields and labels; each score table schema is exactly `api_record_id, score`.

For each fold, the H1/H2 boundary is January–June versus July–December of Y−1. The retained H1 races end no later than two calendar days before the first H2 race. H2 ends at least two days before the first evaluation race in all three saved folds. The saved F1 refit maxima—2022-12-24, 2023-12-30, and 2024-12-28—are at least two days before their fold's first H1 race. These date checks establish the source-score timing path; they do not reconstruct historical public release times.

## Pair-probability reference sources

`20261010_joint_relationship_v1/outputs/report/all_triples.parquet` stores both `matched_baseline` and `candidate` probabilities over unordered exact Top3 sets for the same 1,779-race evaluation cohort (402,808 rows total). Its manifest hash and content hash are pinned in `source_manifest.json`. Summing a saved arm's triple probabilities over triples containing a pair yields that arm's pair-in-Top3 probability. `runner_marginals.csv` contains saved Top3 runner marginals and labels and can independently check the candidate's two highest Top3-marginal runners. The two saved joint arms and this derived top-two-marginal pair are fixed exploratory references.

The `tau=1` additive baseline's maximum pair is mathematically the same pair as the two highest raw scores for the supported field sizes (`N>=4`): pair mass is proportional to `w_i w_j` times the remaining weight sum, where `w_i=exp(s_i)`. The outcome-free preflight will confirm this parity with canonical `math.fsum` accumulation; it is a structural identity check, not a separate policy result.

The prior joint study reports that its candidate missed both pre-registered performance gates. Its outputs are still usable as frozen same-cohort comparisons, but they do not provide independent confirmation. Its unordered set distribution gives no exact-Top2 or finish-order probability. This direct-pair study excludes exact-Top2 outcomes and all triple/ticket objectives.

## Source and population limits

The frozen target is the complete-roster, normal-finish cohort used by `F1_STYLE6`; a source race should have exactly three Top3 labels. The original feature table includes post-race finish labels for retrospective training and evaluation only. Horse IDs, race IDs, pair IDs, and finish labels are join/target fields, never predictors. The pair model inherits the prepared style-history source and T−2 contract; it does not query raw database tables or reconstruct feature history.

The repeated 2024–2026 dates are development material already reviewed in prior work. A row from a calendar year may serve as a later fold's calibration source using a different F1 score model path even when that same date was an earlier fold's evaluation date. Keep every fold and score artifact path distinct; do not concatenate or join fold scores on `api_record_id` alone. The combined result is not an independent test.
