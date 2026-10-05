# Early official closure-source audit: 2010–2013

Audit scope: official KRA evidence for planned holiday, summer, and year-end closures and dated amendments affecting Seoul (`meet_code=1`) and Busan-Gyeongnam (`meet_code=3`) in 2010–2013. Checked 2026-10-01. The directory contains source-status records and review evidence only; it does not modify the v1 closure inventory or core data.

## Findings

No planned closure interval for 2010–2013 was established from the official materials captured in this audit. [`closures_supplement.csv`](closures_supplement.csv) is therefore header-only. No dates were inferred from long gaps or other no-event patterns.

The KRA yearbook archive currently lists 2012 and 2013 on page 2 (page 1 lists 2015–2024; page 2 also lists 2014). The official 2013 yearbook PDF was captured in full (304 pages). It reports actual race nonexecution and make-up events, summarized with page citations in [`actual_nonexecution_evidence.csv`](actual_nonexecution_evidence.csv). This is execution evidence, not a planned holiday calendar:

- Seoul: partial-day cancellations on 2010-08-21, 2011-01-23, and 2011-07-03; full-day cancellation on 2012-06-30. The 2012-06-30 row corroborates an already-adjudicated `official_day_cancelled` event in the canonical data and is not a new planned closure interval.
- Busan-Gyeongnam: a 2010-03-14 nonexecution entry reports six make-up races; a 2012-12-07 entry reports one make-up race held on 2012-12-14. The yearbook does not state the original affected-race scope for those two events.
- The yearbook reports zero 2013 nonexecution events for both Seoul and Busan-Gyeongnam.

The 2013 yearbook’s Seoul table is at printed p.18 (PDF physical p.60); the Busan-Gyeongnam table is at printed p.67 (PDF physical p.109). Full-page rendered excerpts are preserved at [`raw/pages/2013_masa_01_physical_p60.png`](raw/pages/2013_masa_01_physical_p60.png) and [`raw/pages/2013_masa_01_physical_p109.png`](raw/pages/2013_masa_01_physical_p109.png). The PDF and images have hashes in [`capture_manifest.csv`](capture_manifest.csv) and [`raw/capture_manifest.json`](raw/capture_manifest.json).

Three 2012 yearbook attachments (`2012_masa_02_1.pdf`, `_02_2.pdf`, `_02_3.pdf`) were captured and text-inspected. They contain venue/facility descriptions and layouts, not racing schedules. They are only a subset of the attachments listed on the official 2012 yearbook record; the remaining listed parts were not captured here. National Archives metadata confirms records for KRA-produced 2011 and 2012 yearbooks (268 pages reported), but those metadata records do not expose the yearbook content.

The guessed candidate annual-plan URLs `https://race.kra.co.kr/down/raceplan_YYYY.pdf` for 2010–2013 returned HTTP 200 with 295-byte non-PDF bodies (same SHA-256 `d832d79866aff4d0bb8a7aef305f437f8264c2118b5ec3ff788c920e2b22046d`). The parent audit holds the raw responses and access manifest at [`../20261001_calendar_core_review_v2/raw_plan_access/access_manifest.json`](../20261001_calendar_core_review_v2/raw_plan_access/access_manifest.json). This only rules out those tested filename responses as usable PDFs; it does not prove that no official plan exists elsewhere. In the broader 2010–2015 candidate check, the same tested alias failed for 2014 and 2015 as well. Planned schedule coverage for 2010–2015 remains incomplete until valid annual-plan documents or dated official amendment notices are obtained.

The targeted official-domain notice searches did not locate dated 2010–2013 planned-closure amendments. This is a search-status result, not proof that no such notices exist. The current KRA race-operation page displays a 2026 schedule and is not a historical archive.

## Review files

- [`source_status.csv`](source_status.csv): year-by-year plan, yearbook, metadata, and notice source inventory.
- [`capture_manifest.csv`](capture_manifest.csv): official response paths, URLs, page/record references, hashes, byte counts, and capture status.
- [`gap_candidate_checks.csv`](gap_candidate_checks.csv): 32 calendar-gap candidates from 2010–2013 (8 per year; 16 per meet). All remain unadjudicated as planned closures; gaps are not closure evidence.
- [`actual_nonexecution_evidence.csv`](actual_nonexecution_evidence.csv): actual race-cancellation and make-up evidence, kept separate from planned closure intervals.
- [`closures_supplement.csv`](closures_supplement.csv): merge-compatible planned closure schema; no evidence-backed rows found.

## Official records

- [KRA yearbook archive](https://www.kra.co.kr/board/op/skr0325.do?menuId=skr03_skr032_skr0325)
- [2012 yearbook record](https://www.kra.co.kr/board/view/op/pu/11/1186041_1175.do?menuId=skr03_skr032_skr0325)
- [2013 yearbook record](https://www.kra.co.kr/board/view/op/pu/11/1186474_1175.do?menuId=skr03_skr032_skr0325)
- [National Archives record for 2011 yearbook](https://archives.go.kr/next/newsearch/showDetailPopup.do?rc_code=1310377&rc_rfile_no=201103734823&rc_ritem_no=000000000001)
- [National Archives record for 2012 yearbook](https://archives.go.kr/next/newsearch/showDetailPopup.do?rc_code=1310377&rc_rfile_no=201305761322&rc_ritem_no=000000000001&sitePage=0-0-0)
