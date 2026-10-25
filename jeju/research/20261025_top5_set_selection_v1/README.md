# Top5 set-selection comparison

This retrospective study kept the frozen `F1_STYLE6` runner scores unchanged and compared their score-ranked Top5 with the five-horse set maximizing probability mass over every exact Top3 triple in the already fitted pair-interaction joint distribution. It performed zero new model fits and made no post-result rule or parameter changes.

On the prespecified 900/1000/1110/1200m primary cohort, score Top5 contained all three actual Top3 horses in 439 of 1,503 races (29.208%). Joint q-max Top5 did so in 415 races (27.611%), a paired difference of **−1.597 percentage points**. The frozen 2,000-draw date-cluster bootstrap 95% CI was **[−2.804, −0.402] pp**. The prespecified success gate was not met.

| Cohort | Score Top5 all-three hits | Joint q-max all-three hits | Difference |
|---|---:|---:|---:|
| Primary, 1,503 races | 439 (29.208%) | 415 (27.611%) | −1.597 pp |
| Full, 1,779 races | 519 (29.174%) | 500 (28.106%) | −1.068 pp |

The independent full-cohort paired date-bootstrap 95% CI was [−2.178, 0.000] pp. In the primary cohort, the annual hit counts were 140→130 in 2024 (499 races), 164→151 in 2025 (559 races), and 135→134 in 2026 through September 19 (445 races). The sets changed in 331 primary races and 386 full-cohort races. Primary candidate-only hits numbered 27 versus 51 baseline-only hits; full-cohort counts were 36 versus 55. Mean captured Top3 horses in the primary cohort were 2.057 for q-max and 2.072 for score Top5. Candidate expected coverage utility increased from 0.26930 to 0.27139, while observed all-three coverage declined.

The selection stage used the existing joint distribution without refitting or fitting a new model for this five-set decision. It chose exactly five unique runners per race and passed the matched-baseline unary negative control in all 1,779 races. Outcome labels were opened only by the separately approved report stage after it verified the selection artifact hash. Root independently reconstructed the probability mass and separately recomputed outcomes; the saved checks agree on the reported primary and full-cohort counts and primary CI.

Among baseline misses in the primary cohort, exactly one actual Top3 horse was outside the selected five in 759 of 1,064 misses (71.3%). That suggests a separate future research question around near-miss coverage; it does not change this completed analysis or its decision rule. Keep score Top5 as the established choice for this objective and hold the q-max candidate from adoption.

The historical 2024–2026 races were used in earlier development analyses. This is a repeated-use retrospective comparison, not an independent future holdout or model-promotion result. The reviewer's earlier schema inspection exposed some `y`/`logloss` values, disclosed in [PLAN.md](PLAN.md); those values did not inform selection or rule decisions.

See [outputs/REPORT.md](outputs/REPORT.md) for the short report, [outputs/metrics.json](outputs/metrics.json) for year/distance/career and miss-count detail, [outputs/selections.jsonl](outputs/selections.jsonl) for the hash-locked per-race selections, and [SOURCE_AUDIT.md](SOURCE_AUDIT.md) for source provenance and the fixed cohort.
