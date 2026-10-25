# Pair-axis target and selection review

Date: 2026-10-10. Status: independent source and target audit, followed by a no-fit validation of the frozen pair-axis policy contract. No new predictions, fitting, database access, network access, or central publication writes were performed. All code and outputs are confined to this review directory.

## Source inventory and integrity

The intended source is the immutable `20261010_joint_relationship_v1` study and its saved F1_STYLE6 inputs. I independently computed SHA-256 from local bytes for the main manifest, complete triple table, runner marginals, race metrics, feature table, and the STYLE6 artifact manifest. The locked hashes matched:

| Source | SHA-256 | Structural role |
|---|---|---|
| `jeju/research/20261010_joint_relationship_v1/ARTIFACT_MANIFEST.json` | `d0d1a749afb6a6f894de1bb4263c9d67dd1e3b2d1a35bf1b5fd38d8948c656b0` | Locks the joint study's sources and outputs |
| `jeju/research/20261010_joint_relationship_v1/outputs/report/all_triples.parquet` | `13409e65353c0cb6dab14df97317cce24de913056ae464ee3524520759de681c` | 402,808 rows, two probability arms |
| `jeju/research/20261010_joint_relationship_v1/outputs/report/runner_marginals.csv` | `0e6a01607164a7cb54fbbb5fb445e975ea9fbadad21d4e7a842adfc915616a09` | Runner-level Top3 inclusion probabilities and labels |
| `jeju/research/20261010_joint_relationship_v1/outputs/report/race_metrics.csv` | `89820acf0dfafc749f394cf9e74a3b58a5ec890e2c746f890ad257eaf32ff115` | Per-race summary, including fixed six-ticket results |
| `jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet` | `036939bd6d518a9e53d458a2f4eb2bf30bfecfa4bb80e21c78edd1f7f44f028f` | Locked roster, finish labels, dates, and saved style inputs |
| `jeju/research/20261010_style_history_ablation_v1/ARTIFACT_MANIFEST.json` | `6afc0e8f73ec086052fad4cde4d7edcd62fdf1bbc782108da89732dc3a5b4a4e` | STYLE6 source/artifact manifest |

The saved cohort is 1,779 races, 17,412 runners, and 269 race dates from 2024-01-05 through 2026-09-19; 2026 is partial. The existing study describes this as a retrospective, repeatedly used development cohort. Its independent reproduction passed, while both preregistered performance gates failed. This review does not recalculate or reinterpret those outcomes.

The Parquet schema confirms that `all_triples.parquet` has `triple_numbers`, `probability`, and `canonical_rank`, but no first-, second-, or third-place slot. Runner marginals include Top3 labels/probabilities, but no exact-position probabilities. The source finish labels can score rank-based choices after the fact; they do not turn the saved unordered probability distribution into an ordered one.

## What the saved distribution identifies

Let `Q_r(S)` be the saved probability of the unordered exact Top3 set `S` in race `r`, where each `S` contains three distinct horses and the race distribution sums to one.

For a fixed pair `A={i,j}`, the joint probability that both horses appear somewhere in the Top3 is identifiable:

`p_pair(A) = sum_{k not in A} Q_r({i,j,k})`.

When `p_pair(A)>0`, the conditional distribution of the remaining Top3 member is also identifiable:

`p(k | A both in Top3) = Q_r({i,j,k}) / p_pair(A)`.

These are unordered Top3 events. The remaining candidate is the third *member of the Top3 set*, not necessarily the horse that finishes in third place. Selecting `m` completion horses yields `m` unordered Top3 tickets, with model-assigned hit mass `sum_{k in C_m} Q_r({i,j,k})`; its conditional completion coverage is that mass divided by `p_pair(A)`. If the pair probability is zero, conditional completion is undefined.

For a single anchor `i`, its Top3-inclusion probability is `p_i = sum_{S contains i} Q_r(S)`. If `p_i>0`, the conditional distribution over unordered companion pairs is `Q_r({i,j,k})/p_i` for each pair `{j,k}` excluding `i`. Thus an anchor-plus-`m`-companion-pairs policy is identifiable from the saved distribution too.

An exact Top2 pair is not identifiable from this `Q`. A distribution assigning all probability to `{i,j,k}` is unchanged whether `i,j` finish first and second or whether `k` takes one of those positions. The same loss of order prevents deriving exact win/second/third probabilities and ordered quinella/exacta-style events from the saved table. That branch needs an ordered joint distribution or a separately specified rank model and its own calibration/evaluation contract.

## Fixed selection contract to freeze before outcomes

If the next study stays within the saved unordered Q, treat the primary target as **a selected pair that both land in the Top3, followed by one of the selected completion horses landing in the same Top3 set**. Name the remaining horse a “completion horse” in reports, not “third-place horse.”

- Choose the pair only from pre-race probabilities, using the largest pair-in-Top3 marginal. Choose completion horses by descending `Q_r({i,j,k})`; conditional ranking is identical because the pair denominator is constant. Never use labels to choose the pair or completions.
- Freeze ticket budgets `m` before looking at labels. If evaluating `m=3`, `4`, and `6`, report each separately; do not compare hit rates across budgets or select a winning budget after seeing results.
- Give every candidate and control the same race roster, probability arm, ticket budget, and label set. A useful equal-budget allocation reference is the globally highest `m` triple probabilities from the same Q, which maximizes the model-assigned mass among all `m`-ticket subsets. To compare probability arms, apply the same anchor rule and `m` to the H2-matched baseline and candidate Q. Keep allocation-policy comparisons distinct from probability-model comparisons.
- Preserve exact ticket counts. Resolve equal pair marginals by ascending `(horse_number_i, horse_number_j)` and equal completion probabilities by ascending horse number; use the existing canonical triple order for global top-`m` ties. Do not expand a tied cutoff into extra tickets.
- Report the pair event separately from completion: pair hits / all eligible races; then completions hit / races where the selected pair was actually in the true Top3. Also report unconditional full-ticket hits / all races and the model mass assigned to selected tickets. Publish every numerator and denominator; never show the conditional rate alone as overall hit probability or certainty.
- For paired policy differences, resample whole race dates and recompute each metric inside every replicate. For conditional completion, recompute both numerator and pair-hit denominator per replicate, report undefined replicates if a resample contains no pair-hit races, and show how often that occurred. Keep the same paired dates for both arms.
- Add probability calibration or reliability summaries for pair-in-Top3 and conditional completion mass, with fixed bins and counts set in advance. Do not describe a high predicted mass as certainty.
- Keep the present normal-completion, complete-roster cohort and its T−2/history limits. State that the rows are retrospective and repeatedly used; this comparison cannot establish performance on future races.

The single-anchor route is an identifiable alternative, but it is a different policy family and must be labeled as such. If both anchor families or both pair-Top3 and exact-Top2 targets are examined, predeclare one primary question and keep the rest as separately labeled exploratory results; do not choose the headline after looking at hits.

## Independent frozen-policy validation

The validator in `independent_validation.py` reads the pinned immutable source files and frozen plan only. It does not import the A analysis or joint-study helper code. The receipt records the plan, input-contract, precompute-lock, and source hashes before and after execution. It checks complete triple coverage, roster and API/horse identity joins, finish-label parity, one true unordered Top3 set per race and arm, normalized probabilities, the sum of runner Top3 marginals and pair-in-Top3 marginals, exact energy/tie rank parity, and saved unrestricted K=6 tickets.

The check passed for all 1,779 races, 17,412 runners, and 269 dates (2024-01-05 through 2026-09-19; 2026 is partial), with 402,808 saved triples and 3,558 race-arm top-six parity checks. The saved six-ticket reference reproduced 407/1,779 hits for matched baseline and 423/1,779 for candidate. All five frozen policies were independently selected and scored at K=3 and K=4: 35,580 race-policy rows and 124,530 selected tickets. A synthetic exact-tie fixture passed. Across all 3,558 race-arm cases, shuffling triple input rows and changing truth labels did not change policy selection.

Independent output comparison against A's frozen per-race table matched all 35,580 K3/K4 rows: selected ticket identities and order, saved q mass, ticket labels, axes, axis labels, and secondary exact-Top2 labels had zero differences. The four frozen primary paired date-bootstrap comparisons also matched A's point estimates and 95% intervals exactly; the C validator reports only those four prespecified contrasts, not exploratory intervals for the other policies.

The primary candidate counts were maximum-joint-pair 246/292 ticket hits at K=3/4, single-anchor 247/300, and unrestricted 248/302. Matched-baseline counts were 236/294, 233/296, and 233/298, respectively. The maximum-pair p≥0.6 subset had 6 candidate races with 2 pair-axis hits and 8 baseline races with 4 hits. The single-anchor p≥0.8 subset had 55 candidate races with 45 axis hits and 60 baseline races with 48. These small threshold subsets need wide-interval caution; the fixed retrospective coverage slices do not promise future coverage. The full race denominators and conditional completion denominators are retained in the per-policy summary.

An additional structural check confirmed that, in all 1,779 matched-baseline races, the maximum-joint pair, top-two marginal pair, and K-ticket-mass pair axes coincide at both K values. The additive unary baseline ranks the highest-scoring horse as the single anchor, and its unrestricted top-three tickets all contain that horse, so the single-anchor K3 tickets exactly equal unrestricted K3 in all 1,779 races. Treat these as duplicated baseline selection controls, not independent votes. The pair-in-Top3 joint probability is still a distinct event from multiplying two marginal probabilities, and K3/K4 pair-ticket completion remains a separate conditional event. These source-level structural statements follow the frozen baseline definition `E(S)=sum_{h∈S} score(h)` in the joint-study `joint_model.py`; the saved baseline relationship-energy column is zero.

The observed exact-Top2 pair counts are outcome-only labels and are not probability estimates. A pair event is “both selected horses in the unordered Top3”; a completion ticket adds the remaining *member* of that unordered set and does not assert third-place finish. No result here establishes future performance, a finish-order distribution, exacta value, returns, or operational readiness.

### 고정 단일축 cutoff 보충 검증

A의 최종 README 해시 `5c737060cd6c46d52f95cdb930e99b35fd0754645b714ac10ceb8c8363bf7a04`와 독립 C의 행별 결과 해시를 고정한 별도 검증은 ≥0.6 및 ≥0.8 부분집합을 같은 경주의 unrestricted K=3/4와 대조했다. ≥0.8에서는 candidate 55경주와 matched baseline 60경주 모두, K=3과 K=4 각각 선택한 티켓 목록이 모든 경주에서 완전히 같았다. 이 구간은 관찰된 축 성공률을 보여 주지만, 고정축 정책이 다른 티켓을 선택해 성과를 바꾼 사례는 아니다. ≥0.6에서는 candidate 684경주와 baseline 693경주였고, 티켓 적중 수 차이는 K=3에서 양쪽 모두 0, K=4에서 각각 −1건과 +1건이었다. 날짜·연도별 표본 수, 축 성공 분모, 조건부 완성률, 동일 티켓 목록 수는 [supplemental_fixed_cutoff_receipt.json](outputs/supplemental_fixed_cutoff_receipt.json)에 남겼다. 이 부분집합은 사후 과거 경주이므로 미래 coverage나 정책 우위를 보장하지 않는다.

## Instructions reviewed

The applicable Jeju instructions were read: `jeju/AGENTS.md`, `jeju/docs/RESTART_PLAN_20260928.md`, `jeju/docs/JEJU_PREDICTION_OBJECTIVES_2026-09-28.md`, `jeju/research/RESEARCH_PUBLICATION_POLICY.md`, and `jeju/review_documents/README.md`. They require preserving the baseline and old research, using the complete runner set and joint set probabilities, distinguishing Top3 inclusion from exact order, fixing ticket budgets before evaluation, retaining date-level uncertainty, and distinguishing retrospective development from future validation. The code-security skill was also read; this phase added no executable code.
