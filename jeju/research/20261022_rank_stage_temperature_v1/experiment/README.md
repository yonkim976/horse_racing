# Rank-stage temperature experiment

## Result

The one F1_STYLE6 candidate used sequential full-field PL with separately fitted `T1=0.964852115736921`, `T2=1.2410594884809307`, and `T3=1.5195802928274653`. Each scalar was fit independently by race-equal conditional NLL on the same 2,492 raw OOS races from 2019–2023, bounded to `[0.35,4.0]` without regularization. The saved raw scores were used as-is; the score model was not retrained and provider tau/probabilities were not used.

Every stage normalized over the full remaining field: rank 1 over `N`, rank 2 over `N−1`, and rank 3 over all `N−2` starters left after removing the first two. The third-stage risk set included actual finishers below third. The 2019–2023 training objective improved over the common-T reference at each stage by `−0.0089863531`, `−0.0003468548`, and `−0.0073172333` mean conditional NLL, respectively. All three fits were interior to their bounds; inverse-temperature gradient/Hessian diagnostics and common-T comparisons are in [fit_receipt.json](outputs/fit_receipt.json).

The primary TRI gate passed against the prior common-T comparator `T=1.1837152381349905`. Candidate-minus-common TRI race-equal NLL was `−0.0101346964`; its fixed 2,000-draw date-paired 95% interval was `[−0.0179419430, −0.0023730696]`. TRI sum-Brier difference was `−0.0000904367`.

The WIN protection gate failed against raw `T=1`: candidate-minus-raw NLL was `+0.0007926712`, and Brier was `+0.0003219947`. Since both TRI and WIN conditions were required, the overall gate is **FAIL_OR_PARTIAL**. WIN improved against common T but still did not meet the separate raw-T1 protection condition. No statistical non-inferiority claim is made.

All pool differences below are candidate minus common T. NLL is race-equal; Brier follows the categorical sum-Brier or within-race ticket-Brier contract.

| Pool | Races | Δ NLL | Δ Brier |
|---|---:|---:|---:|
| WIN | 1,779 | −0.002684570 | −0.000505813 |
| PLC | 1,743 | +0.000039100 | +0.000003274 |
| QNL | 1,779 | +0.000010114 | −0.000209009 |
| EXA | 1,779 | −0.002443680 | −0.000226268 |
| QPL | 1,779 | +0.000030670 | −0.000002464 |
| TLA | 1,779 | +0.000727839 | −0.000023534 |
| TRI | 1,779 | −0.010134696 | −0.000090437 |

The 2024–2026 evaluation data contain 1,779 races, 17,412 runners, and 269 race dates. They were reused during development and do not form an independent holdout. PLC excludes the same 36 actual-seven-runner races whose sales-opening roster is unknown; the other six pools retain all 1,779 races. Pool annual comparisons and candidate calibration bins are in [pool_year_comparisons.parquet](outputs/pool_year_comparisons.parquet) and [candidate_reliability_bins.parquet](outputs/candidate_reliability_bins.parquet). Reliability bins use the fixed prior edges and pooled ticket-event-count weighting, separate from race-equal proper scores.

With the same `p >= pmax − 1e−12` then lexicographic horse-number rule applied to candidate, common-T, and raw-T1 diagnostic arms, no selected ticket keys changed in any pool. Hit counts were therefore unchanged across these arms. `selected_probability` is the chosen ticket's actual probability; the tolerance affects selection diagnostics only. Selection changes or hits are not an additional model-improvement gate, and no raw-score ordering was assumed for ordered MAP. The compact selection record is [selection_ledger.parquet](outputs/selection_ledger.parquet); changed-ticket details are in [selection_change_ledger.parquet](outputs/selection_change_ledger.parquet), which is empty under this comparison.

## Scope and interpretation

All seven event definitions, minima, and PLC denominator rules follow the read-only [rules contract](../../20261022_joint_wager_baseline_v1/rules_contract/README.md). Historical pool offering and settlement were not audited race by race, so these are structural event probabilities, not payout reconstruction or ROI. The evaluation outcomes were previously used in development; the fixed bootstrap holds fitted temperatures fixed and omits fit uncertainty. A TRI gate pass by itself would not establish all-pool superiority, improve native `q(T)`, or justify a production change. The WIN protection failure makes the full proposed gate unsuccessful.

## Reproduction and artifacts

Preparation checks passed with:

```bash
.venv/bin/python jeju/research/20261022_rank_stage_temperature_v1/experiment/rank_stage.py --synthetic-checks
.venv/bin/python jeju/research/20261022_rank_stage_temperature_v1/experiment/rank_stage.py --source-preflight
```

The approved fit/evaluation command was run once:

```bash
.venv/bin/python jeju/research/20261022_rank_stage_temperature_v1/experiment/rank_stage.py --fit-evaluate
```

It used supervisor approval SHA-256 `22c6279a63f9eb1e15e716374adea7996bae2ea5c5e0cf07ee952ef093877d95`. The command refuses existing result files, so it will not overwrite this run. The evaluation streamed each race's ordered PL mass into runner and ticket aggregates, then discarded the full Q distribution. No output stores all ticket probabilities.

The independent supervisor verification passed: 3,625,272 ordered triples, 12,417 candidate race/pool metrics, 17,412 runner marginals, 37,251 selection rows, 24,834 prior metric rows, the 2,000-draw date bootstrap, and the three fitted-point derivatives were independently checked. Its recorded verdict is TRI gate true, WIN protection false, and overall gate false in [RESULT_REVIEW.json](../supervisor/RESULT_REVIEW.json).

To reproduce the independent check against the preserved results, run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python jeju/research/20261022_rank_stage_temperature_v1/supervisor/verify_results.py --check-only
```

This experiment folder is sealed. Do not rerun `--source-preflight`: it rewrites the preflight receipt and changes the approved input hash. Use the supervisor's `--check-only` command to verify this run. Any new fitting requires a separate new research folder.

Key implementation and provenance hashes:

- [PLAN.md](PLAN.md): `2e43a53a8f6ea8fcf925b5e54bb36858c0e1b13269b6d3a672964e36ed33aa3c`
- [rank_stage.py](rank_stage.py): `ac4c9693a6017539833bb19847a731609541789f27777cf093d7ef3b6837daa6`
- [source_preflight.json](outputs/source_preflight.json): `a62278e5e24434581d07806c708ef3eb2ec9d261fa781f1e0ab272bd00868612`
- Raw asset manifest: `ea2d2b0363539f3b7b0b88c3b2254c14f04095715ac1f137f71beba77a9a36a3`
- Rules contract: `20cd4b17274018a36efbb1b0cea64eb5d5c9809ed5f3481bea59c734f99fee83`
- [report.json](outputs/report.json): `94cca5139551638bcbacd789714e689f2d666f92d7e3df0ff8a6b14e611d3a80`
- [fit_receipt.json](outputs/fit_receipt.json): `74e528a52f40f410005465ac53f47ad735cacaa0eb6a872c7248cbedeab33058`

The new experiment folder occupies approximately 2.84 MB, below its 20 MB cap. The prior baseline outputs are referenced by their original paths and hashes rather than copied.
