# Outcome code review before evaluation label access

Status: **PASS for the reviewed outcome source hash and the approved run.**

- `report_outcomes.py` SHA-256: `4c787aceb33afb8c926ad8c7a95d64d1f2a63011fa8d0a2072b992ef89c9311a`
- Final `select_sets.py` SHA-256: `332304c499615288b37d9bc485f45f926931dedaf35d8242a4823e14fc616d54`

The pre-run code review read source code, plan/receipts, and the choice ledger schema only; it did not open evaluation outcome columns. The outcome audit below was run later, after root approval bound the locked choices and this reporter hash.

## Approval and outcome data boundary

`main()` first verifies the locked choice and fit receipts, the expected full/primary race counts, and a separate outcome approval bound to the fit receipt hash, choices hash, choice receipt hash, selection code hash, outcome code hash, plan/source hashes, and source audit. The fit and selection modules imported at module load contain no data reads or execution of their `main()` functions. Only after `require_outcome_approval()` succeeds does the reporter parse locked choice ledgers, prior outcome summary, the frozen bootstrap files, and then the baseline parquet outcome allowlist.

The baseline reader requests exactly the declared `api_record_id`, race/runner metadata, variant, raw score, and binary `y` columns. The report validates `y∈{0,1}`, exactly three positive labels per race, complete unique runner rosters, exact five distinct selected IDs/numbers per arm, selection ID/number consistency, and raw-score Top5 identity. No labels or probabilities are used to change any selected set.

## Metrics and bootstrap

The locked three-arm comparison is raw-score Top5, prior partial-event NLL head, and the new reward head. It reports the all-three Top3 capture rate, paired caught/lost/both-hit/both-miss counts, captured-Top3 0/1/2/3 counts, and paired changes by primary/full population, year, and distance. The primary cohort is fixed to 900/1000/1110/1200m (1,503 races); all 1,779 races are the secondary cohort. It recomputes old-arm hit totals from the frozen old choice ledger and approved `y`, and checks those totals against the old outcome receipt.

The reporter loads the pinned 2,000×269 date schedule with `allow_pickle=False`, checks schedule/date inventory hashes, shape, dtype, index bounds, and the declared seed, then computes paired date-cluster bootstrap deltas with NumPy linear quantiles. The success gate requires both `reward−raw` and `reward−partial-NLL` primary deltas to be positive with 95% CI lower bounds above zero. Full-sample intervals and subgroup summaries are secondary.

The race-level output contains aggregate hit/capture/caught/lost flags and race metadata, not a copied runner feature table or full candidate-set space. Write-once outputs remain in the study's `outputs/` folder; code requires the independent approval before reading labels or creating outputs.

No blocking correctness or leakage issue was found. The independent `verify_locked_outcomes.py` replay opened the fixed `y` allowlist only after validating approval and then matched all 1,779 race ledger rows, all three arms, captured-count distributions, changed/caught/lost counts, year/distance summaries, four date-bootstrap intervals, and the main receipt. All 13 independent reconciliation checks passed; see `INDEPENDENT_OUTCOME_AUDIT.json`.
