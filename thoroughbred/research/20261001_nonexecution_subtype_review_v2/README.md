# KRA nonexecution subtype review v2

Reviewed all 29 rows previously marked `reason_recorded_outcome_unclassified` in the 2026-09-29 calendar ledger. This standalone adjudication addendum does not modify the source ledger, builders, core tables, or database.

## Results

The archived official KRA mobile all-race scoretable pages contain a matching race header and the literal label `취소` for 27 of the 29 keys. These rows are reviewed as `race_cancelled`. No key in this reviewed set was classified as `race_invalid`.

Two keys remain `reason_recorded_outcome_unclassified`: Busan-Gyeongnam 2015-03-29 R5 and R6. The official 2015 KRA yearbook (printed/PDF p.63) records one event-date `경주미시행` incident on 3/29, attributes it to the entrance route being blocked after dissatisfaction with the R4 result, and says two make-up races were held. It does not enumerate R5 and R6 or distinguish cancellation from non-establishment/invalidity. The mobile all-race page and dacom11 report provide R1-R4 only; the R5/R6 PC detail requests returned HTTP 200 but blank body text. Those gaps do not resolve either key, so both remain unclassified.

For distinction, the Seoul 2023-01-15 page labels R9 `경주불성립` and R10 `취소`. The reviewed key is R10; its explicit outcome is cancellation. R9 is outside the 29-key review.

## Cause groups from the earlier KRA period-scoretable transcript

The groups below describe the recorded reason wording. They do not determine the reviewed subtype. Each specific key is listed so that mixed causes remain visible.

| Recorded cause group | Count | Exact keys |
| --- | ---: | --- |
| System or wagering disruption, including mixed weather/system issue | 3 | 1/20151108/R4, 1/20160228/R8, 3/20160228/R4 |
| Snow preventing race progress | 2 | 1/20160228/R10, 1/20160228/R11 |
| COVID-19 prevention measures | 10 | 1/20201220/R6, 1/20201220/R7, 1/20201220/R8, 1/20201220/R9, 1/20201220/R10, 1/20201220/R11, 1/20201220/R12, 1/20201220/R13, 1/20201220/R14, 1/20201220/R15 |
| Track condition or track repair | 11 | 1/20230115/R10, 1/20230506/R2, 1/20230506/R3, 1/20230506/R4, 1/20230506/R5, 1/20230506/R6, 1/20230506/R7, 1/20230506/R8, 1/20230506/R9, 1/20230506/R10, 3/20200710/R1 |
| Delay handling the preceding race incident | 1 | 1/20240929/R2 |
| Crowd obstruction after dissatisfaction with R4 result | 2 | 3/20150329/R5, 3/20150329/R6 |

## Evidence and decision rule

`raw/root_official_mobile/` contains the captured official KRA all-race HTML and extracted text for all nine event dates. The capture manifest records source URLs, HTTP 200 status, timestamps, and HTML SHA-256 hashes. The row-level `root_mobile_label_verification.json` records the matching date/race headers and adjacent labels. A literal `취소` adjacent to the keyed header supports `race_cancelled`; an explicit `경주불성립` would support an invalid/non-established subtype.

`raw/root_official_pc/` contains two captured Busan R5/R6 PC detail responses and their manifest. HTTP 200 is only transport status; the captured bodies contain no useful rendered text and provide no event classification. `raw/root_official_yearbook/` preserves the KRA 2015 yearbook PDF, article HTML, a render of p.63, and a short transcription. The yearbook supports the date-level interruption and cause, but not an exact R5/R6 subtype.

`raw/kra_dacom11/` contains byte-preserving copies of official KRA RPT files already archived in the workspace. These files show which surrounding result-report pages exist for each event date. Missing race pages alone are not evidence of cancellation or invalidity.

`reason_text` for all 29 rows comes from `thoroughbred/research/20260929_calendar_api_v1/kra_scoretable_nonfinish_reasons.csv`, the earlier official KRA period-scoretable transcription. That earlier UI session was not archived. The Busan 2015 yearbook independently corroborates the event-date cause in `supporting_reason`, while still leaving the exact race numbers and subtype unresolved. API rank/time sentinel fields were reviewed as context and were not used to infer an outcome type.

## Files

- `decisions.csv`: one row per exact `(meet, date, race_no)` key, with previous and reviewed subtype, recorded cause wording, source files/URLs, and decision notes.
- `manifest.json`: scope, counts, key validation, hashes for source inputs, raw captures, and outputs.
- `raw/`: official KRA mobile captures, PC detail captures, rendered excerpts, and copied official KRA RPTs.
- `root_mobile_label_verification.json`: row-level check of mobile page headers and outcome labels.
- `raw/root_official_yearbook/`: official yearbook evidence for the unresolved Busan event-date record.

Reviewed date: 2026-10-01.
