# API24_1 Jeju race-day collection

This folder stores raw responses from the official `/API24_1/horseMedicalAndEquipment_1` operation (`meet=2`, `rc_date=YYYYMMDD`). The period filter was confirmed as `rc_date`. API values remain the primary source; this work does not load or replace any value in the core database.

## 2026 scope: 2026-01-01 through 2026-09-19

[`source_dates_2026.json`](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20260929_api_equipment_recent/source_dates_2026.json>) freezes the 79 distinct Jeju race dates derived from the validated official API4_3 response and cross-checked exactly against the read-only core database date set. The cutoff is inclusive; later dates were not requested.

All 79 source dates were examined. The ledger records 76 exact-date `complete` partitions (5,300 rows), three `validation_failed` partitions (203 returned rows), zero confirmed empty responses, and zero pending dates. The API returned 79 successful single-page response bodies: 5,503 total rows including the three quarantined mismatches. The collector ledger records 82 request starts overall: 79 successful HTTP responses plus two earlier transport failures and one interrupted request. These counts describe responses observed from the official API; only the 76 exact-date partitions count as validated coverage.

The final requested date, 2026-09-19, returned result code `00`, `totalCount=63`, one page with 63 rows, all with `rcDate=20260919`; its raw SHA-256 is `2e06efd9748dcae12e699ee327547eb0d0f362e3dc1901c224714fb219fc4bca`.

| Requested `rc_date` | Ledger status | API rows and returned `rcDate` values | Raw SHA-256 | Duplicate evidence |
|---|---|---|---|---|
| 2026-07-07 | `validation_failed` | `totalCount=69`; 69 rows had `rcDate=20260704`, 0 matched the request | `b747a27fb9bbb0651e238891f828b7da86cf286f7af826f8b9ac49d48df389ef` | Byte-identical to the normal 2026-07-04 response |
| 2026-08-25 | `validation_failed` | `totalCount=67`; 67 rows had `rcDate=20260822`, 0 matched the request | `5770fec8ec1e5f7b5191c10ca6f61d97742bb5a35a263d8e7c16b89777ee465a` | Byte-identical to the normal 2026-08-22 response |
| 2026-08-26 | `validation_failed` | `totalCount=67`; 67 rows had `rcDate=20260822`, 0 matched the request | `5770fec8ec1e5f7b5191c10ca6f61d97742bb5a35a263d8e7c16b89777ee465a` | Byte-identical to the normal 2026-08-22 and 2026-08-25 responses |

The next source dates, 2026-08-28 and 2026-08-29, returned exact matching dates and are `complete`. The evidence does not establish why the three mismatches occurred, and it does not show that API24 ignores the date filter globally. Mismatch bodies remain archived and excluded from exact-date coverage. Full page-hash and response comparison details are in [`scope_mismatch_audit.json`](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20260929_api_equipment_recent/scope_mismatch_audit.json>).

## Official Text/RPT inventory for the mismatch dates

[`rpt_txt_mismatch_inventory.json`](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20260929_api_equipment_recent/rpt_txt_mismatch_inventory.json>) is a read-only inventory of the local official KRA text archive. It found no meet=2 RPT/TXT file for 2026-07-07 or 2026-08-25. For 2026-08-26 it found six meet=2 files. The relevant candidate is `dacom71` (`출전마진료및장구사용`), whose report headings include `보조장구`, `폐출혈`, and `진료사항`; `dacom72` contains date-bearing clinical text and is a possible illness-note source, but its field boundaries and API24 row mapping were not validated. The `dacom71` file dated 2026-08-26 contains race-day headings for 2026-08-28 and 2026-08-29, so the file date alone does not establish a direct match to `rc_date=20260826`.

No TXT/RPT data has been parsed into a supplement or used to substitute an API24 value. Future supplementation requires exact race/date/horse-key validation and separate provenance for the supplementary source. The API24 raw and core database remain unchanged by this inventory.

## 2002–2025 historical scope

[`source_dates_2002_2025.json`](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20260929_api_equipment_recent/source_dates_2002_2025.json>) freezes 2,225 unique official API4_3 Jeju race dates from 2002 through 2025. All 24 annual API4_3 source manifests are `completed`; their raw pages were checked against manifest SHA-256, byte size, `totalCount`, and actual page-row counts. The resulting date set matches exactly the 2,225 dates in `race_result_rows` read-only from `jeju/data/jeju_native_core.sqlite3`.

[`collect_api24_history.py`](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20260929_api_equipment_recent/collect_api24_history.py>) and [`history_collection_ledger.json`](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20260929_api_equipment_recent/history_collection_ledger.json>) are the historical collector and its resume ledger. Before each run, the collector rechecks the frozen API4_3 pages and the read-only database date set. It requests one race date at a time, waits at least one second between request starts, saves raw response bytes immutably, follows all pages, and validates each page's pagination metadata, `totalCount`, row count, and every row's `rcDate`. The ledger records year-by-year `complete`, `zero_rows`, `validation_failed`, and pending coverage separately. A zero-row response is not treated as positive record coverage.

Use a request budget explicitly allocated against the shared KRA API quota:

```sh
.venv/bin/python jeju/research/20260929_api_equipment_recent/collect_api24_history.py --request-budget 1600 --dry-run
.venv/bin/python jeju/research/20260929_api_equipment_recent/collect_api24_history.py --request-budget 1600
```

The budget is the maximum number of API24 request starts this collector may use on one Korea Standard Time calendar date; the ledger retains its own per-date API24 usage across resumes. It does not observe calls made by other collectors. Before resuming on a later day, recalculate the shared account's remaining capacity and pass the newly authorized API24 allowance. The currently authorized allowance for the 2026-09-30 KST run is at most 1,600 requests; this is not enough to claim all 2,225 historical dates complete.

The 2026-09-30 KST history run had a 1,600-start API24 allowance, including failed attempts and retries. It is currently stopped by the transient-timeout safety limit at 1,061 starts, before reaching the allowance. Ledger status is 1,055 `complete`, 1 `failed`, 1,169 `pending`, 0 `zero_rows`, and 0 `validation_failed`. Years 2002–2012 are fully complete (1,041 dates); 2013 has 14 complete, 1 failed, and 80 pending dates; 2014–2025 remain pending. The 1,055 complete dates contain 92,129 rows across 1,055 validated pages. On 2003-05-17, the first request ended in a 60-second `ReadTimeout`; a resumed same-date/page attempt then succeeded with `resultCode=00`, `totalCount=77`, one page, 77 exact-date rows, and raw SHA-256 `4d1274636d4dd0575182e356b8bb8be8144a9bc9018bb8457d03ae193e822048`. Both the timeout and successful retry remain separately recorded. On 2013-03-08, all three same-page network starts ended in `ReadTimeout` (60-second timeout, then 2-second and 4-second backoffs); there was no HTTP response or raw response page. That date remains `failed`, and the run stopped with `transient_timeout_retry_limit_reached`. The collector does not automatically skip this exhausted failed date; any continuation past it requires an explicit policy/ledger decision while preserving the failure.

One early response for requested date 2002-04-14 returned HTTP 200 with `resultCode=99`; the API response body was a JSON string rather than a success body. The official Public Data Portal's common API error table defines `99` as `UNKNOWN_ERROR` / 기타에러, while quota is code `22` and access/key errors have separate codes ([official error-code table](https://www.data.go.kr/en/data/15021104/standard.do)). The error body was preserved but its message was not copied into the ledger or log. A single retry for 2002-04-14 then returned `resultCode=00`, `totalCount=83`, one page with 83 exact-date rows, SHA-256 `b4652773ec1d37180492fbc750791b852ecd1f54a82841b88e22fa98c7e9437f`; the first error response SHA-256 is `d1d86795bc27801ee5a2da1aed5b825ee417a152ec8e2fde43bd467138d1a794`. The retry is recorded as a second immutable attempt page. Because the same-date retry recovered, the conditional special probe was not invoked. The next actual source date is 2002-04-20 (there is no 2002-04-15 race date); it was subsequently fetched and validated as `complete` during sequential collection. Future quota/permission codes stop without a retry.

Every date mismatch is quarantined as `validation_failed`, kept separate from `zero_rows` and `complete`, and the collector continues while the cumulative and consecutive mismatch counts stay below five. Five cumulative or five consecutive date mismatches stop collection. `ConnectTimeout`, `ReadTimeout`, `WriteTimeout`, and `PoolTimeout` may be retried only on the same date/page, up to three network starts total across resumes, with 2-second and 4-second backoffs; every start is recorded in the ledger. If the third timeout fails, collection stops at that date. HTTP status errors (including 429), API result errors, credential echoes, response/schema errors, and pagination failures stop immediately without retry; exception text and the service credential are not stored. The 2026 mismatch dates above belong to the separate 2026 ledger and remain excluded; this historical collector does not retry or alter them.

## Files

- `collect_api24_recent.py`: 2026 race-day collector with explicit handling for the three quarantined dates.
- `source_dates_2026.json`: frozen 2026 API4_3 date input.
- `collection_ledger.json`: 2026 per-date statuses, page hashes, API counts, and request attempts.
- `scope_mismatch_audit.json`: sanitized analysis of the three 2026 mismatches and succeeding exact-date responses.
- `rpt_txt_mismatch_inventory.json`: read-only local Text/RPT availability and field inventory.
- `collect_api24_history.py`: resumable 2002–2025 collector, per-KST-day request budget and per-year coverage.
- `diagnose_api24_code99.py`: one-retry/conditional-next-date probe for a generic API `resultCode=99`; limited to the already quarantined date and one following source date.
- `source_dates_2002_2025.json`: frozen 2,225-day API4_3 source with raw-page and core date-set provenance.
- `history_collection_ledger.json`: per-date and per-year historical checkpoint; created when the historical collector first runs without `--dry-run`.
- `raw/api24_1/YYYYMMDD/page_NNNN.json`: immutable 2026 response bodies.
- `raw/api24_1_history/YYYYMMDD/page_NNNN.json`: immutable historical response bodies.

No service credential is written to these files. Request URLs, credential values, and raw exception messages are not recorded by the historical collector.
