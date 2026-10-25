# Final pre-fit review

**Status: PASS — static pre-fit review.** I found no blocking design or source issues in the frozen bundle. This is not an execution approval.

I checked the final implementation against the frozen contract, with attention to annual A/phase OOS vintages, B's conditional-Z training and forecast-q shared mixture, R's same-provider raw-score calibration, probability/event identities, pool eligibility, race-equal proper losses, date bootstrap comparisons, ledgers, and the approval gate. A, B, and R use the same exact evaluation rows. B fits gamma only on annual OOS vintages through `Y−2`, calibrates its mixture temperature on `Y−1`, and evaluates with the target-year forecast `q`; target-race Z is not an input to its prediction. The output includes post-prediction OOS phase diagnostics, and those diagnostics do not feed model fitting or pool gates.

The refreshed structural preflight passes for 5,206 races / 52,155 runners and the exact 1,779-race / 17,412-runner / 269-date evaluation cohort. It verifies denominators of 1,779 for WIN, QNL, EXA, QPL, TLA, and TRI, and 1,743 for PLC. The 36 actual 5–7-runner races are excluded only from PLC because sales-opening N is unknown. Actual N≥8 remains a lower-bound assumption under the inherited contract; the ledger does not claim opening counts, pool offering, or settlement were audited.

The worker reports eight passing synthetic checks and a passing source preflight. I independently rechecked the final module, test, input manifest, and preflight hashes and confirmed the preflight pins the final code bundle. The output directory contains only the preflight receipt; no fit, forecast run, or real-outcome metric calculation occurred in this review.

Residual limits are inherited and nonblocking for this pre-fit decision: historical pool-offering/settlement is not reconstructed for every race; the study conditions on the final recorded starter roster; 2024–2026 are reused development data; and the fixed date bootstrap does not include fit uncertainty. A positive penalized gamma-Hessian is a numerical property of the regularized objective, not evidence of unregularized or causal identification.

| Reviewed artifact | SHA-256 |
|---|---|
| `experiment/dynamic_ability_pace.py` | `706b2e94a6b311e5bd9b3706da7df4f6a08117e917d22171fbde63a4d1a3210c` |
| `experiment/test_dynamic_ability_pace.py` | `9e6089f9c770c253da0d6229769ca48abc7a343bf4bcdd87d4a73cf6acab3ef9` |
| Code bundle | `e374a0682a225cdfb06fd079f5e32514f618e3e7276643c88680afc10a131612` |
| `experiment/outputs/source_preflight.json` | `1153cbda6b377db7f8c49c0e741122abf3c83d35957742d7161cbae3b695d179` |
| `inputs/input_manifest.json` | `f5ad29d2c96cbfbc11c9d5ae9387f4de69bed2de87461b0b86167575b36657c7` |

No blocking findings remain for the supervisor's separate execution-approval review. This report itself does not authorize fitting.
