# Independent website rider completion verification

`verify_website_completion.py` is a standalone, read-only verifier. It does not import or call the website collector, the production classifier, or `apply_website_types.py`. It parses saved official HTML with BeautifulSoup and validates page SHA-256, byte length, official URL, hidden Jeju horse ID, the six-month notice, full rider legend, and per-page first/last visible training dates.

The pre-apply phase compares every successful page in the 913-horse collection manifest against the read-only source DB, requiring unique exact keys for horse ID, date, entry time, exit time, and duration. It independently reparses the original HTML behind the earlier 534-row and 587-row evidence sets, then merges any uniquely supported archival-only rows with the latest collection. Duplicate exact keys are excluded from the plan even when duplicate labels agree; missing or unresolved events remain unclassified. Explicit labels are interpreted only from the page legend; a bare name is a jockey only when it appears in the independently SHA-checked official API307 roster archive. The plan must equal the union of unique direct evidence from the new pages and the earlier HTML snapshots, after excluding ambiguous row IDs.

After the independent report passes, the loader requires its plan SHA to match `verification/preapply_verification.json`. Run the pre-apply command only after the root coordinator announces the finished collection and plan:

```sh
.venv/bin/python jeju/research/20261017_training_rider_website_completion/verification/verify_website_completion.py \
  --phase preapply \
  --db jeju/data/jeju_native_core.sqlite3 \
  --plan jeju/research/20261017_training_rider_website_completion/plan.jsonl \
  --collection-manifest jeju/research/20261017_training_rider_website_completion/collection/manifest.json \
  --output jeju/research/20261017_training_rider_website_completion/verification/preapply_verification.json
```

After application, the `postapply_views` phase compares candidate rows in `daily_training_rider_type_values` and candidate IDs present in `training_current` against the apply-time backup and plan. It also confirms the unchanged view definitions, validates the `daily_training_api_rows_analysis_2026` 2026-09-19 cutoff without materializing that older analysis view, checks the jockey-name NULL policy for planned rows, and confirms neither database changed during verification. A candidate may change fewer than seven fields when (for example) its jockey-name field remains NULL. The root coordinator records the full source-table and assignment-table comparison separately. This phase is read-only and does not apply the plan again:

```sh
.venv/bin/python jeju/research/20261017_training_rider_website_completion/verification/verify_website_completion.py \
  --phase postapply_views \
  --db jeju/data/jeju_native_core.sqlite3 \
  --baseline jeju/research/20261017_training_rider_website_completion/before_website_completion.sqlite3 \
  --plan jeju/research/20261017_training_rider_website_completion/plan.jsonl \
  --output jeju/research/20261017_training_rider_website_completion/verification/view_verification.json
```

Reports are written only below this directory and are never overwritten. The pre-apply command is intentionally pending until the collector and plan are ready.
