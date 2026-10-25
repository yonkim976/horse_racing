# S40–G47 pre-train review

**PASS_PRE_TRAIN_REVIEW_NO_FIT.** The input artifact, source contract, experiment code bundle, root independent verification, and no-fit structural preflight were checked against their frozen hashes. No candidate model was fit, and no candidate probabilities or outcome metrics were produced. This review does not authorize execution.

The root verifier independently checked 52,155 runners across 5,206 races, 403,224 selected historical slots, and 365,085 feature cells; its maximum formula difference was 8.88×10⁻¹⁶. The consumer preflight independently accepted the same artifact and code pins, confirmed the 1,779-race evaluation cohort and fixed per-pool denominators (PLC 1,743; each other pool 1,779), quarantined 36 PLC races, and projected 26,983,089 study bytes against the 40,000,000-byte cap.

Static review found the single comparison follows the frozen S40 splits, weights, categorical vocabularies, PL calibration/evaluation, score replay and gate. G alone adds seven numeric inputs and uses six LightGBM calls, three final models, and three temperature optimizations; saved S40 raw scores and temperatures are reused with zero S refits or temperature optimizations.

Publication and revision timestamps remain unverified, so T−2 does not prove pre-race availability. The cohort is retrospective and result-conditioned, and the features represent historical first-group tendencies and horse-number interactions rather than calibrated current-race probabilities or verified physical gate pressure. Execution still requires the supervisor’s separate hash-bound one-run approval and root pre/post integrity checks.

See [PRE_TRAIN_REVIEW.json](PRE_TRAIN_REVIEW.json) for the exact artifact, verifier, preflight, and code hashes.
