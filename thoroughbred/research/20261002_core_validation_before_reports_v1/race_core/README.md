# Pre-steward-report core validation

## Result

**PASS: 99 of 99 checks.** The checks found no actual storage or referential-integrity errors in the scoped race, plan, result, trial, entity-reference, closure, or sectional data.

Validation used the archived database `thoroughbred/data/core_api_2010_20260929_v1/backups/20261002_before_steward_reports/thoroughbred_core.duckdb` and its sibling manifest. The database SHA-256 was `616aa6111242cfbcee4b87bc2e77251644e5c3780fc8c978319f69e7b1c4c8f7` both before and after validation, and matches the manifest. The DuckDB connection was read-only, with a 2 GB memory limit and two threads.

The manifest lists row counts for 178 objects; all are present. The database has 180 objects because it also contains the two helper views `confirmed_runners_entity_reviewed_before_role_review` and `trial_participants_entity_reviewed_before_role_review`, which the manifest does not count separately.

## Core counts and keys

| Area | Checked count |
|---|---:|
| Calendar days × venues | 18,348 |
| Planned races, race events, execution flags | 29,826 each |
| Confirmed races | 29,710 |
| Runner result rows | 331,811 |
| Runner rows for confirmed races | 330,465 |
| Runner rows retained for planned races without valid completed-race evidence | 1,346 |
| Confirmed races / runner rows from 2017 onward | 16,547 / 182,062 |
| Trial sessions / participants | 6,199 / 61,777 |
| Official entity IDs: horses / jockeys / trainers / owners | 23,814 / 337 / 225 / 1,438 |
| Section measurements / runner coverage / parse issues | 4,380,065 / 330,465 / 0 |

Duplicate natural keys were zero for race plans, plan API rows, race events, runner results, execution flags, adjudications, trial sessions and participants, entity IDs, and section coverage/measurement pointers. Race events and runners match their plan/event parents; all trial participants match a session; section coverage matches the confirmed-runner spine in both directions; and all section measurements have coverage rows.

## Dates and official IDs

Race plans, result/event keys, and section coverage use `YYYYMMDD`. Calendar, trial, and closure interval dates use ISO `YYYY-MM-DD`. All inspected date values parse in their documented format, and all are inside the requested range. The last observed race/event/section date is 2026-09-20; the calendar itself extends through 2026-09-29, and trial sessions extend through 2026-09-17.

Date and official-ID columns are stored as `VARCHAR`. Checks compared official ID strings directly without numeric conversion or name-based joins. Leading-zero examples retained in the roster include horse `0014396`, jockey `080014`, trainer `070017`, and owner `001201`.

For confirmed runners, horse, jockey, and reviewed owner IDs match the official-ID roster. Reviewed trainer IDs match for 330,442 rows; the other 23 are confirmed non-person `0AAAAA` / `휴양마` placeholders. The 38 original race API rows with blank trainer and owner IDs remain blank in their source fields; reviewed ID columns preserve their supported supplements. One runner has a verified owner ID (`010424`) but no owner name in the source.

## Adjudication and known exceptions

All 116 planned races without valid completed-race evidence have final verdict `no_valid_completed_race`: 17 official closure nonexecutions, 35 official day cancellations, 51 race cancellations, 2 invalid races, and 11 reported day cancellations. The 29 rows previously left as `reason_recorded_outcome_unclassified` are now classified as `race_cancelled`. `unresolved_race_days` is empty. The closure ledger has 81 sourced intervals covering 552 venue-days and no verified race-date overlap.

The 1,346 runner rows attached to planned nonexecution races remain in the raw result spine with status `planned_no_execution_evidence`; they contain no positive-finish evidence. Among all runner result rows, 0/94/95/98/99 rank/status codes are retained with zero positive-finish evidence (4,946 rows total: 3,600 in otherwise executed races and 1,346 in planned nonexecution races). These raw codes were not rewritten as finishing places.

The current role-exception view contains 164 non-person placeholders (23 race rows and 141 trial rows) and 22 trial trainer source errors. The 22 are closed under the user-accepted `source_error_unknown_cause` classification, remain without trainer IDs (19 have positive trial time and 3 have zero time), and were not reopened. The pending review view has zero rows.

The 104 trial rows missing an API horse ID are partitioned into 99 crosschecked operational-RPT links and 5 user-confirmed links; none remain unresolved. Trial jockey IDs are absent from the original API field on 5,121 rows: 5,079 official RPT row reviews, 18 official score-table conflict reviews, and 24 scheduled-only IDs. The completed-trial jockey field covers all 54,502 positive-time participant rows. Zero-time scheduled riders are not classified as actual completed rides.

Section coverage retains all 330,465 confirmed runner rows. It records no measurements for 4,870 runners. Two known finishers have no API sectional measurements:

- Seoul 2010-07-04 race 6, runner 10, horse ID `0020813` 용왕성: the user-provided record says `특이경주 / 실격 미처분`.
- Seoul 2012-10-06 race 9, runner 9, horse ID `0027368` 동촌: the user-provided record says `출주정지 2개월(2012.10.07~2012.12.06); 양 앞다리 질병(양전 제염)`.

Both post-race records and their source status are preserved in the review table. Whether either record directly explains the missing API sectional values remains unverified; the values were not imputed. Sectional measurements are post-race observations, not validated pre-race model inputs.

## Actual errors and limits

No actual storage, duplicate-key, out-of-range-date, scope, foreign-key, ID-width, or sectional-parse error was found by these checks. The source manifest itself still labels the database `staged_core_not_frozen`; historical closure coverage is partial. The capture/publication as-of time and full historical completeness remain unverified, so this PASS is a scoped data QA result rather than a final historical-completeness claim.

The verifier's first run used an incorrect expected count for rank 0/99 because it assumed only the two confirmed-race rows. The database contains those 2 rows plus 1,330 planned-nonexecution rows; ranks 94, 95, and 98 also occur as non-positive-finish codes. The verifier was corrected to check the full status-by-rank distribution, then rerun successfully. This was a verifier expectation correction, not a database change.

## Reproduction

From the repository root:

```bash
.venv/bin/python thoroughbred/research/20261002_core_validation_before_reports_v1/race_core/validate_core.py
```

The script writes `validation.json` beside itself and fails with a nonzero exit code if a checked contract no longer passes. The full machine-readable findings are in [validation.json](validation.json).
