# 제주 관계 모델: gained/lost 경주 후향 분석

## 요약과 해석 범위

저장된 baseline과 candidate의 1,779개 평가 경주를 비교했다. 두 arm은 각 경주에서 삼복승 후보 조합을 정확히 6개 선택한다. 이 기간은 앞선 모델 개발·평가에서 이미 사용됐으므로 이 문서는 새로운 사전등록, 확증 분석, 독립 홀드아웃 결과가 아니다. 고정된 저장 파라미터와 산출물만 재현·기술했고, 모델 재학습이나 계수·threshold 조정, 운영·DB 변경은 하지 않았다.

후보는 baseline보다 적중 경주가 16개 많았다(407→423, +0.90%p). 날짜 단위 paired bootstrap 95% 구간은 −0.11~+1.90%p로 0을 포함한다. 50개가 baseline miss→candidate hit, 34개가 hit→miss로 바뀌었고, 373개는 두 arm 모두 적중, 1,322개는 모두 미적중이었다. 따라서 이 결과만으로 평균 성능 개선이 확인됐다고 결론내릴 수는 없다.

84개 사례에서는 정답 Top3 조합의 순위가 실제로 재배치됐다. Gained 50개에서 평균 순위는 9.22→4.88(중앙값 9→5, 범위 7–18→2–6), lost 34개에서는 5.44→8.94(중앙값 6→8, 범위 2–6→7–25)였다. 이 이동만으로 확신이나 예측 신뢰도가 커졌다고 볼 수는 없다. 6–7위 에너지 간격과 전체 조합 확률 집중도는 gained/lost에서 일관된 방향을 보이지 않았다.

전체 1,779개에서 저장된 평가 score gap 및 T−2 cutoff가 적용된 과거 경력·거리이력·스타일 지원량을 기술 비교했으나, gained와 lost를 안정적으로 가르는 적용 조건은 확인되지 않았다. cutoff 날짜 필드는 오류가 없지만 첫 공개 시각까지 검증한 것은 아니다. 같은 이벤트의 체중·부담·주로 수분은 결과-side context이며 당시 예측 마감 전 공개 여부가 검증되지 않았다. 이 정보로 예측 규칙을 만들거나 추천하지 않는다.

## 코호트와 주요 분모

| 범위 | 경주 | 실제 관측 날짜 수 | 관측 기간 |
|---|---:|---:|---|
| 전체 고정 코호트 | 1,779 | 269 | 2024-01-05–2026-09-19 |
| 2024 | 637 | 98 | 2024-01-05–2024-12-28 |
| 2025 | 654 | 98 | 2025-01-03–2025-12-27 |
| 2026 | 488 | 73 | 2026-01-02–2026-09-19, 부분 연도 |

전체 코호트는 17,412개 출전 행과 402,808개 저장 triple row를 포함한다. 17,412는 고유한 말 수가 아니다. 연도별 후보 모델은 별도 fold 파라미터를 썼으며 β와 H2 temperature가 연도별로 다르다. 그러므로 연도별 net 차이를 계절·거리 구성만의 결과로 돌릴 수 없다. 2026은 부분 연도이며 연도별 추정치는 기술 비교다.

| 연도 | baseline 적중 | candidate 적중 | gained | lost | net | 차이(%p) | 날짜 paired 95% CI(%p) |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2024 | 150 | 147 | 12 | 15 | −3 | −0.47 | −2.16~+1.15 |
| 2025 | 138 | 153 | 25 | 10 | +15 | +2.29 | +0.63~+3.98 |
| 2026 부분 | 119 | 123 | 13 | 9 | +4 | +0.82 | −1.04~+2.75 |
| 전체 | 407 | 423 | 50 | 34 | +16 | +0.90 | −0.11~+1.90 |

연간 candidate 차이는 같은 방향으로 반복되지 않았다. 더구나 fold별 관계 파라미터·temperature가 달라 연도차를 환경 구성 변화로만 설명할 수 없다.

## 조건별 기술 비교

아래 거리는 원자료의 정확한 거리값별 분모다. 차이는 candidate hit rate−baseline hit rate이며 구간은 날짜 단위 paired bootstrap의 pointwise 95% 범위다. 소표본 구간과 여러 조건 비교를 고려해야 한다.

| 거리 | 경주 | gained/lost | net | 차이(%p) | 95% CI(%p) |
|---:|---:|---:|---:|---:|---:|
| 800m | 152 | 3/2 | +1 | +0.66 | −2.01~+3.42 |
| 900m | 251 | 4/3 | +1 | +0.40 | −1.61~+2.48 |
| 1000m | 508 | 14/15 | −1 | −0.20 | −2.31~+1.83 |
| 1110m | 482 | 11/4 | +7 | +1.45 | −0.20~+3.07 |
| 1200m | 262 | 12/7 | +5 | +1.91 | −1.17~+5.12 |
| 1300m | 63 | 5/0 | +5 | +7.94 | +1.59~+15.87 |
| 1400m | 52 | 1/3 | −2 | −3.85 | −11.54~+3.85 |
| 1610m | 9 | 0/0 | 0 | 0.00 | 0.00~0.00 |

1300m의 양의 차이는 63개에 기반하며, 연도별 표본은 2024년 8개, 2025년 35개, 2026년 20개다. 이를 거리별 채택 규칙으로 바꾸지 않는다. 1610m는 9개 경주에서 두 arm 모두 적중이 없어 CI가 0~0으로 퇴화했으며 효과가 정확히 0이라는 증거가 아니다. 편성두수 11+도 2경주뿐이다. 전체 등급·월·편성두수 및 거리 표는 [condition_summary.csv](outputs/condition_summary.csv)에 있다. 등급과 실제 출전 두수는 사후 경주 기술값이며 마감 시점 가용성이 검증되지 않아 예측 조건으로 부르지 않는다.

분석계획에 추가된 고정 교차표는 [연도×거리](outputs_followup_addendum/year_distance_condition_summary.csv)와 [연도×수분 band](outputs_followup_addendum/year_moisture_band_condition_summary.csv)다. 각 표가 2024/2025/2026의 전체 경주를 각각 빠짐없이 나누며, 조건 분모와 전체 1,779 대비 비중을 함께 제공한다. 거리별 24개 칸 중 2024년 1610m는 0개이고, 나머지 작은 칸은 분모가 얇다. 이 표는 설명용이며 threshold 선택이나 확증 검정이 아니다.

수분은 결과-side context CSV의 다섯 고정 범주를 경주 단위로 연결했다. 전체 1,779경주에서 건조 783, 양호 297, 다습 389, 포화 185, 불량 125개다.

| 수분 band | 경주 | gained/lost | net | 차이(%p) | 날짜 paired 95% CI(%p) |
|---|---:|---:|---:|---:|---:|
| 건조 | 783 | 27/17 | +10 | +1.28 | −0.38~+2.99 |
| 양호 | 297 | 9/7 | +2 | +0.67 | −1.87~+3.45 |
| 다습 | 389 | 8/6 | +2 | +0.51 | −1.35~+2.40 |
| 포화 | 185 | 4/3 | +1 | +0.54 | −2.26~+3.33 |
| 불량 | 125 | 2/1 | +1 | +0.80 | −1.72~+3.74 |

다섯 구간의 pointwise 날짜 구간은 모두 0을 포함한다. band의 연도별 순증은 건조에서 −1, +8, +3으로 달랐고, 연도×band 전체 counts는 교차표를 참조한다. 이 수분은 같은 경주 시점의 사후 설명값이며 예측 마감 전 공개 여부를 확인하지 못했다.

## 순위 이동, 경계 간격, 관계 항

정답 세 마리의 비순서 조합을 각 arm에서 추적했다. gained에서는 정답이 candidate top6 안으로 들어왔고 lost에서는 밖으로 나갔지만, 모든 변화가 단순 6↔7 순위 교체는 아니었다. 84건 ledger와 1,779개 race ledger에 전 사례를 담았다.

rank-6 minus rank-7 energy margin의 평균은 gained에서 baseline 0.0592→candidate 0.0405, lost에서 0.0320→0.0422였다. triple entropy 평균은 gained 4.300→4.302, lost 4.222→4.224로 거의 변하지 않았다. 에너지 margin 0은 동점이고 저장된 stable order가 순위를 정한다. 전체 1,779경주에서 baseline exact/tolerance tie가 각각 83건, candidate exact tie 81건·절대 margin 1e-12 이내가 84건이었다. 경계 교체는 top6 절단 구조에서 예상되는 현상이며, 그 자체를 추가적인 신호로 보지 않는다.

Candidate에서 정답 조합 T와 정답을 제외한 최고 경계 경쟁 조합 U를 비교한 사후 에너지 분해도 저장했다. T가 top6 안이면 U는 candidate rank 7, 밖이면 rank 6이다. 에너지 순위는 큰 쪽이 앞선다.

| 사례 | E(T)−E(U) 평균 | baseline score-energy 차 | 관계에너지 차 | 관계 중 style-mean 3항 | 관계 중 support-count 3항 |
|---|---:|---:|---:|---:|---:|
| gained (n=50) | +0.114 | −0.102 | +0.216 | +0.109 | +0.121 |
| lost (n=34) | −0.118 | +0.044 | −0.162 | −0.089 | −0.076 |

이는 gained/lost를 사후 분류한 경주에서 정답과 해당 boundary competitor의 항별 합을 비교한 대수적 진단이다. 실제 후보선택을 설명하는 유일 원인이나 인과효과가 아니다. 서로 상관된 11항은 중복된 신호를 공유할 수 있어 개별 beta의 독립 의미를 부여하지 않는다. 11개 항 전체 및 네 묶음 합계는 [true_set_beta_contributions.csv](outputs/true_set_beta_contributions.csv), [beta_group_decomposition_by_outcome.csv](outputs/beta_group_decomposition_by_outcome.csv), [true_set_boundary_competitor_1779.csv](outputs/true_set_boundary_competitor_1779.csv)에 있다. 그룹 기여 평균은 row 단위 합으로 확인했으며 그룹별 median들의 합은 total median과 같다고 해석하지 않는다.

## T−2 과거 이력·저장 말 평가와 별도 context

저장된 평가 score gap 및 T−2 cutoff를 적용한 과거이력 요약을 1,779 전체와 사후 hit class별로 비교했다. Gained/lost의 rank-1 대 rank-2 score gap을 경주 내 score 표준편차로 나눈 평균은 0.932 대 0.752였다. 반면 career starts 5+ 비중은 86.9% 대 87.5%, same-distance 최근 5개 슬롯의 actual support 평균은 3.35 대 3.57, style-support 평균은 10.01 대 10.60, 세 style 평균 간 heterogeneity는 1.125 대 1.108이었다. 50/34 경주 사후 집단에서 보이는 작은 차이이며 후보 조건으로 최적화하지 않았다. raw score gap은 fold별 scale 차이가 있어 경주 내 표준편차 정규화 결과와 같이 봤다.

same_starts와 same_valid_times는 저장 피처가 보유한 과거 조회범위 안의 전체 동일거리 이력 수이고, same_distance_last5_actual_n 및 same_distance_last5_normal_n은 가장 최근 5개 history 슬롯의 지원 수다. 이번 target에서 보유 과거 조회범위 내 관측 수 평균은 출전 행 단위 7.71이며 최근 5개 actual 슬롯 지원 평균은 3.27이었다. 정의가 다르므로 서로 대체하지 않으며, 조회범위 밖의 말 이력까지 포함한 생애 census로 해석하지 않는다. 첫 summary의 파일명과 계약 문구에서 lifetime 표현을 사용한 것은 범위 과장이었다. 숫자 자체는 유지했고, 범위를 명시한 [정정 history 표](outputs_followup_addendum/same_distance_support_available_range_corrected.csv)와 [교정 receipt](outputs_followup_addendum/history_scope_correction_receipt.json)가 이를 대체한다.

T−2 timing 감사에서는 17,412개 출전 행 모두의 history_cutoff가 race_date−2일과 같았고, 그보다 최근인 cutoff는 0행이었다. history_cutoff 누락 0, cutoff가 경주 뒤인 행 0, latest_history_date가 cutoff 뒤인 행 0이었다. latest_history_date 자체는 661개 행에서 누락됐다. 이 검사는 저장 date field의 순서만 확인하며, 원천 관측값의 최초 공개 시각을 증명하지 않는다. 전체 값은 [history_timing_audit.json](outputs/history_timing_audit.json)에 있다.

스타일 값은 측정 구간 사이의 상대 순위 위치 변화다. 양의 forward 값은 다음 측정 지점에서 상대 순위가 나아졌다는 뜻이지 속도, 결승 기록, 순수 추입력을 의미하지 않는다. 1300m는 출발→2C→S1F 관측 구간이 다른 거리와 다르므로 같은 초반 구간으로 해석하지 않았다. 거리·연도 구성표와 소표본도 함께 고려해야 한다.

보충 context는 17,412개 API record ID와 1,779개 race ID 모두를 1:1 대조했고, 수분/band가 경주 내 상수임을 확인했다. 체중·부담 평균, 모집단 표준편차, 부담/체중 비율은 먼저 출전마를 경주 단위로 집계한 뒤 경주들을 비교했다(말 수를 독립 경주 표본처럼 취급하지 않음). gained 50경주의 경주 평균 body mass는 277.0kg, lost 34경주는 278.7kg이었다. 이 차이는 결과-side 기술통계이며 예측 시점 입력 가용성도, 관계 모델의 조건 효과도 증명하지 않는다. 현재 기수 ID별 효과·규칙은 분석하지 않았고, horse_number는 물리적 gate로 검증되지 않았다. 실제 Top3 세 마리의 체중/부담은 gained/lost 84경주 안에서만 별도 저장했다. 본문에서 사용하는 최종 race-level summary는 [feature 이름·단위가 포함된 v2 표](outputs_followup_addendum/actual_top3_context_summary_corrected_v2.csv)다.

첫 supplemental summary [actual_top3_context_summary.csv](outputs_supplemental/actual_top3_context_summary.csv)는 all_1779 라벨로 84개 discordant 경주만 요약하고 빈 both-hit/both-miss 행도 포함하는 표기 오류가 있었다. 이어 만든 corrected v1은 scope를 바로잡았으나 feature 이름 열이 빠져, 이를 보완한 v2를 최종 표로 지정한다. 이전 두 파일은 감사용으로 보존했고 본문에서는 v2만 사용한다. [v2 교정 receipt](outputs_followup_addendum/top3_summary_feature_label_correction_receipt.json)는 v1의 수치가 기존 gained/lost feature별 요약과 일치하고 v2가 feature 열을 추가했음을 기록한다.

## 다음 학습·검증 가설

이 후향 결과로 운영 조건을 제안하지 않는다. 다음 별도 학습·검증에서 다룰 가설은 두 가지다.

1. Runner score와 same-six 비교틀은 고정하고 style-mean 차이 3항과 support-count 차이 3항을 분리 ablation 또는 shrinkage해, 둘 중 어떤 묶음이 완전히 미관측한 뒤 기간에서 재현되는지 비교한다. 84개의 사후 분해는 이 검증을 설계할 이유일 뿐 결과 예측이 아니다.
2. 특정 거리 한 곳을 고르는 대신 지원이 있는 year×distance mix를 표준화하고, 관계 강도에 pooled/shrunken context 변화를 둘 수 있는지 미관측 기간에서 시험한다. 1300m·1400m·1610m의 작은 cell을 독립 채택 근거로 쓰지 않는다.

현재 평가기간을 확증자료로 재사용하지 않는다. 향후 가설을 시험하기 전에는 feature 시점 가용성과 교차 기간 설계를 별도로 고정해야 한다.

## 재현·산출물

실행은 저장 산출물과 현재 helper를 대상으로 한 no-fit 재현이며 fitting 함수는 실행하지 않았다. core script는 전체 저장 triple의 energy 재현을 확인했다. helper 무결성 파일은 core 실행 후 현재 import된 joint_model.py와 고정 source manifest를 대조한 검사라서, core 실행 당시 사전 검사로 주장하지 않는다.

- 고정 core 계획·입력: [ANALYSIS_PLAN.md](ANALYSIS_PLAN.md), [INPUT_CONTRACT.json](INPUT_CONTRACT.json)
- 84건 전체 및 전체분모: [race_ledger_1779.csv](outputs/race_ledger_1779.csv), [gain_loss_84.csv](outputs/gain_loss_84.csv)
- 조건·연속피처: [condition_summary.csv](outputs/condition_summary.csv), [continuous_features_by_outcome.csv](outputs/continuous_features_by_outcome.csv), [feature_missingness_by_outcome.csv](outputs/feature_missingness_by_outcome.csv)
- 정답 조합·경계·분해: [selection_boundary_detail_1779.csv](outputs/selection_boundary_detail_1779.csv), [true_set_boundary_competitor_1779.csv](outputs/true_set_boundary_competitor_1779.csv), [beta_decomposition_by_outcome.csv](outputs/beta_decomposition_by_outcome.csv), [beta_group_decomposition_by_outcome.csv](outputs/beta_group_decomposition_by_outcome.csv)
- 결과-side context 분석 계약·표: [SUPPLEMENTAL_CONTEXT_PLAN.md](SUPPLEMENTAL_CONTEXT_PLAN.md), [SUPPLEMENTAL_CONTEXT_CONTRACT.json](SUPPLEMENTAL_CONTEXT_CONTRACT.json), [SAVED_HISTORY_EXTENSION_CONTRACT.json](SAVED_HISTORY_EXTENSION_CONTRACT.json), [moisture_band_condition_summary.csv](outputs_supplemental/moisture_band_condition_summary.csv), [race_context_by_outcome.csv](outputs_supplemental/race_context_by_outcome.csv), [정정 history 표](outputs_followup_addendum/same_distance_support_available_range_corrected.csv)
- 후속 교정·교차표 계약·표: [FOLLOWUP_ADDENDUM_PLAN.md](FOLLOWUP_ADDENDUM_PLAN.md), [FOLLOWUP_ADDENDUM_CONTRACT.json](FOLLOWUP_ADDENDUM_CONTRACT.json), [year_distance_condition_summary.csv](outputs_followup_addendum/year_distance_condition_summary.csv), [year_moisture_band_condition_summary.csv](outputs_followup_addendum/year_moisture_band_condition_summary.csv), [actual_top3_context_summary_corrected_v2.csv](outputs_followup_addendum/actual_top3_context_summary_corrected_v2.csv)
- context 원천가용성 근거: [CONDITION_AVAILABILITY_AUDIT.md](../20261010_joint_gain_loss_context_v1/CONDITION_AVAILABILITY_AUDIT.md), [context ARTIFACT_MANIFEST.json](../20261010_joint_gain_loss_context_v1/ARTIFACT_MANIFEST.json), [verify_receipt.json](../20261010_joint_gain_loss_context_v1/verify_receipt.json)
- 독립 검토: [C 독립 분석 receipt](../20261010_joint_gain_loss_review_v1/outputs/independent_analysis_output_receipt.json)
- 원천/결과 검증: [analysis_receipt.json](outputs/analysis_receipt.json), [supplemental_receipt.json](outputs_supplemental/supplemental_receipt.json), [followup_receipt.json](outputs_followup_addendum/followup_receipt.json), [HELPER_INTEGRITY_AUDIT.json](HELPER_INTEGRITY_AUDIT.json), 최종 [ARTIFACT_MANIFEST.json](ARTIFACT_MANIFEST.json)

모든 CI는 날짜 cluster를 복원 단위로 한 2,000회 bootstrap, seed 20261008의 pointwise 구간이다. 작은 분모와 여러 비교를 감안해야 한다.
