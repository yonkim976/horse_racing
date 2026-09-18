# 제주마 v5 추가 변수와 현재 사용 범위

2026-09-16. 기존 H3의 68개 변수에 편성·초반 경쟁 18개, 과거 수행 변화 22개를 더한 총 108개 입력 이름을 비교했다. 결측 표시와 시대 구분을 변환한 실제 학습 열 수는 실험 보고서에 별도로 기록한다.

기존 변수의 정의는 [기존 변수 카탈로그](/Users/kimyongjin/Desktop/horse_racing/docs/JEJU_NATIVE_VARIABLE_CATALOG_2026-09-16.md)와 [H3 보고서](/Users/kimyongjin/Desktop/horse_racing/docs/JEJU_NATIVE_H3_MODEL_REPORT_2026-09-16.md)를 함께 참조한다. 아래 관측 수는 2025년 출전 행 6,953개 중 유효 숫자가 있는 행의 수이며 정확도나 독립 표본 수가 아니다.

## 편성·초반 경쟁: 18개

| 변수 | 정의·기간·단위 | 유효 행 / 6,953 |
|---|---|---:|
| `rival_global_elo_mean` | 현재 출전 상대(자신 제외)의 T-2 사전 global Elo 평균, Elo 점수 | 6,953 |
| `rival_global_elo_std` | 현재 상대 사전 global Elo 모집단 표준편차, Elo 점수 | 6,953 |
| `rival_global_elo_max` | 현재 상대 사전 global Elo 최댓값, Elo 점수 | 6,953 |
| `rival_global_elo_gap` | 자신의 사전 global Elo - 상대 최댓값, Elo 점수 | 6,953 |
| `rival_distance_elo_mean` | 현재 거리에서 상대들의 사전 distance Elo 평균, Elo 점수 | 6,953 |
| `rival_distance_elo_max` | 현재 거리에서 상대들의 사전 distance Elo 최댓값, Elo 점수 | 6,953 |
| `rival_distance_elo_gap` | 자신의 distance Elo - 상대 distance Elo 최댓값 | 6,953 |
| `declared_horse_number_fraction` | (선언 출주번호-1)/(현재 필드에서 확인된 최대 선언번호-1). 취소로 빈 번호 보존. 물리 게이트 확정 아님. 번호 미확인/최대1이면 결측 | 6,953 |
| `historical_early_front_rate` | 자신의 T-2까지 과거 유효 초반 통과순위 중 3위 이내 비율. 거리 혼합, 관측없으면 결측 | 6,657 |
| `rival_early_pressure_count` | 초반 상위3 비율>=0.5인 현재 상대 수. 이력 알려진 상대만. 전부 미확인하면 결측 | 6,950 |
| `rival_early_pressure_mean` | 현재 상대의 과거 초반 상위3 비율 평균. 알려진 상대만 | 6,950 |
| `field_early_ability_percentile` | 현재 필드의 초반 상위3 비율 중 자기 이하 비율. 동률 포함 ECDF, 0~1 | 6,657 |
| `jockey_early_front_rate` | 선언 기수의 T-2까지 초반 상위3 비율. 당시까지 알려진 이름-ID만 연결, 다중ID 불명확 시 결측 | 6,953 |
| `current_minus_previous_elo` | 현재 자기 global Elo - 최근 과거 출전 당시 자기 사전 Elo. 최근 변화 대용치 | 6,657 |
| `previous_rival_elo_mean_3` | 최근 과거3회 출전의 상대 사전 global Elo 평균을 다시 평균. 없으면 결측 | 6,657 |
| `current_vs_previous_rival_elo` | 현재 상대 평균 global Elo - 최근3회 상대 평균. 양수면 이전보다 강한 편성 추정 | 6,657 |
| `lower_number_early_pressure_count` | 자신보다 낮은 선언 출주번호이고 과거 초반 상위3 비율>=0.5인 상대 수. 물리 안쪽 확정 아님 | 6,950 |
| `higher_number_early_pressure_count` | 자신보다 높은 선언 출주번호이고 과거 초반 상위3 비율>=0.5인 상대 수. 물리 바깥쪽 확정 아님 | 6,950 |

## 과거 수행 변화: 22개

| 변수 | 정의·기간·단위 | 유효 행 / 6,953 |
|---|---|---:|
| `last_burden_kg` | T-2까지 과거 출전 중 마지막 유효 실제 부담중량 kg | 6,657 |
| `current_minus_last_burden_kg` | 현재 선언 부담중량 - 과거 마지막 유효 실제 부담중량 kg | 6,657 |
| `last_body_weight_kg` | T-2까지 과거 출전의 마지막 유효 마체중 kg. 당일 체중 아님 | 6,629 |
| `body_weight_delta_kg` | 과거 마지막 두 유효 마체중의 차이 kg. 현재 경주의 증감 아님 | 6,330 |
| `body_weight_trend_3` | 과거 최근 최대3개 유효 체중의 (마지막-첫값)/(관측수-1), kg/관측 | 6,330 |
| `last_early_rank` | 직전 출전의 유효 S1F 통과순위. 1..당시 출전수만 유효 | 6,657 |
| `last_late_rank` | 직전 출전의 결승200m 전 G1F 통과순위. 막판200m 구간 속도 순위와 다름 | 6,657 |
| `last_early_late_gain` | 직전 S1F 통과순위-G1F 통과순위. 양수는 두 지점 사이 순위 상승 | 6,657 |
| `closing_speed_quality_mean_3` | 최근3회 출전의 최종200m 구간시간 상대속도 평균. 같은 과거 경주의 정상/유효 구간시간에서 빠를수록1, 평균동률, 관측2개 이상 | 6,657 |
| `late_rank_mean_3` | 최근3회 출전의 유효 G1F 통과순위 평균 | 6,657 |
| `early_late_gain_mean_3` | 최근3회 출전의 유효 S1F순위-G1F순위 평균 | 6,657 |
| `early_rank_percentile_3` | 최근3회 출전의 1-(S1F순위-1)/(당시출전수-1) 평균 | 6,657 |
| `late_rank_percentile_3` | 최근3회 출전의 1-(G1F순위-1)/(당시출전수-1) 평균 | 6,657 |
| `progression_last3_vs_prev3` | 최근3회 상대결승점수 평균 - 그전3회 평균. 6회 출전 필요. 상대결승점수=1-(착순-1)/(출전수-1). DQ/DNF 점수 결측 | 5,443 |
| `best_last5_performance` | 최근5회 출전 중 정상 상대결승점수 최댓값. 한 번 부진했다고 이전 좋은 수행을 삭제하지 않음 | 6,657 |
| `poor_last_but_good_late` | 직전 정상 상대결승점수<=0.25 이면서 최종200m 상대속도>=0.75면1. 둘다알려진비해당0, 미확인 결측. 포기 의도 라벨 아님 | 6,656 |
| `wet_performance_mean` | 과거 함수율10~100% 경주의 정상 상대결승점수 평균. 거리/등급 혼합 관측요약, 젖은주로 인과효과 아님 | 6,250 |
| `wet_performance_count` | wet_performance_mean에 사용한 유효 정상 관측 수 | 6,953 |
| `dry_performance_mean` | 과거 함수율1~9%(건조+양호)의 정상 상대결승점수 평균. 현재 날씨 입력 아님 | 6,514 |
| `dry_performance_count` | dry_performance_mean에 사용한 관측 수. 함수율0/미확인 제외 | 6,953 |
| `history_time_minus_same_race_median` | 최근3회 과거 정상 유효 결승시간 - 같은 과거 경주의 유효시간 중앙값 평균, ms. 유효2마리 이상. 주로뿐 아니라 편성/전개도 섞인 상대기록 | 6,657 |
| `jockey_changed` | 현재 선언 기수 이름과 직전 실제 기수 이름이 다르면1. 어느 이름이든 미확인 시 결측. 현재 실제 결과 기수 대입 없음 | 6,657 |

## 해석과 아직 관측하지 못하는 부분

- 모든 과거 결과는 T−2까지 사용한다. 현재 부담중량·기수·출주번호는 복원된 선언 출마표를 사용한다. 기수 이름과 ID의 연결도 당시까지의 관측만 쓴다.
- 과거 마체중 증감은 이번 경주의 당일 증감이 아니다. 당일 체중과 기수 변경은 실제 공지·수집 시각이 있는 별도 입력으로 추가해야 한다.
- 초반 상위 3위 빈도는 선행력 대용치이며, 항상 단독 선행한다는 의미가 아니다. 출주번호도 물리 게이트 위치와 취소 후 배치를 확정한 값이 아니다.
- 최종 200m 구간 속도와 결승 200m 전 통과순위를 구분한다. 낮은 최종 착순과 좋은 막판 속도가 함께 관측됐는지를 표시해 반등 가능성의 단서를 남긴다.
- 주로의 건습 변수는 원문에 명시된 함수율만 쓴다. 1–9%를 dry, 10% 이상을 wet으로 묶은 실험 분류이며, 공식 건조·양호 등 전체 분류와 동일하지 않다. 비나 맑음이라는 글자만으로 함수율을 추정하지 않는다.
- 같은 과거 경주 내 시간 차이는 주로·상대·전개가 섞인 상대 수행이다. 순수한 날씨 보정 기록으로 해석하면 안 된다.
- 발전 변수는 최근 성적 변화의 대용치다. 생리적 성장 자체나 기수의 포기 의도를 직접 측정하지 않는다. 심판보고·진료·조교·영상으로 확인하는 별도 관측이 필요하다.
- 현재 연구 대상은 실제 출전마로 확정된 필드다. 주간 출마표 시점에는 아직 모르는 취소 여부와 편성 변동을 별도 재현해야 하므로 수요일 실전 정확도로 곧바로 해석할 수 없다.

## 이번 후보에 실제로 사용한 기존 68개 입력 이름

신규 40개와 합쳐 R_FORM의 108개 입력 이름을 이룬다. 이전 상대변환 14개(H3R)는 이번 후보에 포함하지 않는다. 아래 각 항목의 상세 정의와 시점은 위 기존 카탈로그의 해당 행을 참조한다.

- `global_elo_pre`: 기존 변수 카탈로그 참조
- `distance_elo_pre`: 현재 정확한 거리의 distance Elo 사전값. 400m도 별도 거리 상태로 보존
- `elo_uncertainty_pre`: `1/sqrt(1 + starts)`로 만든 Elo 불확실성 대용치
- `starts_pre`: 시작 횟수. 정상 순위 1–89 및 started code 91/92 포함
- `normal_completed_pre`: 정상 finish(순위 1–89)의 완료 횟수
- `wins_pre`: 정상 finish 순위 1 횟수
- `top3_pre`: 정상 finish 순위 1–3 횟수
- `days_since_previous_start`: 최근 시작일로부터 현재 경주일까지의 날짜 차이
- `days_since_previous_normal_finish`: 최근 정상 finish일로부터 현재 경주일까지의 날짜 차이
- `distance_starts_pre`: 현재 정확한 거리에서의 시작 횟수
- `distance_normal_completed_pre`: 현재 정확한 거리에서 정상 finish한 횟수
- `distance_wins_pre`: 현재 정확한 거리에서 순위 1 횟수
- `distance_top3_pre`: 현재 정확한 거리에서 순위 1–3 횟수
- `recent_finish_score_5_mean`: 최근 정상 finish 최대 5회의 `(field_size-position)/(field_size-1)` 평균. 1두 필드는 1로 처리
- `recent_top3_rate_5`: 최근 정상 finish 최대 5회 중 순위 3 이내 비율
- `performance_variability_pre`: 최근 finish score 최대 5회의 population 표준편차
- `speed_time_per_100m_mean_pre`: 말의 같은 거리 usable `time_per_100m` 평균
- `speed_residual_mean_pre`: 기존 변수 카탈로그 참조
- `speed_residual_std_pre`: 같은 거리 residual의 population 표준편차
- `speed_observation_count_pre`: 같은 거리 usable finish time 관측 횟수
- `normal_usable_count_pre`: 구현상 global 비-400m 정상 usable time 누적 횟수
- `distance_normal_usable_count_pre`: 현재 정확한 거리에서의 정상 usable time 횟수
- `section_s1f_ms_mean_pre`: 같은 거리 과거 초반 200m 구간 S1F 시간 평균
- `section_s1f210_ms_mean_pre`: 1110/1610m source가 제공하는 초반 210m S1F210 시간 평균
- `section_g1f_ms_mean_pre`: 같은 거리 과거 결승선 전 200m G1F 시간 평균
- `section_g3f_ms_mean_pre`: 같은 거리 과거 결승선 전 600m G3F 시간 평균
- `distance_m`: 기존 변수 카탈로그 참조
- `field_size`: 기존 변수 카탈로그 참조
- `regime`: target date가 속한 era: `pre_2018_08_31`, `2018_08_31_2022_12_31`, `2023_01_01_2025_12_27`, `post_2025_12_28`
- `training_28d_count`: 일반 훈련 event 수
- `training_28d_duration_seconds`: 일반 훈련 event의 duration 합
- `training_28d_canter_count`: 일반 훈련의 canter 횟수 합
- `training_28d_gallop_count`: 일반 훈련의 gallop 횟수 합
- `training_28d_coverage_unknown`: 28일 훈련 원천 coverage를 완전히 확인할 수 없는지 표시
- `training_28d_observed_any`: dedup 훈련 event가 있었는지
- `start_training_28d_count`: start training event 수
- `start_training_28d_coverage_unknown`: start training coverage 불확실성 flag
- `start_training_28d_observed_any`: dedup start training event 존재 여부
- `medical_90d_count`: 의료 event 수
- `medical_90d_coverage_unknown`: 90일 의료 coverage 불확실성 flag
- `medical_90d_observed_any`: dedup 의료 event 존재 여부
- `trial_count_pre`: 과거 시험/조교 event 수
- `trial_last_valid_time_ms_pre`: 가장 최근 유효 trial finish time
- `trial_coverage_unknown`: trial 원천 coverage 불확실성 flag
- `trial_observed_any`: trial event가 하나라도 존재하는지
- `weight_last_kg_pre`: dedup된 과거 체중 event 중 가장 최근 체중
- `weight_count_pre`: dedup된 체중 event 수
- `weight_coverage_unknown`: 체중 원천 coverage 불확실성 flag
- `weight_observed_any`: 체중 event 존재 여부
- `card_observed`: T-2 이하 문서에서 entry와 일치하는 선언카드를 선택했는지
- `declared_horse_number`: 선언카드에 적힌 마번/출전 번호
- `declared_age`: 선언카드의 말 연령
- `declared_female`: 성별이 `암`인지 나타내는 flag
- `declared_gelded`: 성별이 `거`인지 나타내는 flag
- `declared_burden_kg`: 선언 부담중량
- `declared_rating`: 헤더가 명시한 `레이팅` 열의 숫자
- `declared_grade_number`: `출전/출주: 제 N등급`에서 읽은 등급 번호
- `declared_jockey_allowance_kg`: 기수 표기의 `(-N)` 감량 allowance
- `jockey_history_starts`: target 기수 이름에 과거 단일 official ID가 매핑된 경우 그 ID의 과거 시작 수
- `jockey_history_win_rate`: 기수 과거 승률의 고정 prior smoothing `(win + 2) / (starts + 20)`
- `jockey_history_top3_rate`: 기수 과거 입상률 `(top3 + 6) / (starts + 20)`
- `trainer_history_starts`: target 조교사 이름에 과거 단일 official ID가 매핑된 경우 과거 시작 수
- `trainer_history_win_rate`: 조교사 과거 승률 `(win + 2) / (starts + 20)`
- `trainer_history_top3_rate`: 조교사 과거 입상률 `(top3 + 6) / (starts + 20)`
- `horse_jockey_history_starts`: 해당 horse–jockey official ID pair의 과거 시작 수
- `horse_jockey_history_top3_rate`: pair 입상률 `(pair_top3 + 3) / (pair_starts + 10)`
- `jockey_identity_history_known`: target 이름이 과거 관측에서 정확히 하나의 official jockey ID로 확인됐는지
- `trainer_identity_history_known`: target 이름이 과거 관측에서 정확히 하나의 official trainer ID로 확인됐는지
