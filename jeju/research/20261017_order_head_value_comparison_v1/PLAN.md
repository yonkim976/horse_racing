# Conditional order head: fixed-policy postrace pool-value comparison

## Purpose and interpretation

This is a secondary retrospective comparison of frozen `F1_STYLE6_COND_ORDER_V1` joint probabilities against the current registered `HY_R_FORM` probabilities for the four requested order-sensitive pools: WIN, QNL, EXA, and TRI. It describes postrace ticket selection on 2026 races already used in prior research; it is not an adoption criterion, promotion request, independent out-of-sample estimate, or live betting result. Final displayed prices were archived after each race, so EV and ROI are hindsight measures and do not represent prices or profits available at a real purchase time.

The learned head and its calibration must be fully frozen and separately approved by the root reviewer before this evaluator performs quote-based selection or outcome calculation. This evaluator does no training, calibration fitting, database access, registration change, network access, or change to an earlier study. It writes only inside this study directory.

## Frozen race population and price coverage

Use exactly the 467 `qpl_eligible=true` races in `jeju/research/20261015_operating_postrace_value_comparison_v1/cohort.csv` (2026-01-02 through 2026-09-12, 70 race dates), preserving its race IDs and fixed runner roster. WIN, QNL, and EXA have complete candidate prices for all 467 races. TRI has invalid `9999.9` sentinel quotes in 245 races; exclude each affected TRI race as a whole, leaving 222 complete-price races. Also report all four pools on the same fixed 222-race universal intersection. Source coverage and exclusions come from the already reviewed `jeju/research/20261015_other_pools_postrace_value_v1/SOURCE_PREFLIGHT.json` and `source_exclusions.csv`; this study will not repair, impute, or infer missing prices.

The exact official runner result labels come from `jeju/research/20261014_single_place_returns_v1/source_audit/OFFICIAL_RUNNER_RESULTS.csv`. Require each in-scope race to have the same full runner roster, exactly one official 1st, 2nd, and 3rd horse, and no top-three dead heat. A ticket hits only the exact pool event below. Quote candidates include losing and winning tickets; do not infer a missing loser price from a winner record.

## Probability inputs and event construction

The fixed HY probability source is the `p` column from `jeju/research/20261015_other_pools_postrace_value_v1/candidate_rows.csv`, restricted to `model=operating_hy_r_form` and pools WIN, QNL, EXA, and TRI. Ignore that file's quote, EV, hit, and outcome fields. Read final raw prices only from the fixed full-candidate `candidate_quotes.csv` after both approval gates pass.

The new model input is the frozen `outputs/evaluation_ordered_joint.parquet` from `jeju/research/20261017_conditional_order_head_v1`. Its required fields are `race_id`, `race_date`, `distance_m`, `field_n`, `horse_no_1`, `horse_no_2`, `horse_no_3`, `q_top3_set`, `p_ordered_joint`, and `control_p_ordered_joint`. The model labels are `F1_STYLE6_COND_ORDER_V1` and `F1_STYLE6_FIXED_SCORE_PL_CONTROL`. Consume the saved joint probabilities as-is and do not refit or recalibrate them. Verify that every race has each ordered triple exactly once, no triple repeats a runner, and each model's ordered mass sums to one.

For each ordered pool, aggregate the complete ordered-triple joint distribution into exact event probabilities:

- WIN: first horse.
- QNL: the unordered pair occupying first and second.
- EXA: the ordered first-to-second pair.
- TRI: the exact ordered first-second-third triple.

The fixed-score PL control contextualizes the change to the learned order head while retaining the supplied set-probability factor. The primary contrast is current HY versus the conditional-order model.

TLA is a probability-invariance diagnostic only. For every unordered triple, verify that the six head joint masses and six control joint masses each sum to the supplied `q_top3_set` within absolute tolerance `1e-12`. Reconcile every set key and probability to `jeju/research/20261015_research_other_pool_support_v1/tla_set_probabilities.parquet` (`set_probability`). Use that artifact's canonical `set_probability` for TLA ranks, EV, and policy decisions for the head and fixed-score control so floating-point summation cannot create a tie break or apparent order-head gain. Head, control, and the canonical F1_STYLE6 TLA artifact must have identical TLA probabilities and choices under every fixed policy. Do not compare HY TLA or present TLA returns as an order-head gain.

## Fixed selection policies

Apply the same ten policies to each supported model and ordered pool, in each declared scope. Each policy can select at most one ticket per eligible race and stakes KRW 1,000. Rank events by probability descending, breaking probability ties by numeric event tuple ascending. For max-EV rules, break EV ties by the same numeric event tuple. Unordered QNL tuples are sorted; EXA and TRI tuples preserve order. Apply the same policies to the TLA diagnostic only to prove its fixed q yields identical choices.

1. Select probability rank 1, 2, 3, 4, or 5 (five separate policies).
2. Select rank 1 only when its postrace EV is strictly greater than 0.
3. Select the all-candidate maximum-EV ticket only when its EV is strictly greater than 0.
4. Select the maximum-EV ticket among probability ranks 1–3 only when its EV is strictly greater than 0.
5. Select the maximum-EV ticket among probability ranks 1–5 only when its EV is strictly greater than 0.
6. Select the maximum-EV ticket among probability ranks 1–3 only when its EV is strictly greater than 0.20.

For every candidate, `EV = p × final displayed odds − 1`. Displayed odds include stake; an exact-hit ticket returns `1,000 × odds` gross, otherwise gross return is zero. ROI is `(gross return − stake) / stake`. Do not tune, add, or remove a rule after seeing selection or payout results.

## Reporting and uncertainty

For the four ordered pools, write a complete candidate table for each model with candidate event key, probability, raw final quote, parsed odds/quote status, and exact-hit label. Write a complete decision grid with one row per model × pool × scope × policy × eligible race, including no-bet rows; write chosen tickets separately. Summaries report eligible races, selections, no-bets, coverage, hits, hit rate, stake, gross return, net, ROI, mean selected probability, mean selected probability on actual hits, mean quote, mean selected postrace EV, and selected probability rank. Also report ROI after removing the one, three, or five largest gross winning tickets and the stake removed with those tickets. Report TLA invariance separately; its three identical grids are diagnostic only.

Use the exact fixed 2,000 × 269 date-block bootstrap schedule in `jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy`, its sealed JSON receipt, and the original 269-date inventory. Dates outside an evaluation cohort contribute zero selected tickets. Report ROI and hit-rate percentile 95% intervals, valid/zero-stake draws, and paired same-draw ROI differences in percentage points for `HY_R_FORM − F1_STYLE6_COND_ORDER_V1` for WIN, QNL, EXA, and TRI under every policy and scope. Also report `F1_STYLE6_FIXED_SCORE_PL_CONTROL − F1_STYLE6_COND_ORDER_V1` to contextualize order-head learning. Keep zero-bet draws visible.

Do not use the highest observed ROI as a recommendation. Explicitly expose results driven by one hit through the fixed top-1/top-3/top-5 winning-ticket removal table. Preserve `horseTop3` and `QPL pair_id` analyses outside this scope.

## Freeze and execution gate

Before quote-based policy selection, freeze this plan, the pre-fit source hashes, and evaluator code. The evaluation runner must stop unless the main study's separate frozen-fit approval and the root reviewer's explicit approval for this exact value comparison are present at the fixed receipt paths, and their hashes match the ordered-joint artifact and this plan. It must also verify the sealed current-registry, HY model, HY distribution function, common cohort, quote source, official labels, bootstrap inputs, canonical TLA q, and main frozen design hashes listed in `SOURCE_MANIFEST_PREFIT.json`.

The new evaluator must not use final odds to change model, probability, policy, scope, or cohort. All result files and manifests remain confined to this new study directory. Freeze the report after root checks; keep the separate verification receipt outside the report's input-hash set.
