# 제주마 전체 연구 DB 적재·독립 검증 보고서 (2026-09-15)

## 최종 판정

기존 경주·주행심사 DB와 운영 DB를 보존한 채, 조교·출발조교·진료·실측 체중 및 제주 Text 9종을 새 [`jeju_native_text_phase2.sqlite3`](../data/research/jeju_native_text_phase2_db_20260915/jeju_native_text_phase2.sqlite3)에 적재했다. 공식 ID가 직접 있거나 날짜·경주/사건 키로 유일하게 연결된 행만 분석 뷰에 넣었다. 혼합 Text의 이름만으로 말 ID를 추정하지 않았고, 비제주 또는 미확정 후보의 내용은 새 제주마 행으로 복제하지 않았다.

DB SHA-256은 `0f2871c2a8f931bb968d8bf7086c27f0644c0ef7332b41b7a1bd85ff637c638f`, 크기는 1,535,651,840바이트다. 기존 경주·주행심사, 확장 DB의 모든 기존 테이블, 원문, 운영 DB, 데이터셋, 모델과 registry는 수정하지 않았다.

## 자료별 적재 범위

| 자료 | 원천 범위 | 원천/후보 | 공식 연결·확인 | 기본 분석 범위 | 미해결·제외 |
| --- | --- | ---: | ---: | ---: | ---: |
| 경주결과 | 2002-07-28~2026-09-12 | 92,208출전 | 공식 세 ID 90,863 | 90,082출전·407,327구간 | ID 29, 결과/구간 격리 별도 |
| 주행심사 | 2003-07-11~2026-09-09 | 15,688후보 | `hrNo/trNo` 15,633 | 11,671출전·46,685구간 | ID 55, 구간 결측/모순 별도 |
| 일별 조교 API | 2007-10-01~2026-09-13 | 884,383 | 말 ID 전 행 | 884,383 | 양수 시간 866,457; 0은 원천값 |
| 출발조교 API | 2007-10-17~2026-09-13 | 184,351 | 말 ID 전 행 | 동일 payload 대표 181,198 | 초과 중복 3,153 |
| 진료 API | 2008-04-02~2026-09-13 | 11,653 | 말 ID 전 행 | 동일 payload 대표 11,632 | 초과 중복 21; 진단 있음 10,001 |
| 실측 체중 API | 2002-07-28~2026-09-12 | 90,713 | 출전키 전 행 | 정상 확정 경주 90,262 | 정상 결과키 미보존 630 별도 원장 |
| Text 8종 추가 파싱 | 유형별 범위, 13,006문서 | 의미 후보 1,528,696 | 구조화 제주 관련 876,813 | 아래 유형별 | 제외 160,397·미연결/혼합후보 495,617 |
| Text `dacom23` | 1,125문서 | 주행심사 후보 15,688 | 공식 신원 15,633 | 주행심사 분석 11,671 | 신원 55·구간 공백 별도 |

API 네 자료의 원천행은 `source_row`에 파일·행번호·정규화 JSON·행 SHA-256으로 저장했다. Text는 혼합 마종 원문 전체를 복사하지 않고 `text_document`의 원문 경로·파일 SHA-256과, 확인된 의미행의 줄번호·줄 SHA-256을 저장한다.

## Text 유형별 결과

| 유형 | 문서 | 후보행 | 구조화 제주 관련 | 명시 제외 | 미연결/충돌 |
| --- | ---: | ---: | ---: | ---: | ---: |
| `dacom01` 출전표 | 1,094 | 132,535 | 54,219 | 78,316 | 이름 충돌 315 |
| `dacom12` 체중표 | 2,150 | 158,343 | 81,322 | 77,021 | 이름 충돌 4 |
| `dacom13` 주로·말취소·기수변경 | 2,128 | 6,062 | 3,878 | 2,184 | 기수변경 대응 출전 부재 1 |
| `dacom23` 주행심사 | 1,125 | 기존 DB 분모 사용 | 후보 15,688 별도 테이블 | 한/래/검/산 14,201 | 공식 신원 55 |
| `dacom55` 일별조교 | 3,248 | 894,000 | 520,424 | 확정 불가 | 373,576 |
| `dacom71` 출전마 진료·장구 | 532 | 55,787 | 55,787 | 0 | 이름 충돌 4 |
| `dacom72` 말진료 | 1,150 | 53,185 | 7,362 | 확정 불가 | 45,823 |
| `db4` 출발심사 | 1,005 | 6,683 | 제주산 명시 3,807 | 비제주 산지 2,876 | 공식 말 ID 미연결 3,807 |
| `db5` 출발조교 | 1,699 | 222,101 | 150,014 | 확정 불가 | 72,087 |

`dacom55`는 날짜·마명·훈련시간·입퇴장시각·기승자 유형이 공식 API 행과 모두 맞을 때만 연결했다. Text의 `0:21`은 21분이므로 1,260초로 정규화했다. `db5`는 날짜·마명·마방·조번·기승자명이 공식 출발조교 행에서 같은 공식 말 ID로 귀결될 때 연결했다. `dacom72`는 진료일·마명·마방과 진단 문자열이 공식 진료 사건에 일치할 때만 연결했다.

출전표·체중표·장구는 `(경주일, 경주번호, 출주번호)`와 마명을 대조했다. `dacom13`의 말취소 724행과 기수변경 1,340행은 공식 출전행에 연결됐고, 기수변경 1행은 확정 제주 경주이지만 대응 출전행이 없어 격리했다. `db4`는 원문 산지가 `제주`인 행만 저장했으나 공식 말 ID가 직접 없으므로 3,807행 모두 ID 미해결 상태다.

미연결/혼합 후보는 제주마라고 확정할 수 없는 경우를 포함한다. 특히 `dacom55`, `dacom72`, `db5`의 미연결 수를 “미연결 제주마”라고 부르면 안 된다. 이름과 상세 내용은 새 제주마 테이블에 복사하지 않고 문서 ID·행번호·후보 수·사유만 `text_parse_issue`에 남겼다.

## 테이블과 소비 규칙

- 기존 분석은 `analysis_race_segments`, `analysis_trial_segments`, `analysis_daily_training`, `analysis_start_training_distinct`, `analysis_medical_distinct`, `analysis_measured_weight`를 사용한다.
- Text 분석은 `analysis_text_race_weight`, `analysis_text_entry_equipment`, `analysis_text_daily_training`, `analysis_text_start_training`, `analysis_text_medical`, `analysis_text_track_snapshot`을 사용한다.
- 출전표, 말취소와 기수변경은 `text_native_record.record_type`과 `link_status='official_entry_key_name_linked'`를 조건으로 읽는다.
- `quarantined_text_records`, `text_parse_issue`, `resolution_issue`, `extended_issue`, `source_duplicate_group`은 제외·충돌·중복 조사용이다.
- 조교·진료는 `hr_no`로 말에게 연결할 수 있지만 사건 날짜의 조교사·마주 공식 ID는 별도 입증이 없어 채우지 않았다.

전체 실제 열·형식·PK·FK·인덱스·뷰 SQL과 행 수는 [`catalog.json`](../data/research/jeju_native_text_phase2_db_20260915/catalog.json)에 있다.

## 원천과 검증

DB에는 원천 artifact 14,806건, 기존/신규 원천행 1,279,932행, 진료·체중 요청 316건과 기존 경주·심사 공식 요청 2,624건이 있다. 요청의 서비스 키는 저장하지 않았다. Text 14,131문서 모두 `text_parse_summary`에 처리 결과가 있다.

독립 검증은 다음을 확인했다.

- DB와 기반 확장 DB SHA-256, SQLite 무결성, 외래키
- 기존 테이블 행 수와 기존 metadata 값 보존
- 원천 artifact 14,806개의 실제 파일 SHA-256
- 구조화 Text 876,813행의 원문 파일·행번호·줄 SHA-256 전수 대조
- 출전키·마명·말 ID, 조교·출발조교·진료 사건 연결 전수 재검사
- 이름 충돌행에 공식 ID를 부여하지 않았는지 검사
- `db4`가 원문 `제주` 산지 행만 포함하는지 검사
- 문서별 집계와 유형별 coverage 일치, 혼합 미확정행 내용 미복제

결과는 [`independent_validation.json`](../data/research/jeju_native_text_phase2_db_20260915/independent_validation.json)이며 모든 검사가 통과했다. 요구사항별 완료 판정은 [`completion_audit.json`](../data/research/jeju_native_text_phase2_db_20260915/completion_audit.json)에 있다. 재현 코드는 [`build_jeju_native_text_phase2_db.py`](../scripts/build_jeju_native_text_phase2_db.py), 독립 검증은 [`verify_jeju_native_text_phase2_db.py`](../scripts/verify_jeju_native_text_phase2_db.py), 카탈로그 생성은 [`export_jeju_native_text_phase2_catalog.py`](../scripts/export_jeju_native_text_phase2_catalog.py)다.

```bash
.venv/bin/python scripts/verify_jeju_native_analysis_db.py
.venv/bin/python scripts/verify_jeju_native_extended_db.py
.venv/bin/python scripts/verify_jeju_native_text_phase2_db.py
.venv/bin/python scripts/export_jeju_native_text_phase2_catalog.py
```

## 아직 공식적으로 연결되지 않은 범위

경주 ID 29행, 주행심사 신원 55행, `db4` 제주산 출발심사 3,807행의 공식 말 ID는 미해결이다. 혼합 Text 중 공식 제주마 사건으로 유일하게 연결되지 않은 491,809행은 제주마 여부 자체가 확인되지 않은 후보가 대부분이며 새 제주마 의미행에 포함하지 않았다. 원천 접근이 확인되지 않은 수영·언덕조교, 예방접종·장제·약물·ECG는 이 DB의 적재 범위가 아니다.

이 보고서는 확보된 공식 원천 스냅샷의 정제·연결 상태를 검증한다. 공식 전체 역사에서 원천이 애초에 존재하지 않는 기간까지 채웠다는 뜻이 아니며, 과거 경주 전 공개 시각이나 예측 성능을 검증하지 않는다.
