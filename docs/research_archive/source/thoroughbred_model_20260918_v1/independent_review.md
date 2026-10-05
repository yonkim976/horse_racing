# Independent implementation review

Status: **pass for code and artifact review; final manifest pending deliberate finalization**. This review covers the implementation and completed offline artifacts against the supplied experiment specification. It did not modify source or model code.

The executable feature allowlist contains 38 inputs: 13 categorical and 25 numeric. Categorical vocabularies are fit only from each training frame; unknown IDs and other unseen values use the reserved missing/unknown category. The primary training labels use fractional `target_win_mass`, so a dead heat contributes unit mass split among official winners. Training and evaluation reject any race whose target mass is not one.

The earlier material implementation findings have been resolved:

| ID | Prior issue | Verified resolution |
| --- | --- | --- |
| IR-001 | `arg_max(venue_code, race_no)` invented a previous venue for horse/date records spanning multiple venues. | Ambiguous confirmed horse/date venue histories now yield null previous venue. The source conflict remains in the validation ledger. |
| IR-002 | Nonconfirmed races could affect historical aggregate features. | All three history populations join the race table and require `official_result_state='confirmed'`. Preparation reports 251 excluded races and 2,872 excluded entry rows. |
| IR-003 | Full-card inference did not validate `field_size_full_card`. | Inference rejects a declared card size that differs from the supplied race group. A three-entry subset marked as a four-entry card was rejected in a focused smoke test. |
| IR-004 | Generic inference could not reproduce the frozen route and partial-shared temperature. | `infer_selected.py` loads the frozen route and calibration temperatures. A mixed Seoul/Busan smoke test applied the correct route/temperature and retained probability sum one per race. |
| IR-005 | `feature_cutoff` was emitted as a contract label rather than a traceable cutoff. | Inference validates an optional prepared cutoff and exports race-date midnight in the same convention as evaluation output. |

The local code test suite passed: `14 passed`. Preparation passed all 26 checks for 410,168 rows and 36,748 races. Post-training artifact validation passed all 540 checks across 28 saved bundles and 22 validation/test prediction files. This covers training-only category vocabularies, absence of test-period fitting, probability/rank/key invariants, frozen selected-route replay, and partial-card rejection. The 82 probability-sum checks passed with a maximum absolute error of `4.44e-16`.

Selection was frozen at `2026-09-17T18:08:42Z`, before test evaluation began at `18:12:39Z`. The frozen route selected `partial_shared` for Seoul and Busan and `integrated` for Yeongcheon. On the full-card test, selected-route log loss was `2.082660` against uniform `2.371257`; Brier was `0.842049` against `0.905399`. These are offline results and do not authorize an operational promotion.

The preservation check passed for every pre-existing substantive protected file and all existing model/database hashes. It separately records a Finder `.DS_Store` change plus four outside-run additions whose authorship cannot be inferred from the snapshot. The strict recalculation differs from the unified source history for 23,988 target rows because nonconfirmed history is now excluded; this remains documented in `data_validation.json`.

`manifest.json` is intentionally generated after this review so it can hash this final review too. Parent finalization must run and verify that SHA-256 manifest; this is the remaining procedural step, not a model or evaluation blocker.

The full-card cohort is still the supplied result-card population. Completeness of historical declared cards and the publication time of cancellations are not proven, so final-starter evaluation must remain labelled as a retrospective conditional cohort.
