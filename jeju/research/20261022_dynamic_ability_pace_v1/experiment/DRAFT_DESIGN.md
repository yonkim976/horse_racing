# Dynamic ability + pace study — draft design

> **SUPERSEDED (2026-10-22):** This exploratory proposal is not the active experiment specification. Use the frozen [`../supervisor/DESIGN_CONTRACT.md`](../supervisor/DESIGN_CONTRACT.md) for implementation, review, and any future approved execution. The proposal below is retained only as design history; its formulas, fits, feature lists, and gates must not be used.

**Status: design only. No model has been fitted and no candidate probabilities or evaluation results have been computed.** This draft is for supervisor and input-audit review. Any fitting requires a separate approval bound to final input and code hashes.

## Question and scope

Can a small, time-causal model built from Jeju race history alone provide a better ordered Top-3 joint distribution than the saved F1_STYLE6 raw-score reference, and does adding pre-race forecasts of early position and late recovery improve that distribution further? This is a new scorer; F1_STYLE6 scores and fitted coefficients are not model inputs.

The two planned comparisons are fixed: (A) a four-state, history-only scorer against reference R, and (B) a three-coefficient phase-informed residual added to frozen A. B is a conditional-score correction in the same full-field Plackett–Luce (PL) distribution. It is **not** a shared latent-pace mixture, a race simulator, or a claim that post-race pack position causally changes finishing order. The phase forecasts are predictive summaries of likely race roles.

The 2024–2026-09-19 evaluation cohort has already been used in several studies. Its 1,779 races (1,743 PLC-eligible races; 36 actual-seven-runner races are PLC-quarantined because the sales-opening count is unavailable) are a repeated development evaluation, not a fresh holdout. Future untouched dates would be needed for a confirmatory claim.

## Frozen temporal protocol

For a target year `c`, generate predictions using outcome labels dated no later than `c−2`, fit any scalar calibration on year `c−1`, then predict `c`. The same rule applies to A, both phase heads, and R. For the final evaluation year `Y ∈ {2024, 2025, 2026}`, model parameters are trained on years `≤Y−2`, calibration uses `Y−1`, and evaluation uses `Y` through 2026-09-19. The final `Y−1` calibration data do not enter the outcome-model fit.

For fitting B in an evaluation fold `Y`, its training rows are only annual OOS predictions from target years `c ≤ Y−2`. Each such row's A score and both phase probabilities must themselves have been generated with that row's own `≤c−2 / c−1 / c` split. In-sample A scores, same-race phase observations, and future labels are forbidden in the B design matrix. At evaluation, A is frozen before B is fitted; B does not update A's four state coefficients.

Saved F1_STYLE6 raw scores are a read-only comparator R, never a feature. For each evaluation year, fit one bounded scalar temperature on the preceding year's raw-OOS reference scores by full-field ordered-Top3 race-equal NLL, `T_R ∈ [0.35, 4.0]`. Do not use provider-calibrated probabilities or a temperature fitted on the evaluation year. The earlier COMMON temperature `1.1837152381349905` may be shown only as a supplemental historical reference; it does not replace the fold-specific R calibration or serve as the primary control.

All historical features must obey the existing T−2 cutoff and source-quality rules. The input audit owns deterministic observations and their provenance; this experiment owns all fitted state, coefficients, phase heads, and calibration parameters. Exact coverage, labels, row keys, cutoff implementation, and hashes remain pending the audit's final manifest.

## Candidate A: shrunk historical ability state

For each runner and prediction date `t`, form four deterministic summaries from that horse's valid starts strictly before `t−2` days. Weight a past start `q` by `w_q = 2^(−days(t,q)/365)` (one-year half-life). Each state is `H=(κμ+Σ_q w_q x_q)/(κ+Σ_q w_q)`. A missing or invalid label contributes neither numerator nor denominator. Keep support counts with the state features; no missing value is silently changed into an adverse or neutral event.

1. **Global ability `A`:** transform a unique official finish rank `r_q` among `N_q` starters to `z_q = Φ⁻¹(1−(r_q−0.5)/N_q)`, so higher is better, then use the recency-weighted mean shrunk toward 0 with prior strength `κ_A=3`.
2. **Exact-distance deviation `D`:** for the exact distance only, average `z_q − A_h(q)` with the same decay and shrink toward 0 with `κ_D=5`. `A_h(q)` is the causal global state available immediately before historical start `q`; compute it chronologically. Do not pool raw sectional seconds across distances.
3. **Early-role history `E`:** recency-weighted rate, shrunk with `κ_E=5`, of the audited event “S1F first group.”
4. **Late-recovery history `C`:** recency-weighted rate, shrunk with `κ_C=5`, of the audited `last200_recovery` event from the existing deterministic phase contract. Do not infer an individual order inside a pack.

The shrinkage prior means for A/D are 0. For E/C, use race-equal prevalences estimated only from the current fold's training labels and save those values with the fit receipt. For a horse without history, use the prior mean and retain a zero-support indicator for audit; the four-coefficient scorer below has no extra missingness coefficients.

Within each training fold, standardize the four states using training-starter means and standard deviations only; a constant feature is set to zero and recorded. Fit four slopes `β_A, β_D, β_E, β_C` by minimizing race-equal full-field ordered-Top3 PL NLL plus fixed ridge penalty `0.5 * Σβ²` on standardized features. There is no race intercept because it cancels from within-race PL. The linear utility is `s_i^A = β_A A_i + β_D D_i + β_E E_i + β_C C_i`. This is a four-slope, low-capacity scorer, not a posterior distribution over latent ability. It does not propagate state uncertainty in v1.

Use full-field sequential PL for each exact ordered top-three outcome. For distinct runners `i,j,k`:

`Q(i,j,k) = exp(s_i)/Σ_all exp(s) × exp(s_j)/Σ_{all except i} exp(s) × exp(s_k)/Σ_{all except i,j} exp(s)`.

Every remaining starter stays in the second- and third-place denominator; do not normalize only within the realized top-three set. Calibrate the fold's A raw utilities using one scalar `T_A ∈ [0.35,4.0]` fitted on the preceding year by race-equal joint Top-3 NLL, then use `s_i^A/T_A` for probability evaluation. The same rule is applied separately to R. Temperature optimization uses a deterministic bounded optimizer, records the objective at both bounds and the optimum, and stops on non-finite values.

## Candidate B: OOS phase-informed conditional residual

Use exactly two pre-race phase probabilities: (1) probability the runner is in the S1F first group, and (2) probability of the audited `last200_recovery` event (G1F-to-finish normalized rank improvement of at least two places). These are not the current race's realized phase labels. Each ridge-logistic head uses exactly the four A history states, `log(1+field_size)`, and seven one-hot exact-distance indicators (the eighth distance is the reference): 12 slopes plus an intercept per target. No saved F1 score or post-start measurement enters a head. Standardize continuous predictors on each training fold, use ridge `λ=1` on slopes with an unpenalized intercept, and calibrate each head with a single bounded logit temperature on year `c−1` race-equal binary log loss. If label/source support is inadequate or a target's fold labels are not valid, fail closed rather than synthesize labels.

For runner `i` in race `r`, let `p^L_i` and `p^C_i` be the two calibrated OOS phase forecasts. Center each within its race: `l_i=p^L_i−mean_j(p^L_j)` and `c_i=p^C_i−mean_j(p^C_j)`. Define field pressure as `g_r=(mean_i(p^L_i)−μ_L,train)/σ_L,train`, where the mean and standard deviation are estimated across B-training races only; set `g_r=0` and record it if the training standard deviation is zero. The residual features are fixed as `(l_i, c_i, l_i*g_r)`. Fit exactly three coefficients `γ` with fixed ridge `λ=1` by minimizing race-equal full-field ordered-Top3 PL NLL on the strictly OOS B-training rows. No other phase targets, interactions, variable selection, or tuning are planned.

The A log-worth used by B is normalized across vintages with the corresponding preceding-year `T_A(c)`: `u_i^A=s_i^A/T_A(c)`. For each vintage, learn no rescaling from its target-year outcomes. The B raw utility is `u_i^B=u_i^A+γᵀφ_i`. For evaluation year `Y`, fit `γ` on OOS rows `c≤Y−2`; calibrate B's `T_B(Y) ∈ [0.35,4.0]` on the OOS B scores for year `Y−1`, generated by the `c=Y−1` annual folds (A/phase model labels `≤Y−3`, their calibrations `Y−2`) with that frozen `γ`, using only `Y−1` ordered-Top3 outcomes for the joint-NLL temperature fit. Evaluate on OOS `c=Y` rows, whose A/phase models use labels `≤Y−2` and calibrations `Y−1`. This keeps B calibration features OOS and separates it from the phase-head temperature fit. Save all scales so the phase residual cannot silently exploit a fold-to-fold score-scale shift.

This modest residual tests whether expected early pressure and late-recovery propensity add signal conditional on A. It does not integrate over a shared pace scenario. A scenario-mixture model would require a separately specified latent field state and joint normalization; that extra complexity is out of scope unless this residual first shows stable out-of-time value.

## Fold and fit inventory

Annual OOS vintages `c=2019,…,2026` require at most eight A fits and temperatures, 16 phase-head fits and 16 phase-head scalar calibrations. The three final evaluation folds add three B residual fits, three B temperatures, and three R temperatures; the annual `c=Y` A/phase fits and temperatures are already included in the eight-vintage count. Exact fit counts may be lower only if a source audit rejects a fold; do not bridge a rejected year by using a later year.

Fit counts and sample availability are design costs, not promises of statistical power. Phase labels are substantially sparser than finish ranks, so minimum positive/negative event counts per training and calibration year must be audited before any approval. If a required fold is under-supported, stop and ask for a revised design instead of dropping the fold after seeing results.

## Evaluation, decision gates, and reporting

Use the fixed prior race/pool eligibility contract in `../rules_contract/` after the rules owner completes its manifest. In particular, keep the 36 actual-seven-runner PLC races out of PLC denominators because sales-opening count is unknown; preserve the 1,779-race denominators for the other six pools and the 1,743 PLC denominator. Do not infer historical pool availability or prices from this model evaluation.

Primary A comparison: A versus fold-calibrated R on exact ordered TRI events. Draft A gate is TRI NLL difference upper 95% bound `<0` and TRI sum-Brier point difference `≤0` versus R. Primary B comparison: B versus A on the same races. Draft gate for B is TRI NLL difference upper 95% bound `<0` and TRI sum-Brier point difference `≤0` versus A. Draft protection gate is WIN categorical NLL and Brier point differences `≤0` versus R; this is a point-estimate screen, not a statistical noninferiority claim. Since R may be materially different from A, also report WIN changes versus A without substituting that comparison into the protection gate. Gate passage would support only a research candidate on a reused development evaluation, never operational adoption.

For each of the seven pools (WIN, QNL, EXA, TLA, TRI, PLC, QPL), report the contract-defined proper loss: categorical NLL and sum-Brier for single-horse/pair/triple outcome distributions, and race-averaged ticket-binary log loss/Brier for PLC and QPL. Also report fixed-bin, pooled event-count-weighted reliability separately from race-equal primary losses; event, runner, and race denominators by year; and any quarantine reasons. State clearly that a pooled reliability curve is event-count weighted, not race weighted.

Apply the same fixed max-probability one-ticket rule to all arms: probabilities are left unmodified; among tickets within absolute `1e−12` of the maximum, choose the lexicographically smallest horse-number tuple and record that selected ticket's actual probability. Report selected-ticket key changes and hit rates by pool. For a positive hit-rate baseline, report relative change `(candidate/base−1)` as well as percentage-point difference; when the baseline hit count is zero, relative change is undefined. Also report win-axis/top-three runner hit rates. A relative improvement of 10% is a user-interest threshold to measure, not a guaranteed result or automatic gate; disclose absolute counts and paired uncertainty. Do not infer market returns because pre-race odds/pool prices are unavailable.

For all seven pools, report annual losses/calibration, plus total-period results, even if some worsen. A TRI gain alone must not be described as seven-pool superiority or complete calibration.

## Synthetic checks and implementation limits

Before any approval, synthetic-only checks must prove: full-field `N`, `N−1`, `N−2` PL denominators; exact ordered-Top3 probability sums to one for small fields; removal of one runner changes later denominators; T−2 excludes same-race and intervening labels; an unknown state target is omitted from both numerator and support; fold `c` cannot see labels after `c−2` except scalar calibration labels in `c−1`; B rows are OOS predictions only; score-scale normalization uses only the matching prior calibration; phase-head calibration cannot access target outcomes; fixed ticket ties use actual selected-ticket p and do not change the forecast distribution; legal event scope and seven-pool quarantine follow the rules contract; and fail-closed behavior on ties, invalid finish ranks, and sparse phase labels.

No full race-by-race triple table is retained. Stream PL terms and pool probabilities race by race. Save only compressed fold receipts/coefficients, hashes and provenance, per-race/per-pool evaluation ledgers, the compact selected-ticket and runner-axis ledgers needed to reproduce hit rates, calibration-bin aggregates, and quarantine counts. Reference previous read-only artifacts by path and SHA; do not copy old loss ledgers, raw scores, DB tables, or full Q. Target new permanent outputs below 100 MB.

## Dependencies requiring review before implementation

- Final audited definition, timestamp cutoff, coverage, and stable source hashes for each historical feature and phase event.
- Whether finish-rank inputs for all proposed folds have unique official ranks and sufficient history before 2019; tie, disqualification, cancellation, DNF, and missing-rank quarantine must match the existing outcome contract.
- Training-only standardization and prevalence calculation; exact regularized objective and optimizer receipt.
- Phase-head context feature allowlist and minimum positive/negative support thresholds, fixed before fitting.
- Whether the previously frozen bootstrap schedule is appropriate and can be referenced read-only; otherwise supervisor must provide a new fixed schedule before approval.
- Rules contract final hash and its compatibility with this study's event labels and denominators.

Until those items and the input audit are resolved, this document is a proposal rather than an executable authorization. No model fitting, calibration fitting, real-score generation, or evaluation has been run for this study.
