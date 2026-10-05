# API18_1 raw-to-operating row count comparison

Read-only aggregate comparison of the reconstructed source Parquet against `data/horse_racing.sqlite3` `horse_training` rows. The operating SQLite database was opened with `mode=ro`, `PRAGMA query_only=ON`, and a read transaction; the core database and both published daily artifacts were not modified.

| Measure | Count |
|---|---:|
| Selected raw API18_1 observations | 5,173,033 |
| Operating `horse_training` rows | 5,173,018 |
| Raw observation difference | +15 |
| Distinct source natural keys | 5,173,025 |
| Source natural-key duplicate excess rows | 8 |
| Nonidentical raw collision groups / observations | 8 / 16 |
| Source-only natural keys / observations | 8 / 8 |
| Operating-only natural keys / observations | 1 / 1 |

The raw observation difference decomposes as source-only observations minus operating-only observations plus source duplicate rows on matched natural keys. Source natural keys use exact `hrNo`, meet, `trDate`, `stTime`, and `spTime` values with blank and NULL time values treated alike, matching the operational uniqueness key convention. No names are used to match horses.

Exact reconciliation: +15 = +8 preserved extra observations from nonidentical collision variants + 8 source-only observations - 1 operating-only observations. The 8 nonidentical collision keys contain 16 raw observations and account for 8 extra rows over one operating row per key.

## Date and meet cells with row-count differences

| Event date | Meet | Raw rows | Raw unique keys | Operating rows | Source-only keys/rows | Operating-only keys/rows | Nonidentical collision keys/rows |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2015-11-12 | 3 | 514 | 514 | 513 | 1/1 | 0/0 | 0/0 |
| 2015-11-13 | 3 | 491 | 491 | 490 | 1/1 | 0/0 | 0/0 |
| 2015-11-15 | 3 | 483 | 483 | 482 | 1/1 | 0/0 | 0/0 |
| 2015-11-18 | 3 | 509 | 509 | 508 | 1/1 | 0/0 | 0/0 |
| 2018-09-02 | 1 | 601 | 600 | 600 | 0/0 | 0/0 | 1/2 |
| 2020-01-13 | 3 | 517 | 517 | 516 | 1/1 | 0/0 | 0/0 |
| 2025-08-31 | 1 | 685 | 684 | 684 | 0/0 | 0/0 | 1/2 |
| 2025-09-01 | 1 | 9 | 8 | 8 | 0/0 | 0/0 | 1/2 |
| 2025-09-02 | 1 | 9 | 8 | 8 | 0/0 | 0/0 | 1/2 |
| 2025-09-03 | 1 | 754 | 753 | 753 | 0/0 | 0/0 | 1/2 |
| 2025-09-04 | 1 | 764 | 763 | 763 | 0/0 | 0/0 | 1/2 |
| 2025-09-05 | 1 | 779 | 778 | 778 | 0/0 | 0/0 | 1/2 |
| 2025-09-06 | 1 | 716 | 715 | 715 | 0/0 | 0/0 | 1/2 |
| 2026-08-12 | 3 | 653 | 653 | 653 | 1/1 | 1/1 | 0/0 |
| 2026-09-13 | 1 | 640 | 640 | 639 | 1/1 | 0/0 | 0/0 |
| 2026-09-20 | 1 | 697 | 697 | 696 | 1/1 | 0/0 | 0/0 |

## Source-only key capture classes

| Selected capture type for source-only keys | Keys |
|---|---:|
| fresh_month_capture | 2 |
| monthly_archive | 6 |

## Operating-only source keys

| Event date | Meet | Operating-only keys | Operating-only rows |
|---|---:|---:|---:|
| 2026-08-12 | 3 | 1 | 1 |

The tables distinguish extra raw variants from source natural keys absent in the operating table. The September 2026 monthly source query was selected for its scoped dates as the latest complete capture; the per-date rows above show whether any net difference falls in that capture window. “Meet 3” retains the API region code and does not infer a physical venue.
