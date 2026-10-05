# Thoroughbred prospective shadow intake

This directory contains immutable, research-only pre-race inputs for the next
available thoroughbred cards. It does not activate a production model, publish
probabilities, place bets, or write to the production database.

## Frozen future cards

The audit clock was 2026-09-18 14:11 KST. The canonical snapshots are:

| Venue | Date | Races | Entries | Official source observed (UTC) | Scheduled span (UTC) |
|---|---:|---:|---:|---|---|
| Seoul | 2026-09-19 | 10 | 109 | 2026-09-17T11:38:08.173Z | 01:35–08:55 on 2026-09-19 |
| Seoul | 2026-09-20 | 11 | 120 | 2026-09-17T11:39:01.245Z | 01:35–08:55 on 2026-09-20 |
| Yeongcheon | 2026-09-20 | 6 | 65 | 2026-09-17T11:39:37.505Z | 03:45–07:30 on 2026-09-20 |

Each snapshot joins the official entry-sheet response, which supplies horse,
jockey, trainer, and owner IDs, to the official gate card. Source `totalCount`,
per-race declared field size, joined counts, official scheduled times, and the
read-only production SQLite counts must all agree. The three canonical
snapshots cover 27 races and 294 entries without missing horse or jockey IDs.

Busan 2026-09-18 is excluded from the whole-card prospective set. Its first
scheduled race was 11:15 KST, before the 14:11 KST audit. Treating the complete
card as newly prospective would therefore mix already-started races with future
races.

The six raw files were copied byte-for-byte from the project's official KRA raw
store. Their original retrieval milliseconds in the filenames are preserved as
`observed_at_utc`; the copy time is separately recorded as `created_at_utc`.
They are not described as fresh 2026-09-18 HTTP observations. A bounded fresh
request through the configured project client was attempted, but the official
endpoint timed out after its configured retries. No response from that attempt
was saved and the earlier records were not restamped.

## Feature artifact

`features/future_20260919_20_base38_v2_verified.parquet` contains 294 rows and
27 complete race groups. It includes the 38 v1 scheduled-card/prior-history
features and all 34 features from `code/features_v2.py`. The history source is
the read-only unified DuckDB and is capped strictly before the target date; its
latest confirmed source date is 2026-09-13. The audited Yeongcheon numeric
`finish_raw` fallback is applied only in derived history, leaving the source
unchanged. The artifact has no target, result, odds, dividend, current weather,
current track, or race-day body-weight columns.

## Timing and immutability contract

A prediction ledger is accepted only when:

1. every source observation is at or before the prediction timestamp;
2. the prediction timestamp is before every included race's official scheduled
   start;
3. every snapshot runner has one and only one probability row;
4. probabilities are finite, within `[0,1]`, and sum to one per race;
5. model and feature artifacts exist and are content-hashed; and
6. neither the card nor prediction row contains labels, outcomes, odds, or
   unverified current-condition inputs.

All writers use exclusive creation. An existing artifact is never replaced.
Identical official raw bytes may be reused, but differing content at the same
path is rejected.

## Commands

Import a timestamped official card while preserving its original observation:

```bash
.venv/bin/python data/research/thoroughbred_win_research_20260918_v2/code/shadow.py \
  import-local --date 20260919 --meet 1 \
  --entry data/raw/kra/entry_sheet/2026/09/19/meet_1/run_15433/page_0001_1789645085039_ac285938c858.json \
  --gate data/raw/kra/gate_entry_sheet/2026/09/19/meet_1/run_15434/page_0001_1789645088173_f1d89a6f0d63.json \
  --database data/horse_racing.sqlite3 \
  --output-root data/research/thoroughbred_win_research_20260918_v2/shadow
```

Build the base-38 plus v2 feature artifact from one or more snapshots:

```bash
.venv/bin/python data/research/thoroughbred_win_research_20260918_v2/code/shadow.py \
  build-features --snapshot SNAPSHOT.json \
  --unified-db data/research/thoroughbred_unified_20260918/thoroughbred_unified.duckdb \
  --features-module data/research/thoroughbred_win_research_20260918_v2/code/features_v2.py \
  --output NEW_FEATURE_ARTIFACT.parquet
```

An external normalized card can be accepted only with an explicit observation
timestamp already embedded in it and an explicit prospective prediction time:

```bash
.venv/bin/python data/research/thoroughbred_win_research_20260918_v2/code/shadow.py \
  accept-external --input OBSERVED_CARD.json \
  --prediction-at 2026-09-19T00:00:00Z --output NEW_SNAPSHOT.json
```

Freeze model probabilities after inference has produced complete JSON rows:

```bash
.venv/bin/python data/research/thoroughbred_win_research_20260918_v2/code/shadow.py \
  freeze-predictions --snapshot SNAPSHOT.json --predictions ROWS.json \
  --prediction-at 2026-09-19T00:00:00Z --model MODEL_ARTIFACT \
  --features FEATURE_ARTIFACT.parquet --output NEW_LEDGER.json
```

The tests cover overwrite refusal, partial source pages and race groups, missing
official IDs, label/odds/current-condition rejection, complete probability
groups, and both sides of the observation/prediction/start-time ordering.
