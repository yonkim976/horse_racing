# Pair-axis and single-anchor ticket study

This no-fit analysis reuses the saved 2024-01-05 to 2026-09-19 joint distributions. The cohort contains 1,779 races, 17,412 runners, and 269 race dates; 2026 is partial. These labels were examined in prior research, so this is retrospective development evidence, not independent future validation.

The target is the unordered exact Top3 set. A pair's exact first-and-second-place result is reported only as an observed secondary outcome; no exact-Top2 probability is estimated. Tickets anchored by a pair add the remaining member of the unordered Top3 set, without assigning that horse third place.

Both saved arms are shown separately. No preferred arm is selected from these labels. The five policies are reported at K=3 and K=4. Unrestricted K=6 is included only to confirm the original reference (407/1,779 and 423/1,779); pair-anchored K=6 is omitted because 36 seven-runner races cannot supply six unique tickets from a fixed pair.

Saved unrestricted K=6 parity reproduced: matched_baseline 407/1,779; candidate 423/1,779.

## Ticket outcomes

Rates use all 1,779 races unless a conditional denominator is named. `Mean q mass` is the saved distribution probability assigned to the selected ticket set. `Axis hit` means both anchored horses are in the actual Top3, or the single anchor is in the actual Top3. `Completion` is ticket hit among axis hits.

| Arm | Policy | K | Ticket hits / 1,779 | Hit rate | Mean q mass | Axis hits / races | Axis rate | Completion hits / axis hits | Pair exact Top2 hits / races | Pair miss | Completion miss |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| candidate | maximum_joint_pair | 3 | 246/1,779 | 13.83% | 13.17% | 422/1779 | 23.72% | 246/422 (58.29%) | 203/1779 (11.41%) | 1357 | 176 |
| candidate | maximum_k_ticket_pair_mass | 3 | 248/1,779 | 13.94% | 13.18% | 425/1779 | 23.89% | 248/425 (58.35%) | 210/1779 (11.80%) | 1354 | 177 |
| candidate | single_top3_anchor | 3 | 247/1,779 | 13.88% | 13.42% | 1020/1779 | 57.34% | 247/1020 (24.22%) | — | 759 | 773 |
| candidate | top_two_marginal_pair | 3 | 250/1,779 | 14.05% | 13.15% | 434/1779 | 24.40% | 250/434 (57.60%) | 209/1779 (11.75%) | 1345 | 184 |
| candidate | unrestricted_top_k | 3 | 248/1,779 | 13.94% | 13.42% | — | — | — | — | — | — |
| candidate | maximum_joint_pair | 4 | 292/1,779 | 16.41% | 16.18% | 422/1779 | 23.72% | 292/422 (69.19%) | 203/1779 (11.41%) | 1357 | 130 |
| candidate | maximum_k_ticket_pair_mass | 4 | 291/1,779 | 16.36% | 16.19% | 421/1779 | 23.66% | 291/421 (69.12%) | 208/1779 (11.69%) | 1358 | 130 |
| candidate | single_top3_anchor | 4 | 300/1,779 | 16.86% | 16.71% | 1020/1779 | 57.34% | 300/1020 (29.41%) | — | 759 | 720 |
| candidate | top_two_marginal_pair | 4 | 299/1,779 | 16.81% | 16.15% | 434/1779 | 24.40% | 299/434 (68.89%) | 209/1779 (11.75%) | 1345 | 135 |
| candidate | unrestricted_top_k | 4 | 302/1,779 | 16.98% | 16.76% | — | — | — | — | — | — |
| candidate | unrestricted_top_k | 6 | 423/1,779 | 23.78% | 22.58% | — | — | — | — | — | — |
| matched_baseline | maximum_joint_pair | 3 | 236/1,779 | 13.27% | 13.14% | 429/1779 | 24.11% | 236/429 (55.01%) | 203/1779 (11.41%) | 1350 | 193 |
| matched_baseline | maximum_k_ticket_pair_mass | 3 | 236/1,779 | 13.27% | 13.14% | 429/1779 | 24.11% | 236/429 (55.01%) | 203/1779 (11.41%) | 1350 | 193 |
| matched_baseline | single_top3_anchor | 3 | 233/1,779 | 13.10% | 13.35% | 1023/1779 | 57.50% | 233/1023 (22.78%) | — | 756 | 790 |
| matched_baseline | top_two_marginal_pair | 3 | 236/1,779 | 13.27% | 13.14% | 429/1779 | 24.11% | 236/429 (55.01%) | 203/1779 (11.41%) | 1350 | 193 |
| matched_baseline | unrestricted_top_k | 3 | 233/1,779 | 13.10% | 13.35% | — | — | — | — | — | — |
| matched_baseline | maximum_joint_pair | 4 | 294/1,779 | 16.53% | 16.18% | 429/1779 | 24.11% | 294/429 (68.53%) | 203/1779 (11.41%) | 1350 | 135 |
| matched_baseline | maximum_k_ticket_pair_mass | 4 | 294/1,779 | 16.53% | 16.18% | 429/1779 | 24.11% | 294/429 (68.53%) | 203/1779 (11.41%) | 1350 | 135 |
| matched_baseline | single_top3_anchor | 4 | 296/1,779 | 16.64% | 16.67% | 1023/1779 | 57.50% | 296/1023 (28.93%) | — | 756 | 727 |
| matched_baseline | top_two_marginal_pair | 4 | 294/1,779 | 16.53% | 16.18% | 429/1779 | 24.11% | 294/429 (68.53%) | 203/1779 (11.41%) | 1350 | 135 |
| matched_baseline | unrestricted_top_k | 4 | 298/1,779 | 16.75% | 16.71% | — | — | — | — | — | — |
| matched_baseline | unrestricted_top_k | 6 | 407/1,779 | 22.88% | 22.58% | — | — | — | — | — | — |

## Primary paired comparisons

The primary comparison is maximum-joint-pair minus unrestricted top K within each saved arm at K=3 and K=4. Intervals use 2,000 paired race-date cluster bootstrap draws, seed 20261010. No multiplicity-adjusted claim is made.

| Arm | K | Hit-rate difference | 95% race-date bootstrap interval |
|---|---:|---:|---:|
| matched_baseline | 3 | +0.17%p | [-0.46, +0.79]%p |
| matched_baseline | 4 | -0.22%p | [-1.18, +0.68]%p |
| candidate | 3 | -0.11%p | [-0.83, +0.61]%p |
| candidate | 4 | -0.56%p | [-1.51, +0.39]%p |

Across the four primary comparisons, the estimated differences ranged from −10 to +3 hits per 1,779 races, and every 95% interval included zero. These results do not show a reliable same-budget gain from fixing the maximum-joint pair. The pair axis itself hit in about 24% of races, so pair misses accounted for most pair-ticket misses. The single-horse axis hit in about 57%, while only about 23–29% of those axis hits completed a selected K=3 or K=4 ticket; this descriptive pattern leaves full-trio completion as a substantial constraint.

## Axis probability checks

Only maximum-joint-pair and single-Top3-anchor axes receive probability diagnostics. Fixed probability bins, cutoffs, and score-ranked coverage tables are descriptive. A score-ranked coverage slice is retrospective and does not guarantee the same future coverage.

| Arm | Policy | Races | Axis Brier | Mean predicted axis probability | Observed axis hit rate |
|---|---|---:|---:|---:|---:|
| candidate | maximum_joint_pair | 1779 | 0.173373 | 0.2361 | 23.72% |
| candidate | single_top3_anchor | 1779 | 0.232734 | 0.5763 | 57.34% |
| matched_baseline | maximum_joint_pair | 1779 | 0.175591 | 0.2367 | 24.11% |
| matched_baseline | single_top3_anchor | 1779 | 0.233250 | 0.5789 | 57.50% |

Fixed-bin counts and rates, fixed prediction-cutoff coverage, score-ranked coverage slices, and selected-ticket-mass bins are in the companion CSV files.

## Limits

All results are post hoc summaries of saved probability distributions and previously examined races. They do not establish independent future performance, finish-order probabilities, exact-Top2 calibration, odds value, returns, or operating readiness. Ticket hits, axis hits, conditional completion, exact-Top2 empirical hits, and predicted q mass are different quantities.
