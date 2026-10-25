# Independent review: Top-5 set selection

This folder records an independent mathematical, source, selection, and outcome review of `20261025_top5_set_selection_v1`. All new files here total about 120 KB, far below the 20 MB study target. Source parquet/model/bootstrap assets are referenced by path and SHA-256; no copies were made.

## Finding

The frozen pair-interaction joint distribution's five-runner set maximizer did **not** improve the prespecified event: capturing all three actual Top3 horses. On the primary 900/1000/1110/1200 m cohort, score Top5 hit 439/1,503 races (29.2083%); joint-q-max Top5 hit 415/1,503 (27.6114%). The paired difference was −1.5968 percentage points, with the frozen 2,000-draw race-date bootstrap 95% interval from −2.8039 to −0.4024 points. The prespecified gate failed because both the point difference and its lower confidence limit were below zero. The historical full cohort was also lower: 519/1,779 baseline hits against 500/1,779 candidate hits (−1.0680 points).

The decision supported by this retrospective comparison is to retain the frozen F1_STYLE6 score Top5 and hold the joint q-max set candidate from adoption. This does not establish future performance: the 2024–2026 history was examined in previous research and is not a fresh holdout.

## Independent checks

- The probability objective is `q(S) = sum P(T)` over the ten exact unordered Top3 triples contained in each five-runner set. Individual-runner PL weights and a unary additive exact-set softmax are mathematically degenerate for this fixed-score objective: their maximizing five-set is already score Top5. The frozen pair-residual Q distribution is the compatible non-unary source. The rate-swap PL proof is stated in `PREOUTCOME_REVIEW.md`.
- `verify_choices.py` independently rebuilt all race Q maps from frozen triple probabilities and exhaustively evaluated every `C(N,5)` set. All 1,779 choices matched the locked main ledger; the matched-unary negative control matched score Top5 in all races. It read no outcomes. The selection ledger SHA-256 is `1f3d40769939b82afe4f6278f92bf5f13af85329355a4a03ddc036391d55322d`.
- After the choices and report-stage approval were hash-checked, `verify_outcomes.py` independently read the raw `y` field and computed primary/full hit counts, capture/miss distributions, overlap, subgroups, and the fixed date-bootstrap interval. It did not import the main report or selector.
- `reconcile_outcomes.py` compared all 1,779 report rows against raw `y` and locked horse IDs, checked all 494 aggregate/subgroup comparisons against the main report, and reconciled the primary counts, rates, interval, and gate with the root's separate computation. Root's three-way receipt records 35 passing checks across the main, root, and independent summaries.

The independent machine-readable receipts are `INDEPENDENT_CHOICE_AUDIT.json`, `INDEPENDENT_OUTCOME_AUDIT.json`, and `OUTCOME_RECONCILIATION.json`. Their source and code hashes are catalogued in `FINAL_MANIFEST.json`.

## Disclosure and scope

During an earlier schema inspection, this reviewer saw the first three rows containing `y`, `log_loss`, and `brier`. Those values were not aggregated or used to alter the comparison, cohort, or selection rule. We do not describe all reviewers as label-blind. The root Q rebuild, selector, and independent choice replay read no outcome labels; outcome data were opened only after the choice ledger was locked and outcome-stage execution was approved.

The first invocation of `verify_outcomes.py` halted after opening `y` because a pandas timestamp conversion used a Series method incorrectly; it wrote no output. The call was corrected to use `.dt.strftime`, and the complete independent run and reconciliation then passed. No database, network, model registry, or operating model was changed; no model fitting or post-result tuning occurred.
