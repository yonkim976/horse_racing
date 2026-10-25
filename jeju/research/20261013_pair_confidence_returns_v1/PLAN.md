# Pair confidence and realized returns — fixed analysis plan

## Question and fixed inputs

For races with verified pair-payout coverage (2025 plus 2026 through 2026-09-19; 1,142 races), compare exact-Top2 QNL and Top3-pair QPL returns for the frozen `jockey_id_candidate` pair, conditional on the saved `jockey_id_candidate_calibrated_probability`. Keep only prediction rows where `selected_jockey_id_candidate == 1`. The confidence value is a calibrated probability that **both horses finish in the Top 3**. It is not the probability that the pair finishes exactly 1st–2nd, so QNL results are stratified by this score without interpreting it as QNL calibration.

Use the already verified, payout-supported per-race return files: QPL from `20261013_pair_qpl_roi_v1/race_returns.csv` and QNL from `20261013_qnl_tla_roi_v1/race_returns.csv`, filtering `selector=jockey_id_candidate` and `pool=QNL` for QNL. Match each payout row to the frozen selected pair and race ID. Retain the verified 1,142-race common cohort; fail rather than silently drop a mismatch. Do not query or write SQLite.

## Boundaries fixed before segment calculations

Disjoint intervals are `[0,0.10)`, `[0.10,0.15)`, `[0.15,0.20)`, `[0.20,0.25)`, `[0.25,0.30)`, `[0.30,0.40)`, `[0.40,0.50)`, and `[0.50,1.00]`. Cumulative selections are `p >= 0.10`, `0.15`, `0.20`, `0.25`, `0.30`, `0.40`, `0.50`, plus the all-races baseline `p >= 0.00`. Apply the same boundaries to full period, 2025, and partial-year 2026.

For every pool/scope/bin or threshold, report selected races, coverage of the 1,142-race pool, unique race days, mean saved confidence, exact-hit count/rate, mean paid dividend among hits, stake, return, net, recovery, and net ROI. Emit zero-count rows with null rates/means. Compare QPL observed hit rate with mean confidence as a descriptive calibration check; do not label QNL as calibrated to this probability.

Stake one QPL ticket and one QNL ticket at KRW 10,000 per selected race. For QPL, use the verified final paid QPL dividend. For QNL, scale the verified KRW 6,000 ticket dividend to KRW 10,000 using exact decimal arithmetic. Return is zero for a miss; ROI is `(return - stake) / stake`.

For uncertainty, reuse the pinned 2,000 × 269 saved date-bootstrap schedule. Map its date indices to the original sorted 2024–2026 date cohort, resample day clusters with replacement, then apply each fixed 2025/2026 and confidence mask. Report percentile 95% intervals for ROI and hit rate; drop and count draws with no selected race instead of imputing zero. Do not regenerate the schedule.

## Scope and interpretation limits

This is a retrospective, repeatedly inspected development period. The confidence intervals describe date-cluster resampling uncertainty within this historical sample; they are not future validation. Do not select or recommend a threshold based on realized returns, imply future profitability, fit or recalibrate a model, or change shared models/DB/other studies. Discuss sparse high-confidence bins and payout/odds effects.

## Reproduction

Run `python -B analyze.py` from this directory using repository `.venv`. `analyze.py` checks the input SHA-256 pins, pair/race alignment, cohort coverage, and bootstrap shape/hash before writing outputs.
