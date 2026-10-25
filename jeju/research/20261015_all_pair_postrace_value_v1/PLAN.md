# All-pair QPL post-race value exploration

## Question and interpretation

For the fixed 2025–2026 Jeju evaluation races, does choosing a pair whose saved Top3-coincidence probability has a positive post-race score `p × final QPL quote − 1` produce a better realized return than choosing only the highest-probability pair? The final displayed quote is known only after the race in these records. This score is therefore a retrospective oracle condition, not a pre-race expected return or a betting recommendation.

QPL (quinella place / 복연승) is the only pool in scope. The saved pair probability means that both horses finish in the official Top3; QNL probability is never substituted. On a hit the displayed gross multiplier includes stake, so return is `quote × 1,000 KRW`; on a miss it is zero. ROI is `(gross return − stake) / stake`. No second fee is deducted.

## Frozen sources and cohort

- Primary saved pair probabilities: `jeju/research/20261012_pair_jockey_id_v1/outputs/evaluation_pair_predictions.parquet`, expected SHA-256 `0d41ee66149edfae79f2b422ba588c422686a328aad0122071183ee9db6768d6`; use `jockey_id_candidate_calibrated_probability` for every unordered pair.
- Supplementary recent candidate: `jeju/research/20261015_pair_riding_conditions_v1/outputs/evaluation_pair_predictions.parquet`, expected SHA-256 `c50f7cdd762cc4ed36e50b97bd4d6d979be408c7477f0c747c917e120cde9ced`; use `riding_conditions_candidate_calibrated_probability` for every unordered pair. It is reported separately and cannot replace the primary source.
- Common priced target cohort: 2025 (654 races) and 2026-01-01 through 2026-09-19 (488 races), 1,142 races total. The 637-race 2024 fold has no verified local API301 price archive and is excluded from price/ROI claims.
- Reuse the read-only `archive_rows` helper in `jeju/research/20261013_pair_payout_audit_v1/analyze.py` to choose the latest complete API301 page run for each race date, verify every cached page SHA against `source_documents`, and inspect the complete returned QPL event set. Preserve page path/hash provenance in a restricted index without exporting URLs, request parameters, or credentials.
- Cross-check every candidate pair and quote against the separate direct-JSON source reference and review prepared by the supervising root task; require the full race/pair roster and numeric prices to agree before calculating strategy results.
- Before strategy calculations, census all candidate pairs against the chosen final QPL API301 source for every target race, regardless of hit or miss. Audit exact full-field combination keys, source duplicates, pair ordering, scratched/nonstarter combinations, missing/zero/nonfinite/9999.9 quotes, and conflicting values. Keep the complete-valid-price race cohort as the primary analysis denominator; report pair-price-available selections separately with their own coverage and exclusions. Never infer a losing quote from a winning payout or treat `paidloss=0` as a price.

## Strategies fixed before reading results

One 1,000 KRW ticket per selected race; every rule is applied separately to both fixed probability sources using the same source quotes and cohort:

1. Select the exact probability rank 1, 2, 3, 4, or 5 (five independent rules).
2. Select rank 1 only when its `p × quote − 1 > 0`.
3. Select the maximum-score pair among all priced pairs only when its score is `> 0`.
4. Select the maximum-score pair among probability ranks 1–3 only when its score is `> 0`.
5. Select the maximum-score pair among probability ranks 1–5 only when its score is `> 0`.
6. Select the maximum-score pair among pairs with `p >= 0.20`, or separately `p >= 0.30`, only when its score is `> 0`.
7. Apply the two fixed positive-score rules for ranks 1–3 and `p >= 0.20` with the stricter `score > 0.20` threshold.

There is no post-result threshold selection. Equal probabilities and equal scores are broken deterministically by ascending unordered horse numbers. For the partial-price appendix, an EV-maximizing rule can search only source pairs whose quote is valid; this is labeled as price-availability conditioned.

## Measures and diagnostics

Report primary complete-price results and partial-price availability separately for all years combined, 2025, and 2026 partial: eligible races, bets/coverage, hits/hit rate, mean `p`, mean quote, mean winning quote among hits, mean post-hoc score, stake, gross return, net, and ROI. Show model/rule paired-date 95% intervals using the frozen 2,000 × 269 draw schedule at `jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy` (SHA-256 `d141b0c3f9a463cbfc9d1f4c61228b58757c31aee4ec74b79f41c5baeadaccbd`). Record draws with zero selected bets; omit them only from undefined metric intervals and report the count. Use the same date draws for all comparisons.

For each selected rule, show sensitivity after removing its largest 1, 3, and 5 realized gross-return hits, removing each removed ticket's stake from its denominator. Report pairwise paired-date intervals versus the fixed rank-1 rule. Also report exact probability-rank calibration (count, mean p, observed hit rate, Brier score) and selected-pair rank distribution. Provide a balanced, median-centered sample of rank-switch cases with rank-1 and chosen pair p/quote/score, chosen rank, hit, stake, and return; do not choose cases by maximum profit.

Interpret positive-score selection as a retrospective oracle. Discuss selection coverage, quote availability, p<0.20/0.30 restrictions, and high-odds selection bias. Repeated use of these historical development years is not independent validation. Do not change models, refit, recollect data, use network, write to DB, or change operations.
