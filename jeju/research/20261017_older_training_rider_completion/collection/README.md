# Older daily-training rider collection

This folder contains the read-only collector for the older unclassified rider rows. The initial 609-row application was confirmed before the snapshot. The collector never writes to the database.

## Workflow

1. Create the read-only snapshot after the database state has been confirmed:

   ```sh
   .venv/bin/python jeju/research/20261017_older_training_rider_completion/collection/collect_older_training.py snapshot \
     --output-dir jeju/research/20261017_older_training_rider_completion/collection/snapshot_post609
   ```

   The snapshot refuses to continue unless the remaining target is exactly 280,351 rows across 4,122 dates from 2007-10-01 through 2026-04-16. It saves the row ID, the eight API event-key fields, and the complete rider-type assignment fields. It excludes `raw_row_json`. A compact per-date index records API event keys that occur more than once across all API rows, including already classified rows.

2. Fetch and classify with the official POST form:

   ```sh
   .venv/bin/python jeju/research/20261017_older_training_rider_completion/collection/collect_older_training.py fetch \
     --snapshot-dir jeju/research/20261017_older_training_rider_completion/collection/snapshot_post609 \
     --run-dir jeju/research/20261017_older_training_rider_completion/collection/official_daily_all
   ```

   Requests use verified HTTPS to the fixed KRA host and path, two workers, a 20-second timeout, a 4 MiB response cap, and one retry. A DNS resolution failure is logged and stops new requests so the same run can resume in the approved network environment. Each successful date gets immutable outcomes and candidate JSONL files plus an atomically written receipt. Receipts bind the date, request form, URL, page SHA-256, and result file hashes. The checkpoint is small and updated every 50 completed dates. Failed responses, including HTTP 200 error pages, are kept in a separate attempt log.

3. Freeze the combined files after all dates have been attempted:

   ```sh
   .venv/bin/python jeju/research/20261017_older_training_rider_completion/collection/collect_older_training.py finalize \
     --snapshot-dir jeju/research/20261017_older_training_rider_completion/collection/snapshot_post609 \
     --run-dir jeju/research/20261017_older_training_rider_completion/collection/official_daily_all \
     --allow-failed-pages
   ```

   `outcomes.jsonl` has one row for every target source row. `candidates.jsonl` contains only uniquely matched, classifiable rows. Both aggregate files are written once at finalization; individual daily files are never re-created after a successful receipt. A final manifest freezes source and output hashes and keeps failed-page outcomes as unclassified.

The page parser uses Python's standard-library `HTMLParser`. It requires the official detail heading and rider legend, the hidden meet/date fields, the exact nine-column table header, and one `goPage4('<horse_id>')` link per data row. Matching requires a unique horse ID, date, start time, end time, and duration; API seconds must be `:00`, website interval length must equal website duration, API event-key duplicates and website-key duplicates stay unclassified, and missing times never match. Labels follow the existing `parse_label` policy and SHA-verified API307 jockey-name roster.

## Completed collection run (2026-10-17)

- Read-only post-609 database snapshot: `snapshot_post609/target_rows.jsonl`, 280,351 rows across 4,122 dates, SHA-256 `763f84a989421c28f223e90c27d29bf58e067ad9a1f9524fd9b770934ea11aaa`. The snapshot manifest records the source database SHA and confirms that `raw_row_json` was excluded.
- Official requests: `official_daily_all/`; all 4,122 dates have successful receipts and per-date outcomes/candidate files (1,106,004 official table rows total). The final run manifest is frozen with zero failed dates.
- A sandbox DNS failure during the initial request attempt is retained in `official_daily_all/attempt_logs/`; the resumable collection then completed against the same fixed official endpoint with TLS verification.
- Frozen aggregate `outcomes.jsonl`: 280,351 rows, SHA-256 `23ae16538ae831dbc58b5ab32e878f68b3278063fe50bcb75a9751554cb08411`. Status counts: 185,819 exact classifiable matches; 75,740 exact matches with unresolved labels; 18,028 missing/invalid API timings; 592 ambiguous website keys; 172 without an exact website event match.
- Frozen aggregate `candidates.jsonl`: 185,819 rows, SHA-256 `8ecc27c8676485f7abbe7d2838356c3c4cf0b71969f3361504a0bfb853c9928b` (185,724 `주로조교`, 95 `교육생`). `run_manifest.json` freezes both aggregate hashes and the complete receipt set. Database writes remain disabled.

`verify-sample-parser` performs a smoke check against the archived 2010 page without accessing the database or network:

```sh
.venv/bin/python jeju/research/20261017_older_training_rider_completion/collection/collect_older_training.py verify-sample-parser
```
