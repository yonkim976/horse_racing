# Busan freshness audit — 2026-09-17

This directory contains a read-only freshness check of
`../busan_complete_db_20260916/busan_complete.sqlite3`.

- `*_page_*.json`: newly fetched official KRA responses
- `freshness_report.json`: redacted request parameters, page counts, timestamps, hashes
- `verification.json`: exact comparison with the frozen database
- `manifest.json`: artifact hashes

The verdict is `partially_current_update_required`. The confirmed race history is
current through 2026-09-11. Training, starting-training and medical events have new
rows through 2026-09-16, and two prior running-trial judgements were revised.

See `docs/BUSAN_DATA_FRESHNESS_AUDIT_2026-09-17.md` for the Korean report.
