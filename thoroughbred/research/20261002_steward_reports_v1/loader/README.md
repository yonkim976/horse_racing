# Steward report and sanction research loader

This package appends API215 steward-report occurrences, API180_1 sanction occurrences, and reviewed horse-paragraph evidence to the research core. The loader defaults to a read-only dry run. It must not be used against an operational database or service; only the root operator may run its gated `--apply` mode after reviewing the report and paired backup.

## Preservation and interpretation

- Preserve every source item occurrence, raw JSON payload, field-presence/type record, source page/file hash, capture timestamp, and source locator. Keep report rows, sanction rows, and page requests as separate source evidence.
- Keep API215 as race-level narrative unless an exact program-number/name anchor resolves against that event's official runner roster. Save paragraph, sentence, and mention spans as neutral evidence. Links say that a horse was mentioned; they do not say the horse caused an incident or was at fault.
- Preserve all unresolved and ambiguous mention candidates. A report with no linked horse mention is not equivalent to a report with no paragraph or a source response that returned no report row.
- Treat API180_1 `gubun` as the target class and preserve `prNo`, `prName`, `chulNo`, `kind`, `reason`, `fine`, `stDate`, `spDate`, and `etlTime` exactly. Link a sanction target only when its official ID and race entry are verified against the same event's roster. Do not infer IDs from names or code suffixes, and do not link horses described as affected in `reason` as the sanction target.
- Preserve all day-wide API215 `addJudgement` source occurrences. Exact duplicate supplemental paragraphs may be grouped in `horse_steward_history` only when parent venue/date, explicit target venue/date/race, official horse ID/program number, field, and full text all agree; the raw source-linked passage view retains every occurrence locator in the grouped history row.
- Keep duplicate natural-key observations and distinct dispositions. A repeated meet/date/race/target/kind key is not proof that two records are the same sanction.
- Separate race/event date, sanction effective dates, API ETL text, request time, and source capture time. Historical publication time stays unknown unless a source explicitly proves it.
- A successful zero-row response is recorded as an empty source response; it never means that the event was clean or had no incident/sanction.
- Retain nonexecution report observations and link them to the event ledger when the exact race key exists. Do not drop them for lacking runner rows.

## Dry-run gates

The frozen input contract pins every source artifact by repository-relative path, SHA-256, byte size, and Parquet row count. Preflight checks the baseline core database and manifest, the official race/runner roster, report and sanction source-page completeness, source scope, exact source-row parity, paragraph/sentence/mention span integrity, approved horse-link evidence, independent sanction-entry parity, table/view name collisions, and append-only manifest behavior. It attaches the core read-only and does not modify it.
