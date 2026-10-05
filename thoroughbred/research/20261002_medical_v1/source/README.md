# 진료 원천 수집·정규화

진료일 `2010-01-01`부터 `2026-09-29`까지 서울(meet 1)·영남(meet 3, 부산경남/영천 혼합) 대상이다. 원천 행은 반복·중복 관측을 포함해 그대로 보존한다. 운영 DB나 서비스에는 접근하거나 쓰지 않았다.

## 원천 관측량

| 원천 코호트 | 유효 관측 행 | 수집·검증 상태 | 범위 제외 |
| --- | ---: | --- | ---: |
| API16 연도별 현재 응답 (`current_annual`) | 243,411 | 2010–2026 × meet 1/3, 34개 요청, 42개 페이지. 페이지 수집 완료; 제공처의 과거 이력 완전성은 미확인 | 475 |
| 보존된 API16 일별 캡처 (`archived_daily_snapshot`) | 238,591 | 원본 2,524페이지 모두 응답 헤더·페이지·경로·해시 검증. 일별 스냅샷이며 연도 전체 커버리지로 해석하지 않음 | 8,775 |
| 공식 dacom72 Text (`rpt`) | 1,619,071 | 3,377개 파일의 고정 CP949 바이트 레이아웃을 사용; 날짜형 후보 중 32행 격리 | 32 |
| **합계** | **2,101,073** |  | **9,282** |

API16 연도별 조회에서 정상 응답이면서 0건인 요청 17개도 `api16_year_meet_coverage.parquet`와 페이지 원문에 남긴다. 0건 응답은 해당 과거 연도의 완전한 진료 부재를 증명하지 않는다. 두 API 코호트는 별도로 유지한다.

Text 파일은 주간 기록이 반복될 수 있어 발생 행을 합치거나 삭제하지 않는다. `medical_fingerprint_candidates.parquet`는 1,904,555개의 정확한 필드 조합별 집계이고 실제 방문 건수가 아니다. `medical_api_comparison_ledger.parquet`는 1,825,169개 비교 행으로, API 진단 슬롯과 Text의 단일 진단 문자열을 비교할 뿐 원천을 대체하거나 자동 연결하지 않는다.

## 원문 필드와 provenance

- API16의 `illName1`, `illName2`, 공식 마번, 소속조, 병원은 원문 문자열 그대로 보존한다. 각 행은 원문 페이지 경로·SHA-256·캡처 ID·페이지/행 번호·원문 JSON으로 추적한다.
- dacom72는 CP949 바이트 위치로 파싱한다: 날짜 `0:10`, 마명 `11:29`, 소속조 `29:31`, 병원 `32:44`, 진단 문자열 `45:end`. 구분자 위치는 `10`, `31`, `44` 바이트다. 숫자 칸은 조 번호이며 진단 슬롯으로 해석하지 않는다. 쉼표를 기준으로 진단을 임의 분할하지 않는다.
- dacom72 원문 행, 파일 기준일, 본문 진료일, 파일 SHA-256과 행 번호를 함께 보존한다. 본문 진료일과 파일 기준일이 달라도 행을 버리지 않는다. Text 원문에는 공식 마번이 없으므로 `hr_no_raw`는 NULL이며, 마명만으로 API 마번을 연결하지 않는다. 빈 마명 두 행도 보존한다.
- dacom72 캡처 시각은 `_manifests/dacom72/manifest.jsonl`의 `retrieved_at_ms`를 정확한 파일 경로와 전체 SHA-256으로 연결해 채웠다. 대상 3,377개 모두 정확히 하나의 다운로드 항목과 일치한다. manifest SHA-256은 `080b3e2bb268d26e833f0b2728248e892480ddbb2811d23b4f18b650f3984e86`이다. 캡처 시각은 과거 진료의 공개 시각을 뜻하지 않는다. manifest의 원본 URL은 산출물에 복사하지 않았다.
- `source_row_hash`는 `source_kind`, `source_path`, API 페이지·행 또는 Text 행 번호로 만든 행 위치 식별자다. 내용 동일성이 아니라 원문 위치를 가리킨다.

## 검증 및 파일

독립 원문 검증 `../root_input_verify.py`를 최신 관측 파일에 실행해 통과했다. API 원문 1,654개 파일, dacom72 원문 3,377개 파일, 전체 2,101,073개 관측 행을 검증했다. 개별 산출물 SHA-256·행 수는 `source_output_hashes.csv`; 원천별 수집 시각, 페이지·파일 ledger 및 커버리지 해석은 `source_capture_manifest.json`, `coverage_manifest.json`, 각 원천 capture manifest에 기록한다.

- 관측: `api16_current_annual_observations.parquet`, `api16_archived_daily_observations.parquet`, `dacom72_observations.parquet`
- 대조·집계: `medical_fingerprint_candidates.parquet`, `medical_api_comparison_ledger.parquet`
- 커버리지·검증: `source_year_meet_coverage.parquet`, `source_exclusions.parquet`, `dacom72_file_ledger.parquet`, `api16_page_ledger.parquet`, `api16_archived_page_ledger.parquet`
- 파이프라인: `collect_api16_annual.py`, `normalize_local_sources.py`, `derive_comparison.py`, `source_common.py`
