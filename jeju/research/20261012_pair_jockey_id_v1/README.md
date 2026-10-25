# 제주 F1_STYLE6 두 말 동시 Top3 pair 기수 ID categorical 비교

저장 F1_STYLE6 말 점수와 기존 20 style pair basis, rolling365 jockey scalar·moments를 고정하고, 각 fold H1에서만 정의한 공식 기수 ID categorical main effect 39열을 추가해 기존 21열과 함께 joint fit했다. H1 pair moments는 경주 균등이며 `W_r=(u_r−K*pi_r)/sigma_r`; H1 밖 ID의 categorical runner effect는 0이다. 최소 H1 support는 52 eligible starts였고 rare pooling은 하지 않았다. 기수 ID 값의 크기와 이름은 입력으로 쓰지 않았다.

평가 코호트는 1,779경주·269경주일·76,848 unordered pair다. 반복 개발기간이며 2026년은 9월까지의 부분연도다.

## 사전 지정 비교

Primary incremental: ID candidate 438/1779 − 저장 rolling candidate 429/1,779 = +0.506%p (date-bootstrap 95% CI +0.113~+0.903%p); 통과.
Secondary raw Top2: ID candidate 438/1779 − raw Top2 429/1,779 = +0.506%p (95% CI -0.112~+1.106%p); 미통과.
두 사전 gate 모두 통과: 아니오. 저장 rolling 대비 pair 선택이 다른 경주 50개 중 +11승/−2패/37동률.

| 저장 비교 방식 | 적중 | 경주 | 적중률 |
|---|---:|---:|---:|
| jockey_id_candidate | 438 | 1,779 | 24.62% |
| jockey_basic_candidate | 429 | 1,779 | 24.11% |
| latest_expanded_direct_pair_427 | 427 | 1,779 | 24.00% |
| old_direct_pair_426 | 426 | 1,779 | 23.95% |
| H2_calibrated_p0_baseline | 429 | 1,779 | 24.11% |
| raw_F1_STYLE6_score_Top2_429 | 429 | 1,779 | 24.11% |
| saved_F1_STYLE6_PTop3_Top2_429 | 429 | 1,779 | 24.11% |
| existing_joint_marginal_Top2_434 | 434 | 1,779 | 24.40% |
| existing_candidate_max_joint_pair_422 | 422 | 1,779 | 23.72% |
| existing_matched_max_joint_pair_429 | 429 | 1,779 | 24.11% |

## 확률과 하위집단 진단

All-pair/selected-pair Brier·log loss, fixed reliability bins, 선택확률 0.20 이상 coverage·적중률, 연도·거리별 paired 차이, probability sum 진단은 `outputs/REPORT.json`에 보존했다. 날짜 bootstrap은 기존 seed·2,000회·269일 schedule을 그대로 썼다.

## 범주 계수와 해석

fold별 전체 `theta`와 weighted-centered runner `alpha`는 `outputs/FIT.json`에 ID별 H1 support와 함께 저장했다. Ridge는 standardized basis coefficient에 적용되어 원시 alpha의 유효 penalty가 ID support와 sigma에 따라 달라진다. 결과는 관측 기수-ID 연관성이며 기수 능력 또는 인과효과로 해석하지 않는다.

## 제한

기수 변경·마방·상호작용·희귀 ID pooling·추가 tuning은 포함하지 않았다. 결과 게시 timestamp가 없어 과거 기수 snapshot의 사전 가용성은 검증하지 못했다. 이 후향 평가와 반복 개발자료만으로 운영 반영을 정당화하지 않는다.
