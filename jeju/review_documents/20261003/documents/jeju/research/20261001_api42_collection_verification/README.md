# API42 마필 프로필 수집 독립 검증 — 2026-10-01

## 후속 DB 적재 검증 완료

사용자 승인 후 동일 날짜에 4,617두를 `jeju/data/jeju_native_core.sqlite3`에 추가 적재했다. [적재 보고서](<../20261001_api42_profile_db_import/README.md>), [말 정보 218개 항목 인벤토리](<HORSE_PROFILE_FIELDS_20261001.md>)를 함께 본다. 아래의 수집 단계 저장 상태는 적재 이전 기록이다.

- `verify_imported_profiles.py`가 DB에 저장한 4,617개 전체 item JSON의 타입·값, 응답 원문·item 해시, 정규화 식별 항목, 조회시각, 공식 API 출처와 마종 근거 FK를 원문과 독립 대조했다. 모두 일치했다. [검증 JSON](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261001_api42_collection_verification/db_profile_verification.json>)
- `verify_db_import.py`가 적재 전 10개 기존 테이블의 모든 기존 행 fingerprint와 5개 기존 view SQL을 비교했다. 경주결과 191,604행·심사 34,377행·기존 API20 마종 근거 34,377행을 포함해 모두 보존됐다. SQLite 무결성 정상, FK 위반 0건이다. [보존 검증 JSON](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261001_api42_collection_verification/db_preservation_verification.json>)
- API20 사건일 기준 집계는 적재 전후 완전히 같았다. API42 `제주마`와 API20 `제주`를 서로 다른 마종 충돌로 세지 않도록 builder의 API20 집계에 출처 조건을 추가했다. DB builder 자체는 재실행하지 않았다. `api20_summary_before_import.json`·`api20_summary_after_import.json`에 비교 근거가 있다.
- 적재기의 두 번째 실행에서 삽입·업데이트 0건을 확인했다. 최초 적재 manifest와 재실행 검증은 적재 디렉터리에 각각 보존했다. 백업 파일을 직접 읽어 확인한 SHA-256은 `392c05dceef4ab50c14ace448af59f152324b7e278fe627cb462d9908594b1b8`이며 manifest와 일치했다.

## 원문 수집 검증

수집 담당 GPT-6 Luna xhigh의 결과를 지휘 에이전트가 응답 원문에서 다시 검증했다. 수집 결과는 [당일 보고서](<../20260930_api42_horse_breed_collection/RESULTS_20261001.md>), 기계 판독 검증 결과는 [verification.json](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261001_api42_collection_verification/verification.json>)에 있다.

## 확인 결과

| 항목 | 결과 |
| --- | ---: |
| 고정 대상 공식 말 ID | 4,617 |
| 경주결과 후보 | 4,006 |
| API20 제주 심사 보조 후보 | 611 |
| 2026-09-30 성공 프로필 | 2,900 |
| 2026-10-01 추가 성공 프로필 | 1,717 |
| 최신 성공 프로필의 마종 | 제주마 4,617 |
| 남은 ID | 0 |
| API42와 API20 마종 충돌 | 0 |
| 이전 성공 ID의 오늘 재조회 | 0 |
| SHA·바이트 수 대조한 원문 파일 | 4,618 |
| 전체 요청 시도 | 4,718 |

원문 파일에는 과거 HTTP 504 실패 응답 1개가 포함된다. 실패 이력은 삭제하지 않았다. 전체 이력의 통신 오류 100건은 과거 99건과 오늘 sandbox DNS 실패 1건이며, 실패했던 대상도 최종적으로 모두 조회됐다.

## 검증 방법

`verify_profile_collection.py`는 대상 목록·API20 교차원장의 고정 SHA를 확인하고, 요청 원장 모든 행의 대상 ID·공개 요청 파라미터·UTC/KST 날짜를 검사한다. 저장된 모든 응답 파일의 경로·SHA·바이트 수를 대조하고, 성공 응답을 독립 파싱해 HTTP/API 성공, 응답 건수 1, 공식 말 ID 일치, 비어 있지 않은 마종 및 수집 원장과의 마종 일치를 검사한다.

날짜별 요청 수는 9월 30일 3,000회, 10월 1일 1,718회로 일일 3,000회 한도 안이다. 각 날짜의 최소 요청 시작 간격은 1.05초다. 최종 요청 원장 SHA-256은 `007b5f426e15898c4ef61be75e3247091c158816d549a39a9fb2dfd5bc14a235`다. 초기 검증 2,900두의 결과는 `baseline_2900_verification.json`으로 보존했다.

## 해석 및 저장 상태

API는 공공데이터포털 15057985 [한국마사회 마필종합 상세정보](https://www.data.go.kr/data/15057985/openapi.do), `API42_1/totalHorseInfo_1`이다. 4,617두의 관측일은 9월 30일 2,900두와 10월 1일 1,717두로 구분한다. 오늘 기존 성공 2,900두를 재조회한 것은 아니다.

이 자료는 조회 당시 프로필의 마종 근거이며 과거 경주일의 품종 유효기간을 제공하지 않는다. 수집물은 별도 파일 원장에 보존했으며, 이번 작업에서 `jeju_native_core.sqlite3`·운영 DB·모델을 수정하거나 과거 경주행을 `native_confirmed`로 자동 승격하지 않았다. 예약 작업은 생성하지 않았다.
