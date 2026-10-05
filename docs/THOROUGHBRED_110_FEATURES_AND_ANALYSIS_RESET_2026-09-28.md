# 최종 더러브렛 연구 모델의 110개 입력과 분석 재설계 — 2026-09-28

현재 대화에서 유지한 연구 기준은 A=v5 `rolling_all`(반기 갱신), B/C의 기본 Top3 점수=v4 `top3_growth_strength`(연간 갱신)다. 2026H2 A와 2026 B/C 저장 모델의 metadata 및 실제 LightGBM feature_names가 후보 목록과 순서까지 같은지 대조했다. **13개 범주형+97개 수치형=110개**다. 이 연구 계열의 최종 선택이며 운영 시스템 전체 모델 현황을 감사했다는 뜻은 아니다.

C의 정확한 순서 계산에는 별도 v2 `H3_relative` 우승 점수 모델도 사용된다. 그 저장 메타데이터 입력은 72개다. 따라서 110개는 기본 Top3 점수 모델의 입력 수이지 전체 조합·순서 계산 단계를 통틀어 별도 부가 모델이 없다는 뜻이 아니다.

110개는 입력 열 개수다. 서로 독립적인 현상 110가지, 인과효과 110개, 모든 열에 동일 가중치를 주는 방식이라는 뜻은 아니다. 같은 성적의 최근값·평균·최고값이 여러 열로 들어가고, 식별번호 및 이력 개수도 포함한다. 변수의 유효성은 저장 목록만으로 판정하지 않으며, 분할별 기여·제거 실험이 별도로 필요하다.

**구성 요약**

| 분류 | 개수 |
|---|---:|
| 범주형 출마·개체 정보 | 13 |
| 현재 카드 수치 정보 | 6 |
| 누적 전적·경마장 이력 | 17 |
| 계절 | 2 |
| 최근 성적·조건 변화 | 12 |
| 상대 수준을 반영한 Elo 능력 | 5 |
| 보정된 최종 기록 | 10 |
| 이번 편성 대비 상대 능력 | 7 |
| 게이트 | 8 |
| 거리·기수·부담중량·휴양·기록 편차 | 16 |
| 초반 위치·선행 경쟁 | 8 |
| 성장·최근 변화·과거 상대 수준 | 6 |
| 합계 | 110 |

**110개 전체 목록 — 저장 모델의 입력 순서**

`최근3/5회`는 최대 관측 개수다. 결측과 0의 의미는 다르다. 누적 출전 정의도 base의 확정 행 수와 condition의 실제 출전 수가 다르므로 합칠 때 재검증해야 한다.

**범주형 출마·개체 정보**

| 번호 | 코드명 | 의미·주의점 |
|---:|---|---|
| 1 | `venue_code` | 경마장 구분 |
| 2 | `race_type` | 공식 경주 유형 |
| 3 | `race_class` | 경주 등급 |
| 4 | `burden_type` | 부담중량 부여 방식 |
| 5 | `rating_condition_raw` | 출전 가능 레이팅 조건 원문 |
| 6 | `origin_raw` | 말의 산지 |
| 7 | `sex_raw` | 말의 성별 |
| 8 | `hr_no` | 말의 공식 식별번호. 능력 측정값 자체는 아님 |
| 9 | `jockey_no` | 기수 식별번호. 세부 기승 스타일 자체는 아님 |
| 10 | `trainer_no` | 조교사 식별번호. 조교 강도 자체는 아님 |
| 11 | `owner_no` | 마주 식별번호. 승부 의도를 측정하지 않음 |
| 12 | `hist_previous_race_venue` | 직전 확정 출전의 경마장 |
| 13 | `venue_distance_class` | 경마장×거리×등급을 결합한 범주 |

**현재 카드 수치 정보**

| 번호 | 코드명 | 의미·주의점 |
|---:|---|---|
| 14 | `distance_m` | 이번 경주 거리(m) |
| 15 | `field_size_full_card` | 보존된 전체 출마표 행 수. 최종 실제 출전두수와 다를 수 있음 |
| 16 | `chul_no` | 등록된 출발번호/마번 |
| 17 | `age_raw` | 현재 말 나이 |
| 18 | `rating_raw` | 현재 공식 레이팅 |
| 19 | `burden_weight_kg` | 현재 부담중량(kg). 마체중이 아님 |

**누적 전적·경마장 이력**

| 번호 | 코드명 | 의미·주의점 |
|---:|---|---|
| 20 | `hist_prior_starts_all` | 과거 확정 출전행 수 |
| 21 | `hist_prior_finished_all` | 과거 착순 라벨이 있는 완주 수 |
| 22 | `hist_prior_wins_all` | 과거 우승 수 |
| 23 | `hist_prior_top3_all` | 과거 3위 이내 수 |
| 24 | `hist_prior_starts_at_venue` | 현재 경마장에서의 과거 확정 출전행 수 |
| 25 | `hist_prior_finished_at_venue` | 현재 경마장에서의 과거 완주 수 |
| 26 | `hist_prior_wins_at_venue` | 현재 경마장에서의 과거 우승 수 |
| 27 | `hist_prior_starts_other_venue` | 다른 경마장에서의 과거 확정 출전행 수 |
| 28 | `hist_days_since_last_race` | 직전 확정 출전일 이후 일수 |
| 29 | `hist_venue_changed_since_last_start` | 직전 출전과 현재 경마장이 달라졌는지 |
| 30 | `hist_first_start_at_venue` | 현재 경마장에 첫 출전인지 |
| 31 | `hist_away_from_first_observed_venue` | 처음 관측된 경마장과 현재 경마장이 다른지 |
| 32 | `smoothed_historic_win_rate` | 완화한 통산 승률: (우승+1)/(완주+10) |
| 33 | `smoothed_historic_top3_rate` | 완화한 통산 입상률: (입상+3)/(완주+10) |
| 34 | `prior_starts_venue_distance_class` | 같은 경마장×정확거리×등급의 과거 출전행 수 |
| 35 | `prior_wins_venue_distance_class` | 같은 경마장×정확거리×등급의 과거 우승 수 |
| 36 | `smoothed_win_rate_venue_distance_class` | 동일 조건 완화 승률: (우승+1)/(출전행+20) |

**계절**

| 번호 | 코드명 | 의미·주의점 |
|---:|---|---|
| 37 | `race_month_sin` | 경주 월을 원형으로 표현한 sine 값 |
| 38 | `race_month_cos` | 경주 월을 원형으로 표현한 cosine 값. 위 값과 함께 12월·1월의 연속성 표현 |

**최근 성적·조건 변화**

| 번호 | 코드명 | 의미·주의점 |
|---:|---|---|
| 39 | `research_form_finish_pct_last` | 직전 유효 상대 착순 점수. 1이 좋고 0이 나쁨 |
| 40 | `research_form_finish_pct_avg3` | 최근 유효 최대 3회 상대 착순 점수 평균 |
| 41 | `research_form_finish_pct_avg5` | 최근 유효 최대 5회 상대 착순 점수 평균 |
| 42 | `research_form_wins3` | 최근 유효 최대 3회 중 우승 횟수 |
| 43 | `research_form_wins5` | 최근 유효 최대 5회 중 우승 횟수 |
| 44 | `research_form_top3_3` | 최근 유효 최대 3회 중 입상 횟수 |
| 45 | `research_form_top3_5` | 최근 유효 최대 5회 중 입상 횟수 |
| 46 | `research_form_prior_valid_finishes` | 누적 유효 착순 이력 수 |
| 47 | `research_form_last_burden_delta_kg` | 현재 부담중량−직전 출전 부담중량(kg) |
| 48 | `research_form_last_distance_delta_m` | 현재 거리−직전 출전 거리(m) |
| 49 | `research_form_dnf_count5` | 최근 확정 최대 5회 출전 중 미완주(DNF) 횟수 |
| 50 | `research_form_dnf_rate5` | 최근 확정 최대 5회 출전 중 미완주 비율 |

**상대 수준을 반영한 Elo 능력**

| 번호 | 코드명 | 의미·주의점 |
|---:|---|---|
| 51 | `research_elo_global` | 과거 상대와의 승패에서 누적한 전체 Elo. 신규 기본값 1500 |
| 52 | `research_elo_global_starts` | 전체 Elo를 갱신한 과거 경주 수 |
| 53 | `research_elo_context` | 현재 경마장×정확거리의 Elo. 신규 기본값 1500 |
| 54 | `research_elo_context_starts` | 해당 경마장×정확거리의 Elo 갱신 경주 수 |
| 55 | `research_elo_uncertainty` | Elo 이력 부족 정도: 1/sqrt(전체 Elo 갱신 수+1). 예측 신뢰구간 자체는 아님 |

**보정된 최종 기록**

| 번호 | 코드명 | 의미·주의점 |
|---:|---|---|
| 56 | `research_speed_last` | 직전 유효 보정 속도지수 |
| 57 | `research_speed_avg3` | 최근 유효 최대 3회 보정 속도지수 평균 |
| 58 | `research_speed_median5` | 최근 유효 최대 5회 보정 속도지수 중앙값 |
| 59 | `research_speed_best5` | 최근 유효 최대 5회 최고 보정 속도지수 |
| 60 | `research_speed_trend` | 최근 2회 평균−그 이전 최대 3회 평균. 유효 4회 이상 필요 |
| 61 | `research_speed_count5` | 최근 최대 5회 창의 유효 속도지수 개수 |
| 62 | `research_speed_censored_rate5` | 최근 최대 5회 지수 중 뒤처진 완주 기록의 하한 제한이 적용된 비율. 실제 전력 질주 포기를 관측한 값은 아님 |
| 63 | `research_speed_exact_distance_avg5` | 이번 정확거리에서 최근 유효 최대 5회 속도지수 평균 |
| 64 | `research_speed_exact_distance_count5` | 이번 정확거리에서 확보된 최근 유효 속도지수 수(최대 5) |
| 65 | `research_speed_has_valid_history` | 유효 속도지수 이력이 있는지 |

**이번 편성 대비 상대 능력**

| 번호 | 코드명 | 의미·주의점 |
|---:|---|---|
| 66 | `research_elo_vs_field` | 자기 전체 Elo−이번 상대마 평균 Elo |
| 67 | `research_context_elo_vs_field` | 자기 경마장×거리 Elo−이번 상대마 평균 |
| 68 | `research_rating_vs_field` | 자기 레이팅−현재 레이팅이 있는 상대마 평균 |
| 69 | `research_speed_vs_field` | 자기 직전 속도지수−해당 지수가 있는 상대마 평균 |
| 70 | `research_field_competitor_count` | 전체 출마표에서 자기 외 상대마 수 |
| 71 | `research_field_rating_available_count` | 현재 레이팅이 있는 상대마 수 |
| 72 | `research_field_speed_available_count` | 과거 유효 속도지수가 있는 상대마 수 |

**게이트**

| 번호 | 코드명 | 의미·주의점 |
|---:|---|---|
| 73 | `research_gate_position_pct` | 출발번호/전체 출마표 두수. 이번 게이트 감사의 순위 기반 정의와 다름 |
| 74 | `research_gate_band_code` | 상대 출발번호 ≤1/3이면 내측0, ≤2/3이면 중간1, 그 밖은 외측2 |
| 75 | `research_gate_top3_index_course_3y` | 이전 1095일 경마장×게이트 구역의 관측/Elo 기대 입상 지수. 100이 중립 |
| 76 | `research_gate_top3_index_distance_3y` | 이전 1095일 경마장×정확거리×게이트 구역 입상 지수 |
| 77 | `research_gate_top3_index_recent_1y` | 이전 365일 같은 경마장×정확거리×게이트 구역 입상 지수 |
| 78 | `research_gate_recent_minus_long` | 최근 1년 지수−3년 정확거리 지수 |
| 79 | `research_gate_distance_expected_slots` | 이전 1095일 같은 경마장×거리×게이트 구역의 기대 입상 슬롯 합 |
| 80 | `research_gate_distance_reliability` | 게이트 거리 통계 신뢰도 대리값: 기대 슬롯/(기대 슬롯+30) |

**거리·기수·부담중량·휴양·기록 편차**

| 번호 | 코드명 | 의미·주의점 |
|---:|---|---|
| 81 | `research_condition_distance_starts` | 현재 정확거리의 과거 실제 출전 수. 경마장 합산 |
| 82 | `research_condition_distance_wins` | 현재 정확거리의 과거 우승 수 |
| 83 | `research_condition_distance_top3` | 현재 정확거리의 과거 입상 수 |
| 84 | `research_condition_distance_top3_rate_smoothed` | 거리 입상률 완화값: (입상+2)/(출전+8) |
| 85 | `research_condition_distance_finish_pct_avg5` | 현재 정확거리 최근 유효 최대 5회 상대 착순 점수 평균. 높을수록 좋음 |
| 86 | `research_condition_jockey_changed` | 현재 기수가 직전 출전 기수와 달라졌는지 |
| 87 | `research_condition_jockey_pair_starts` | 현재 말×기수 조합의 과거 실제 출전 수 |
| 88 | `research_condition_jockey_pair_top3_rate_smoothed` | 말×기수 조합 입상률 완화값: (입상+2)/(출전+8) |
| 89 | `research_condition_burden_z5` | 현재 부담중량이 최근 최대 5회 중량 평균에서 몇 표준편차 떨어졌는지 |
| 90 | `research_condition_burden_performance_slope5` | 최근 유효 최대 5회 부담중량과 상대 착순 점수의 회귀 기울기. 기록 초/최적 중량/인과효과가 아님 |
| 91 | `research_condition_layoff_log1p` | log(1+직전 출전 이후 일수) |
| 92 | `research_condition_short_return_21d` | 출전 간격 21일 이하 여부 |
| 93 | `research_condition_long_layoff_90d` | 출전 간격 90일 이상 여부 |
| 94 | `research_condition_speed_variability_proxy` | 최근 5회 최고 속도지수−중앙값. 분산 자체는 아님 |
| 95 | `research_condition_speed_potential_gap` | 최근 5회 최고 속도지수−직전 지수. 잠재력/반등을 확정하지 않음 |
| 96 | `research_condition_speed_last_vs_avg3` | 직전 속도지수−최근 3회 평균 |

**초반 위치·선행 경쟁**

| 번호 | 코드명 | 의미·주의점 |
|---:|---|---|
| 97 | `research_pace_early_pos_pct_avg5` | 과거 검증 S1F 최근 최대 5회 상대순위 평균. 0이 앞, 1이 뒤 |
| 98 | `research_pace_early_pos_pct_std5` | 위 초반 상대순위의 표준편차. 최소 2회 필요 |
| 99 | `research_pace_late_gain_pct_avg5` | 과거 (S1F 순위−최종순위)/(전체 카드 두수−1) 평균. 양수면 순위 상승 |
| 100 | `research_pace_section_coverage5` | 최근 창의 검증 S1F 관측 수(최대 5) |
| 101 | `research_pace_field_available_count` | 현재 카드에서 초반 성향을 계산할 수 있는 말 수. 자기 포함 |
| 102 | `research_pace_front_runner_count` | 과거 초반 상대순위 평균 <0.35인 말 수. 자기 포함 |
| 103 | `research_pace_front_competition` | 현재 카드의 Σmax(0, 0.5−과거 초반 상대순위 평균) |
| 104 | `research_pace_self_front_advantage` | 상대마들의 과거 초반 상대순위 평균−자기 값. 양수면 자기의 앞선 경향 |

**성장·최근 변화·과거 상대 수준**

| 번호 | 코드명 | 의미·주의점 |
|---:|---|---|
| 105 | `research_v4_finish_pct_slope5` | 최근 최대 5회 (착순−1)/(카드두수−1)의 추세. 앞의 form 점수와 반대로 작을수록 좋으므로 음의 기울기가 개선 방향 |
| 106 | `research_v4_recent_vs_career_finish` | 최근 3회 위 상대순위 평균−누적 과거 평균. 음수면 최근 개선 방향 |
| 107 | `research_v4_opponent_elo_avg3` | 최근 유효 최대 3회에 상대했던 말들의 사전 Elo 평균 |
| 108 | `research_v4_opponent_elo_vs_current_field` | 최근 상대 Elo 평균−이번 상대 Elo 평균. 양수면 과거 상대가 더 강한 편 |
| 109 | `research_v4_age_center4` | 현재 나이−4. 실제 능력 정점이 4세라는 검증 결과가 아님 |
| 110 | `research_v4_age_experience` | (현재 나이−4)×log(1+과거 확정 출전행 수) |

**이 목록으로 설명할 수 있는 것과 없는 것**

보정 속도지수는 과거 최종 기록에서 `100×log(실제 속도/보정 기준속도)`로 만든다. 이전 730일 경마장·정확거리 기록에서 기준을 만들며, 표본이 충분하면 당시 주로 상태를 맞춘다. 과거 경주일의 전체 속도 편차 보정도 그날 이후 이력에서만 사용한다. 따라서 현재 모델을 “착순만 본다”고 설명하면 틀리지만, 이미 모든 구간·주행 손해·날씨 조건을 정밀하게 보정한다고 설명해도 틀리다.

게이트 변수에는 3년 및 최근 1년의 경마장×거리×구역 통계가 들어 있다. 최근 연구에서 확인한 분기별 변화를 그대로 입력하지 않으며, 주로 상태×게이트의 별도 통계나 통과조의 상대 내외측 위치도 이 110개에 없다. 기존 게이트 구역의 분모는 출마표 전체 두수다. 최근 게이트 감사에서는 실제 분석 대상의 게이트 순위를 사용했으므로 양쪽 정의도 같지 않다.

전개 8개는 주로 과거 S1F 통과순위 성향과 현재 편성의 선행 경쟁을 나타낸다. 원래 context_features.py는 부산 자체의 S1F 구간 이력을 제외했다. 새 운영 DB의 2017년 이후 정정 구간과 통과조는 기존 봉인 모델/학습 표본에 자동 반영되지 않는다. 따라서 서울과 부산에 같은 변수명이 있어도 정보 충실도가 같지 않다.

마체중과 부담중량은 다르다. **현재 마체중, 증감, 말별·거리별 적정 체중 이탈, 단기 변화와 휴양 중 변화는 이 110개에 포함되지 않는다.** 관련 후보를 연구한 것과 최종 기준 모델에 채택된 것은 구분해야 한다. 110개 중 중량 관련 항목은 기수를 포함해 말이 부담하는 중량 및 그 이력이다.

조교 강도·횟수, 진료·부상, 주행심사 세부 기록, 혈통, 모래 보충/정비일, 심판의 출발·진로방해 사건, 실제 코너 외곽 주행, 예시장 상태, 이번 경주의 날씨/함수율은 직접 입력하지 않는다. 기수·조교사·마주 ID가 있다는 사실이 이런 내용을 직접 분석한다는 뜻은 아니다. 또한 `potential_gap`이나 `growth`라는 이름이 잠재력·성장을 검증해 준다는 뜻도 아니다.

**데이터 분석을 먼저 하는 방향에 대한 판단**

분석과 원천 정리를 먼저 진행할 근거가 있다. 부산 구간 결손과 의미 정정, 게이트×거리×기간 차이, 출발 게이트와 실제 상대 주행위치의 구분처럼 기존 입력에서 개선할 지점이 확인됐다. 다만 이런 관찰이 예측 성능 향상을 보장하지 않는다. 이미 다른 변수가 같은 정보를 담았거나, 표본 부족·측정 오차·기간 한정 현상이라면 새 입력이 도움이 없거나 해로울 수 있다. 110개보다 적은 변수로도 더 나은 모델이 가능하고 더 많은 변수가 필요할 수도 있다.

분석 순서는 다음과 같이 제안한다. 기존 모델과 결과는 비교 기준으로 보존하며 새 모델을 이번 작업에서 학습하지 않는다.

1. **원천과 시점 정리:** 말·경주 키, 취소·동착·미완주, 거리별 구간 정의, 기록 단위와 결측, 원천 버전, 예측 시점에 공개되는 정보를 목록화한다. 현재110개의 입력 계약과 실제 결측을 함께 점검한다.
2. **질문별 관찰 분석:** 경마장×거리의 기준 기록 및 주로 빠르기 → 게이트×거리×상태×기간 → 과거 구간별 능력과 상대 주행위치 → 편성·선행 경쟁 → 부담중량·마체중·휴양 → 기수 조합·신마 순으로 질문을 나눈다. 말별 적정 체중은 반복 관측·나이·거리·휴양을 구분하며 관측 최고 체중을 최적치로 단정하지 않는다.
3. **가설 원장:** 관측 사실, 가능한 설명, 표본 수, 불확실성, 해당 조건 밖 재현성, 누수 위험, 다음 검증 방법을 기록한다. 특정 과거 기간의 유리함과 당시에 예측 가능했는지를 별도로 검증한다.
4. **입력 설계:** 말의 기본 능력, 거리 적성, 초반/종반 특성, 최근 상태, 이번 편성 적합성 및 정보 부족 정도를 수치화한다. 과거 경주 관측값과 이번 경주 예상값을 분리한다.
5. **최소 기준선과 비교:** 정정 원천으로 만든 같은110개 기준, 해석 가능한 소수 변수 기준, 기존 보존 모델을 비교한다. 원천 교체와 새 변수 추가의 효과를 분리한다.
6. **가설 단위 추가·제거:** 기본+게이트, 기본+전개처럼 단독 증분을 보고, 통과 후보를 결합한 뒤 결합 모델에서 각 그룹을 빼서 중복과 상호작용을 점검한다. 변수를 무조건 누적하지 않는다.
7. **목표별 시간순 평가:** A 한 말 입상, B 세 말 입상, C 정확한 순서를 각각 비교한다. 적중률과 확률 오차·확률 구간별 실제 적중률을 함께 보고 서울/부산·연도·거리별 안정성을 확인한다.

분석 전에 기간별 역할부터 정해야 한다. 평가 기간까지 보고 변수·기간·임계값을 고른 다음 같은 기간에서 성능을 재면 낙관적 편향이 생긴다. 각 시간순 평가 구간에서 통계 추정·전처리·후보 선택은 그 이전 자료에서 수행하는 것이 원칙이다. [scikit-learn 누수 방지 설명](https://scikit-learn.org/stable/common_pitfalls.html#data-leakage), [시간순 교차검증](https://scikit-learn.org/stable/modules/cross_validation.html#time-series-split).

현재 2021~2026년 자료는 이미 여러 번 분석했으므로 새 분할을 만들어도 완전히 새로운 독립 검증으로 되돌릴 수는 없다. 기존 자료에서 가설·설정을 고정하고 여러 시간순 구간의 일관성을 비교하는 후향적 연구는 계속할 수 있다. 새 자료를 기다릴 필요는 없지만 결과를 검증되지 않은 미래 성능으로 표현하지 않는다.

**근거 파일**

- [실제110개 허용 목록](/Users/kimyongjin/Desktop/horse_racing/data/research/thoroughbred_followup_20260918_v4/model/candidate_features.json)
- [A 저장 모델 메타데이터](/Users/kimyongjin/Desktop/horse_racing/data/research/thoroughbred_offline_20260918_v5/windows/models/2026H2/rolling_all/metadata.json)
- [B/C 기본 점수 저장 모델 메타데이터](/Users/kimyongjin/Desktop/horse_racing/data/research/thoroughbred_followup_20260918_v4/model/models/2026/top3_growth_strength/metadata.json)
- [순서축 모델 메타데이터](/Users/kimyongjin/Desktop/horse_racing/data/research/thoroughbred_win_research_20260918_v2/models/2026/H3_relative/metadata.json)
- [V4 추가6개 실행 코드](/Users/kimyongjin/Desktop/horse_racing/data/research/thoroughbred_followup_20260918_v4/model/code/run_v4_model.py)
- [최종 유지 결정](/Users/kimyongjin/Desktop/horse_racing/data/research/thoroughbred_seed_ensemble_20260925_v13/REPORT.md)
