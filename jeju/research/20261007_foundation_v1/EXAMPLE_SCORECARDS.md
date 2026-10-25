# 실제 말별 평가표 예시 6두

대상일 2026-09-19, 이력 절단일 **2026-09-17 포함**. 1·2·6경주에서 관측 과거 출전수가 가장 적은 말과 많은 말을 각각 선택했고 동률은 말 ID로 정했다. 대상 경주의 착순·시간을 선택이나 평가 계산에 사용하지 않았다. 거리·등급·중량 등 이번 조건은 사후 결과 원장에서 재구성했으며 T−2 공개 검증 전이다.

모든 시간은 **주로 보정하지 않은 동일거리 원기록**이다. 서로 다른 거리의 시간을 직접 비교하지 않는다. 최신 마명과 2026 고정 표시 나이를 썼다. 관측 경주 출전수는 평생 경력이나 신마 판정이 아니다. NULL은 능력 0이 아니다. 확률·추천 조합은 아직 산출하지 않았다.

| 말 / ID | 표시 나이 | 목표 거리 | 관측 출전 / 동일거리 유효수 | 직전 동일거리 s | 최근 ≤5 평균 s (n) | 편차 s | 365일 최고 s |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 제주소리 / 3107406 | 3 | 900 | 0 / 0 | NULL | NULL (0) | NULL | NULL |
| 가문의여신 / 3107451 | 3 | 900 | 6 / 5 | 76.20 | 76.12 (5) | 1.34 | 74.20 |
| 붉은노을 / 3107838 | 3 | 1000 | 4 / 0 | NULL | NULL (0) | NULL | NULL |
| 글라가게 / 3103957 | 5 | 1000 | 34 / 18 | 82.30 | 83.42 (5) | 0.61 | 82.30 |
| 드림매직 / 3103294 | 5 | 1610 | 20 / 2 | 131.70 | 132.60 (2) | 0.90 | 131.70 |
| 새벽바람 / 3014773 | 15 | 1610 | 123 / 5 | 132.30 | 134.60 (5) | 2.51 | 132.30 |

## 각 말의 근거와 해석

### 제주소리 (3107406)

관측 경주 이력은 없지만 심사 2행이 있다. 경주 이력 0을 미출전 확정이나 능력 부족으로 바꾸지 않는다. 심사 거리 미확정이므로 심사 67.8초를 900m 경주 기록에 섞지 않는다.

| 평가 열 | 값 | n | 단위 |
| --- | --- | --- | --- |
| days_since_last_observed_start | NULL | 0 | days |
| same_distance_latest_minus_prior3_mean_s | NULL | 0 | seconds |
| same_distance_second_best_gap365_s | NULL | 0 | seconds |
| last_historical_body_weight_kg | NULL | 0 | kg |
| last_minus_previous_body_weight_kg | NULL | 0 | kg |
| last_historical_carried_weight_kg | NULL | 0 | kg |
| last_observed_event_age | NULL | 0 | source age |
| s1f_recent5_mean_s | NULL | 0 | seconds |
| g3f_recent5_mean_s | NULL | 0 | seconds |
| g1f_recent5_mean_s | NULL | 0 | seconds |
| early_rank_fraction_recent5 | NULL | 0 | fraction |
| early_to_g1f_order_gain_recent5 | NULL | 0 | positions |

365일 최고: 관측 없음(NULL).

주행심사: 관측 2행, 최근 2026-09-03, 원문 전체시간 67.80초. 거리 비교 불가 상태로 별도 보존.

### 가문의여신 (3107451)

최근 평균과 최고가 구분된다. 365일 최고와 두 번째 기록 차는 1.1초다. 이 차이만으로 최고가 이상치 또는 반복 가능한 능력이라고 판정하지 않는다.

| 평가 열 | 값 | n | 단위 |
| --- | --- | --- | --- |
| days_since_last_observed_start | 15 | 1 | days |
| same_distance_latest_minus_prior3_mean_s | 0.30 | 4 | seconds |
| same_distance_second_best_gap365_s | 1.10 | 2 | seconds |
| last_historical_body_weight_kg | 272 | 1 | kg |
| last_minus_previous_body_weight_kg | -3 | 2 | kg |
| last_historical_carried_weight_kg | 55.00 | 1 | kg |
| last_observed_event_age | 3 | 1 | source age |
| s1f_recent5_mean_s | 17.80 | 5 | seconds |
| g3f_recent5_mean_s | 50.36 | 5 | seconds |
| g1f_recent5_mean_s | 17.88 | 5 | seconds |
| early_rank_fraction_recent5 | 0.6444 | 5 | fraction |
| early_to_g1f_order_gain_recent5 | 0 | 5 | positions |

365일 최고 원천: API record 188607, 2026-06-12, 900m, 제6등급, 부담중량 55.0kg, 체중 273kg, 주로 `건조 (2%)`.

주행심사: 관측 2행, 최근 2025-12-31, 원문 전체시간 68.70초. 거리 비교 불가 상태로 별도 보존.

### 붉은노을 (3107838)

관측 출전 4회가 있어도 이번 1000m 유효 기록은 없다. 다른 거리 기록을 평균속도로 환산해 빈 능력값을 채우지 않았다. 전체 무이력마와 별도 결측 사유다.

| 평가 열 | 값 | n | 단위 |
| --- | --- | --- | --- |
| days_since_last_observed_start | 42 | 1 | days |
| same_distance_latest_minus_prior3_mean_s | NULL | 0 | seconds |
| same_distance_second_best_gap365_s | NULL | 0 | seconds |
| last_historical_body_weight_kg | 280 | 1 | kg |
| last_minus_previous_body_weight_kg | -7 | 2 | kg |
| last_historical_carried_weight_kg | 55.00 | 1 | kg |
| last_observed_event_age | 3 | 1 | source age |
| s1f_recent5_mean_s | NULL | 0 | seconds |
| g3f_recent5_mean_s | NULL | 0 | seconds |
| g1f_recent5_mean_s | NULL | 0 | seconds |
| early_rank_fraction_recent5 | NULL | 0 | fraction |
| early_to_g1f_order_gain_recent5 | NULL | 0 | positions |

365일 최고: 관측 없음(NULL).

주행심사: 관측 2행, 최근 2026-07-23, 원문 전체시간 64.30초. 거리 비교 불가 상태로 별도 보존.

### 글라가게 (3103957)

최근 동일거리 평균 83.42초와 최고 82.3초를 따로 보존했다. 최고 당시 주로 포화 17%이므로 시간 단축을 순수 능력 향상으로 해석할 수 없다.

| 평가 열 | 값 | n | 단위 |
| --- | --- | --- | --- |
| days_since_last_observed_start | 14 | 1 | days |
| same_distance_latest_minus_prior3_mean_s | -1.33 | 4 | seconds |
| same_distance_second_best_gap365_s | 1.00 | 2 | seconds |
| last_historical_body_weight_kg | 261 | 1 | kg |
| last_minus_previous_body_weight_kg | 3 | 2 | kg |
| last_historical_carried_weight_kg | 52.00 | 1 | kg |
| last_observed_event_age | 5 | 1 | source age |
| s1f_recent5_mean_s | 17.66 | 5 | seconds |
| g3f_recent5_mean_s | 49.32 | 5 | seconds |
| g1f_recent5_mean_s | 16.88 | 5 | seconds |
| early_rank_fraction_recent5 | 0.5563 | 5 | fraction |
| early_to_g1f_order_gain_recent5 | -0.60 | 5 | positions |

365일 최고 원천: API record 186678, 2026-09-05, 1000m, 제5등급, 부담중량 52.0kg, 체중 261kg, 주로 `포화 (17%)`.

주행심사: 관측 2행, 최근 2026-08-13, 원문 전체시간 65.70초. 거리 비교 불가 상태로 별도 보존.

### 드림매직 (3103294)

전체 관측 출전 20회지만 1610m는 2회다. 편차와 최고 기록에 대한 근거가 얇고, 마지막 관측 출전 이후 119일이라는 최근성도 함께 봐야 한다.

| 평가 열 | 값 | n | 단위 |
| --- | --- | --- | --- |
| days_since_last_observed_start | 119 | 1 | days |
| same_distance_latest_minus_prior3_mean_s | -1.80 | 2 | seconds |
| same_distance_second_best_gap365_s | 1.80 | 2 | seconds |
| last_historical_body_weight_kg | 310 | 1 | kg |
| last_minus_previous_body_weight_kg | 13 | 2 | kg |
| last_historical_carried_weight_kg | 54.50 | 1 | kg |
| last_observed_event_age | 5 | 1 | source age |
| s1f_recent5_mean_s | 17.95 | 2 | seconds |
| g3f_recent5_mean_s | 48.25 | 2 | seconds |
| g1f_recent5_mean_s | 16.25 | 2 | seconds |
| early_rank_fraction_recent5 | 0.8182 | 2 | fraction |
| early_to_g1f_order_gain_recent5 | 7 | 2 | positions |

365일 최고 원천: API record 189626, 2026-04-25, 1610m, 제OPEN, 부담중량 54.5kg, 체중 297kg, 주로 `건조 (5%)`.

주행심사: 관측 2행, 최근 2025-04-24, 원문 전체시간 67.00초. 거리 비교 불가 상태로 별도 보존.

### 새벽바람 (3014773)

관측 출전이 123회여도 1610m 유효 기록은 5회다. 동일거리 최근 평균 134.6초와 최고 132.3초의 차이가 크다. 위치 변화는 전개 이력일 뿐 이번에도 앞선 또는 후방이라고 고정하지 않는다.

| 평가 열 | 값 | n | 단위 |
| --- | --- | --- | --- |
| days_since_last_observed_start | 35 | 1 | days |
| same_distance_latest_minus_prior3_mean_s | -4.30 | 4 | seconds |
| same_distance_second_best_gap365_s | 3.80 | 2 | seconds |
| last_historical_body_weight_kg | 282 | 1 | kg |
| last_minus_previous_body_weight_kg | -5 | 2 | kg |
| last_historical_carried_weight_kg | 55.00 | 1 | kg |
| last_observed_event_age | 15 | 1 | source age |
| s1f_recent5_mean_s | 17.42 | 5 | seconds |
| g3f_recent5_mean_s | 49.70 | 5 | seconds |
| g1f_recent5_mean_s | 16.78 | 5 | seconds |
| early_rank_fraction_recent5 | 0.1354 | 5 | fraction |
| early_to_g1f_order_gain_recent5 | -3.80 | 5 | positions |

365일 최고 원천: API record 187372, 2026-08-15, 1610m, 제1등급, 부담중량 55.0kg, 체중 282kg, 주로 `다습 (10%)`.

주행심사: 관측 8행, 최근 2025-04-03, 원문 전체시간 64.10초. 거리 비교 불가 상태로 별도 보존.

전체 원천 ID·payload SHA·계산식은 `example_scorecards.json`과 `SCORECARD_SPEC.md`에 있다. 이 값들은 평가표의 계산 검토용이며 말 간 최종 순위나 입상확률이 아니다.
