# Fresh period source bundle

This folder freezes read-only source inputs for a retrospective comparison of the saved F1_STYLE6 model and the saved four-feature API20 trial candidate on dates unused in those models' development/evaluation. It is not a prospective or verified as-of replay: public availability before each race has not been established. The bundle contains no predictions, performance metrics, retrained models, or database changes. The immutable row-level bundle is in `outputs/`; its checksums are recorded in `outputs/audit_manifest.json` (manifest SHA256: `c3e08c29c6acd8c263b64649e4816e287427338464af966c103623084f56e44a`).

## Observed population

The source period requested was 2026-09-20 through 2026-10-17 inclusive. The latest Jeju race date in the read-only core database was 2026-10-17. Stored API4 source rows were observed on seven dates only: October 2, 3, 5, 9, 10, 16, and 17. These contain 464 raw runner rows across 49 races. Applying the frozen population contract gives 426 runner rows in 45 eligible races. The raw roster and race-level inclusion/exclusion reasons are preserved, so dates absent from the source are not treated as zero-runner races.

The 14 frozen-snapshot-cold target horses occur on six dates. Coldness was checked against each horse’s started history through the target race date minus two calendar days, inclusive. Root’s independent raw-source parity review matched all 381 horses in the 464 raw cards to the same 8,910 pre-September-20 native history IDs and payload SHA256 values in the preserved September 19 source snapshot. That is ID-and-payload-digest parity. This audit’s current-database all-column reconciliation is narrower: it covers history for the eligible-target horse scope and found no missing IDs, extra IDs, or field differences there. Newer native history through each target’s T−2 cutoff is retained as warm-up data. No pre-September-20 scope deltas were found in the eligible-target scope. These checks do not establish that the period was unseen by every other project.

## Point-style history inputs

The last-five same-distance history selection for the 426 eligible targets contains 1,319 target-slot rows and 1,209 unique API4 source IDs. Of these IDs, 205 were absent from the existing frozen full-point cache. The audit queried complete starter rosters and selected API4/API303 quality records for all 66 affected source races (581 starters); 197 of 198 race-point checks passed. Failed or unavailable point fields remain explicitly gated in `actual_slot_point_eligibility_fresh_targets.parquet`; a missing old-cache record is never converted to an implicit null.

That actual-slot table uses the saved `prepare.build_style_features` input shape, including `target_api_record_id`, `source_api_record_id`, `slot_oldest_to_newest`, each point’s individual order status, full-roster permutation, API303 group status, and final eligibility flags. `fresh_history_source_rows_20col.parquet` supplies post-September-19 warm-up rows through each target’s T−2 cutoff in the frozen model source schema. The pre-cutoff source snapshot and original point cache were read-only and are identified by their hashes in the manifest.

## API20 trial inputs

The cold-target trial source includes 21 registered target-horse records for 14 horses, linked to 14 `(trial_date, meet_code, trial_number)` events. The bundle keeps the full explicit-Jeju peer rosters: 121 peer rows total, including raw `payload_json`, its SHA256, 1-based response `record_index`, source artifact/page path, response hash, byte count, normalized event key, raw day serial/order/time/pass fields, and candidate/status checks. `rcDist` was absent from all 121 peer payloads; raw trial times must not be converted into race-performance times or treated as distance-adjusted values. The latest-three registered-record ledger preserves invalid/cancelled slots and does not backfill from older records.

Trial pages were collected at `2026-09-29T13:26:44.936000+00:00` and `2026-10-16T11:24:55.606000+00:00`. The target cutoff is a race-date rule, while the collection timestamps show that public availability at prediction time has not been established. Any fresh-period result must therefore retain the retrospective/as-of limitation; these sources alone do not prove the historical information was available before each target race.

Horse ID `3005648` remains excluded. API303 quality statuses use the frozen explicit allowlist; absent, null, or unknown statuses fail closed. API4 full-roster checks and API20 peer scope are recorded in the row-level outputs and source lineage.

## Files and integrity

`outputs/audit_manifest.json` inventories the source contract, population counts, scoped before/after fingerprints, and SHA256 for every other frozen output file. Recompute those file hashes before use. The sibling `failed_numeric_scalar_preflight/` directory preserves a discarded first-pass bundle: its old-source comparison reported a false mismatch because NumPy integer and float scalar representations were compared as strings. The corrected final manifest uses numeric value comparison and reports zero source-field differences. Do not consume the failed preflight files.

The main row-level files are:

- `fresh_raw_race_rows.parquet`, `race_eligibility_ledger.parquet`, and `eligible_target_roster.parquet` for raw cards and cohort selection.
- `target_history_through_tminus2.parquet`, `target_history_reconciliation.parquet`, and `fresh_history_source_rows_20col.parquet` for history, cutoff, and warm-up inputs.
- `fresh_target_last5_same_distance_slots.parquet`, `selected_history_missingcache_full_started_rosters.parquet`, `api4_selected_point_quality.parquet`, `api303_group_status_by_starter.parquet`, `style6_source_point_gate_audit.parquet`, and `actual_slot_point_eligibility_fresh_targets.parquet` for style-history source coverage.
- `api20_target_trial_source_rows_all.parquet`, `api20_cold_target_trial_rows.parquet`, and `api20_linked_full_peer_event_rows.parquet` for target histories, latest-three registration slots, and full event peers.
- `source_artifacts.json`, `quality_view_definitions.json`, `source_scope_id_reconciliation.json`, `presep20_source_scope_diffs.parquet`, and `audit_manifest.json` for provenance and audit checks.
