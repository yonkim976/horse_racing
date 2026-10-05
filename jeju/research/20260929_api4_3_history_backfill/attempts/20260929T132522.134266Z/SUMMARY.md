# Historical API4_3 backfill summary

Attempt: `20260929T132522.134266Z`  
Status: **completed**; successful years 24/24; failed years: none  
Total API rows: **186,304**; 제주 + `rank` prefix `제` candidates: **86,932 rows / 8,874 races**.

All rows below are full `meet=2` API response rows. Candidate columns use `meet == 제주` and `rank.startswith("제")`; this is only a candidate selector, not horse-breed confirmation. `Pages` is actual/derived expected page count. `Compare Δ` is API candidates minus the existing comparison layer.

| Year | API totalCount | Pages actual/expected | Actual rows | Candidate rows | Candidate races | Compare Δ rows/races |
|---:|---:|---:|---:|---:|---:|---:|
| 2002 | 8,545 | 1/1 | 8,545 | 48 | 6 | 0/0 (archive) |
| 2003 | 8,279 | 1/1 | 8,279 | 102 | 12 | 0/0 (archive) |
| 2004 | 8,307 | 1/1 | 8,307 | 491 | 53 | 0/0 (archive) |
| 2005 | 7,705 | 1/1 | 7,705 | 802 | 88 | 0/0 (archive) |
| 2006 | 8,015 | 1/1 | 8,015 | 1,209 | 135 | 0/0 (archive) |
| 2007 | 8,534 | 1/1 | 8,534 | 1,805 | 191 | 0/0 (archive) |
| 2008 | 8,543 | 1/1 | 8,543 | 2,239 | 239 | 0/0 (archive) |
| 2009 | 8,395 | 1/1 | 8,395 | 2,656 | 280 | 0/0 (archive) |
| 2010 | 8,083 | 1/1 | 8,083 | 2,581 | 274 | 0/0 (archive) |
| 2011 | 8,063 | 1/1 | 8,063 | 2,682 | 283 | 0/0 (archive) |
| 2012 | 8,437 | 1/1 | 8,437 | 2,957 | 313 | 0/0 (archive) |
| 2013 | 8,009 | 1/1 | 8,009 | 3,132 | 336 | 0/0 (archive) |
| 2014 | 8,079 | 1/1 | 8,079 | 3,552 | 382 | 0/0 (archive) |
| 2015 | 7,866 | 1/1 | 7,866 | 3,981 | 429 | 0/0 (phase2 explicit-rank) |
| 2016 | 8,199 | 1/1 | 8,199 | 4,953 | 504 | 0/0 (phase2 explicit-rank) |
| 2017 | 8,067 | 1/1 | 8,067 | 5,493 | 553 | 0/0 (phase2 explicit-rank) |
| 2018 | 8,134 | 1/1 | 8,134 | 6,089 | 601 | 0/0 (phase2 explicit-rank) |
| 2019 | 8,108 | 1/1 | 8,108 | 6,354 | 622 | 0/0 (phase2 explicit-rank) |
| 2020 | 4,619 | 1/1 | 4,619 | 3,574 | 358 | 0/0 (phase2 explicit-rank) |
| 2021 | 6,154 | 1/1 | 6,154 | 4,978 | 481 | 0/0 (phase2 explicit-rank) |
| 2022 | 7,103 | 1/1 | 7,103 | 6,194 | 602 | 0/0 (phase2 explicit-rank) |
| 2023 | 7,086 | 1/1 | 7,086 | 7,086 | 715 | 0/0 (phase2 explicit-rank) |
| 2024 | 6,903 | 1/1 | 6,903 | 6,903 | 695 | 0/0 (phase2 explicit-rank) |
| 2025 | 7,071 | 1/1 | 7,071 | 7,071 | 722 | 0/0 (phase2 explicit-rank) |

## Verification

- 24/24 years completed; no missing or failed years.
- Every year has one archived source page; actual page count equals expected page count.
- Every year’s parsed response row count equals API `totalCount`.
- All 24 page files match the SHA-256 recorded in the annual manifest.
- 2002–2014 candidate row and race counts match `data/raw/jeju_native_results/native_results_YEAR.jsonl` for every year.
- 2015–2025 candidate row/race counts match both phase2 `official_result_rank_explicit_je` counts and total phase2 entry/race counts for every year.
- `run_manifest.json` and annual manifests contain no service-key parameter or value.

The full API row count is the preserved source population. The candidate view is a separate derived count and must not be treated as a confirmed native-breed population.

## 2026 append and independent integrity check

I independently reparsed the 24 archived 2002–2025 response bodies and the complete 2026 response through 2026-09-19 at [`the 2026 API4_3 attempt`](../../../20260929_core_collection_inventory/raw/2026/attempts/20260929T132618.518555Z/attempt_manifest.json). The 2026 response SHA matches the earlier same-scope capture; both represent the complete `meet=2` API response, not a candidate-only extract.

| Scope | Full API rows | `meet=제주` and `rank` prefix `제` candidate rows | Candidate races |
|---|---:|---:|---:|
| 2002–2025 | 186,304 | 86,932 | 8,874 |
| 2026-01-02–2026-09-19 | 5,482 | 5,482 | 571 |
| Combined | **191,786** | **92,414** | **9,445** |

Integrity results across the combined 191,786 API result rows:

- All 25 raw response pages match their recorded SHA-256; each page's parsed row count matches its own API count, and each year's sum of rows matches `totalCount`.
- Race key `(meet, rcDate, rcNo)`: 20,117 unique races. Per-horse result key `(meet, rcDate, rcNo, hrNo)`: 0 missing key components, 0 duplicate groups, 0 excess rows.
- Entry-slot key `(meet, rcDate, rcNo, chulNo)`: 0 missing key components, 0 duplicate groups, 0 excess rows.
- `hrNo`: 0 missing IDs; all 191,786 values match seven decimal digits; 12,763 unique IDs. Candidate rows also have 0 missing or malformed horse IDs.
- Every response row has `meet=제주`. This verifies venue only. The `rank` prefix count remains a candidate classification; it does not confirm breed for any horse.

This is a raw API4_3 response integrity check. It does not assert that every API row belongs to the 제주마 breed population.
