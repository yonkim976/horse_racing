# Dacom11 passing-group extraction and comparison

This package preserves the original Dacom11 passing-group print lines for Seoul, Busan-Gyeongnam, and Yeongcheon from 2010-01-01 through 2026-09-29. Jeju is excluded. Source RPT files are decoded as CP949 and never modified.

`rpt_point_observations.parquet` contains every observed passing-group print line, including blank and placeholder rows. `raw_line_bytes_hex` includes the physical line ending; `notation_raw` and `notation_raw_bytes_hex` preserve everything after the colon, including source padding. No group grammar is parsed. A separate comparison field trims only outer ASCII spaces. Source download time is populated only when `local_path + sha256` exactly matches `data/raw/kra_text/_manifests/dacom11/manifest.jsonl`; unmatched files remain null, and filesystem mtime is not used.

`rpt_point_mapping.csv` maps exact labels by actual header venue. The path meet code is retained because it can differ from the actual venue: path meet 3 on 2026-09-13 contains six Yeongcheon races (actual meet 4).

`rpt_snapshot_comparison.parquet` is a read-only comparison with the named research snapshot, not a replacement instruction. Both values remain available for every key. Conflicts, absent rows, and placeholder rows are explicit. The old snapshot is opened read-only and its file SHA-256 is checked unchanged.

`root_independent_parse_parity.json` records exact source-coordinate parity against the independently created root parse. `manifest.json` pins all generated output hashes, source file hashes/counts, scope, and safety boundaries.
