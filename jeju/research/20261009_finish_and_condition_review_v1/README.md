# Finish-history and condition review

Independent implementation checks for the 2026-10-09 finish-history ablation and special-condition audit. The underlying studies use repeated retrospective evaluation data; these checks reproduce calculations and do not constitute independent future validation, causal evidence, or operational approval.

The finish-history check reloaded the three stored R1 models and six F1/F2 candidates, reproduced R1 replay and candidate probabilities, calibration, runner/race metrics, six-combination tables, bootstrap summaries, and the common 467-race operating comparison. F1 passed the predeclared sequential probability gate against R1. F2's incremental F2−F1 log-loss and Brier point estimates were lower, but both date-bootstrap intervals included zero, so F2 did not pass the next sequential research-candidate gate. Combination results are reported separately. On the common operating set, HY_R_FORM remained ahead of F1, and no operational model or registry was changed.

The special-condition review independently recalculated the original S1–S4 statistics and the F1-only residual supplement. The original 575-row condition table remained unchanged. The 301 F1 cells and intervals, 17,412 prediction-to-condition joins, per-race probability sums, and S2's 312-row/26-scope fixed 12-cell grid passed independent recalculation. The original S2 supplement grid had six `period=all` rows with `F1_rows=0` but non-null `mean_p_F1`; the original is preserved and a correction-only v2 nulls those six means. The F1 supplement reports conditional residuals, not feature effects. The first-return condition is a thresholded form of existing days-since-start information after censoring uncertain rows; S4 residual patterns attenuate in F1 and do not identify unique or causal contribution.

The review did not modify the database, production model, registry, or either study's locked source and primary result files.

## Independent receipts

- [Finish-history model and metric recalculation](independent_verification.json)
- [Original S1–S4 recalculation](special_condition_independent_verification.json)
- [F1 condition supplement and corrected S2 grid recalculation](f1_condition_supplement_independent_verification.json)

## Source studies

- [Finish-history ablation](../20261009_finish_history_ablation_v1/README.md)
- [Special-condition audit](../20261009_special_condition_audit_v1/README.md)
- [Predeclared sequential gate interpretation](sequential_gate_decision.md)
- [Review log and correction trail](review_log.md)
- [Central publication receipt](central_publication_receipt.json)
