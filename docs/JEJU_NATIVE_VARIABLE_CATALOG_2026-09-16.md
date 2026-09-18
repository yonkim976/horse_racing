# 제주 네이티브 Top3 변수 카탈로그 (2026-09-16)

이 문서는 `jeju_native_top3_dataset_v1_20260915_r2`의 57개 feature registry 항목을
원천 state builder와 현재 실험 runner가 실제로 계산·사용하는 방식에 대조한 초안이다.
따라서 registry의 설명과 구현이 다르면 구현을 기준으로 적었고, 차이는 별도로 표시했다.
변수는 경주일 `T`를 기준으로 사건일이 `T-2` 이하인 과거 행만 사용한다. H0/H1/H2
상태는 이 사건일 cutoff를 지키지만, H3 선언카드의 문서 날짜를 실제 공개·수정 시각의
증거로 볼 수는 없다.

## 기준과 사용 묶음

- 상태 생성기: [`jeju_native_top3_states.py`](../src/horse_racing/analysis/jeju_native_top3_states.py)
- 결측 처리와 변환: [`jeju_top3_preprocessing.py`](../src/horse_racing/analysis/jeju_top3_preprocessing.py)
- registry: `data/research/jeju_native_top3_dataset_v1_20260915_r2/feature_registry.json`
- 상태 metadata: `data/research/jeju_native_top3_dataset_v1_20260915_r2/state_metadata.json`
- 실험 protocol: `data/research/jeju_native_top3_experiment_v1_20260915/protocol.json`

여기서 “사용 묶음”은 registry family를 뜻하고, 괄호 안은 현재 실험 후보를 뜻한다.

| 표기 | 의미 | 현재 사용 방식 |
|---|---|---|
| H0 | 과거 성적·Elo 상태 | `M0_H0`, `M1_H0`에 공통 16개만 사용. alias 4개는 제거 |
| H1 | H0에 시간·구간·속도 상태 추가 | `M0_H1`, `M1_H1`에서 H0와 함께 사용. alias 4개 제거 |
| H2 | H1에 훈련·의무·시험·체중 availability 보조변수 추가 | `M0_H2`, `M1_H2`에서 사용 |
| common | 현재 경주 문맥 | H0/H1/H2 모두 사용하며 `distance_m`, `field_size`는 필수값 |
| B1/B2 | 단일 직접 baseline | B1은 `global_elo_pre`, B2는 `speed_residual_mean_pre`만 사용 |
| B0 | 입력 없는 uniform baseline | feature를 사용하지 않음 |

현재 runner 후보는 B0, B1, B2, M0/M1의 H0/H1/H2와 입상 목표의 P_H0/P_H1/P_H2이다. H0/H1/H2 모델은
`FitPreprocessor`로 FIT split의 numeric median 대치, 결측 indicator, 표준화,
`regime` one-hot을 적용하고 FIT에서 상수 열을 제거한다. TUNE/CAL/EVAL에는 FIT
통계와 category만 재사용한다. 알 수 없는 regime은 모든 regime one-hot이 0이다.
상수인 결측 indicator도 FIT에서 제거될 수 있다.

## 57개 registry 변수

### H0: 과거 성적·Elo 상태 (1–20)

| # | 기술명 | 한글 뜻·계산 | 기간·단위 | 사용 묶음 | 결측·시점 가정 및 alias |
|---:|---|---|---|---|---|
| 1 | `global_elo_pre` | 전체 비-400m 정상 결승마의 global Elo 사전값. 정상 순위끼리 pairwise 갱신, K=20, 동률은 0.5 | 과거 전체, Elo 점수 | H0: M0/M1 H0–H2 | 과거 정상 시작이 없으면 초기값 1500. T-2 cutoff. |
| 2 | `distance_elo_pre` | 현재 정확한 거리의 distance Elo 사전값. 400m도 별도 거리 상태로 보존 | 과거 전체, Elo 점수 | H0: M0/M1 H0–H2 | 거리별 과거가 없으면 초기값 1500. 다른 거리와 섞지 않음. |
| 3 | `ability_mean_pre` | 구현상 `global_elo_pre`와 완전히 같은 값 | 과거 전체, Elo 점수 | registry H0 | **제거 alias**: `global_elo_pre`의 alias. |
| 4 | `distance_state_pre` | 구현상 `distance_elo_pre`와 완전히 같은 값 | 과거 전체, Elo 점수 | registry H0 | **제거 alias**: `distance_elo_pre`의 alias. |
| 5 | `elo_uncertainty_pre` | `1/sqrt(1 + starts)`로 만든 Elo 불확실성 대용치 | 과거 global 비-400m 시작 수, 무차원 | H0: M0/M1 H0–H2 | 시작이 없으면 1.0. T-2 cutoff. |
| 6 | `ability_uncertainty_pre` | 구현상 `elo_uncertainty_pre`와 같은 식과 값 | 과거 global 시작 수, 무차원 | registry H0 | **제거 alias**: `elo_uncertainty_pre`의 alias. |
| 7 | `starts_pre` | 시작 횟수. 정상 순위 1–89 및 started code 91/92 포함 | 과거 global 비-400m, 횟수 | H0: M0/M1 H0–H2 | 0에서 시작. 결장/비시작은 증가시키지 않음. |
| 8 | `normal_completed_pre` | 정상 finish(순위 1–89)의 완료 횟수 | 과거 global 비-400m, 횟수 | H0: M0/M1 H0–H2 | 0에서 시작. `normal_history_count`와 동일. |
| 9 | `wins_pre` | 정상 finish 순위 1 횟수 | 과거 global 비-400m, 횟수 | H0: M0/M1 H0–H2 | 0에서 시작. T-2 cutoff. |
| 10 | `top3_pre` | 정상 finish 순위 1–3 횟수 | 과거 global 비-400m, 횟수 | H0: M0/M1 H0–H2 | 0에서 시작. T-2 cutoff. |
| 11 | `normal_history_count` | 구현상 `normal_completed_pre`와 같은 완료 횟수 | 과거 global 비-400m, 횟수 | registry H0 | **제거 alias**: `normal_completed_pre`의 alias. |
| 12 | `days_since_previous_start` | 최근 시작일로부터 현재 경주일까지의 날짜 차이 | 과거 시작, 일 | H0: M0/M1 H0–H2 | 이전 시작이 없으면 null. 현재 경주일은 포함하지 않음. |
| 13 | `days_since_previous_normal_finish` | 최근 정상 finish일로부터 현재 경주일까지의 날짜 차이 | 과거 정상 finish, 일 | H0: M0/M1 H0–H2 | 이전 정상 finish가 없으면 null. T-2 cutoff. |
| 14 | `distance_starts_pre` | 현재 정확한 거리에서의 시작 횟수 | 과거 exact distance, 횟수 | H0: M0/M1 H0–H2 | started code 91/92 포함, 거리 상태 0에서 시작. |
| 15 | `distance_normal_completed_pre` | 현재 정확한 거리에서 정상 finish한 횟수 | 과거 exact distance, 횟수 | H0: M0/M1 H0–H2 | 순위 1–89만 포함. |
| 16 | `distance_wins_pre` | 현재 정확한 거리에서 순위 1 횟수 | 과거 exact distance, 횟수 | H0: M0/M1 H0–H2 | 정상 순위 1만 포함. |
| 17 | `distance_top3_pre` | 현재 정확한 거리에서 순위 1–3 횟수 | 과거 exact distance, 횟수 | H0: M0/M1 H0–H2 | 정상 순위 1–3만 포함. |
| 18 | `recent_finish_score_5_mean` | 최근 정상 finish 최대 5회의 `(field_size-position)/(field_size-1)` 평균. 1두 필드는 1로 처리 | 최근 5회 정상 finish, 무차원 | H0: M0/M1 H0–H2 | 이력이 없으면 null. 400m 및 비정상 status 제외. |
| 19 | `recent_top3_rate_5` | 최근 정상 finish 최대 5회 중 순위 3 이내 비율 | 최근 5회 정상 finish, 비율 | H0: M0/M1 H0–H2 | 이력이 없으면 null. 400m 및 비정상 status 제외. |
| 20 | `performance_variability_pre` | 최근 finish score 최대 5회의 population 표준편차 | 최근 최대 5회, 무차원 | H0: M0/M1 H0–H2 | 관측 2회 미만이면 null. 표본 표준편차가 아님. |

### H1: 시간·속도·구간 상태 (21–34)

속도·구간 관측은 정상 순위이고 `segment_quality == usable`이며 양수 finish time인
기록만 사용한다. `time_per_100m = finish_time_ms / distance_m * 100`이다. speed
baseline은 `(distance, era)`별 과거 중앙값이고, sparse cell은 null로 남긴다. 말의
residual 평균은 같은 거리의 과거 residual을 era를 넘어 pooling한다.

| # | 기술명 | 한글 뜻·계산 | 기간·단위 | 사용 묶음 | 결측·시점 가정 및 alias |
|---:|---|---|---|---|---|
| 21 | `speed_time_per_100m_mean_pre` | 말의 같은 거리 usable `time_per_100m` 평균 | 과거 exact distance usable, ms/100m | H1: M0/M1 H1–H2 | 관측이 없으면 null. T-2까지. |
| 22 | `speed_residual_mean_pre` | 말의 같은 거리 usable 시간이 `(거리, era)` baseline에서 얼마나 벗어나는지의 평균 | 과거 exact distance, ms/100m | B2 및 H1: M0/M1 H1–H2 | baseline이 없는 과거 기록은 residual을 만들지 않음. 관측 없으면 null. |
| 23 | `speed_residual_std_pre` | 같은 거리 residual의 population 표준편차 | 과거 exact distance residual, ms/100m | H1: M0/M1 H1–H2 | residual 2개 미만이면 null. |
| 24 | `speed_observation_count_pre` | 같은 거리 usable finish time 관측 횟수 | 과거 exact distance, 횟수 | H1: M0/M1 H1–H2 | 관측 없으면 0. |
| 25 | `distance_speed_time_per_100m_mean_pre` | 구현상 21번과 같은 값 | 과거 exact distance usable, ms/100m | registry H1 | **제거 alias**: `speed_time_per_100m_mean_pre`의 alias. |
| 26 | `distance_speed_residual_mean_pre` | 구현상 22번과 같은 값 | 과거 exact distance, ms/100m | registry H1 | **제거 alias**: `speed_residual_mean_pre`의 alias. |
| 27 | `distance_speed_observation_count_pre` | 구현상 24번과 같은 값 | 과거 exact distance, 횟수 | registry H1 | **제거 alias**: `speed_observation_count_pre`의 alias. |
| 28 | `normal_usable_count_pre` | 구현상 global 비-400m 정상 usable time 누적 횟수 | 과거 global 비-400m usable, 횟수 | H1: M0/M1 H1–H2 | **registry metadata의 “same distance” 설명과 구현이 다름**. 실제 builder는 전역 count. 없으면 0. |
| 29 | `usable_time_count` | 구현상 28번과 같은 `state.usable` 값 | 과거 global 비-400m usable, 횟수 | registry H1 | **제거 alias**: `normal_usable_count_pre`의 alias. |
| 30 | `distance_normal_usable_count_pre` | 현재 정확한 거리에서의 정상 usable time 횟수 | 과거 exact distance usable, 횟수 | H1: M0/M1 H1–H2 | 관측 없으면 0. |
| 31 | `section_s1f_ms_mean_pre` | 같은 거리 과거 초반 200m 구간 S1F 시간 평균 | 과거 exact distance, ms | H1: M0/M1 H1–H2 | section 값이 유효한 기록만, 최대 최근 10개 deque. 없으면 null. |
| 32 | `section_s1f210_ms_mean_pre` | 1110/1610m source가 제공하는 초반 210m S1F210 시간 평균 | 과거 exact distance, ms | H1: M0/M1 H1–H2 | S1F와 섞지 않음. 유효 관측이 없으면 null, 최대 10개. |
| 33 | `section_g1f_ms_mean_pre` | 같은 거리 과거 결승선 전 200m G1F 시간 평균 | 과거 exact distance, ms | H1: M0/M1 H1–H2 | 유효 관측만, 최대 최근 10개. 없으면 null. |
| 34 | `section_g3f_ms_mean_pre` | 같은 거리 과거 결승선 전 600m G3F 시간 평균 | 과거 exact distance, ms | H1: M0/M1 H1–H2 | 유효 관측만, 최대 최근 10개. 없으면 null. |

### common: 현재 경주 문맥 (35–37)

| # | 기술명 | 한글 뜻·계산 | 기간·단위 | 사용 묶음 | 결측·시점 가정 및 alias |
|---:|---|---|---|---|---|
| 35 | `distance_m` | 현재 경주의 명시된 경주 거리 | 현재 race, m | common: M0/M1 H0–H2 | 필수값. target race에서 직접 읽음. |
| 36 | `field_size` | 현재 경주에 포함된 starter 수 | 현재 race, 마리 | common: M0/M1 H0–H2 | 필수값. 과거 경주가 아니라 target entry snapshot에서 계산. |
| 37 | `regime` | target date가 속한 era: `pre_2018_08_31`, `2018_08_31_2022_12_31`, `2023_01_01_2025_12_27`, `post_2025_12_28` | target date, 범주 | common: M0/M1 H0–H2 | FIT categories만 one-hot. 미지 category는 all-zero. |

### H2: 훈련·의무·시험·체중 availability 보조변수 (38–57)

H2 원천 API/native 행은 event/source/event ID로 중복 제거한다. H2의
`coverage_unknown`은 “자료가 없다는 것이 사건이 없다는 뜻은 아님”을 보존하기 위해
builder가 관측 여부와 무관하게 1로 둔다. `observed_any`는 deduplicated event가
하나라도 있을 때 1이다. 모든 창은 T-2에서 끝난다.

| # | 기술명 | 한글 뜻·계산 | 기간·단위 | 사용 묶음 | 결측·시점 가정 및 alias |
|---:|---|---|---|---|---|
| 38 | `training_28d_count` | 일반 훈련 event 수 | T-29..T-2, 횟수 | H2: M0/M1 H2 | event 없으면 0, `coverage_unknown=1`. |
| 39 | `training_28d_duration_seconds` | 일반 훈련 event의 duration 합 | T-29..T-2, 초 | H2: M0/M1 H2 | duration missing은 event별 0 fallback. event 없으면 0. |
| 40 | `training_28d_canter_count` | 일반 훈련의 canter 횟수 합 | T-29..T-2, 횟수 | H2: M0/M1 H2 | event별 값 합. 없으면 0. |
| 41 | `training_28d_gallop_count` | 일반 훈련의 gallop 횟수 합 | T-29..T-2, 횟수 | H2: M0/M1 H2 | event별 값 합. 없으면 0. |
| 42 | `training_28d_coverage_unknown` | 28일 훈련 원천 coverage를 완전히 확인할 수 없는지 표시 | T-29..T-2, flag | H2: M0/M1 H2 | builder가 항상 1. 0은 관측 부재의 증명이 아님. |
| 43 | `training_28d_observed_any` | dedup 훈련 event가 있었는지 | T-29..T-2, flag | H2: M0/M1 H2 | event가 하나라도 있으면 1, 아니면 0. |
| 44 | `start_training_28d_count` | start training event 수 | T-29..T-2, 횟수 | H2: M0/M1 H2 | dedup event 기준. 없으면 0. |
| 45 | `start_training_28d_coverage_unknown` | start training coverage 불확실성 flag | T-29..T-2, flag | H2: M0/M1 H2 | builder가 항상 1. |
| 46 | `start_training_28d_observed_any` | dedup start training event 존재 여부 | T-29..T-2, flag | H2: M0/M1 H2 | event가 있으면 1. |
| 47 | `medical_90d_count` | 의료 event 수 | T-91..T-2, 횟수 | H2: M0/M1 H2 | dedup event 기준. 없으면 0. |
| 48 | `medical_90d_coverage_unknown` | 90일 의료 coverage 불확실성 flag | T-91..T-2, flag | H2: M0/M1 H2 | builder가 항상 1. |
| 49 | `medical_90d_observed_any` | dedup 의료 event 존재 여부 | T-91..T-2, flag | H2: M0/M1 H2 | event가 있으면 1. |
| 50 | `trial_count_pre` | 과거 시험/조교 event 수 | 모든 과거, T-2 cutoff, 횟수 | H2: M0/M1 H2 | event ID 또는 `(day,event_number)` dedup. 없으면 0. |
| 51 | `trial_last_valid_time_ms_pre` | 가장 최근 유효 trial finish time | 모든 과거 through T-2, ms | H2: M0/M1 H2 | 양수이고 `segment_quality == usable`인 값만. 없으면 null. |
| 52 | `trial_coverage_unknown` | trial 원천 coverage 불확실성 flag | 모든 과거 through T-2, flag | H2: M0/M1 H2 | builder가 항상 1. |
| 53 | `trial_observed_any` | trial event가 하나라도 존재하는지 | 모든 과거 through T-2, flag | H2: M0/M1 H2 | 유효 time이 없어도 event가 있으면 1. |
| 54 | `weight_last_kg_pre` | dedup된 과거 체중 event 중 가장 최근 체중 | 모든 과거 through T-2, kg | H2: M0/M1 H2 | 값이 없으면 null. 최신 측정값 기준. |
| 55 | `weight_count_pre` | dedup된 체중 event 수 | 모든 과거 through T-2, 횟수 | H2: M0/M1 H2 | 체중값이 null이어도 dedup event이면 count. event가 없으면 0. |
| 56 | `weight_coverage_unknown` | 체중 원천 coverage 불확실성 flag | 모든 과거 through T-2, flag | H2: M0/M1 H2 | builder가 항상 1. |
| 57 | `weight_observed_any` | 체중 event 존재 여부 | 모든 과거 through T-2, flag | H2: M0/M1 H2 | event가 있으면 1. |

## 명시적으로 제거한 alias 8개

현재 protocol은 아래 중복 항목을 모델 입력에서 제거한다. registry에는 남아 있어
57개 완전성을 보존하지만, active feature 수에는 포함하지 않는다.

1. `ability_mean_pre` → `global_elo_pre`
2. `distance_state_pre` → `distance_elo_pre`
3. `ability_uncertainty_pre` → `elo_uncertainty_pre`
4. `normal_history_count` → `normal_completed_pre`
5. `distance_speed_time_per_100m_mean_pre` → `speed_time_per_100m_mean_pre`
6. `distance_speed_residual_mean_pre` → `speed_residual_mean_pre`
7. `distance_speed_observation_count_pre` → `speed_observation_count_pre`
8. `usable_time_count` → `normal_usable_count_pre`

따라서 common 3개를 포함한 active 입력은 H0 19개, H1 29개, H2 49개이다.
`normal_usable_count_pre`는 실제 builder가 전역 비-400m usable count를 계산한다는
점에서 registry의 same-distance aggregation metadata와 다르다. 이 문서에서는 구현값을
정의로 삼았다.

## 모델 사용 상태와 목표의 차이

같은 active feature를 넣어도 목표 함수가 같지는 않다.

- M0는 LightGBM ranker로 relevance(1위/2위/3위의 순서형 relevance)를 학습하고,
  최종 raw score를 Plackett–Luce top3 evaluator에서 평가한다. seed 17/43 raw score를
  평균한 뒤 calibration beta를 별도로 적용한다.
- M1은 직접 linear score를 만들고 accepted order에 대한 Top3 Plackett–Luce NLL을
  최적화한다. 따라서 동일한 H0/H1/H2 변수라도 M0와 M1의 score scale, 순서, calibration
  결과가 다를 수 있다.
- B1은 `global_elo_pre`, B2는 `speed_residual_mean_pre`만 사용하므로 입력 비교용
  baseline이다. B0는 uniform baseline이다.

set hit, exact order hit, order-given-set, set/order NLL은 서로 다른 평가 목표다.
한 feature가 set 선택에 기여했는지와 정확한 1–2–3 순서에 기여했는지는 따로 판정해야
하며, 후보 간 차이를 변수 하나의 인과 효과로 해석해서는 안 된다.

## metadata·정답·ID로서 입력에서 제외한 항목

다음은 state/dataset에 존재해도 예측 feature가 아니다.

- 식별·분할·출처: `race_id`, `entry_id`, `horse_id`, `event_date`, `target_date`,
  `cutoff_at`, history policy/version, source/event IDs, source hashes, split/fold,
  FIT/TUNE/CAL/EVAL role, availability class, source quality, raw row numbers.
- 정답과 평가 파생값: finish position, winner/top3 labels, accepted top3 orders/sets,
  race outcome/status, evaluation metric rows, post-race result fields.
- state bookkeeping: last-start dates, raw deque contents, Elo state internals,
  dedup keys, complete-event markers, and target-row bookkeeping. 이 값들은 위 57개를
  계산하는 데 쓰이지만 그대로 model column으로 넘기지 않는다.

## H3 현재 연구 변수 (33개 추가)

H3 선언카드 build가 기존에 제안했던 미구현 구획을 실제 연구 feature로 작성했다.
원천 구현은 [`jeju_h3_features.py`](../src/horse_racing/analysis/jeju_h3_features.py)와
`data/research/jeju_native_h3_features_v1_20260916/build_report.json`에 있다. H3 arm은
legacy active 49개에 아래 BASE_FEATURES 19개를 더하고, H3R arm은 여기에
RACE_RELATIVE_FEATURES 14개를 더한다. 기존 registry 57개에서 alias 8개를 뺀
legacy active 49개를 기준으로
세면 `49 + 19 = 68`, H3R은 `49 + 33 = 82`개 이름이다. relative 14개 중
세 개는 legacy 상태값을 source로 재사용하지만, centered/percentile 열 자체는 새
연구 변수다. FIT의 missing flag와 constant drop 뒤 실제 encoded dimension은
이 명목 개수와 별도로 기록해야 한다.

### H3 BASE_FEATURES (19개)

| # | 기술명 | 한글 뜻·계산 | 기간·단위 | 결측·주의점 |
|---:|---|---|---|---|
| 1 | `card_observed` | T-2 이하 문서에서 entry와 일치하는 선언카드를 선택했는지 | target card, binary | 카드가 없거나 변형이 충돌하면 0. 카드 문서 날짜는 공개·수정 시각의 증거가 아님. |
| 2 | `declared_horse_number` | 선언카드에 적힌 마번/출전 번호 | target card, 정수 | raw declared horse number일 뿐 physical gate/stall 매핑은 검증하지 않음. |
| 3 | `declared_age` | 선언카드의 말 연령 | target card, 년 | 카드가 없으면 null. 결과 데이터의 나이 fallback을 쓰지 않음. |
| 4 | `declared_female` | 성별이 `암`인지 나타내는 flag | target card, binary | 카드 성별 `암`만 1. |
| 5 | `declared_gelded` | 성별이 `거`인지 나타내는 flag | target card, binary | 카드 성별 `거`만 1. female/gelded는 서로 다른 binary 열. |
| 6 | `declared_burden_kg` | 선언 부담중량 | target card, kg | 카드가 없으면 null. 결과의 실제 중량 fallback 없음. |
| 7 | `declared_rating` | 헤더가 명시한 `레이팅` 열의 숫자 | target card, rating 점수 | 명시적 레이팅만 사용하며 `승군순위`를 rating으로 해석하지 않음. |
| 8 | `declared_grade_number` | `출전/출주: 제 N등급`에서 읽은 등급 번호 | target card, 등급 정수 | 헤더가 없거나 파싱되지 않으면 null. |
| 9 | `declared_jockey_allowance_kg` | 기수 표기의 `(-N)` 감량 allowance | target card, kg | allowance 표기가 없으면 0. 기수 이름 자체는 feature가 아님. |
| 10 | `jockey_history_starts` | target 기수 이름에 과거 단일 official ID가 매핑된 경우 그 ID의 과거 시작 수 | 과거 결과, 횟수; event date ≤ T-2 | 과거 실제 참가자와 결과만 사용. 이름 미매칭/다중 ID면 0과 unknown. |
| 11 | `jockey_history_win_rate` | 기수 과거 승률의 고정 prior smoothing `(win + 2) / (starts + 20)` | 과거 결과 ≤ T-2, 비율 | prior 2/20은 고정값이며 FIT 추정이 아님. current target 기수 결과를 대입하지 않음. |
| 12 | `jockey_history_top3_rate` | 기수 과거 입상률 `(top3 + 6) / (starts + 20)` | 과거 결과 ≤ T-2, 비율 | prior 6/20 고정. ambiguous name은 unknown state. |
| 13 | `trainer_history_starts` | target 조교사 이름에 과거 단일 official ID가 매핑된 경우 과거 시작 수 | 과거 결과 ≤ T-2, 횟수 | 과거 ID mapping만 사용. current trainer ID 직접 입력 아님. |
| 14 | `trainer_history_win_rate` | 조교사 과거 승률 `(win + 2) / (starts + 20)` | 과거 결과 ≤ T-2, 비율 | prior 2/20 고정, unknown mapping이면 smoothing baseline. |
| 15 | `trainer_history_top3_rate` | 조교사 과거 입상률 `(top3 + 6) / (starts + 20)` | 과거 결과 ≤ T-2, 비율 | prior 6/20 고정. |
| 16 | `horse_jockey_history_starts` | 해당 horse–jockey official ID pair의 과거 시작 수 | 과거 pair 결과 ≤ T-2, 횟수 | pair가 과거에 식별된 경우만 집계. target actual jockey fallback 없음. |
| 17 | `horse_jockey_history_top3_rate` | pair 입상률 `(pair_top3 + 3) / (pair_starts + 10)` | 과거 pair 결과 ≤ T-2, 비율 | prior 3/10 고정. |
| 18 | `jockey_identity_history_known` | target 이름이 과거 관측에서 정확히 하나의 official jockey ID로 확인됐는지 | 과거 mapping ≤ T-2, binary | 0은 미관측과 ambiguous 다중 ID를 함께 포함. 이름→ID mapping은 과거 관측만 사용. |
| 19 | `trainer_identity_history_known` | target 이름이 과거 관측에서 정확히 하나의 official trainer ID로 확인됐는지 | 과거 mapping ≤ T-2, binary | 0은 미관측/ambiguous. 현재 이름·ID 자체는 직접 모델 열이 아님. |

기수·조교사 current `name`/`ID`는 target row에서 직접 feature로 넣지 않는다. 과거
결과에 함께 있는 official ID와 이름 mapping만으로 history를 만들며, 과거 mapping이
불명확하면 unknown으로 남긴다.

### H3R RACE_RELATIVE_FEATURES (14개)

각 `__race_centered`는 같은 `race_id` 안에서 source 값에서 race 평균을 뺀 값이다.
각 `__race_percentile`은 같은 race에서 average rank를 사용해
`(rank - 1) / max(count - 1, 1)`로 계산한 값이다. 따라서 race 안의 상대 위치를
표현하며 source의 원래 기간·단위를 이어받는다. source가 null이면 preprocessing의
FIT median/missing 처리에 맡긴다.

| # | 기술명 | source와 계산 | 기간·단위 | 주의점 |
|---:|---|---|---|---|
| 20 | `global_elo_pre__race_centered` | `global_elo_pre - race mean(global_elo_pre)` | legacy H0 과거 Elo, 점수 | 현재 race의 말끼리 중심화. |
| 21 | `distance_elo_pre__race_centered` | `distance_elo_pre - race mean(distance_elo_pre)` | legacy H0 과거 거리 Elo, 점수 | exact-distance 사전 상태를 중심화. |
| 22 | `speed_residual_mean_pre__race_centered` | `speed_residual_mean_pre - race mean(source)` | legacy H1 과거 residual, ms/100m | sparse baseline/null 정책은 H1 source와 동일. |
| 23 | `declared_rating__race_centered` | 선언 rating에서 같은 race 평균을 뺌 | target card, rating 점수 | explicit `레이팅`만; missing rating은 raw fallback 없음. |
| 24 | `declared_burden_kg__race_centered` | 선언 부담중량에서 같은 race 평균을 뺌 | target card, kg | 실제 physical condition으로 해석하지 않고 선언값 상대치로만 사용. |
| 25 | `declared_age__race_centered` | 선언 연령에서 같은 race 평균을 뺌 | target card, 년 | 카드 연령 상대치. |
| 26 | `jockey_history_top3_rate__race_centered` | 기수 history top3 rate에서 같은 race 평균을 뺌 | 과거 ≤ T-2, 비율 | fixed prior smoothing 결과의 상대치. |
| 27 | `global_elo_pre__race_percentile` | global Elo race average rank를 `(rank-1)/max(n-1,1)`로 변환 | legacy H0, [0,1] | ties는 average rank. |
| 28 | `distance_elo_pre__race_percentile` | distance Elo의 race average rank percentile | legacy H0, [0,1] | ties는 average rank. |
| 29 | `speed_residual_mean_pre__race_percentile` | speed residual의 race average rank percentile | legacy H1, [0,1] | 빠르기 방향의 의미는 source residual convention을 유지. |
| 30 | `declared_rating__race_percentile` | 선언 rating의 race average rank percentile | target card, [0,1] | explicit rating only; count 1 race는 denominator 1로 처리. |
| 31 | `declared_burden_kg__race_percentile` | 선언 부담중량의 race average rank percentile | target card, [0,1] | 높은 값은 상대적으로 큰 declared burden을 뜻할 뿐 gate가 아님. |
| 32 | `declared_age__race_percentile` | 선언 연령의 race average rank percentile | target card, [0,1] | race 내 상대 연령. |
| 33 | `jockey_history_top3_rate__race_percentile` | 기수 history top3 rate의 race average rank percentile | 과거 ≤ T-2, [0,1] | current jockey identity가 unknown이면 smoothed baseline에서 계산. |

### H3 availability와 현재 coverage

H3는 **문서 날짜가 race date-2일 이하라는 가정**을 사용하지만 실제 publication
timestamp와 revision history는 검증되지 않았다. 선언된 정보의 availability를
확정된 사실로 표현하지 않는다. 또한 결과 데이터에서 target actual jockey/rating/
weight/grade를 보충하지 않는다.

build report 기준 development(2025)에는 715 races, 6,953 entries/cards가 있다.
`declared_rating`은 5,648건, `declared_grade_number`는 6,874건이 non-null이다.
train에는 36,255 entries 중 card가 36,249건으로 6건의 card missing이 있다.
이는 coverage 요약이며 모델 성능 수치가 아니다. report의 unresolved entry/key와
문서 날짜 지연 행은 source lineage/issues에 남고, 각 선택 카드의 document ID,
file date, line hash를 lineage에 기록한다.

H3와 H3R 각각에서 P family는 공식 top3 binary target, R family는 podium relevance 3/2/1/0을
사용하는 별도 목표다. 같은 49개 legacy state와 H3 변수라도 P와 R의 loss가 다르므로
변수 목록만으로 두 family의 성능이나 우열을 결론내리지 않는다.

## 재현·해석 주의

- 모든 과거 상태는 event가 완전히 끝난 뒤에만 갱신하며 target은 `event_date - 2 days`
  cutoff를 적용한다. date-only source도 이 보수적 cutoff를 따른다.
- 400m 행은 별도 거리 상태로 보존하고 global Elo, starts, recency, rank, time 상태를
  갱신하지 않는다.
- sparse speed baseline은 null로 유지하며, null 여부와 H2 availability unknown은
  preprocessing에서 missing indicator와 함께 처리될 수 있다.
- registry의 aggregation metadata는 계약 문서이고, 실제 의미 판정은 state builder와
  sealed state metadata를 함께 확인해야 한다. 특히 28번과 29번은 위에 적은 구현
  discrepancy를 고정적으로 기록한다.

## 이번 적합에서 확인한 실제 입력 열 수

2026-09-16 실험의 네 fold 모두에서 H3 후보(P/R)는 68개 입력 변수 이름을 받아 결측 표시·regime 인코딩·상수 제거 후 **83개 열**, H3R 후보(P/R)는 82개 이름에서 **105개 열**을 사용했다. 인코딩 후 열 수를 서로 독립적인 원천 변수 수로 해석하지 않는다.
