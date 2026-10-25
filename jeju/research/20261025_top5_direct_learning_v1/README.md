# F1_STYLE6 고정 점수 기반 Top5 직접 학습 선택기

상태: **3개 선택 head 학습·평가 완료. 사전 개선 gate는 통과하지 못했다.** F1_STYLE6 말 평가 모델과 저장 원점수, 운영 등록부는 바꾸지 않았다.

## 질문과 범위

기존 raw-score Top5와, 경주당 정확히 5두를 선택해 실제 Top3 3두를 모두 포함하도록 전용 head를 학습한 결과를 같은 경주에서 비교했다. 점수 기준은 원점수 내림차순, 동점은 마번 오름차순이다.

주 평가 모집단은 2024-01-05~2026-09-19의 900/1000/1110/1200m 1,503경주다. 사전 고정한 전체거리 보조 모집단은 1,779경주·269일이다. 이 기간은 여러 기존 연구에서 사용된 역사적 개발 자료로, 새로운 미래 holdout이 아니다.

## 학습과 선택

평가연도 2024, 2025, 2026마다 별도 head 하나를 학습했다. 학습 라벨은 각각 2019–2023, 2019–2024, 2019–2025년만 썼다. 훈련 점수는 각 과거 라벨연도의 F1_STYLE6 다음-fold calibration raw score였고, 각 provider의 `refit_max`가 해당 경주일보다 적어도 2일 앞섰다. 별도의 temperature 또는 배당 자료는 쓰지 않았다. 학습 전 라벨 검사는 각 훈련 경주에서 완전한 `1..N` finish와 정확히 3개 Top3 라벨을 확인했다.

head 에너지는 경주 내 ddof=0 표준화 raw score 합(고정 prior)에 11개 기존 F1_STYLE6 입력의 표준화 합을 더한다. 11개 잔차 입력에는 출전·동일거리 이력 및 세 style mean/support 값이 들어가며 scaler는 각 expanding training fold의 runner행으로만 계산했다. 유일한 학습 목적함수는 실제 Top3 3두를 포함하는 5두 집합들의 Gibbs 질량에 대한 partial-event NLL과 `λ=1` L2 penalty다. L-BFGS-B는 zero start에서 fold별 한 번만 실행했다.

여기서 `Pgood`는 관측한 실제 Top3에 조건부인 Gibbs **무작위** 5두 선택 질량이다. 이는 deterministic argmax 선택기의 실제 coverage 확률이나 보정된 확률이 아니다. 평가에서는 모든 `C(N,5)` 후보를 열거해 에너지 argmax 집합을 만들었다. `β=0` negative control은 전 1,779경주에서 기존 raw-score Top5와 일치했다.

## 결과

| 모집단 | Raw-score Top5 | 학습 head | 차이 |
|---|---:|---:|---:|
| Primary 900/1000/1110/1200m, 1,503경주 | 439 (29.208%) | 435 (28.942%) | −0.266 pp |
| 전체 거리, 1,779경주 | 519 (29.174%) | 520 (29.230%) | +0.056 pp |

Primary 차이의 고정 date-cluster bootstrap 95% CI는 **[−1.343, +0.775] pp**다. 사전 gate(점추정치 `>0`이고 구간 하한도 `>0`)는 실패했다. Root의 독립 재계산은 이 수치를 재현했다. 전체거리 차이의 독립 paired CI는 [−0.903, +1.009] pp였다.

Primary에서 head만 all-three를 맞힌 경주는 31, raw Top5만 맞힌 경주는 35다. 학습 head가 바꾼 선택은 primary 254경주, 전체 304경주다.

| Primary 층화 | Raw-score Top5 | 학습 head | 차이 |
|---|---:|---:|---:|
| 2024, 499경주 | 140 (28.056%) | 133 (26.653%) | −1.403 pp |
| 2025, 559경주 | 164 (29.338%) | 167 (29.875%) | +0.537 pp |
| 2026-09-19까지, 445경주 | 135 (30.337%) | 135 (30.337%) | 0.000 pp |
| 900m, 251경주 | 74 (29.482%) | 68 (27.092%) | −2.390 pp |
| 1000m, 508경주 | 155 (30.512%) | 154 (30.315%) | −0.197 pp |
| 1110m, 482경주 | 136 (28.216%) | 142 (29.461%) | +1.245 pp |
| 1200m, 262경주 | 74 (28.244%) | 71 (27.099%) | −1.145 pp |

이전 [zero-fit 관계분포 q-max 연구](../20261025_top5_set_selection_v1/README.md)는 primary 415회, 전체 500회 all-three hit을 기록했다. 이번 학습 head의 435회·520회는 참고용 기술 수치일 뿐이며, 서로 다른 목표·선택 규칙을 사전 head-to-head 비교한 것이 아니므로 raw-score Top5에 대한 우위 근거로 사용하지 않는다.

## 해석과 한계

이 전용 head는 실제 all-three 포함 사건으로 3개 시간순 fold에서 학습을 완료했지만, primary에서 raw-score Top5보다 나은 신호를 보이지 않았다. 입력 중 `same_starts`와 `same_valid_times`, style-support log count 간 상관이 매우 높으므로 개별 계수의 부호·크기를 말의 독립적 효과로 해석하지 않는다. 결과는 반복 사용된 후향 개발 표본에 한정되며, 구매 전략·수익성·미래 성능 또는 인과 효과를 뜻하지 않는다. 운영 반영이나 등록부 변경은 없다. 기존 raw-score Top5를 이 목표의 비교 기준으로 유지한다.

## 보관 파일

- [사전 계획](PLAN.md): 목적함수·시간분할·성공 gate와 해석 계약.
- [원천 감사](SOURCE_AUDIT.md): 원천·해시·점수 시점·선택 입력 제한.
- [출력 manifest](FINAL_MANIFEST.json): 모델, 코드, 선택·결과 원장, root 독립 검토의 SHA-256과 크기.
- `outputs/LABEL_PREFLIGHT.json`: 훈련 label 연도별 완전 rank/Top3 검사.
- `outputs/model_2024.json`, `model_2025.json`, `model_2026.json` 및 `FIT_RECEIPT.json`: 세 fitted head와 진단.
- `outputs/candidate_choices.jsonl` 및 `CHOICES_RECEIPT.json`: label-free 경주별 raw Top5/head 선택.
- `outputs/outcomes.json`, `race_outcomes.jsonl`, `OUTCOME_RECEIPT.json`: 해시 승인 뒤 계산한 평가 결과.
- Root 독립 결과 재계산: [ROOT_OUTCOME_RECOMPUTATION.json](../20261025_top5_direct_learning_rootreview_v1/ROOT_OUTCOME_RECOMPUTATION.json), [3-way reconciliation](../20261025_top5_direct_learning_rootreview_v1/THREE_WAY_RECONCILIATION.json).

완성된 연구 폴더는 2 MB 미만이며 source parquet, DB, full candidate sets 또는 full triple tables를 복사하지 않았다.
