# Initial selector-code review

Reviewed `jeju/research/20261025_top5_set_selection_v1/select_sets.py` before execution. No choice or outcome calculations were run during this review.

## Checks that pass

- The selector reads a fixed baseline subset that omits outcome columns, plus only race/triple/probability fields from the frozen joint file. It does not read odds, favorite, finishing rank, or `is_true_set` for choice generation.
- The baseline is raw F1_STYLE6 score descending with deterministic horse-number tie-break. The candidate enumerates every 5-subset, sums all ten exact Top3 probabilities with `math.fsum`, and applies the predeclared `1e-12` tolerance, baseline-overlap preference, then sorted number tuple.
- The per-race probability checks reject missing, duplicate, out-of-roster, nonfinite, negative, incomplete, or non-normalized triple distributions. The matched unary distribution is required to reproduce score Top5 in each race.
- Paths and source hashes are fixed. Output files are created exclusively in the study output directory. No database or network code is imported.

## Follow-up status before execution

The initial snapshot review identified three follow-ups. Before execution, the plan was clarified to allow a temporary in-memory load of the approximately 9.5 MB source probability table while prohibiting persistent all-set products; the selector was bound to the passing, label-free root Q-reconstruction receipt and locked source hashes; and the plan fixed the bootstrap quantile method to `numpy.quantile(method="linear")` at 0.025 and 0.975. Root approved the selector at SHA-256 `9bbd0556236dde13697f62dec70e7a81928bab1f57de0ab267008b429e94c4e2` with report execution initially not approved. A report-code hash race was detected before I executed an independent label aggregation; root preserved the original approval record and issued a revised v2 approval that binds report SHA-256 `3d39be089cce838a3f7993cb494b69d76fed1524dbbdc52e159dbaed8c8088d9`. The independent outcome calculation matched that v2 code's result.

The selector was independently replayed after the selection artifact was hash-locked. See `INDEPENDENT_CHOICE_AUDIT.json` and `CHOICE_AUDIT.md` for exhaustive choice verification. `verify_outcomes.py` then independently aggregated `y` after verifying the locked choices and v2 report approval. `reconcile_outcomes.py` matched all 1,779 race result rows against source outcomes and matched the main and root summaries, including the primary date-bootstrap interval. See the two outcome JSON receipts for hashes and comparison details.

## Frozen-model audit notes

The reused relationship parameters were fit without refitting the base F1_STYLE6 horse model. The original plan defines H1-only weighted population standardization (variance denominator is the valid weight sum, so `ddof=0`) and an H1 pair-residual RMS that averages within-race pair mean squares equally over races (also population averaging). The selector must reuse these stored parameters without estimating new scales or coefficients. The original evaluation years have chronological OOS score/model boundaries with T−2 purges, but the 2024–2026 evaluation races have been repeatedly examined; this is a retrospective development comparison, not an unseen holdout.

Reviewer visibility disclosure is recorded in `PREOUTCOME_REVIEW.md`: three rows from the first race exposed `y`, `log_loss`, and `brier` values during an earlier schema check. Those values were not aggregated or used to choose or alter the selector.
