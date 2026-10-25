# F1_STYLE6 debut-cohort running-trial source audit

This read-only audit freezes the available API20 running-trial records linked to the existing F1_STYLE6 `observed_starts == 0` cohort. It does not establish that these horses are lifetime first-time starters: the label means no prior *started* result was present under the frozen F1 source definition. The baseline is unchanged, the cohort spans all target race distances, and horse 3005648 remains excluded as it was in the baseline.

## Source and cutoff contract

The source is KRA OpenAPI API20 `ridingTestResult_1`, represented by `running_trial_rows` joined to raw `api_records` and `source_artifacts`. Only explicit native-label Jeju rows (`meet_code=2`, raw `meet=제주`, raw `majong=제주`, `breed_assessment=api_native_label`) are included. API21 starting exams are unrelated and excluded. Current profile attributes (including current name, age, sex, or affiliation) are never joined or copied into candidate inputs.

For each frozen target race, the historical cutoff is exactly `race_date - 2 days`, inclusive. A target horse's registered trial-event records up to that date are ordered by `(trial_date, trial_number)`, with latest record slot rank 1; separate `trainNo` values on the same date remain separate slots. Raw `daySerial` is retained and checked for within-key invariance. The event key is `(trial_date, meet_code, trial_number)`, mapped from API20 `trainDate`, requested meet 2, and `trainNo`; the participant natural key used by the local importer is `trainDate|2|trainNo|chulNo|hrNo`.

An observed relative-time candidate is eligible only when the target and at least two other explicit-Jeju horses in the same validated event each have finite positive `rcTime`, integer `ord` from 1 through 89, and `passFlag` in the observed allowlist: `합격`, `불합격`, `주행불합격`, `출발불합격`, `불합격(능검)`, `발주불합격`, or `불합격(발검)`. The candidate value is `(target rcTime - median(other eligible peer rcTime)) / median(other eligible peer rcTime)`. It is same-event and unitless; raw seconds are not pooled across events, distances are not inferred, and API20 trial times are not converted to race times.

Rows with cancellation, exclusion, stop, special `ord`, zero/missing/non-finite time, or unrecognized judgment remain in target registered-record counts and the latest-three record lineage. Those counts are not counts of completed or performed trials. The judgment allowlist is a conservative source-screening rule, not a claim that the accessible official API metadata publishes a complete judgment enum or formal semantics for each label.

Exact raw API20 payloads are retained for source reproducibility, including age/sex fields recorded on the trial item if present. These raw fields are not part of the proposed four-column candidate feature bundle; a current-profile join is never performed.

## Findings

- Frozen cohort: 1,946 starts from 1,946 horses in 641 races; every target has exactly one frozen target row and every history cutoff is `T-2`. No prior-start row exists in the frozen baseline or current DB for these targets. The current DB contains 47 prior non-starter result rows for 44 horses (finish codes 94, 95, and 99); this is why `observed_starts=0` must not be presented as a verified lifetime-debut label.
- Trial coverage through individual `T-2`: all 1,946 targets have at least one registered API20 record; the lineage contains 3,500 target records and 961 linked event keys.
- Linked events have 8,824 same-event explicit-Jeju roster rows for 3,194 horses (6–12 entries/event). All 961 keys have consistent `daySerial`, raw date/number match, Jeju `meet`/`majong`, and native-label assessment. There are no duplicate horse rows or duplicate participant natural keys, and no natural key with differing payload hashes.
- Of 3,500 target records, 3,413 meet the source-screening rule; 87 have zero `rcTime` and an unusable order/status combination. The latest-three lineage has 3,240 slots (some targets have fewer than three source records), 3,168 of which have eligible relative-time peer support. Invalid/cancelled rows are retained and not backfilled around.
- The current explicit-Jeju API20 inventory has 15,831 records through 2026-10-15. `rcDist` is absent in all 15,831 raw payloads. `rcTime` is present in all, with 440 zero and 15,391 positive values. The event-relative formula therefore avoids an unsupported distance assumption.
- Scoped source fingerprints were captured before, within the extraction transaction, and after; the linked API20 rows, source-artifact provenance, and target prior-race rows remained stable across all three captures. This is a scoped comparison, not a whole-database hash. Linked API20 artifacts were retrieved on 2026-09-29; historical public-availability timestamps were not established, so the T-2 cutoff is retrospective event-date filtering only.

## Frozen artifacts

The `outputs/` directory contains:

- `cold_target_roster.parquet`: one row per frozen target, with F1/baseline identity, prior-race audit, record counts, and latest-three summary. No current profile fields.
- `api20_trial_event_rows.parquet`: one row per linked event participant, including exact `payload_json`, payload hash, normalized API20 fields, row-validity flags, event key checks, and source response/artifact provenance. This is the full peer roster used to independently reconstruct eligibility and peer medians.
- `cold_target_trial_lineage.parquet`: one row per target horse-event record through its strict cutoff; includes latest-record rank, raw order/time/judgment, hold reasons, source hashes, and event key.
- `trial_event_relative_peer_ledger.parquet`: one row per target event record with same-event eligible peer IDs, median, relative-gap candidate, and eligibility.
- `trial_event_key_audit.parquet`: one row per linked normalized event key, with raw-key invariants, roster size, duplicates, and valid-time peer count.
- `cold_target_prior_race_history_audit.parquet`: target-linked prior race-result rows for verifying cold-label interpretation.
- `source_artifacts.json`: distinct source artifact records with request parameters, retrieval timestamp, source URL/endpoint, response hashes, and raw path references.
- `audit_summary.json` and `audit_manifest.json`: compact counts/contracts, input hashes, output hashes, exact allowlist, source references, and scoped before/during/after fingerprints.

Raw values are exact in `payload_json`; text/JSON companion columns make heterogeneous API scalars Parquet-safe. Treat the payload as source evidence and recompute derived columns when consuming the bundle. The source audit intentionally does not fit a model or compare predictive outcomes. Candidate use requires leakage, temporal, cohort, and ablation review in the separate model task.

## Reproduction

From the repository root, run:

```sh
.venv/bin/python jeju/research/20261018_debut_trial_source_audit_v1/audit_source.py
```

The script opens SQLite with URI `mode=ro`, sets `PRAGMA query_only=ON`, reads related source rows and provenance within one explicit transaction, and refuses to overwrite a non-empty `outputs/` directory. It writes only under this audit folder.

## Source references

- Existing F1 baseline/features: `../20261010_style_history_ablation_v1/README.md` and its frozen `outputs/features.parquet`.
- API20 collection history: `../20260929_trial_api_backfill_2003_2025/README.md`.
- Local parser field mapping: `../../scripts/build_native_core_from_api_raw.py`.
- Current source contract and inventory: `../20261007_foundation_v1/SOURCE_CONTRACT.md` and `trial_inventory.json`.
- Official public dataset entry: [KRA API20 running-test detailed results](https://www.data.go.kr/data/15056974/openapi.do). The accessible API description lists event, entry, judgment/reason, and time-related result fields but does not expose a raw distance field or the complete judgment enum/semantics.
- Official 2024 Jeju race plan: [Jeju plan PDF](https://race.kra.co.kr/down/raceplan_2024_jeju.pdf). Distance rules vary by breed and period, which is not enough to infer a per-event distance missing from the API20 payload.
