# Thoroughbred cleanup overlay

This directory records storage pruning performed after the v3 audit. The frozen v1, v2, and v3 manifests remain unchanged. `cleanup_manifest.json` is the effective overlay: a consumer must interpret the original v2 manifest together with the overlay entry that replaces `features_v2_rows.csv` by a lossless gzip archive.

The CSV can be restored without overwriting an existing file:

```sh
python3 data/research/thoroughbred_followup_20260918_v4/cleanup/restore_features_v2_rows.py \
  --restore data/research/thoroughbred_win_research_20260918_v2/features_v2_rows.csv
```

Running the helper without `--restore` verifies the archive by streaming decompression. Full historical regeneration remains available in a new directory:

```sh
python3 data/research/thoroughbred_win_research_20260918_v2/code/reproduce_research.py \
  --output data/research/thoroughbred_win_research_REPRODUCED
```

That reproduction regenerates the CSV and `prepared_v2.parquet` from the preserved source references and code. The cleanup verification additionally tests an archive round trip, the original SHA-256 and byte count, the retained prepared Parquet hash, unchanged original manifest hashes, and absence of the pruned paths.
