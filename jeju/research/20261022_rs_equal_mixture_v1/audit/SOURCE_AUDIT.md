# R/S mixture source audit

Status: **PASS_SOURCE_PREFLIGHT_ONLY**. This is a source preflight only; no E mixture probabilities or metrics were created or inspected.

- Frozen contract SHA-256: `e3cd97f4c2081e23dc077bf20641e5012e39ece3a396b11fd6838bef971e13a8`.
- F1 target: 17,412 runners, 1,779 races, 269 race days (2024-01-05 to 2026-09-19); all complete 1..N ranks and inclusive T−2 history cutoffs passed.
- Both R and S raw score sources join exactly to the F1 target keys, with finite scores and no duplicate API keys. S uses the exact filter `arm == S AND role == evaluation`.
- PLC retains 1,743 races; 36 seven-runner races with unknown opening roster are quarantined only for PLC. The other six wagers retain all 1,779 races.
- R temperatures are pinned from `jeju/research/20261022_dynamic_ability_pace_v1/experiment/outputs/parameters.json#R_reference_fits` (not the unrelated F1 meta `tau`); S temperatures are pinned from `jeju/research/20261022_tb_state_transfer_v1/experiment/outputs/parameters.json#models[arm=S].temperature_fit`. Both use prior-year calibration and fixed stored values.
- Existing bootstrap schedule: `jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy` SHA-256 `d141b0c3f9a463cbfc9d1f4c61228b58757c31aee4ec74b79f41c5baeadaccbd`, shape [2000, 269]; its sorted-date inventory matches the frozen 269-date roster.
- 28 source-file facts are pinned against the existing F1/TB/joint manifests. Existing result references are hashes only: `jeju/research/20261010_style_history_ablation_v1/FINAL_RESULTS.md`, `jeju/research/20261022_tb_state_transfer_v1/experiment/RESULTS.md`, `jeju/research/20261022_tb_state_transfer_v1/experiment/outputs/report.json`, `jeju/research/20261022_joint_wager_baseline_v1/experiment/outputs/report.json`.

This 2024–2026 cohort has already been used in the earlier R/S studies. It is a repeated retrospective development period, not fresh future validation. Race-day/publication timestamps and the actual final pre-race purchase roster remain unverified. This audit does not authorize E evaluation; the new fixed 50:50 full-Q mixture remains exactly as specified by the contract.

Re-run with `.venv/bin/python -B jeju/research/20261022_rs_equal_mixture_v1/audit/source_audit.py`. The script has no CLI inputs, reads static paths only, and writes only the two files in this `audit/` directory.
