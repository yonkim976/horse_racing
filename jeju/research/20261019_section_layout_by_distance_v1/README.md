# Jeju per-horse section-time layout by distance

This is a read-only source and measurement-layout proposal. It identifies the non-overlapping per-horse intervals supported by the stored cumulative checkpoints and finish-section durations. It does not fit a model, compare predictive performance, or change the database or model registry.

## Scope and source

The audit used the frozen 92,513-row `outputs_v2/source_snapshot.parquet` from the existing Jeju baseline study to define the horse/race roster, then read the current quality-selected per-horse time fields from `jeju_race_section_time_values`. The scoped period is **2017-01-01 through 2026-09-19 inclusive**, Jeju meet code 2, and the requested distances 400, 800, 900, 1000, 1110, 1200, 1300, 1400, and 1610m. The inherited starter rule is finish position 1–89 or 91/92. The result contains 57,876 starter rows in 5,828 started races. No 2026-09-20 or later results are included.

The time fields are the current view-selected API4 values for S1F, 1C–4C, G3F, and G1F, including applied website corrections and unresolved time-review holds. A positive field value is counted when the selected time is positive and its status is `api_positive_unreviewed` or `website_corrected`. Coverage below is **time-field support only**. It does not apply the full-race order/group point mask or the inherited feature-eligibility contract, so none of these counts are model-ready usable-record counts. Existing unresolved order/group conflicts remain out of bounds for a future feature-reuse decision until separately reviewed.

The main DB connection used SQLite URI `mode=ro` with `PRAGMA query_only=ON`. The ID table used to restrict the query was connection-local temporary state. Source hashes cover the selected race rows and their selected field/status/provenance values by distance; no whole-database hash is claimed. See [the machine-readable audit](source_audit.json) for the scoped hashes, input snapshot hash, view-definition hash, and exact filters, and the [artifact manifest](artifact_manifest.json) for output hashes. No source collection was performed.

## Starter support and time-field coverage

“Candidate” includes all frozen API4 rows at the distance; “started” uses the inherited starter rule. Field counts are positive time-view selections among starters.

| Distance | Candidate rows / races | Started rows / races | Date range | S1F | 1C | 2C | 3C | 4C | G3F | G1F |
|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 400 legacy | 1,266 / 135 | 1,258 / 135 | 2017-01-14–2018-12-28 | 1,257 | 0 | 0 | 0 | 0 | 0 | 1,257 |
| 800 | 14,068 / 1,423 | 13,813 / 1,411 | 2017-01-13–2026-02-06 | 13,803 | 0 | 0 | 13,803 | 13,802 | 13,801 | 13,801 |
| 900 | 9,915 / 993 | 9,718 / 981 | 2017-01-13–2026-09-19 | 9,716 | 0 | 0 | 9,716 | 9,716 | 9,715 | 9,715 |
| 1000 | 15,849 / 1,560 | 15,505 / 1,536 | 2017-01-14–2026-09-19 | 15,504 | 0 | 0 | 15,504 | 15,503 | 15,503 | 15,503 |
| 1110 | 10,913 / 1,078 | 10,703 / 1,064 | 2017-01-13–2026-09-19 | 10,701 | 0 | 0 | 10,701 | 10,701 | 10,700 | 10,700 |
| 1200 | 5,273 / 529 | 5,178 / 522 | 2017-06-16–2026-09-18 | 5,177 | 0 | 0 | 5,177 | 5,177 | 5,176 | 5,175 |
| 1300 | 680 / 71 | 666 / 70 | 2024-05-18–2026-09-04 | 666 | 0 | 666 | 666 | 666 | 666 | 666 |
| 1400 | 973 / 101 | 951 / 100 | 2020-07-25–2026-09-04 | 951 | 0 | 951 | 951 | 951 | 951 | 951 |
| 1610 | 105 / 11 | 84 / 9 | 2025-09-13–2026-09-19 | 84 | 84 | 84 | 84 | 84 | 84 | 84 |

The machine-readable [distance counts](distance_counts.csv) and [time coverage table](time_coverage.csv) include positive finish-time and `valid_time` counts, percentages, and races with at least one selected positive value. [Status counts](time_status_counts.csv) expose each time-view status: three scoped field values are website-corrected (1110m S1F, 1200m S1F, and 1300m G1F); one 1200m G1F remains `unresolved_official_website_anomaly` and has no selected usable value. The correction/hold handling follows the current time view.

## Measured checkpoints and non-overlapping profiles

The KRA Jeju definitions give S1F as 200m except at 1110m and 1610m, where it is **210m**; G3F is the final 600m duration and G1F the final 200m duration. The Jeju glossary describes 1C, 2C, 3C, and 4C at approximately 1400m, 1200m, 600m, and 400m remaining, respectively. Corner locations therefore remain approximate. G3F and G1F crossing times below are computed as `finish_time − duration`; they are derived boundaries, not API6 leader times. The official S1F exception is documented in the [2026-10-18 source review](../20261018_s1f_measurement_official_review/README.md); the prior study links the [KRA Jeju glossary](https://race.kra.co.kr/raceScore/scoretableLayerExplanation.do?meet=2) and [official Jeju race-view guide](https://race.kra.co.kr/down/pdf/raceView_jeju.pdf).

| Distance | Proposed non-overlapping boundary sequence | Segments | Observed duplicate or ordering result |
|---:|---|---:|---|
| 400 legacy | Start → S1F (= `T−G1F`, 200m) → finish (400m) | 2 | S1F equals the G1F-start crossing in all 1,257 shared rows. 1C–4C and G3F have no positive values. Keep this legacy profile separate. |
| 800 | Start → S1F (= 3C = `T−G3F`, 200m) → 4C (~400m) → `T−G1F` (600m) → finish | 4 | S1F=3C in 13,803/13,803 shared rows; 3C=`T−G3F` in 13,799/13,799. Do not create a zero-length interval between aliases. |
| 900 | Start → S1F (200m) → 3C = `T−G3F` (~300m) → 4C (~500m) → `T−G1F` (700m) → finish | 5 | 3C=`T−G3F` in 9,715/9,715 shared rows. |
| 1000 | Start → S1F (200m) → 3C = `T−G3F` (~400m) → 4C (~600m) → `T−G1F` (800m) → finish | 5 | 3C=`T−G3F` in 15,502/15,502 shared rows. This is the existing five-interval layout. |
| 1110 | Start → S1F (**210m**) → 3C = `T−G3F` (~510m) → 4C (~710m) → `T−G1F` (910m) → finish | 5 | 3C=`T−G3F` in 10,700/10,700 shared rows. Do not rescale S1F to 200m. |
| 1200 | Start → S1F (200m) → 3C = `T−G3F` (~600m) → 4C (~800m) → `T−G1F` (1000m) → finish | 5 | 3C=`T−G3F` in 5,176/5,176 shared rows. One G1F value remains held by the website review. |
| 1300 | Start → 2C (~100m) → S1F (200m) → 3C = `T−G3F` (~700m) → 4C (~900m) → `T−G1F` (1100m) → finish | 6 | 2C precedes S1F in all 666/666 rows (median `2C−S1F` −8.3s; range −9.7 to −7.1s); 3C=`T−G3F` in 666/666. |
| 1400 | Start → S1F (= 2C; 200m nominal) → 3C = `T−G3F` (~800m) → 4C (~1000m) → `T−G1F` (1200m) → finish | 5 | S1F=2C in 951/951 rows; 3C=`T−G3F` in 951/951. Retain both source labels on the same measured value. |
| 1610 | Start → S1F (= 1C; **210m nominal**) → 2C (~410m) → 3C = `T−G3F` (~1010m) → 4C (~1210m) → `T−G1F` (1410m) → finish | 6 | S1F=1C and 3C=`T−G3F` in all 84/84 shared rows. Only 9 started races; treat this profile as small support. |

In every distance from 800m through 1610m, the row-level check found `3C = finish_time − G3F` wherever 3C, G3F, and a positive valid finish endpoint were all present: **56,593 of 56,593** shared rows across those distances. The largest floating-point residual was 1.42×10⁻¹⁴ seconds; the displayed source precision is 0.1 seconds. This is one boundary with two provenance routes, not evidence for an extra short segment or a 10m difference. C3/G3F support and residual details are in [the consistency table](c3_g3f_crossing_consistency.csv).

For the profiles above, every available adjacent endpoint pair was in the proposed order, including intentional equal-time aliases. Rows with every proposed endpoint available were monotone in all cases: 13,799/13,799 at 800m, 9,715/9,715 at 900m, 15,502/15,502 at 1000m, 10,700/10,700 at 1110m, 5,175/5,175 at 1200m, 666/666 at 1300m, 951/951 at 1400m, and 84/84 at 1610m. These are descriptive arithmetic checks only. See [all endpoint pair comparisons](endpoint_relations.csv) and [chronology summary](chronology_summary.csv).

The current quality-selected per-horse time contract exposes S1F, 1C–4C, G3F, and G1F; it exposes **no G2F duration**. API6 leader furlong times are not horse-level API4 values and were not used. No intermediate 200m checkpoints or unverified distances were interpolated, and no speed-per-distance conversion was made.

## Recommendation and limits

For 1000m, the already-tested proposal used the five measured intervals shown above and failed its pre-set maintenance gate. The saved `F1_STYLE6` baseline remains in place: the candidate's 2024–2026 Top3 log loss was 0.564610 versus 0.563635, Brier was 0.190717 versus 0.190325, and the six-combination hit count was 111 versus 116 of 508 races. See the [original source audit](../20261017_1000m_five_section_source_audit_v1/README.md) and [ablation result](../20261017_1000m_five_section_ablation_v1/README.md). This report does not retest that candidate or infer that the time fields have no research value.

The measurement-layout result suggests no finer general 200m segmentation for 1000m: the current per-horse measurements yield five non-overlapping pieces, and the next official-looking boundary at C3 is numerically the G3F start. The distinct 2C-before-S1F boundary at 1300m and the 2C boundary after S1F at 1610m offer additional resolution; at 1610m, 1C duplicates S1F and adds no segment. The 1610m profile has only 9 races, and both proposed refinements require the regular point-quality and as-of availability gates before any feature reuse. A suitable next research step would define distance-specific profiles and test their measured checkpoint-derived intervals against the preserved baseline under the project’s pre-registered evaluation rules. No model or operating change is proposed here.

The source audit covers the existing roster through 2026-09-19; API and website timestamps do not prove that the selected values were available at the historical prediction time. The full race-point conflict mask was deliberately not rebuilt in this descriptive layout pass. Any future model comparison must apply the current quality and point-mask contracts, keep each horse's historical source time separate from its target-race outcome, and use the established time-ordered evaluation gates.
