# Three-target implementation review

Review date: 2026-09-18. Scope is a read-only review of `code/targets_core.py`, its unit tests, the frozen `protocol.json`, and the current context-feature build path. No model, source data, or saved prediction artifact was changed.

## Current result

`test_targets.py` and `test_context_features.py` pass: 12 tests passed. An additional exhaustive check over 21,824 rank/tie patterns for three through seven runners passed: every compatible order has nondecreasing official rank, maps to a compatible set, and produces A label mass exactly three. `targets_core.py` has no current blocker in its coherent ordered-triple construction: every B set and A inclusion value is summed from the normalized C ordered-triple distribution; set-energy candidates condition their within-set order on Plackett-Luce; position and rank candidates normalize over distinct ordered triples. The tests cover a tied third-place boundary, fractional A labels, compatible B/C credit, numerical extremes, train-only category vocabulary, unseen-category mapping, and bundle reload parity.

The protocol’s selection boundary is also clear: only 2021–2024 can select candidates. 2025–2026 are already-exposed reference years and cannot be retuned or described as new independent holdout data.

After the completed training run, the independent artifact verifier wrote `verification.json`: all 3,176 checks passed, with no failures. It verified the protocol lock, annual split dates, FIT-only category vocabularies, calibration support, A/B/C prediction keys and probability laws, dead-heat labels, frozen selection, baseline references, and deterministic saved-model reload/score replays. The prepared context also passed the direct official-finish precondition: each of its 36,748 races has at least three rank-1-to-3 horses (minimum 3, maximum 4; none below 3).

## Run-contract review

`run_targets.py` now implements the annual split, FIT-only bundle vocabulary, TUNE-only iteration choice, CAL-only target/venue temperature fitting, 2021–2024-only selection freeze, and separate full-card/final-starter normalization. The rank-zero guard was reviewed with a focused smoke check: rank 0 receives neither an official Top-3 event label nor ranking relevance.

Before results are accepted, the run/verification pair must demonstrate:

1. FIT-only category vocabularies for every model and fold; TUNE/CAL/EVAL unseen values map to the saved missing category.
2. Fit through the preceding June, tuning only in July–September, calibration only in October–December, and candidate selection only on 2021–2024.
3. A/B/C probability sums and exact C→B→A marginalization for every saved prediction race.
4. Compatible-set and compatible-order target construction for every official tie, including fractional A only at the third-place boundary.
5. Saved-bundle reload and raw-score replay on a fixed deterministic sample, without refitting.

## Resolved reproduction check

The initially observed missing `tempfile` import in `code/context_features.py` was corrected by the feature owner. The owner reran the fresh complete feature build successfully for 410,168 rows, and this review independently reran the seven context tests successfully. It is no longer a blocker.

`code/verify_targets.py` was invoked only after the final training run completed. The resulting `verification.json` passed all 3,176 checks. It covers saved artifact presence and protocol lock, split dates, exact FIT vocabularies, temperature schema/bounds, baseline hashes, saved-model reload and probability replay, every A key/target/probability race mass, B/C top-ten coverage, frozen-selection recomputation, and the official top-three finisher precondition.

## Inference, reproduction, and report review

`infer_targets.py` rejects result/label fields unless the caller explicitly marks an already-observed historical replay. Its non-replay output is labelled `prepared_card_inference_timing_unverified`, rather than prospective or live. The report also calls 2025–2026 already-observed historical reference, preserves target-specific calibration, and does not claim a future result.

`reproduce_targets.py` rebuilds in a new sibling research directory and reruns feature, model, verification, preservation, report, and manifest stages. Its audit copy list includes `operational_steward_report_coverage.csv` and the other availability coverage CSVs referenced by `DATA_AVAILABILITY.md`.

## Frozen future-card export review

`export_forecast.py` reads only the source card identity fields and the already-produced inference files; it has no source-DB/result query. It requires every card to remain future-dated in Korea and carries the 2026-09-17 frozen-card, unrefreshed-final-starter, and inference-timing-unverified limitations into its metadata and readable export. It does not alter historical candidate selection or evaluation.

The export hardening follow-up is resolved: it now asserts prediction `inference_status`, requires exact source/A `(race_id, hr_no)` and race-date equality, verifies each target’s frozen selected candidate, and refuses existing CSV/JSON siblings as well as the Markdown output. These checks make malformed or wrongly labelled inference artifacts fail before a future-card report is written.
