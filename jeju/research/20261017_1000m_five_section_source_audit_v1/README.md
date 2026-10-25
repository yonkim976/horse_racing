# Jeju 1000 m five-section source snapshot

This is a read-only, provenance-pinned source bundle for the 1000 m five-interval study. It preserves the exact saved F1 target and `last5_same_source_ids` lineage; no history was reselected, no invalid slot was backfilled, and no model was fitted. The source SQLite database was opened with URI `mode=ro` and `PRAGMA query_only=ON`; the quality view was scanned once in one transaction. API6 race-level leader checkpoints were not used as per-horse times.

The saved target population has 14,457 horse rows in 1,424 races, from 2017-01-14 through 2026-09-19, excluding horse ID 3005648. Its exact last-five lineage contains 53,828 slots, 13,060 targets with at least one slot, and 14,193 unique historical API4 records. The section snapshot has 16,352 unique rows: targets/history plus all 16,247 started runners in the 1,607 referenced source races. Current `race_result_rows` and the baseline candidate snapshot matched exactly in all 16,348 event rows; all 16,247 started API IDs and their horse IDs/program numbers matched in all 1,607 races. Starter codes follow the inherited rule (finish position 1–89 or 91/92).

The measured interval formulas are:

- `seg_0_200 = S1F`
- `seg_200_to_c3_approx400 = C3 - S1F`
- `seg_c3_approx400_to_c4_approx600 = C4 - C3`
- `seg_c4_approx600_to_800 = finish_time - G1F - C4`
- `seg_800_to_1000 = G1F`

KRA’s Jeju glossary labels S1F as the first 200 m, 3C as approximately 600 m remaining, 4C as approximately 400 m remaining, and G1F as the last 200 m. Therefore C3/C4-derived labels retain “approximately”; no exact physical sensor location is claimed. See the [official KRA Jeju glossary](https://race.kra.co.kr/raceScore/scoretableLayerExplanation.do?meet=2).

Each interval retains raw seconds, endpoint-measurement eligibility, full-race point-mask result, positive-delta quality eligibility, F1 `valid_time` feature eligibility, and the final masked feature value. All five segment deltas sum to finish time on every slot with five finite deltas and a finite finish-time endpoint (see `five_segment_additive_identity` in `source_audit.json`). G3F is stored only as the independent diagnostic `finish_time - C3 - G3F`, not as a sixth interval. A source slot contributes only when its inherited `valid_time=True`; known failed time statuses/values, nonpositive or nonmonotone deltas, blocked point masks, or invalid baseline time leave that segment null. Other segments remain independently usable.

Race-point masks use the exact started roster from current `race_result_rows` and require exact API4 status-row ID and horse identity coverage. Group statuses are pinned to the API303 record selected in the quality view; its ID must be consistent across the full started roster, and the one selected point row’s payload, artifact, page hash/path, and group status must match the quality-view attachment. Missing/unknown/held status fails closed. Known explicit unavailable statuses are retained as recognized domain values; they do not count as positive time endpoints.

`source_audit.json` contains target/source counts, status domains, mask and segment availability, source snapshot fingerprint parity, input file hashes, and output hashes. `artifact_manifest.json` freezes those input/output identities and the audit JSON hash. `target_last5_section_intervals.parquet` is the main modeling handoff; `target_last5_lineage.parquet` and `api4_quality_source_snapshot.parquet` retain its IDs and source evidence.
