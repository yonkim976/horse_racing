# API42_1 Horse Profile Feasibility

## Finding

The official KRA horse-profile endpoint is callable by both pagination and horse number, but the unfiltered list returned by this account is not a complete catalog for the collected race candidates.

- Portal dataset: [15057985, 한국마사회 마필종합 상세정보](https://www.data.go.kr/data/15057985/openapi.do)
- Operation: `B551015/API42_1/totalHorseInfo_1`
- Portal description lists `pageNo`, `numOfRows`, `hr_name`, and `hr_no`; it does not publish a historical effective period for breed.
- Initial unfiltered response (`numOfRows=1000`): `totalCount=100`, 100 rows, one page. `breed` values: 더러브렛 69, 제주마 13, 소형마 13, 중형마 4, 대형마 1.
- Probe with `numOfRows=20000`: still `totalCount=100` and 100 rows. Page 2 returned 0 rows. This confirms the returned list is capped at 100 for this query/account; it does not establish that the catalog itself contains only 100 profiles.
- Direct `hr_no` lookup succeeded for one candidate present in the bulk page and one candidate absent from it: each returned one profile (`totalCount=1`).

## Candidate Coverage

The candidate set was derived from all 2002–2025 API4_3 raw result pages and the 2026 raw result page, without treating rank as breed truth:

- Candidate race-result rows: 92,414
- Unique candidate `hrNo`: 4,006; missing or malformed IDs: 0
- Initial bulk-page matches: 11/4,006 IDs (0.274%), covering 79/92,414 result rows (0.085%)
- The 11 matched current profiles report `breed=제주마`.
- The two direct-lookup probes also currently report `breed=제주마`; these are feasibility samples, not a coverage estimate.

These are present-day profile observations at each response's `retrieved_at_ms`. No profile breed is assigned retrospectively to a historical race date. A `rank` beginning with `제` remains a candidate heuristic and does not establish breed.

## Collection Plan and Limits

The observed endpoint behavior supports one direct profile request per `hr_no`; no multi-ID filter or complete bulk pagination path was verified. Full candidate profile coverage would therefore require up to 4,006 individual requests, stored independently from the core race-result load.

The portal currently advertises a 3,000-request daily development allowance. At that allowance, 4,006 IDs require at least two quota days, before retries or any other API use. The two direct sample response bodies were 3.7–3.8 KB each, suggesting roughly 15 MB of uncompressed response bodies for 4,006 profiles, but profile sizes can vary. A complete run should use bounded pacing, retry/backoff, a per-ID completion ledger, and immutable raw response files so it can resume safely after throttling or transient errors. The API currently exposes present profile state, not a verified breed history; a full profile run would improve current-ID coverage but cannot by itself resolve historical breed.

## Captures

All captures below retain raw response bytes and SHA-256 in their manifests; service keys are not recorded.

- Initial bulk: [`attempts/20260929T135818.827876Z/attempt_manifest.json`](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20260929_horse_breed_profile_api/attempts/20260929T135818.827876Z/attempt_manifest.json>)
- Page-size and direct-ID probes: [`attempts/20260929T140522.696450Z-probes/attempt_manifest.json`](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20260929_horse_breed_profile_api/attempts/20260929T140522.696450Z-probes/attempt_manifest.json>)

The probe manifest records four response hashes: `dbea72e2c211849b9611e4a772e7265417902c7a4164e77e642fc1ff3e221666` (bulk page 1), `2dda010e6abd3d52ae255529086fb6236b225c4ac60a8dea3613a58a16abd47e` (bulk page 2), `2836b95486d47f0db17f9b1a10f66b0b2a055be206660ec9b299c4a609f76eb9` (direct lookup sample 1), and `5de9460adc06a67e3dd228b9fd0679de92750115aba1f38cc98530523e05ebb5` (direct lookup sample 2).
