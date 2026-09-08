# Feature 카탈로그 (자동 생성)

이 문서는 `horse-racing write-feature-catalog`가 feature 레지스트리에서 생성한다.
직접 수정하지 말고 각 그룹 모듈(`src/horse_racing/analysis/features/`)의
`FeatureSpec`을 수정한 뒤 재생성한다. 설계 배경은
[MODELING_ROADMAP](MODELING_ROADMAP.md) §4를 본다.

공통 원칙: 모든 feature는 예측 시점(`prediction_at`) 이전에 공개된 값만 사용한다.
과거 이력은 예측 대상 경주일 **이전** 데이터만 집계하며, 당일 이벤트(훈련·진료)는
공개 시점이 불확실해 보수적으로 제외한다 (T3 실측 후 완화 검토).

생성일: 2026-09-04 · 등록 feature: 217개


## A. 경주 컨텍스트

| feature | 설명 | 원천 | lookback | null 정책 | 누수 위험 |
|---|---|---|---|---|---|
| `distance_m` | 경주 거리(m) | races.distance_m | - | null 유지 | low |
| `starters` | 출주 두수(정상 완주 기준) | 라벨 정책에서 계산 | - | null 유지 | low |
| `race_number` | 당일 경주 번호 | races.race_number | - | null 유지 | low |
| `meet_code` | 경마장 코드 (1 서울 / 2 제주 / 3 부산경남) | racecourses | - | null 유지 | low |
| `burden_type` | 부담구별 (범주) | races.burden_type | - | null 유지 | low |
| `age_condition` | 연령 조건 (범주) | races.age_condition | - | null 유지 | low |
| `sex_condition` | 성별 조건 (범주) | races.sex_condition | - | null 유지 | low |
| `weather_planned` | 경주 전 계획 날씨 (범주) | races.weather_planned (T1) | - | null 유지 | low |
| `track_condition_planned` | 경주 전 계획 주로상태 (범주) | races.track_condition_planned | - | null 유지 | low |
| `track_moisture_percent_planned` | 경주 전 계획 주로 함수율 | races (T1) | - | null 유지 | low |
| `race_month` | 경주 월 (계절성) | races.race_date_local | - | null 유지 | low |
| `race_weekday` | 경주 요일 (월=1 ~ 일=7) | races.race_date_local | - | null 유지 | low |
| `grade_mix` | 등급 혼합구분 (국산/혼합/제주/None) | races.grade → analysis.grades.parse_race_grade | - | null 유지 | low |
| `grade_tier` | 등급 숫자 (1~6, OPEN은 null) | races.grade → parse_race_grade | - | null 유지 | low |
| `grade_is_open` | OPEN 경주 여부 | races.grade → parse_race_grade | - | null 유지 | low |
| `burden_type_clean` | 허용 사전으로 정규화한 부담구별 | races.burden_type, grade_raw 접미사 | - | 복원 불가 시 기타/미상 | low |
| `operation_era` | 운영 시기(pre_covid/covid/post_covid) | race_date_local | - | null 유지 | low |
| `source_era` | 데이터 원천 시기(text_backfill/api_full) | race_date_local | - | null 유지 | low |
| `jeju_breed_regime` | 더러브렛/제주마/한라마/미상 구분 | meet_code + grade_raw + race_date_local | - | null 유지 | low |
| `grade_system` | 더러브렛·제주 구형·제주 레이팅 등급체계 구분 | meet_code + grade_raw + race_date_local | - | null 유지 | low |

## B. 출전 정적

| feature | 설명 | 원천 | lookback | null 정책 | 누수 위험 |
|---|---|---|---|---|---|
| `horse_number` | 공식 출발번호/게이트 번호 (기존 특성명 호환 유지) | race_entries.gate_number (결측 시 horse_number) | - | null 유지 | low |
| `horse_number_pct` | 출발번호 / 출주 두수 (경주 내 상대 위치) | 파생 | - | null 유지 | low |
| `carried_weight_kg` | 부담중량(kg) | race_entries.carried_weight_kg | - | null 유지 | low |
| `carried_weight_rel` | 부담중량 − 경주 평균 | 파생 | - | null 유지 | low |
| `load_ratio_pct` | 부담중량/마체중 비율(%) | race_entries.carried_weight_kg / body_weight_kg | - | 마체중 결측·0이면 null | 당일 마체중 사용. day_before_18 정책에서는 자동 제외 |
| `rating` | 출전표 레이팅 (경주 전 공개) | race_entries.rating | - | null 유지 (결측 12행) | low |
| `body_weight_kg` | 당일 마체중(kg) — start_minus_30m 정책 전용 | race_entries.body_weight_kg | - | null 유지 | 당일 공개. day_before_18 정책에서는 컬럼 자체가 제거됨 |
| `body_weight_change_kg` | 공식 체중 증감(kg) — start_minus_30m 정책 전용 | race_entries.body_weight_change_kg | - | null 유지 | 당일 공개 |
| `horse_age_months` | 경주일 기준 말 나이(월) | horses.birth_date (불변 속성) | - | null 유지 | low |
| `horse_sex` | 성별 (수/암/거세) | horses.sex | - | null 유지 | med — 현재 스냅샷 값. 거세 전 과거 경주에 소급될 수 있음 |
| `horse_origin` | 산지 (범주) | horses.origin_country (불변 속성) | - | null 유지 | low |

## C. 말 Form

| feature | 설명 | 원천 | lookback | null 정책 | 누수 위험 |
|---|---|---|---|---|---|
| `career_starts` | 과거 정상 완주 횟수 (0이면 신마) | past_results (race_results + races, 정상 착순 1~89) | career | 0 (신마) | low — 그룹 내 행 인덱스(현재 경주 미포함) |
| `is_debut` | 신마 여부 (career_starts==0, 0/1) | past_results (race_results + races, 정상 착순 1~89) | career | career_starts에서 파생 (결측 없음) | low |
| `finish_pos_last` | 직전 경주 착순 | past_results (race_results + races, 정상 착순 1~89) | 직전 1경주 | 과거 경주 없으면 null | low — shift(1)로 현재 경주 제외 |
| `form_recent3_pct` | 최근 3경주 착순 백분위 평균. (pos−1)/(starters−1), 0=1착 | past_results (race_results + races, 정상 착순 1~89) | 최근 3경주 | 과거 없으면 null. 1~2경주면 있는 것만 평균. starters=1은 0 | low — rolling 후 shift(1) |
| `form_recent5_pct` | 최근 5경주 착순 백분위 평균. (pos−1)/(starters−1), 0=1착 | past_results (race_results + races, 정상 착순 1~89) | 최근 5경주 | 과거 없으면 null. 1~4경주면 있는 것만 평균. starters=1은 0 | low — rolling 후 shift(1) |
| `form_recent5_median_pct` | 최근 5경주 착순 백분위 중앙값 (극단적 하위 착순 영향 완화) | past_results (race_results + races, 정상 착순 1~89) | 최근 5경주 | 과거 없으면 null | low — rolling 후 shift(1) |
| `form_recent5_best_pct` | 최근 5경주 최고 착순 백분위 (작을수록 좋음) | past_results (race_results + races, 정상 착순 1~89) | 최근 5경주 | 과거 없으면 null | low — rolling 후 shift(1) |
| `top3_rate_recent5` | 최근 5경주 3위 내 비율 | past_results (race_results + races, 정상 착순 1~89) | 최근 5경주 | 과거 없으면 null | low — rolling 후 shift(1) |
| `win_rate_career` | 과거 전체 승률 (finish_position==1) | past_results (race_results + races, 정상 착순 1~89) | career | 과거 0경주면 null | low — cum_sum 후 shift(1) |
| `top3_rate_career` | 과거 전체 복승률 (finish_position<=3) | past_results (race_results + races, 정상 착순 1~89) | career | 과거 0경주면 null | low — cum_sum 후 shift(1) |
| `days_since_last_race` | 직전 경주 후 경과일 | past_results (race_results + races, 정상 착순 1~89) | 직전 1경주 | 과거 경주 없으면 null | low — race_date shift(1) |
| `long_layoff` | 장기 휴양 복귀 (직전 경주 후 90일 초과, 0/1) | past_results (race_results + races, 정상 착순 1~89) | 직전 1경주 | 과거 경주 없으면 null | low |
| `speed_avg_mps_3` | 최근 3경주 평균 속도(m/s). 경마장별 대역 밖은 null | past_results (race_results + races, 정상 착순 1~89) | 최근 3경주 | 유효 속도 없으면 null. 서울·부산 12~18, 제주 10~13.5 m/s 밖 제외 | low — rolling 후 shift(1) |
| `speed_avg_mps_5` | 최근 5경주 평균 속도(m/s). 경마장별 대역 밖은 null | past_results (race_results + races, 정상 착순 1~89) | 최근 5경주 | 유효 속도 없으면 null. 서울·부산 12~18, 제주 10~13.5 m/s 밖 제외 | low — rolling 후 shift(1) |
| `speed_best_mps_5` | 최근 5경주 최고 속도(m/s). 경마장별 대역 밖은 null | past_results (race_results + races, 정상 착순 1~89) | 최근 5경주 | 유효 속도 없으면 null. 서울·부산 12~18, 제주 10~13.5 m/s 밖 제외 | low — rolling 후 shift(1) |
| `speed_rel_avg5` | 최근 5경주의 해당 경주 중앙속도 대비 상대속도 평균 | past_results (race_results + races, 정상 착순 1~89) | 최근 5경주 | 유효 기록 없으면 null | low — 완료된 과거 경주 내부 비교 후 shift(1) |
| `speed_rel_median5` | 최근 5경주 상대속도 중앙값 (비경쟁 종료의 느린 기록 영향 완화) | past_results (race_results + races, 정상 착순 1~89) | 최근 5경주 | 유효 기록 없으면 null | low — rolling 후 shift(1) |
| `speed_rel_best5` | 최근 5경주 최고 경주 내 상대속도 | past_results (race_results + races, 정상 착순 1~89) | 최근 5경주 | 유효 기록 없으면 null | low — rolling 후 shift(1) |
| `distance_change_m` | 현재 거리 − 직전 출전 거리(m) | past_results (race_results + races, 정상 착순 1~89) | 직전 1경주 | 과거 경주 없으면 null | low — 현재 출전표 거리와 직전 과거 거리만 사용 |
| `dist_band_starts` | 현재 경주 거리 ±200m 이내 과거 출주 수 | past_results (race_results + races, 정상 착순 1~89) | career, 현재 거리 ±200m | 0 | low — horse_id join 후 race_date < 현재만 집계 |
| `dist_band_top3_rate` | 현재 경주 거리 ±200m 이내 과거 복승률 | past_results (race_results + races, 정상 착순 1~89) | career, 현재 거리 ±200m | 해당 거리대 0경주면 null | low — horse_id join 후 race_date < 현재만 집계 |
| `exact_distance_starts` | 현재와 정확히 같은 거리의 과거 출주 수 | past_results (race_results + races, 정상 착순 1~89) | career, 동일 거리 | 0 | low — horse_id join 후 race_date < 현재만 집계 |
| `exact_distance_top3_rate` | 현재와 정확히 같은 거리의 과거 3위 내 비율 | past_results (race_results + races, 정상 착순 1~89) | career, 동일 거리 | 동일 거리 0경주면 null | low — horse_id join 후 race_date < 현재만 집계 |
| `meet_starts` | 현재 경마장 과거 출주 수 | past_results (race_results + races, 정상 착순 1~89) | career, 동일 meet_code | 0 | low — horse_id join 후 race_date < 현재만 집계 |
| `meet_win_rate` | 현재 경마장 과거 승률 | past_results (race_results + races, 정상 착순 1~89) | career, 동일 meet_code | 해당 경마장 0경주면 null | low — horse_id join 후 race_date < 현재만 집계 |

## B+. 생애주기·출전주기

| feature | 설명 | 원천 | lookback | null 정책 | 누수 위험 |
|---|---|---|---|---|---|
| `age_regime_stage` | 경마장 체계별 연령 단계(서울·부산 2~7+, 제주 2~8+) | horse_age_months + meet_code | - | 나이 또는 경마장 결측 시 unknown | low |
| `age_pre_peak_months` | 체계별 기준 전성기까지 남은 월수(서울·부산 42개월, 제주 54개월) | horse_age_months + meet_code | - | 나이 또는 경마장 결측 시 null | low |
| `age_post_peak_months` | 체계별 기준 전성기 이후 경과 월수 | horse_age_months + meet_code | - | 나이 또는 경마장 결측 시 null | low |
| `rest_cycle_bin` | 직전 출전 후 경과일의 비선형 구간 | days_since_last_race | - | 신마는 debut | low |
| `rest_log_days` | log(1 + 직전 출전 후 경과일) | days_since_last_race | - | 신마는 null | low |
| `rest_excess_41d` | 41일을 초과한 휴양 일수 | days_since_last_race | - | 신마는 null | low |
| `senior_long_layoff` | 체계별 고령마이면서 60일 초과 휴양이면 1 | horse_age_months + meet_code + days_since_last_race | - | 필수 입력 결측 시 null | low |
| `young_short_cycle` | 체계별 성장기 말이면서 20일 이내 재출전이면 1 | horse_age_months + meet_code + days_since_last_race | - | 필수 입력 결측 시 null | low |

## C1. 보정 속도지수

| feature | 설명 | 원천 | lookback | null 정책 | 누수 위험 |
|---|---|---|---|---|---|
| `speed_figure_last` | 직전 유효 경주의 경기장·거리·주로·당일 variant 보정 속도지수 | 과거 finish_time + 경기장·정확거리·실제 주로상태 | 직전 유효 1경주 | 기준속도 표본이 없으면 null | 대상 경주일 이전 결과만 사용 |
| `speed_figure_avg3` | 최근 유효 3경주 보정 속도지수 평균 | 과거 finish_time + 경기장·정확거리·실제 주로상태 | 최근 유효 3경주 | 유효 기록이 없으면 null | 날짜 단위 갱신으로 같은 날 결과도 제외 |
| `speed_figure_median5` | 최근 유효 5경주 보정 속도지수 중앙값 | 과거 finish_time + 경기장·정확거리·실제 주로상태 | 최근 유효 5경주 | 유효 기록이 없으면 null | 과거 경주만 사용 |
| `speed_figure_best5` | 최근 유효 5경주 최고 보정 속도지수 | 과거 finish_time + 경기장·정확거리·실제 주로상태 | 최근 유효 5경주 | 유효 기록이 없으면 null | 과거 경주만 사용 |
| `speed_figure_trend` | 최근 2경주 평균과 그 이전 최대 3경주 평균의 차이 | 과거 finish_time + 경기장·정확거리·실제 주로상태 | 최근 유효 5경주 | 유효 기록 4회 미만이면 null | 과거 경주만 사용 |
| `speed_figure_count5` | 최근 5경주 창의 유효 보정 속도지수 수 | 과거 finish_time + 경기장·정확거리·실제 주로상태 | 최근 5경주 | 이력 없으면 0 | 과거 경주만 사용 |
| `speed_figure_censored_rate5` | 최근 유효 5경주 중 큰 착차 하위권으로 하한 절단된 비율 | 과거 finish_time + 경기장·정확거리·실제 주로상태 | 최근 유효 5경주 | 유효 기록이 없으면 null | 완료된 과거 경주의 착순만 사용 |
| `speed_figure_exact_distance_avg5` | 현재와 정확히 같은 거리의 최근 유효 5경주 보정지수 평균 | 과거 finish_time + 경기장·정확거리·실제 주로상태 | 동일 거리 최근 유효 5경주 | 동일 거리 이력이 없으면 null | 현재 거리와 과거 결과만 사용 |
| `speed_figure_exact_distance_count5` | 현재와 정확히 같은 거리의 최근 유효 보정지수 수(최대 5) | 과거 finish_time + 경기장·정확거리·실제 주로상태 | 동일 거리 최근 유효 5경주 | 동일 거리 이력이 없으면 0 | 현재 거리와 과거 결과만 사용 |

## C2. 자체 잠재 능력

| feature | 설명 | 원천 | lookback | null 정책 | 누수 위험 |
|---|---|---|---|---|---|
| `ability_elo_global` | 과거 상대 착순으로 계산한 경주 전 multiplayer Elo | past_results 직접 계산 (공식 레이팅 미사용) | 전 기간, 장기 휴양 시 1500으로 완만히 회귀 | 과거가 없으면 1500 | 현재 날짜 결과는 rating 출력 뒤 일괄 갱신 |
| `ability_elo_global_starts` | 자체 global Elo 갱신에 사용된 과거 경주 수 | past_results 직접 계산 (공식 레이팅 미사용) | 전 기간 | 신마는 0 | 현재 경주 미포함 |
| `ability_elo_context` | 경마장×거리대가 같은 과거 경주로 계산한 경주 전 Elo | past_results 직접 계산 (공식 레이팅 미사용) | 동일 경마장×거리대 전 기간 | 해당 조건 첫 출전이면 1500 | 현재 날짜 결과는 rating 출력 뒤 일괄 갱신 |
| `ability_elo_context_starts` | 동일 경마장×거리대 Elo 갱신에 사용된 과거 경주 수 | past_results 직접 계산 (공식 레이팅 미사용) | 동일 조건 전 기간 | 첫 출전이면 0 | 현재 경주 미포함 |
| `ability_elo_vs_field` | global Elo와 같은 경주 상대마 평균 Elo의 차이 | past_results 직접 계산 (공식 레이팅 미사용) | 현재 출전표 + 과거 Elo | 단독 출전이면 0 | 현재 경주의 착순은 사용하지 않음 |
| `ability_elo_uncertainty` | 과거 경주 수 기반 자체 Elo 불확실성 1/sqrt(starts+1) | ability_elo_global_starts 파생 | 전 기간 | 신마는 1 | 현재 경주 미포함 |

## D. 주행 스타일

| feature | 설명 | 원천 | lookback | null 정책 | 누수 위험 |
|---|---|---|---|---|---|
| `early_pos_pct_avg5` | 최근 5경주 S1F 통과순위/출주두수 평균 (작을수록 선행 성향) | race_section_results.S1F + past_results.starters | 최근 5경주 | 구간 원천 공백일·신마·해당 코드 결측 시 null 유지 | low — 현재 경주 제외(shift 1). 라벨(finish_position 등)은 past_results의 과거 행만 사용 |
| `late_gain_avg5` | 최근 5경주 (S1F position − finish_position) 평균 (클수록 막판 추입) | race_section_results.S1F + past_results.finish_position | 최근 5경주 | 구간 원천 공백일·신마·해당 코드 결측 시 null 유지 | low — 현재 경주 제외(shift 1). 라벨(finish_position 등)은 past_results의 과거 행만 사용 |
| `late_gain_pct_avg5` | 최근 5경주 (S1F position − 착순)/출주두수 평균 | race_section_results.S1F + past_results.finish_position/starters | 최근 5경주 | 구간 원천 공백일·신마·해당 코드 결측 시 null 유지 | low — 현재 경주 제외(shift 1). 라벨(finish_position 등)은 past_results의 과거 행만 사용 |
| `early_pos_pct_std5` | 최근 5경주 초반 위치 백분위 표준편차 (전개 성향 안정성) | race_section_results.S1F + past_results.starters | 최근 5경주 | S1F 이력 2회 미만이면 null | low — 현재 경주 제외(shift 1). 라벨(finish_position 등)은 past_results의 과거 행만 사용 |
| `corner4_pos_pct_avg5` | 최근 5경주 4C 통과순위/출주두수 평균 (거리 의존 결측 많음) | race_section_results.4C + past_results.starters | 최근 5경주 | 4C 미존재(거리 의존)·원천 공백일은 null 유지. 0으로 채우지 않음 | low — 현재 경주 제외(shift 1). 라벨(finish_position 등)은 past_results의 과거 행만 사용 |
| `pace_fade_avg5` | 최근 5경주 (G1F position − G3F position) 평균 (막판 1펄롱 순위 변화) | race_section_results.G1F, G3F | 최근 5경주 | G1F 또는 G3F position 결측 시 해당 경주는 창에서 제외, 전부 없으면 null | low — 현재 경주 제외(shift 1). 라벨(finish_position 등)은 past_results의 과거 행만 사용 |
| `style_category` | early_pos_pct_avg5 규칙 분류 (선행/선입/중위/추입) | 파생 (early_pos_pct_avg5) | 최근 5경주 | early_pos_pct_avg5 없으면 null | low — 현재 경주 제외(shift 1). 라벨(finish_position 등)은 past_results의 과거 행만 사용 |
| `section_coverage5` | 최근 5경주 중 S1F position이 존재한 경주 수 (0~5) | race_section_results.S1F | 최근 5경주 | 이력 없으면 0 (null 아님). 구간 원천 공백일은 해당 경주가 미커버 | low — 현재 경주 제외(shift 1). 라벨(finish_position 등)은 past_results의 과거 행만 사용 |

## D+. 예상 전개·코스 상호작용

| feature | 설명 | 원천 | lookback | null 정책 | 누수 위험 |
|---|---|---|---|---|---|
| `course_distance_key` | 경마장×정확한 거리 범주 | meet_code + distance_m | - | null 유지 | low |
| `gate_band` | 출전두수 대비 안쪽/중간/바깥쪽 게이트 | horse_number_pct | - | null 유지 | low |
| `course_distance_gate_band` | 경마장×정확한 거리×게이트 구역 범주 | 파생 | - | null 유지 | low |
| `known_style_share` | 출전마 중 과거 S1F 2회 이상인 말의 비율 | early_pos_pct_avg5 + section_coverage5 | 출전마별 최근 5경주 | null 유지 | low — 과거 구간기록만 사용 |
| `front_runner_count` | 경주 내 강선행형(과거 평균 S1F 상위 25%) 출전마 수 | early_pos_pct_avg5 | 출전마별 최근 5경주 | null 유지 | low — 과거 구간기록만 사용 |
| `front_rival_count` | 자기 자신을 제외한 강선행 경쟁자 수 | front_runner_count | 출전마별 최근 5경주 | null 유지 | low — 과거 구간기록만 사용 |
| `pace_pressure` | 선행 경쟁자 수 범주(없음/1두/2두이상), 성향 확인률 70% 미만은 null | front_rival_count + known_style_share | 출전마별 최근 5경주 | 성향 확인률 70% 미만이면 null | low — 과거 구간기록만 사용 |
| `style_pace_key` | 자기 주행 성향×예상 선행 경합 범주 | style_category + pace_pressure | 출전마별 최근 5경주 | 둘 중 하나가 없으면 null | low — 과거 구간기록만 사용 |
| `style_gate_key` | 자기 주행 성향×게이트 구역 범주 | style_category + gate_band | 출전마별 최근 5경주 | 주행 성향이 없으면 null | low — 과거 구간기록과 현재 출전표만 사용 |

## D1. 거리·계절·주로 게이트 보정

| feature | 설명 | 원천 | lookback | null 정책 | 누수 위험 |
|---|---|---|---|---|---|
| `gate_top3_index_course_distance` | 경마장×정확거리×게이트구역의 과거 3위내 기대대비 지수(100=기대) | 과거 착순 + 출전두수 + 게이트; 경마장 게이트 효과로 수축 | 대상 경주일 이전 3년 | 표본이 없으면 경마장·게이트 또는 중립 100 | 같은 날을 포함하지 않는 날짜 단위 누적 |
| `gate_top3_index_season` | 경마장×정확거리×계절×게이트구역 보정 지수 | 과거 착순 + 계절; 정확거리 지수로 계층 수축 | 대상 경주일 이전 3년 | 희소하면 정확거리 지수로 수축 | 같은 날을 포함하지 않는 날짜 단위 누적 |
| `gate_top3_index_going` | 경마장×정확거리×주로군×게이트구역 보정 지수 | 과거 실제 주로상태; 정확거리 지수로 계층 수축 | 대상 경주일 이전 3년 | 희소·미상 주로는 정확거리 지수로 수축 | 현재는 경주 전 계획 주로상태만 사용 |
| `gate_top3_index_context` | 거리·계절·주로를 결합한 최종 게이트 보정 지수 | 계절/주로 부모 + 과거 동일 세부조건 | 대상 경주일 이전 3년 | 희소하면 계절·주로 부모 평균으로 수축 | 현재 경주의 결과·실제 사후 주로를 사용하지 않음 |
| `gate_context_expected_slots` | 동일 거리·계절·주로·게이트 과거 기대 입상 슬롯 합 | 각 과거 경주의 min(3, 출전두수)/출전두수 합 | 대상 경주일 이전 3년 | 표본이 없으면 0 | 모델이 보정지수의 표본량을 함께 판단하도록 제공 |
| `gate_context_reliability` | 세부조건 게이트 보정의 표본 신뢰도(0~1) | expected_slots / (expected_slots + prior_slots) | 대상 경주일 이전 3년 | 표본이 없으면 0 | 과거 표본량만 사용 |

## D1+. 게이트별 초반속도 보정

| feature | 설명 | 원천 | lookback | null 정책 | 누수 위험 |
|---|---|---|---|---|---|
| `gate_early_speed_course` | 경마장×게이트구역의 과거 S1F 상대속도 효과 | 과거 S1F 시간 + 상대 게이트 | 대상 경주일 이전 3년 | 표본 없으면 중립 0 | 같은 날짜 결과를 대상 feature 출력 후 반영 |
| `gate_early_speed_distance` | 경마장×정확거리×게이트구역의 계층 수축 S1F 효과 | 과거 경주내 S1F 상대속도 | 대상 경주일 이전 3년 | 희소하면 경마장×게이트 효과로 수축 | 현재·같은 날 경주 결과 제외 |
| `gate_early_speed_context` | 경마장×거리×출전두수군×게이트구역의 최종 S1F 효과 | 과거 경주내 S1F 상대속도 | 대상 경주일 이전 3년 | 희소하면 정확거리 효과로 수축 | 현재·같은 날 경주 결과 제외 |
| `gate_early_speed_evidence` | 최종 게이트 초반속도 셀의 과거 유효 S1F 표본 수 | 과거 S1F 유효 관측 수 | 대상 경주일 이전 3년 | 표본 없으면 0 | 현재·같은 날 경주 결과 제외 |
| `gate_early_speed_reliability` | 게이트 초반속도 세부효과 신뢰도 n/(n+20) | gate_early_speed_evidence | 대상 경주일 이전 3년 | 표본 없으면 0 | 현재·같은 날 경주 결과 제외 |
| `gate_early_speed_front_fit` | 게이트 초반속도 효과×과거 선행성향×스타일 신뢰도 | gate_early_speed_context + early_pos_pct_avg5 | 게이트 3년, 말 최근 5경주 | 스타일 이력 없으면 0 | 모든 입력은 경주 전 정보 |

## G3. 모래반응·회복 상태

| feature | 설명 | 원천 | lookback | null 정책 | 누수 위험 |
|---|---|---|---|---|---|
| `sand_incident_count_prior` | 심판보고서에서 확인된 과거 모래 이상반응 누적 횟수 | race_steward_reports + 출전마명 | 전 기간 | 명시 반응 없으면 0 | 대상 경주일 보고서는 다음 경주부터 반영 |
| `sand_incident_count_365d` | 최근 365일 명시적 모래 이상반응 횟수 | race_steward_reports | 365일 | 없으면 0 | 대상 경주일 제외 |
| `sand_days_since_incident` | 마지막 명시적 모래 이상반응 후 경과일 | race_steward_reports | 직전 사건 | 사건 없으면 null | 대상 경주일 제외 |
| `sand_sensitivity_state` | 재발·시간감쇠·후속 정상노출을 반영한 말별 모래 민감도(0~1) | 명시 반응 + 후속 고노출 경주 | 전 기간, 365일 반감기 | 사건 없으면 0 | 같은 날짜 feature 출력 후 상태 갱신 |
| `sand_recovery_evidence` | 마지막 반응 이후 모래 고노출 추정 경주에서 정상 수행한 누적 증거 | 과거 S1F 위치·게이트·출전두수·착순 | 마지막 반응 이후 | 증거 없으면 0 | 현재 경주 결과 제외 |
| `sand_recovery_score` | 민감도 감소와 정상노출 증거를 결합한 회복 점수(0~1) | sand_sensitivity_state + recovery evidence | 마지막 반응 이후 | 반응 이력 없으면 0 | 현재 경주 결과 제외 |
| `sand_recovered_flag` | 충분한 정상노출 증거와 낮은 현재 민감도를 함께 만족하면 1 | 회복 상태 규칙 | 마지막 반응 이후 | 반응 이력 없거나 미회복이면 0 | 현재 경주 결과 제외 |
| `sand_exposure_risk` | 이번 경주의 스타일·게이트·출전두수 기반 모래 노출 위험(0~1) | early_pos_pct_avg5 + horse_number_pct + starters | - | 결측 입력은 중립값 | 현재 출전표와 과거 스타일만 사용 |
| `sand_expected_penalty` | 현재 민감도×모래 노출위험×상태 신뢰도 | sand sensitivity state + exposure risk | - | 민감도 이력 없으면 0 | 모든 입력은 경주 전 정보 |
| `sand_state_reliability` | 최근 사건과 회복증거 및 정보 최신성을 반영한 상태 신뢰도 | 사건·회복 상태 | - | 정보 없으면 0 | 현재 경주 결과 제외 |

## E~G. 체중·훈련·건강

| feature | 설명 | 원천 | lookback | null 정책 | 누수 위험 |
|---|---|---|---|---|---|
| `body_weight_prev_avg5` | 과거 5경주 체중 평균 (현재 경주 제외) | past_results.body_weight_kg | 직전 최대 5경주 | 과거 경주 없으면 null | horse_id·race_date 정렬 후 shift(1) rolling — 현재 경주 체중 제외 |
| `body_weight_std5` | 과거 5경주 체중 표준편차 (현재 경주 제외) | past_results.body_weight_kg | 직전 최대 5경주 | 과거 2경주 미만이면 null | shift(1) rolling — 현재 경주 체중 제외 |
| `body_weight_dev` | 현재 체중 − 과거 5경주 체중 평균 | frame.body_weight_kg − body_weight_prev_avg5 | 직전 최대 5경주 | 현재 체중 또는 과거 평균이 없으면 null. day_before_18이면 컬럼 스킵 | 당일 체중은 계량 후 공개. frame에 body_weight_kg 없으면 이 feature만 스킵 |
| `train_n_3d` | 경주 직전 3일 훈련 횟수 (당일 제외) | horse_training | 3일 | 이력 없으면 0 | event_date < race_date (당일 제외) |
| `train_n_7d` | 경주 직전 7일 훈련 횟수 (당일 제외) | horse_training | 7일 | 이력 없으면 0 | event_date < race_date (당일 제외) |
| `train_n_14d` | 경주 직전 14일 훈련 횟수 (당일 제외) | horse_training | 14일 | 이력 없으면 0 | event_date < race_date (당일 제외) |
| `train_n_28d` | 경주 직전 28일 훈련 횟수 (당일 제외) | horse_training | 28일 | 이력 없으면 0 | event_date < race_date (당일 제외) |
| `train_dur_28d` | 경주 직전 28일 훈련 시간 합(초) | horse_training.duration_seconds | 28일 | 해당 말 훈련 이력이 없으면 null | event_date < race_date (당일 제외) |
| `gallop_n_28d` | 경주 직전 28일 습보(gallop) 횟수 합 | horse_training.gallop_count | 28일 | 해당 말 훈련 이력이 없으면 null | event_date < race_date (당일 제외) |
| `canter_n_28d` | 경주 직전 28일 구보(canter) 횟수 합 | horse_training.canter_count | 28일 | 해당 말 훈련 이력이 없으면 null | event_date < race_date (당일 제외) |
| `days_since_training` | 마지막 훈련 후 경과일 | horse_training | 직전 1회 | 이전 훈련 없으면 null | event_date < race_date (당일 제외) |
| `start_train_n_28d` | 경주 직전 28일 출발대 훈련 횟수 | horse_start_training | 28일 | 이력 없으면 0 | event_date < race_date (당일 제외) |
| `medical_n_14d` | 경주 직전 14일 진료 횟수 (당일 제외) | horse_medical | 14일 | 이력 없으면 0 | event_date < race_date (당일 제외) |
| `medical_n_30d` | 경주 직전 30일 진료 횟수 (당일 제외) | horse_medical | 30일 | 이력 없으면 0 | event_date < race_date (당일 제외) |
| `medical_n_60d` | 경주 직전 60일 진료 횟수 (당일 제외) | horse_medical | 60일 | 이력 없으면 0 | event_date < race_date (당일 제외) |
| `days_since_medical` | 마지막 진료 후 경과일 | horse_medical | 직전 1회 | 이전 진료 없으면 null | event_date < race_date (당일 제외) |
| `bleeding_count_prior` | 현재 경주 출전마 누적 폐출혈 횟수 | entry_equipment.bleeding_count | 현재 경주 행 | 해당 경주 equipment 행 없으면 null | 현재 경주 equipment 행은 경주 전 공개 (horse_id+race_date+race_number 매칭) |
| `equipment_present` | 현재 경주 장구 착용 여부 (equipment_raw 비어있지 않으면 1) | entry_equipment.equipment_raw | 현재 경주 행 | 행 없거나 공백이면 0 | 현재 경주 equipment 행은 경주 전 공개 정보로 사용 |
| `equipment_changed` | 직전 경주 대비 장구 변경 여부 | entry_equipment.equipment_raw | 직전 경주 (race_date 엄격 이전 마지막 행) | 현재 또는 직전 equipment_raw가 없으면 null | 현재 행은 경주 전 공개. 직전 행은 race_date < 현재 경주일인 마지막 equipment 이력 |

## G+. 조교 부하·개인기준

| feature | 설명 | 원천 | lookback | null 정책 | 누수 위험 |
|---|---|---|---|---|---|
| `train_prior_n_29_180d` | 직전 29~180일 훈련일 수(개인 기준의 증거량) | horse_training | 29~180일 | 이력 없으면 0 | event_date < race_date, 최근 28일과 분리 |
| `train_frequency_ratio_7_28` | 최근 7일 일평균 훈련빈도 / 최근 28일 일평균(평활) | train_n_7d + train_n_28d | 7일 / 28일 | 평활값 사용 | low |
| `train_frequency_dev_28_prior` | 최근 28일 훈련일 수 − 이전 152일에서 환산한 28일 기대치 | horse_training | 최근 28일 vs 이전 152일 | 이전 구간 이력 없으면 null | low |
| `train_frequency_ratio_28_prior` | 최근 28일 훈련빈도 / 이전 152일 개인 기준(평활) | horse_training | 최근 28일 vs 이전 152일 | 이전 구간 이력 없으면 null | low |
| `train_avg_duration_28d` | 최근 28일 훈련 1회당 평균 시간(초) | train_dur_28d / train_n_28d | 28일 | 훈련 0회면 null | low |
| `train_gallop_per_day_28d` | 최근 28일 훈련일당 습보 횟수 | gallop_n_28d / train_n_28d | 28일 | 훈련 0회면 null | low |
| `train_canter_per_day_28d` | 최근 28일 훈련일당 구보 횟수 | canter_n_28d / train_n_28d | 28일 | 훈련 0회면 null | low |

## G+. 주행심사

| feature | 설명 | 원천 | lookback | null 정책 | 누수 위험 |
|---|---|---|---|---|---|
| `trial_n_180d` | 경주 전 180일 주행심사 참가 횟수 | running_trial_results + running_trials | 180일 | 이력 없으면 0 | trial_date < race_date, 당일 심사 제외 |
| `trial_pass_n_180d` | 경주 전 180일 주행심사 합격 횟수 | running_trial_results.judgement='합' | 180일 | 이력 없으면 0 | trial_date < race_date |
| `trial_fail_n_180d` | 경주 전 180일 주행심사 불합격 횟수 | running_trial_results.judgement='불' | 180일 | 이력 없으면 0 | trial_date < race_date |
| `days_since_trial` | 가장 최근 주행심사 후 경과일 | running_trials.trial_date_local | 직전 1회 | 이력 없으면 null | trial_date < race_date |
| `last_trial_passed` | 최근 심사 판정: 합격 1, 불합격 0, 기타 null | running_trial_results.judgement | 직전 1회 | 합·불 외 판정 또는 이력 없으면 null | 엄격히 이전인 마지막 심사 |
| `last_trial_time_per_100m` | 최근 심사 100m당 기록(초) | finish_time_ms / distance_m | 직전 1회 | 완주 기록 없으면 null | 엄격히 이전인 마지막 심사 |
| `last_trial_finish_percentile` | 최근 심사 순위/참가두수 비율(낮을수록 우수) | finish_position / field_size | 직전 1회 | 정상 순위 없으면 null | 엄격히 이전인 마지막 심사 |
| `last_trial_s1f_sec` | 최근 심사 S1F 기록(초) | running_trial_results.s1f_ms | 직전 1회 | 구간 기록 없으면 null | 엄격히 이전인 마지막 심사 |
| `last_trial_g3f_sec` | 최근 심사 G3F 기록(초) | running_trial_results.g3f_ms | 직전 1회 | 구간 기록 없으면 null | 엄격히 이전인 마지막 심사 |
| `last_trial_g1f_sec` | 최근 심사 G1F 기록(초) | running_trial_results.g1f_ms | 직전 1회 | 구간 기록 없으면 null | 엄격히 이전인 마지막 심사 |
| `last_trial_body_weight_kg` | 최근 심사 당시 마체중 | running_trial_results.body_weight_kg | 직전 1회 | 취소·미계량이면 null | 엄격히 이전인 마지막 심사 |
| `last_trial_newcomer_exam` | 최근 심사가 신마 주행심사이면 1 | running_trial_results.inspection_reason | 직전 1회 | 이력 없으면 null | 엄격히 이전인 마지막 심사 |

## G++. 기수 조교·교정심사

| feature | 설명 | 원천 | lookback | null 정책 | 누수 위험 |
|---|---|---|---|---|---|
| `current_jockey_train_n_28d` | 이번 기수가 해당 말에 직접 참여한 최근 28일 조교 일수 | horse_training.rider_id + jockeys.kra_jockey_id | 28일 | 없으면 0 | training_date < race_date; 당일 제외 |
| `current_jockey_train_duration_28d` | 이번 기수가 참여한 최근 28일 조교 시간 합(초) | horse_training.duration_seconds | 28일 | 없으면 0 | training_date < race_date; 당일 제외 |
| `current_jockey_train_gallop_28d` | 이번 기수가 참여한 최근 28일 습보 횟수 합 | horse_training.gallop_count | 28일 | 없으면 0 | training_date < race_date; 당일 제외 |
| `current_jockey_train_2plus_28d` | 이번 기수의 최근 28일 직접 조교가 2일 이상이면 1 | current_jockey_train_n_28d | 28일 | 없으면 0 | strict prior 집계의 파생값 |
| `jockey_changed_from_last_start` | 직전 공식 출전 기수와 이번 기수가 다르면 1 | race_entries.jockey_id | 직전 공식 출전 | 직전 출전 또는 기수 미상이면 null | race_date보다 엄격히 이전인 공식 결과만 사용 |
| `remedial_trial_passed_since_start` | 직전 출전 뒤 주행지정(재) 심사 합격이 있으면 1 | running_trial_results | 직전 출전 이후 | 없으면 0 | last_start < trial_date < race_date |
| `remedial_trial_winner_since_start` | 최근 교정 심사에 합격하면서 1착이면 1 | running_trial_results.finish_position | 직전 출전 이후 최근 합격 심사 | 없으면 0 | last_start < trial_date < race_date |
| `remedial_trial_current_jockey` | 최근 교정 심사를 이번 출전 기수가 탔으면 1 | running_trial_results.jockey_id | 직전 출전 이후 최근 합격 심사 | 없거나 기수 미상이면 0 | last_start < trial_date < race_date |
| `remedial_trial_current_jockey_winner` | 이번 기수가 탄 최근 교정 심사에서 합격·1착이면 1 | running_trial_results | 직전 출전 이후 최근 합격 심사 | 없으면 0 | strict prior 교정 심사 파생값 |
| `remedial_trial_new_jockey_winner` | 직전과 다른 이번 기수가 교정 심사 합격·1착을 만들었으면 1 | running_trial_results + race_entries | 직전 출전 이후 최근 합격 심사 | 없으면 0 | strict prior 공식 결과와 교정 심사만 사용 |
| `remedial_trial_finish_percentile` | 최근 교정 합격 심사의 순위/참가두수(낮을수록 우수) | running_trial_results | 직전 출전 이후 최근 합격 심사 | 없으면 null | last_start < trial_date < race_date |
| `bit_changed_from_last_start` | 직전 공식 출전 대비 재갈 종류가 바뀌면 1 | entry_equipment.equipment_raw | 직전 공식 출전 | 양쪽 장구 정보가 없으면 null | 현재 출전표 장구와 strict prior 출전 장구만 비교 |
| `remedial_trial_bit_changed` | 교정 심사 합격과 직전 출전 대비 재갈 변경이 함께 있으면 1 | running_trial_results + entry_equipment | 직전 공식 출전 이후 | 판단 불가면 0 | 두 point-in-time 신호의 상호작용 |

## H. 사람·조합

| feature | 설명 | 원천 | lookback | null 정책 | 누수 위험 |
|---|---|---|---|---|---|
| `jockey_starts_90d` | 기수 최근 90일 출주수 | past_results (race_entries+race_results 직접 집계) | 90일 | jockey_id null이면 null. 과거 출주 없으면 0 | race_date 엄격히 이전만 집계, 당일·미래 제외 |
| `jockey_starts_365d` | 기수 최근 365일 출주수 | past_results (race_entries+race_results 직접 집계) | 365일 | jockey_id null이면 null. 과거 출주 없으면 0 | race_date 엄격히 이전만 집계, 당일·미래 제외 |
| `jockey_win_rate_90d` | 기수 최근 90일 승률 (1착 / 출주) | past_results (race_entries+race_results 직접 집계) | 90일 | jockey_id null이거나 출주 0이면 null | race_date 엄격히 이전만 집계, 당일·미래 제외 |
| `jockey_win_rate_365d` | 기수 최근 365일 승률 (1착 / 출주) | past_results (race_entries+race_results 직접 집계) | 365일 | jockey_id null이거나 출주 0이면 null | race_date 엄격히 이전만 집계, 당일·미래 제외 |
| `jockey_top3_rate_90d` | 기수 최근 90일 복승률 (3착 이내 / 출주) | past_results (race_entries+race_results 직접 집계) | 90일 | jockey_id null이거나 출주 0이면 null | race_date 엄격히 이전만 집계, 당일·미래 제외 |
| `trainer_starts_90d` | 조교사 최근 90일 출주수 | past_results (race_entries+race_results 직접 집계) | 90일 | trainer_id null이면 null. 과거 출주 없으면 0 | race_date 엄격히 이전만 집계, 당일·미래 제외 |
| `trainer_starts_365d` | 조교사 최근 365일 출주수 | past_results (race_entries+race_results 직접 집계) | 365일 | trainer_id null이면 null. 과거 출주 없으면 0 | race_date 엄격히 이전만 집계, 당일·미래 제외 |
| `trainer_win_rate_90d` | 조교사 최근 90일 승률 (1착 / 출주) | past_results (race_entries+race_results 직접 집계) | 90일 | trainer_id null이거나 출주 0이면 null | race_date 엄격히 이전만 집계, 당일·미래 제외 |
| `trainer_win_rate_365d` | 조교사 최근 365일 승률 (1착 / 출주) | past_results (race_entries+race_results 직접 집계) | 365일 | trainer_id null이거나 출주 0이면 null | race_date 엄격히 이전만 집계, 당일·미래 제외 |
| `trainer_top3_rate_90d` | 조교사 최근 90일 복승률 (3착 이내 / 출주) | past_results (race_entries+race_results 직접 집계) | 90일 | trainer_id null이거나 출주 0이면 null | race_date 엄격히 이전만 집계, 당일·미래 제외 |
| `horse_jockey_starts` | 이 말×이 기수 과거 조합 출주수 | past_results (race_entries+race_results 직접 집계) | 전 기간 | jockey_id null이면 null. 과거 조합 없으면 0 | 현재 경주는 그룹 내 shift(1) cum count로 제외 |
| `horse_jockey_wins` | 이 말×이 기수 과거 조합 승수 | past_results (race_entries+race_results 직접 집계) | 전 기간 | jockey_id null이면 null. 과거 조합 없으면 0 | 현재 경주는 그룹 내 shift(1) cum count로 제외 |
| `horse_jockey_first` | 이 말×이 기수 첫 조합 여부 (0/1) | past_results (race_entries+race_results 직접 집계) | 전 기간 | jockey_id null이면 null. 과거 출주 0이면 1, 아니면 0 | 현재 경주는 그룹 내 shift(1) cum count로 제외 |
| `jockey_changed` | 이 경주에 기수변경 공지 존재 (0/1) | jockey_changes (horse_id+race_date+race_number) | - | 공지 없으면 0 | 공지는 경주 전 공개, observed_at은 수집시각이라 사용 안 함(T3) |

## I. 경주 내 상대값

| feature | 설명 | 원천 | lookback | null 정책 | 누수 위험 |
|---|---|---|---|---|---|
| `rating_race_z` | rating의 경주 내 z-score | 파생 | - | 경주 내 표준편차 0이면 null | low |
| `rating_race_rank` | rating의 경주 내 순위 (내림차순, 동률 평균) | 파생 | - | null 유지 | low |
| `carried_weight_kg_race_z` | carried_weight_kg의 경주 내 z-score | 파생 | - | 경주 내 표준편차 0이면 null | low |
| `carried_weight_kg_race_rank` | carried_weight_kg의 경주 내 순위 (내림차순, 동률 평균) | 파생 | - | null 유지 | low |
| `body_weight_kg_race_z` | body_weight_kg의 경주 내 z-score | 파생 | - | 경주 내 표준편차 0이면 null | low |
| `body_weight_kg_race_rank` | body_weight_kg의 경주 내 순위 (내림차순, 동률 평균) | 파생 | - | null 유지 | low |
| `horse_age_months_race_z` | horse_age_months의 경주 내 z-score | 파생 | - | 경주 내 표준편차 0이면 null | low |
| `horse_age_months_race_rank` | horse_age_months의 경주 내 순위 (내림차순, 동률 평균) | 파생 | - | null 유지 | low |
| `form_recent5_pct_race_z` | form_recent5_pct의 경주 내 z-score | 파생 | - | 경주 내 표준편차 0이면 null | low |
| `form_recent5_pct_race_rank` | form_recent5_pct의 경주 내 순위 (내림차순, 동률 평균) | 파생 | - | null 유지 | low |
| `form_recent5_median_pct_race_z` | form_recent5_median_pct의 경주 내 z-score | 파생 | - | 경주 내 표준편차 0이면 null | low |
| `form_recent5_median_pct_race_rank` | form_recent5_median_pct의 경주 내 순위 (내림차순, 동률 평균) | 파생 | - | null 유지 | low |
| `speed_avg_mps_5_race_z` | speed_avg_mps_5의 경주 내 z-score | 파생 | - | 경주 내 표준편차 0이면 null | low |
| `speed_avg_mps_5_race_rank` | speed_avg_mps_5의 경주 내 순위 (내림차순, 동률 평균) | 파생 | - | null 유지 | low |
| `speed_rel_median5_race_z` | speed_rel_median5의 경주 내 z-score | 파생 | - | 경주 내 표준편차 0이면 null | low |
| `speed_rel_median5_race_rank` | speed_rel_median5의 경주 내 순위 (내림차순, 동률 평균) | 파생 | - | null 유지 | low |
| `speed_figure_median5_race_z` | speed_figure_median5의 경주 내 z-score | 파생 | - | 경주 내 표준편차 0이면 null | low |
| `speed_figure_median5_race_rank` | speed_figure_median5의 경주 내 순위 (내림차순, 동률 평균) | 파생 | - | null 유지 | low |
| `speed_figure_exact_distance_avg5_race_z` | speed_figure_exact_distance_avg5의 경주 내 z-score | 파생 | - | 경주 내 표준편차 0이면 null | low |
| `speed_figure_exact_distance_avg5_race_rank` | speed_figure_exact_distance_avg5의 경주 내 순위 (내림차순, 동률 평균) | 파생 | - | null 유지 | low |
| `early_pos_pct_avg5_race_z` | early_pos_pct_avg5의 경주 내 z-score | 파생 | - | 경주 내 표준편차 0이면 null | low |
| `early_pos_pct_avg5_race_rank` | early_pos_pct_avg5의 경주 내 순위 (내림차순, 동률 평균) | 파생 | - | null 유지 | low |
| `late_gain_pct_avg5_race_z` | late_gain_pct_avg5의 경주 내 z-score | 파생 | - | 경주 내 표준편차 0이면 null | low |
| `late_gain_pct_avg5_race_rank` | late_gain_pct_avg5의 경주 내 순위 (내림차순, 동률 평균) | 파생 | - | null 유지 | low |
| `exact_distance_top3_rate_race_z` | exact_distance_top3_rate의 경주 내 z-score | 파생 | - | 경주 내 표준편차 0이면 null | low |
| `exact_distance_top3_rate_race_rank` | exact_distance_top3_rate의 경주 내 순위 (내림차순, 동률 평균) | 파생 | - | null 유지 | low |
| `ability_elo_global_race_z` | ability_elo_global의 경주 내 z-score | 파생 | - | 경주 내 표준편차 0이면 null | low |
| `ability_elo_global_race_rank` | ability_elo_global의 경주 내 순위 (내림차순, 동률 평균) | 파생 | - | null 유지 | low |
| `ability_elo_context_race_z` | ability_elo_context의 경주 내 z-score | 파생 | - | 경주 내 표준편차 0이면 null | low |
| `ability_elo_context_race_rank` | ability_elo_context의 경주 내 순위 (내림차순, 동률 평균) | 파생 | - | null 유지 | low |
| `jockey_win_rate_90d_race_z` | jockey_win_rate_90d의 경주 내 z-score | 파생 | - | 경주 내 표준편차 0이면 null | low |
| `jockey_win_rate_90d_race_rank` | jockey_win_rate_90d의 경주 내 순위 (내림차순, 동률 평균) | 파생 | - | null 유지 | low |
| `trainer_win_rate_90d_race_z` | trainer_win_rate_90d의 경주 내 z-score | 파생 | - | 경주 내 표준편차 0이면 null | low |
| `trainer_win_rate_90d_race_rank` | trainer_win_rate_90d의 경주 내 순위 (내림차순, 동률 평균) | 파생 | - | null 유지 | low |
