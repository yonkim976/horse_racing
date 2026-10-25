# 제주 F1_STYLE6 두 말 동시 Top3 pair 기수 기본정보 비교

저장 F1_STYLE6 말 점수·평가 roster·latest expanded pair를 고정하고, pair 선택에 최근 365일 기수 기록 한 열을 더했다. 공식 event jockey ID는 과거 출전을 묶는 데만 썼다. `C=T−2일` 기준 `(C−365일,C]` 구간에서 `d=(Top3 횟수−Σ(3/편성수))/(관측 출전수+20)`를 계산하고 unordered pair 입력은 두 말 값의 합으로 정의했다. 20 pseudo-start는 사전 고정이며 조정하지 않았다. 지표는 과거 관측 편성 대비 Top3 빈도이지 기수 능력 추정치가 아니다.

평가는 1,779경주·269경주일·76,848 pair다. 2026년은 9월까지의 부분연도이며 이 기간은 반복 개발 자료다.

## 사전 지정 비교

Primary feature-effect: candidate 429/1779 − latest pair 427/1,779 = +0.112%p (date-bootstrap 95% CI -0.340~+0.569%p); 미통과.
Raw 429 gate: candidate 429/1779 − raw Top2 429/1,779 = +0.000%p (95% CI -0.506~+0.509%p); 미통과.
두 gate 모두 통과: 아니오. Latest pair 대비 선택이 다른 경주는 69개로, 변경 경주에서 +10승/−8패/51동률이었다.

| 비교 방식 | 적중 | 경주 | 적중률 |
|---|---:|---:|---:|
| jockey_basic_candidate | 429 | 1,779 | 24.11% |
| latest_expanded_direct_pair_427 | 427 | 1,779 | 24.00% |
| old_direct_pair_426 | 426 | 1,779 | 23.95% |
| H2_calibrated_p0_baseline | 429 | 1,779 | 24.11% |
| raw_F1_STYLE6_score_Top2_429 | 429 | 1,779 | 24.11% |
| saved_F1_STYLE6_PTop3_Top2_429 | 429 | 1,779 | 24.11% |
| existing_joint_marginal_Top2_434 | 434 | 1,779 | 24.40% |
| existing_candidate_max_joint_pair_422 | 422 | 1,779 | 23.72% |
| existing_matched_max_joint_pair_429 | 429 | 1,779 | 24.11% |

## 확률·하위집단 진단

All-pair/selected-pair Brier와 log loss, reliability, 선택확률 0.20 이상 coverage·적중률, 연도·거리별 paired 결과 및 확률합 진단은 `outputs/REPORT.json`에 기록했다. 기존 2,000 draw·269-date bootstrap schedule을 그대로 사용했다.

## 제한

원천은 정상 완주 완전 편성 cohort라 `n`은 전체 현실 기승수가 아니다. 결과 게시시각은 없고 현재 기수 배정도 후향 event snapshot을 가정한다. 반복 개발 기간 결과이므로 새 미래 holdout 전 운영 적용 근거가 되지 않는다. 이번 비교는 rolling-365 scalar 하나만 확인했으며 기수 범주형 효과, 마방, 교체, 전문성은 포함하지 않았다.
