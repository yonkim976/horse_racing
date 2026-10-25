# Direct pair learner input contract

Status: hash-pinned review inputs, 2026-10-11. This is not the execution contract. The authoritative input contract is `jeju/research/20261011_pair_top3_direct_v1/INPUT_CONTRACT.md`. Verify those authoritative pinned sources before any preflight or fit. A mismatch fails closed; do not substitute another file or read the database.

## Immutable sources

| Role | Path | SHA-256 |
|---|---|---|
| Frozen runner features, pair labels, roster/date keys | `jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet` | `036939bd6d518a9e53d458a2f4eb2bf30bfecfa4bb80e21c78edd1f7f44f028f` |
| Style-history source study manifest | `jeju/research/20261010_style_history_ablation_v1/ARTIFACT_MANIFEST.json` | `6afc0e8f73ec086052fad4cde4d7edcd62fdf1bbc782108da89732dc3a5b4a4e` |
| Frozen feature/time contract | `jeju/research/20261010_style_history_ablation_v1/CONTRACT.md` | `c10aac8f6faa6e841afd9ef829bfa0b29ada2dceabcbb5405fdfad9c12536bf9` |
| Raw calibration scores, fold 2024 | `jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_2024/calibration_scores.parquet` | `360cc559b1ab19cde177e0bb23206fd36f123b707714fbcb63547fdb9bed05b2` |
| Raw evaluation scores, fold 2024 | `jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_2024/evaluation_scores.parquet` | `b9541396c81e307f99f6c8eff4441594b181b9a0398120a4fa5f529add55cd60` |
| Fold metadata, 2024 | `jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_2024/meta.json` | `15acbf959654da82d2240027e7b7d768bb9226af18395dac9ec92a68a4471726` |
| Raw calibration scores, fold 2025 | `jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_2025/calibration_scores.parquet` | `b092d28f0cbd45dd3a184a4a8ab89e9b5b5a78eef8068c45fda3de92734a3755` |
| Raw evaluation scores, fold 2025 | `jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_2025/evaluation_scores.parquet` | `45247f00f286197067957d25ee46e0594f2ef0d26089c6b6081592272651eb12` |
| Fold metadata, 2025 | `jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_2025/meta.json` | `23c4b0684477f34fbb2e99c22d0037cd903d5459db369f084773ec25c640f4a8` |
| Raw calibration scores, fold 2026 | `jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_2026/calibration_scores.parquet` | `6a7ed320e59add698faafd9008c882dc8a83a84f9198094371525f4c4ebd37d8` |
| Raw evaluation scores, fold 2026 | `jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_2026/evaluation_scores.parquet` | `0ccae2475fc1ea87ddf62b054572961ab32fed26b332070907853ebbd412989a` |
| Fold metadata, 2026 | `jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_2026/meta.json` | `e9dbfe5226571cb29e34b352a4ad8808a735d70929e66b42efb41b3e807ff06d` |
| Saved joint probabilities for fixed comparisons | `jeju/research/20261010_joint_relationship_v1/outputs/report/all_triples.parquet` | `13409e65353c0cb6dab14df97317cce24de913056ae464ee3524520759de681c` |
| Saved Top3 runner marginals for fixed comparison/check | `jeju/research/20261010_joint_relationship_v1/outputs/report/runner_marginals.csv` | `0e6a01607164a7cb54fbbb5fb445e975ea9fbadad21d4e7a842adfc915616a09` |
| Joint study manifest and history | `jeju/research/20261010_joint_relationship_v1/ARTIFACT_MANIFEST.json` | `d0d1a749afb6a6f894de1bb4263c9d67dd1e3b2d1a35bf1b5fd38d8948c656b0` |
| Joint study frozen plan | `jeju/research/20261010_joint_relationship_v1/PLAN.md` | `e0a34c6962112d88bfec7e645efbd8e4ea69bf4aada088f580e1188bac1207f3` |
| Joint report receipt | `jeju/research/20261010_joint_relationship_v1/outputs/report/report_receipt.json` | `5720519b0d8860f5652650b4d2ee3b6f8444a6c6f01421395cd51f4a0251fae4` |
| Prior joint results/limits | `jeju/research/20261010_joint_relationship_v1/RESULTS_AND_LIMITATIONS.md` | `2ce5677434390542d6adf7eba3114328c6d5068e5a8620fc543f80d364f821e7` |

The score files have schema `api_record_id:int64, score:float64`. `features.parquet` supplies the runner keys and the seven model inputs; the joint probability artifact supplies fixed comparison outputs. Exact source roles and row/date counts are documented in [SOURCE_AUDIT.md](SOURCE_AUDIT.md).

## Join and fail-closed checks

- Join each score artifact to features by unique `api_record_id`; preserve `(evaluation_year, score_artifact_path, api_record_id)` as the fold-qualified source key. Validate `race_id`, `race_date`, `horse_number`, and any available horse ID across joins. Require one-to-one keys, finite score values, complete race rosters, and exactly `N_r` score rows for each race.
- Require the evaluation cohort to match the saved F1 rows: 1,779 races, 17,412 runners, 269 race dates, 2024-01-05 through 2026-09-19. Preserve the year counts and partial-year marker from the source manifest.
- Require exactly three distinct `finish_position <= 3` runners per race. Generate every unordered pair from the full roster and require exactly `C(N_r,2)` pair rows and exactly three positive labels per race. Outcomes are labels only.
- For each continuous history mean, require `n=0` iff value is null; for valid values require finite means and integer counts in `1..5`. Do not impute from other horses, races, or older slots. Fail closed on inconsistent mean/count pairs.
- Verify all calendar and T−2 assertions in [PLAN.md](PLAN.md), including each H1 purge, H2-to-evaluation gap, and saved F1 `refit_max` to H1 gap. Do not use the saved F1 yearly `tau` in H1, H2, or `p_0`.
- Rebuild `p_0` from every `C(N,3)` unordered triple at fixed `tau=1`: compute each triple energy with `math.fsum` over ascending horse number, stable softmax after subtracting the maximum energy, and all mass sums with `math.fsum` in canonical triple order. Require probabilities finite and strictly between 0 and 1 for each pair, each race's triple mass to sum to 1, and each race's pair mass to sum to 3 within absolute tolerance `1e-12`. Verify that the maximum-`p_0` pair equals the raw-score top-two pair for every race; this is a structural parity check for `N>=4`, and a mismatch fails closed. Do not round source scores or probabilities.
- Require pair feature invariance under swapping its runners. At `beta=0`, require raw candidate logits and probabilities to match `p_0` exactly within `1e-12`; after H2 calibration, require the candidate and baseline calibrated outputs to match when calibration is given the same `p_0` logits and labels.
- For saved joint comparisons, require race, roster, and exact triple coverage to match the evaluation cohort. Reconstruct each pair event probability as a sum over source triples; cross-check Top3 runner marginals against the pinned runner file. Do not use these saved outcomes to train the direct model.

## Prohibited access and writes

Do not access any database, network source, current model, operating registry, or files beyond the pinned paths. Do not modify source artifacts or prior research folders. Do not fit, calibrate, calculate outcome metrics, or publish under this design alone. Any eventual code, fit receipts, and reports must be written only under `jeju/research/20261011_pair_top3_direct_design_v1/`, after their separate approvals.
