# F1_STYLE6 Top5 direct selector: primary gain/loss diagnosis

Status: **locked before this study's condition summaries**. This is a retrospective description of the already completed selector comparison. It does not fit, tune, or apply a new selection rule.

## Question and comparison contract

Describe which pre-race conditions and runner substitutions differ between the 31 primary races where the frozen additive head included all three actual Top3 runners and the frozen raw-score Top5 did not (`caught`), and the 35 races with the reverse outcome (`lost`). The denominator for condition summaries is the full fixed primary cohort of 1,503 races, including the 1,249 unchanged selections. The 66 `caught`/`lost` races are a post-outcome discordant subset; they are not a standalone discovery sample and cannot establish a deployable condition rule.

| Primary cohort outcome | Races |
|---|---:|
| Both selections hit all three | 404 |
| Head only (`caught`) | 31 |
| Raw-score Top5 only (`lost`) | 35 |
| Both miss at least one | 1,033 |
| Total | 1,503 |

The full 1,779-race cohort is secondary and remains distinct: 38 caught, 37 lost, 482 both-hit, 1,222 both-miss. No primary/full counts are mixed.

## Fixed condition variables

Every race-level condition below is formed from pre-race inputs. For runner-level race summaries, use the **raw-score rank-5 runner** (the boundary runner of the frozen baseline Top5), so every primary race has exactly one defined subject. The 254 changed races receive a separate added/removed runner analysis; unchanged races have no added/removed runner and are marked `not_applicable`, not zero or missing.

1. Race-level: year, distance, source `grade_raw`, and exact field size.
2. Raw-score fifth-minus-sixth score gap: retain raw gap in score units and report its continuous distribution; z-gap is the same gap divided by within-race population SD (`ddof=0`, zero SD gives zero). Fixed z-gap bins: `<=0.10`, `(0.10,0.25]`, `>0.25`.
3. Rank-5 boundary runner: `observed_starts` bins `0`, `1–4`, `5+`; `valid_n5` bins `0`, `1–2`, `3–5`; `same_valid_times` support (`0`, `1`, `2+`); `days_since_start` bins `<15`, `15–28`, `29–60`, `61+`, and missing.
4. Rank-5 boundary runner's last, mean of up to 5, best of up to 5, fast-two mean of up to 5, standard deviation of up to 5, and recent trend values are described in seconds **within distance only**, with each metric's observed count and `valid_n5` support. No raw time is pooled across distances. Style inputs are the three saved relative-position means and their respective support counts; means are shown only with support, counts use their exact 0–5 values. These features are historical summaries, not current-race positions or causal effects.
5. For changed selections, separately retain each added/removed runner's raw-score rank, score, career/reliability, recent form, and style values with supports, plus whether it actually finished Top3. Compare additions with removals as race-equal set means. Only one-add/one-remove races receive a direct runner pair difference. For 2+ swaps, never invent one-to-one horse pairings.

## Outcome tables and uncertainty

Each categorical condition cell reports the full cell denominator, changed selections, caught, lost, both-hit, both-miss, baseline/head all-three hits and rates, and net count (`caught − lost`) and net percentage-point difference divided by that cell's full race denominator. The only cross-tab is year × distance (at most 12 cells); every other condition is one-way. Form-value descriptions are stratified by distance and the four primary race-outcome groups. Cells with fewer than 30 races are marked small; no cell is promoted or selected by a p-value. Where estimated, 95% intervals resample dates using the pre-existing frozen 2,000 × 269 schedule, retain `method='linear'`, and mark the interval undefined if a replicate has no member of the condition group.

For each changed race, decompose the exact selected-set energy difference `E_head(Snew) − E_head(Bold)` into raw-score prior and all 11 standardized runner-input contributions using the existing evaluation-year head and its saved train-fold scaler. The choice file's `baseline_energy` is the **prior-only** energy; it will not be substituted for `E_head(Bold)`. Report individual contributions for exact arithmetic, and grouped contributions for interpretation: career (1), same-distance experience (2), rank (2), style mean (3), style support (3). Due to strong collinearity, individual feature contributions are arithmetic allocations, not independent or causal importance.

## Source, outputs, and limits

Read-only sources: frozen main `FINAL_MANIFEST.json` and its `candidate_choices.jsonl`, `CHOICES_RECEIPT.json`, `race_outcomes.jsonl`, `outcomes.json`; `baseline_runner_predictions.parquet`; `features.parquet` (pre-race allowlist, then a separate `finish_position` label read for post-choice decomposition); yearly fitted head JSONs and fit receipt; and the frozen date bootstrap schedule. Verify and record source paths and SHA-256; do not copy source parquet, full runner roster, database, candidate sets, models, or training matrices.

This study writes only a compact source audit, this locked plan, code, a 1,503-row race ledger, the changed-race energy ledger, changed-runner ledger, condition/form summaries, and a Korean README under this directory. Keep total storage under 10 MB (target <2 MB). Results remain repeated-use historical development evidence, with no operational adoption, independent holdout claim, causal claim, or new performance comparison by condition.
