# Independent math and source review: direct exact-five selector

Status: pre-fit design review. No selector was fitted, no new candidate set was selected, and no 2024–2026 evaluation labels or metrics were read or computed in this review. This folder is the only output location owned by this reviewer.

## Scope and source basis

I read `jeju/AGENTS.md`, `jeju/docs/RESTART_PLAN_20260928.md`, `jeju/review_documents/README.md`, the source/plan records in `20261020_axis_selector_v1`, and the first-pass review of the earlier zero-fit Top-5 experiment. The project constraints apply: preserve the current F1_STYLE6 model and its raw scores, use date-ordered OOS score vintages, keep 2024–2026 as repeated historical development data, and make no database, registry, production model, or existing-study edits.

The current model source calls `predict(..., raw_score=True)` when creating F1_STYLE6 score files (`20261010_style_history_ablation_v1/run.py`). Thus the score is an uncalibrated LightGBM margin. The previous source audit records the approved OOS mapping: label year `c` uses raw calibration score from fold `c+1`; evaluation fold `Y` uses its frozen evaluation score. It also records T−2 refit boundaries, the existing feature lineage cutoff, and the fixed paired date-bootstrap schedule. I have not re-read outcome values in those sources.

The fixed-energy convention has a direct precedent: `20261010_joint_relationship_v1/PLAN.md` defines its raw-score reference energy as the sum of the runners' raw margins, fixes the relationship term's temperature at 1 during H1, and excludes same-year calibration temperature from H1. The main proposal instead uses per-race z-scored raw margins (`ddof=0`) before summing them. That is rank-preserving and a sensible way to hold a common per-race reference scale, but it is numerically different from the prior study's native raw-margin sum. Name it as this study's fixed reference-energy transform; do not call it an exact reuse of the old numeric energy or a calibrated event probability.

## Proposed partial-event likelihood

For one race, let `A_r` be all 5-subsets and `G_r` the subsets containing all three actual Top-3 horses. Let `E_r(S)=e0_r(S)+βᵀφ_r(S)`. Then

`L_r(β) = logsumexp_{S∈A_r} E_r(S) − logsumexp_{S∈G_r} E_r(S)`

is exactly `−log P_β(S∈G_r | race)` under the Gibbs distribution `P_β(S|race) ∝ exp(E_r(S))`. The stated gradient is correct:

`∇L_r = E_{S~P_all}[φ_r(S)] − E_{S~P_good}[φ_r(S)] + λβ` after race averaging and regularization.

The Hessian contribution is `Cov_all(φ) − Cov_good(φ) + λI`. The covariance difference need not be positive semidefinite, so this objective is not generally convex. A one-dimensional example makes the issue explicit: give two good sets feature values `+1` and `−1`, one bad set value `0`, and no prior energy. Then `L(β)=log(1+1/(2 cosh β))`; its second derivative at zero is `−1/3` before regularization. A fixed zero initialization and single solver call make the run reproducible; they do not establish a global optimum. If the optimizer fails its predeclared convergence conditions, the result should fail closed without a retry/search.

This likelihood is a coherent direct event-mass learning objective and is preferable to `mean(1−P_good)` for the first single head: it uses all positive sets and does not multiply each race's gradient by `P_good`, which would attenuate signal on races where initial success mass is small. Do not call either objective a calibrated probability for the eventual deterministic choice.

## Important target mismatch

The fitted Gibbs model assigns mass to possible choices; deployment chooses `argmax_S E_r(S)`. Maximizing the total Gibbs mass on `G_r` does not guarantee the single argmax set lies in `G_r`. The deterministic evaluator asks whether that one set contains all three actual Top-3 horses. Therefore the proposed loss is a direct *surrogate* for the requested event, not the same objective and not a Fisher-consistent guarantee for deterministic argmax coverage. Report the distinction plainly, and do not interpret `P_β(G_r)` as the hit probability of the chosen argmax set.

## Feature and scale review of the concrete main plan

The main plan now fixes an additive 11-column feature vector: `log1p(observed_starts)`, `log1p(same_starts)`, `log1p(same_valid_times)`, `mean5_rank_fraction` plus its missing flag, and three style-history means plus `log1p` of their three support counts. Every runner input is standardized on that fold's training runner rows only, then the five standardized rows are summed. The base energy is the sum of per-race z-scored raw OOS margins. The objective uses a race-equal mean and fixed `λ=1`.

The source-only contrast audit in `FEATURE_SUPPORT_IDENTIFIABILITY_AUDIT.json` uses the same unweighted runner-row standardization as the main plan. All 11 features have nonzero within-race contrast and full rank; adding the per-race-z score prior gives rank 12. The score prior is not an exact linear combination of the 11 features. This establishes design support, not label-based coefficient identification. Near-collinearity remains strong: the two same-distance count logs correlate at about 0.99996 and style-support count logs at about 0.9990–0.9997; the smallest/largest centered-design singular-value ratio is about 0.00256. Keep the planned ridge penalty and avoid interpreting individual coefficients as distinct effects.

The paired style support audit confirms the source contract: each count is an integer from 0 to 5, each mean is NULL exactly at count zero and finite at positive count, with no contradictions. Missing-mean imputation to the training mean gives a standardized value of zero; its count log preserves the support level. `mean5_rank_fraction` has its own fixed missing flag. No additional style missing flags are needed for this source.

The sum-vs-mean choice must remain locked. Replacing `φ_sum` with `φ_mean = φ_sum/5` while leaving `λ=1` would require a coefficient 5 times as large to recover the same energies and therefore impose a 25 times larger quadratic penalty on that equivalent fit. This is the scale effect, even though the coefficient itself changes by 5 times.

Because `φ_r(S)` is a sum of runner features, `E_r(S)` decomposes as a sum of one runner utility. `argmax_{|S|=5} E_r(S)` is therefore exactly the five highest runner utilities under the fixed tie rule. The model learns from the all-three positive-set event, but its head has no horse-pair or set interaction term; describe it as an additive learned selector.

## Feature and scale questions to resolve before fit

1. **Raw margin as fixed energy offset.** The base score is an uncalibrated LightGBM raw margin. Inserting `sum(score)` directly into an exponential-family energy fixes its inverse-temperature coefficient at exactly one. Rank order is unchanged if the margin is rescaled, but the Gibbs distribution and gradients are not. OOS score vintages may have different scales. Before locking the plan, either justify this unit from a pre-existing probabilistic contract, or specify a training-only, predeclared scale transform / fit a single score coefficient within the new head. Keep the stored F1_STYLE6 score untouched; this concerns only how the selector consumes it.
2. **Within-race constants.** Any feature that is constant across every 5-set in a race cancels from both log-partitions and has zero event gradient. This includes a set intercept, a fixed cardinality term, race ID effects, and race-only metadata. Such columns are not identified by this objective; remove them from `φ` rather than expecting L2 to create signal.
3. **Redundant set features.** If `φ` includes a score-proportional feature, its coefficient can change the effective total score weight despite the fixed prior; that is a different design, not an inability to adjust it. If the intention is a fixed score reference, omit score from `φ`. Exact linear dependencies or dependencies up to race-wise constants produce the same within-race set-energy differences. Ridge regularization then chooses coefficient allocation through its penalty, not through independent data support. Record the feature-difference rank (or another deterministic identifiability audit) on training inputs only; retain a predeclared minimal basis.
4. **Scaler weighting.** The main plan standardizes runner inputs on training runner rows, with each runner row equally weighted; larger fields therefore contribute N times as much to the scaler as a race with N runners, while the loss gives every race equal weight. This is a valid fixed convention and it is the one checked in the unweighted branch of the training-only audit. Do not estimate scalers from the expanded action table, where a naive row-wise scaler would weight races by `C(N,5)`. Never use evaluation-year statistics. A zero-variance column uses a documented fixed scale and remains zero.
5. **Field-size effect.** With equal energies, the initial Gibbs success mass is `|G_r|/|A_r| = C(N−3,2)/C(N,5) = 10/C(N,3)`, which varies from `10/C(7,3)` to `10/C(12,3)`. State this baseline and verify the fixed feature basis does not accidentally encode outcomes through candidate counts. Keep all eligible races in fit and evaluation as planned; do not filter or rebalance after seeing evaluation results.
6. **Set enumeration.** Generate exact `C(N,5)` sets. The evaluation roster has N=7–12, while the 2019–2025 training source has N=7–13; therefore train-time code must support `C(13,5)=1,287` actions per race. Define `G_r` from exactly the three unique training-label horse IDs, and check every set has five unique roster IDs. Enumerate in deterministic sorted horse-number order. No all-set table is needed as a persistent artifact; stream/hold transient arrays only within the task memory budget.

## Training-only feature support check

`FEATURE_SUPPORT_IDENTIFIABILITY_AUDIT.json` records a feature-only check of the proposed basis on 38,017 runners in 3,783 races from 2019–2025. It read only the named training feature columns and approved raw OOS score columns; no finish-position, `y`, log-loss, Brier, evaluation feature row, fit, candidate choice, or outcome metric was read or produced. Results above use the main plan's unweighted runner-row scaler; the companion race-balanced scaling audit has the same full-rank result and nearly identical correlations.

## Leakage and evaluation guardrails

The reviewed historical OOS contract supports training labels from 2019–2025 for the three expanding fits (2024 uses 2019–2023; 2025 adds 2024; 2026 adds 2025). Raw scores must be joined on `api_record_id`, checked against race and roster keys, and verified to be from the correct next-fold raw calibration source with provider `refit_max ≤ race_date−2 days`. Use only the fixed small feature allowlist and each row's pre-race feature lineage. A same-year-fitted temperature, `p_top3`, rank/outcome columns, favorite/odds, or any post-race field must never enter head training or selection.

Selection/fit code must read explicit Parquet column allowlists and must not load outcome columns and then drop them. Evaluation labels remain unqueried in source audit, selection, and fit. Fit receipts should contain training-year label counts and source hashes but no evaluation hit, coverage, or label aggregates. The report stage can read labels only after selection artifacts and hashes are locked. Hashing source files is not a substitute for checking feature availability or chronology.

The existing evaluation dates and bootstrap schedule are development evidence, not a fresh holdout. Report both primary and all-distance results under the fixed gates, date-cluster interval, fixed thresholds, caught/lost counts, exact misses, and year/field-size strata; do not adapt the model to these results or call the output production-ready.

## Pending review

The concrete plan/source audit are now available; fit and stage code are still pending. Before fit, clarify the optimizer's postcondition for accepted convergence (for example: optimizer success, all values finite, and a predeclared maximum gradient norm). The L-BFGS `gtol` alone does not guarantee that it stopped by the gradient rather than `ftol`. I will review the exact code and source-only receipts before any model fit, then independently check the locked selections and results after the authorized stages.
