# Remaining closure source audit: 2010–2015

Scope: alternative official-source leads for planned holiday, summer, and year-end closures and dated amendments for Seoul (`meet_code=1`) and Busan-Gyeongnam (`meet_code=3`). Checked 2026-10-01. No database, builder, or earlier evidence package was changed.

## Result

No new interval met the official-source evidence threshold. [`closure_candidates.csv`](closure_candidates.csv) uses the inherited eight-column schema and is header-only. Secondary reports do provide exact-date leads, kept separately in [`reported_interval_leads.csv`](reported_interval_leads.csv) with `confidence=reported_not_official_original`; none is promoted to an official confirmed closure.

The strongest secondary lead is a 2012 KRJ report that attributes its annual schedule to KRA and gives date ranges by venue. The same article says the 2012 annual plan was not applied (at least for Seoul). The API-derived daily calendar cross-check also shows races inside the reported Seoul year-end window, Busan summer window, and Busan year-end window (25, 16, and 20 executed races, respectively). The other five 2012 reported windows show zero executions in the API calendar. These API counts describe execution only and do not validate schedule intent.

Two 2015 Busan monthly-plan reports give exact closure dates: July 24–26 (summer cross-rotation) and September 25–27 (Chuseok). Both date ranges have zero executed races in the API calendar, but the original KRA monthly schedules were not recovered. They remain reported leads.

## Alternate-source checks

- The official KRA monthly-plan board, [boardNo 73](https://board.kra.co.kr/board/viewBoard.do?boardNo=73), showed 15 recent entries with 2026 monthly-plan titles; no 2010–2015 entries were visible. The [current KRA overview](https://www.kra.co.kr/op/pu/07/oppu0701.do?menuId=skr03_skr032_skr0321) is 2026-only.
- Targeted KRA-domain searches found no historical annual/monthly plan original or dated 2010–2015 holiday-amendment notice. The broken `raceplan_YYYY.pdf` candidate responses are documented in the parent calendar review capture and were not retried.
- Targeted searches for a Seoul Owners Association archive and Korea.kr/MAFRA-hosted KRA plan announcement did not locate a dated original.
- Search indexing surfaced a 2025 KRA-plan mirror on the Busan Owners Association site, but opening its domain returned HTTP 403. Access stopped there. No historical archive was recovered. The later KRA-authored HWP mirror already captured in `20261001_official_closure_completion_v2` does not establish 2010–2015 dates.
- Direct downloads of secondary report pages failed at environment DNS resolution; no source-page bytes were captured. URLs, publisher dates, query outcomes, the KRA monthly-board web-reader observation, and fetch failures are preserved in `source_status.csv`, `raw/search_observations.json`, and `raw/reported_sources_fetch_manifest.json`. The web-reader text is not represented as original HTML bytes.

## Files

- `closure_candidates.csv`: inherited eight-field planned-closure schema; no official additions.
- `reported_interval_leads.csv`: exact secondary date leads and API execution cross-checks.
- `lead_confidence_provenance.csv`: confidence and provenance limits for each reported lead.
- `source_status.csv`: year-by-year source coverage and alternative-source outcomes.
- `raw/`: search observations and attempted-fetch status; no original historical KRA plan bytes were available in this pass.
- `manifest.json`: hashes and byte counts for this package.
