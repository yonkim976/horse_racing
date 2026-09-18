# 제주마 나머지 자료 정제·확장 DB 1차 적재 보고서 (2026-09-15)

## 결과

기존 경주·주행심사 연구 DB를 수정하지 않고 [`jeju_native_extended.sqlite3`](../data/research/jeju_native_extended_db_20260915/jeju_native_extended.sqlite3)을 새로 만들었다. 기존 테이블은 양방향 `EXCEPT` 비교로 동일함을 확인했다. 새 DB SHA-256은 `a10cf4ce2d153268926b0bb14a83bbe29a325ba572811b9303f1fa209426da61`, 크기는 1,125,683,200바이트다. 운영 DB, 원문, 기존 연구 DB, 데이터셋, 모델과 registry는 수정하지 않았다.

| 신규 자료 | 원천행 | 기간 | 고유 말 | 기본 분석 뷰 | 상태 |
| --- | ---: | --- | ---: | ---: | --- |
| 일별 조교 | 884,383 | 2007-10-01~2026-09-13 | 3,939 | 884,383 | 행 단위 적재·검증 완료 |
| 출발조교 | 184,351 | 2007-10-17~2026-09-13 | 3,877 | 181,198 | 3,153개 동일 payload의 두 번째 행을 distinct 뷰에서 제외 |
| 말 ID 확인 진료 | 11,653 | 2008-04-02~2026-09-13 | 788 | 11,632 | 19개 중복 그룹·초과 21행을 distinct 뷰에서 제외 |
| 실측 출전체중 | 90,713 | 2002-07-28~2026-09-12 | 3,993 | 90,262 | 90,713행 모두 연구 DB 출전행에 연결; 정상 확정 경주만 기본 뷰에 포함 |
| 제주 Text 9종 | 14,131문서 | 유형별 상이 | 미산출 | 해당 없음 | 파일·해시·파싱 상태 등록; 대부분 내용 파싱은 다음 단계 |

일별 조교 중 양수 훈련시간은 866,457행이다. 0은 원천값을 그대로 보존한 것이며 원천이 없는 날을 훈련 0회로 채우지 않았다. `exercise_person_no`는 원천의 `prNo`를 문자열로 보존한 값일 뿐, 공식 기수·조교사 FK로 승격하지 않았다. 출발조교에는 기승자 이름만 있고 당시 공식 사람 ID가 입증되지 않아 이름 그대로 저장했다.

진료의 `-`와 빈 진단은 정규화 열에서 NULL로 바꾸되 `source_row.normalized_json`에 원 표기를 보존한다. 진단명이 있는 행은 10,001행이다. 진료가 없는 말이나 진단명이 빈 행을 건강으로 해석하지 않는다. 중복행도 삭제하지 않고 `duplicate_occurrence`와 `source_duplicate_group`에 남긴다.

체중 90,713행은 `(경주일, 경주번호, hrNo)`와 출주번호를 함께 대조해 연구 DB의 `entry`에 모두 연결했다. 이 중 양수 정상 결과와 공식 경주 ID가 완결된 90,262행만 `analysis_measured_weight`에 나온다. `recentRcDate`는 날짜 외에 `신마` 문자열도 담으므로 `recent_race_date`와 `recent_race_date_raw`를 분리했다.

## 신규 테이블과 뷰

| 객체 | 행 수 | 역할 |
| --- | ---: | --- |
| `collection_request` | 316 | 진료 19년·체중 297개월의 정제 요청, 응답 해시·크기·시각·totalCount |
| `daily_training_record` | 884,383 | 말 ID·일자·훈련시간·구보/습보·기승자 원 필드 |
| `start_training_record` | 184,351 | 말 ID·일자·기승자명·비고·중복 발생 순서 |
| `medical_record` | 11,653 | 말 ID·진료일·병원·진단·중복 발생 순서 |
| `measured_weight_record` | 90,713 | 출전 FK·실측 체중·증감·최근 경주 표기·연결 상태 |
| `source_duplicate_group` | 3,172 | 출발조교 3,153그룹, 진료 19그룹의 payload 해시와 반복 수 |
| `text_document` | 14,131 | Text 유형·날짜·원격/로컬 원천·파일 해시·파싱/연결 상태 |
| `extended_issue` | 936 | 기존 다른 원천 검증의 체중 공백·진료 중복·Text 부재/마명 충돌 원장 |
| `extended_coverage` | 97 | 네 행 자료의 연도별/전체 및 Text 유형별 파일 coverage; 진료 0행 연도 포함 |
| `analysis_daily_training` | 884,383 | 원천행 전체를 유지하는 조교 분석 뷰 |
| `analysis_start_training_distinct` | 181,198 | 동일 payload당 한 행만 제공하는 출발조교 뷰 |
| `analysis_medical_distinct` | 11,632 | 동일 payload당 한 행만 제공하는 진료 뷰 |
| `analysis_measured_weight` | 90,262 | 정상 확정 제주마 경주에 연결된 체중 뷰 |

전체 DB에는 기존 경주·주행심사 원천행을 포함해 `source_row` 1,279,932행, `source_artifact` 14,806건이 있다. 신규 네 자료와 기존 이슈 원장에서 추가한 행별 원천은 1,172,036행이다. 모든 공식 말 ID는 7자리 숫자 문자열 `TEXT`로 검증했다.

## Text 문서 상태

| 유형 | 문서 | 현재 `row_parse_status` |
| --- | ---: | --- |
| `dacom01` 출전표 | 1,094 | `document_hash_verified_unparsed` |
| `dacom12` 출전마체중 | 2,150 | `document_hash_verified_unparsed` |
| `dacom13` 기수변경·취소·주로상태 | 2,128 | `document_hash_verified_unparsed` |
| `dacom23` 주행심사 | 1,125 | `native_candidate_rows_loaded_in_base_db` |
| `dacom55` 일별조교 | 3,248 | `document_hash_verified_unparsed` |
| `dacom71` 출전마 진료·장구 | 532 | `race_number_name_keys_partially_verified` |
| `dacom72` 말진료 | 1,150 | `document_hash_verified_unparsed` |
| `db4` 출발심사 | 1,005 | `document_hash_verified_unparsed` |
| `db5` 출발조교 | 1,699 | `document_hash_verified_unparsed` |

따라서 Text 14,131문서는 DB에서 파일 수준 provenance와 작업 상태를 조회할 수 있지만, `dacom23`의 제주마 후보를 제외한 내용 전체를 정량 테이블로 적재 완료했다고 해석하면 안 된다. `dacom71`도 출주번호·마명 키 대조까지만 부분 검증된 상태다.

## 보존한 문제 원장

`extended_issue`에는 체중 API 양수행 미보존 771키, 원래 체중 모집단 밖에서 확인된 결과키 4개, 진료 중복 payload 19그룹, `dacom71` 마명 충돌 4행, 확인 경주에 대응 Text가 없는 138경주를 행별 근거와 함께 적재했다. 출발조교 초과 중복 3,153행과 진료 초과 중복 21행은 `source_duplicate_group`에서 별도로 집계한다.

## 독립 검증

재현 코드는 [`build_jeju_native_extended_db.py`](../scripts/build_jeju_native_extended_db.py), 읽기 전용 검증 코드는 [`verify_jeju_native_extended_db.py`](../scripts/verify_jeju_native_extended_db.py), 스키마 카탈로그 생성기는 [`export_jeju_native_extended_catalog.py`](../scripts/export_jeju_native_extended_catalog.py)다.

```bash
.venv/bin/python scripts/verify_jeju_native_extended_db.py
.venv/bin/python scripts/export_jeju_native_extended_catalog.py
```

독립 검증은 기존 10개 핵심 테이블의 양방향 동일성, DB·기존 DB SHA-256, 외래키·무결성, 14,806개 원천 파일 해시, 신규 1,172,036행의 원문 파일·행번호·정규화 JSON·행 해시, 체중 출전키, 공식 ID 문자열, 중복 그룹, 분석 뷰 분모, Text 상태 과대표기 여부와 요청 내 비밀키 부재를 검사해 모두 통과했다. 결과는 [`independent_validation.json`](../data/research/jeju_native_extended_db_20260915/independent_validation.json), 전체 실제 스키마는 [`catalog.json`](../data/research/jeju_native_extended_db_20260915/catalog.json)에 있다.

빌더는 기존 확장 DB가 있으면 기본적으로 중단한다. 봉인 스냅샷을 교체하는 `--force`는 새 검증용 복사본에서만 사용한다.

## 다음 적재 단계

다음 단계는 Text 8종의 시대별 서식을 파싱하고, 경주 기반 자료는 `(meet, 경주일, 경주번호, 출주번호)`와 마명·`hrNo`를 대조하며, 경주키가 없는 조교·진료·출발심사는 이름만으로 ID를 선택하지 않고 다중 후보를 격리하는 것이다. `dacom23`은 이미 주행심사 후보 연결이 끝났으므로 미해결 55행과 옛 구간 공백을 유지한다. 수영·언덕조교, 예방접종·장제·약물·ECG처럼 접근·제공 범위가 확인되지 않은 원천은 별도 상태로 남긴다.

이 적재는 자료 정리와 출처 추적을 위한 연구 스냅샷이다. 과거 경주 전 공개 시각이나 예측 성능을 검증하지 않는다.
