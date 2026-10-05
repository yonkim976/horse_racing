# HY_R_FORM 실제 입력 감사와 데이터 분석부터 다시 시작하는 계획

2026-09-28. 보관 중인 기준 모델 번들을 직접 열어 확인했다. 신규 학습·모델 교체·기존 자료 삭제는 수행하지 않았다. 최근 실험 후보는 기준 모델과 구분한다. 이 문서의 A/B/C 분석 계획은 당시 목표를 기록한 것이며, 새 연구 목표는 [우승축·착순·동반 후보 문서](<JEJU_PREDICTION_OBJECTIVES_2026-09-28.md>)가 대체한다. 아래 모델 구조·입력 감사는 기존 HY_R_FORM에 대한 사실 기록으로 유지한다.

## 1. 확인한 모델 구조

- 번들: `data/research/jeju_native_transition_holdout_v13_20260916/bundles/frozen_2026__HY_R_FORM.pkl`
- SHA-256: `f1b9531e068cab51dff906961d56f51c7c4b0e5a86f378c9aa1f03f159ec9706`
- 말 선택: LambdaRank 계열 두 시드 앙상블. A 한 마리 입상 선택과 B 세 마리 선택에 같은 말 점수와 결합분포를 사용한다.
- 순서: 별도 JointTop3MLP 두 시드. B가 선택한 세 마리 안의 C 순서를 정한다. A/B/C 평가 목표 세 개가 모두 독립된 세 모델이라는 뜻은 아니다.
- 선언 입력 이름: 선택108개, 순서68개. 순서68개는 선택108개의 앞부분과 정확히 같다.
- 전처리 후: 선택154열 = 수치99 + 결측표시53 + 시대2. 순서83열 = 수치59 + 결측표시22 + 시대2.
- 두 모델 모두8개 원입력을 상수로 제외했다. 선언 입력 개수, 변환 후 입력 개수, 실제 트리 분기에 사용한 개수는 서로 다르다.
- 선택 모델의 시드17/43에서 분기에 사용된 변환 열은77/95개다. 이 수치는 변수의 인과효과 또는 독립적인 추가 예측력 측정치가 아니다.
- 과거 이력은 원칙적으로T−2까지. 복원 출마표 날짜가 실제 최초 공개·정정 시각을 완전히 입증하지는 않는다.

## 2. 입력 묶음

| 묶음 | 선택용 선언 수 | 순서용 선언 수 |
|---|---:|---:|
|과거 성적·Elo·출전 간격|16|16|
|시간·구간기록|10|10|
|경주 조건|3|3|
|조교·진료·심사·과거 체중|20|20|
|출마표·기수·조교사 이력|19|19|
|편성·초반 경쟁|18|0|
|중량·체중·전개·수행 변화|22|0|
|합계|108|68|

## 3. 전체108개 명세

정의는 기존 변수 카탈로그와 문맥 변수 문서를 연결했다. 번호·명칭·모델 포함 여부와 전처리 보존 여부는 저장 번들에서 직접 추출했다. 정의 자체의 원천 재감사는 다음 단계이며, 아래는 현재 모델이 받도록 설계된 의미다.

`section_s1f210_ms_mean_pre`는 기존 연구 데이터셋에서210m로 분리한 항목이다. 이후 원천 정리 문서의200m 정의와 함께 재대조할 대상이며, 이 표만으로 실제 측정거리를 새로 확정하지 않는다. 전체 주파시간의100m 환산값은 초반100m 구간기록이 아니다.

### 과거 성적·Elo·출전 간격

|번호|변수|뜻·계산|순서 모델에도 포함|선택 모델 전처리|
|---:|---|---|---|---|
|1|`global_elo_pre`|전체 비-400m 정상 결승마의 global Elo 사전값. 정상 순위끼리 pairwise 갱신, K=20, 동률은 0.5|예|수치 보존|
|2|`distance_elo_pre`|현재 정확한 거리의 distance Elo 사전값. 400m도 별도 거리 상태로 보존|예|수치 보존|
|3|`elo_uncertainty_pre`|`1/sqrt(1 + starts)`로 만든 Elo 불확실성 대용치|예|수치 보존|
|4|`starts_pre`|시작 횟수. 정상 순위 1–89 및 started code 91/92 포함|예|수치 보존|
|5|`normal_completed_pre`|정상 finish(순위 1–89)의 완료 횟수|예|수치 보존|
|6|`wins_pre`|정상 finish 순위 1 횟수|예|수치 보존|
|7|`top3_pre`|정상 finish 순위 1–3 횟수|예|수치 보존|
|8|`days_since_previous_start`|최근 시작일로부터 현재 경주일까지의 날짜 차이|예|수치 보존|
|9|`days_since_previous_normal_finish`|최근 정상 finish일로부터 현재 경주일까지의 날짜 차이|예|수치 보존|
|10|`distance_starts_pre`|현재 정확한 거리에서의 시작 횟수|예|수치 보존|
|11|`distance_normal_completed_pre`|현재 정확한 거리에서 정상 finish한 횟수|예|수치 보존|
|12|`distance_wins_pre`|현재 정확한 거리에서 순위 1 횟수|예|수치 보존|
|13|`distance_top3_pre`|현재 정확한 거리에서 순위 1–3 횟수|예|수치 보존|
|14|`recent_finish_score_5_mean`|최근 정상 finish 최대 5회의 `(field_size-position)/(field_size-1)` 평균. 1두 필드는 1로 처리|예|수치 보존|
|15|`recent_top3_rate_5`|최근 정상 finish 최대 5회 중 순위 3 이내 비율|예|수치 보존|
|16|`performance_variability_pre`|최근 finish score 최대 5회의 population 표준편차|예|수치 보존|
### 시간·구간기록

|번호|변수|뜻·계산|순서 모델에도 포함|선택 모델 전처리|
|---:|---|---|---|---|
|17|`speed_time_per_100m_mean_pre`|말의 같은 거리 usable `time_per_100m` 평균|예|수치 보존|
|18|`speed_residual_mean_pre`|말의 같은 거리 usable 시간이 `(거리, era)` baseline에서 얼마나 벗어나는지의 평균|예|수치 보존|
|19|`speed_residual_std_pre`|같은 거리 residual의 population 표준편차|예|수치 보존|
|20|`speed_observation_count_pre`|같은 거리 usable finish time 관측 횟수|예|수치 보존|
|21|`normal_usable_count_pre`|구현상 global 비-400m 정상 usable time 누적 횟수|예|수치 보존|
|22|`distance_normal_usable_count_pre`|현재 정확한 거리에서의 정상 usable time 횟수|예|수치 보존|
|23|`section_s1f_ms_mean_pre`|같은 거리 과거 초반 200m 구간 S1F 시간 평균|예|수치 보존|
|24|`section_s1f210_ms_mean_pre`|1110/1610m source가 제공하는 초반 210m S1F210 시간 평균|예|수치 보존|
|25|`section_g1f_ms_mean_pre`|같은 거리 과거 결승선 전 200m G1F 시간 평균|예|수치 보존|
|26|`section_g3f_ms_mean_pre`|같은 거리 과거 결승선 전 600m G3F 시간 평균|예|수치 보존|
### 경주 조건

|번호|변수|뜻·계산|순서 모델에도 포함|선택 모델 전처리|
|---:|---|---|---|---|
|27|`distance_m`|현재 경주의 명시된 경주 거리|예|수치 보존|
|28|`field_size`|현재 경주에 포함된 starter 수|예|수치 보존|
|29|`regime`|target date가 속한 era: `pre_2018_08_31`, `2018_08_31_2022_12_31`, `2023_01_01_2025_12_27`, `post_2025_12_28`|예|범주 변환|
### 조교·진료·심사·과거 체중

|번호|변수|뜻·계산|순서 모델에도 포함|선택 모델 전처리|
|---:|---|---|---|---|
|30|`training_28d_count`|일반 훈련 event 수|예|수치 보존|
|31|`training_28d_duration_seconds`|일반 훈련 event의 duration 합|예|수치 보존|
|32|`training_28d_canter_count`|일반 훈련의 canter 횟수 합|예|상수 제외|
|33|`training_28d_gallop_count`|일반 훈련의 gallop 횟수 합|예|상수 제외|
|34|`training_28d_coverage_unknown`|28일 훈련 원천 coverage를 완전히 확인할 수 없는지 표시|예|상수 제외|
|35|`training_28d_observed_any`|dedup 훈련 event가 있었는지|예|상수 제외|
|36|`start_training_28d_count`|start training event 수|예|수치 보존|
|37|`start_training_28d_coverage_unknown`|start training coverage 불확실성 flag|예|상수 제외|
|38|`start_training_28d_observed_any`|dedup start training event 존재 여부|예|수치 보존|
|39|`medical_90d_count`|의료 event 수|예|수치 보존|
|40|`medical_90d_coverage_unknown`|90일 의료 coverage 불확실성 flag|예|상수 제외|
|41|`medical_90d_observed_any`|dedup 의료 event 존재 여부|예|수치 보존|
|42|`trial_count_pre`|과거 시험/조교 event 수|예|수치 보존|
|43|`trial_last_valid_time_ms_pre`|가장 최근 유효 trial finish time|예|수치 보존|
|44|`trial_coverage_unknown`|trial 원천 coverage 불확실성 flag|예|상수 제외|
|45|`trial_observed_any`|trial event가 하나라도 존재하는지|예|수치 보존|
|46|`weight_last_kg_pre`|dedup된 과거 체중 event 중 가장 최근 체중|예|수치 보존|
|47|`weight_count_pre`|dedup된 체중 event 수|예|수치 보존|
|48|`weight_coverage_unknown`|체중 원천 coverage 불확실성 flag|예|상수 제외|
|49|`weight_observed_any`|체중 event 존재 여부|예|수치 보존|
### 출마표·기수·조교사 이력

|번호|변수|뜻·계산|순서 모델에도 포함|선택 모델 전처리|
|---:|---|---|---|---|
|50|`card_observed`|T-2 이하 문서에서 entry와 일치하는 선언카드를 선택했는지|예|수치 보존|
|51|`declared_horse_number`|선언카드에 적힌 마번/출전 번호|예|수치 보존|
|52|`declared_age`|선언카드의 말 연령|예|수치 보존|
|53|`declared_female`|성별이 `암`인지 나타내는 flag|예|수치 보존|
|54|`declared_gelded`|성별이 `거`인지 나타내는 flag|예|수치 보존|
|55|`declared_burden_kg`|선언 부담중량|예|수치 보존|
|56|`declared_rating`|헤더가 명시한 `레이팅` 열의 숫자|예|수치 보존|
|57|`declared_grade_number`|`출전/출주: 제 N등급`에서 읽은 등급 번호|예|수치 보존|
|58|`declared_jockey_allowance_kg`|기수 표기의 `(-N)` 감량 allowance|예|수치 보존|
|59|`jockey_history_starts`|target 기수 이름에 과거 단일 official ID가 매핑된 경우 그 ID의 과거 시작 수|예|수치 보존|
|60|`jockey_history_win_rate`|기수 과거 승률의 고정 prior smoothing `(win + 2) / (starts + 20)`|예|수치 보존|
|61|`jockey_history_top3_rate`|기수 과거 입상률 `(top3 + 6) / (starts + 20)`|예|수치 보존|
|62|`trainer_history_starts`|target 조교사 이름에 과거 단일 official ID가 매핑된 경우 과거 시작 수|예|수치 보존|
|63|`trainer_history_win_rate`|조교사 과거 승률 `(win + 2) / (starts + 20)`|예|수치 보존|
|64|`trainer_history_top3_rate`|조교사 과거 입상률 `(top3 + 6) / (starts + 20)`|예|수치 보존|
|65|`horse_jockey_history_starts`|해당 horse–jockey official ID pair의 과거 시작 수|예|수치 보존|
|66|`horse_jockey_history_top3_rate`|pair 입상률 `(pair_top3 + 3) / (pair_starts + 10)`|예|수치 보존|
|67|`jockey_identity_history_known`|target 이름이 과거 관측에서 정확히 하나의 official jockey ID로 확인됐는지|예|수치 보존|
|68|`trainer_identity_history_known`|target 이름이 과거 관측에서 정확히 하나의 official trainer ID로 확인됐는지|예|수치 보존|
### 편성·초반 경쟁

|번호|변수|뜻·계산|순서 모델에도 포함|선택 모델 전처리|
|---:|---|---|---|---|
|69|`rival_global_elo_mean`|현재 출전 상대(자신 제외)의 T-2 사전 global Elo 평균, Elo 점수|아니오|수치 보존|
|70|`rival_global_elo_std`|현재 상대 사전 global Elo 모집단 표준편차, Elo 점수|아니오|수치 보존|
|71|`rival_global_elo_max`|현재 상대 사전 global Elo 최댓값, Elo 점수|아니오|수치 보존|
|72|`rival_global_elo_gap`|자신의 사전 global Elo - 상대 최댓값, Elo 점수|아니오|수치 보존|
|73|`rival_distance_elo_mean`|현재 거리에서 상대들의 사전 distance Elo 평균, Elo 점수|아니오|수치 보존|
|74|`rival_distance_elo_max`|현재 거리에서 상대들의 사전 distance Elo 최댓값, Elo 점수|아니오|수치 보존|
|75|`rival_distance_elo_gap`|자신의 distance Elo - 상대 distance Elo 최댓값|아니오|수치 보존|
|76|`declared_horse_number_fraction`|(선언 출주번호-1)/(현재 필드에서 확인된 최대 선언번호-1). 취소로 빈 번호 보존. 물리 게이트 확정 아님. 번호 미확인/최대1이면 결측|아니오|수치 보존|
|77|`historical_early_front_rate`|자신의 T-2까지 과거 유효 초반 통과순위 중 3위 이내 비율. 거리 혼합, 관측없으면 결측|아니오|수치 보존|
|78|`rival_early_pressure_count`|초반 상위3 비율>=0.5인 현재 상대 수. 이력 알려진 상대만. 전부 미확인하면 결측|아니오|수치 보존|
|79|`rival_early_pressure_mean`|현재 상대의 과거 초반 상위3 비율 평균. 알려진 상대만|아니오|수치 보존|
|80|`field_early_ability_percentile`|현재 필드의 초반 상위3 비율 중 자기 이하 비율. 동률 포함 ECDF, 0~1|아니오|수치 보존|
|81|`jockey_early_front_rate`|선언 기수의 T-2까지 초반 상위3 비율. 당시까지 알려진 이름-ID만 연결, 다중ID 불명확 시 결측|아니오|수치 보존|
|82|`current_minus_previous_elo`|현재 자기 global Elo - 최근 과거 출전 당시 자기 사전 Elo. 최근 변화 대용치|아니오|수치 보존|
|83|`previous_rival_elo_mean_3`|최근 과거3회 출전의 상대 사전 global Elo 평균을 다시 평균. 없으면 결측|아니오|수치 보존|
|84|`current_vs_previous_rival_elo`|현재 상대 평균 global Elo - 최근3회 상대 평균. 양수면 이전보다 강한 편성 추정|아니오|수치 보존|
|85|`lower_number_early_pressure_count`|자신보다 낮은 선언 출주번호이고 과거 초반 상위3 비율>=0.5인 상대 수. 물리 안쪽 확정 아님|아니오|수치 보존|
|86|`higher_number_early_pressure_count`|자신보다 높은 선언 출주번호이고 과거 초반 상위3 비율>=0.5인 상대 수. 물리 바깥쪽 확정 아님|아니오|수치 보존|
### 중량·체중·전개·수행 변화

|번호|변수|뜻·계산|순서 모델에도 포함|선택 모델 전처리|
|---:|---|---|---|---|
|87|`last_burden_kg`|T-2까지 과거 출전 중 마지막 유효 실제 부담중량 kg|아니오|수치 보존|
|88|`current_minus_last_burden_kg`|현재 선언 부담중량 - 과거 마지막 유효 실제 부담중량 kg|아니오|수치 보존|
|89|`last_body_weight_kg`|T-2까지 과거 출전의 마지막 유효 마체중 kg. 당일 체중 아님|아니오|수치 보존|
|90|`body_weight_delta_kg`|과거 마지막 두 유효 마체중의 차이 kg. 현재 경주의 증감 아님|아니오|수치 보존|
|91|`body_weight_trend_3`|과거 최근 최대3개 유효 체중의 (마지막-첫값)/(관측수-1), kg/관측|아니오|수치 보존|
|92|`last_early_rank`|직전 출전의 유효 S1F 통과순위. 1..당시 출전수만 유효|아니오|수치 보존|
|93|`last_late_rank`|직전 출전의 결승200m 전 G1F 통과순위. 막판200m 구간 속도 순위와 다름|아니오|수치 보존|
|94|`last_early_late_gain`|직전 S1F 통과순위-G1F 통과순위. 양수는 두 지점 사이 순위 상승|아니오|수치 보존|
|95|`closing_speed_quality_mean_3`|최근3회 출전의 최종200m 구간시간 상대속도 평균. 같은 과거 경주의 정상/유효 구간시간에서 빠를수록1, 평균동률, 관측2개 이상|아니오|수치 보존|
|96|`late_rank_mean_3`|최근3회 출전의 유효 G1F 통과순위 평균|아니오|수치 보존|
|97|`early_late_gain_mean_3`|최근3회 출전의 유효 S1F순위-G1F순위 평균|아니오|수치 보존|
|98|`early_rank_percentile_3`|최근3회 출전의 1-(S1F순위-1)/(당시출전수-1) 평균|아니오|수치 보존|
|99|`late_rank_percentile_3`|최근3회 출전의 1-(G1F순위-1)/(당시출전수-1) 평균|아니오|수치 보존|
|100|`progression_last3_vs_prev3`|최근3회 상대결승점수 평균 - 그전3회 평균. 6회 출전 필요. 상대결승점수=1-(착순-1)/(출전수-1). DQ/DNF 점수 결측|아니오|수치 보존|
|101|`best_last5_performance`|최근5회 출전 중 정상 상대결승점수 최댓값. 한 번 부진했다고 이전 좋은 수행을 삭제하지 않음|아니오|수치 보존|
|102|`poor_last_but_good_late`|직전 정상 상대결승점수<=0.25 이면서 최종200m 상대속도>=0.75면1. 둘다알려진비해당0, 미확인 결측. 포기 의도 라벨 아님|아니오|수치 보존|
|103|`wet_performance_mean`|과거 함수율10~100% 경주의 정상 상대결승점수 평균. 거리/등급 혼합 관측요약, 젖은주로 인과효과 아님|아니오|수치 보존|
|104|`wet_performance_count`|wet_performance_mean에 사용한 유효 정상 관측 수|아니오|수치 보존|
|105|`dry_performance_mean`|과거 함수율1~9%(건조+양호)의 정상 상대결승점수 평균. 현재 날씨 입력 아님|아니오|수치 보존|
|106|`dry_performance_count`|dry_performance_mean에 사용한 관측 수. 함수율0/미확인 제외|아니오|수치 보존|
|107|`history_time_minus_same_race_median`|최근3회 과거 정상 유효 결승시간 - 같은 과거 경주의 유효시간 중앙값 평균, ms. 유효2마리 이상. 주로뿐 아니라 편성/전개도 섞인 상대기록|아니오|수치 보존|
|108|`jockey_changed`|현재 선언 기수 이름과 직전 실제 기수 이름이 다르면1. 어느 이름이든 미확인 시 결측. 현재 실제 결과 기수 대입 없음|아니오|수치 보존|

## 4. 감사에서 확인한 중요한 한계

- **구보·습보 횟수:** 이름은 선언돼 있지만 학습자료에서 상수였으며 결측표시를 포함해 실제 입력에서 제외됐다. 실제 말들의 조교가 모두 같다는 뜻은 아니며 수집·파싱·집계 원인을 확인해야 한다.
- **진료:** 90일 진료 건수·관측 여부 중심이다. 병명, 부위, 심각도, 치료와 예방의 구분, 회복 여부를 충분히 표현하지 않는다.
- **조교:** 누가 조교했는지, 말 자신의 평소보다 얼마나 달라졌는지, 영상상 여유는 현재 입력에서 충분히 표현하지 않는다.
- **체중:** 과거 마체중과 그 변화다. 이번 경주 직전 발표한 체중을 기본 모델 입력으로 쓰지 않는다.
- **주로:** 거리·시대 기준 잔차, 건습 조건별 과거 성적, 같은 경주 상대 기록 등이 있다. 공식tempo를 이용한 정교한 주로 보정·당일 주로 예측이 채택됐다는 뜻은 아니다.
- **전개:** 초반상위3비율, 통과순위 변화, 상대종반속도 등 대용치다. 실제 외곽 주행거리·진로막힘·모래반응·기수 의도·잔여체력을 직접 측정하지 않는다.
- **기수:** `jockey_early_front_rate`는 선두1위가 아니라 초반상위3위 빈도다. 기수와 말의 능력·배정 효과가 섞인다.
- **성장:** 최근3회와 이전3회의 상대착순 차이 등을 사용한다. 생리적 성장이나 컨디션 회복의 직접 측정이 아니다.
- **혈통·영상·예시장·상세 심판 사건:** 기본108/68입력에는 없다. 관련 연구 자료·실험 후보가 존재하는 것과 기준모델 채택을 구분한다.
- **순서 모델:** 추가40개 문맥·변화 입력은 이번 기준의 순서 모델에 직접 들어가지 않는다. 선택된 세 마리가 바뀌면서 C에 간접 영향은 있을 수 있다.

## 5. 데이터 분석 우선 재설계에 대한 판단

현 단계에서는 새 모델 후보를 계속 늘리는 것보다 데이터의 의미·품질·관계를 먼저 정리하는 방향이 타당하다. 효과가 생길 경로는 잘못된 값/단위/연결 수정, 중요한 상태의 누락 보완, 평균으로 뭉개진 조건 차이 분리, 신뢰할 수 없는 신호 축소다.

다만 선행 분석 자체가 적중률 상승을 보장하지 않는다. 관측으로 확인할 수 없는 요소, 작은 표본, 시간에 따른 변화가 남는다. 데이터를 더 정직하게 정리해 기존의 과대평가가 줄면 보고되는 성능이 낮아질 수도 있다. 모델이 상호작용을 이미 학습하는 경우도 있어 모든 상관관계를 수작업 규칙으로 바꿀 필요는 없다.

### 제안하는 작업 순서

| 단계 | 할 일 | 완료 산출물 |
|---|---|---|
|1. 분석 기준·평가 절차 고정|A/B/C 정의, 출마표/직전 예측 시점,9월12일 자료 상한, 과거→미래 분할|분석·검증 규칙|
|2. 원천·품질 감사|제주마 구분, 말/경주 키, 구간 단위와 시간종류, 공개시점, 결측·상수·오연결·중복|자료별 원천·기간·결측률·표본수·문제 목록|
|3. 분석용 경주/말 이력 정리|현재 조건·과거 관측·사건·정답 분리, 날짜별 재현, 설명 가능한 파생값|원천에 연결되는 분석용 데이터셋|
|4. 핵심 가설 분석|주로×거리 기록, 초반부담×종반수행, 편성×게이트, 중량·체중·주기, 조교·진료·기수·신마|조건별 표본수·차이·불확실성·반례|
|5. 변수 설계|가설별 직접관측/대용치/추정 분리, 과거창·정규화·결측 규칙, 중복 검토|채택/보류/제외 이유가 있는 변수사전|
|6. 제한된 모델 비교|단순 기준부터 시작해 정보 묶음별 추가, A/B/C 각각 확인|묶음의 추가 가치와 연도·시드 안정성|
|7. 전개 구조 검토|중간 전개 예측이 실제로 맞는지 먼저 평가, 도움이 될 때만 최종모델 연결|전개 예측·최종 적중 각각의 검증|

처음에는 모든 변수를 상호 조합하기보다 (1)기록·구간 의미, (2)주로·거리 기준, (3)초반부담과 종반수행, (4)심판 사건과 다음 출전 변화부터 다룬다. 조교·진료 자료가 상수/결측으로 사라진 원인 점검은 원천 감사에 포함한다.

기존모델과 원본·검증 코드는 비교 기준으로 보존한다. 기존 가설 분석에서 재현 가능한 부분은 재사용하고, 현재 원천과 정의가 달라진 부분을 다시 검증한다. 이번 문서에서 새 학습은 시작하지 않았다.

### 선행 분석에도 적용할 검증 원칙

- 결과와의 관계를 보고 변수·경계를 선택하는 분석도 모델 개발의 일부다. 전체 결과를 먼저 탐색하고 같은 자료에서 성능을 평가하면 과대평가할 수 있다. 전처리·변수선택은 과거 학습 구간에서 정하고 이후 구간에 적용한다. [scikit-learn 공식 누수 안내](https://scikit-learn.org/stable/common_pitfalls.html#data-leakage)
- 시간 분할은 경주 단위·날짜 단위로 한다. 같은 경주의 말들을 서로 다른 학습/평가 집합으로 쪼개지 않는다. 경주일 반복도 불확실성에 반영한다. [시간 순서 검증 안내](https://scikit-learn.org/stable/modules/cross_validation.html#time-series-split)
- 이미 여러 번 확인한2024~2026 평가 기간은 분할을 바꿔도 새 독립시험이 되지 않는다. 현재 자료 안에서는 과거 구간별 선택→이후 구간 비교의 후향 개발 평가로 명시한다.
- 단일변수 유의성만으로 채택·제외하지 않는다. 작은 집단의 우연, 여러 비교, 중복 신호와 상호작용을 함께 본다. 분석상 연관성과 최종 A/B/C 예측 기여는 별도로 평가한다.

## 연결 문서

- [사람의 분석 방식 정리](<JEJU_HUMAN_ANALYSIS_FRAMEWORK_2026-09-28.md>)
- [기존 변수 카탈로그](<JEJU_NATIVE_VARIABLE_CATALOG_2026-09-16.md>)
- [편성·변화 변수 정의](<JEJU_NATIVE_CONTEXT_VARIABLES_2026-09-16.md>)
- [저장 번들 입력·전처리·분기 사용 목록](</Users/kimyongjin/Desktop/horse_racing/data/research/jeju_model_input_audit_20260928/bundle_input_inventory.json>)
