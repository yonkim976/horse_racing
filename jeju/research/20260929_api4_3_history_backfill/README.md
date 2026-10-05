# KRA API4_3 historical result backfill

This research collection preserves the complete annual `meet=2` response from
KRA `API4_3/raceResult_3` for 2002–2025. The response is a mixed result source;
every page is archived as the response body bytes before parsing. The
`meet == 제주` plus `rank` prefix `제` counts are a separate candidate view.
That prefix does not establish an individual horse's breed.

Run `collect_history.py` from the repository root with the configured public
data service credential. Each execution creates a new timestamped directory in
`attempts/`; page files and manifests are immutable. A failed year is recorded
on its own and does not stop collection of later years. The collector reads
the existing archives and phase2 SQLite database in read-only mode solely to
write count comparisons. It does not write to the operational database,
phase2 database, or existing raw archives.

The completed run report is in
[`attempts/20260929T132522.134266Z/run_manifest.json`](attempts/20260929T132522.134266Z/run_manifest.json).
It records API `totalCount`, derived expected page count, actual page and row
counts, response SHA-256 values, candidate counts, and the yearly comparisons.
