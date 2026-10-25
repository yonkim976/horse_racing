# Pair-in-Top3 axis design and source audit

Status: read-only design review, 2026-10-10. No fitting, database access, new outcome metric calculation, or operational change was performed. This is an exploratory follow-up using a repeatedly reviewed historical cohort; it is not a pre-registered independent validation.

## What the saved distribution can answer

The source study `20261010_joint_relationship_v1` stores a probability distribution over **unordered exact Top3 sets**. Its frozen `all_triples.parquet` contains 402,808 rows across two arms (matched baseline and candidate), 1,779 races, 17,412 runner rows, and 269 race dates from 2024-01-05 through 2026-09-19; 2026 is partial. The saved runner marginal file contains Top3 marginals, not probabilities for first, second, or third place. The frozen `features.parquet` includes `finish_position`, which can label actual finish order for retrospective hit accounting.

For a race and arm, write the saved probability of unordered Top3 set `{i,j,k}` as `q_ijk`. Then

- `P(i and j both Top3) = sum over k != i,j of q_ijk`;
- when that pair probability is positive, `P(k is the remaining Top3 horse | i and j both Top3) = q_ijk / P(i and j both Top3)`.

These are coherent pair-in-Top3 and completion probabilities because each race's saved set distribution is normalized over exact three-horse sets. They say nothing about whether `i` and `j` are first and second. The set distribution cannot identify an exact Top2 pair probability, `P(i is first, j is second)`, or exact second/third marginals.

## Smallest useful policy comparison

A transparent no-fit policy can select the unordered pair with the largest saved pair-in-Top3 probability. Resolve exact ties by ascending horse numbers. Rank each remaining horse by its conditional completion probability and resolve ties by ascending horse number. For fixed ticket budgets `K = 3, 4, 6`, issue the top K triples containing that same pair and the first K completion candidates. No threshold is chosen after seeing results.

For each race, classify the actual unordered Top3 set as:

1. **Hit:** it contains the selected pair and the actual third horse is in the K completion list.
2. **Pair miss:** it does not contain the selected pair.
3. **Completion miss:** it contains the selected pair, but the actual third horse is absent from the K completion list.

These cases are mutually exclusive and exhaustive for the complete, no-tie Top3 cohort. Report pair-event probability quality separately from selection coverage: for the selected pair, compare its saved `P(i and j both Top3)` with the binary actual pair-in-Top3 outcome using Brier/log loss; for completion, report both the saved conditional mass assigned to the selected K horses and the observed completion rate among races where the pair actually made Top3. Report total K-ticket hit rate and paired race-date uncertainty. This makes pair confidence, completion coverage, and ticket hit distinct quantities.

For context at the same K, compare the axis policy against the top K individual exact-set tickets from the **same frozen arm**. Since unrestricted top K maximizes probability mass under that Q, the pair-constrained policy's predicted mass cannot be higher; this is a structural check, not a performance gate, and observed hit rates may differ in either direction. A pair with maximal `P(i and j both Top3)` can still have its completion probability spread across many horses, so report the K-completion conditional mass and its observed coverage. Keep arm choice fixed in advance; if both arms are shown, label that comparison exploratory because this cohort has already been used for model and design decisions. The previous 2026-10-09 axis-companion study is a separate one-anchor conditional companion experiment and is not a direct replication of this pair-in-Top3 policy.

Use confidence bins fixed before outcome tabulation (for example, five equal-width bins over `[0,1]`, with counts shown). Pair coverage and global pair-rank summaries are descriptive; they are not prospective decision thresholds or rules for choosing a different pair.

## Secondary exact-Top2 check and local ordered assets

Actual finish ranks in `features.parquet` allow a secondary check of whether a pair selected by its Top3 joint probability happens to occupy the actual first two places, in either order. That is a ranking-transfer outcome only; `q_ijk` supplies no calibrated exact-Top2 probability for it. Do not label `P(i and j both Top3)` as exact Top2 probability or use it to claim exacta calibration.

Authentic ordered HY_R_FORM joint outputs are available for a few individual race-card forecasts in `jeju/predictions/card_20261009_manual_then_model/race_*/model_probabilities.json`; the files store ordered `(first, second, third)` outcomes and joint probabilities. Related saved forecasts on 2026-10-02 and 2026-10-10 also contain runner-level win/Top2/Top3 marginals. These are different, small race-card cohorts and do not cover the 1,779 F1_STYLE6 races with matched ordered probabilities. They establish local output availability, but cannot support a broad matched exact-Top2 study on the present source cohort. A direct exact-Top2-pair target therefore needs a separately frozen, cohort-matched ordered source before it can be evaluated as a probability target.

## Source integrity and limits

The immutable source manifest SHA-256 is `d0d1a749afb6a6f894de1bb4263c9d67dd1e3b2d1a35bf1b5fd38d8948c656b0`. The saved set distribution SHA-256 is `13409e65353c0cb6dab14df97317cce24de913056ae464ee3524520759de681c`, runner marginals SHA-256 is `0e6a01607164a7cb54fbbb5fb445e975ea9fbadad21d4e7a842adfc915616a09`, and the rank-bearing features SHA-256 is `036939bd6d518a9e53d458a2f4eb2bf30bfecfa4bb80e21c78edd1f7f44f028f`. These exact paths and verified hashes are recorded in [source_manifest.json](source_manifest.json). The first three hashes agree with the source study manifest/report receipt; the feature hash agrees with its saved style-history manifest and prepared lock.

The source report states that the joint-relationship candidate did not pass its two pre-registered performance gates. Any pair-axis result on these same races remains exploratory and must not be described as independent confirmation or an operational model improvement. The cohort is based on complete normal finishes and historical start/publication timing was not fully reconstructed; conclusions do not extend automatically to ties, scratches, disqualifications, or non-finishes.
