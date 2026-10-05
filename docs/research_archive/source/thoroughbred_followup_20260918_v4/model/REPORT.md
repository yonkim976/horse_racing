# Thoroughbred growth / opponent-strength follow-up

The predeclared `top3_growth_strength` candidate qualifies for B and C on the
2021--2024 development gate. It does not qualify for A because Busan A top-1 hit
rate was non-worse in only two of four years. The frozen selection is therefore:
**A = v3 `top3_allcore`; B/C = v4 `top3_growth_strength`**.

| Period | Target | Candidate loss | v3 loss | Candidate top-1 hits/races | v3 top-1 hits/races | Decision |
| --- | --- | --- | --- | --- | --- | --- |
| 2021--24 development | A | 0.504155 | 0.504899 | 4167/6666 (62.511%) | 4105/6666 (61.581%) | retain v3: Busan stability failed |
| 2021--24 development | B | 4.286377 | 4.293704 | 516/6681 (7.723%) | 502/6681 (7.514%) | select v4 |
| 2021--24 development | C | 6.019371 | 6.026693 | 126/6681 (1.886%) | 120/6681 (1.796%) | select v4 |
| 2025--26 exposed reference | A | 0.513158 | 0.513124 | 1912/3039 (62.915%) | 1894/3039 (62.323%) | descriptive only; A remains v3 |
| 2025--26 exposed reference | B | 4.254107 | 4.254642 | 235/3044 (7.720%) | 223/3044 (7.326%) | descriptive only |
| 2025--26 exposed reference | C | 5.981899 | 5.982439 | 54/3044 (1.774%) | 55/3044 (1.807%) | **one fewer hit; no reference hit improvement** |

The C deterioration on the exposed period is retained explicitly. It does not
trigger post-hoc reselection: the protocol forbids using 2025--2026 for selection,
and the small loss improvements are not evidence of a stable new advantage.
`selection_frozen_before_reference.json` contains every annual/venue stability
count, including the failed A Busan gate.

The six added variables are generated only from earlier dates and current-card
pre-race fields. Opponent ELO is leave-one-out; cumulative career form uses canonical
corrected prior finishes; histories update only after the entire date. The first
partial implementation failed this contract and is visibly preserved as
`invalid_attempt_01`; it was stopped before metrics inspection and is ineligible.

The selected 27-race September 19--20 output is under
`future_predictions_20260919_20`. Its A probabilities are bit-for-bit equal to v3
r2, while B/C use the selected v4 2026 bundle. The source card is frozen and its
timing remains unverified, so these are research-only probabilities rather than a
final-starter or betting product. Neither v3 r2 nor production was modified.

Verification reloads all six bundles, checks finite inference, frozen protocol
hashes, all evaluation years, probability outputs, exact A preservation, v4-only
B/C, and all 27 future races. Run the command in `USAGE.md`.
