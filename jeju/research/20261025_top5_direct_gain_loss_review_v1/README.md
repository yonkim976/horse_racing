# Top5 gain/loss analysis: independent review

Status: **PASS; no blocking discrepancy found.** This review independently replayed the locked gain/loss analysis against its frozen sources and checked the generated tables. It did not change the source study, model, database, or registry.

## Review scope and evidence

`verify_gain_loss.py` reads the frozen baseline predictions, historical features and outcomes, original candidate choices, locked plan, bootstrap schedule, fitted model artifacts, and gain/loss outputs. It writes only `VERIFICATION.json` in this review folder.

The replay confirmed:

- 17,412 evaluation runners joined one-to-one to frozen features; all history dates respect the T−2 cutoff, and the frozen Top3 label agrees with finish position.
- All 1,779 race rosters have complete ranks and exactly three actual Top3 runners. Baseline Top5 choices replay from raw-score rank; selected-set IDs, horse numbers, captures, and outcome classes match the frozen ledgers.
- The primary cohort is 1,503 races at 900/1000/1110/1200m: 404 both-hit, 31 caught, 35 lost, and 1,033 both-miss. The 254 changed primary races split into 31 caught, 35 lost, 45 both-hit, and 143 both-miss.
- All 65 predeclared condition cells, their full-cohort denominators, outcome counts, rates, and date-bootstrap intervals match the source replay. The continuous gap summary and 16-row distance-by-outcome boundary form/style table also match; the latter contains primary races only.
- All 304 changed races across primary and secondary distances are represented in the change and energy ledgers. The 614 added/removed runner rows match the frozen feature values and actual Top3 membership. The 143 primary changed both-miss races include at least one actual Top3 outside both five-runner sets in 129 races (155 runners total); the other 14 have the actual Top3 inside the union but not together in either five-runner set.
- The full head energy of both old and new sets was rebuilt from the year-specific frozen coefficients and standardized inputs. Maximum replay error for the saved selected-set energy is `5.33e-15`; maximum decomposition residual is `8.05e-16`.

The preserved upstream manifest contains a baseline SHA metadata typo. The actual parquet SHA matches the frozen selector source audit and the new correction receipt; the old manifest was not edited. The analysis discloses this discrepancy and binds the corrected SHA.

## Interpretation for the 31/35 question

No one of the 65 fixed condition cells has a date-bootstrap 95% lower bound above zero. In particular, most selection changes occur when the raw-score fifth-to-sixth gap is small, but that stratum does not show a reliable gain. The 31 caught and 35 lost races also have similar added-runner pre-race profiles; their shared patterns do not separate the outcomes.

Two exact style-support cells have intervals fully below zero: `hist_s1f_relpos_n=4` and `hist_s1f_to_c4_pair_n=4`. Independent replay confirms both are the same four lost races: `2024-06-07_2_3`, `2024-06-08_2_4`, `2025-02-08_2_2`, and `2025-08-08_2_7`. These overlapping, posthoc views are not independent replications or a usable selection rule. The 65 intervals are descriptive and are not multiplicity-adjusted.

The main report's distinction between the candidate-union misses (129/143 both-miss changed races) and set-composition misses (14/143) is useful for framing subsequent work. It is a diagnosis of where these historical misses occurred, not evidence that a richer set objective will improve future results. Any model change should be evaluated on a new, date-separated holdout with a success criterion locked in advance. The analysis does not support deployment or a condition-based switching rule.

## Review files

- `verify_gain_loss.py`: independent replay, source/hash audit, and output checks.
- `VERIFICATION.json`: machine-readable PASS result, source hashes, denominators, overlap check, and numerical energy tolerances.
- `FINAL_REVIEW_MANIFEST.json`: hashes and byte sizes for this review's files.
