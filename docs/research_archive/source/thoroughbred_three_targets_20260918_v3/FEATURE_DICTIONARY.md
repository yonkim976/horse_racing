# Thoroughbred three-target V3 feature dictionary

이 문서는 `prepared_context.parquet`에 V3에서 새로 추가한 54개 피처의 실행 계약을 설명한다. 기존 72개 피처는 [V2 feature dictionary](../thoroughbred_win_research_20260918_v2/feature_dictionary.md)를 따르며, 그중 최초 38개 피처의 상세 계약은 [V1 primary feature dictionary](../thoroughbred_model_20260918_v1/feature_dictionary.md)를 참고한다.

## 공통 시점 계약

- `gate`, `condition`, `pace`는 기본 연구에 사용할 수 있는 verified core 후보군이다. 현재 경주의 편성·거리·게이트·부담중량·기수와, 대상 경주일보다 **엄격히 이전 날짜**의 확정 결과만 사용한다.
- 같은 날짜의 모든 카드 피처를 먼저 산출한 뒤 그날 결과를 일괄 갱신한다. 같은 날 앞 경주의 결과도 뒤 경주 피처에 들어가지 않는다.
- 취소·제외 상태인 `cancelled`, `scratched`, `excluded`, `start_excluded`, `race_excluded`, `void`, `void_or_unresulted`, `unmapped_special_98`, `ranked_time_missing_unconfirmed`는 실제 출전 이력 갱신에서 제외한다.
- `historical_event_unverified`와 `late_info_unverified`는 retrospective 비교 전용이며 모델 선택에 사용할 수 없다. 이벤트 날짜가 과거라는 사실과, 당시 실제 공개·수집 가능 시각이 검증되었다는 것은 서로 다른 조건이다.
- 모든 공식 ID는 문자열로 보존한다. 아래 자료형은 `prepared_context.parquet`의 실제 DuckDB 자료형이다.

## 1. `gate`

가용성: `verified_core_strict_prior_date`

게이트 효과는 단순 입상률이 아니다. 각 과거 경주의 V2 사전 Elo로 정확한 Plackett–Luce 3위 이내 포함확률을 계산하고, 실제 3위 이내 질량을 그 기대확률과 비교한다. 동착 경계에서는 남은 입상 슬롯을 동착마에게 균등 배분한다. 따라서 관측·기대 질량은 편성 능력 차이를 일부 통제하지만, 측정되지 않은 편성·전개 요인까지 제거한 인과효과는 아니다.

| 피처 | 자료형·단위 | 의미와 계산 | 기간·축소 | 결측·기본값 |
|---|---|---|---|---|
| `research_gate_position_pct` | DOUBLE, 비율 | `chul_no / field_size_full_card`. 현재 카드에서의 상대 게이트 위치 | 현재 카드 | 유효 게이트가 없으면 NULL. 완성 데이터에서는 전 행 존재 |
| `research_gate_band_code` | BIGINT, 코드 | 상대 게이트 위치가 안쪽이면 0, 중간이면 1, 바깥이면 2. 경계는 각각 `≤1/3`, `≤2/3`, 그 초과 | 현재 카드 | 유효 게이트가 없으면 NULL |
| `research_gate_top3_index_course_3y` | DOUBLE, 지수 | 개최지×게이트 구역의 `관측 top3 질량 / Elo-PL 기대 top3 질량` 축소 지수. 100이 기대와 동일 | 이전 1,095일. 중립 1.0에 기대 슬롯 30을 둔 사전분포로 축소 후 ×100 | 표본이 없으면 100 |
| `research_gate_top3_index_distance_3y` | DOUBLE, 지수 | 개최지×정확거리×게이트 구역 지수 | 이전 1,095일. 위 개최지 지수를 부모로 기대 슬롯 30만큼 축소 | 표본이 없으면 부모 개최지 지수 |
| `research_gate_top3_index_recent_1y` | DOUBLE, 지수 | 최근 개최지×정확거리×게이트 구역 지수 | 이전 365일. 3년 정확거리 지수를 부모로 기대 슬롯 15만큼 축소 | 최근 표본이 없으면 3년 정확거리 지수 |
| `research_gate_recent_minus_long` | DOUBLE, 지수 포인트 | `최근 1년 지수 - 3년 정확거리 지수` | 위 두 지수의 차이 | 부모 fallback이면 0 |
| `research_gate_distance_expected_slots` | DOUBLE, 기대 슬롯 질량 | 해당 개최지×정확거리×게이트 구역에 누적된 Elo-PL 기대 top3 확률의 합 | 이전 1,095일 | 표본이 없으면 0 |
| `research_gate_distance_reliability` | DOUBLE, 0–1 | `expected_slots / (expected_slots + 30)` | 이전 1,095일 | 표본이 없으면 0 |

역사 경주의 게이트 구역은 선언 카드 전체 행 수를 분모로 정한다. PL 기대확률은 실제 출전 상태인 말들을 대상으로 계산한다. DNF·실격은 실제 출전으로 남아 기대 질량을 가지되 관측 top3 질량은 0이다.

## 2. `condition`

가용성: `verified_core_strict_prior_date`

| 피처 | 자료형·단위 | 의미와 계산 | 기간·정규화 | 결측·기본값 |
|---|---|---|---|---|
| `research_condition_distance_starts` | BIGINT, 경주 수 | 말의 현재 정확거리 과거 실제 출전 수. 개최지는 합산 | 전체 엄격 이전 이력 | 신마·거리 첫 출전은 0 |
| `research_condition_distance_wins` | BIGINT, 경주 수 | 현재 정확거리 과거 우승 수 | 전체 엄격 이전 이력 | 이력 없으면 0 |
| `research_condition_distance_top3` | BIGINT, 경주 수 | 현재 정확거리 과거 3위 이내 수 | 전체 엄격 이전 이력 | 이력 없으면 0 |
| `research_condition_distance_top3_rate_smoothed` | DOUBLE, 비율 | `(distance_top3 + 2) / (distance_starts + 8)` | 전체 이력, 고정 Beta형 사전값 2/8 | 이력 없으면 0.25 |
| `research_condition_distance_finish_pct_avg5` | DOUBLE, 0–1 | 현재 정확거리의 최근 유효 착순 최대 5회에서 상대 착순 점수 평균. 상대를 이기면 1, 동착은 0.5, 뒤지면 0 | 정확거리 최근 유효 5회 | 유효 착순이 없으면 NULL |
| `research_condition_jockey_changed` | BIGINT, 0/1 | 현재 기수가 말의 직전 실제 출전 기수와 다른지 여부 | 직전 엄격 이전 출전 | 직전 출전 또는 현재 기수 ID가 없으면 NULL |
| `research_condition_jockey_pair_starts` | BIGINT, 경주 수 | 현재 말×기수 조합의 과거 실제 출전 수 | 전체 엄격 이전 이력 | 조합 첫 출전은 0 |
| `research_condition_jockey_pair_top3_rate_smoothed` | DOUBLE, 비율 | `(말×기수 top3 + 2) / (말×기수 starts + 8)` | 전체 이력, 고정 사전값 2/8 | 조합 첫 출전은 0.25 |
| `research_condition_burden_z5` | DOUBLE, 표준편차 단위 | 현재 부담중량에서 최근 유효 착순 최대 5회의 부담중량 평균을 뺀 뒤 그 5회의 모집단 표준편차로 나눈 값 | 최근 유효 착순 최대 5회, 최소 2회. 과거 중량 표준편차가 0이면 0 | 현재 중량 결측 또는 이력 2회 미만이면 NULL |
| `research_condition_burden_performance_slope5` | DOUBLE, 착순점수/㎏ | 최근 최대 5회에서 `부담중량 x`와 위 상대 착순 점수 `y`의 단순 OLS 기울기 | 유효 이력 3–5회, `Σ(x-x̄)²`로 정규화 | 3회 미만 또는 중량 변화가 없으면 NULL |
| `research_condition_layoff_log1p` | DOUBLE, `log(1+일)` | 현재일과 직전 실제 출전일의 일수 차이에 `log1p` 적용 | 직전 엄격 이전 출전 | 직전 출전이 없으면 NULL |
| `research_condition_short_return_21d` | BIGINT, 0/1 | 출전 간격이 21일 이하인지 | 직전 엄격 이전 출전 | 직전 출전이 없으면 NULL |
| `research_condition_long_layoff_90d` | BIGINT, 0/1 | 출전 간격이 90일 이상인지 | 직전 엄격 이전 출전 | 직전 출전이 없으면 NULL |
| `research_condition_speed_variability_proxy` | DOUBLE, V2 속도지수 포인트 | `최근 5회 최고 속도지수 - 최근 5회 중앙값` | 현재 카드 시점의 V2 엄격 이전 속도 요약 | 두 입력 중 하나라도 없으면 NULL |
| `research_condition_speed_potential_gap` | DOUBLE, V2 속도지수 포인트 | `최근 5회 최고 속도지수 - 직전 속도지수` | 현재 카드 시점의 V2 엄격 이전 속도 요약 | 두 입력 중 하나라도 없으면 NULL |
| `research_condition_speed_last_vs_avg3` | DOUBLE, V2 속도지수 포인트 | `직전 속도지수 - 최근 3회 평균 속도지수` | 현재 카드 시점의 V2 엄격 이전 속도 요약 | 두 입력 중 하나라도 없으면 NULL |

`research_condition_burden_performance_slope5`는 부담중량과 **상대 착순 성과의 과거 관측 관계**다. 기록 초, 속도 자체, 인과적 중량 효과, 최적 부담중량 또는 특정 경주의 유·불리를 직접 추정하지 않는다. 표본이 최대 5회로 작으므로 후보 피처로만 해석한다.

세 속도 차이도 이름 그대로 proxy다. `variability_proxy`는 통계적 분산이 아니며, `potential_gap`은 잠재능력이나 반등을 확정하지 않는다. 최근 최고치와 현재 상태의 간격을 표현하는 연구 변수다.

## 3. `pace`

가용성: `verified_sections_seoul_and_yeongcheon_only_strict_prior_date`

서울의 `verified_source_field` S1F 순위와 영천 첫 개최의 `official_api_verified_first_meeting` S1F 순위만 사용한다. 부산 구간 2,565,960행은 `source_specific_unverified`이므로 사용하지 않는다. 부산 현재 카드에서도 과거 서울·영천에서 확인된 해당 말의 주행 성향만 남을 수 있으며, 부산 자체 구간 이력은 들어가지 않는다.

| 피처 | 자료형·단위 | 의미와 계산 | 기간·정규화 | 결측·기본값 |
|---|---|---|---|---|
| `research_pace_early_pos_pct_avg5` | DOUBLE, 0–1 | 최근 S1F 상대 위치 `((S1F 순위-1)/(전체 카드 행 수-1))` 평균. 0에 가까울수록 앞선 위치 | 검증 구간이 있는 최근 유효 착순 최대 5회 | 이력 없으면 NULL |
| `research_pace_early_pos_pct_std5` | DOUBLE, 비율 표준편차 | 위 S1F 상대 위치의 모집단 표준편차 | 최근 최대 5회, 최소 2회 | 2회 미만이면 NULL |
| `research_pace_late_gain_pct_avg5` | DOUBLE, -1–1 | `(S1F 순위 - 최종 착순)/(전체 카드 행 수-1)` 평균. 양수면 초반보다 최종 순위가 좋아진 관측 | 최근 최대 5회 | 이력 없으면 NULL |
| `research_pace_section_coverage5` | BIGINT, 경주 수 | 최근 창에 들어간 검증 S1F 관측 수 | 최근 최대 5회 | 이력 없으면 0 |
| `research_pace_field_available_count` | BIGINT, 말 수 | 현재 카드에서 `early_pos_pct_avg5`가 있는 말 수. 자기 자신 포함 | 현재 카드 | 아무도 없으면 0 |
| `research_pace_front_runner_count` | BIGINT, 말 수 | 현재 카드에서 `early_pos_pct_avg5 < 0.35`인 말 수. 자기 자신 포함 | 현재 카드, 임계값 0.35 고정 | 아무도 없으면 0 |
| `research_pace_front_competition` | DOUBLE, 경쟁 지수 | 현재 카드의 가용 말에 대해 `Σ max(0, 0.5 - early_pos_pct_avg5)` | 현재 카드 | 가용 말이 없으면 0 |
| `research_pace_self_front_advantage` | DOUBLE, 상대 위치 차이 | `상대마들의 early_pos_pct_avg5 평균 - 자기 값`. 양수면 과거 기준으로 자신이 상대보다 앞선 위치를 취하는 경향 | 현재 카드 상대 비교 | 자기 이력 또는 가용 상대가 없으면 NULL |

이 그룹은 과거 통과순위 성향과 현재 편성 내 선행 경쟁을 표현한다. 실제 현재 경주의 전개, 출발 성공, 진로방해 또는 확정 선행 여부를 직접 관측한 값은 아니다.

## 4. `historical_event_unverified`

가용성: `retrospective_only_selection_ineligible_posting_time_unverified`

모든 값은 이벤트 날짜가 대상 경주일보다 앞서도록 제한했다. 그러나 원천의 게시 시각과 당시 예측 시점에서의 이용 가능성이 검증되지 않아 기본 core나 모델 선택에 합치지 않는다.

| 피처 | 자료형·단위 | 의미와 계산 | 기간 | 결측·기본값 |
|---|---|---|---|---|
| `research_unverified_training_days_3d` | BIGINT, 서로 다른 일수 | 말의 일반 조교 이벤트가 있었던 서로 다른 날짜 수 | 이전 3일 | 집계상 없으면 0. 원천 미수집과 실제 무조교를 구분하지 못함 |
| `research_unverified_training_days_7d` | BIGINT, 서로 다른 일수 | 위와 동일 | 이전 7일 | 집계상 없으면 0 |
| `research_unverified_training_days_14d` | BIGINT, 서로 다른 일수 | 위와 동일 | 이전 14일 | 집계상 없으면 0 |
| `research_unverified_training_days_28d` | BIGINT, 서로 다른 일수 | 위와 동일 | 이전 28일 | 집계상 없으면 0 |
| `research_unverified_training_seconds_7d` | DOUBLE, 초 | 일반 조교 `duration_seconds` 합 | 이전 7일 | 집계상 없으면 0. 원천의 음수·24시간 초과 문제 때문에 retrospective 전용 |
| `research_unverified_training_seconds_28d` | DOUBLE, 초 | 일반 조교 `duration_seconds` 합 | 이전 28일 | 집계상 없으면 0 |
| `research_unverified_start_training_events_28d` | BIGINT, 이벤트 수 | 출발조교 이벤트 수 | 이전 28일 | 집계상 없으면 0 |
| `research_unverified_trial_count180d` | DOUBLE, 정수값 경주 수 | 허용된 신원 연결의 주행심사·연습 출전 수 | 이전 180일 | 없으면 0. 저장 자료형은 DOUBLE이나 값은 정수 |
| `research_unverified_trial_days_since_last` | DOUBLE, 일 | 가장 최근 허용 주행심사일 이후 경과일 | 전체 엄격 이전 심사 이력 | 심사 이력이 없으면 NULL |
| `research_unverified_trial_speed_last` | DOUBLE, m/s | 가장 최근 유효 심사의 `distance_m / (finish_time_ms/1000)` | 전체 엄격 이전 심사 중 10–20m/s 범위의 최신값 | 유효 시간이 없으면 NULL |

주행심사는 `confirmed`+`confirmed_historical_text`와, 감사 근거가 있는 `confirmed_official_id`, `linked_profile_signature`, `linked_race_age_corroborated`, `linked_training_date_corroborated`, `linked_training_disambiguated`만 허용한다. 그래도 원천 대부분이 `retrospective_only`이므로 운영 입력으로 간주하지 않는다.

## 5. `late_info_unverified`

가용성: `retrospective_only_selection_ineligible_current_condition_availability_unverified`

이 그룹은 당일 마체중·날씨·주로처럼 결과 데이터에는 넓게 존재하지만 실제 예측 시점 공개 계약이 확정되지 않은 정보를 격리한다. 과거 마체중 이력도 같은 원천 계열의 가용성 제약을 명확히 하기 위해 이 그룹에 둔다.

| 피처 | 자료형·단위 | 의미와 계산 | 기간·정규화 | 결측·기본값 |
|---|---|---|---|---|
| `research_late_current_weight_kg` | DOUBLE, ㎏ | 현재 경주의 관측 마체중 | 현재 경주 당일 정보 | 없으면 NULL |
| `research_late_current_weight_delta_kg` | DOUBLE, ㎏ | 원천이 제공한 현재 경주 마체중 증감 | 현재 경주 당일 정보 | 없으면 NULL |
| `research_late_hist_weight_last_kg` | DOUBLE, ㎏ | 직전 실제 출전의 유효 마체중 | 엄격 이전 실제 출전, 250–700㎏ 값만 허용 | 이력 없으면 NULL |
| `research_late_hist_weight_median5_kg` | DOUBLE, ㎏ | 최근 유효 마체중 최대 5회의 중앙값 | 엄격 이전 실제 출전 최대 5회 | 이력 없으면 NULL |
| `research_late_hist_weight_mad5_kg` | DOUBLE, ㎏ | 최근 최대 5회 마체중의 MAD: `median(|weight-median|)` | 엄격 이전 실제 출전 최대 5회 | 이력 없으면 NULL. 한 번만 있어도 0 |
| `research_late_current_vs_hist_median5_kg` | DOUBLE, ㎏ | `현재 마체중 - 과거 5회 중앙값` | 현재값과 엄격 이전 이력 결합 | 어느 한쪽이 없으면 NULL |
| `research_late_current_weight_robust_z` | DOUBLE, 강건 척도 단위 | 위 차이를 `max(1㎏, 1.4826×MAD)`로 나눈 값 | 현재값과 과거 최대 5회 | 어느 한쪽이 없으면 NULL |
| `research_late_current_weight_outside_normal` | BIGINT, 0/1 | 현재-중앙값 절대차가 `max(5㎏, 2.5×MAD)`보다 큰지 | 현재값과 과거 최대 5회 | 어느 한쪽이 없으면 NULL |
| `research_late_track_moisture_pct` | DOUBLE, % | 현재 경주의 원천 주로 함수율 | 현재 경주 당일 정보 | 없으면 NULL |
| `research_late_track_wet_flag` | BIGINT, 0/1 | `track_raw`가 `포화` 또는 `불량`으로 시작하는지 | 현재 경주 당일 정보 | 원문이 비면 NULL |
| `research_late_weather_rain_flag` | BIGINT, 0/1 | `weather_raw`에 `비`가 포함되는지 | 현재 경주 당일 정보 | 원문이 비면 NULL |
| `research_late_condition_available` | BIGINT, 0/1 | 주로 원문·날씨 원문·함수율·현재 마체중 중 하나 이상이 있는지 | 현재 경주 당일 정보 | 모두 없으면 0 |

마체중 중앙값·MAD·이탈 플래그는 관측된 과거 범위와 현재값의 차이를 표현할 뿐이다. 건강 상태, 컨디션 이상, 불리 사건, 인과효과 또는 말별 **최적체중**을 판정하지 않는다. 특히 이 그룹은 retrospective-only이므로 미래 운영에서 같은 시점에 확보할 수 있다는 증거도 아니다.

## 사용 프로필

| 프로필 | 포함 그룹 | 해석 |
|---|---|---|
| verified core | 기존 `base72` + `gate` + `condition` + `pace` | 엄격 이전 날짜 결과와 현재 카드 정보만 사용한 연구 후보 |
| historical retrospective | verified core + `historical_event_unverified` | 조교·심사 이벤트의 조건부 상한 진단. 모델 선택 부적격 |
| late retrospective | verified core + `late_info_unverified` | 당일 체중·날씨·주로의 사후 조건부 진단. 모델 선택 부적격 |
| full retrospective | verified core + 두 unverified 그룹 | 가용성 위험을 모두 포함한 참고 상한. 운영 성능 또는 live 재현성으로 표현 금지 |

모래 보충·정비일, 검증된 심판 trouble 사건, 부산 구간 의미를 직접 나타내는 신뢰 가능한 열은 통합 원천에 없다. 이 세 종류는 피처로 만들지 않았다. 각 피처의 실제 결측률과 범위는 [feature_coverage.csv](feature_coverage.csv), 원천 채택·제외 근거와 보존 검증은 [FEATURE_AUDIT.md](FEATURE_AUDIT.md)에 기록되어 있다.
