# Conditional order head implementation review

Review scope: read-only static audit of `20261017_conditional_order_head_v1/order_head_core.py`, `fit_predict.py`, and the current `metrics.py`, against the frozen `PLAN.md` and `INPUT_CONTRACT.md`. No fitting, real-data evaluation, or edits to the study implementation were performed by this reviewer.

## Findings

- No remaining plan-breaking issue found in the inspected implementation. The conditional head is applied only to permutations of each saved unordered Top3 set, and the prediction path multiplies its six normalized order probabilities by the unchanged set probability `q`. The fixed-score control uses the saved raw score, and the uniform control is `1/6` within each set.
- The fold wrapper rebuilds H1/H2 from prior-year OOS calibration scores, checks rebuilt row/race/date boundaries against the frozen preflight, fits the feature transform on H1 only, uses only the observed H1 Top3 order for conditional PL, and calibrates one bounded positive temperature on H2 order labels. Evaluation prediction loading drops `finish_position`.
- The metric path calculates race-equal conditional-order NLL and its paired date-bootstrap interval. It separately confirms, per race, that the candidate-minus-control full ordered TRI NLL delta equals the conditional NLL delta. The gate is correctly the predeclared 95% interval favoring lower conditional NLL plus point nonregression in the full-field TRI rank-1 hit rate. Conditional rank-1 accuracy remains diagnostic only.
- WIN/QNL/EXA/TRI event tables sum the complete ordered joint distribution, assert categorical mass and expected event support, and calculate categorical NLL, multiclass Brier, and event rank-1 hit rate. The same-467 HY comparison is filtered to the fixed common cohort and its saved probability CSV is loaded with explicit probability/event columns only; odds and hit columns are excluded. The TRI q-plus-order NLL decomposition is mathematically correct.
- The two runtime issues reported by root are corrected in the current source: key extraction iterates tuple values instead of indexing a named tuple with strings, and pivot columns are flattened with `_`, which matches the downstream column names. The current same-467 comparison also explicitly filters both model rows to the 2026 common IDs before pairing.

## Verification boundary

The main agent reports that its memory-only synthetic end-to-end checks pass for event support/mass, pivot/gate assembly, four-pool pairing on a two-race common cohort, and the TRI q-plus-order NLL identity (maximum reported identity error `2.22e-16`). I reviewed the corresponding implementation and formulas statically. This review did not run that test, fit or recalibrate a model, consume the saved evaluation outcomes, or calculate any real-data metric. Root's independent fit/stationarity review remains the numerical fit check.

No additional blocking issue was identified before source sealing.
