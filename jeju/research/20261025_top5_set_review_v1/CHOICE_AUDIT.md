# Independent label-free Top-5 choice audit

Status: **PASS.** The selection ledger was hash-locked before this independent exhaustive replay. This audit reads no finishing labels or outcome-derived columns. The separate, root-approved report stage has since been independently recomputed and reconciled; see `INDEPENDENT_OUTCOME_AUDIT.json` and `OUTCOME_RECONCILIATION.json`.

## Locked artifacts

- Selector code SHA-256: `9bbd0556236dde13697f62dec70e7a81928bab1f57de0ab267008b429e94c4e2`.
- Selections SHA-256: `1f3d40769939b82afe4f6278f92bf5f13af85329355a4a03ddc036391d55322d`.
- Selection receipt SHA-256: `28711efecfece9da8dbf79639f2dd55223335cc67453273aa46a7efe6a55f2e6`.
- Root Q-reconstruction receipt SHA-256: `f50e75f1815793fd4874bc36f38f80d64c4fd0192da2e89fb144b9ae7bae627a`.
- Compact machine-readable result: `INDEPENDENT_CHOICE_AUDIT.json`.

## Independent checks

`verify_choices.py` does not import the selector or model implementation. It checks the locked receipts and source hashes, loads only runner identity/score/metadata fields plus race/triple/probability fields, and reconstructs both probability arms from the saved unordered triple probabilities. For each of 1,779 races, it enumerates every `C(N,5)` set, sums its ten triple probabilities with canonical tuple order and `math.fsum`, applies the fixed `1e-12` tolerance and overlap/lexicographic tie rule, and compares the result and q values with the locked ledger.

All 1,779 candidate choices matched the independent exhaustive optimizer. All 1,779 matched-unary negative-control choices equaled the raw F1_STYLE6 score top-5. The primary cohort count was 1,503. Candidate choices differed from baseline in 386 races. The largest optimal-tie pool contained 126 sets. The largest q gap between the selected set and the exact maximum was `2.7755575615628914e-17`; selected-q replay had maximum absolute difference `0.0`. Reversing probability dictionary insertion order preserved selected-set q values.

The root Q receipt independently reports 201,404 candidate and 201,404 matched-baseline triples checked, exact maximum probability reconstruction difference `0.0` for both arms, maximum race-mass error `6.66e-16`, temporal-gap checks passing, zero new fits, and no outcome labels read. The independent outcome receipt and reconciliation verify the later outcome stage separately.

## Limitations

The historical 2024–2026 period is a repeatedly examined development period, not a fresh holdout. During an earlier schema inspection, the reviewer saw three first-race rows containing `y`, `log_loss`, and `brier`; those values were not aggregated or used to define or alter the rule. The later Q reconstruction, selector, and this exhaustive choice replay did not read labels. Do not describe all reviewers as label-blind.
