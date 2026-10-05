# API78 equipment inventory

This folder contains frozen, read-only exports of saved API78 gate-entry card observations for Seoul (meet 1), Busan (meet 3), and Yeongcheon (meet 4), from 2010-01-01 through 2026-09-29. The inventory reads the operational SQLite database in `mode=ro`, enables `query_only`, and holds a read transaction while it extracts document and runner rows. It reads the thoroughbred core through DuckDB read-only. The builder makes no network requests and does not write either database.

## Selection and identity

The builder groups saved pages by capture run and date/meet, verifies each source-file SHA-256 against its saved manifest, checks HTTP status and response date/page metadata, and verifies that all pages cover the API `totalCount` with unique race/program-number keys. It selects the latest complete capture per date/meet by saved retrieval time. A payload-complete run remains eligible when its ingestion status is `partial`; run status is retained in the exports.

API78 provides no horse ID. A runner links to `confirmed_runners` only when its meet/date/race/program-number key identifies exactly one core runner and its normalized raw API78 name equals the normalized core result name. If the operating snapshot has the same unique key, the official IDs and normalized names must also agree; that link is labeled `linked_op_id_corroborated`. If no operating entry exists, the exact key and normalized core name may establish `linked_core_key_name_only`. Every other API78 row remains in `api78_runner_records.csv` and the subset ledger `api78_unresolved_runner_identity_ledger.csv` with its candidate counts and reason.

The name normalization applies Unicode NFKC, removes a leading star and bracketed venue tag, removes whitespace, and case-folds. It does not match on horse name alone.

## Files

- `api78_runner_records.csv`: every item in the selected complete captures, including raw `equipCrs` values and explicit blank/null/field-missing states.
- `api78_explicit_change_marks.csv`: comma-positioned tokens whose raw equipment text ends in `+` or `-`. It does not infer changes from differences between races.
- `api78_core_runner_ledger.csv`: one row per in-scope confirmed runner, including linked observations, unresolved candidates, runners absent from a complete card, and date/meets with no complete saved card.
- `api78_unresolved_runner_identity_ledger.csv`: selected API78 rows without a safe unique core identity link.
- `api78_selected_batches.csv` and `api78_selected_pages.csv`: selected capture and page provenance, including safe paths, hashes, times, batch status, record totals, blank counts, and explicit mark counts.
- `api78_batch_inventory.csv` and `api78_source_document_inventory.csv`: all in-scope capture batches and source documents, including incomplete and failed ingestion runs.
- `api78_coverage_by_meet_year.csv` and `api78_missing_core_date_meets.csv`: complete capture coverage, blank/nonblank counts, explicit changes, and remaining core date/meet gaps.
- `api78_capture_queue_status.csv`: the historical collection queue, including planned date/meets without core runners, with capture status where available.
- `frozen_export_manifest.csv`: row counts and SHA-256 hashes for the CSV exports. `snapshot_summary.json` pins this manifest and the versioned, sanitized copies of the historical capture and target manifests used for that export.

No source URL, request-parameter blob, or API key is included in the exports or sanitized manifest snapshots. The capture-time basis distinguishes recorded response times from archived review files whose time was reconstructed from their save time.

## Rebuild

From the repository root, run:

```sh
.venv/bin/python thoroughbred/research/20261002_equipment_full_v1/inventory/build_inventory.py
```

Each rebuild snapshots the current historical capture manifest, writes a uniquely named sanitized manifest copy, and records its path and hash in `snapshot_summary.json`. The CSV manifest is written after the CSVs so downstream consumers can verify a complete export set.
