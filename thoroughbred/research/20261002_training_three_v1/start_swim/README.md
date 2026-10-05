# START and SWIM raw reconstruction

Scope: 2010-01-01 through 2026-09-29 inclusive, API meet 1 and 3. Jeju meet 2 is excluded. Raw venue labels are retained; meet 3 is not assigned to a physical venue.

The source is API22_1 monthly JSON plus verified API22_1 exact-date source documents and the fresh 2026-09 monthly response; API216 annual XML source documents. Capture selection is the latest hash-verified complete response covering each event date and meet, based on actual response retrieval time. Every date × meet has an explicit coverage row, so complete zero-row responses remain distinct from missing or incomplete captures.

The Parquets preserve every selected source row as an observation. API22_1 supplies no event ID/time, so repeated same-key rows retain their page/row locations and an anonymous storage ordinal that is not chronology. API216 raw cnt, horsepart, and trpart are not transformed; cnt's count-versus-바퀴 unit is unresolved. Core links use exact official horse ID matching only; unmatched IDs are in separate ledgers.

`source_captured_at` is stored as timezone-naive UTC. Source request/retrieval timestamps and their original KST/UTC basis are retained in sanitized inventory metadata. Raw payload JSON is canonical compact JSON of the source row. Exact and nonidentical natural-key repeats are flagged and kept.

This directory and loader/input contain research artifacts only. The script reads the operating SQLite in a query-only transaction and the core DuckDB in a read-only transaction; it does not call APIs or write to either database.
