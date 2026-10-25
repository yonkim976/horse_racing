# Rank-specific sequential PL temperature experiment

Status: preparation only. The comparison conditions below are fixed by the supervisor after methods review. The single candidate, fitted temperatures, evaluation probabilities, and performance metrics remain uncomputed until code review passes and the supervisor publishes an approval matching the final hashes.

## Question and scope

This study asks whether three stage-specific scalar temperatures improve the full-field sequential Plackett–Luce joint Top3 distribution over the previous common-temperature PL baseline, while also protecting WIN against the prior raw-score `T=1` reference. There is one candidate with three fitted parameters (`T1`, `T2`, `T3`), not three candidate models. F1_STYLE6 is not retrained. Only saved raw F1_STYLE6 score columns and the frozen finish labels are used. Saved provider temperatures and temperature-applied probabilities are excluded.

This is a research calibration comparison. It does not alter the native additive `q(T)`, the production model, the experimental registry, or any prior experiment. A gate pass will not imply model promotion, operating readiness, market availability, or ROI.

## Frozen cohorts and inputs

Training uses the existing raw OOS score files for label years 2019–2023: 2,492 races and 25,278 runners. Evaluation uses the existing raw evaluation score files for 2024–2026 through 2026-09-19: 1,779 races, 17,412 runners, and 269 race dates. The evaluation years retain their saved rolling model vintages; no 2024–2026 label is used to update the temperatures.

The source index is the read-only asset manifest `../../20261022_joint_wager_baseline_v1/assets_audit/assets_manifest.json` (SHA-256 `ea2d2b0363539f3b7b0b88c3b2254c14f04095715ac1f137f71beba77a9a36a3`). The frozen feature file SHA-256 is `036939bd6d518a9e53d458a2f4eb2bf30bfecfa4bb80e21c78edd1f7f44f028f`. Its `api_record_id` joins to each raw score file one-to-one. All feature history cutoffs must equal race date minus two calendar days; provider `refit_max` must precede the first target race by at least two days. Scores remain the saved pre-temperature `score` values, including 2023 training scores whose provider metadata also contains a same-year fitted tau.

The prior baseline sources, contracts, and reusable outputs are immutable inputs. Their expected hashes are checked during preflight and again before evaluation:

| Reference | Path | SHA-256 |
|---|---|---|
| Baseline plan | `../../20261022_joint_wager_baseline_v1/experiment/PLAN.md` | `818e8a268d2955890f7185157f9503ffc4c24df035839354bc74f5804a71fe62` |
| Baseline code | `../../20261022_joint_wager_baseline_v1/experiment/baseline.py` | `c7c6fb27ac43bdf4eba952a30ecdb957f4c1c19575bd856e50eba9b87455a6c7` |
| Baseline structural input report | `../../20261022_joint_wager_baseline_v1/experiment/outputs/source_preflight.json` | `10c5a75c79055da3e5c9278ab23dd3a75bfbd6a8fd64121a3dbff315d8754494` |
| Baseline common-T and T=1 race losses | `../../20261022_joint_wager_baseline_v1/experiment/outputs/race_metrics.parquet` | `35dd5adbe954af6b086e917267a4ae08ca0d1974cdea43ed61a93a2db60d86ff` |
| Baseline runner marginals | `../../20261022_joint_wager_baseline_v1/experiment/outputs/runner_marginals.parquet` | `c4416ec90ff426d2debedbfc897dbc5be6ee85df48180ba940e96a81a5b15110` |
| Baseline selected-ticket ledger | `../../20261022_joint_wager_baseline_v1/experiment/outputs/selected_ticket_ledger.parquet` | `6f0dcce5e3c2e68f06c7cb209bc8cc279e24e6b274aef45cd33e5e3d97e8e7f0` |
| Baseline annual summaries | `../../20261022_joint_wager_baseline_v1/experiment/outputs/pool_year_summary.parquet` | `4c67d073f812d909c6e52db0a2511c111af4c2e70f65964cc6a50e4489082444` |
| Baseline reliability bins | `../../20261022_joint_wager_baseline_v1/experiment/outputs/reliability_bins.parquet` | `d319ff030e62c08365e42c699a0000eb079d43d291166cc3df2d364b477a3652` |
| Baseline race/pool contract ledger | `../../20261022_joint_wager_baseline_v1/experiment/outputs/race_contract_ledger.parquet` | `fe3f58e3ab071e1f8eb5a527c28f665fbdecca1314ec778bbd98e320ccd51bac` |
| Official event/rule contract | `../../20261022_joint_wager_baseline_v1/rules_contract/rules_contract.json` | `20cd4b17274018a36efbb1b0cea64eb5d5c9809ed5f3481bea59c734f99fee83` |

The baseline common-temperature comparator is the prior fitted `T=1.1837152381349905` applied at every PL stage. The separate WIN protection reference is raw-score `T=1`. No old baseline loss, runner, selection, or contract table is copied into this experiment; the report records reference paths and hashes. Only the new candidate metrics and a small fresh selection ledger under a uniform tie rule are written.

## Candidate probability and fitting definition

For a race with all `N` starters and saved raw scores `s_i`, define each stage's conditional selection probability over the full set still available:

`P_r(i | A) = exp(s_i / T_r) / sum_{h in A} exp(s_h / T_r)`.

For distinct ordered horses `(i,j,k)`,

`Q(i,j,k) = P_1(i | all N) × P_2(j | all except i) × P_3(k | all except i,j)`.

The stage-2 denominator therefore has `N−1` runners. The stage-3 denominator has `N−2` runners and includes every remaining starter, including horses whose final finish was below third. The target is not a three-horse set followed by a conditional ordering. Each stage uses a stable log-sum-exp over its full remaining starter set. Race-local probabilities are aggregated directly into runner marginals and the seven pool event maps; no full Q table or all-ticket table is retained across races.

For each rank `r∈{1,2,3}`, fit exactly one scalar `T_r` on the 2,492 training races by minimizing that stage's race-equal conditional NLL:

`L_r(T_r) = (1/2492) × Σ_race −log P_r(actual horse at rank r | actual earlier finishers removed; all other starters remain)`.

Each independent bounded scalar optimization uses `[0.35,4.0]`, SciPy `minimize_scalar(method="bounded", xatol=1e-12)`, and an explicit comparison of the optimizer point and both bounds. If candidate objective values are exactly equal, select the smaller T. There is no regularization, sharing, or post-fit adjustment. In particular, rank 3 must retain all `N−2` competing runners so `T3` is identifiable. Calibration labels are exactly the unique final ranks 1, 2, and 3 under the existing complete-field contract. After approval, record the inverse-temperature objective gradient and Hessian at each fitted value, verify convexity/identifiability, check the correct gradient direction if a bound is optimal, and check the fitted training objective is not worse than the frozen common-T objective by more than `1e−10` numerical tolerance. An optimizer failure, flat/unidentified objective, or failed diagnostic stops the run; bounds are not widened after results.

## Comparisons and draft decision gates

These conditions are fixed by the supervisor after methods review. The execution code will fail closed if its approved condition/hash record does not match this plan.

The primary comparison is candidate versus common-T baseline for TRI over the complete ordered triple event space on the same evaluation races. The TRI difference is race-equal NLL with the existing frozen 2,000-draw, 269-date paired bootstrap schedule; `candidate − common-T` bootstrap 95% CI upper bound must be below zero. TRI sum-Brier point difference must be at most zero. `T1,T2,T3` are fixed across bootstrap draws, so this interval does not include calibration-fit uncertainty. The 2024–2026 evaluation material was previously reused during development and is not an independent holdout.

The WIN protection comparison is candidate versus raw `T=1`. Both race-equal categorical WIN NLL and sum Brier point differences must be at most zero. These are point-estimate checks only and do not establish statistical non-inferiority. Other pools are reported against common-T, pool by pool; they do not override the primary gate. No market price, hit-rate-based promotion, ROI, or post-result tuning is performed.

All seven pools retain the existing official event definitions, statutory minimum fields, label contract, and race denominators. Candidate versus common-T loss and annual summaries are calculated per pool. The WIN protection comparison uses the raw-T1 losses already stored by the prior experiment. Reliability uses the same fixed probability bins and pooled ticket-event-count weighting; this weighting is reported separately from the race-equal proper scores. For categorical pools use race-equal `−log(max(p_true, 1e−15))` and ticket-space sum Brier. For PLC/QPL use ticket Bernoulli log loss with probabilities clipped to `[1e−15,1−1e−15]` and Brier without clipping, averaged across eligible tickets within a race before equal race weighting.

The official contract sets PLC's Top2/Top3 split from the sales-opening field count. Since that count is unavailable, the same 36 actual-seven-runner races are excluded from PLC only. For actual field size at least eight, Top3 remains conditional on the prior contract's no-post-opening-additions lower-bound inference. QPL remains the Top3-pair event. Other pool denominators remain 1,779.

## Selection diagnostics and tie policy

For candidate, common-T, and raw-T1 selection diagnostics, apply exactly one deterministic rule: tickets with `p >= pmax − 1e−12` are eligible; choose the lexicographically smallest horse-number tuple. Apply the same rule to every arm and pool. Report selected key, selected probability, exact maximum, number of eligible numerical ties, and hit. This tie convention only governs the one-ticket diagnostic; it does not alter event probabilities, loss, reliability, or any gate. The candidate's ordered MAP is not assumed to follow raw-score order because different stage temperatures can change order. WIN's score-based ordering is unchanged, subject to the fixed tie rule. Choice/hit changes are not evidence of probability calibration or model-selection improvement by themselves.

## Preparation checks, approval gate, and stored outputs

`--synthetic-checks` tests normalization, score-shift invariance, rank-specific denominators, third-stage inclusion of horses outside the actual Top3, full ordered joint mass and marginals, pool event masses, rule branches, and the uniform tie policy on constructed arrays only. It never reads real race score/label data.

`--source-preflight` may read the raw-score files, frozen features, metadata, official contract, fixed bootstrap schedule, and listed baseline outputs. It checks SHA-256s, schemas, one-to-one joins, years/counts, score finiteness, complete distinct race labels, date cutoffs, pool denominator references, and a 20 MB output budget. It does not fit temperatures, compute real-race PL probabilities, evaluate outcomes, or produce performance metrics. It writes only `outputs/source_preflight.json` and a 36-row PLC preflight quarantine table; the full contract ledger is referenced by its frozen path/hash.

Actual fitting and evaluation require a supervisor approval at `../supervisor/RANK_STAGE_EXECUTION_APPROVAL.json` that matches this PLAN, code, source preflight, raw asset manifest, rules contract, immutable baseline references, and final comparison conditions. Only after that approval may `--fit-evaluate` calculate the three temperatures and make one complete evaluation pass. The command refuses an existing result file and never overwrites results. No fit or evaluation command is run as part of preparation.

After approval, compact new outputs are limited to: fit receipt/report JSON; candidate race/pool metrics; candidate runner marginals; candidate reliability-bin aggregates; annual and overall comparisons; a small selected-ticket diagnostic ledger for candidate/common-T/raw-T1 under the common tie rule; and one summary of arm choice changes. Existing loss and event ledgers remain path/hash references. Every full ordered Q is discarded after race-local aggregation. Outputs are compressed Parquet and capped at 20,000,000 bytes total for this experiment; the working session remains under the supervisor's 300,000,000-byte budget.

Structural preflight is not a code-review pass or execution authorization. Wait for supervisor code review and the explicit final-condition/hash approval before fitting.
