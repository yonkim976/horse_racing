# Older daily-training rider verification

This folder contains read-only verification for the older unclassified daily-training rider rows. The shared SQLite database remains writable only by the root coordinator.

## Initial 609-row gate

`verify_initial_609_preapply.py` is a lightweight gate for the preserved six-date sample. It checks that `sample_verification.json` records the independent standard-library HTMLParser PASS (6 official pages, 805 exact events, 609 explicit `관` rows, one ambiguous key excluded); confirms the preserved page manifests and their source SHA values; then compares all 609 evidence IDs with the proposed plan and current DB source and assignment rows. It validates each complete old/new assignment plus the plan's flat type, status, source-key, and website fields. It opens SQLite with URI `mode=ro`, enables `query_only`, and refuses to overwrite its report.

Run after the root coordinator has created the initial plan and provides its SHA-256:

```sh
.venv/bin/python jeju/research/20261017_older_training_rider_completion/verification/verify_initial_609_preapply.py \
  --plan jeju/research/20261017_older_training_rider_completion/initial609.plan.jsonl \
  --expected-plan-sha256 PLAN_SHA256
```

The result is written to `initial_609_preapply_verification.json`. The existing six sample HTML pages are not parsed again in this gate; their earlier independent parse result and source SHA provenance are checked.

## Full dated-page verification

`official_daily_detail.py` contains the independent BeautifulSoup reader for the full dated daily-detail pages. It validates Jeju request fields, the returned date and official role legend, the linked official horse ID on each row, minute-precision start/end times, and the page's interval and duration. `classify_label` only accepts an explicit role marker from the legend or an exact name in the SHA-verified API307 roster.

`verify_older_full_collection.py days --limit 50` checks the first 50 committed successful dates. `days --watch --poll-seconds 30` processes newly committed receipts until the collector freezes. The verifier makes one bounded-memory pass over the fixed snapshot to validate its SHA and build date offsets, then caches an immutable receipt for each independently verified date. Per-date checks compare the complete BeautifulSoup parse, exact horse-ID/date/start/end/duration match outcomes, candidates, and receipt SHA/counts. Missing timing, duplicate API or HTML keys, `외`, legacy markers without an explicit mapping, malformed or failed pages, and labels absent from both the official legend and roster remain unclassified. Raw pages are read one at a time.

After the full run is frozen and the root coordinator creates a complete plan, run `preapply --plan ... --expected-plan-sha256 ...`. This gate compares the frozen combined files and plan's complete old/new and flat assignment fields to the verified dates and fixed post-609 snapshot before any apply. After apply, `postapply --plan ... --expected-plan-sha256 ...` reads planned IDs in small parameterized batches with SQLite `mode=ro` and `query_only`, compares full assignments and `daily_training_rider_type_values`, and checks `website_jockey_name` is NULL for every non-jockey. It does not materialize the older analysis view.
