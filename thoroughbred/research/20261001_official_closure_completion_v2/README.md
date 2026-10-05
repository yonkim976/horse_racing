# Official closure completion v2

## Scope and additions

Cutoff: 2026-09-29. Venues: Seoul meet 1, Busan-Gyeongnam meet 3, Yeongcheon meet 4; Jeju excluded. `closure_additions.csv` contains 22 reviewed planned intervals (18 from the 2016–2017 KRA annual plans and 4 from the KRA-authored 2021 Q3 plan), totaling 61 venue-days. Added to the inherited base of 53 intervals, the resulting inventory has 75 intervals / 450 venue-days.

The 2016 annual-plan summer cells explicitly say 휴장(예비), reflected as `summer_rotation_reserve`. The 2021 HWP table maps its venue columns as Seoul, Busan, Jeju: Seoul is closed 2021-07-30..08-01; Busan is closed 2021-08-06..08-08; both are closed 2021-09-24..09-26. The same 2021 table explicitly says Busan races on July 30–August 1, so that is not a Busan closure. A cell-index/record-index transcription is preserved in `extracted/2021_q3_closure_table_cells.csv`; `tools/hwp5_text_extract.py` reproduces the paragraph record extraction. Parent calendar checks found zero actual executions inside the 22 added intervals.

The 2021 document is KRA-authored but was republished on the Busan Owners Association site; its mirror provenance is explicit in `sources_inventory.csv`. The associated KRA-authored Q3 adjustment HWP was reviewed and did not supply a replacement closure-date interval.

## Actual event evidence and limitations

Planned intervals and actual event cancellations are separate. `actual_nonexecution_evidence.csv` records historical yearbook entries and their limits. `actual_interruption_source_summary.csv` contains paraphrase-only (not verbatim) summaries of dated 2020 yearbook events with physical/printed page numbers and the source PDF hash. The revised 2020 KRA plan already included in v1 states racing was suspended from 2020-02-23 through 2020-06-18. A 2020-08-30 to 2020-10-16 calendar gap does not establish a closure interval: no official Sept 1 racing-stop notice was verified, and customer-admission restrictions are not treated as race stoppages.

This supplement is not a complete official closure calendar for each year. No 2010–2015 annual plan was located. KRA archive records for 2012 and 2013 were found but their attachments are absent here; 2010 and 2011 yearbook entries are not listed in the archive. The full 2021 annual plan was not validated; its Q3 schedule and the already-inherited 2021 year-end interval do not fill the full year. See `year_coverage_inventory.csv` for year-specific gaps. No interval is inferred from normal no-race weekdays or calendar gaps. The 2022 PDF's stray 2021 running header is treated as template carryover, not as a 2021 schedule.

Existing 2018–2020 and 2022–2026 intervals remain in the previous closure inventory; three 2026-09-25..27 venue entries remain in the prior calendar API addendum. KRA's 2023-08-03 notice confirms all business sites were closed Aug 4 while Seoul racing proceeded Aug 5–6; it supports the existing date interpretation and adds no interval.

## Package files

- `closure_additions.csv`: new planned intervals in the existing 8-column schema.
- `sources_inventory.csv`: URLs, source/page locators, local raw files, SHA-256, and acquisition status.
- `year_coverage_inventory.csv`: year-by-year coverage and gaps.
- `actual_nonexecution_evidence.csv` and `actual_interruption_source_summary.csv`: actual event evidence, kept separate from planned closure intervals.
- `raw/`: preserved KRA documents and KRA-authored HWP copies with mirror provenance.
- `tools/` and `extracted/`: reproducible 2021 HWP text extraction and exact closure-table cell audit.
- `manifest.json`: byte length and SHA-256 for each package file, except the manifest itself.

Page citations use PDF physical and printed page numbers when available. HWP page numbering is not stable, so its exact table heading and record indexes are cited. File hashes identify local bytes; a hash does not make the hosting site an official KRA domain.
