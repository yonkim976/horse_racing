# Source-only design amendment: saved F1 probability tie handling

Date: 2026-10-11. This amendment records a source-reconstruction exception approved by root after an outcome-free audit. The model, H1/H2 split, primary comparator, primary gate, and fit budget remain as specified in `PLAN.md` and `INPUT_CONTRACT.md`.

## Version history and hashes

| Snapshot | PLAN SHA-256 | INPUT_CONTRACT SHA-256 | Meaning |
|---|---|---|---|
| Initial reviewed design snapshot | `1188b0458ee70de520a638c31888e391f38b778b76e360bb40397bfce68cfd37` | `6468b16829861b22a6285a8e2ff07fecde926a30a46b280a3c3a3f85178d1f31` | Pair-model design after root/design review, before final source-specific checks. |
| Provisional source-check snapshot | `a593560afd6cf1ee4fd95af91e9107b006ebe6f01876f211f5d7cf3ee12a2f67` | `46df32b295bc009466902069661966ac4aec9e8d5c129f0e5c5970716c95703c` | Added `latest_history_date`, report-only distance metadata and an initially strict saved-probability/raw-score parity assertion. The contract still contained an outdated `N_r<3` wording at this intermediate point. |
| Approved amended documents | `7fab8fa552d0572e303e626df153b4a231820544b9394d61f133a0f44c917ee5` | `01b811a7a8aaaae43c7bb16fd08e5505ffbd385e285b6aa6cdb471c15da80b6d` | Current documents: `N_r<4`; exact-boundary tie exception below; all other approved constraints retained. |

The source-specific edit corrected the intermediate strict parity rule after it failed on stored values. The raw-score Top2 remains the primary comparator, and saved `F1_STYLE6 P(Top3)` Top2 remains a separate comparator with its saved selection intact.

## Outcome-free parity diagnostic

For each evaluation fold, compare the two highest saved raw scores from that fold's `evaluation_scores.parquet` with the two highest `saved_f1_style6_p_top3` values in the locked marginal source. Across 1,779 races, six selector differences occur. All six have an exact raw-score tie at rank 2 versus rank 3; the saved-probability rank-2/rank-3 gaps are 0 or at most `5.551115123125783e-17`. The selector differences therefore arise within a tied raw-score boundary and reflect floating-point accumulation in the stored probability reference.

| Evaluation race | Raw-score Top2 | Saved-probability Top2 | Rank 2 = rank 3 raw-score tie | Saved probability rank-2/rank-3 gap |
|---|---:|---:|---:|---:|
| `2024-03-15_2_1` | 1, 9 | 7, 9 | yes | 0 |
| `2025-03-07_2_1` | 3, 6 | 6, 7 | yes | 0 |
| `2025-08-08_2_1` | 3, 5 | 5, 8 | yes | 0 |
| `2025-12-19_2_1` | 1, 9 | 7, 9 | yes | `5.551115123125783e-17` |
| `2026-07-18_2_1` | 3, 7 | 5, 7 | yes | 0 |
| `2026-07-24_2_1` | 1, 4 | 1, 7 | yes | 0 |

This diagnostic reads score, horse number, and saved probability only. It does not read labels or compute pair hits. The approved preflight rule is: require exact selector parity when raw scores at ranks 2 and 3 differ; when those scores are exactly tied, preserve the stored-probability pair as its own comparator and assert that its horses lie in the raw-score tie block at or above the rank-2 threshold, retaining every strictly higher-scored horse. The six rows above are a fixed source diagnostic, not performance evidence.

## Saved joint-marginal selector reconstruction

The saved `top_two_marginal_pair` policy is reconstructed from the locked full triple probabilities using canonical triple order and `math.fsum`, matching the pair-axis source calculation. The exported `candidate_joint_marginal` column is checked against these reconstructed values with the frozen numerical tolerance, but is not used to break selector ties: its decimal CSV round-trip can perturb exact ties by one ULP. For example, in `2024-03-08_2_2`, the export placed horses 4/7/8 at `0.3623581694235643` and 5/9 at `0.36235816942356419`, while canonical `math.fsum` gave an exact tie across 4/5/7/8/9; the saved policy selected 4,5 by numeric horse-number tie break. This was identified from source probabilities and the saved policy row only; labels and performance were not read. The preflight therefore checks export closeness, derives the selector from canonical triple masses, and asserts saved-policy parity.

## Preflight source lock

`PREFLIGHT_SOURCE_LOCK.json` pins the approved PLAN, INPUT_CONTRACT, this amendment, `core.py`, `preflight.py`, and all locked input hashes. The outcome-free structural receipt records that lock's SHA-256 and each pinned artifact hash. The receipt is write-once; an existing receipt causes a fail-closed stop.
