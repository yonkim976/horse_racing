# Independent blend and cleanup-overlay review

## Verdict

No material blend-result bug was found. The frozen outcome is conservative and reproducible: `top3_allcore` remains selected for A, B, and C. Independent aggregation of the six stored race-metric Parquets reproduces `summary.csv`, `annual_metrics.csv`, and every field of `selection_frozen.json` within floating-point tolerance. All endpoint metrics and exact protocol-comparable race-ID sets match the frozen v3 `top3_allcore` and `win72_pl` baselines.

The blend protocol was locked before evaluation. Its SHA-256 matches `protocol_lock.json`. File timestamps and the implementation order show `selection_frozen.json` was written after the 2024 output and before the 2025 and 2026 reference outputs. The independent selection calculation uses only 2021–2024, Seoul/Busan, excludes A boundary ties, and reproduces all qualification evidence. No candidate qualifies. The rule requires pooled loss and hit to be non-worse, a strict pooled gain, and both loss and hit to be non-worse in at least three of four years for each venue; this is not overly permissive.

## Metric, truth, and mixture contracts

`mix` forms a convex combination of the complete set, order, and inclusion distributions on identical support. Convexity therefore preserves normalization and the C→B→A marginal identities. The stored maximum errors are at most `1.78e-15`, safely below the `1e-12` invariant threshold. The unit test independently compares blend A/B/C log loss and Brier values to `target_metrics` across ordinary finishes, boundary ties, first-place ties, and missing finish values; it passed.

Truth treatment matches the frozen v3 contract. B and C score total probability assigned to every compatible set/order, while their Brier targets divide mass uniformly across compatible truths. A uses the fractional inclusion target and intentionally excludes boundary-tie races from selection and summaries. The baseline comparison scope is Seoul/Busan; v3's additional 2026 Yeongcheon records and A boundary-tie records are correctly outside the blend scope.

## Verification coverage observations

The blend run's internal parity check uses an inner merge and does not separately assert equality of the old and new race-ID sets. Its stored parity could therefore pass if a row existed on only one side. This did not affect the result: the independent audit asserts exact race-ID equality after applying the declared scope, and all 36 endpoint/target/year comparisons pass with maximum loss/Brier differences below `1e-12` and zero hit mismatches.

The shipped unit test exercises mixture math and metric parity but does not directly unit-test `select`, development-year isolation, protocol locking, output aggregation, or exact endpoint race coverage. These are test-coverage gaps rather than observed result errors; `audit_blend_outputs.py` covers them read-only against the stored run.

## Cleanup overlay semantics

The original v2 `integrity.py verify-manifest` is expected to fail while `features_v2_rows.csv` is absent, because that verifier knows only the frozen manifest and requires a physical file at the original path. It will pass again after using the restore helper to recreate the CSV. Alternatively, `verify_prior_manifests.py` provides overlay-aware effective verification without restoring the file: it accepts exactly the explicitly listed pruned CSV, streams its gzip replacement, and compares the decompressed bytes and SHA-256 with the original v2 manifest entry. It does not waive or redirect any other missing artifact.

The whole-manifest audit passed all 1,173 frozen entries: 158 v1, 303 v2, and 712 v3 artifacts. The only overlay resolution was `features_v2_rows.csv`, whose decompressed stream is 139,748,563 bytes with SHA-256 `37c89e88396187bed69a3c39e838c390cb166d7330ef48466ff741f7fe20b9a2`. Every other manifest artifact remains present and byte-identical.

## Reproduction

```sh
.venv/bin/python data/research/thoroughbred_followup_20260918_v4/review_blend/audit_blend_outputs.py
python3 data/research/thoroughbred_followup_20260918_v4/review_blend/verify_prior_manifests.py
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q \
  data/research/thoroughbred_followup_20260918_v4/blend/test_blend.py -p no:cacheprovider
```

Machine-readable results are in `blend_audit.json` and `prior_manifest_verification.json`.
