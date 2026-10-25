# Fit code review

Status: **PASS for the separate root fit-approval gate.** Final reviewed snapshot:

- Plan: SHA-256 `c5683a8716e62094a7856cadfd44119dfac3c6ac3edd9f08652a951e42297012`
- Source audit: SHA-256 `c70596688c22c97deb7fa48cba21ef6e5442ea29e1901f790277c1f03fbe3fbd`
- `fit_selector.py`: SHA-256 `257542455ad60ba8299f0952ee3976cc1a6916a432b3a1ecdbbf9420241e94a3`

No model fit, candidate selection, or evaluation outcome calculation was run by this reviewer. Fit should remain gated on the root's own synthetic objective/positive-set controls and a fit approval that binds these exact hashes.

## Corrections verified

1. The label reader now queries only `2019 <= year < evaluation_year`, then rechecks the returned years before building its label map. Feature inputs are read with an explicit non-label allowlist. The fit receipt and `LABEL_PREFLIGHT.json` preserve fold-specific training-label checks and state that the evaluation year was not accessed.
2. The positive-set mask now checks that exactly three of the selected five runners are Top3, which is the same as requiring all three actual Top3 runners to be contained in the five-set. It validates the expected positive-set count `C(N−3,2)` after confirming exactly three Top3 labels.
3. Count inputs are checked as finite nonnegative integers; style support counts are constrained to 0–5; infinities in the continuous inputs fail closed. The plan now specifies finite-only train-row mean/SD fitting, `ddof=0`, missing-value mean imputation to standardized zero, and no set-count-based scaler weighting.
4. The optimizer is a single zero-start L-BFGS-B call. It requires optimizer success, finite coefficients/objective/gradient, and a fixed maximum absolute gradient threshold `1e-6`. It fails closed without retry or search.

## Math and data-flow checks

- `G_r` is correctly constructed as all five-sets containing the actual three Top3 runners. Every training race is checked for a complete `1..N` finish with exactly three Top3 labels.
- The implemented objective is the locked partial-event Gibbs negative log likelihood averaged equally over races, plus `λ||β||²/2`. Grouped log-sum-exp subtracts each race maximum before exponentiation. The aggregate gradient sums the per-race `E_all[φ]−E_good[φ]` terms, divides by race count, and adds `λβ`; this matches the stated derivative.
- The fit receipt includes the pre-fit label-validation summary expected by the separately gated report stage. Source/provider hashes and row-wise T−2 checks are fixed; the score providers are raw OOS calibration scores and no same-year temperature is used.
- The reviewed objective is non-convex in general and a single converged run is only a local solution. Its Gibbs mass is a stochastic-selector training quantity, not calibrated probability or deterministic argmax coverage. The plan and model metadata state these limits.

## Security and scope checks

The script uses fixed, SHA-locked source paths confined to the repository; validates output confinement and refuses symlink/overwrite paths; writes only to the new study output directory; and uses JSON serialization with `allow_nan=False`. No shell command execution, dynamic code evaluation, database/network access, or unsafe deserialization is present. The separate root approval checks the plan, source-audit, and fit-code hashes before the code can train.
