# Model card

- Version: thoroughbred_model_20260918_v1.
- Intended use: offline research candidate for race-normalized win probability; no production or betting authorization.
- Algorithm: race-balanced LightGBM soft-label cross entropy, then within-race softmax; 300 fixed boosting rounds.
- Training: 2006–2022, Seoul/Busan. Prior history includes earlier warm-up years. Six expanding annual checks 2019–2024.
- Validation: 2023–2024. Frozen route: {"SEOUL": "partial_shared", "BUSAN": "partial_shared", "YEONGCHEON": "integrated"}.
- Test: 2025-01-01 through 2026-09-13, once after selection freeze. Evaluation artifacts are immutable inputs to this report.
- Calibration: strictly within training years via held-out last training year and auxiliary model; no validation/test fit.
- Target: official first-place fractional mass in dead heats. DQ/DNF preserved as zero.
- Population: all supplied result-card entries; final-starter conditional evaluation separately. Complete historical declared-card coverage is not proven.
- Exclusions: results/current-time/odds, current weight/weather/track/equipment, unverified training/medical availability, unverified section semantics.
- Missing/unknown: train-only category vocabulary with common unknown category; numeric missing branch. No numeric interpretation of IDs.
- Data correction: derived normalization of Yeongcheon finish_raw while preserving original missing numeric ranks; see issues.json.
- Cold start: Yeongcheon uses pooled model, no independent fit; 6 races cannot validate generalization.
- Limitations: changing source coverage and class regimes, unverified exact publication timestamps of reconstructed cards, calibration transfer drift, selection across only two validation years.
- Metrics: see REPORT.md and comparison.csv; failures and small samples retained in test_slice_diagnostics.csv.
- Integrity: see preservation_check.json and manifest.json. No operational promotion.
