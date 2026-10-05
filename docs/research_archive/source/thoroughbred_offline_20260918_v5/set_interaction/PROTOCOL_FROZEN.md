# Frozen protocol: one conditional podium-set interaction correction

Frozen before any v5 metrics were computed or inspected. The immutable comparator is
v4 `top3_growth_strength`, on the identical v4 full-card race coverage. Only target B
(the unordered podium set) is selectable. Target C is formed coherently by the frozen
v2 win-score Plackett--Luce distribution conditional on B; A is the exact B marginal.

For each evaluation year 2021--2026, the frozen v4 FIT model supplies the per-horse
Top-3 raw score and the frozen v2 model supplies the win raw score. A four-feature
set correction is fitted only on the preceding year's Q3 TUNE races, with the v4
sum of three raw Top-3 scores as an offset. The features are fixed card-relative
quantities and require no learned transform:

1. mean pairwise absolute percentile-rank gap in pre-race global ELO;
2. mean pairwise absolute percentile-rank gap in corrected strict-prior average-three speed;
3. number of front-runner pairs, where a runner has strict-prior early-position percentile
   at or below 0.25; this feature is zero outside Seoul because verified section pace is
   unavailable at Busan;
4. the selected set's weakest v4 raw score minus the strongest omitted score, divided
   by within-card raw-score standard deviation and clipped to [-4, 4].

The fourth feature directly targets the missed-third-horse boundary; the first three
test whether a podium is too homogeneous in ability, speed, or front-running style.
No outcome, current/late, or unverified feature is used. Missing ELO/speed ranks receive
the neutral card percentile 0.5; missing pace never implies front-runner status.

Fit one joint multinomial set likelihood with exact normalization over every triple.
Boundary ties use the likelihood of the compatible-set union and its exact conditional
gradient. L2 is fixed at 4.0 and all four coefficients are bounded to [-1, 1]. Q4 CAL
fits one positive temperature globally and by venue when the same v3 minimum-support
rule permits; otherwise the global value is used. No transform is learned from EVAL.

Selection uses 2021--2024 only. A correction qualifies when pooled B hit rate is at
least baseline with one strict hit improvement, pooled B log loss is no worse, and for
each of Seoul and Busan both hit and loss are non-worse in at least three of four years.
If no correction qualifies, v4 remains selected. Years 2025--2026 are descriptive only.

