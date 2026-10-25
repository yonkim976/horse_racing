# Joint relationship gain/loss retrospective analysis

## Status and scope

This is a fixed analysis plan for repeated historical evaluation data. It is not a new preregistration, confirmatory study, independent holdout, or production decision. The 2024–2026 evaluation races have already appeared in prior development work. The analysis reads the saved relationship model parameters and existing outputs; it does not fit a model, tune a coefficient or threshold, alter a database, or change an operating model.

All new code, documentation, and outputs for this analysis belong in `jeju/research/20261010_joint_gain_loss_v1/`. The fixed cohort is the saved 1,779-race, 17,412-runner, 269-date cohort from 2024-01-05 through the partial 2026 period ending 2026-09-19. The comparison is saved `matched_baseline` versus saved `candidate`, with 6 selected triples per race at most.

## Questions

1. Which exact races account for gained versus lost Top3-set hits, and how do those 84 cases sit within the full 1,779-race denominator?
2. How do saved prediction-time conditions and descriptive race groups relate to both arms' hit outcomes and their paired difference?
3. How did the actual unordered Top3 set move in rank, probability, and relationship energy, and what happened at each arm's rank-6/rank-7 boundary?
4. How do the fixed 11 relationship terms add up on the actual Top3 set in the saved candidate? These are algebraic diagnostics of correlated model terms, not causal or independently interpretable effects.

## Frozen inputs and joins

The input hash and column contract is recorded in `INPUT_CONTRACT.json` before outcome analysis. The authoritative source manifest is `20261010_joint_relationship_v1/ARTIFACT_MANIFEST.json`, whose expected SHA-256 is `d0d1a749afb6a6f894de1bb4263c9d67dd1e3b2d1a35bf1b5fd38d8948c656b0`.

The main comparison uses the immutable saved `fit_parameters.json`, `race_metrics.csv`, `runner_marginals.csv`, and `all_triples.parquet`. Runner history and race descriptors come from `20261010_style_history_ablation_v1/outputs/features.parquet`; the saved year-specific `evaluation_scores.parquet` files are joined by unique `api_record_id`. No database query, network access, source collection, or model fitting is part of this analysis. Before computing outcomes, the code will verify source hashes, fold coverage, unique keys, the 1,779 race / 17,412 runner / 269 date totals, one exact true Top3 set per race, and complete `C(N,3)` rows for both arms.

The three saved style-history means and their support counts are treated as existing prediction-time inputs under their source contract. `history_cutoff` and `latest_history_date` are carried into the audit so their timing can be checked; no post-race measurements are added. These are relative-position summaries: a positive forward difference means a better relative rank at the later measured point, not faster elapsed time, final placing, or a pure closer style. At 1300m, the measured start-to-2C-to-S1F sequence differs from other distances, so its first segment is not treated as an equivalent early 200m measure. Experience, layoff, and same-distance history are descriptive saved features, not newly created inputs.

`field_n` describes the complete saved post-race evaluation roster, and `grade_raw` is carried as a saved race descriptor. The analysis does not establish that either value was available at the intended prediction timestamp; subgroup results using them are retrospective descriptors unless a separate publication-time source audit confirms availability.

## Outcomes and denominators

The full race ledger has one row for every evaluation race. Its mutually exclusive hit class is `gained` (baseline miss, candidate hit), `lost` (baseline hit, candidate miss), `both_hit`, or `both_miss`. Selection-set changes are recorded separately: unchanged versus changed top-six ticket sets. The 84 gained/lost rows are exported as a complete ledger and are always shown alongside their denominators in the 1,779-race cohort or the named condition subgroup.

For the full cohort and each fixed single-factor subgroup, report race count, unique race dates, gained, lost, net (`gained - lost`), baseline hits, candidate hits, both hit rates, and candidate-minus-baseline hit-rate difference. Compute a pointwise 95% paired-date cluster-bootstrap interval for the race-level hit difference using 2,000 draws and seed `20261008`; each sampled date contributes all subgroup races on that date. Subgroups are year (2026 marked partial), calendar month, exact saved distance, exact saved raw grade (missing kept explicit), and fixed field-size bins `<=8`, `9-10`, `>=11`. These are descriptive intervals across many comparisons; small date counts and multiple comparisons will be shown, not treated as confirmatory evidence.

## Prediction-time condition summaries

No condition boundary is chosen by looking for the largest gain. The analysis will report simple continuous summaries, and the fixed subgroup table above, for:

- Raw saved score gaps between ranks 1–2, 1–3, and 3–4, plus each gap divided by the within-race score standard deviation for cross-fold scale context.
- Baseline and candidate probability concentration: maximum triple probability, top-six probability mass, entropy, and effective number of triples (`exp(entropy)`).
- Baseline and candidate rank-6/rank-7 triple-energy and probability margins, with exact energy ties (`margin=0`) and tolerance ties (`|margin|<=1e-12`) reported separately. Stable rank order remains the saved enumerator order and is recorded for each boundary pair.
- Race-level distributions of career starts (`0`, `1-4`, `5+`), same-distance prior observations and missingness, days since the prior start and missingness, style-history support counts and missingness, and the two forward-progression means.
- Within-race style heterogeneity as the mean over runner pairs of their average absolute difference on the three available style means after the saved fold scaler; eligible-pair and feature support are reported with it. This is descriptive and may vary with missingness.

The within-race score standard deviation uses population scaling (`ddof=0`).

Continuous summaries are shown by full cohort and the four hit classes. The hit class is an outcome-defined grouping, so its comparisons are explanatory after selection and cannot define an application rule. Prediction-time conditions over all races are kept distinct from the post-outcome `gained`/`lost` partition.

## Actual Top3-set movement and relationship decomposition

For every race, pair the same actual unordered Top3 triple across both saved arms and record rank, probability, total energy, relationship energy, rank change, and entry/exit status in the selected six. Also record each arm's rank-6 and rank-7 tickets, energy margin `E(rank 6)-E(rank 7)`, probability margin, exact/tolerance tie status, and stable boundary order. This separates a changed selection at a zero margin from a strict energy separation.

For each actual Top3 set, reconstruct the saved candidate's 11 term contributions with the fold's immutable scaler, pair RMS, beta, and the fixed relationship-feature construction in `joint_model.py`. Verify the 11 contributions sum to the candidate relationship energy already stored for that triple within `1e-10`. Report each term and four descriptive grouped sums: score-related (2 terms), style-mean differences (3), support-count differences (3), and missingness indicators (3). Show the full-cohort total and means by hit class, as well as the 84 gained/lost rows. Term correlations and shared transformations prevent causal or isolated-term interpretation.

Also choose one candidate boundary competitor `U` per race for the actual true set `T*`: if `T*` is inside the candidate six, `U` is the candidate rank-7 triple; otherwise `U` is the candidate rank-6 triple. Record `E_candidate(T*)-E_candidate(U)` as the sum of the saved baseline score-energy contrast and all 11 candidate relationship-contribution contrasts (`T*` minus `U`). Record both ticket IDs, ranks, exact/tolerance tie status, and the stable order. This is an outcome-dependent diagnostic of the saved ranking; it is not a prediction-time condition, a unique cause, or a one-ticket-only explanation.

## Mechanical case selection and reporting

To make examples reproducible rather than cherry-picked, select within each evaluation year: (a) the gained race with the smallest positive true-set rank improvement, (b) the lost race with the smallest positive true-set rank deterioration, ties broken by `race_id`, and (c) a both-miss race whose true-set rank improved but remains outside six, choosing the smallest candidate true-set rank and then `race_id`. If a rule has no eligible race in a year, report no case. Include contrary cases through the complete 84-row ledger and the both-miss example; do not use examples to propose a cutoff.

The final README will state only 2–3 bounded hypotheses for a future, separately designed model-training or validation study. It will not claim a discovered deployable condition or recommend coefficient/threshold changes from this retrospective split.

## Planned artifacts

- `race_ledger_1779.csv`: complete cohort and full denominators.
- `gain_loss_84.csv`: every gained/lost case with true-set and boundary details.
- `condition_summary.csv`: all fixed condition groups with counts, hit rates, paired-date intervals, date counts, and subgroup denominators.
- `continuous_features_by_outcome.csv` and `feature_missingness_by_outcome.csv`: prediction-time diagnostics, full cohort plus outcome-defined classes.
- `true_set_beta_contributions.csv` and `beta_decomposition_by_outcome.csv`: the complete true-set term and grouped decomposition.
- `selection_boundary_detail_1779.csv` and `selected_ticket_changes.csv`: rank-six/rank-seven diagnostics and selected ticket entry/exit accounting.
- `true_set_boundary_competitor_1779.csv`: post-outcome true-set versus candidate rank-6/rank-7 competitor energy decomposition.
- `mechanical_cases.csv`, `README.md`, and a final `ARTIFACT_MANIFEST.json` with source and output hashes.

