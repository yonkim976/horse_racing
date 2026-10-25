# 1000m five-section ablation: independent design review

Review date: 2026-10-17  
Scope: read-only source, temporal leakage, feature arithmetic, and training-contract review. No source, feature, or model artifacts were changed by this review, and no model was fitted.

## Conclusion

I found no concrete blocker to the separately authorized three-fold candidate fit. The frozen source bundle reconciles to the saved F1 lineage and current started rosters, the five interval calculations and aggregation preserve the stated feature contract, and the prepared pre-fit receipt reports a passing, hash-locked feature table with no candidate scores or outcome metrics.

This is an event-time retrospective ablation. The inputs establish that each historical source race is at least two calendar days before its target race, but they do not establish when the API4 values or any later website correction became available to a bettor or model. The existing F1 source audit also states that its post-race cohort does not prove public availability at prediction time. This limitation does not prevent the retrospective fit, but it prevents interpreting this test as a live as-of evaluation without archived acquisition/review timestamps.

## Source and feature checks

The frozen source audit contains 14,457 1000m target rows in 1,424 races and 53,828 exact saved-F1 last-five slots. It includes the 16,247 started runners from 1,607 referenced source races. Its current `race_result_rows` comparison matches the baseline snapshot for all 16,348 event rows and all 16,247 started IDs, horse IDs, and program numbers in all 1,607 races.

For each of four race points, the audit reports exact started-runner API4 status-row ID sets and horse identity matches in 1,607/1,607 races. The selected API303 record is consistent across each started roster; each point has exactly one selected record row and that row’s payload, artifact, page hash/path, and status match the quality-view attachment in 1,607/1,607 races. The resulting point masks clear 1,604 S1F, 1,607 C3, 1,606 C4, and 1,606 G1F race-points. Blocked points remain masked for every runner in that race-point.

The extractor pins API4 source record type, artifact, payload, page hash, and path before and after its single read-only quality-view scan. All 16,453 fingerprint rows match; `source_audit.json` records SQLite URI `mode=ro`, `query_only=ON`, one quality-view scan, and explicitly does not claim that the whole database was unchanged. The source manifest’s nine output files and three input files pass SHA-256 and byte-count checks, and its audit JSON hash matches.

The five intervals are implemented as `S1F`, `C3−S1F`, `C4−C3`, `finish−G1F−C4`, and `G1F`. The source audit reports that all 53,820 rows with five finite intervals and a finite finish time sum to finish time within `1e-10` seconds; maximum observed absolute residual is approximately `1.42e-14` seconds. C3/C4 boundaries are labeled approximate. G3F remains a separate identity diagnostic.

The feature aggregator enforces the exact saved last-five IDs and slot order, same horse, started status, same 1000m distance, source date no later than target date minus two days, and `valid_time=True` for every contributed slot. Invalid slots remain in lineage and are not backfilled. It verifies feature seconds against the frozen raw interval formulas, emits NULL mean/n for non-1000m rows, and emits mean NULL/n=0 for 1000m rows without a usable observation. The prepared output preserves the original 30 columns and row order exactly, then appends the ten agreed numeric fields. The pre-fit receipt reports 52,155 rows, 65 total columns, 5,013 1000m evaluation runners across 508 races, and a 53,828-row history ledger.

The frozen source audit reports three baseline `valid_time=False` source rows; the feature gate excludes them while retaining their slots. Across the five features, eligible history support ranges from 53,743 to 53,781 slots, so the result is based on the predeclared quality-filtered history rather than complete coverage. This support variation is expected under segment-specific endpoint and point masks and should be reported with the evaluation.

## Training and metric checks

The candidate keeps the existing all-distance 52,155-row cohort and the baseline 30 inputs, adding only the ten section mean/count fields. Its folds are chronological: initial training through Y−3, early stop on Y−2, refit through Y−2, calibration on Y−1, and evaluation on Y. The target remains binary runner Top3; training weights remain `1/field_n`; the existing calibration and additive Top3 construction are reused. The code caps the experiment at three candidate models, six LightGBM training calls, and three temperature optimizations, and refuses to overwrite an existing fit.

The primary metric is correctly defined as runner-level binary Top3 log loss and Brier, averaged within each race and then equally across races; the candidate-minus-saved-F1 sign convention is explicit. Canonical six-combination categorical NLL is an auxiliary metric. The fixed 2,000×269 date bootstrap schedule is hash-pinned. Saved F1 replay passed exactly: all 17,412 runners, 1,779 races, 10,674 canonical max-six sets, raw scores, runner probabilities, and recorded race metrics were reproduced with zero maximum numerical error. Baseline retraining and candidate outcome metrics are both recorded as false in the pre-fit receipts.

## Frozen evidence

- Source manifest SHA-256: `6f3e9e6d8111c4c85021c02e4086f4f2a2750df5c2f5e63f256b63506397cda5`
- Source audit SHA-256: `50a819b323653094a110eed9b22d67512953595926153ece06af2dc8f3141e99`
- Source preflight SHA-256: `b2dec82847f6dab13505965d1a3073d83266dd6cc5f28ab12a57ebbf120ead8f`
- Prepared lock SHA-256: `81c90fe61596ef1c959e54ef12ec0d7a0e7a5321a5c30e681989138e7224e981`
- Prepared feature table SHA-256: `bfa6c8535b0cb7c334ad5e60bde12a7d9ad72e3351068a29bafc227f80cfe94c`
- Baseline replay receipt SHA-256: `64d3160c4cf0a7da1b210f8763a8c94e8559df9f034549ed1f55dd51d858960a`

The pre-fit receipts pin the contract/code and inputs listed above. Any subsequent change to those artifacts requires a new review against the updated lock before candidate fitting.
