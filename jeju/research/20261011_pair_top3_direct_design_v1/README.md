# Direct pair-in-Top3 learner: design and source audit

Status: independent design/source review and publication-preparation record, 2026-10-11. The saved sources were inspected read-only. The authorized fit and evaluation are recorded in A; C independently reproduced them. This folder is not a second execution contract. If plans differ, follow `jeju/research/20261011_pair_top3_direct_v1/PLAN.md` and `INPUT_CONTRACT.md`.

This study proposes one direct binary model for the event that a specified unordered pair of runners both finish in the Top3. It retains the saved `F1_STYLE6` runner score as a fixed offset, adds one small symmetric pair correction, and does not construct ticket or full joint probabilities.

- [Source audit](SOURCE_AUDIT.md) records the available OOS score paths, joins, time boundaries, and source limits.
- [Plan](PLAN.md) freezes the pair target, feature basis, loss, calibration, comparisons, and evaluations.
- [Input contract](INPUT_CONTRACT.md) pins source hashes, keys, and fail-closed checks.
- [Machine-readable source manifest](source_manifest.json) records the immutable source identities.

The analysis cohort repeats historical race dates used by prior research. The result remains retrospective development work, not independent future validation or an operating-model promotion. The evaluation did not support adopting the direct pair model; the saved F1_STYLE6 runner evaluation and operating model remain the reference.
