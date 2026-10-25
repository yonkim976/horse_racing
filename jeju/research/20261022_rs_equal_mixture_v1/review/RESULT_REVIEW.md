# R/S 50:50 mixture — result review

**Review result: PASS. Candidate decision: HOLD.** The review passes receipt, denominator, gate, storage, and independent-verification consistency checks. The fixed 50:50 candidate fails its predeclared adoption gate because it does not beat S; the E−R protection comparison passes.

The single approved run completed with `COMPLETED_RESEARCH_ONLY`, `run_count=1`, and zero fits, calibrations, or weight searches. I checked all 13 receipt-listed artifacts against their SHA-256, byte counts, and Parquet row counts; they match. The receipt's approval, source-preflight, code-bundle, and gate hashes agree with the saved records. The experiment occupies about 3.0 MB against its 25 MB cap. The new ledgers contain 1,779 races / 17,412 runners / 269 dates, with 1,743 PLC races because 36 actual-seven-runner races have unknown opening rosters. The other six pools each contain 1,779 races. Seven-pool losses are reported overall and by year.

E is the fixed mixture of each arm's separately temperature-adjusted, normalized full-field **ordered first-three (Top-3) joint distribution**. It is not a model of the complete finishing order after third place.

The result gate is unambiguous:

- **E−S fails.** TRI NLL difference is +0.000343 (date-bootstrap 95% interval −0.009199 to +0.010260), so the interval's upper bound is not below zero. TRI Brier is +0.000076; WIN NLL and Brier are also positive (+0.003627 and +0.000997).
- **E−R passes.** TRI NLL difference is −0.043708 (95% interval −0.053950 to −0.033735), TRI Brier is −0.000322, and WIN NLL/Brier are −0.018032/−0.004736.

Since the contract requires both comparisons, `overall_research_candidate_gate_pass` is false. The report and run receipt agree on this decision. The supervisor's independent verifier passed: it replayed 3,625,272 ordered triples and found all pool losses, marginals, selected probabilities, pair-hit-count PMFs, reliability rows, and bootstrap values within reported numerical tolerance; it confirms E−S false, E−R true, and overall false. Six protected pins remained unchanged. The paired bootstrap is conditional on these frozen predictions over a reused development period; it does not include fitting uncertainty. E−S fails the adoption gate, but the TRI NLL interval crosses zero, so this is not evidence of statistically significant worsening.

The WIN axis is 1,027 Top-3 selections: 4 more than R's 1,023, but 17 fewer than S's 1,044. The R-relative change is about +0.39%, far short of the 1,126-hit +10% reference target; this descriptive axis result cannot override the failed proper-loss gate. Do not generalize this hold to other ensemble weights or ensemble designs: only the fixed 50:50 mixture was tested.

**Recommendation:** retain E as a non-adopted research result, keep S as the current research candidate and R/F1 as its baseline, and leave the registered operational `HY_R_FORM` unchanged. This run contains no market-price or ROI evaluation and is not independent future validation. Its complete-finish cohort, unknown pre-race public-information timestamps, and unverified purchase-time roster remain limitations.
