# S40 vs G47 gate–pace interaction experiment

Status: implementation and synthetic checks only. The candidate is not fit and no candidate scores, probabilities, or outcome metrics have been computed. The source contract and one-run supervisor approval are required before those steps.

## Fixed comparison

The single candidate G47 is the sealed S40 40-feature model matrix plus exactly these seven numeric columns, in this order:

1. `pace_own_early_tendency`
2. `pace_own_label_support_fraction_max10`
3. `pace_inner_interaction`
4. `pace_outer_interaction`
5. `pace_adjacent_inner_interaction`
6. `pace_adjacent_outer_interaction`
7. `pace_opponent_observed_fraction`

For runner *i*, the audit summary provides the first-pack label mean `m_i` and valid-observation count `n_i` from the most recent at most ten actual starts in the inclusive race-date window `[T−730, T−2]`. `q_i=(m_i*n_i+1)/(n_i+3)`; when `n_i=0`, `m_i` remains NULL and `q_i=1/3`. Support is `n_i/10`, not the share of the slots actually present. All four opponent sums use only the exact S40 target roster, exclude the subject runner, and use the original uncompressed horse numbers. Adjacent means integer number difference exactly one. `pace_opponent_observed_fraction` is the share of other target runners with `n_j>0`.

The audit owner creates the thin feature table. This consumer validates its hash-pinned source contract, one-to-one target keys, distance and roster identity, slot dates against the fixed T−730/T−2 window, q/support, peer lineage, and every feature formula. It returns only the seven contracted model inputs. Current-race labels, outcomes, actual pace, and market inputs are prohibited. Historical source publication times are unverified, so this retrospective comparison does not claim operational pre-race availability.

## Training and evaluation

Reuse the existing S40 model recipe unchanged: annual vintages 2024–2026; initial training 2017 through Y−3; early stopping on Y−2; refit through Y−2 using the selected iteration count; calibration on Y−1; evaluation on Y. Keep the S40 category vocabulary, binary Top3 LightGBM objective, `1/field_n` sample weights, seed 20261008, learning rate 0.04, 15 leaves, minimum leaf size 100, L2 5, deterministic column-wise execution, four threads, 800 rounds and patience 25. G47 uses six training calls, saves three final models, and fits three PL temperatures. S40 models, OOS scores, temperatures, and evaluation contract are reused with zero S refits/recalibrations.

Use the existing full-field sequential Plackett–Luce joint distribution and the same seven-wager proper-loss, selection, calibration-bin, fixed-denominator, and 2,000-draw paired date-bootstrap outputs as S40. Keep output schemas compatible with S40 and compare the S replay against its frozen results before interpreting G−S. The sole gate is frozen in `supervisor/DESIGN_CONTRACT.md`.

## Execution boundary

`gate_pace_pipeline.py --synthetic-checks` reads no source rows and performs no fit, candidate probability construction, or outcome evaluation. `--source-preflight` is run once after the audit artifact and contract are final and performs no candidate fit or scoring. `--run` requires the code/input/hash-bound `supervisor/GATE_PACE_EXECUTION_APPROVAL.json` authorizing exactly one run. Fit metadata and the complete calibration/evaluation raw-score ledger are checkpointed before evaluation, so evaluator recovery cannot refit. Every write is exclusive-created beneath `experiment/`; path, per-write, projected and final byte checks enforce the 40,000,000-byte study cap. The audit input is capped at 8,000,000 bytes. No existing source table, database, model, or study is copied or modified.
