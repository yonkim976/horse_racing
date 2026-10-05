# Local race steward and sanction source inventory

Audit scope: 2010-01-01 through 2026-09-29, actual venues Seoul, Busan/Bukyeong, and Yeongcheon. This is a local-source inventory against the read-only research `confirmed_races` table, not a claim that the available source records are complete. No operating database or service was accessed.

## Finding

The requested source is **not locally present for every confirmed race**. Local report bodies or race-score reports were found for 20,390 of 29,710 confirmed-race keys (68.62%); 9,320 confirmed keys have no matching local report body in the two local source families below. The gap is concentrated in 2010–2014. A separate official-API probe by the parent task shows the APIs can return historical records beyond the local snapshot, so a missing local file is not evidence that KRA has no record.

The race-score Text source contains a disposition table for every race report found, but does **not** provide a full, separately labeled steward narrative section. The table is source text, not structured sanction data in the existing parser. Local API report records have structured event metadata and free-text judgement narratives. Neither source has been loaded or applied here.

## Local race-score Text (`dacom11`)

- Inventory: 1,827 in-scope `.rpt` files under `data/raw/kra_text/dacom11/meet={1,3}/`, covering 2015-01-02 through 2026-09-13. There are no in-scope files for 2010–2014 or 2025. All files decoded as CP949; race-header dates agreed with file dates; no header or date disagreements were found.
- The reports contain 17,371 race blocks whose body-level venue/date/race-number keys match `confirmed_races`: Seoul 10,130; Busan 7,226; Bukyeong 9; Yeongcheon 6. The 9 Bukyeong keys count as Busan/meet 3. The six Yeongcheon reports are stored beneath a path labeled meet 3, but their body says `(영천)`; venue mapping therefore uses the report body, not the directory name.
- All 17,371 race blocks contain the table headed `구분 출전번호 대상명 처분종류 처분내용 세부내용`. It has one or more nonblank/nonplaceholder rows for 12,791 race keys; 4,580 have the table header but no data rows. This means “no row listed in this table,” not a definitive finding that no sanction or steward action occurred.
- A scan found no separately labeled `심판사항` or `기타심판사항` narrative section in these race blocks. `심판위원` appears in table detail text for 13 races; these are table cells, not a full steward report narrative. Thus the 17,371-key result is **disposition-table presence**, not full API215 report coverage.
- The existing `src/horse_racing/parsers/dacom11.py` parses race/result and runner fields; it does not expose disposition rows as structured sanction fields. The original `.rpt` bodies remain the evidence for those table entries.

## Local API report raw (`race_steward_reports`)

- Inventory: 668 page JSON files under `data/raw/kra/race_steward_reports/`; 459 are in-scope venue paths (meet 1/3/4), dated 2025-01-03 through 2026-09-20. In-scope venue item arrays within the audit cutoff contain 3,855 raw row occurrences, including repeated captures, and 3,066 distinct date/venue/race keys.
- Of those distinct keys, 3,065 match confirmed races. One additional item is a nonperformance report for Busan, 2025-12-26, race 6, whose text states `경주불성립`; retain it as a report, but it is not a confirmed-race key.
- The JSON records provide race metadata and free-text `judgement` (sometimes additional `addJudgement`). These narratives are not a normalized sanction table. `jkChange` is `-` for all 3,855 in-scope row occurrences; this field alone does not establish absence of all penalties.
- Nineteen in-scope page payloads through the cutoff have a non-array/empty `items` value (Seoul 8, Busan 9, Yeongcheon 2). They are response observations without an event row, not evidence of an event with no report or no sanction. No separate local raw API180_1 sanction-history snapshot directory was found under `data/raw/kra`.

## Coverage against confirmed races

| Local evidence | Distinct confirmed keys |
| --- | ---: |
| `dacom11` race-score body with disposition table | 17,371 |
| API report raw item | 3,065 |
| Present in both sources | 46 |
| Present in either local source | 20,390 |
| Confirmed keys without either local source | 9,320 |
| Confirmed-race denominator | 29,710 |

The overlap is exact race-key overlap; it does not establish that table rows and API narratives describe identical actions. The gap count is a local inventory result and does not imply an official source record is absent.

## Separate source: running-trial reports (`dacom23`)

`data/raw/kra_text/dacom23/` has 1,628 in-scope `.rpt` files (path meet 1: 821, 2010-01-08 through 2026-09-17; path meet 3: 807, 2010-01-09 through 2026-09-17). These are running-trial examination reports, a distinct report type from race-day steward/disposition reports. File-path date/venue coverage does not establish a complete set of trial examination events or sanctions; in particular it does not mean all 61,777 examination records/reports are present.

## Official API availability probe (parent-task evidence, not local capture inventory)

The parent task verified that API215 judge-report queries returned normal zero results in 2010–2016, partial 2017 Q4 results (Seoul 257, Busan 194), and positive results in every year 2018–2026. API180_1 sanction-history queries returned positive results for Seoul and Busan in every year 2010–2026. This shows historical retrieval is possible from the official APIs; it does not mean those responses are saved locally or that every event has been collected. The 2026 API results include dates after the audit cutoff and must be filtered before use.

## Evidence and counting rules

- Denominator: read-only `confirmed_races` in `thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb` (29,710 rows: Seoul 17,322, Busan/meet 3 12,376, Yeongcheon/meet 4 12).
- `dacom11`: files inventoried from `data/raw/kra_text/dacom11/`; race dates and numbers come from each report's title/header; actual venue comes from the race block's body header. Key is actual venue + race date + race number. RPT counts and key bridge were independently checked against `passing_inventory.json` and `passing_rpt_file_evidence.json` in this research directory.
- Local API: page JSON inventoried from `data/raw/kra/race_steward_reports/`; repeated capture rows are preserved as occurrences, then distinct event keys are counted for coverage.
- `dacom23`: file counts and path date ranges only; no claim of complete event-level trial coverage.
- Blank table, non-array response, no local file, and nonperformance report are distinct states and have not been collapsed into “no sanction.”
