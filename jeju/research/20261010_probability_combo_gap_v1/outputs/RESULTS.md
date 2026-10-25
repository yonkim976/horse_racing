# Saved-score probability and six-ticket gap results

This report analyzes the frozen 1,779-race / 17,412-runner / 269-day retrospective cohort. It does not fit a model, search tau, or change ticket selection.

## Saved-output parity and invariance checks

Reproduction used 3558 variant-races and 21348 saved canonical ticket rows. The detailed exact-tolerance checks are in `parity_verification.json`.

| variant | races | ticket_order_exact | max_ticket_probability_abs_diff | max_marginal_abs_diff | saved_tau_rank_mismatch_races | saved_tau_rank_mismatch_triples | saved_tau_top6_mismatch_races | tau1_rank_mismatch_races | tau1_rank_mismatch_triples | tau1_top6_mismatch_races | p_score_order_violations_saved_tau | p_score_order_violations_tau1 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| F1 | 1779 | True | 0.000000 | 0.000000 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| F1_STYLE6 | 1779 | True | 0.000000 | 0.000000 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

A positive temperature preserves a model's energy ordering mathematically; any reported rank difference is retained as a floating-point tie/order diagnostic. Tau=1 results are temperature diagnostics, not a new model-performance decision.

## Race-equal averages by fixed cohort strata

Losses and rates below are race means. `hit_at_10` and `hit_at_20` are rank diagnostics; only `six_hit` is the six-ticket hit result.

| scope | value | variant | races | joint_true_nll_saved_tau | full_joint_brier_saved_tau | top3_marginal_log_loss_saved_tau | top3_marginal_brier_saved_tau | six_mass_saved_tau | six_hit | hit_at_1 | hit_at_3 | hit_at_6 | hit_at_10 | hit_at_20 | true_triple_rank |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| overall | all | F1 | 1779 | 4.298868 | 0.979955 | 0.569469 | 0.192724 | 0.225091 | 0.223159 | 0.062957 | 0.131535 | 0.223159 | 0.323215 | 0.509837 | 30.281057 |
| overall | all | F1_STYLE6 | 1779 | 4.287044 | 0.979447 | 0.568159 | 0.192256 | 0.230067 | 0.228780 | 0.060146 | 0.130972 | 0.228780 | 0.341765 | 0.514334 | 30.026981 |
| year | 2024 | F1 | 637 | 4.376089 | 0.982121 | 0.568598 | 0.191952 | 0.216382 | 0.215071 | 0.050235 | 0.128728 | 0.215071 | 0.309262 | 0.486656 | 32.637363 |
| year | 2024 | F1_STYLE6 | 637 | 4.359765 | 0.981321 | 0.566793 | 0.191229 | 0.225155 | 0.235479 | 0.051805 | 0.124019 | 0.235479 | 0.329670 | 0.491366 | 32.343799 |
| year | 2025 | F1 | 654 | 4.286355 | 0.979557 | 0.567216 | 0.191741 | 0.209764 | 0.214067 | 0.068807 | 0.129969 | 0.214067 | 0.318043 | 0.509174 | 29.055046 |
| year | 2025 | F1_STYLE6 | 654 | 4.276779 | 0.979138 | 0.566143 | 0.191392 | 0.209561 | 0.211009 | 0.065749 | 0.128440 | 0.211009 | 0.350153 | 0.518349 | 28.990826 |
| year | 2026 | F1 | 488 | 4.214840 | 0.977659 | 0.573624 | 0.195050 | 0.257001 | 0.245902 | 0.071721 | 0.137295 | 0.245902 | 0.348361 | 0.540984 | 28.848361 |
| year | 2026 | F1_STYLE6 | 488 | 4.205875 | 0.977414 | 0.572646 | 0.194754 | 0.263960 | 0.243852 | 0.063525 | 0.143443 | 0.243852 | 0.346311 | 0.538934 | 28.391393 |
| distance_m | 800 | F1 | 152 | 4.333313 | 0.980868 | 0.561839 | 0.189146 | 0.293847 | 0.236842 | 0.052632 | 0.131579 | 0.236842 | 0.289474 | 0.500000 | 30.940789 |
| distance_m | 800 | F1_STYLE6 | 152 | 4.289138 | 0.978670 | 0.556921 | 0.187087 | 0.299838 | 0.217105 | 0.046053 | 0.111842 | 0.217105 | 0.328947 | 0.500000 | 30.223684 |
| distance_m | 900 | F1 | 251 | 4.267527 | 0.978647 | 0.565317 | 0.191228 | 0.240741 | 0.239044 | 0.083665 | 0.175299 | 0.239044 | 0.334661 | 0.501992 | 28.924303 |
| distance_m | 900 | F1_STYLE6 | 251 | 4.242237 | 0.978127 | 0.562451 | 0.190242 | 0.240210 | 0.258964 | 0.071713 | 0.183267 | 0.258964 | 0.330677 | 0.517928 | 28.450199 |
| distance_m | 1000 | F1 | 508 | 4.309949 | 0.979952 | 0.565497 | 0.190980 | 0.221208 | 0.210630 | 0.053150 | 0.124016 | 0.210630 | 0.320866 | 0.515748 | 30.454724 |
| distance_m | 1000 | F1_STYLE6 | 508 | 4.293008 | 0.979431 | 0.563635 | 0.190325 | 0.227912 | 0.228346 | 0.059055 | 0.124016 | 0.228346 | 0.366142 | 0.521654 | 29.925197 |
| distance_m | 1110 | F1 | 482 | 4.321551 | 0.981444 | 0.570999 | 0.193483 | 0.216362 | 0.215768 | 0.060166 | 0.122407 | 0.215768 | 0.323651 | 0.483402 | 30.226141 |
| distance_m | 1110 | F1_STYLE6 | 482 | 4.331120 | 0.981442 | 0.572174 | 0.194040 | 0.220819 | 0.215768 | 0.051867 | 0.116183 | 0.215768 | 0.319502 | 0.487552 | 30.535270 |
| distance_m | 1200 | F1 | 262 | 4.291021 | 0.980331 | 0.581125 | 0.197601 | 0.206889 | 0.232824 | 0.049618 | 0.103053 | 0.232824 | 0.324427 | 0.541985 | 31.164122 |
| distance_m | 1200 | F1_STYLE6 | 262 | 4.276645 | 0.979605 | 0.579417 | 0.196867 | 0.214729 | 0.232824 | 0.057252 | 0.118321 | 0.232824 | 0.354962 | 0.538168 | 30.629771 |
| distance_m | 1300 | F1 | 63 | 4.093956 | 0.969209 | 0.555641 | 0.186540 | 0.192724 | 0.301587 | 0.142857 | 0.238095 | 0.301587 | 0.412698 | 0.603175 | 25.873016 |
| distance_m | 1300 | F1_STYLE6 | 63 | 4.110755 | 0.970558 | 0.557859 | 0.187593 | 0.192486 | 0.253968 | 0.111111 | 0.222222 | 0.253968 | 0.380952 | 0.555556 | 26.111111 |
| distance_m | 1400 | F1 | 52 | 4.294977 | 0.978261 | 0.584825 | 0.198905 | 0.198667 | 0.192308 | 0.096154 | 0.115385 | 0.192308 | 0.326923 | 0.480769 | 34.461538 |
| distance_m | 1400 | F1_STYLE6 | 52 | 4.279672 | 0.977276 | 0.582673 | 0.197874 | 0.207659 | 0.230769 | 0.096154 | 0.115385 | 0.230769 | 0.326923 | 0.538462 | 35.192308 |
| distance_m | 1610 | F1 | 9 | 4.436269 | 0.995398 | 0.625027 | 0.218348 | 0.223265 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.555556 | 31.111111 |
| distance_m | 1610 | F1_STYLE6 | 9 | 4.383443 | 0.993561 | 0.618060 | 0.215086 | 0.224786 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.111111 | 0.555556 | 29.222222 |

## Six-ticket hit outcomes

| scope | value | races | hit_both | F1_only | STYLE6_only | neither |
| --- | --- | --- | --- | --- | --- | --- |
| overall | all | 1779 | 354 | 43 | 53 | 1329 |
| year | 2024 | 637 | 122 | 15 | 28 | 472 |
| year | 2025 | 654 | 123 | 17 | 15 | 499 |
| year | 2026 | 488 | 109 | 11 | 10 | 358 |
| distance_m | 800 | 152 | 32 | 4 | 1 | 115 |
| distance_m | 900 | 251 | 57 | 3 | 8 | 183 |
| distance_m | 1000 | 508 | 95 | 12 | 21 | 380 |
| distance_m | 1110 | 482 | 93 | 11 | 11 | 367 |
| distance_m | 1200 | 262 | 51 | 10 | 10 | 191 |
| distance_m | 1300 | 63 | 16 | 3 | 0 | 44 |
| distance_m | 1400 | 52 | 10 | 0 | 2 | 40 |
| distance_m | 1610 | 9 | 0 | 0 | 0 | 9 |

## Model-specific selected-six union decomposition

Each U6 is derived from that variant's own six tickets. The partition describes where the realized triple falls under the current selections; U6 is not a fixed candidate pool or a causal diagnosis.

| scope | value | variant | races | hit | allocation_miss | union_miss | mean_U6_size | mean_U6_overlap |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| overall | all | F1 | 1779 | 397 | 463 | 919 | 6.273749 | 5.857223 |
| overall | all | F1_STYLE6 | 1779 | 407 | 468 | 904 | 6.279370 | 5.857223 |
| year | 2024 | F1 | 637 | 137 | 161 | 339 | 6.295133 | 5.773940 |
| year | 2024 | F1_STYLE6 | 637 | 150 | 155 | 332 | 6.277865 | 5.773940 |
| year | 2025 | F1 | 654 | 140 | 179 | 335 | 6.316514 | 5.923547 |
| year | 2025 | F1_STYLE6 | 654 | 138 | 189 | 327 | 6.325688 | 5.923547 |
| year | 2026 | F1 | 488 | 120 | 123 | 245 | 6.188525 | 5.877049 |
| year | 2026 | F1_STYLE6 | 488 | 119 | 124 | 245 | 6.219262 | 5.877049 |
| distance_m | 800 | F1 | 152 | 36 | 51 | 65 | 6.907895 | 6.401316 |
| distance_m | 800 | F1_STYLE6 | 152 | 33 | 54 | 65 | 6.809211 | 6.401316 |
| distance_m | 900 | F1 | 251 | 60 | 54 | 137 | 6.211155 | 5.800797 |
| distance_m | 900 | F1_STYLE6 | 251 | 65 | 57 | 129 | 6.135458 | 5.800797 |
| distance_m | 1000 | F1 | 508 | 107 | 145 | 256 | 6.283465 | 5.822835 |
| distance_m | 1000 | F1_STYLE6 | 508 | 116 | 135 | 257 | 6.267717 | 5.822835 |
| distance_m | 1110 | F1 | 482 | 104 | 129 | 249 | 6.240664 | 5.898340 |
| distance_m | 1110 | F1_STYLE6 | 482 | 104 | 131 | 247 | 6.317427 | 5.898340 |
| distance_m | 1200 | F1 | 262 | 61 | 52 | 149 | 6.095420 | 5.690840 |
| distance_m | 1200 | F1_STYLE6 | 262 | 61 | 61 | 140 | 6.145038 | 5.690840 |
| distance_m | 1300 | F1 | 63 | 19 | 12 | 32 | 6.015873 | 5.650794 |
| distance_m | 1300 | F1_STYLE6 | 63 | 16 | 12 | 35 | 6.142857 | 5.650794 |
| distance_m | 1400 | F1 | 52 | 10 | 16 | 26 | 6.211538 | 5.615385 |
| distance_m | 1400 | F1_STYLE6 | 52 | 12 | 14 | 26 | 6.115385 | 5.615385 |
| distance_m | 1610 | F1 | 9 | 0 | 4 | 5 | 5.888889 | 5.666667 |
| distance_m | 1610 | F1_STYLE6 | 9 | 0 | 4 | 5 | 5.777778 | 5.666667 |

## Paired date bootstrap, reliability, and runner-loss contributions

Paired bootstrap deltas are STYLE6 minus F1, resampling race dates with the contract's fixed seed and 2,000 replicates per metric. Six-mass reliability uses the fixed bins in `six_mass_reliability.csv`.

Runner contributions divide each outcome-subgroup loss sum by that race's full field size before taking race means. `runner_rows` is the entrant-row denominator count, not a race count.

| ticket_changed | metric | races | improved_races | worsened_races | unchanged_races | mean_delta_STYLE6_minus_F1 |
| --- | --- | --- | --- | --- | --- | --- |
| False | log_loss | 477 | 266 | 211 | 0 | -0.001821 |
| False | brier | 477 | 264 | 213 | 0 | -0.000596 |
| True | log_loss | 1302 | 692 | 610 | 0 | -0.001122 |
| True | brier | 1302 | 674 | 628 | 0 | -0.000421 |

| ticket_changed | outcome_group | variant | metric | race_equal_loss_contribution | races | race_days | runner_rows |
| --- | --- | --- | --- | --- | --- | --- | --- |
| False | actual_top3 | F1 | brier | 0.124855 | 477 | 223 | 1431 |
| False | actual_top3 | F1 | log_loss | 0.324820 | 477 | 223 | 1431 |
| False | actual_top3 | F1_STYLE6 | brier | 0.124255 | 477 | 223 | 1431 |
| False | actual_top3 | F1_STYLE6 | log_loss | 0.323407 | 477 | 223 | 1431 |
| False | other_runners | F1 | brier | 0.065136 | 477 | 223 | 3191 |
| False | other_runners | F1 | log_loss | 0.237657 | 477 | 223 | 3191 |
| False | other_runners | F1_STYLE6 | brier | 0.065140 | 477 | 223 | 3191 |
| False | other_runners | F1_STYLE6 | log_loss | 0.237249 | 477 | 223 | 3191 |
| True | actual_top3 | F1 | brier | 0.129519 | 1302 | 269 | 3906 |
| True | actual_top3 | F1 | log_loss | 0.333117 | 1302 | 269 | 3906 |
| True | actual_top3 | F1_STYLE6 | brier | 0.128952 | 1302 | 269 | 3906 |
| True | actual_top3 | F1_STYLE6 | log_loss | 0.332154 | 1302 | 269 | 3906 |
| True | other_runners | F1 | brier | 0.064206 | 1302 | 269 | 8884 |
| True | other_runners | F1 | log_loss | 0.238913 | 1302 | 269 | 8884 |
| True | other_runners | F1_STYLE6 | brier | 0.064352 | 1302 | 269 | 8884 |
| True | other_runners | F1_STYLE6 | log_loss | 0.238754 | 1302 | 269 | 8884 |

## Interpretation limits

The saved-output parity and the listed decompositions are confirmed for this historical cohort. These are retrospective associations, not causal explanations or evidence of future performance. The normalized joint distribution is over unordered exact Top3 sets; it does not recover finish order or exact second/third-place probabilities. Raw score magnitudes are not compared across models. No conclusion that U6 misses identify a horse-evaluation or combination-model cause is supported. Any proposed pair-specific or alternative ticket-selection mechanism remains a future hypothesis requiring a separately approved study.
