# Expanded pair OOS review

Independent, read-only verification of `20261011_pair_top3_oos_expansion_v1`.
The verifier replays the four saved historical score models, checks the saved
H1/H2 moments and objective gradients, reconstructs all evaluation pair
probabilities and selections, and recomputes reported metrics with the original
date-bootstrap schedule. It does not train models, run optimizers, or create a
bootstrap schedule.

Results: 427/1,779 expanded direct hits, 426/1,779 prior direct hits, and
429/1,779 raw F1_STYLE6 Top2 hits. Expanded minus raw is −0.1124 percentage
points (95% date-bootstrap CI −0.3407 to +0.0569 pp), so the existing primary
gate remains failed. Expanded minus prior direct is +0.0562 pp (CI −0.2804 to
+0.3909 pp). All reconstructed report values and the final study manifest
passed independent checks; details and hashes are in
`INDEPENDENT_REVIEW_RECEIPT.json`.
