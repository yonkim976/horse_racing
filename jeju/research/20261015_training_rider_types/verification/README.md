# Rider type verification

`verify_rider_types.py` independently checks the stored rider-type assignments and their source evidence. It opens each SQLite database with `mode=ro` and `PRAGMA query_only=ON`; it does not write to the database. Its HTML parser is implemented here with Python's standard library and does not import the production classifier or the project audit script.

From the repository root, run the staging semantic and schema check with:

```sh
.venv/bin/python jeju/research/20261015_training_rider_types/verification/verify_rider_types.py \
  --db jeju/research/20261015_training_rider_types/staging.sqlite3 \
  --baseline jeju/research/20261015_training_rider_types/before_types.sqlite3 \
  --output jeju/research/20261015_training_rider_types/verification/staging_verification.json
```

After production application, run the one-time old-table preservation comparison with:

```sh
.venv/bin/python jeju/research/20261015_training_rider_types/verification/verify_rider_types.py \
  --db jeju/data/jeju_native_core.sqlite3 \
  --baseline jeju/research/20261015_training_rider_types/before_types.sqlite3 \
  --full-old-preservation \
  --output jeju/research/20261015_training_rider_types/verification/production_verification.json
```

Reports are written only under this directory, and the verifier refuses to overwrite them. The production comparison checks exact SQL definitions for all pre-existing schema objects and computes an order-independent multiset fingerprint for every pre-existing table by hashing every row and combining its SHA-256 values with both a 256-bit sum and XOR, bound to the row count. This avoids large temporary sorts while retaining duplicate-row sensitivity. It also checks the new assignment table, all three views, original raw columns, the complete set of exact-event website matches from the 32 saved official pages, conservative unknown-name handling, per-type counts, and jockey-name visibility.
