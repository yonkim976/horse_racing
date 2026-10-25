# 축 붕괴 사전 예측 — 더러브랫 연구

2026-10-09 완료. **과거 구간·각질·상대 비교를 더한 붕괴 학습의 추가 개선 근거를 확인하지 못했다. 고위험이라고 원축을 제외한 정책은 적중이 감소했다.** 축은 현재 선택 연구모델 `month_gate_weight22` 점수 1위 말이며 붕괴는 **실제 3위 밖**이다. 전개상 선행 실패와 다르다. 운영 모델의 축을 직접 예측한 실험은 아니다.

2024–2026년 동일 **4,799경주**, 원축 붕괴 **1,937경주(40.36%)**다. 새 위험 학습의 주 정책은 기존 축자유6개 대비 **-0.104%p**, 날짜 군집95% 구간 **-0.447~+0.245%p**다. 위험 Brier 차이는 **-0.000020**(작을수록 좋음, 구간 -0.001806~+0.001758)다. 두 지표를 구분하여 판단한다.

## 위험을 어떻게 예측했는가

기본 모델22개의 학습은 2017년부터이며 이전 자료는 기존 이력 구축에만 쓰인 동결 입력을 재사용했다. 2020–2023년 축을 만드는 기본 모형8개는 각 평가연도 Y−2까지 학습, Y−1 삼복분포 온도보정으로 별도 생성했다. 2024–2026년 기본 모형6개는 원본과 점수가 완전히 일치한다.

위험 모형은 2020–Y−3 학습, Y−2 조기종료, Y−2까지 재학습, Y−1 Platt 확률보정, Y년 평가했다. 각 과거 학습 축도 해당 경주 이후 자료를 보지 않은 OOF 축이다. `base_raw`는 기존 공동분포의 1−축입상확률, `base_cal`은 이것만 전년도 확률보정, `score`는 점수 차이·분산·집중도 10개, `context`는 이 점수 변수와 축의 보정기록·부중·구간·각질 및 자기 제외 상대 비교 등 90개다. 기수/조교사와 현재 결과·현재 구간·현재 통과조는 입력하지 않았다. 현재 마번과 상대 게이트 위치는 사전 대리변수이며 실제 주행경로가 아니다.

과거 S1F/G3F/G1F 기록과 통과조 성향은 기존53개 이력 계약 그대로 사용했다. 새 경주의 선행/추입을 확정한 값이 아니며, 알려지지 않은 현재 전술 의도를 관측한 것도 아니다. 원본 전체/구간 보정은 이번에 재추정하지 않았다.

| variant | races | actual_risk | mean_risk | auc | brier | logloss |
| --- | --- | --- | --- | --- | --- | --- |
| base_raw | 4799 | 0.4036 | 0.4041 | 0.6178 | 0.2303 | 0.6520 |
| base_cal | 4799 | 0.4036 | 0.4087 | 0.6169 | 0.2305 | 0.6524 |
| context | 4799 | 0.4036 | 0.4083 | 0.6179 | 0.2303 | 0.6519 |
| score | 4799 | 0.4036 | 0.4090 | 0.6054 | 0.2320 | 0.6557 |

AUC는 0.5가 무작위 구분, Brier/logloss는 작을수록 좋다. 확률의 평균이 맞는 것과 개별 붕괴를 잘 찾아내는 것은 다르다.

## 위험 신호의 정확도

위험 신호 문턱은 각 전년도 보정 예측의70백분위다. 평가연도 결과를 보고 상위30%를 골라낸 것이 아니므로 실제 선택 비율은30%와 다를 수 있다. precision은 신호를 보낸 경주 중 실제 붕괴 비율, recall은 전체 붕괴 중 포착 비율이다. 낮은 위험에서도 붕괴는 남는다.

| variant | races | flagged | coverage | predicted_risk | collapse_precision | collapse_recall |
| --- | --- | --- | --- | --- | --- | --- |
| base_cal | 4799 | 1427 | 0.2974 | 0.5221 | 0.5151 | 0.3795 |
| context | 4799 | 1434 | 0.2988 | 0.5295 | 0.5181 | 0.3836 |
| score | 4799 | 1418 | 0.2955 | 0.5075 | 0.5035 | 0.3686 |

전체 위험 구간별 실제 붕괴율은 [risk_bins.csv](outputs/risk_bins.csv)에 있다.

## 같은6조합으로 연결한 결과

`fixed7`: 원축+상대6두에서 최고6개. `global6`: 원축 강제 없이 전 출전마의 기존 공동확률 최고6개. `trigger_free`: 고위험 때만 global6. `trigger_exclude`: 고위험 때만 원축이 없는 조합6개. `reweight`: 모든 경주에서 축포함 조합의 합을1−새 붕괴확률로, 미포함 조합의 합을 새 붕괴확률로 맞춘 뒤 최고6개. 재배분은 각 집합 안의 상대 확률은 유지하므로 새로운 동반관계를 학습한 것은 아니다. 모든 정책은 경주당 정확히6개다.

| policy | races | hits | hit_percent |
| --- | --- | --- | --- |
| base_cal_reweight | 4799 | 1229 | 25.6095 |
| base_cal_trigger_exclude | 4799 | 1125 | 23.4424 |
| base_cal_trigger_free | 4799 | 1205 | 25.1094 |
| context_reweight | 4799 | 1223 | 25.4845 |
| context_trigger_exclude | 4799 | 1109 | 23.1090 |
| context_trigger_free | 4799 | 1205 | 25.1094 |
| fixed7 | 4799 | 1204 | 25.0886 |
| global6 | 4799 | 1228 | 25.5887 |
| score_reweight | 4799 | 1224 | 25.5053 |
| score_trigger_exclude | 4799 | 1112 | 23.1715 |
| score_trigger_free | 4799 | 1212 | 25.2553 |

| candidate | control | metric | difference | ci_low | ci_high | rescued | lost |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base_cal_reweight | fixed7 | — | 0.0052 | 0.0004 | 0.0102 | 80.0000 | 55.0000 |
| base_cal_reweight | global6 | — | 0.0002 | -0.0015 | 0.0019 | 11.0000 | 10.0000 |
| base_cal_trigger_exclude | fixed7 | — | -0.0165 | -0.0244 | -0.0087 | 136.0000 | 215.0000 |
| base_cal_trigger_exclude | global6 | — | -0.0215 | -0.0302 | -0.0131 | 149.0000 | 252.0000 |
| base_cal_trigger_free | fixed7 | — | 0.0002 | -0.0025 | 0.0029 | 20.0000 | 19.0000 |
| base_cal_trigger_free | global6 | — | -0.0048 | -0.0086 | -0.0010 | 31.0000 | 54.0000 |
| context_reweight | fixed7 | — | 0.0040 | -0.0014 | 0.0095 | 92.0000 | 73.0000 |
| context_reweight | global6 | — | -0.0010 | -0.0045 | 0.0025 | 37.0000 | 42.0000 |
| context_trigger_exclude | fixed7 | — | -0.0198 | -0.0277 | -0.0121 | 146.0000 | 241.0000 |
| context_trigger_exclude | global6 | — | -0.0248 | -0.0337 | -0.0166 | 164.0000 | 283.0000 |
| context_trigger_free | fixed7 | — | 0.0002 | -0.0021 | 0.0027 | 18.0000 | 17.0000 |
| context_trigger_free | global6 | — | -0.0048 | -0.0087 | -0.0010 | 33.0000 | 56.0000 |
| score_reweight | fixed7 | — | 0.0042 | -0.0008 | 0.0091 | 79.0000 | 59.0000 |
| score_reweight | global6 | — | -0.0008 | -0.0037 | 0.0021 | 24.0000 | 28.0000 |
| score_trigger_exclude | fixed7 | — | -0.0192 | -0.0273 | -0.0116 | 138.0000 | 230.0000 |
| score_trigger_exclude | global6 | — | -0.0242 | -0.0334 | -0.0160 | 158.0000 | 274.0000 |
| score_trigger_free | fixed7 | — | 0.0017 | -0.0006 | 0.0040 | 20.0000 | 12.0000 |
| score_trigger_free | global6 | — | -0.0033 | -0.0072 | 0.0004 | 38.0000 | 54.0000 |
| base_cal | base_raw | brier | 0.0001 | -0.0002 | 0.0005 | — | — |
| base_cal | base_raw | logloss | 0.0004 | -0.0004 | 0.0011 | — | — |
| context | base_raw | brier | -0.0000 | -0.0018 | 0.0018 | — | — |
| context | base_raw | logloss | -0.0001 | -0.0040 | 0.0037 | — | — |
| score | base_raw | brier | 0.0017 | 0.0005 | 0.0028 | — | — |
| score | base_raw | logloss | 0.0037 | 0.0011 | 0.0061 | — | — |

조합 차이는 비율 단위다(0.01=1%p). CI는 날짜를 단위로2,000회 paired bootstrap한95% 구간이며 여러 후보/하위군에 대한 다중비교 보정은 없다. 주 비교는 미리 고정했다. 가장 좋아 보이는 정책을 선택/승격하지 않았다.

## 구조한 경주와 잘못 버린 경주

아래는 fixed7 대비 변화이며 실제 붕괴 여부는 **사후 진단용**이다. 정책 선택에 실제 붕괴 여부를 넣지 않았다. collapsed=0에서 잃은 적중은 원축이 살아왔는데 위험 판단/조합변경으로 놓친 비용이다. collapsed=1에서 구조한 경주는 실제 축 붕괴를 살린 적중이다.

| variant | action | collapsed | races | flagged | rescued | lost | candidate_hits | baseline_hits |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| base_cal | trigger_free | 0 | 2862 | 692 | 2 | 19 | 1187 | 1204 |
| base_cal | trigger_free | 1 | 1937 | 735 | 18 | 0 | 18 | 0 |
| base_cal | trigger_exclude | 0 | 2862 | 692 | 0 | 215 | 989 | 1204 |
| base_cal | trigger_exclude | 1 | 1937 | 735 | 136 | 0 | 136 | 0 |
| base_cal | reweight | 0 | 2862 | 692 | 23 | 55 | 1172 | 1204 |
| base_cal | reweight | 1 | 1937 | 735 | 57 | 0 | 57 | 0 |
| context | trigger_free | 0 | 2862 | 691 | 3 | 17 | 1190 | 1204 |
| context | trigger_free | 1 | 1937 | 743 | 15 | 0 | 15 | 0 |
| context | trigger_exclude | 0 | 2862 | 691 | 0 | 241 | 963 | 1204 |
| context | trigger_exclude | 1 | 1937 | 743 | 146 | 0 | 146 | 0 |
| context | reweight | 0 | 2862 | 691 | 22 | 73 | 1153 | 1204 |
| context | reweight | 1 | 1937 | 743 | 70 | 0 | 70 | 0 |
| score | trigger_free | 0 | 2862 | 704 | 2 | 12 | 1194 | 1204 |
| score | trigger_free | 1 | 1937 | 714 | 18 | 0 | 18 | 0 |
| score | trigger_exclude | 0 | 2862 | 704 | 0 | 230 | 974 | 1204 |
| score | trigger_exclude | 1 | 1937 | 714 | 138 | 0 | 138 | 0 |
| score | reweight | 0 | 2862 | 704 | 23 | 59 | 1168 | 1204 |
| score | reweight | 1 | 1937 | 714 | 56 | 0 | 56 | 0 |

모든 경주의 변경 기록을 [action_events.parquet](outputs/action_events.parquet), 전체6조합을 [six_tickets.parquet](outputs/six_tickets.parquet)에 보존했다. 성공 사례만 골라 제시하지 않았다.

## 연도·지역과 변수 사용

| scope | policy | races | hits | hit_rate |
| --- | --- | --- | --- | --- |
| 2024 | context_reweight | 1761 | 448 | 0.2544 |
| 2024 | context_trigger_exclude | 1761 | 405 | 0.2300 |
| 2024 | context_trigger_free | 1761 | 437 | 0.2482 |
| 2024 | fixed7 | 1761 | 433 | 0.2459 |
| 2024 | global6 | 1761 | 444 | 0.2521 |
| 2025 | context_reweight | 1750 | 416 | 0.2377 |
| 2025 | context_trigger_exclude | 1750 | 400 | 0.2286 |
| 2025 | context_trigger_free | 1750 | 414 | 0.2366 |
| 2025 | fixed7 | 1750 | 417 | 0.2383 |
| 2025 | global6 | 1750 | 423 | 0.2417 |
| 2026 | context_reweight | 1288 | 359 | 0.2787 |
| 2026 | context_trigger_exclude | 1288 | 304 | 0.2360 |
| 2026 | context_trigger_free | 1288 | 354 | 0.2748 |
| 2026 | fixed7 | 1288 | 354 | 0.2748 |
| 2026 | global6 | 1288 | 361 | 0.2803 |
| Seoul | context_reweight | 2838 | 749 | 0.2639 |
| Seoul | context_trigger_exclude | 2838 | 680 | 0.2396 |
| Seoul | context_trigger_free | 2838 | 739 | 0.2604 |
| Seoul | fixed7 | 2838 | 740 | 0.2607 |
| Seoul | global6 | 2838 | 757 | 0.2667 |
| Busan | context_reweight | 1961 | 474 | 0.2417 |
| Busan | context_trigger_exclude | 1961 | 429 | 0.2188 |
| Busan | context_trigger_free | 1961 | 466 | 0.2376 |
| Busan | fixed7 | 1961 | 464 | 0.2366 |
| Busan | global6 | 1961 | 471 | 0.2402 |

context 모델이 분할에 사용한 gain 상위 변수(연도별 합)는 아래와 같다. 원인·영향방향·인과효과를 뜻하지 않으며 대체 입력과 중복될 수 있다.

| feature | gain |
| --- | --- |
| base_risk | 6317.5095 |
| score_entropy | 2766.5113 |
| axis_gap_moist_last3_record_index_mean | 1868.3936 |
| axis_section_same_distance_n5 | 1695.7893 |
| axis_gap_style_role0_rate5 | 1315.3437 |
| field_front_mass | 1301.8159 |
| axis_style_group_mean_relative_mean5 | 1123.6947 |
| axis_style_gain400_mean5 | 1006.5448 |
| axis_moist_last_record_index | 961.5211 |
| axis_moist_last5_record_index_best | 874.0271 |
| axis_gap_section_late_mean3 | 867.0985 |
| gap15 | 850.7536 |

## 검증과 적용 범위

기본 모형14개/새 위험 모형6개 재예측, 전년도 보정·문턱, 52,789 경주-정책/316,734조합 전수 독립 재구성, 결과 변조 불변성, 기준선1,204/1,228적중 재현, 원본 해시 보존을 통과했다. [검증](outputs/verification.json).

이미 여러 연구에서 본2024–2026년을 재사용한 후향 평가다. 전후 학습 누수 방지는 새 미사용 검증기간을 대신하지 못한다. 원천의 당일 부담중량 PIT 검증 미완료 한계도 그대로다. 위험 구분의 개선과6조합 적중 개선, 수익률 개선은 각각 다른 주장이다. 배당/수익률은 이번에 검증하지 않았다. `month_gate_weight22` 선택과 운영 레지스트리는 유지했고 제주·DB에 접근하지 않았다.

[사전 계획](PLAN.md) · [입력 계약](outputs/feature_contract.json) · [연도/지역 결과](outputs/summary.csv) · [paired 차이](outputs/paired_differences.csv) · [판정](outputs/decision.json) · [용량](outputs/artifact_inventory.json).
