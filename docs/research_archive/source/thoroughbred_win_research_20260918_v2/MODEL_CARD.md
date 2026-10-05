# Thoroughbred win research v2

Selected research candidate: H3_relative. Intended use: offline comparison and immutable pre-race shadow predictions only.

- Targets: fractional dead-heat winner mass; DQ/DNF kept as zero. Full preserved card and final-starter conditional metrics reported separately.
- Inputs: baseline38 plus predeclared historical form/Elo/speed/relative groups. No odds, current weight/going/weather, medical, training, or steward events.
- Algorithm: deterministic LightGBM cross_entropy; FIT-only vocab and native missing branches; Q3 iteration selection; Q4 temperature on exactly that fixed model; race softmax.
- Selection: development2021–2024, gated pervenue and multi-year improvement against matched B0. 2025/26 previously-exposed reference only.
- Future: 27 races294entries, preserved9/17officialcards, latestmodelhistory9/13; no future results or validated profitability yet. No automatic production promotion.
- Limitations: historical publication timestamps reconstructed; Elo updates use ranked finishers only; missing prior records and unmatched/new IDs; old source regimes; six historical Yeongcheon races insufficient for generalization; current card changes may exist after preserved observations.
- Artifacts and validation: REPORT.md, feature_audit.json, verification.json, preservation_check.json, manifest.json.
