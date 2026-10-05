# 데이터 사전

모든 날짜는 원천의 한국 현지 경주일/사건일을 `DATE`로 저장한다. ID는 선행 0과 문자형 값을 보존하기 위해 `VARCHAR`로 저장한다.

## 정규화 테이블

| 테이블 | 기본키 | 내용 | 행 수 |
|---|---|---|---:|
| `venue_dimension` | `venue_code` | 서울·부경·영천 개최지와 공식 meet/권역 | 3 |
| `race` | `race_id` | 거리·등급·부담중량 방식·주로·날씨·결과 확정 상태 | 44,089 |
| `entry_result` | `(race_id, hr_no)` | 출전표, 공식 말·기수·조교사·마주 ID, 체중, 결과 | 489,851 |
| `section` | 원천 행 보존 | 원천별 구간 값·단위·시간 의미 | 4,242,283 |
| `trial_entry` | `(trial_event_id, participant_no)` | 주행심사 출전·판정·구간 JSON·연결 상태 | 76,413 |
| `training_event` | `training_event_id` | 일별 조교와 출발조교 사건 | 7,749,406 |
| `medical_event` | `medical_event_id` | 공식 API 및 Text 진료·치료 사건과 후보 ID | 2,181,002 |
| `weight_event` | `weight_event_id` | 경주일 마체중과 증감 | 438,868 |
| `equipment_event` | `equipment_event_id` | 장구·비출혈·질병 관련 원문 필드 | 441,918 |

## 연결·연구 테이블

| 테이블 | 내용 | 사용상 주의 |
|---|---|---|
| `horse_dimension` | 공식 `hr_no`별 이름 변형, 최초·최종 경주일, 최초 개최지, 개최지 수 | 이름은 표시·대조용이며 키는 `hr_no`다. |
| `model_entry_base` | warm-up을 포함한 전체 출전행과 시점 이전 이력 피처 | 2000~2005년 행은 과거 이력 계산용이다. |
| `model_target_entry` | 2006년 이후 결과 확정 경주의 상세 학습 모집단 | 현재 경주 결과·배당도 있으므로 직접 피처 행렬로 쓰지 않는다. |
| `model_training_entry` | 허용 입력 열과 `target_*` 목표값을 분리한 기본 학습 테이블 | 당일 체중·주로·날씨는 공개시각 미검증 표시를 따른다. |
| `coverage_year_source` | 개최지×자료 종류×연도 coverage | `official_id_rate`의 분모는 해당 원천 행이다. |
| `identity_issue` | 대표적인 원천 충돌·개최지 오분류 사례 | 5개 핵심 사례다. |
| `unresolved_identity_ledger` | 모든 미확정 진료·체중·주행심사·관계자 연결 행 | 자동 학습 입력에서 제외한다. |

## 핵심 열

### 공통 식별자

- `venue_code`: 실제 개최지. `SEOUL`, `BUSAN`, `YEONGCHEON`; 주행심사 일부는 `NULL`이고 ledger/coverage에서 `YEONGNAM_UNRESOLVED`로 표시한다.
- `canonical_meet`: 서울 1, 부경 3, 영천 4.
- `region_code`: 서울 또는 영남 권역. 개최지와 별개다.
- `race_id`: 개최지·경주일·경주번호로 만든 안정 키.
- `hr_no`, `jockey_no`, `trainer_no`, `owner_no`: 공식 문자열 ID.
- `owner_no_raw_json`: 마주 ID의 원문 표현. 숫자/문자 혼합과 선행 0 추적용이다.
- `source_dataset`, `source_path`, `source_row`: 원천 역추적 열.

### 결과 상태

- `official_result_state`: `confirmed`, `void`, `special_only_unresolved` 등 경주 단위 상태.
- `result_status`: `finished`, `scratched`, `disqualified`, `did_not_finish`, `start_excluded`, `race_excluded`, `void_or_unresulted`.
- `is_rank_label`: 정상 순위·경주시간을 목표값으로 쓸 수 있는 행.
- `is_dead_heat`: 동일 경주·동일 순위가 2두 이상인 동착 표시.
- `is_model_target`: 2006-01-01 이후이며 경주 결과가 확정된 행.

### 구간기록

- `value_ms`, `unit`: 밀리초 단위의 원천 값과 명시 단위.
- `time_basis`: `cumulative` 또는 `source_specific_unverified`.
- `canonical_closing_ms`: 의미가 검증된 경우에만 채운 종반 표준값.
- `semantic_status`: 변환 근거와 검증 상태. 다른 `time_basis`끼리는 같은 피처로 합치지 않는다.

### 사건 연결 및 가용성

- `link_status`: `confirmed*`, `ambiguous*`, `unmatched` 등 신원 연결 상태.
- `candidate_hr_nos_json`: 진료 Text에서 가능한 공식 말 ID 후보.
- `venue_resolution_status`: 주행심사의 실제 개최지 확정 여부.
- `availability_status`: 당시 공개 시각이 확인됐는지 표시. `availability_unverified`와 `retrospective_only`는 실시간 모의실험의 기본 입력에서 제외한다.

### 학습 테이블

- `prior_*`: 현재 경주보다 앞선 모든 개최지/동일 개최지 경력.
- `training_*_3d/7d/14d/28d`: `event_date < race_date` 조건으로 계산한 조교 이력.
- `official_medical_events_28d`: 공식 ID가 있는 API 진료 사건 수.
- `confirmed_text_medical_events_28d`: Text 중 신원이 확정된 사건만 계산한 수.
- `venue_changed_since_last_start`, `first_start_at_venue`, `away_from_first_observed_venue`: 원정·개최지 이동 피처.
- `target_*`: 현재 경주의 사후 목표값. 입력 피처에서 제외한다.
- `feature_availability_note`: 당일 체중·주로·날씨의 과거 공개시각 제약.
- `history_cutoff_contract`: 현재 값은 `strictly_before_race_date`다.

## 학습 범위

- 서울 2000~2005년과 부경 2005년은 warm-up 이력이다.
- 기본 목표 모집단은 2006-01-01 이후 결과 확정 경주다.
- 영천 2026-09-13의 6경주는 목표 테이블에 포함되지만, 표본이 적어 개최지 전용 모델 학습에는 부적합하다.
- 주행심사·모의경주는 `trial_entry`에만 있으며 정식 경주 라벨과 합치지 않는다.

