# Conditional order head postrace value comparison

This is a secondary retrospective comparison on the fixed 2026 cohort. EV and ROI use archived final displayed odds after the race and are oracle hindsight measures, not real purchase prices or operating profit. The results do not decide model adoption.

The primary comparison covers WIN, QNL, EXA, and TRI. TRI uses only the 222 races with complete candidate prices; the universal comparison uses that same 222-race set for all four pools. Ten ticket policies and KRW 1,000 stakes were fixed in `PLAN.md` before any quote-based choices.

TLA is only an invariance diagnostic. The order-head and fixed-score control probabilities are reconciled to the canonical saved F1_STYLE6 set probabilities, and the canonical values are used for ranking and EV. TLA choices are required to match exactly; they do not show an order-head gain.

## Primary scope snapshot

| Pool | Model | Policy | Bets / eligible | Hits | Net (KRW) | ROI | ROI after removing top hit |
|---|---|---|---:|---:|---:|---:|---:|
| EXA | F1_STYLE6_COND_ORDER_V1 | all_max_ev_positive | 467 / 467 | 2 | -36300 | -7.77% | -76.46% |
| EXA | F1_STYLE6_COND_ORDER_V1 | p_rank_1 | 467 / 467 | 32 | -145700 | -31.20% | -39.14% |
| EXA | F1_STYLE6_COND_ORDER_V1 | p_rank_1_ev_positive | 207 / 467 | 7 | -50200 | -24.25% | -42.18% |
| EXA | F1_STYLE6_COND_ORDER_V1 | p_rank_2 | 467 / 467 | 28 | -191900 | -41.09% | -47.06% |
| EXA | F1_STYLE6_COND_ORDER_V1 | p_rank_3 | 467 / 467 | 28 | -131000 | -28.05% | -40.21% |
| EXA | F1_STYLE6_COND_ORDER_V1 | p_rank_4 | 467 / 467 | 19 | 63600 | 13.62% | -16.42% |
| EXA | F1_STYLE6_COND_ORDER_V1 | p_rank_5 | 467 / 467 | 15 | -188700 | -40.41% | -58.78% |
| EXA | F1_STYLE6_COND_ORDER_V1 | top3_max_ev_gt_020 | 286 / 467 | 4 | -161200 | -56.36% | -76.35% |
| EXA | F1_STYLE6_COND_ORDER_V1 | top3_max_ev_positive | 340 / 467 | 5 | -201600 | -59.29% | -76.11% |
| EXA | F1_STYLE6_COND_ORDER_V1 | top5_max_ev_positive | 402 / 467 | 8 | -101600 | -25.27% | -46.58% |
| EXA | F1_STYLE6_FIXED_SCORE_PL_CONTROL | all_max_ev_positive | 467 / 467 | 3 | -85000 | -18.20% | -69.33% |
| EXA | F1_STYLE6_FIXED_SCORE_PL_CONTROL | p_rank_1 | 467 / 467 | 41 | -52100 | -11.16% | -19.06% |
| EXA | F1_STYLE6_FIXED_SCORE_PL_CONTROL | p_rank_1_ev_positive | 264 / 467 | 12 | -49200 | -18.64% | -32.66% |
| EXA | F1_STYLE6_FIXED_SCORE_PL_CONTROL | p_rank_2 | 467 / 467 | 25 | -196300 | -42.03% | -47.42% |
| EXA | F1_STYLE6_FIXED_SCORE_PL_CONTROL | p_rank_3 | 467 / 467 | 19 | -254500 | -54.50% | -60.00% |
| EXA | F1_STYLE6_FIXED_SCORE_PL_CONTROL | p_rank_4 | 467 / 467 | 14 | -161700 | -34.63% | -50.99% |
| EXA | F1_STYLE6_FIXED_SCORE_PL_CONTROL | p_rank_5 | 467 / 467 | 18 | 213300 | 45.67% | -5.32% |
| EXA | F1_STYLE6_FIXED_SCORE_PL_CONTROL | top3_max_ev_gt_020 | 351 / 467 | 13 | -76400 | -21.77% | -31.03% |
| EXA | F1_STYLE6_FIXED_SCORE_PL_CONTROL | top3_max_ev_positive | 405 / 467 | 15 | -88300 | -21.80% | -29.83% |
| EXA | F1_STYLE6_FIXED_SCORE_PL_CONTROL | top5_max_ev_positive | 439 / 467 | 13 | 183100 | 41.71% | -12.56% |
| EXA | HY_R_FORM | all_max_ev_positive | 466 / 467 | 2 | -269900 | -57.92% | -84.80% |
| EXA | HY_R_FORM | p_rank_1 | 467 / 467 | 40 | -134900 | -28.89% | -32.98% |
| EXA | HY_R_FORM | p_rank_1_ev_positive | 217 / 467 | 12 | -62400 | -28.76% | -37.59% |
| EXA | HY_R_FORM | p_rank_2 | 467 / 467 | 35 | -178300 | -38.18% | -42.96% |
| EXA | HY_R_FORM | p_rank_3 | 467 / 467 | 25 | -180500 | -38.65% | -45.54% |
| EXA | HY_R_FORM | p_rank_4 | 467 / 467 | 21 | -226500 | -48.50% | -53.69% |
| EXA | HY_R_FORM | p_rank_5 | 467 / 467 | 15 | -45800 | -9.81% | -36.52% |
| EXA | HY_R_FORM | top3_max_ev_gt_020 | 300 / 467 | 6 | -193600 | -64.53% | -75.35% |
| EXA | HY_R_FORM | top3_max_ev_positive | 357 / 467 | 9 | -219000 | -61.34% | -70.42% |
| EXA | HY_R_FORM | top5_max_ev_positive | 412 / 467 | 13 | 35100 | 8.52% | -21.73% |
| QNL | F1_STYLE6_COND_ORDER_V1 | all_max_ev_positive | 467 / 467 | 1 | -408900 | -87.56% | -100.00% |
| QNL | F1_STYLE6_COND_ORDER_V1 | p_rank_1 | 467 / 467 | 65 | -24700 | -5.29% | -11.78% |
| QNL | F1_STYLE6_COND_ORDER_V1 | p_rank_1_ev_positive | 205 / 467 | 14 | 3400 | 1.66% | -13.14% |
| QNL | F1_STYLE6_COND_ORDER_V1 | p_rank_2 | 467 / 467 | 40 | -116400 | -24.93% | -38.22% |
| QNL | F1_STYLE6_COND_ORDER_V1 | p_rank_3 | 467 / 467 | 30 | -191200 | -40.94% | -45.39% |
| QNL | F1_STYLE6_COND_ORDER_V1 | p_rank_4 | 467 / 467 | 24 | -148500 | -31.80% | -41.01% |
| QNL | F1_STYLE6_COND_ORDER_V1 | p_rank_5 | 467 / 467 | 24 | -239900 | -51.37% | -57.12% |
| QNL | F1_STYLE6_COND_ORDER_V1 | top3_max_ev_gt_020 | 321 / 467 | 15 | -98400 | -30.65% | -37.62% |
| QNL | F1_STYLE6_COND_ORDER_V1 | top3_max_ev_positive | 368 / 467 | 19 | -93700 | -25.46% | -31.53% |
| QNL | F1_STYLE6_COND_ORDER_V1 | top5_max_ev_positive | 433 / 467 | 10 | -248100 | -57.30% | -65.02% |
| QNL | F1_STYLE6_FIXED_SCORE_PL_CONTROL | all_max_ev_positive | 467 / 467 | 7 | -95500 | -20.45% | -42.70% |
| QNL | F1_STYLE6_FIXED_SCORE_PL_CONTROL | p_rank_1 | 467 / 467 | 64 | -60900 | -13.04% | -19.55% |
| QNL | F1_STYLE6_FIXED_SCORE_PL_CONTROL | p_rank_1_ev_positive | 275 / 467 | 22 | -31700 | -11.53% | -22.59% |
| QNL | F1_STYLE6_FIXED_SCORE_PL_CONTROL | p_rank_2 | 467 / 467 | 42 | -37900 | -8.12% | -21.37% |
| QNL | F1_STYLE6_FIXED_SCORE_PL_CONTROL | p_rank_3 | 467 / 467 | 34 | -100600 | -21.54% | -43.80% |
| QNL | F1_STYLE6_FIXED_SCORE_PL_CONTROL | p_rank_4 | 467 / 467 | 17 | -250800 | -53.70% | -62.96% |
| QNL | F1_STYLE6_FIXED_SCORE_PL_CONTROL | p_rank_5 | 467 / 467 | 25 | -236200 | -50.58% | -56.61% |
| QNL | F1_STYLE6_FIXED_SCORE_PL_CONTROL | top3_max_ev_gt_020 | 379 / 467 | 23 | 109600 | 28.92% | 1.61% |
| QNL | F1_STYLE6_FIXED_SCORE_PL_CONTROL | top3_max_ev_positive | 423 / 467 | 29 | 118900 | 28.11% | 3.65% |
| QNL | F1_STYLE6_FIXED_SCORE_PL_CONTROL | top5_max_ev_positive | 456 / 467 | 17 | -42000 | -9.21% | -31.98% |
| QNL | HY_R_FORM | all_max_ev_positive | 466 / 467 | 6 | -301500 | -64.70% | -78.41% |
| QNL | HY_R_FORM | p_rank_1 | 467 / 467 | 75 | -76000 | -16.27% | -19.18% |
| QNL | HY_R_FORM | p_rank_1_ev_positive | 229 / 467 | 27 | -48500 | -21.18% | -27.15% |
| QNL | HY_R_FORM | p_rank_2 | 467 / 467 | 40 | -234300 | -50.17% | -54.83% |
| QNL | HY_R_FORM | p_rank_3 | 467 / 467 | 29 | -212800 | -45.57% | -54.79% |
| QNL | HY_R_FORM | p_rank_4 | 467 / 467 | 36 | -32800 | -7.02% | -20.58% |
| QNL | HY_R_FORM | p_rank_5 | 467 / 467 | 31 | -146200 | -31.31% | -35.73% |
| QNL | HY_R_FORM | top3_max_ev_gt_020 | 342 / 467 | 11 | -198300 | -57.98% | -64.60% |
| QNL | HY_R_FORM | top3_max_ev_positive | 396 / 467 | 16 | -224900 | -56.79% | -62.51% |
| QNL | HY_R_FORM | top5_max_ev_positive | 438 / 467 | 16 | -143000 | -32.65% | -47.16% |
| TRI | F1_STYLE6_COND_ORDER_V1 | all_max_ev_positive | 222 / 222 | 0 | -222000 | -100.00% | -100.00% |
| TRI | F1_STYLE6_COND_ORDER_V1 | p_rank_1 | 222 / 222 | 5 | -10100 | -4.55% | -40.54% |
| TRI | F1_STYLE6_COND_ORDER_V1 | p_rank_1_ev_positive | 115 / 222 | 1 | -68000 | -59.13% | -100.00% |
| TRI | F1_STYLE6_COND_ORDER_V1 | p_rank_2 | 222 / 222 | 1 | -175100 | -78.87% | -100.00% |
| TRI | F1_STYLE6_COND_ORDER_V1 | p_rank_3 | 222 / 222 | 2 | -17500 | -7.88% | -68.60% |
| TRI | F1_STYLE6_COND_ORDER_V1 | p_rank_4 | 222 / 222 | 5 | -34100 | -15.36% | -50.00% |
| TRI | F1_STYLE6_COND_ORDER_V1 | p_rank_5 | 222 / 222 | 0 | -222000 | -100.00% | -100.00% |
| TRI | F1_STYLE6_COND_ORDER_V1 | top3_max_ev_gt_020 | 141 / 222 | 0 | -141000 | -100.00% | -100.00% |
| TRI | F1_STYLE6_COND_ORDER_V1 | top3_max_ev_positive | 157 / 222 | 0 | -157000 | -100.00% | -100.00% |
| TRI | F1_STYLE6_COND_ORDER_V1 | top5_max_ev_positive | 186 / 222 | 0 | -186000 | -100.00% | -100.00% |
| TRI | F1_STYLE6_FIXED_SCORE_PL_CONTROL | all_max_ev_positive | 222 / 222 | 0 | -222000 | -100.00% | -100.00% |
| TRI | F1_STYLE6_FIXED_SCORE_PL_CONTROL | p_rank_1 | 222 / 222 | 2 | -53500 | -24.10% | -79.82% |
| TRI | F1_STYLE6_FIXED_SCORE_PL_CONTROL | p_rank_1_ev_positive | 105 / 222 | 0 | -105000 | -100.00% | -100.00% |
| TRI | F1_STYLE6_FIXED_SCORE_PL_CONTROL | p_rank_2 | 222 / 222 | 4 | -88300 | -39.77% | -60.77% |
| TRI | F1_STYLE6_FIXED_SCORE_PL_CONTROL | p_rank_3 | 222 / 222 | 0 | -222000 | -100.00% | -100.00% |
| TRI | F1_STYLE6_FIXED_SCORE_PL_CONTROL | p_rank_4 | 222 / 222 | 4 | 53900 | 24.28% | -18.73% |
| TRI | F1_STYLE6_FIXED_SCORE_PL_CONTROL | p_rank_5 | 222 / 222 | 4 | 211900 | 95.45% | -63.26% |
| TRI | F1_STYLE6_FIXED_SCORE_PL_CONTROL | top3_max_ev_gt_020 | 144 / 222 | 0 | -144000 | -100.00% | -100.00% |
| TRI | F1_STYLE6_FIXED_SCORE_PL_CONTROL | top3_max_ev_positive | 162 / 222 | 0 | -162000 | -100.00% | -100.00% |
| TRI | F1_STYLE6_FIXED_SCORE_PL_CONTROL | top5_max_ev_positive | 189 / 222 | 1 | 163700 | 86.61% | -100.00% |
| TRI | HY_R_FORM | all_max_ev_positive | 222 / 222 | 1 | 333300 | 150.14% | -100.00% |
| TRI | HY_R_FORM | p_rank_1 | 222 / 222 | 2 | -188300 | -84.82% | -92.44% |
| TRI | HY_R_FORM | p_rank_1_ev_positive | 133 / 222 | 0 | -133000 | -100.00% | -100.00% |
| TRI | HY_R_FORM | p_rank_2 | 222 / 222 | 2 | -205500 | -92.57% | -96.43% |
| TRI | HY_R_FORM | p_rank_3 | 222 / 222 | 3 | -114000 | -51.35% | -77.83% |
| TRI | HY_R_FORM | p_rank_4 | 222 / 222 | 3 | -32200 | -14.50% | -49.10% |
| TRI | HY_R_FORM | p_rank_5 | 222 / 222 | 2 | -113800 | -51.26% | -83.08% |
| TRI | HY_R_FORM | top3_max_ev_gt_020 | 150 / 222 | 1 | -122700 | -81.80% | -100.00% |
| TRI | HY_R_FORM | top3_max_ev_positive | 169 / 222 | 1 | -141700 | -83.85% | -100.00% |
| TRI | HY_R_FORM | top5_max_ev_positive | 194 / 222 | 1 | -148300 | -76.44% | -100.00% |
| WIN | F1_STYLE6_COND_ORDER_V1 | all_max_ev_positive | 466 / 467 | 16 | -153800 | -33.00% | -41.94% |
| WIN | F1_STYLE6_COND_ORDER_V1 | p_rank_1 | 467 / 467 | 130 | -117300 | -25.12% | -28.69% |
| WIN | F1_STYLE6_COND_ORDER_V1 | p_rank_1_ev_positive | 168 / 467 | 22 | -43700 | -26.01% | -35.99% |
| WIN | F1_STYLE6_COND_ORDER_V1 | p_rank_2 | 467 / 467 | 75 | -71600 | -15.33% | -20.97% |
| WIN | F1_STYLE6_COND_ORDER_V1 | p_rank_3 | 467 / 467 | 73 | 19600 | 4.20% | -3.91% |
| WIN | F1_STYLE6_COND_ORDER_V1 | p_rank_4 | 467 / 467 | 49 | -106800 | -22.87% | -29.38% |
| WIN | F1_STYLE6_COND_ORDER_V1 | p_rank_5 | 467 / 467 | 32 | -230600 | -49.38% | -53.18% |
| WIN | F1_STYLE6_COND_ORDER_V1 | top3_max_ev_gt_020 | 352 / 467 | 34 | 64300 | 18.27% | 7.55% |
| WIN | F1_STYLE6_COND_ORDER_V1 | top3_max_ev_positive | 404 / 467 | 41 | 45800 | 11.34% | 1.99% |
| WIN | F1_STYLE6_COND_ORDER_V1 | top5_max_ev_positive | 459 / 467 | 23 | -114400 | -24.92% | -33.23% |
| WIN | F1_STYLE6_FIXED_SCORE_PL_CONTROL | all_max_ev_positive | 466 / 467 | 24 | -43300 | -9.29% | -32.24% |
| WIN | F1_STYLE6_FIXED_SCORE_PL_CONTROL | p_rank_1 | 467 / 467 | 125 | -130100 | -27.86% | -31.89% |
| WIN | F1_STYLE6_FIXED_SCORE_PL_CONTROL | p_rank_1_ev_positive | 240 / 467 | 42 | -65500 | -27.29% | -35.15% |
| WIN | F1_STYLE6_FIXED_SCORE_PL_CONTROL | p_rank_2 | 467 / 467 | 75 | -40100 | -8.59% | -14.21% |
| WIN | F1_STYLE6_FIXED_SCORE_PL_CONTROL | p_rank_3 | 467 / 467 | 67 | -22400 | -4.80% | -12.92% |
| WIN | F1_STYLE6_FIXED_SCORE_PL_CONTROL | p_rank_4 | 467 / 467 | 55 | -115600 | -24.75% | -30.34% |
| WIN | F1_STYLE6_FIXED_SCORE_PL_CONTROL | p_rank_5 | 467 / 467 | 36 | -202800 | -43.43% | -48.41% |
| WIN | F1_STYLE6_FIXED_SCORE_PL_CONTROL | top3_max_ev_gt_020 | 382 / 467 | 41 | 60700 | 15.89% | 6.01% |
| WIN | F1_STYLE6_FIXED_SCORE_PL_CONTROL | top3_max_ev_positive | 432 / 467 | 51 | 43600 | 10.09% | 1.35% |
| WIN | F1_STYLE6_FIXED_SCORE_PL_CONTROL | top5_max_ev_positive | 462 / 467 | 29 | -103700 | -22.45% | -30.69% |
| WIN | HY_R_FORM | all_max_ev_positive | 465 / 467 | 32 | 2300 | 0.49% | -9.29% |
| WIN | HY_R_FORM | p_rank_1 | 467 / 467 | 155 | -51500 | -11.03% | -13.03% |
| WIN | HY_R_FORM | p_rank_1_ev_positive | 203 / 467 | 48 | -4900 | -2.41% | -6.98% |
| WIN | HY_R_FORM | p_rank_2 | 467 / 467 | 81 | -128000 | -27.41% | -30.99% |
| WIN | HY_R_FORM | p_rank_3 | 467 / 467 | 63 | -53300 | -11.41% | -19.55% |
| WIN | HY_R_FORM | p_rank_4 | 467 / 467 | 54 | -39600 | -8.48% | -14.10% |
| WIN | HY_R_FORM | p_rank_5 | 467 / 467 | 37 | -81200 | -17.39% | -25.84% |
| WIN | HY_R_FORM | top3_max_ev_gt_020 | 315 / 467 | 39 | 500 | 0.16% | -11.88% |
| WIN | HY_R_FORM | top3_max_ev_positive | 407 / 467 | 53 | -35900 | -8.82% | -18.15% |
| WIN | HY_R_FORM | top5_max_ev_positive | 457 / 467 | 30 | -84100 | -18.40% | -27.04% |

The complete fixed-rule outcomes are in `strategy_summary.csv`; same-draw HY−head differences are in `paired_hy_minus_order_head.csv`. The 2,000 × 269 date-block intervals are in `strategy_bootstrap_ci.csv`. The full candidate event, price, and hit tables retain losing as well as winning events.

The root reviewer must check the draft outputs before `REPORT.json` and the final manifest are frozen. `REPORT_DRAFT.json` and `OUTPUT_MANIFEST_DRAFT.json` are the review artifacts.
