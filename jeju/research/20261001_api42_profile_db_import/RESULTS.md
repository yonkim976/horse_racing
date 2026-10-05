# API42 프로필 DB 적재 결과

적재 시각은 2026-10-01 07:34:42 UTC (16:34:42 KST)다. 조회시각을 프로필 관측시각으로 저장했으며 경주일 또는 과거 유효일로 소급하지 않았다.

| 항목 | 결과 |
|---|---:|
| 동결 대상 | 4,617두 |
| 경주 후보 | 4,006두 |
| API20 제주 보조 대상 | 611두 |
| 원문 출처 행 추가 | 4,617 |
| API 레코드 추가 | 4,617 |
| 프로필 관측 추가 | 4,617 |
| 조회시점 품종 근거 추가 | 4,617 |
| 최신 프로필 품종 분포 | 제주마 4,617 |
| 경주 후보 프로필 커버리지 | 4,006 / 4,006 |
| 보조 대상 프로필 커버리지 | 611 / 611 |
| API42 근거 중 과거 이벤트 날짜가 지정된 행 | 0 |
| SQLite integrity check | `ok` |
| 외래키 위반 | 0 |

원문 프로필 객체 218개 필드는 `api_records.payload_json`에 유지한다. 출처 역할은 `primary`이며, 원본 응답 파일 경로·바이트 수·SHA-256은 `source_artifacts`에 기록했다. 관측의 최소 정규화 필드는 공식 API 명세에서 확인한 `hrNm`, `birthDt`, `age`, `breed`, `sex`, `color`, `prdCty`다.

적재 전 SQLite 백업은 `jeju/research/20261001_api42_profile_db_import/backups/jeju_native_core_before_api42_20261001.sqlite3`에 SQLite backup API로 생성했다. 크기는 570,015,744바이트이고 SHA-256은 `392c05dceef4ab50c14ace448af59f152324b7e278fe627cb462d9908594b1b8`이다. 지휘 에이전트가 백업 파일을 직접 읽어 manifest와 일치함을 확인했다.

적재기를 두 번째 실행해 멱등성을 확인했다. 기존 4,617개 출처·API 레코드·관측·근거가 동결 입력과 모두 일치했고 추가 삽입 및 갱신은 0건이었다. 최초 적재 수량과 시각은 `first_import_manifest.json`에 보존했다.

입력 근거 해시:

- 대상 ID 파일 SHA-256: `b2f0737ee92f4b9d54f4b5d0ecb5cb45ff370e03b279d942b99cd81f90a0a117`
- 요청 원장 SHA-256: `007b5f426e15898c4ef61be75e3247091c158816d549a39a9fb2dfd5bc14a235`
- 총 API 요청 시도: 4,718회 (2026-09-30 3,000회, 2026-10-01 1,718회)
- 유효 프로필 조회일: 2026-09-30 2,900건, 2026-10-01 1,717건

독립 DB 검증도 통과했다. [db_profile_verification.json](../20261001_api42_collection_verification/db_profile_verification.json)은 4,617개 레코드의 원문 JSON 218필드 값·타입·해시, 말 ID, 조회시각, primary 출처와 외래키를 대조했다. [db_preservation_verification.json](../20261001_api42_collection_verification/db_preservation_verification.json)은 적재 전 기존 10개 테이블의 모든 행 fingerprint와 5개 view SQL이 보존됐음을 확인했다. [api20_summary_after_import.json](../20261001_api42_collection_verification/api20_summary_after_import.json)에서 API20 기존 요약도 적재 전과 동일하고 잘못된 다중 품종 충돌은 0건이다. 전체 검증 개요는 [독립 검증 README](../20261001_api42_collection_verification/README.md)에 있다.
