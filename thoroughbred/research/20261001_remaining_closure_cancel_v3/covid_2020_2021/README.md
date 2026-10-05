# Remaining 2020-2021 closure and cancellation evidence (v3 supplement)

## Scope and result

This package covers Seoul (meet 1) and Busan-Gyeongnam (meet 3), with focus on the 2020 COVID interruption after August and 2021 Q1, Q2 and Q4. Yeongcheon and Jeju are outside this narrow supplement. It does not modify the v1/v2 inventories or the core database.

`closure_additions.csv` contains two date-bounded rows for 2020-09-01 through 2020-10-15, one for each meet. The start is stated in a National Assembly Budget Office report table sourced to KRA: “경마 중단 조치 (9.1~현재)”. The report was issued during 2020 and its word “현재” has no explicit end date. The end boundary is therefore reconciled from the official KRA API-derived calendar: both meets have zero scheduled and executed races for all 45 days 2020-09-01..10-15, and the first recorded actual racing day after the start is 2020-10-16 (15 Seoul races; 10 Busan races). The last pre-gap execution is 2020-08-30. This is an evidence-bounded interval, not a KRA notice naming 2020-10-15 as the closure end.

The KRA revised 2020 plan (already preserved in v2) covers the separate 2020-02-23..06-18 suspension. Its notes about reduced night racing due to restricted customer admission are not treated as racing stoppage. The local NABO report capture and rendered physical page 56 (printed p.48) are included under `raw/`.

## 2021 result and unresolved leads

The full KRA 2021 annual plan was not recovered. The expected official URL `raceplan_2021.pdf` returned HTTP 200 with a 295-byte HTML response, preserved under `raw/`; targeted KRA search did not surface an alternate full plan. This only establishes that this URL did not deliver a PDF.

- Q1: the KRA-derived calendar shows a gap from 2021-02-05 to 2021-02-21 for Seoul and 2021-02-05 to 2021-02-20 for Busan. It overlaps Lunar New Year, but no official dated source was found to label those dates as planned closures. No interval is added.
- Q2: the canonical long-execution-gap ledger has no 7-day-or-longer execution gap for either meet. This is not proof that no planned closure/weekday was present; no new interval is added without the annual plan or a notice.
- Q3: the four already verified KRA-authored Q3 intervals remain in v2 and are not duplicated here. The HWP source was mirrored by BROA; the hosting distinction is preserved in the v2 inventory.
- Q4: the last 2021 executions are Dec. 26; the existing v1 inventory already documents Dec. 30, 2021–Jan. 2, 2022 for both meets from the official 2022 plan. The broader execution gap is not extended into additional closures.

No 2021 Q1/Q2/Q4 interval was added. Normal no-race weekdays and calendar gaps alone are not closure evidence. Partial-day cancellations are outside this supplement unless they change the full-day boundary assessment.

## Files

- `closure_additions.csv`: two rows in the existing eight-column closure schema.
- `boundary_reconciliation.csv`: 45-day zero-plan/zero-execution window and first post-start race-day counts by meet.
- `calendar_boundary_evidence.csv`: neighboring and in-window KRA-derived calendar rows.
- `2021_gap_assessment.csv`: unresolved Q1 gaps, Q2 continuity check, and inherited Q4 interval.
- `decision_provenance_ledger.csv`: decision evidence, exact statements, interpretation, and limits.
- `sources_inventory.csv`: source URLs, locators, source/host distinction, local paths and hashes.
- `raw/`: NABO source report/page rendering and non-PDF response from the official KRA 2021 annual-plan URL. The KRA 2020 and 2022 plan PDFs and Q3 HWP are reused by reference from v2 to avoid altering or duplicating prior evidence.
- `manifest.json`: file byte lengths and SHA-256 hashes; it excludes itself.
