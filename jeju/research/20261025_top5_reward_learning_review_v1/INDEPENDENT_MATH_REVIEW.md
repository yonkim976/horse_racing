# Independent math review: reward based Top5 learner

## Scope and current gate

The mathematical derivation and synthetic check were completed before reading project data. The synthetic-only check itself did not read the feature parquet, labels, database, new study code, fitted coefficients, choices, or evaluation outcomes. Subsequent stages reviewed the corrected fit implementation and receipts, independently replayed the three approved training folds, reproduced all locked choices without outcomes, then opened evaluation labels only after root approval to audit the final result. The staged evidence is recorded below and in the linked receipts.

## Objective and gradient

For race `r`, let `A_r` contain every exact five-runner set, `z_i` be the fixed within-race population-standardized raw F1_STYLE6 score, and `x_i` be the 11 runner inputs standardized with that fold's training-runner scaler. The additive set energy is

`E_r(S; β) = Σ(i∈S) z_i + βᵀ Σ(i∈S) x_i`.

The policy is the Gibbs distribution over all such five-sets,

`π_β(S|r) = exp(E_r(S;β)) / Σ(T∈A_r) exp(E_r(T;β))`.

Given exactly three actual Top3 labels, define `G_r = {S ∈ A_r : actual Top3 ⊆ S}`. Its cardinality must be `C(N−3, 2)`. The action reward is `+1` for `S∈G_r` and `−1` otherwise. Thus the exact expected reward under the stochastic Gibbs policy is

`R̄_r(β) = Σ_S π_β(S|r) R_r(S) = 2P_r(β) − 1`,

where `P_r(β) = Σ_(S∈G_r) π_β(S|r)`. The fit minimizes

`J(β) = mean_r(1 − 2P_r(β)) + (λ/2)||β||²`, with fixed `λ=1`.

Writing `φ_r(S)=Σ_(i∈S)x_i`, differentiation gives `∇P_r=P_r(E_good[φ]−E_all[φ])`. Therefore the per-race data gradient is `2P_r(E_all[φ]−E_good[φ])`, and the objective gradient is

`∇J(β) = mean_r[2P_r(E_all[φ]−E_good[φ])] + λβ`.

This agrees with the task's formula. The probabilities and expectations are over the entire enumerated action space; no sampling approximation is needed. `P_r` is not a calibrated probability for a real race and does not equal the deterministic `argmax_S E_r(S;β)` selector's empirical success rate. A deterministic argmax output still needs separate evaluation.

## Synthetic control

`check_reward_objective.py` directly enumerates every `C(N,5)` action in two synthetic races (`N=7,8`), verifies the positive-set count `C(N−3,2)`, enforces exactly three Top3 labels, computes `Pgood` and the analytic gradient, compares it with central finite differences at `ε=1e−6`, and checks `E[R]=2Pgood−1` against the direct sum of the enumerated signed rewards. The observed maximum absolute gradient discrepancy was `1.1014944512055536e−10`; the largest reward-identity discrepancy was `2.220446049250313e−16`. Both `Pgood` values were in `[0,1]`; enumerated rewards had exactly the support `{-1,+1}`. The script reported 77 total actions and 16 correct actions across the synthetic races.

## Interpretation and completed audit stages

The expected-reward objective is not the direct-study partial-event NLL: it maximizes the softmax mass of correct sets linearly rather than minimizing its negative log. It is a stochastic-policy surrogate with a known gap to deterministic deployment. Training uses complete-information action labels derived from the observed finish, and the three expanding fold fits reuse historical years. It is not PPO, a learned language model, or a probability calibration procedure.

The fixed source hashes, OOF provider cutoffs, 11-input feature contract, train-only scaler, label windows and complete-finish/Top3 masks were independently checked against all three fold receipts. The corrected objective and gradient were replayed on the training folds, all 1,779 deterministic choices were independently reproduced without outcome values, and outcome results were opened only after root approval locked the final choices and reporter hash. The result audit reconciled every race and the paired bootstrap intervals. The evidence and limitations are summarized in `README.md` and `README_KO.md`.
