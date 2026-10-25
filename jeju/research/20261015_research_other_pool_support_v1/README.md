# Native probability support for pools beyond PLC and QPL

This audit checks which race events the saved `F1_STYLE6` research output can support on the same 467-race cohort used by the 2026 operating-versus-research postrace-value comparison. It performs no fit, calibration, promotion, database access, or network access.

The model has a binary runner Top3 score, not a native finish-order head. Its original F1 evaluator turns the three saved runner scores into an unordered exact Top3-set distribution. For each unordered set `T={i,j,k}`, it computes `E(T)=sum(sort(score_i,score_j,score_k))`, then `P(T)=exp(E(T)/tau)/sum_U exp(E(U)/tau)` over every `C(N,3)` set in the race. `tau` is read from the saved year-specific model metadata. Summing these native set probabilities over all sets containing a runner recovers its saved `p_top3`.

That makes **TLA (unordered exact Top3 set)** natively supportable. The other pools outside PLC/QPL are not supported by this model: **WIN** needs first-place probability; **QNL** needs the unordered first-two set; **EXA** needs first-to-second order; and **TRI** needs the exact first-to-third order. The unordered Top3 set and runner score ranks do not identify those events. The direct pair-ID candidate is a separate pair-event model and does not supply an ordered joint distribution.

`derive_tla.py` uses the original saved 2026 `F1_STYLE6` evaluation scores and saved `tau`, covering all 467 matched races, including races with seven runners. It writes every exact unordered triplet and its probability to `tla_set_probabilities.csv` and `.parquet`. It checks per-race total mass, the recovered runner marginals against saved `p_top3`, and the keys, probabilities, and hit labels of all six original native selections per race. The exact input and output hashes are in `SOURCE_MANIFEST.json`; checks are in `REPORT.json`.

Recreate the one-time artifact with:

```sh
.venv/bin/python -B jeju/research/20261015_research_other_pool_support_v1/derive_tla.py
```

The output is a source-support artifact for retrospective comparison. It is not independent validation, a claim of profitability, a new model, or an operating recommendation. It does not include tote quotes or calculate EV; those remain in the parent postrace-value comparison.
