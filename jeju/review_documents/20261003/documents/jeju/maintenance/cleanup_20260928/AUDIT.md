# Jeju cleanup audit — 2026-09-28

## Result

The approved cleanup removed **632 exact files totaling 114,267,306 bytes** across four hash-checked allowlists. No directory-wide deletion was used. The production registry still resolves to the same Jeju champion, `HY_R_FORM`, with `ok: true` after cleanup.

| Batch | Scope | Removed |
| --- | --- | ---: |
| Phase 1 | Nonchampion Jeju model weights and cached research outputs | 128 files / 38,473,965 bytes |
| Phase 2 | Jeju-only racefit table payloads and obsolete experiment outputs | 65 files / 71,866,919 bytes |
| Legacy review, batch 1 | Copied archive evidence and obsolete reproduction copies | 256 files / 2,393,255 bytes |
| Legacy review, batch 2 | Obsolete Jeju experiment scripts/tests/modules and superseded root research docs | 183 files / 1,533,167 bytes |

The four deletion receipts have disjoint path lists. Phase 1 began from a 131-file manifest; the three saved transition-holdout baseline tables were explicitly retained. The phase-2 plan was reviewed and approved by the root agent at SHA-256 `4df9e29c99abc0ff8e5c1d176766d362cb805c8a42021183fa21200fd60794bc`. The legacy review recorded batch 1 in [its first receipt](</Users/kimyongjin/Desktop/horse_racing/jeju/maintenance/legacy_review_20260928/deletion_receipt.json>), based on allowlist SHA-256 `69cc0d523186232be127cbae754048111813cb412a47a485b5ab0ed2a466c547`, and batch 2 in [its second receipt](</Users/kimyongjin/Desktop/horse_racing/jeju/maintenance/legacy_review_20260928/deletion_receipt_v2.json>), based on approved manifest SHA-256 `64363a7ed37ec6f2fc38754f06337de92676d2976c41bc76e8605b912f431f39`.

## Champion and inference checks

- Canonical physical model: [`jeju/models/current/HY_R_FORM.pkl`](</Users/kimyongjin/Desktop/horse_racing/jeju/models/current/HY_R_FORM.pkl>), 638,955 bytes, SHA-256 `f1b9531e068cab51dff906961d56f51c7c4b0e5a86f378c9aa1f03f159ec9706`.
- The registry remains unchanged at SHA-256 `944e4aad25c99d3d346dab23c7f7596c216d8722a548dea2c7c07abf9b10b70b`. Its original model path is a relative compatibility symlink to the canonical Jeju file.
- The official prediction-model resolver was rerun after phase 2. It returned `ok: true`, champion `HY_R_FORM`, and the expected model, registry, inference-script, verification, and challenger-gate hashes.
- The direct live inference inputs remain present: Jeju top-3 `labels.parquet` and `history_results.parquet`; `jeju_native_text_phase2.sqlite3`; and transition `context_history.parquet`. The saved pregame fixtures, predictions, raw/source/operational databases, shared source histories, Jeju yearly score databases, source analysis modules needed to unpickle the champion, and all shared/mixed-run ledgers remain outside the deletion allowlists.
- The three frozen baseline files remain in `data/research/jeju_native_transition_holdout_v13_20260916/`: `frozen_scores.parquet`, `horse_predictions.parquet`, and `race_predictions.parquet` (700,060 bytes total).

## Historical experiment records kept

- All five `data/datasets/jeju_native_racefit_*` lineage `manifest.json` files remain. Their five generated `dataset.parquet` payloads were removed (62,175,018 bytes); the raw/source tables needed for a data-first rebuild remain. The old engineered table payloads are not represented as byte-for-byte reproducible from these manifests alone.
- Twenty-seven small decision, protocol, selection-lock, summary, verification, and gate records across the five reviewed experiment directories remain. They preserve the rejected hypotheses and outcomes without retaining the larger derived score/probability caches.
- The user-designated framework, model-input audit/rebuild plan, native variable catalog, context-variable guide, and evaluation register remain in the root `docs/` folder. The restart packet also exists under `jeju/docs/`; copied archive versions were removed under the separate legacy allowlists after references were checked. The three root-level evidence reports linked from the framework remain available.
- The shared `data/experiments/model_runs.jsonl` ledger was not edited; its post-cleanup SHA-256 is `7ff2f6a11f0b11da1a92c98be25935123f2712b9d6fb628ddf994cec8db1330f`. Its 13 Jeju racefit run records remain as historical metadata. Their model pickle payloads were disposed, and 10 recorded comparison parquet payloads were also disposed. Exact run IDs, dataset versions, paths, hashes, and sizes are in [the run disposal receipt](</Users/kimyongjin/Desktop/horse_racing/jeju/maintenance/cleanup_20260928/racefit_run_disposal_receipt.json>). The remaining ledger paths should be understood as historical records, not as a promise that every old artifact is still present.

## Receipts and manifests

- [Phase 1 exact manifest](</Users/kimyongjin/Desktop/horse_racing/jeju/maintenance/cleanup_20260928/cleanup_plan.json>) and [phase 1 execution receipt](</Users/kimyongjin/Desktop/horse_racing/jeju/maintenance/cleanup_20260928/execution_receipt.json>)
- [Champion relocation receipt](</Users/kimyongjin/Desktop/horse_racing/jeju/maintenance/cleanup_20260928/model_move_receipt.json>)
- [Phase 2 exact manifest](</Users/kimyongjin/Desktop/horse_racing/jeju/maintenance/cleanup_20260928/phase2_cleanup_plan.json>) and [phase 2 execution receipt](</Users/kimyongjin/Desktop/horse_racing/jeju/maintenance/cleanup_20260928/phase2_execution_receipt.json>)
- [13-run disposal receipt](</Users/kimyongjin/Desktop/horse_racing/jeju/maintenance/cleanup_20260928/racefit_run_disposal_receipt.json>)
- [Legacy archive/reproduction cleanup receipts](</Users/kimyongjin/Desktop/horse_racing/jeju/maintenance/legacy_review_20260928/deletion_receipt.json>) and [batch 2 receipt](</Users/kimyongjin/Desktop/horse_racing/jeju/maintenance/legacy_review_20260928/deletion_receipt_v2.json>)

Each execution receipt records the allowlist hash, pre-deletion hash-and-size checks, and exact removed paths. The phase-2 postflight verified that all 65 approved paths were absent. The shared registry and all protected source inputs listed in the phase-2 manifest were verified present with their expected hashes after cleanup.
