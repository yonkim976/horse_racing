# Cleanup verification report

The v2 `features_v2_rows.csv` was archived with deterministic gzip, restored to a temporary file, and matched to its original SHA-256 (`37c89e…b9a2`) and 139,748,563-byte size before the original was removed. Streaming verification after removal also confirms 410,168 data rows. The retained `prepared_v2.parquet` still matches SHA-256 `9825ae…653a`; the v3 audit previously established equality for all 410,168 keys and 34 absorbed feature columns.

The frozen v1, v2, and v3 manifest hashes remain unchanged. The effective preservation record is their original content plus `cleanup_manifest.json`. Restoration is available through `restore_features_v2_rows.py`; full reconstruction is available through the preserved v2 reproduction driver and its hashed code and inputs.

Twenty-seven `.pyc` files were removed only from the two cache directories identified in the v3 audit. They were excluded from integrity manifests, no open file handles were found immediately before removal, and source `.py` files remain. The v3 cache was left untouched because it was outside the audit's two-cache candidate set.

Logical removal was 140,219,210 bytes. The new lossless archive occupies 47,928,499 logical bytes, so net logical reclamation is **92,290,711 bytes** (about 88.0 MiB). On-disk allocated reclamation measured from filesystem block counts is **91,394,048 bytes** (about 87.2 MiB).

Run `python3 data/research/thoroughbred_followup_20260918_v4/cleanup/verify_cleanup.py` to repeat the effective-manifest, archive round-trip, retained-Parquet, absence, row-count, and space-accounting checks.
