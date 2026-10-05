# Independent corrected-model review

## Verdict

No material defect was found in the corrected v4 model, its development-only selection, its stored historical predictions, or its selected future export. The invalid first training attempt remains segregated under `invalid_attempt_01` and was not used.

The independent selection reproduces the frozen decision exactly: retain v3 `top3_allcore` for A and select `top3_growth_strength` for B and C. Only 2021–2024 full-card results enter this decision. The selection file states that reference metrics were absent when it was frozen, and the separate reference runner refuses to start without that frozen file or if 2025+ candidate metrics already exist.

The already-exposed 2025–2026 reference period does not change selection. Relative to v3, the selected v4 candidate records 235 versus 223 B exact hits (+12), and 54 versus 55 C exact hits (-1), over 3,044 races. C log loss is slightly lower (`5.981899` versus `5.982439`) despite the one-hit decline. These descriptive reference results must not trigger post-hoc reselection.

## Feature contracts

The frozen runner, amended protocol, and protocol lock match every hash in `protocol_frozen_hashes.json`.

The persisted feature table contains exactly 410,168 rows, has no duplicate `(race_id, hr_no)` keys, and matches the v3 source card keys exactly. Independent checks and five tests confirm:

- historical finishes come from canonical `target_finish_order`; changes to the preserved raw source rank do not affect features;
- recent-versus-career uses a cumulative career mean beyond the five-race trend deque;
- current-card opponent ELO excludes the focal horse, including under an extreme focal-ELO test;
- historical opponent ELO stores prior cards' leave-one-out opponent means;
- date-batched updates prevent any same-date result from entering another same-date feature;
- age and age-experience formulas are exact;
- a targetless future card can be appended to historical context, enriched, mapped through the saved fit-only categorical vocabulary, and scored finitely.

The full-table opponent-delta comparison differs by at most `9.09e-13` ELO because DuckDB and pandas sum in a different order. This is floating-point roundoff under the `1e-12` audit tolerance. The initially over-strict equality result is retained in `superseded_initial_audit.json`.

First- and last-fold metadata contain all six new numeric features, complete categorical vocabularies learned from their fit windows only, correct strictly prior training cutoffs, and finite evaluation scores when unseen values map to `__MISSING_OR_UNSEEN__`.

## Stored-output verification

All stored overall and Seoul/Busan candidate metrics for six years independently reaggregate from the race-level Parquets with a maximum error of `1.11e-16`. Independent pooling and venue/year gates reproduce every frozen selection value.

A complete 2026 model replay covers 1,286 races and all three venues, including Yeongcheon:

- 13,802 A probabilities match exactly;
- 25,720 B/C top-10 probabilities and keys match exactly;
- the maximum joint-probability invariant error is `1.78e-15`.

For unseen venues, the frozen evaluation and inference contract deliberately uses win temperature `1.0`, as defined by both `evaluate_candidate` and `frozen_win_temperature`. An initial review replay incorrectly used the stored `GLOBAL` temperature; its superseded result is retained in `superseded_initial_replay.json`.

The future export contains 294 rows across 27 races and matches the frozen prepared card's keys, dates, feature cutoffs, and source SHA-256. Same-date history-dependent features remain constant for repeated horse/date pairs. Because A remains the v3 model, its probability array is bit-exact against the corrected v3 r2 export. B and C are explicitly labeled `top3_growth_strength`.

## Audit notes

The main training runner's `splits.csv` records the development folds through 2024; 2025–2026 were intentionally run later by the separate reference runner after selection froze. Their saved model metadata and independently replayed outputs establish their actual fit/evaluation contracts.

The two `invalid_future_export_attempt_*` directories are excluded from every check and from the valid destination. Each now contains an `INVALID.md` explaining its export failure and pointing to the corrected destination, so the preserved attempts cannot be mistaken for valid exports.

Reproduction commands:

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q \
  data/research/thoroughbred_followup_20260918_v4/review_model/test_strict_feature_contract.py \
  data/research/thoroughbred_followup_20260918_v4/review_model/test_review_contracts.py -p no:cacheprovider
.venv/bin/python data/research/thoroughbred_followup_20260918_v4/review_model/audit_model_outputs.py
.venv/bin/python data/research/thoroughbred_followup_20260918_v4/review_model/replay_2026_predictions.py
.venv/bin/python data/research/thoroughbred_followup_20260918_v4/review_model/audit_future_export.py
```
