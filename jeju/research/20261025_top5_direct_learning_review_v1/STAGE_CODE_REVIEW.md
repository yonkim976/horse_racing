# Selection and outcome-stage code review

Status: **PASS for the separately approved selection and outcome stages.** Final source snapshots:

- `select_sets.py`: SHA-256 `574de788e1f8e4a31c10354cf804bc83f99618c521dad6823a6fe13fa961361f`
- `report_outcomes.py`: SHA-256 `5d48a2430c1ad6a24ded4f861da64f64b7b5b669139b61e2acf57f07662fb608`

The root approval files bind these source hashes. I independently replayed all locked choices before outcome approval, then independently recomputed outcomes after the outcome approval.

## Selection script

`select_sets.py` reads an explicit baseline allowlist without `y`, `p_top3`, log-loss, Brier, finish rank, odds, or favorite; raw score parity reads only `api_record_id, score`. Feature inputs use the fit script's non-label allowlist and the saved fold-specific training scaler. It enumerates all `C(N,5)` choices one race at a time and saves only the race-level selection ledger and receipt. The `β=0` control requires the exact score-Top5 baseline set. The tie rule is deterministic: within the declared `1e-12` numerical tolerance, prefer greater baseline overlap and then the lexicographically smaller horse-number tuple. Since the fitted energy is additive by runner, exhaustive set maximization should equal ranking the five highest runner utilities under this tie rule.

The selection code reads `field_n` and `distance_m` only as roster/cohort metadata. The selection approval explicitly allows these columns; no outcome fields enter selection.

## Outcome script

The report verifies the choice artifact and receipt hashes, source/code/model hashes, and a separate root outcome approval before opening outcome columns from the frozen baseline parquet. Before reading labels, it now verifies the sorted primary race-date inventory from the hash-locked choices against the frozen `DATE_INVENTORY_SHA256` and checks the bootstrap schedule receipt, date count, seed, draws, schedule hash, shape, dtype, and index range. After reading outcomes it matches choice/outcome race dates, years, distances, field sizes, selected horse IDs/numbers, and the baseline score Top5 rule.

The outcome reader checks that `y` is exactly binary before integer conversion and requires exactly three Top3 labels per race. It emits the primary/full summaries, paired date-cluster bootstrap with the fixed linear quantiles and success gate, plus a compact per-race ledger with caught/lost events and captured/missed Top3 counts. The fit receipt's `training_label_validation` key exists for the report summary.

## Independent locked-choice replay

`verify_locked_choices.py` is standalone and imports no main study module. After checking the root selection approval and all file hashes, it re-read only the explicit non-outcome score/feature/roster allowlists. It reproduced the exact selected IDs, numbers, energies and candidate counts for all 1,779 races after enumerating 411,084 five-sets. The β=0 raw-Top5 control, row-reversal invariance, additive runner-utility argmax identity, and frozen raw-score parity all passed. It did not request or read `y`, finish rank, or evaluation metrics.

## Independent approved outcome replay

`verify_locked_outcomes.py` checks the root outcome approval, report code hash, choice/fit receipts, independent choice replay receipt, and report-output hashes before opening the fixed outcome allowlist. It independently reproduced every one of the 1,779 race ledger rows and all primary/full totals, year and distance subgroups, caught/lost/miss distributions, and the paired date bootstrap. All values match the main report; 2,000 scheduled replicates over 269 primary dates yield a 95% CI of `[-0.01343341952546293, 0.007752692064066596]` in rate units. The primary gate is false because the observed difference is negative and the interval includes zero.

Primary outcome: selector 435/1,503 (28.9421%), baseline 439/1,503 (29.2083%), difference −0.2661 percentage points; 31 selector-only catches and 35 baseline-only losses. Full sample: selector 520/1,779, baseline 519/1,779, difference +0.0562 percentage points. These are repeated historical development data, not a fresh holdout or calibrated probability claim.

No path traversal, shell command execution, dynamic code evaluation, database/network access, or unsafe deserialization was found. The bootstrap array loads with `allow_pickle=False`; source and output paths use the fixed, hash-checked confinement helpers. The outcome script must only be run after the root outcome approval bound to these final hashes.
