# API42 프로필 로컬 DB 적재

2026-10-01 기준으로 동결된 제주마 API42 프로필 4,617건을 제주 전용 SQLite DB에 현재시점 관측으로 추가했다. 적재기는 원본 수집 파일과 요청 원장을 검증한 뒤 `source_artifacts`, `api_records`, `horse_profile_observations`, `breed_evidence`에 한 트랜잭션으로 기록한다.

프로필의 전체 API 응답 객체는 `api_records.payload_json`에 JSON으로 보존한다. 별도 정규화 필드는 공식 명세에 정의된 마명, 출생일, 연령, 품종, 성별, 모색, 생산국이다. `breed_evidence`는 `observed_event_date=NULL`, `timing_basis='profile_retrieval_time'`으로 기록하며 과거 경주·주행심사 행을 변경하지 않는다. API42 출처 역할은 `primary`다.

## 파일

- 적재 결과: [RESULTS.md](RESULTS.md)
- 최초 적재 수량과 시각: [first_import_manifest.json](first_import_manifest.json)
- 최신 실행 결과: [import_manifest.json](import_manifest.json)
- 재실행 멱등성 확인: [idempotency_check.json](idempotency_check.json)
- 적재 전 DB 백업: [jeju_native_core_before_api42_20261001.sqlite3](backups/jeju_native_core_before_api42_20261001.sqlite3)
- 스키마 변경: `jeju/data/schema/migrations/20261001_add_api42_horse_profiles.sql`
- 적재기: `jeju/scripts/import_api42_horse_profiles.py`

같은 적재기를 재실행하면 기존 API 원문, 관측, 근거가 동결 입력과 정확히 일치하는지 확인하고 추가 행을 쓰지 않는다. 입력이 부분 적재되었거나 기존 행이 다르면 실패한다.
