# 출발심사 API21 제주 DB 적재·검증

기준일: 2026-10-02. **제주 로컬 DB 적재·재실행·독립 전수 검증 완료.**

사용자 승인 범위는 이미 수집한 API42 프로필 21두 반영과 API21 제주마 연결 후보 적재다. GPT-6 Luna xhigh가 로더를 작성했고, 루트가 코드 검토·수정, 원문 대조, 스테이징 실행과 DB 적용을 맡았다. 이번 작업은 보관된 공식 API 응답을 사용하며 새 API 호출을 하지 않는다.

## 저장소와 조회 이름

저장소는 제주 전용 로컬 SQLite `jeju/data/jeju_native_core.sqlite3`다. API 원문과 관측 근거를 보관하는 원장이며, 현재 프로필 품종을 과거 심사일의 품종으로 확정하는 원장은 아니다.

| 내용 | 테이블·뷰 | 검증한 범위 |
|---|---|---|
| 출발심사 원문 연결 행 | `starting_exam_api_rows` | 10,664행·4,636두, 2002-06-07~2026-09-30 |
| 2026년 분석 조회 | `starting_exam_api_rows_analysis_2026` | 기존 경주 상한 2026-09-19까지 10,620행 |
| 최신 말 프로필 | `horse_profile_latest` | 21두 추가 후 전체 4,637두 |
| 최신 이름·2026년 마령 정책 | `horse_analysis_2026` | 기존 사용자 지정 정책 유지 |
| API item 전체 JSON | `api_records` | 출발심사 10,664개 + 프로필 21개 추가 |
| 원문 파일·요청·조회시각·SHA | `source_artifacts` | 출발심사 페이지 35개 + 프로필 응답 21개 추가 |

상한 이후 44행도 원문 연결 테이블에 보존한다. 주행심사 API20, 출발조교 API22와 별도 이벤트다. 이번 적재는 예측 피처 채택이나 모델 적용을 뜻하지 않는다.

## 수집 원천과 출처 연결

- 출발심사: 한국마사회 출발심사 결과, 공공데이터포털 `15057405`, `API21_1/startingTestResult_1`.
- 말 프로필: 한국마사회 마필종합 상세정보, `15057985`, `API42_1/totalHorseInfo_1`.
- 입력: [활성 후보 JSONL](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261001_starting_exam_api_collection/api21_verified_native_candidate_rows.jsonl>), 같은 수집 폴더의 연도별 원문 페이지 및 API42 후속 응답.
- 후보 SHA-256: `4965639c7e39c5e1c458bf530106ffb3c9f18f64634444e5720cb1df616a38d1`.
- 전체 제주 경마장 응답 25,614행 중 현재 API42 제주마 프로필과 연결된 10,664행만 적재한다. 품종 미분류 14,948행과 사용자 제외 2행은 이번 적재 대상이 아니다. 원문 파일은 보존한다.
- API42 21두의 개별 요청시각은 수집 원장에 없다. 관측시각은 배치 종료 `2026-10-01T15:12:06.027315+00:00`를 사용하고 그 근거를 기록한다. 삽입시각이나 심사일로 대체하지 않는다.
- 재적재 방지 키는 원문 artifact와 **1부터 시작하는 item 순번**이다. 내용 해시·말명·말 ID와 날짜만으로 유일화하지 않는다. `event_key`는 검색용 비유일 인덱스다.
- 전체 JSON은 값·타입·키 유무를 보존한다. 편의용 `*_raw` 컬럼은 TEXT이며 키 부재 또는 JSON null은 NULL이다. 빈 문자열과 대시는 원문 그대로 보존한다. 원문 파일 SHA와 item JSON SHA를 별도로 기록한다.

## 입력 해석 계약

- 최신 이름은 `current_horse_name`, 고정 분석 나이는 `current_horse_age_2026 = 2026 − 최신 API42 출생연도`다. 과거 연결키는 공식 `horse_id`다. 심사 당시 마명·성별·나이를 각각 원문 컬럼과 `sex_at_exam_raw`, `age_at_exam_raw`로 유지한다.
- `rider_raw` NULL **5,795행**은 API 원천에 `rider` 키가 없던 기록이다. 미기승·기승자 없음·파서 손실로 해석하지 않는다. 이름 문자열이며 기승자 ID가 아니다. 첫 값 제공 관측일은 2021-10-27이나 공식 필드 도입일을 확정하는 근거는 없다.
- `daySerial`은 공식 심사차수, `trainNo`는 경주번호, `chulNo`는 마번이다. 키 미제공 `daySerial`·`chulNo` 각각 14행을 NULL과 키 부재 목록으로 보존한다.
- 같은 말·날짜의 다른 경주번호 779그룹·1,558행을 모두 보존한다.
- `passFlag='-'` 4행은 `judgment_label_normalized=NULL`, `judgment_status='unknown'`이다. 불합격으로 변환하지 않는다. `1차합격` 651행, 최종 합격, 불합격, 취소·제외의 원문 판정을 각각 유지한다.
- 출발불합격 사유 미제공 3행과 과거 높은 원문 나이 9행·8두는 [선행 감사](<../20261002_starting_exam_data_audit/README.md>)의 검토 이력을 유지한다. 생년월일 자체를 확정하는 판정이 아니다.
- 외부마 조교사 1행은 `tr_name_raw='외부마'`, `tr_no_raw='0BBBBB'`를 보존하고 `trainer_id_normalized=NULL`로 제공한다. 말·심사행을 삭제하지 않는다.
- 토종등극(3005897)의 원문 `수`와 현재 프로필 `암`을 함께 유지한다. 작은곰(3005648)은 [제외 원장](</Users/kimyongjin/Desktop/horse_racing/jeju/data/horse_exclusions.json>)에 따라 활성 테이블·분석 조회에서 0행이며 재적재하지 않는다.
- `meet='제주'`는 경마장, `name='한국'`은 원문 국가 표기다. 두 항목을 마종 근거로 사용하지 않는다. API42 품종은 조회시점 관측이며 과거 유효시점 주장이 아니다.
- `exam_date`는 시행일이다. 공개시각을 제공하지 않으므로 수집시각을 공개시각으로 간주하지 않는다. 향후 과거 경주와 연결할 때 최소 `exam_date < race_date`를 적용하고 실제 가용시점 미확정을 표시한다.

## 검증과 복구 근거

- [원문 사전 점검](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261002_starting_exam_db_load/root_source_precheck.json>): 건수·말 ID·키 부재·판정·복수 회차.
- [스테이징 적재](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261002_starting_exam_db_load/staging_report.json>): 추가 10,664행·21두, 재실행 추가 0행, FK 0건·SQLite integrity_check 정상.
- [독립 전수 대조](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261002_starting_exam_db_load/staging_independent_verification.json>): 원문 페이지·item 위치·18필드·JSON·SHA·프로필·나이·출처·분석 상한·제외 ID, 백업 대비 기존 모든 테이블의 행 내용 불변.
- [분석 뷰 조회 검증](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261002_starting_exam_db_load/staging_view_optimization_verification.json>): 최신 프로필을 쿼리마다 한 번 계산하도록 조정하고 10,620행의 원문·프로필 컬럼을 다시 대조했다.
- [운영 적용 전 상태](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261002_starting_exam_db_load/production_precondition.json>): 실제 DB의 기존 모든 테이블과 스키마가 백업과 일치.
- [적재 전 백업](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261002_starting_exam_db_load/before_load.sqlite3>), [적재 전 상태](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261002_starting_exam_db_load/root_before_load.json>). 백업 SHA-256은 `372e1dcf82c07d1c3e80f4f25727c08d9d62e674e1f68d1cfe99b9bb1f23c31d`다. 로더의 임시 백업은 실행 종료 후 제거되므로 복구에는 이 영구 백업을 사용한다.

- [운영 DB 적재 보고서](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261002_starting_exam_db_load/production_load_report.json>): 출발심사 10,664행·프로필 21행·품종 근거 21행·API item 10,685개·원문 artifact 56개·metadata 12개 추가. 내부 재실행 추가 0행, FK 0건, SQLite integrity_check 정상.
- [운영 DB 독립 검증](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261002_starting_exam_db_load/production_independent_verification.json>): 원문 전수 일치, 분석 조회 10,620행, 기존 15개 테이블의 모든 기존 행 불변, quick_check 정상.
- [적용 manifest](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261002_starting_exam_db_load/application_manifest.json>): 적용 DB·원문·코드·DDL·보고서 해시 및 검증 관문.

## 재현

원문과 보고서가 고정된 이번 배치 전용 로더다. 임의 최신 수집물을 같은 배치로 섞지 않는다. 원문 SHA·관측·기존 metadata 충돌 시 덮어쓰지 않고 중단한다. SQL 값은 파라미터로 전달하며 DDL과 삽입을 같은 트랜잭션에서 실행한다. 공유 운영 DB 경로는 로더에서 거부한다.

```sh
python3 jeju/research/20261002_starting_exam_db_load/load_starting_exam_api.py \
  --db /Users/kimyongjin/Desktop/horse_racing/jeju/data/jeju_native_core.sqlite3 \
  --output-report jeju/research/20261002_starting_exam_db_load/replay_report.json
```

코드는 [로더](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261002_starting_exam_db_load/load_starting_exam_api.py>), [DDL](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261002_starting_exam_db_load/20261002_add_starting_exam_api_rows.sql>), [독립 검증기](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261002_starting_exam_db_load/root_verify_loaded_db.py>)에 있다. 재구축할 때 기존 기본 스키마만 실행해 출발심사 적재가 빠지지 않도록 이 배치 DDL·로더·제외 원장을 함께 적용한다.
