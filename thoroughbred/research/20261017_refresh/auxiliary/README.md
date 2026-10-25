# Thoroughbred auxiliary refresh adapters

This folder documents the official KRA families normalized by
[`thoroughbred/refresh/auxiliary.py`](../../../refresh/auxiliary.py). The
adapter creates public request descriptors and transforms one captured API row;
the shared refresh collector owns transport, complete-page verification, raw
page files, provenance, and storage.

## Source families

| Family | Official endpoint | Query partition | Row date | Meet scope |
| --- | --- | --- | --- | --- |
| Daily training | API18_1 `dailyTraining_1` | `meet` + `tr_month` | `trDate` | 1, 3 |
| Starting training | API22_1 `startingTranning_1` | `meet` + `tr_month` | `trDate` | 1, 3 |
| Swim training | API216 `SwimTr` | `tr_date` | `trDate` | 1, 3 rows; other meets are out of scope |
| Starting exam | API21_1 `startingTestResult_1` | `meet` + `tr_year` | `trainDate` | 1, 3 |
| Medical | API16_1 `raceHorseClinic_1` | `meet` + `clinic_year` | `clinicDate` | 1, 3 |
| Horse profile | API8_2 `raceHorseInfo_2` | `meet` + `act_gubun=y` | capture date | 1, 3 |
| Jockey profile | API307 `jockeyInfo` | `meet` | capture date | 1, 3 |
| Trainer profile | API308 `trainerInfo` | `meet` | capture date | 1, 3 |
| Owner profile | API309 `horseOwnerInfo` | `meet` | capture date | 1, 3 |

Monthly and yearly response partitions can contain rows outside the requested
window. The caller must apply each request's inclusive `event_start` and
`event_end` after validating every page. `event_date` always means the source
event date for event families. For profile families it means the KST date of
the successful capture, and `profile_observed_date` records that same value;
birth, debut, registration, and affiliation dates remain separate profile
fields.

## Identity and preservation rules

- Event natural keys contain the date, meet, official horse ID, and source row
  components that distinguish the event. They do not use capture/page location
  as an identity component. Identical source rows can therefore share a key;
  storage must preserve their observed multiplicity.
- Medical keys include hospital and both raw diagnosis slots so a horse can
  have multiple distinct treatment rows on one date. A later changed payload
  under the same key is a correction observation.
- API21 `trainNo` is retained as `test_no`; it is not a race number. The source
  row fields including session/day serial, program number, names, IDs, pass
  flag, and both reason fields remain available in the normalized output.
- API18 `prNo` and `prGubun` remain source-reported rider identity evidence.
  Current jockey profiles do not fill historical daily-training names or IDs;
  the limited historical name supplement remains the pre-existing
  080626-only source.
- Profile rows are current directory observations keyed by official ID, query
  scope, and capture date. Current horse trainer/owner relationships and person
  affiliations must not be attached to historical race, medical, training, or
  exam events. API307/308/309 performance totals stay in the immutable captured
  pages and are excluded from normalized person profile payloads.
- No owner or trainer relationship is inferred from historical names. Raw
  official IDs are converted to text without padding or name-based matching.

The caller controls date windows: manual history is confirmed through
2026-10-16; daily and weekly future windows are supplied by the refresh
scheduler. Current profile queries are capture-time snapshots and are not
limited by an event date window.

`iter_baseline_rows(connection, start_iso, end_iso)` reads existing research
observations through the caller's already-open read-only connection. It clamps
the input to the last 60 days ending on `end_iso`, reads only API18/API22/API216
training rows, API16 current annual rows, and API21 starting exams, and yields
each as `baseline=true`. It does not seed prior profile snapshots. A stored
source hash is carried only when its local source page exists under the
repository and matches the digest; otherwise the normalized table's raw payload
is retained without a verified hash claim.

The read-only baseline iterator was checked against the core database for the
60-day window 2026-08-18 through 2026-10-16. Per-family source query counts and
iterator counts matched for all five event families; all raw payloads parsed,
source files and hashes were verified, and no inferred daily rider names were
added. See [baseline validation results](baseline_validation_20261017.json).
The separate 31-row `080626` event-name supplement and 70-ID unmatched rider
ledger (69 other IDs) remain present, with no global profile link for `080626`.
