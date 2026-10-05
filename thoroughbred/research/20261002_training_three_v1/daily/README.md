# API18_1 daily training source reconstruction

Scope: event dates 2010-01-01 through 2026-09-29, meet 1 (Seoul) and meet 3 (KRA raw region label retained in each source row). Meet 3 is not split into a physical racecourse. No Jeju meet or hill training is included.

The reconstruction uses the local API18_1 monthly page archive, exact-date API18_1 pages referenced by operating `source_documents`/`ingestion_runs`, and the fresh complete 2026-09 monthly capture. It makes no network requests and does not write to the operating SQLite database or core DuckDB.

## Output

- Parquet: `../loader/input/daily_training.parquet`
- Inventory: `../loader/input/daily_training_inventory.json`
- Date-by-meet coverage: `date_meet_coverage.csv`
- QA and raw natural-key conflicts: `qa_conflicts.csv`
- Exact official-ID link inventory: `horse_link_inventory.csv`
- Unmatched official-ID ledger: `unmatched_official_ids.csv`
- Selected and examined batches: `selected_capture_batches.json`

The Parquet contains 5,173,033 raw observations from 2,876 source page files. Its SHA-256 is `96a075f060e092be4c82b1f2120912075e34cca746d63d621721ea89db01bd57`. The inventory retains selected and older capture metadata, per-page hashes, pagination counts, and request/retrieval time basis. Historical monthly archive timestamps come from `manifest.recorded_at_ms` after download; the one cached ledger event is not treated as a later HTTP capture. Exact-date source documents retain their stored request and retrieval times. The fresh September monthly capture uses its recorded HTTP request/retrieval timestamps.

All 12,232 date-by-meet cells have a coverage record: 10,211 with rows, 2,021 complete zero-row cells, 0 missing, and 0 with only incomplete captures. Selection uses the latest complete capture for each date and meet. Month responses cover dates no later than the capture cutoff; rows after 2026-09-29 are excluded from the research Parquet even when present in the complete September response.

## Preservation and QA

`raw_payload_json` and `typed_fields_json` contain the complete canonicalized API item with all original keys, values, and JSON value types; missing fields are not filled. Raw response files remain untouched. Each observation ID includes its capture ID, source page hash, page number, and one-based row number, so exact repeated rows and nonidentical natural-key variants remain separate observations.

Core links use exact official horse ID equality against `entity_reference_roster.entity_id_official_string` where `entity_type='horse'`. No name-based linking is used. Row counts by link status: {"exact_core_roster_match":5139741,"unmatched_official_id":33292}. The unmatched ledger preserves every unmatched official ID and its observed raw name variants.

The QA file has 371 affected observations, including 16 rows in nonidentical same-natural-key groups and 0 exact repeated payload rows. Time QA retains negative and zero `trTerm`, start/end ordering, raw-time date validity, and any difference between `trTerm` and the raw start/end time delta. No rollover or absolute-value correction is applied.

## Rebuild

Run `.venv/bin/python thoroughbred/research/20261002_training_three_v1/daily/build_daily.py` from the repository root. The builder reads archived JSON using JSON parsing, opens both databases read-only, validates source hashes and pagination, and writes the Parquet and inventories atomically.
