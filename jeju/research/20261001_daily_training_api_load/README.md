# API18 일별조교 적재 및 검증

상태: 2026-10-01 실제 제주 전용 DB 적재와 root 독립 전수 검증 완료. Luna xhigh가 적재기를 구현하고 root가 지시·코드 검토·검증·실제 적용을 담당했다. 대상 DB는 `../../data/jeju_native_core.sqlite3`다.

이 폴더의 로더는 보관된 API18_1 `dailyTraining_1` 원문을 제주 전용 SQLite DB에 적재하기 위한 도구다. 네트워크를 호출하지 않는다. 원천 페이지 선택과 검증은 [조교 원문 감사 코드](../20261001_training_audit/audit_training_sources.py)의 `pages_for_sources()` 및 `checked_rows()`를 그대로 참조한다. 데이터 의미와 사용 한계는 [조교 API 입력 계약](../../docs/JEJU_TRAINING_API_INPUT_CONTRACT_2026-10-01.md)을 따른다.

이 범위는 기존에 보유한 API18 원문과 9개 날짜에 대한 기존 홈페이지 화면 대조를 바탕으로 한다. 전체 기간의 홈페이지를 다시 수집한 작업은 아니다. 화면 대조는 필드 의미 확인 근거이며 모든 원문 item의 공개 시각이나 시행 횟수를 확정하지 않는다.

## 확인된 원천과 모집단

| 항목 | 확인값 |
|---|---:|
| API 페이지 | 337 (양성 263, 빈 coverage 응답 74) |
| API18 전체 원문 item | 1,444,319 |
| 최신 API42 제주마 프로필과 ID 연결 | 908,316행, 4,545두 |
| 연결 ID 밖 원문 | 536,003행 |
| 그중 유효 형식이나 프로필에 없는 ID | 536,000행 |
| 형식 오류로 격리 표시한 ID | 3행 |
| 2026-09-19까지 연결행 | 907,389 |
| 2026-09-19 이후 연결행 | 927 |

자료 선택 경계는 감사 선택기를 기준으로 한다. 월별 원장(`research/20260929_api_monthly_history/ledger.json`)을 읽고, 2015-06은 원장의 일자별 `tr_date` fallback 30페이지를 사용한다. 2026-09의 6페이지는 월별 원장이 가리키는 기존 형제 아카이브에서 읽으며, 상대 경로가 제주 프로젝트 루트 밖으로 나가지 않는지 확인한다. 각 응답 파일 SHA-256과 원장·감사 산출물 해시를 적재 전에 확인한다.

프로필 연결은 최신 `horse_profile_observations` 행을 말 ID별로 `observed_at_utc DESC, api_record_id DESC` 순위화해 선택한다. 최신 프로필 수가 4,617이고 전부 `제주마`인지 확인한 뒤 공식 말 ID를 연결한다. 원문 ID의 숫자 JSON 값은 감사 코드와 같이 십진 ID 문자열로 바꾸어 비교하고, 문자열 ID는 어떤 공백도 제거하지 않는다. 따라서 원문 `hrNo='018570 '` 3행은 제주마 ID에 연결되지 않고 격리 수에 포함된다. 이름이나 ID 접두로 연결하지 않는다.

## DB 저장과 중복 기준

로더가 추가하는 객체는 `daily_training_api_artifacts`, `daily_training_api_rows`, `daily_training_api_rows_analysis_2026`뿐이다. 기존 경주·프로필·출발조교 스키마와 모델 등록부를 바꾸지 않는다.

- artifact 테이블은 선택한 337개 페이지를 모두 기록한다. 빈 페이지도 coverage artifact로 저장한다. 페이지별 원문 경로·SHA-256, source partition, 페이지 번호, 요청·수신 시각, 원문 행 수, 제주마 연결 수, 제외·격리 수 및 품질 상태별 집계를 보존한다.
- rows 테이블에는 검증된 제주마 연결 908,316행만 저장한다. 원문의 15개 API 필드는 각각 원래 필드명에 `_raw`를 붙인 TEXT 값으로 보존하고, `raw_row_json`에는 원래 JSON 값 형식과 모든 키를 보존한다. 이번 제주마 검증 명단 밖 item의 정확한 원문 바이트는 기존 원천 페이지 아카이브에서 보존하며, 행을 DB로 복제하지 않고 artifact별 제외 수로 추적한다.
- 원문 item 위치는 `(daily_training_api_artifact_id, source_row_index)`로 유일하다. 같은 말·날짜 또는 같은 내용인지로 행을 합치지 않는다.
- 안정적인 artifact 키는 source partition과 페이지 번호를 사용한다. 같은 키의 source hash·메타데이터·저장 행이 달라지면 재적재로 덮지 않고 충돌로 중단한다. 원천을 새로 수집하거나 재처리하는 작업은 새 버전 키와 별도 감사를 거쳐야 한다.

정규화 필드는 원문을 덮어쓰지 않는다. `training_date`는 검증된 API 날짜의 ISO 날짜이고, `start_time_local`·`end_time_local`은 원문 `stTime`·`spTime`을 검증해 만든 제주 현지 시계 문자열이다. 조회에서는 한국 현지시각(Asia/Seoul)으로 해석하며 UTC로 변환하지 않는다. 원문에는 별도 시간대 메타데이터가 없고 당시 최초 공개 시각도 확인되지 않는다.

`duration_seconds`는 양수 `trTerm`이 유효한 같은 날짜 시작·종료 시각의 차이와 일치할 때만 채운다. 검증된 제주마 연결행 중 890,288행이 이 조건을 충족한다. `trTerm=0`인 18,028행은 원문 0을 그대로 보존하고 기간은 NULL과 `raw_zero_unavailable` 상태로 둔다. 전체 원문 79,528개의 0값은 실제 0초 훈련으로 해석하지 않는다. 시작·종료 시간 이상이나 기간 불일치가 있으면 원문을 유지하고 정규 기간은 NULL로 둔다.

`run1Cnt`와 `run2Cnt`는 원문값이 모두 0이므로 `run1_count`·`run2_count`를 NULL로 둔다. 상태 `all_zero_unavailable`은 횟수 0이 아니라 원천에서 실횟수를 확인할 수 없음을 뜻한다. `trName`은 조교사명, `prNo`는 기승자 사번 텍스트, `partNo`는 조 안의 말 순번으로 각각 구분한다.

분석 뷰는 말 ID별 최신 API42 마명과 출생연도를 읽는 compact ranked CTE를 사용하며 무거운 `horse_analysis_2026` 뷰와 조인하지 않는다. 뷰의 행 범위는 `training_date <= 2026-09-19`다. `current_horse_age_2026`은 최신 프로필 출생연도를 기준으로 계산한 2026년 고정 나이다.

## 실행

먼저 기존 DB 또는 별도 staged DB에 대해 읽기 전용 dry-run을 수행한다. dry-run은 원문 페이지 전체를 검증하지만 DB를 변경하지 않는다.

```sh
python3 jeju/research/20261001_daily_training_api_load/daily_training_api_load.py \
  --db jeju/data/jeju_native_core.sqlite3
```

검토 가능한 집계 계획 파일이 필요하면 아직 존재하지 않는 출력 경로를 지정한다.

```sh
python3 jeju/research/20261001_daily_training_api_load/daily_training_api_load.py \
  --db /path/to/staged/jeju_native_core.sqlite3 \
  --report-out /path/to/new/daily_training_api_plan.json
```

검토 후 적재하려면 대상 DB 경로를 명시하고 `--apply`를 추가한다. 로더는 대상 DB와 같은 폴더에 SQLite backup API로 복구 사본을 만들고, 여유 공간을 확인한 다음 하나의 `BEGIN IMMEDIATE` 트랜잭션 안에서 artifact와 행을 삽입한다. DDL도 개별 `execute()` 문으로 수행한다. 입력 페이지 SHA-256과 페이지별 메타데이터를 다시 확인하며, 실패하면 해당 트랜잭션을 rollback한다.

```sh
python3 jeju/research/20261001_daily_training_api_load/daily_training_api_load.py \
  --db /path/to/staged/jeju_native_core.sqlite3 \
  --apply \
  --report-out /path/to/new/daily_training_api_apply.json
```

완료된 원문을 다시 적용하면 저장 artifact 메타데이터와 raw/normalized row tuple을 원문에서 재구성해 비교한다. 전체가 정확히 같으면 DB 쓰기와 백업 없이 0 artifact·0 row를 추가한다. 일부 누락 artifact만 채우는 경우에도 기존 artifact는 모두 정확히 비교하고 신규 행과 함께 한 트랜잭션으로 처리한다.

50페이지마다 stderr에 진행 페이지 수와 누적 원문·연결행 수를 출력한다. 보고서에는 API key가 포함된 URL을 기록하지 않는다.

## 검증 결과와 제한

2026-10-01 기준 production DB를 `mode=ro`로 연 dry-run에서 337페이지와 1,444,319행을 검증했다. 원문 페이지 수·행 수, 프로필 연결 수·말 수, ID 격리 수, 기준일 전후 연결 수, 시간 검증 집계가 독립 감사 결과와 일치했다. dry-run 중 DB 쓰기는 수행되지 않았다. 복사본 적재는 `stage_apply.json`, 재적재는 `stage_replay.json`, 독립 검증은 `stage_verification.json`에 기록했다. 재적재에서 추가 artifact 0개·행 0개였고 DB SHA-256도 동일했다. 실제 DB 적용은 `production_apply.json`, 적용 후 전수 대조는 `production_verification.json`이다. 908,316행의 원문 JSON·15개 필드·말 ID·시각·기간 상태를 모두 비교했고, 최신 이름·2026년 나이 및 2026-09-19까지 907,389행 조회도 확인했다. 기존 13개 테이블의 행 수와 기존 스키마 정의는 유지됐으며 SQLite integrity는 `ok`, FK 위반은 0이다.

조교 이벤트 날짜는 공개 시각이 아니다. 화면 공개·정정 시점이 확인되지 않은 상태이므로, 이 자료의 적재는 과거 예측시점의 입력 가용성을 증명하지 않는다. 일별조교 API18의 적재도 모델 입력 채택이나 운영 모델 변경을 뜻하지 않는다.


## 조회와 최종 적용 원장

```sql
SELECT training_date, horse_id, current_horse_name, current_horse_age_2026,
       start_time_local, end_time_local, duration_seconds, duration_minutes,
       duration_status, prNo_raw AS rider_employee_id_raw,
       trName_raw AS trainer_name_raw
FROM daily_training_api_rows_analysis_2026
WHERE horse_id = '3107491'
ORDER BY training_date DESC, source_row_index;
```

원문 전체 기간은 2007-10-01~2026-09-28이다. 분석 뷰는 2026-09-19까지이며 이후 927행은 원문 테이블에 보존한다. 기록이 없는 보유 제주마 72두를 조교 0회로 채우지 않는다. 사용자 화면의 9월 18일 `경주일` 표시도 실제 조교행으로 만들지 않았다. 백두명성의 9월 16일 시작 06:09, 종료 06:30, 1,260초/21분과 기승자 사번 `003086`·조교사명 문성호는 DB에서 다시 확인했다.

`application_manifest.json`에 실제 DB 적용 전후 SHA-256, 백업 경로와 해시, 코드와 검증 보고서 해시를 고정한다. root의 `apply_verified_plan.py`는 이미 검증한 stage 계획을 재사용하며 원장·감사 파일·프로필 snapshot 해시를 다시 확인한다. 각 원문 페이지의 SHA·행과 상태는 검토한 로더의 `apply_plan`에서 다시 검사한다. 집계 계획 재계산만 생략하고 원문 검증을 생략하지 않는다.

### 검토에서 수정한 사항

실제 DB 적용 전 코드 검토에서 프로젝트 루트 경로, 2015-06 fallback 일자별 키, ISO 날짜 상한 비교, 분석 뷰 열 참조와 백업 용량 계산의 계획 키를 수정했다. 메모리 DB에서 뷰 조회와 DDL rollback도 확인했다.

독립 검증기의 첫 시도는 2015-06-15·30 응답이 `date_probes/`의 기존 공식 응답을 참조하는 경로를 고려하지 못해 중단됐다. 폴더명 대신 수집 원장 `public_params.tr_date`로 날짜·자료 종류를 대조하도록 수정했고, 이후 복사본과 실제 DB 전수 검증이 통과했다. 첫 검증기와 당시 조건은 `independent_db_verification_initial.py`, `validation_attempts.json`에 보존한다. 이 실패는 읽기 전용 검증기에서 발생했으며 저장 자료 오류나 DB 변경은 아니었다.

이 작업은 일별조교를 기존 모델에 자동 반영하거나 당시 공개시각을 확정한 작업이 아니다. 출발조교 정규 자료는 기존 홈페이지 기준 테이블·뷰를 계속 사용한다.
