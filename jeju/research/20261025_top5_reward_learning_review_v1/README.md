# Independent review: reward based Top5 selection

This review covers `jeju/research/20261025_top5_reward_learning_v1`. All new review code and receipts live here. The main study, source parquet, database, production models, and registry were not modified. No feature parquet, database, or full candidate-set matrix was copied.

## Result

The new deterministic reward head did **not** improve the primary historical cohort against either raw-score Top5 or the earlier partial-event NLL head. The predeclared gate required both paired primary differences to be positive and both date-bootstrap 95% lower bounds to exceed zero; neither comparison passed. Keep the existing model/selection practice unchanged and do not promote this research head.

| Primary cohort (1,503 races) | All three captured | Rate | Difference vs reward |
|---|---:|---:|---:|
| Raw-score Top5 | 439 | 29.2083% | +0.3327 pp |
| Partial-event NLL head | 435 | 28.9421% | +0.0665 pp |
| Reward head | 434 | 28.8756% | — |

The paired reward-minus-raw difference is **−0.3327 pp** (95% date-bootstrap CI **[−1.6459, +1.0467] pp**). Reward-minus-partial-NLL is **−0.0665 pp** (95% CI **[−1.3185, +1.1356] pp**). Both intervals include zero and both observed differences are negative.

On the 1,779-race full secondary cohort, reward captured all three Top3 runners in **515/1,779 (28.9488%)**, compared with raw Top5 **519/1,779 (29.1737%)** and partial-NLL **520/1,779 (29.2299%)**. The reward-minus-raw difference is −0.2248 pp (95% CI [−1.5247, +1.1251] pp); reward-minus-partial-NLL is −0.2811 pp (95% CI [−1.4543, +0.9045] pp).

## Independent verification

- The objective and gradient were derived independently. Synthetic finite differences passed, and a separate check called the corrected main `make_objective` on three synthetic races: loss difference 0, maximum gradient difference versus an independent formula `2.78e−16`, and versus central finite differences `1.04e−10`.
- The first static fit-code review incorrectly passed a gradient implementation that used one all-race feature expectation for every race. Root's synthetic audit caught the resulting `0.125` gradient error before fitting. The main code was corrected to compute per-race expectations. The initial PASS is explicitly withdrawn in [FIT_CODE_REVIEW.md](FIT_CODE_REVIEW.md); only corrected fit source SHA `043c669ad6f8d7a9d66bb5846002758385c3e0811e7e6720727b2e5c1e9b85dc` was fitted.
- All three fit receipts were independently recomputed using only the fold's training labels (`2019 ≤ year < Y`). The training-only scaler means and scales matched exactly, training row/race and full action counts matched the receipts, and objective/gradient values matched to floating-point precision. OOF score-provider hashes and `refit_max ≤ race_date−2 days` checks passed. No evaluation-year labels were read by the fit audit.
- The final selector source was reviewed at SHA `332304c499615288b37d9bc485f45f926931dedaf35d8242a4823e14fc616d54`. It reads only declared score/roster/feature allowlists for selection. An independent implementation enumerated all **411,084** five-sets and replayed all **1,779** saved choices without importing the selector or reading evaluation outcomes. Selected horse IDs/numbers, race metadata, selected and baseline energies matched exactly. The beta-zero control matched raw-score Top5 in 1,779/1,779 races.
- After root outcome approval bound the locked choices and final reporter hash, the independent outcome audit read the fixed binary `y` allowlist and recomputed every race, all three arms, captured-Top3 distributions, changed/caught/lost counts, year and distance tables, and all four paired date-bootstrap intervals. Every race ledger row and reported summary matched. The outcome audit records 13 independent reconciliation checks as PASS.

See [INDEPENDENT_MATH_REVIEW.md](INDEPENDENT_MATH_REVIEW.md), [FIT_CODE_REVIEW.md](FIT_CODE_REVIEW.md), [SELECTION_CODE_REVIEW.md](SELECTION_CODE_REVIEW.md), [OUTCOME_CODE_REVIEW.md](OUTCOME_CODE_REVIEW.md), [RECOMPUTED_FIT_AUDIT.json](RECOMPUTED_FIT_AUDIT.json), [INDEPENDENT_CHOICE_AUDIT.json](INDEPENDENT_CHOICE_AUDIT.json), and [INDEPENDENT_OUTCOME_AUDIT.json](INDEPENDENT_OUTCOME_AUDIT.json).

## Primary paired results

| Comparison | Caught by reward | Lost by reward | Both hit | Both miss | Δ (pp) | Date-bootstrap 95% CI (pp) |
|---|---:|---:|---:|---:|---:|---:|
| Reward vs raw | 47 | 52 | 387 | 1,017 | −0.3327 | [−1.6459, +1.0467] |
| Reward vs partial-NLL | 43 | 44 | 391 | 1,025 | −0.0665 | [−1.3185, +1.1356] |

Captured Top3 counts (0 / 1 / 2 / 3 runners) were raw **26 / 279 / 759 / 439**, partial-NLL **28 / 272 / 768 / 435**, and reward **27 / 285 / 757 / 434** on primary races. The reward head changed its selected set from raw Top5 in 370 primary and 464 full races; it differed from the partial-NLL head in 356 primary and 436 full races.

Primary subgroup all-three hits, shown as reward / raw / partial-NLL:

| Group | Races | Hits |
|---|---:|---:|
| 2024 | 499 | 132 / 140 / 133 |
| 2025 | 559 | 167 / 164 / 167 |
| 2026 partial year | 445 | 135 / 135 / 135 |
| 900 m | 251 | 69 / 74 / 68 |
| 1000 m | 508 | 146 / 155 / 154 |
| 1110 m | 482 | 142 / 136 / 142 |
| 1200 m | 262 | 77 / 74 / 71 |

These are repeated historical development data, not a fresh holdout. Gibbs `Pgood` and expected reward are stochastic training quantities conditional on the observed Top3; they are not calibrated probabilities and are not deterministic argmax coverage. This study did not claim PPO or LLM fine-tuning.

## Review files

- `check_reward_objective.py`, `ACTUAL_FIT_GRADIENT_AUDIT.json`: synthetic objective checks.
- `recompute_fit_receipt.py`, `RECOMPUTED_FIT_AUDIT.json`: independent folds, source hashes, scaler, objective and gradient replay.
- `verify_locked_choices.py`, `INDEPENDENT_CHOICE_AUDIT.json`: label-free replay of all selected five-sets and utilities.
- `verify_locked_outcomes.py`, `INDEPENDENT_OUTCOME_AUDIT.json`: post-approval three-arm outcome and date-bootstrap reconciliation.
- `FINAL_REVIEW_MANIFEST.json`: final hashes, byte counts, and review scope.
