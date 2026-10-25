# Fixed R/S 50:50 mixture — execution results

The single approved run completed on 2026-10-22 with the fixed candidate `E = 0.5 Q_R + 0.5 Q_S`. It performed zero fitting, calibration, or weight search. It evaluated 1,779 races (17,412 runners; 269 dates): 637/654/488 by year. PLC uses 1,743 races because the 36 actual seven-horse races have unknown sales-opening rosters; each of the other six pools uses all 1,779 races.

The experiment's pooled, race-equal loss differences are shown below; negative values favor E. Values are rounded to six decimals from `outputs/pool_summary.parquet`.

| Pool | E−R Δ NLL | E−R Δ Brier | E−S Δ NLL | E−S Δ Brier |
|---|---:|---:|---:|---:|
| WIN | −0.018032 | −0.004736 | +0.003627 | +0.000997 |
| PLC | −0.004564 | −0.001935 | +0.000229 | +0.000107 |
| QNL | −0.030469 | −0.002227 | +0.002520 | +0.000194 |
| EXA | −0.031545 | −0.001203 | +0.002928 | +0.000148 |
| QPL | −0.001793 | −0.000329 | +0.000139 | +0.000039 |
| TLA | −0.040694 | −0.001656 | −0.000356 | +0.000340 |
| TRI | −0.043708 | −0.000322 | +0.000343 | +0.000076 |

E passes the fixed E−R comparison gate: TRI NLL difference −0.043708, date-bootstrap 95% CI [−0.053950, −0.033735]; TRI Brier difference −0.000322; WIN NLL and Brier differences −0.018032 and −0.004736. E fails E−S: TRI NLL difference +0.000343 with 95% CI [−0.009199, +0.010260], TRI Brier +0.000076, and WIN NLL/Brier +0.003627/+0.000997. Therefore `overall_research_candidate_gate_pass` is **false**. The E−S bootstrap interval includes zero; no statistical noninferiority claim is made.

The fixed WIN-axis top-three selection hit 1,027 of 1,779 races (57.73%), compared with the frozen R reference's 1,023. This descriptive selection count does not change the failed E−S probability gate. For the selected QNL/QPL diagnostics, E's mean realized hit-any rates were 0.1254/0.2771 for QNL k=1/3 and 0.2507/0.4930 for QPL k=1/3. QPL k=3 mean expected hit count was 0.6141 and its realized mean was 0.6352; exact union probabilities and count PMFs are in `outputs/pair_selection_diagnostics.parquet` and `outputs/pair_selection_summary.parquet`.

This is a reused development evaluation, not an independent future validation. It does not establish market return or justify operational promotion. Annual and per-pool details are retained in the output ledgers; the fixed candidate and comparison were not changed after seeing these results. Supervisor independent result replay remains separate.

Reproduction of the one-time execution is recorded in `outputs/fit_run_receipt.json`; rerunning is blocked by the consumed single-run claim. The command used was:

```sh
.venv/bin/python -B jeju/research/20261022_rs_equal_mixture_v1/experiment/rs_equal_mixture.py --run
```
