# 2021 closure-gap follow-up v4

## Findings

The user-supplied 97-page KRA-authored 2021 plan (verified SHA-256; physical PDF p.13 / printed p.9) contains explicit venue closures for **2021-01-01..03 (New Year)** and **2021-02-12..14 (Lunar New Year)**. For the in-scope meets, these yield four compatible planned interval candidates: Seoul and Busan-Gyeongnam for each span. KRA-derived API calendar rows show zero scheduled and zero executed races on those candidate dates. The plan's other closure cells match existing v2 Q3 entries; they were not duplicated. The existing 2021-12-30..2022-01-02 interval remains in the prior inventory.

The plan's exact hosting URL was not supplied. Its PDF cover and metadata identify a KRA 2021 racing plan. A byte-identical copy is preserved under `raw/2021_racing_detailed_plan_user.pdf`; both the supplied PDF and local copy have the same verified SHA-256. The candidate CSV uses a `user-file:` URI to identify that exact source and does not assign a guessed KRA or BROA download URL.

## February 6-21 reconciliation

The supplied Q1 screenshot says the Q1 no-customer format ran from 2021-01-08 through 2021-03-28 on Fridays. The official KRA-derived calendar records Seoul and Busan Friday races through Feb 5; it then records Busan on Saturdays beginning Feb 20 and Seoul on Sundays beginning Feb 21. A targeted KRJ search-index excerpt for a secondary mirrored notice says limited customer admission in non-capital regions resumed from Feb 19 and shows Friday Jeju / Saturday Busan / Sunday Seoul. This is evidence about customer admission and racing format, not a suspension or cancellation notice. Direct retrieval of the KRJ page returned HTTP 200 with an application read-failure message, which is retained separately from the indexed excerpt. Bounded exact-phrase KRA searches did not find the original notice.

Accordingly, 2021-02-06..11 and 2021-02-15..19 remain ordinary no-race/nonmeeting days for Seoul and Busan; only Feb 12..14 is a dated holiday closure candidate. API execution on Busan Feb 20 (10 races) and Seoul Feb 21 (15 races) is preserved as a hard boundary check. The gap is not extended to Feb 20 or Feb 21.

## Remaining scope

Q2 has no >=7-day within-quarter execution gap in the canonical calendar, but that does not prove there were no weekday or single-day closures. Q4 adds no interval; only the existing cross-year New Year interval is retained. The 2021 Q3 summer and Chuseok rows remain sourced by v2 and are not duplicated. This is a bounded supplement, not proof of complete 2021 notice coverage.

## Files

- `interval_candidates.csv`: four planned intervals in the existing 8-column compatible schema.
- `candidate_calendar_validation.csv`: per-candidate schedule/execution and overlap checks.
- `2021_february_schedule_reconciliation.csv`: date-range classification for the Feb gap and actual weekend transition.
- `2021_segment_calendar_audit.csv`, `2021_long_gap_records.csv`, `feb_2021_calendar_window.csv`: quarter/gap calendar evidence.
- `sources_inventory.csv`, `evidence_provenance.csv`, `search_log.csv`: source origin, exact locators, hashes, attempts, and limits.
- `user_review_items.csv`: outstanding URL-provenance and original-notice source questions; no closure date decision is pending.
- `raw/`: byte-identical copy of the user-supplied annual plan, KRJ indexed excerpt transcript, and direct HTTP200 read-failure response. Q1 screenshots remain referenced by verified hashes from `../user_2021_plan/`.
- `manifest.json`: checksums for this folder's files; excludes itself.
