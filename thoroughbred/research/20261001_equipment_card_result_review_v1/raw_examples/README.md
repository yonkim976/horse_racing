# Local API raw provenance

This bundle records the local source evidence for three equipment discrepancies. The operational SQLite database was opened with `mode=ro` and `PRAGMA query_only=ON`. The audit filtered `source_documents` by endpoint, operation, and JSON-extracted race date/meet, then selected only the document ID, local path, SHA-256, requested/retrieved times, HTTP status, and the extracted date/meet. It did not select or emit `source_url` or raw request parameters.

Before parsing each JSON file, the audit resolved its path and required it to stay under `data/raw/`, then verified that its SHA-256 matched `source_documents.sha256`. Times in the evidence file are Asia/Seoul (KST). Each matching original item is represented by only its identity and equipment/result fields.

## Findings

- **2026-09-18, meet 3, R4, no. 9 플라잉스카이 (`0053545`)**: all three API78 captures have `equipCrs=계란형큰,망사,승인편자,양털코,혀끈-`. All three API24 captures have `toolName=망사가면,양털코굴레,쿠션편자(Cushion)`. API156 has `pthrEquip` exactly equal to API78, with rank 2.
- **2026-09-20, meet 4, R3, no. 6 아처하트 (`0060852`)**: all three API78 captures have `equipCrs=망사+,반가지큰+,양털코,혀끈+,Triabit -`. All three API24 captures have `toolName=망사가면,반가지큰고리재갈,혀보정끈`. API156 has `pthrEquip` exactly equal to API78, with rank 3.
- **2026-09-18, meet 3, R9, no. 1 오늘이순간 (`0047505`)**: all three API78 captures have `equipCrs=망사,반가지큰,승인편자+,승인편자-`, preserving both same-category marks. All three API24 captures have `toolName=반가지큰고리재갈,망사가면,쿠션편자(Cushion)`. API156 has `pthrEquip` exactly equal to API78, with rank 6.

API78 identifies the first two target rows by date/meet/race/horse number/name; its saved item has no horse-ID field. API24 and API156 rows provide the matching KRA horse IDs. The raw field differences are therefore present before application parsing or relational-table updates. The repository parsers map API24 `toolName` into its equipment history field and API156 `pthrEquip` into the result entry equipment field.

The repeated snapshots retain the same value within each endpoint for each example. These records do not establish that API24's equipment list is the gear physically worn, or that API156's result field is an independent observation of physical gear. The finding is about distinct source fields and their capture times; the complete per-document hashes, paths, timestamps, and parsed rows are in [`source_document_audit.json`](source_document_audit.json).
