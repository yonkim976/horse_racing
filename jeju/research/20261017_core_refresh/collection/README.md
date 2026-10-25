# Official source collection

The frozen initial backfill collected Jeju (`meet=2`) official raw pages for 2026-09-13 through 2026-10-16. The source manifest is the authoritative page-level inventory and records checksums, pagination, request parameters without credentials, and partition status.

For API4 race results (`race_result`), the requested date range contains **9 positive race-date partitions** and **25 successful zero-row/no-race partitions** (34/34 fully paginated). The zero-row partitions are successful empty responses, not collection failures. API6 (`section_records`) and API303 (`corner_rank`) were freshly checked for all 9 positive race dates.

This collection contains raw Jeju responses; runner cohort filtering belongs in the loader. No production database was written.

## Scheduled collection windows

Scheduled runs choose their end date from the current Asia/Seoul calendar date: the runner uses yesterday before 21:00 KST and today from 21:00 KST onward. `collect_range` and the optional website probe reject any requested date after today in KST. The collector has no fixed 2026-10-16 cutoff, so future scheduled runs can include newly available results. The CLI's default dates remain the explicit initial backfill range; the scheduled runner passes its calculated window.

In future manifests, `target_date_results_queried: false` means the requested end date was not in the future when collection began. It does not exclude a fixed prediction target date. The requested date range remains the loader's scope, including when monthly or annual API pages carry extra rows outside that range.
