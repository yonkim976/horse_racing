# Fit code review before optimizer

Status: **PASS for the corrected source hash only, after a demonstrated gradient defect was fixed and rechecked.** The earlier static PASS below is superseded and must not be used for approval. Reviewed source hashes:

- `PLAN.md`: `97cb3059573fd8c8352139ab9921a541dec997cabdcef2e7dc02cc19cc39d0cf`
- `SOURCE_AUDIT.md`: `918f68b3d78b105e12e4e02502a024fb211ed19f75c7916203ff6db9b5459753`
- Initial `fit_selector.py`: `808e0cde0e04a6046bc4345cb0072b28c6d3d3eb10f364125e129315500b4f8a`
- Corrected `fit_selector.py`: `043c669ad6f8d7a9d66bb5846002758385c3e0811e7e6720727b2e5c1e9b85dc`

The initial static review marked the first fit-code hash PASS, but missed a real gradient bug. Root's synthetic audit `jeju/research/20261025_top5_reward_learning_rootreview_v1/ROOT_PREFIT_GRADIENT_AUDIT_v1.json` (SHA-256 `355dc7b38106196516be39c78f61ad812c5ec5d7154d2024b4bf7a7407e7a5e3`) measured gradient error `0.12503606385115162` versus the independent formula and `0.12503606392920924` versus finite differences. The loss matched, but `grouped_logz_and_weights` returned one expectation aggregated over all races; multiplying it by each race's `Pgood` was invalid. The initial static PASS is explicitly withdrawn.

The main author changed the helper to return per-race `(race_count, feature_count)` expectations. I then called the corrected main `make_objective` on three distinct synthetic races using `check_actual_fit_gradient.py`, independently recomputed each race's formula, and central-differenced the source objective. Exact loss difference was `0`; analytic gradient differed from the independent formula by `2.7755575615628914e−16` and from finite differences by `1.0385774185106555e−10`. The hash-bound receipt is `ACTUAL_FIT_GRADIENT_AUDIT.json`. No project data, training labels, fitted parameters, choices, or outcomes were read.

No fit, evaluation choice, or outcome calculation was run during the pre-fit code-review stage. The corrected source was later approved and run by the main study. Its three fit receipts were independently recomputed in `RECOMPUTED_FIT_AUDIT.json`; all scalers matched exactly and objective/gradient values matched to floating-point precision.

## Objective and positive-set logic

The fit fixes the same additive raw-score prior and standardized runner inputs as the preceding direct-learning head. For every race it enumerates all `C(N,5)` actions, sums the fixed race-z scores and the five runners' 11-vectors, and marks a set good exactly when `top3[actions].sum(axis=1) == 3`. With a separately checked complete `1..N` finish and exactly three Top3 labels, that is equivalent to actual Top3 being a subset of the five-set. `C(N−3,2)` is checked for each race.

The grouped log-sum-exp calculation is stabilized by subtracting the per-race maximum. In the initial source, the grouped helper returned a single all-race expectation vector, which was then incorrectly broadcast across per-race `Pgood`; root's finite-difference audit caught this. The corrected helper accumulates each feature's weighted values by race using `bincount`, returning a matrix with shape `(race_count, feature_count)`. The source now computes positive and all-set expectations per race under their corresponding Gibbs weights. It implements

`mean_r[1−2Pgood_r] + 0.5||β||²`

and

`mean_r[2Pgood_r(Eall[φ]−Egood[φ])] + β`.

This is the exact gradient of the locked expected `+1/−1` reward objective. It is not the prior partial-event NLL objective. Both standalone derivation checks and a call through the actual corrected `make_objective` pass; see `INDEPENDENT_MATH_REVIEW.md` and `ACTUAL_FIT_GRADIENT_AUDIT.json`.

## Inputs, folds, and fit controls

- Feature columns for the head match the prior 11-input study, including `log1p` count transforms, separate missing indicator for `mean5_rank_fraction`, and paired style-mean/support missingness validation.
- Fold scaler fits finite training-runner values only, uses `ddof=0`, maps constant scales to 1, and assigns missing standardized values to 0. Candidate-set counts do not weight the scaler.
- The score providers, hashes, metadata, and `refit_max` cutoffs match the preceding head; every training row is checked against `refit_max ≤ race_date−2 days`.
- Label queries are filter-bounded to `2019 ≤ year < evaluation_year`, and returned years are checked again. Feature input reads an explicit non-label allowlist. Training race rank permutations and exactly-three-Top3 checks run before the optimizer.
- Optimizer is one zero-start L-BFGS-B call with the requested fixed options and no restart/search. The code fails closed on failed convergence, nonfinite output, or final maximum absolute gradient greater than `1e−6`.
- The receipt and model metadata explicitly distinguish Gibbs stochastic expected reward from the later deterministic argmax result and prohibit probability-calibration interpretation.

The feature parquet schema reports `year`, `finish_position`, `field_n`, and `api_record_id` as integer columns. Therefore the fit's integer conversion of training label values cannot silently truncate fractional finish positions in this fixed source. This schema check read only parquet metadata, not label values.

## Security and confinement

Source paths are constants, reject symlinks, resolve under the repository root, and must match pinned SHA-256 values. Output names are fixed internal constants, paths are confined to the new study's `outputs/`, existing files are refused, and JSON uses exclusive-create mode with `allow_nan=False`. Data are read from hash-pinned local Parquet and JSON; the script has no database/network access, shell execution, pickle deserialization, or dynamic code execution. This matches the checked Python path-traversal and deserialization guidance.

No blocking correctness or leakage issue remains in the corrected fit source. The actual objective gradient was checked before renewed fit approval, and the saved fit receipt and source lineage were independently replayed after the approved run.
