# Three API training source loader

This loader stages retrospective observations from API18_1 daily training, API22_1 start training, and API216 swim training for `2010-01-01` through `2026-09-29`, meets 1 and 3. Meet 2 is excluded. Meet 3 remains an unresolved raw Yeongnam label where the source does not identify the physical venue.

The shared Parquet contract is [input_contract.json](input_contract.json). Each dataset supplies a Parquet file and JSON inventory under `input/`. The JSON inventory pins the Parquet path, SHA-256, and row count, lists selected and older source files with their hashes and capture metadata, and records a date-by-meet coverage status for every calendar day. `complete_zero_rows` is a captured zero; missing or incomplete capture blocks the load.

The 19 Parquet columns are explicitly typed. `source_captured_at` is a timezone-naive UTC timestamp; `capture_basis` and inventory metadata retain its meaning. Source observations remain unchanged in JSON, including negative, zero, blank, null, and repeated values. Core horse linkage is an exact official-ID string match only; unmatched IDs are retained. API22 occurrence order stays an anonymous storage ordinal. Every row is labeled `retrospective_training_observation_not_verified_pre_race`; historical publication at 14:00 is not inferred.

Default operation is read-only against the core database and its manifest. DuckDB scans the hash-pinned Parquet inputs into a bounded temporary database, validates row identity, exact roster links, selected captures, and date coverage, then evaluates the six proposed views. The proposed append adds three tables and six views and one source-manifest row.

```sh
.venv/bin/python thoroughbred/research/20261002_training_three_v1/loader/load_training_three.py
```

The write path is intentionally gated by two flags and is for the root reviewer after the dry run:

```sh
.venv/bin/python thoroughbred/research/20261002_training_three_v1/loader/load_training_three.py --apply --confirm-core-append
```

The write path requires the core DB hash to match `087914d31ac0f7025c6f399e5a5aef7ebd221c7bc5dfe08078caf1207847eae1`. It creates a paired DB/manifest backup under `thoroughbred/data/core_api_2010_20260929_v1/backups/20261002_before_training_three`, appends the nine declared objects plus a source-manifest row in one DuckDB transaction, and then appends input pins and counts to the core manifest while preserving its existing fields.

## Completed append and resource-bounded replay

The root applied the append and independently verified it. The full-text default replay exceeded available temporary disk space. Use the read-only root replay for the completed database:

```sh
.venv/bin/python thoroughbred/research/20261002_training_three_v1/root_replay_bounded.py
```

It keeps the pinned loader/schema unchanged, reads incoming Parquet through views, reuses the loader's scope/source/link/count checks, and compares SHA-256 of every complete typed row in both directions. Source/coverage metadata use exact comparisons. `root_bounded_replay_report.json` confirms unchanged database SHA and zero differences. Do not repeat the append to an already loaded core.
