# 제주마 데이터 카탈로그·독립 검증 안내서 (2026-09-15)

> 후속 상태: 이 문서의 경주·주행심사 DB를 보존한 채 조교·출발조교·진료·체중을
> 행 단위로 추가한 [확장 DB 1차 적재 보고서](JEJU_NATIVE_EXTENDED_DB_PHASE1_LOAD_2026-09-15.md)가 생성됐다.
> 이어서 Text 9종까지 처리한 [최종 연구 DB 보고서](JEJU_NATIVE_COMPLETE_RESEARCH_DB_REPORT_2026-09-15.md)가 생성됐다.
> 최신 소비·검증 기준은 최종 연구 DB 보고서를 사용한다.

## 1. 이 문서의 목적과 스냅샷 판정

이 문서는 다른 에이전트나 검증자가 앞선 대화를 읽지 않고도 제주마 연구 산출물의 범위, 테이블, 데이터형, 연결키, 제외 규칙, 구간시간 산식, 잔여 문제와 재검증 절차를 확인할 수 있게 만든 진입점이다. 기준 시점은 **2026-09-15**, 대상 경마장은 제주(`meet=2`)다. 기존 운영 DB `data/horse_racing.sqlite3`, 원문, 기존 데이터셋, 모델, registry는 수정하지 않았다.

핵심 연구 DB는 [`jeju_native_analysis.sqlite3`](../data/research/jeju_native_analysis_db_20260915/jeju_native_analysis.sqlite3)이며 SHA-256은 `b7f05ac07f0a08bb1fdfcf4983b06e8b964e8e1a17853f6a9787ae69de35844e`다. 이 DB에 실제 적재한 데이터는 **확인된 제주마 경주결과와 제주마 주행심사 후보**다. 조교, 출발조교, 진료, 실측 체중과 나머지 Text 원천은 별도 파일로 검증되어 있으나 이 SQLite에는 아직 적재하지 않았다.

| 상태 | 뜻 | 이 스냅샷의 해당 자료 |
| --- | --- | --- |
| `DB_LOADED` | 원천행·근거·상태·구간을 연구 SQLite에 적재하고 독립 검증함 | 경주결과, 주행심사 후보 |
| `VERIFIED_FILE_ONLY` | 별도 파일의 해시·범위 또는 원천 대조를 검증했지만 연구 SQLite 테이블로 만들지 않음 | 일별 조교, 출발조교, 진료, 실측 체중, 대부분의 Text |
| `PARTIALLY_LOADED` | 한 원천 중 범위가 명시된 일부만 DB에 적재함 | `dacom23` 제주마 주행심사 후보와 2015~2018 공식표 구간 보완 |
| `QUARANTINED` | 원문은 보존하거나 집계하지만 분석 뷰에서 제외함 | ID 충돌·구간 결측/모순·비양수 결과·마종 미확정 |
| `NOT_VERIFIED` | 파일 존재만으로 행 파싱·공식 ID 연결·시점 적격성을 승인하지 않음 | 아직 행 연결하지 않은 Text 내용, 미확보/미승인 원천 |

“모든 제주 기록 적재 완료”라는 판정은 아니다. 현재 정확한 표현은 **경주결과와 확인 가능한 주행심사 후보를 별도 연구 DB에 적재했고, 다른 주요 원천은 파일 단위 검증까지 완료했다**이다.

## 2. 적재 범위와 분석 가능한 분모

| 모집단 | 날짜 범위 | 이벤트 | 후보/적재 출전행 | 공식 ID 연결 | 구간 사용 가능 | 엄격 분석 뷰 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 명시적 제주마 경주 | 2002-07-28~2026-09-12 | 9,423 | 92,208 | 정상 결과 90,892행 중 90,863 | 90,086 | 90,082출전·407,327구간 |
| 제주마 주행심사 후보 | 2003-07-11~2026-09-09 | 1,945 | 15,688 | `hrNo`·당시 `trNo` 15,633 | 11,671 | 11,671출전·46,685구간 |
| 합계 | 위 두 범위 | 11,368 | 107,896 | 모집단별 기준 적용 | 101,757 | 101,753출전·454,012구간 |

경주의 구간 사용 가능 90,086행 중 4행은 기존 DB와 공식 API의 말 ID가 충돌한다. 시간 근거는 보존하지만 세 공식 ID가 완결된 `analysis_race_segments`에서는 제외하므로 엄격 뷰가 90,082행이다. DB 전체 `derived_segment` 454,028행과 두 엄격 뷰의 합계 454,012행 차이 16개는 이 4행의 파생 구간이다.

주행심사는 당시 공식 원천에서 `hrNo`와 `trNo`를 확인했다. 해당 심사표에 마주 ID가 없으므로 `ow_no`는 NULL이다. 현재 말 프로필의 조교사·마주를 과거 심사에 소급하지 않았다.

## 3. 연구 SQLite 객체 카탈로그

기계 판독 가능한 전체 스키마는 [`catalog.json`](../data/research/jeju_native_analysis_db_20260915/catalog.json)에 있다. 이 파일은 각 객체의 실제 `sqlite_master.sql`, `PRAGMA table_info`, 외래키, 인덱스와 현재 행 수를 담는다.

### 3.1 테이블

| 테이블 | 행 수 | 기본키·자연키 | 역할 |
| --- | ---: | --- | --- |
| `metadata` | 2 | `key` | 스키마 버전과 범위 선언 |
| `source_artifact` | 1,108 | `id`; `path` UNIQUE | 입력 파일 경로, 원천 종류, SHA-256, 행 수 |
| `source_request` | 2,624 | `id`; 요청 종류·이벤트·요청/응답 해시 UNIQUE | 비밀키를 제거한 공식 요청과 응답 해시·HTTP 상태 |
| `event` | 11,368 | `id`; `(event_type, meet, event_date, event_number)` UNIQUE | 경주 9,423건과 심사 1,945건의 헤더 |
| `source_row` | 107,896 | `id`; `(source_artifact_id, line_number, row_sha256)` UNIQUE | 적재한 각 원천행의 정규화 JSON과 행 해시 |
| `entry` | 107,896 | `id`; `(event_id, horse_number)` UNIQUE | 출주번호, 말/관계자 ID, 품종 근거, 결과·분석 상태 |
| `section_checkpoint` | 599,658 | `id`; `(entry_id, section_code, source_kind)` UNIQUE | 말별 S1F·코너·G3F·G1F·FIN 원 값과 누적 변환값 |
| `derived_segment` | 454,028 | `id`; `(entry_id, segment_sequence)` UNIQUE | 인접 체크포인트 차분으로 만든 구간 거리·시간 |
| `resolution_issue` | 5,002 | `id` | 행별 ID·결과·구간 미해결 사유와 양쪽 근거 |
| `exclusion_summary` | 4 | `id`; `source_code` UNIQUE | 혼합 심사 Text에서 제주마 분석에 넣지 않은 마종 집계 |
| `coverage` | 62 | `id`; `(event_type, dimension, dimension_value)` UNIQUE | 전체·연도·거리별 분모, 양수 완주, 구간 품질 집계 |

### 3.2 분석 뷰

| 뷰 | 행 수 | 고유 출전 수 | 사용 목적과 포함 조건 |
| --- | ---: | ---: | --- |
| `analysis_race_segments` | 407,327 | 90,082 | `race`, `segment_quality='usable'`, `identity_status='official_race_ids_linked'`인 기본 경주 구간 분석 |
| `analysis_trial_segments` | 46,685 | 11,671 | `trial`, `segment_quality='usable'`, `identity_status='official_trial_hr_tr_linked'`인 기본 심사 구간 분석 |
| `quarantined_entries` | 6,143 | 6,143 | 구간이 usable이 아니거나 경주/심사 공식 ID가 미해결인 행 조사 |

### 3.3 열과 SQLite 데이터형

SQLite의 선언형과 실제 저장 규칙은 다음과 같다. 원천 JSON의 ID가 숫자여도 정규화 DB에서는 공식 ID를 `TEXT`로 저장한다.

| 객체 | 열 | 형식·단위 |
| --- | --- | --- |
| `event` | `event_type`, `event_date`, `event_number`, `trial_round`, `distance_m` | `TEXT('race'|'trial')`, `TEXT YYYYMMDD`, `INTEGER`, `INTEGER/NULL`, `INTEGER m` |
|  | `meet`, `grade`, `event_name`, `weather`, `track_condition`, `track_moisture_percent`, `population_status` | `INTEGER=2`, 나머지 설명값 `TEXT/REAL` |
| `entry` | `horse_number`, `horse_name` | 출주번호 `INTEGER`, 마명 `TEXT` |
|  | `hr_no`, `tr_no`, `ow_no` | 각각 7·6·6자리 숫자 문자열 `TEXT/NULL`; 앞자리 0 보존 |
|  | `finish_position`, `finish_time_ms` | `INTEGER/NULL`, `INTEGER ms/NULL` |
|  | `breed_status`, `breed_evidence`, `identity_status`, `record_status`, `segment_quality` | 판정 및 근거 코드 `TEXT` |
|  | `time_analysis_eligible` | 불리언 `INTEGER 0/1` |
|  | `official_evidence_json` | 공식 행과 연결 근거를 담은 JSON 직렬화 `TEXT/NULL` |
| `section_checkpoint` | `section_code` | `S1F`, `1C`, `2C`, `3C`, `G3F`, `4C`, `G1F`, `FIN` |
|  | `source_value_ms`, `elapsed_from_start_ms` | 원천값과 출발 후 누적 변환값 `INTEGER ms` |
|  | `time_basis` | `cumulative` 또는 `closing` |
|  | `distance_from_start_m`, `distance_is_approximate` | 출발점 기준 거리 `INTEGER m`, 근사 여부 `INTEGER 0/1` |
|  | `source_kind`, `source_response_sha256` | 원천 구분과 응답 해시 `TEXT` |
| `derived_segment` | `segment_sequence`, `from_codes`, `to_codes` | 순서 `INTEGER`, 병합된 양 끝 코드 `TEXT` |
|  | `start_distance_m`, `end_distance_m`, `distance_m` | `INTEGER m` |
|  | `distance_is_approximate`, `elapsed_ms`, `derivation` | `INTEGER 0/1`, `INTEGER ms`, 산식 설명 `TEXT` |
| `source_artifact` | `source_kind`, `path`, `sha256`, `row_count` | 모두 `TEXT`, 단 행 수는 `INTEGER/NULL` |
| `source_request` | `request_json`, `request_sha256`, `response_sha256`, `http_status`, `response_bytes` | 정제 요청 JSON·해시 `TEXT/NULL`, 상태·크기 `INTEGER/NULL` |
| `source_row` | `line_number`, `row_sha256`, `normalized_json` | `INTEGER/NULL`, 해시와 정규화 JSON `TEXT` |
| `resolution_issue` | 이벤트·출주 키, `issue_code`, `details_json` | 키는 위와 동일, 사유와 행별 근거는 `TEXT` |
| `coverage` | 분류 열과 각 집계 열 | 차원은 `TEXT`, 모든 집계는 `INTEGER` |

## 4. 연결키와 조인 계약

1. 이벤트 자연키는 `(event_type, meet, event_date, event_number)`다. 경주와 주행심사는 같은 날짜·번호가 있어도 `event_type`으로 분리한다.
2. 출전 자연키는 이벤트키에 `horse_number`를 더한다. 외부 원천을 대조할 때 기본 키는 `(meet=2, 날짜, 경주/심사 번호, 출주번호)`이며 마명과 `hrNo`를 교차 확인한다.
3. 경주 공식 ID는 해당 날짜·경주·출주 행에 실제 표시된 `hrNo/trNo/owNo`만 채택한다. 이름만으로 추정하지 않는다.
4. 말의 서로 다른 사건을 연결할 때는 `hr_no`를 사용한다. 마명 단독 조인은 금지한다.
5. 조교·진료·체중은 사건 날짜의 말 ID로 연결할 수 있다. 그 날짜의 조교사·마주 소속이 별도로 입증되지 않으면 경주 당시 `tr_no/ow_no`를 해당 사건의 담당자로 복사하지 않는다.
6. `entry.id`가 체크포인트와 파생 구간의 외래키다. 분석 소비자는 자연키 문자열을 이어 붙여 내부 PK처럼 사용하지 않는다.

## 5. 구간시간의 의미와 산식

경주결과 API의 초 단위 소수값은 반올림하여 `INTEGER ms`로 저장한다. 주행심사 연결 원장의 시간은 이미 ms다. S1F·코너 값은 출발 후 누적시간이며, G3F·G1F는 결승선까지 남은 구간의 소요시간인 `closing` 값이다. 후자는 다음처럼 같은 누적 기준으로 바꾼다.

```text
G3F 누적시각 = FIN 완주시간 - G3F 원천값
G1F 누적시각 = FIN 완주시간 - G1F 원천값
파생 구간시간 = 오른쪽 체크포인트 누적시각 - 왼쪽 체크포인트 누적시각
파생 구간거리 = 오른쪽 출발점 거리 - 왼쪽 출발점 거리
```

같은 물리 지점을 나타내는 코드가 공개 반올림 오차 200ms 이내에서 일치하면 한 지점으로 묶고, 대표 코드는 `S1F → 1C → 2C → 3C → G3F → 4C → G1F → FIN` 우선순위로 선택한다. 시간 역전, 비양수 구간, 필수 지점 결측은 파생하지 않고 격리한다. `distance_is_approximate=1`이면 양 끝 중 하나 이상이 공식 코너의 **약 위치**다.

파생 구간 454,028행의 거리 분포는 100m 19,492, 200m 402,889, 210m 12,233, 300m 12,157, 400m 5,565, 500m 665, 600m 1,027이다. 대부분 웹사이트식 약 200m 구간 분석에 쓸 수 있지만 모든 거리가 정확한 200m 실측 분할은 아니다. 코너 위치를 포함한 경주 파생구간 256,092행과 심사 파생구간 35,013행은 근사 구간이다. 원천에 없는 중간 지점을 보간하지 않았다.

## 6. 상태 코드와 제외 근거

### 6.1 이벤트·신원·기록 상태

| 차원 | 코드 | 행/이벤트 수 | 해석 |
| --- | --- | ---: | --- |
| `population_status` | `confirmed_native_normal_race` | 9,288이벤트 | 명시적 제주마이며 양수 정상 결과가 있는 경주 |
|  | `explicit_je_no_positive_result` | 135이벤트 | `제`이나 경주 전체에 양수 결과가 없어 구간 분석 제외 |
|  | `native_confirmed_trial` | 1,942이벤트 | 공식 신원 연결이 하나 이상 있는 제주마 심사 |
|  | `native_candidate_identity_unresolved` | 3이벤트 | 후보 전 행의 신원 미해결 |
| `identity_status` | `official_race_ids_linked` | 90,863행 | 당시 공식 `hrNo/trNo/owNo` 완결 |
|  | `official_race_id_unresolved` | 29행 | 경주 공식 ID 미해결 |
|  | `official_source_ids_unvalidated_quarantine` | 1,316행 | 양수 결과 없는 135경주의 ID를 분석용으로 승인하지 않음 |
|  | `official_trial_hr_tr_linked` | 15,633행 | 심사 당시 `hrNo/trNo` 연결 |
|  | `official_trial_identity_unresolved` | 55행 | 심사 신원 충돌/누락 |
| `segment_quality` | `usable` | 경주 90,086·심사 11,671 | 체크포인트 순서와 차분 통과 |
|  | `missing` | 경주 57·심사 3,539 | 양수 완주이나 구간 지점 부족 |
|  | `inconsistent` | 경주 5·심사 1 | 시간 순서·합계 모순 |
|  | `not_applicable` | 경주 2,060·심사 422 | 비양수 결과 또는 격리 경주 |
|  | `identity_unresolved` | 심사 55 | 공식 신원 미해결로 분석 제외 |

### 6.2 `resolution_issue` 사유 원장

| 사유 | 행 수 | 처리 |
| --- | ---: | --- |
| `no_positive_result_race` | 1,316 | 원천행 보존, 구간 분석 제외 |
| `segment_missing` | 3,596 | 결측으로 유지, 보간 금지 |
| `segment_inconsistent` | 6 | 행별 체크포인트 근거와 함께 격리 |
| `missing_official_trNo` | 25 | 경주 ID 미해결 29건 원장에 유지 |
| `official_row_absent_from_db` | 4 | 공식 API/DB 출전 집합 충돌, 어느 쪽도 임의 선택하지 않음 |
| `horse_name_conflict` | 34 | 심사 Text/공식표 마명 충돌 |
| `age_conflict` | 14 | 심사 연령 충돌 |
| `sex_conflict` | 6 | 심사 성별 충돌 |
| `official_row_missing` | 1 | 공식 심사표 대응행 없음 |

### 6.3 혼합 주행심사 원문의 마종 제외

| 원문 코드 | 행 수 | 판정 |
| --- | ---: | --- |
| `한` | 7,338 | Text 코드로 비제주마 확정, 새 제주마 출전행에 미적재 |
| `래` | 818 | Text 코드로 비제주마 확정, 새 제주마 출전행에 미적재 |
| `검` | 29 | 공식 프로필에서 한라마 25두·한라마(래) 3두인 28두를 확인해 제외 |
| `산` | 6,016 | 제주마임을 긍정 확인하지 못해 제주마 분석에서 제외; 비제주마 확정이라고 부르지 않음 |

## 7. DB 밖에 있는 제주 관련 자료

아래 자료는 현재 연구 SQLite에 적재됐다는 뜻이 아니다. 날짜는 이 프로젝트가 실제 보존·검증한 제주마 확인 부분집합의 관측 범위다.

| 자료 종류 | 원천/경로 | 범위·규모 | 현재 상태 | 분석 전 남은 일 |
| --- | --- | --- | --- | --- |
| 일별 조교 | `data/raw/jeju_native_training/horse_training_confirmed_native.jsonl.gz` | 2007-10-01~2026-09-13, 884,383행 | `VERIFIED_FILE_ONLY`; 월별 원문 재추출과 내용·순서 일치 | 사건 테이블 설계, 결측과 훈련 0 구분, 당시 사람 소속 별도 입증 |
| 출발조교 | `data/raw/jeju_native_training/start_training_confirmed_native.jsonl.gz` | 2007-10-17~2026-09-13, 184,351행 | `VERIFIED_FILE_ONLY` | 완전 동일 payload 초과 3,153행을 임의 제거하지 않고 사건 중복 상태로 적재 |
| 말 ID 확인 진료 | `data/raw/jeju_native_health_weight/medical_*.jsonl` | 2008-04-02~2026-09-13, 11,653행 | `VERIFIED_FILE_ONLY`; 진단 문자열 10,001행 | 동일 payload 초과 21행 유지, 무기록을 건강으로 해석 금지 |
| 실측 출전체중 | `data/raw/jeju_native_health_weight/weight_*.jsonl` | 2002-07-28~2026-09-12, 90,713행 | `VERIFIED_FILE_ONLY`; 키 중복·추가 0 | 정상 결과 90,892키 중 미연결 630키, 특히 2026-07-07 40행 조사 |
| Text `dacom01` | 출전표 | 1,094파일, 2003-07-10~2026-09-07 | 파일 해시 검증, 행 연결 미완료 | 출전키·시점 파싱 |
| Text `dacom12` | 출전마체중 안내 | 2,150파일, 2003-07-12~2026-09-12 | 파일 해시 검증; 빈 본문 4건 명시 | API 체중과 출전별 대조 |
| Text `dacom13` | 기수변경·취소·주로상태 | 2,128파일, 2003-07-12~2026-09-12 | 파일 해시 검증 | 경주/출전별 구조화와 공개 시각 검증 |
| Text `dacom23` | 주행심사 결과 | 1,125파일, 2003-07-11~2026-09-09 | `PARTIALLY_LOADED`; 제주마 후보 15,688행 적재 | 미해결 55행, 2003~2014 구간 전수 가능성 조사 |
| Text `dacom55` | 일별 조교 현황 | 3,248파일, 2015-04-29~2026-09-13 | 파일 해시 검증, 행 연결 미완료 | API 조교와 중복·차이 대조 |
| Text `dacom71` | 출전마 진료·장구 | 532파일, 2015-04-29~2026-09-07 | 파일 및 출주번호 일부 검증 | 내용 필드 구조화; 6,731 정상 경주 중 파일 부재 138경주, 마명 충돌 4행 |
| Text `dacom72` | 말 진료 현황 | 1,150파일, 2005-11-03~2026-09-09 | 파일 해시 검증, 행 연결 미완료 | 공식 말 ID 연결과 동명이마 격리 |
| Text `db4` | 출발심사 결과 | 1,005파일, 2014-10-19~2026-09-09 | 파일 해시 검증, 행 연결 미완료 | 심사 종류·말 ID 구조화 |
| Text `db5` | 출발조교 현황 | 1,699파일, 2014-10-19~2026-09-13 | 파일 해시 검증, 행 연결 미완료 | API 출발조교와 대조·중복 판정 |

조교 파일 SHA-256은 일별 조교 `186d2335e799fff2712bcf9ace116ee4eced790f0f5518dc48476d8449b06b64`, 출발조교 `e828597a84f969b0d7fc74c4f1be067e711134266e02393d0a62135a819a214e`다. 진료·체중은 연도/월별 manifest 집합으로 검증한다. 혼합 API 응답 본문을 모두 보존한 구조가 아니므로 제주마 필터 결과와 응답 해시의 검증 범위를 넘어서 원 응답 전체를 재구성할 수 있다고 가정하면 안 된다.

## 8. 원천 근거와 요청 원장

`source_artifact` 1,108건은 경주 제주마 필터 JSONL 25개, 실제 후보행을 사용한 주행심사 Text 1,073개, 연결·제외·구간 관련 control ledger/manifest 10개다. 전체 보존 `dacom23` 1,125개와 수가 다른 이유는 후보 적재에 사용되지 않은 파일까지 DB의 입력 artifact로 등록하지 않았기 때문이다.

`source_request` 2,624건의 구성은 경주결과 API 연도 요청 25, 주행심사 공식 신원표 1,945, 주행심사 공식 구간 보완 390, 품종 프로필 209, `검` 제외 공식 심사표 26, 제외 품종 프로필 28, 공식 체크포인트 정의 1건이다. 서비스 키는 저장하지 않고 정제 요청 JSON, 요청 해시, 응답 해시, HTTP 상태와 응답 크기를 보존한다.

2015~2018 Text에 빠진 주행심사 구간은 공식 상세표 390건을 조회해 **2,981출전행**에 보완했다. `section_checkpoint.source_kind='trial_official_web_supplement'`로 Text 값과 구분한다.

## 9. 다른 에이전트의 독립 검증 절차

검증자는 먼저 DB와 원천을 수정하지 않는 아래 명령을 프로젝트 루트에서 실행한다.

```bash
shasum -a 256 data/research/jeju_native_analysis_db_20260915/jeju_native_analysis.sqlite3
sqlite3 -readonly data/research/jeju_native_analysis_db_20260915/jeju_native_analysis.sqlite3 "PRAGMA integrity_check; PRAGMA foreign_key_check;"
.venv/bin/python scripts/verify_jeju_native_analysis_db.py
.venv/bin/python scripts/export_jeju_data_catalog.py
.venv/bin/python scripts/validate_jeju_running_trial_links.py
.venv/bin/python scripts/verify_jeju_other_sources.py
```

`verify_jeju_native_analysis_db.py`는 DB를 SQLite read-only URI로 열고 1,108개 입력 파일 SHA-256, 공식 ID의 문자열형/길이/숫자 형식, 외래키, 비제주 확정행 부재, 101,757개 usable 출전의 체크포인트 선택과 **454,028개 파생 구간 전수 재계산**을 수행한다. 기대 결과는 [`independent_validation.json`](../data/research/jeju_native_analysis_db_20260915/independent_validation.json)의 `passed=true`, 빈 `bad_source_hash_paths`와 빈 `derivation_error_entry_ids`다.

`verify_jeju_other_sources.py`의 전체 결과는 의도적으로 `all_checks_passed=false`일 수 있다. 이는 진료의 완전 동일 payload 초과 21행을 실패가 아닌 정상행으로 조용히 넘기지 않기 위한 상태다. 세부 검사 중 조교 재추출, 체중 키/값, Text 해시, `dacom71` 출주번호 대조가 통과했는지와 [`issues.jsonl`](../data/research/jeju_other_sources_verification_20260915/issues.jsonl)을 함께 확인해야 한다.

다음 SQL은 문서의 핵심 수치를 DB에서 독립적으로 재집계한다.

```sql
SELECT event_type, COUNT(*) AS events, MIN(event_date), MAX(event_date)
FROM event GROUP BY event_type;

SELECT v.event_type, e.identity_status, e.segment_quality, COUNT(*) AS rows
FROM entry e JOIN event v ON v.id=e.event_id
GROUP BY v.event_type, e.identity_status, e.segment_quality
ORDER BY v.event_type, e.identity_status, e.segment_quality;

SELECT issue_code, COUNT(*) AS rows
FROM resolution_issue GROUP BY issue_code ORDER BY issue_code;

SELECT distance_m, COUNT(*) AS segments
FROM derived_segment GROUP BY distance_m ORDER BY distance_m;

SELECT 'race' AS kind, COUNT(*) AS segments,
       COUNT(DISTINCT event_date||':'||event_number||':'||horse_number) AS entries
FROM analysis_race_segments
UNION ALL
SELECT 'trial', COUNT(*),
       COUNT(DISTINCT event_date||':'||event_number||':'||horse_number)
FROM analysis_trial_segments;
```

빌더 [`build_jeju_native_analysis_db.py`](../scripts/build_jeju_native_analysis_db.py)는 고정 출력 경로의 DB를 새 임시 파일로 완성한 뒤 교체한다. 현재 봉인된 산출물을 유지해야 하는 검증자는 **별도 프로젝트 복사본 또는 별도 checkout**에서 빌더를 실행하고 새 SHA-256과 행 수를 비교한다. 현재 작업 디렉터리에서는 read-only verifier만 실행한다.

## 10. 경계 사례와 합격 기준

| 사례 | 기대 결과 |
| --- | --- |
| 첫 경주 2002-07-28 제주 4경주 800m | 8행 모두 완주시간은 있으나 S1F/G1F가 0이므로 구간 분석 제외 |
| 2015년 경주 경계 | 기존 DB 기반 행과 공식 결과 연결 계약을 유지하고 이름 단독 연결 없음 |
| 2015년 주행심사 경계 | 후보 719행, 공식 연결 718행, 마명 충돌 1행 보류 |
| 2025년 주행심사 | 후보 1,438행, 연결 1,431행, 미해결 7행 |
| 2025년 이후 운영 DB 심사 대조 | 출주 키 2,390개 일치; 연결 2,380·미해결 10, 공식 ID 충돌 0 |
| 2026-07-07 제주 4경주 | 양수 경주결과 40행이나 구간 원값이 0이고 보존 체중 부분집합·`dacom71`도 없음; 결측 유지 |
| 경주 공식 ID 미해결 | 정확히 29행: `missing_official_trNo` 25 + `official_row_absent_from_db` 4 |
| 주행심사 공식 ID 미해결 | 정확히 55행: 마명 34 + 연령 14 + 성별 6 + 공식행 누락 1 |

최소 합격 조건은 DB SHA 일치, `PRAGMA integrity_check='ok'`, 외래키 위반 0, 원천 해시 불일치 0, 확정 비제주마 `entry` 0행, usable 무구간 0행, non-usable 유구간 0행, 파생 산식 불일치 0이다. 수치가 다르면 최신 자료라고 가정해 덮어쓰지 말고 입력 파일·manifest·DB 각각의 SHA-256과 차이 키를 새 원장에 남긴다.

## 11. 아직 해결되거나 적재되지 않은 범위

- 경주 공식 ID 29행과 주행심사 신원 55행은 해결되지 않았다. 이름, 현재 프로필, 다수결로 채우지 않는다.
- 경주 135개·1,316행은 `제`가 명시됐지만 양수 정상 결과가 없다. 정상 경주 안에서도 비양수 완주 744행, 구간 결측 57행, 모순 5행이 있다.
- 주행심사는 ID 연결행 중 구간 결측 3,539행, 모순 1행, 비양수 결과 422행이 엄격 구간 뷰 밖이다. 2003~2014 공식 상세표 전체에 과거 구간이 정말 없는지는 표본 확인만 했고 전수 부재를 입증하지 않았다.
- `산` 6,016행은 제주마 근거가 없어서 제외했으며, 공식 프로필 전수 검증 전까지 비제주마 확정 집합이 아니다.
- 일별 조교·출발조교·진료·체중과 대부분의 Text는 이 연구 SQLite에 아직 없다. 파일 보유량을 DB 적재량으로 합산하면 안 된다.
- 실측 체중 정상 경주키 630개, `dacom71` 정상 경주 138개, `dacom71` 마명 충돌 4행, 진료 중복 payload 21행, 출발조교 동일 payload 초과 3,153행은 상태를 유지한다.
- 수영조교 구형 API는 제주 연도별 조회가 모두 0행이었고, 신규 수영·언덕주로 API는 활용 가능 범위를 확인하지 않았다. 예방접종·장제·약물·ECG도 이번 적재 범위가 아니다.

이 데이터는 보존 원천과 연결·구간 산식의 연구용 스냅샷이다. **과거 경주 전 정보 공개 시각, 모든 원천의 역사적 완전성, 모델 입력 적격성, 예측 성능 또는 수익성을 검증한 결과가 아니다.**

## 12. 산출물 지도

| 산출물 | 용도 |
| --- | --- |
| [`manifest.json`](../data/research/jeju_native_analysis_db_20260915/manifest.json) | 핵심 파일 경로와 봉인 DB SHA-256 |
| [`catalog.json`](../data/research/jeju_native_analysis_db_20260915/catalog.json) | SQLite 객체·열·외래키·인덱스·행 수와 외부 원천 상태 |
| [`validation.json`](../data/research/jeju_native_analysis_db_20260915/validation.json) | 빌더 내부 검증 결과 |
| [`independent_validation.json`](../data/research/jeju_native_analysis_db_20260915/independent_validation.json) | 읽기 전용 독립 전수 검증 결과 |
| [`JEJU_NATIVE_ANALYSIS_DB_LOAD_2026-09-15.md`](JEJU_NATIVE_ANALYSIS_DB_LOAD_2026-09-15.md) | DB 적재 결과와 사용법 |
| [`JEJU_NATIVE_DB_LOAD_200M_READINESS_2026-09-15.md`](JEJU_NATIVE_DB_LOAD_200M_READINESS_2026-09-15.md) | 약 200m 구간의 물리적 의미와 준비도 |
| [`JEJU_RACE_TIME_ID_UNRESOLVED_29_2026-09-14.md`](JEJU_RACE_TIME_ID_UNRESOLVED_29_2026-09-14.md) | 경주 공식 ID 미해결 29행 |
| [`JEJU_NATIVE_RUNNING_TRIAL_LINKAGE_2026-09-15.md`](JEJU_NATIVE_RUNNING_TRIAL_LINKAGE_2026-09-15.md) | 주행심사 공식 신원 연결과 미해결 55행 |
| [`JEJU_OTHER_SOURCE_VERIFICATION_2026-09-15.md`](JEJU_OTHER_SOURCE_VERIFICATION_2026-09-15.md) | 조교·진료·체중·Text 검증과 잔여 이슈 |
| [`JEJU_NATIVE_COMPLETE_RECORD_INGESTION_PLAN_2026-09-15.md`](JEJU_NATIVE_COMPLETE_RECORD_INGESTION_PLAN_2026-09-15.md) | 아직 DB 밖인 자료의 후속 적재 순서와 완료 기준 |
