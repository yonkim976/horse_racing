# Full API78 equipment loader

`load_equipment_api78_full.py` defaults to a read-only dry run. It checks the frozen CSV manifest, its SHA-256 pin in `snapshot_summary.json`, the frozen historical manifest snapshots, selected raw page hashes and payload rows, exact five-key identity links, complete date-meet coverage, token marks, and the proposed coverage view.

Run after the inventory agent publishes the final frozen export:

```sh
.venv/bin/python thoroughbred/research/20261002_equipment_full_v1/loader/load_equipment_api78_full.py
```

The write path requires both flags and is reserved for the root reviewer:

```sh
.venv/bin/python thoroughbred/research/20261002_equipment_full_v1/loader/load_equipment_api78_full.py --apply --confirm-core-append
```

The loader is pinned to the reviewed core database SHA-256 and refuses a write if it changed. Apply copies the database and core manifest to `thoroughbred/data/core_api_2010_20260929_v1/backups/20261002_before_equipment_api78_full`, appends the new source tables/views and source-manifest row in one DuckDB transaction, then atomically updates the core manifest. The source manifest records hashes for all frozen CSV exports, frozen capture/target manifests, this loader, and `schema.sql`.

API78 captures are retrospective and do not establish pre-race availability or actual physical wear. `equipment_raw` preserves its exact source value; JSON null and missing field are SQL NULL but remain distinct through `equipment_is_null`, `equipment_field_present`, and `equipment_value_state`. The declared-token view excludes literal removal tokens only. The official score supplement remains available as fallback where no safely linked API78 observation exists.
