# Thoroughbred trial trainer reference review

## Scope and handling

This review covers the 224 `trial_participants` records whose source `api_trNo`
is `-` (84 rows) or `0AAAAA` (140 rows) in the read-only core database
`thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb`.
The source API trainer fields and database were not changed. The flat review
ledger is supplemental evidence for integration review; it does not alter or
replace the source values.

`review_trial_trainer_ids.py` groups records by official event key and saves
the official KRA score pages to `raw_official_trainer_scores/`. It reuses the
request helper and table parser in
`thoroughbred/research/20260930_trial_jockey_gap_audit_v1/`. Requests use the
official HTTPS page
`https://race.kra.co.kr/referee/RacingTrainCheckScoreTable.do`, POST fields
`meet`, `date` (`YYYYMMDD`), `trno`, `Act=06`, and `Sub=7`. The capture
manifest records the event key, request form, UTC capture time, raw path, and
SHA-256 for every page. Re-running against the saved capture cache verifies
the content hash and does not need another network request.

The official event page was accepted only when its title identified the
expected venue, the page echoed the exact date and trial number, and the trial
score table was present. A candidate horse row had to match the source program
number and resolved horse ID; a trainer reference could be recorded only from
the actual `goPage3` link in that exact row. Horse names were not used as join
keys. The second `goPage3` argument is kept as `official_trainer_profile_meet`;
it is the profile's meet value and is not required to equal the event meet.

For a `-` source row, an ID is marked `verified_supplemental_trainer_id` only
when all exact event, program, horse ID, and trainer-link checks pass, the link
contains a numeric non-sentinel ID and a non-placeholder name, and API and
official finish times agree. Positive-time records are retained regardless of
pass/fail judgement. For a zero-time record, the official time must be blank or
zero. The API result flag and `api_ord` are recorded separately; ordinal is not
used to infer whether a trial was completed. The profile meet value is retained
without interpreting it as the event venue.

`0AAAAA` / `휴양마` remains a source placeholder. A KRA row that repeats that
sentinel is classified as `confirmed_same_nonperson_placeholder`, not as a
trainer identity. A personal trainer link, if one appeared on such a row,
would be kept as a conflict observation and would not be copied into the
supplemental ID field. The one `-` source row with an exact official horse row
whose trainer cell is `0AAAAA` / `휴양마` is separately classified as
`official_row_nonperson_sentinel_for_missing_source_id`.

Local RPT reports are supplemental name-only evidence. Each RPT reference
includes a source file, SHA-256, line number and exact source line when a
unique event/program row is available. RPT does not provide a trainer ID for
this review and was not used to assign one. `days_since_prior_confirmed_race`
is a descriptive calendar gap to the last earlier confirmed runner in core
DB coverage; it does not mean an official rest period or recovery duration.

## Results

| API source value | Rows | Review result |
| --- | ---: | --- |
| `-` | 84 | 61 exact official trainer IDs verified; 22 exact event pages have no source program row; 1 exact row confirms the nonperson `0AAAAA` / `휴양마` sentinel |
| `0AAAAA` / `휴양마` | 140 | All 140 exact event rows repeat the same nonperson sentinel; no trainer IDs filled |

The 61 verified rows contain 35 unique trainer IDs. All 35 occur in the core
event trainer roster. Every fill passed the API/official time check; there are
no placeholder fills or time-conflict fills.

Of the 20 `-` rows with positive API running time, one exact official result
row verifies trainer `070144` (`배휴준`) for Captain Bullet (`0043598`),
program 5 at Seoul trial 5 on 2020-08-28; API and official time are both 62.8
seconds and the official result is pass. The other 19 positive-time rows have
no source program row on their exact official event pages. The ledger also
preserves each row's API result and time independently; positive time is not
treated as a pass requirement.

All 221 distinct event pages have an exact event echo and score table, with
zero fetch errors. The 22 absent-row cases are therefore reported only as
“official event page has no source program row”; this evidence does not
establish why the row is absent. In particular, the 2013-07-27 Yeongnam trial
4 page has no program 2 row for Haylangangja even though the API record exists.
The date/trial request and event-page echo match, but the missing-row cause is
not inferred.

The local RPT scan found 206 unique exact event/program rows, 17 without a
unique matching local row, and one date's local RPT file absent. It gives
trainer-name support only and cannot resolve identities by itself. Among the
20 positive-time `-` records, 16 have an exact RPT row with a trainer name;
those names are not used to infer IDs.

Reason, no-pass reason, result status, raw time, raw ordinal, and training-day
label distributions are in `trial_trainer_gap_summary.json`. For the 140
placeholder rows, the original API reasons are preserved: 92 `주행미합(신)`,
26 `장기휴양(재)`, 9 `주행지정(재)`, 9 `연습주행`, 2 `주행심사(연속)`,
1 `주행불량(연속)(1/2)`, and 1 `장기휴양도래(재)`. Their no-pass reasons
are 82 `조교불충분`, 37 `휴양`, 7 `마체이상`, 3 `기타`, 2 `훈련불충분`,
and 9 `-`. All 140 have `api_rcTime=0`; API result flags and ordinals remain
independently recorded. Across all 224 rows, 75 have an earlier confirmed
runner in the core coverage and 149 do not; this is only a descriptive coverage
observation.

## Ledger schema and evidence files

`trial_trainer_gap_review.jsonl` has one flat JSON object per
`participant_row_id`. Key fields are:

- Identity and source: `participant_row_id`, `meet`, `date`, `trial_no`,
  `horse_program_no`, `resolved_horse_id`, `source_trNo`, `source_trName`,
  `source_api_pointer`, and source-file/hash fields.
- Unmodified API outcomes: `api_rcTime`, `api_passFlag`,
  `api_nopassReason`, `api_reason`, `api_ord`, `api_trainDays`,
  `api_daySerial`, `api_track`, and `api_weather`.
- Official exact-match evidence: event title/header/table flags, official
  horse/program identity, observed trainer ID/name/profile link/profile meet,
  official time and result, API-time/result comparisons, official row text,
  and any same-program candidate rows.
- Outcome: `review_status`, `verified_supplemental_trainer_id`, and
  `verified_supplemental_trainer_name` (nullable); placeholders never populate
  these verified fields.
- Provenance and context: `official_web_source_file`, page SHA-256, UTC capture
  time and request form; RPT source file/hash/line and row fields; descriptive
  prior race date/gap.

`official_score_page_captures.json` indexes all event page captures.
`official_score_capture_seed.json` documents the initial 2013-07-27 page
capture used to verify the historical event lookup. Raw official HTML files
are retained under `raw_official_trainer_scores/`.

## Reproduction and output hashes

From the repository root, run:

```sh
./.venv/bin/python thoroughbred/research/20261001_trial_trainer_review_v1/review_trial_trainer_ids.py --scope all
```

Final output SHA-256 values:

- `trial_trainer_gap_review.jsonl`:
  `8af724039337443b3cee5375f9951a6f39a1d9b0d9400feaa1da79a1df9f3927`
- `official_score_page_captures.json`:
  `3d8b24d9feecb119837daf50da1be164d7d8eae03dc97bfcca7db13bb5995079`
