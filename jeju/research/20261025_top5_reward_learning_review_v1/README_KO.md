# 보상 기반 Top5 선택기 독립 검토

이 검토는 `jeju/research/20261025_top5_reward_learning_v1`을 대상으로 한다. 새 검토 코드와 영수증은 이 폴더에만 저장했다. 주 연구, 원천 parquet, 데이터베이스, 운영 모델과 registry는 수정하지 않았다. feature parquet, DB, 전체 후보 집합 행렬도 복사하지 않았다.

## 결과

새 보상 선택기는 주 평가 기간에서 원점수 Top5나 기존 partial-event NLL head보다 개선되지 않았다. 사전 성공 기준은 주 평가에서 두 비교 모두 차이 `>0`이고 날짜 bootstrap 95% CI 하한도 `>0`이어야 한다. 두 비교 모두 관측 차이가 음수이고 CI가 0을 포함해 기준을 통과하지 못했다. 현재 선택·운영 모델을 유지하고 이 연구 head를 승격하지 않는다.

| 주 모집단(1,503경주) | 실제 Top3 전부 포착 | 비율 | 보상 head 대비 차이 |
|---|---:|---:|---:|
| 원점수 Top5 | 439 | 29.2083% | +0.3327%p |
| 기존 partial-event NLL | 435 | 28.9421% | +0.0665%p |
| 새 보상 head | 434 | 28.8756% | — |

보상−원점수 차이는 **−0.3327%p** (날짜 bootstrap 95% CI **[−1.6459, +1.0467]%p**), 보상−기존 NLL은 **−0.0665%p** (95% CI **[−1.3185, +1.1356]%p**)다.

전체 보조 모집단 1,779경주에서 보상 head는 **515/1,779(28.9488%)**, 원점수 Top5는 **519/1,779(29.1737%)**, 기존 NLL은 **520/1,779(29.2299%)**였다. 보상−원점수는 −0.2248%p (95% CI [−1.5247, +1.1251]%p), 보상−기존 NLL은 −0.2811%p (95% CI [−1.4543, +0.9045]%p)다.

## 독립 검산

- 목적함수와 gradient를 별도로 유도하고 synthetic race에서 finite difference를 확인했다. 수정된 실제 `make_objective`에 서로 다른 `Pgood`을 가진 synthetic 경주 3개를 넣은 검사에서 손실 차이는 0, 독립 수식과의 gradient 최대 차이는 `2.78e−16`, 중앙 유한차분과는 `1.04e−10`이었다.
- 첫 정적 fit-code 검토는 경주별 feature 기댓값 대신 전체 경주 합산 기댓값을 사용하던 잘못된 gradient를 놓쳤다. Root synthetic audit에서 gradient 오차 `0.125`가 확인되어 실제 학습 전에 수정했다. 첫 PASS는 철회했으며 수정 과정과 근거를 [FIT_CODE_REVIEW.md](FIT_CODE_REVIEW.md)에 기록했다. 수정 source SHA `043c669ad6f8d7a9d66bb5846002758385c3e0811e7e6720727b2e5c1e9b85dc`만 학습에 쓰였다.
- 세 학습 fold의 fit receipt를 독립 재계산했다. 각 평가 fold의 라벨은 `2019 ≤ year < Y`로 제한했다. train-only scaler 평균·표준편차는 저장값과 정확히 일치했고, runner/race/action 수, objective, gradient, OOF source hash 및 `refit_max ≤ race_date−2일` 검산이 통과했다. 이 검산은 평가연도 라벨을 읽지 않았다.
- 최종 선택 코드 SHA `332304c499615288b37d9bc485f45f926931dedaf35d8242a4823e14fc616d54`를 검토했다. 결과값을 보지 않고 독립 코드로 `C(N,5)` 총 **411,084개** 조합을 열거해 **1,779경주** 선택을 재현했다. 모든 선택 ID·마번·경주 메타데이터·선택 에너지·기준 에너지가 일치했고, β=0은 1,779/1,779경주에서 원점수 Top5와 같았다.
- Root가 잠금된 선택과 reporter hash에 outcome 승인을 남긴 뒤에만 고정 이진 `y` 열을 열었다. 1,779경주 원장을 독립 재계산해 세 선택 arm, 0/1/2/3두 포착 분포, 연도·거리 하위집단, 변경·caught/lost 및 2,000회·269일 paired date bootstrap 네 개를 모두 대조했다. race 원장과 집계 13개 검사가 전부 일치했다.

세부 증거는 [수학 검토](INDEPENDENT_MATH_REVIEW.md), [fit 코드 검토](FIT_CODE_REVIEW.md), [선택기 코드 검토](SELECTION_CODE_REVIEW.md), [결과 코드 검토](OUTCOME_CODE_REVIEW.md), [fit 재계산](RECOMPUTED_FIT_AUDIT.json), [선택 재검산](INDEPENDENT_CHOICE_AUDIT.json), [결과 재계산](INDEPENDENT_OUTCOME_AUDIT.json)에 있다.

## 주 평가 paired 결과

| 비교 | 보상만 포착 | 보상만 놓침 | 둘 다 포착 | 둘 다 놓침 | 차이(%p) | 날짜 bootstrap 95% CI(%p) |
|---|---:|---:|---:|---:|---:|---:|
| 보상 vs 원점수 | 47 | 52 | 387 | 1,017 | −0.3327 | [−1.6459, +1.0467] |
| 보상 vs 기존 NLL | 43 | 44 | 391 | 1,025 | −0.0665 | [−1.3185, +1.1356] |

주 모집단에서 실제 Top3 포착 수(0 / 1 / 2 / 3두)는 원점수 **26 / 279 / 759 / 439**, 기존 NLL **28 / 272 / 768 / 435**, 보상 **27 / 285 / 757 / 434**였다. 보상 선택은 원점수와 370개 주 경주·464개 전체 경주에서 달랐고, 기존 NLL과는 356개 주 경주·436개 전체 경주에서 달랐다.

주 모집단 하위집단의 전부 포착 수(보상 / 원점수 / 기존 NLL):

| 집단 | 경주 수 | 포착 수 |
|---|---:|---:|
| 2024 | 499 | 132 / 140 / 133 |
| 2025 | 559 | 167 / 164 / 167 |
| 2026 부분연도 | 445 | 135 / 135 / 135 |
| 900m | 251 | 69 / 74 / 68 |
| 1000m | 508 | 146 / 155 / 154 |
| 1110m | 482 | 142 / 136 / 142 |
| 1200m | 262 | 77 / 74 / 71 |

이는 여러 차례 개발에 사용된 과거 자료이며 미래 holdout이 아니다. Gibbs `Pgood`과 기대 보상은 관측한 실제 Top3를 조건으로 한 확률적 학습량으로, 보정된 확률이나 결정적 argmax의 적중률이 아니다. PPO나 LLM 미세조정을 했다고 주장하지 않는다.

## 검토 파일

- `check_reward_objective.py`, `ACTUAL_FIT_GRADIENT_AUDIT.json`: synthetic 목적함수·gradient 검산.
- `recompute_fit_receipt.py`, `RECOMPUTED_FIT_AUDIT.json`: 3개 fold, 원천 해시, scaler, 목적함수와 gradient 독립 재생.
- `verify_locked_choices.py`, `INDEPENDENT_CHOICE_AUDIT.json`: 평가 라벨 없는 전경주 선택·utility 재검산.
- `verify_locked_outcomes.py`, `INDEPENDENT_OUTCOME_AUDIT.json`: 승인 후 세 arm 결과와 date bootstrap 독립 대조.
- `FINAL_REVIEW_MANIFEST.json`: 최종 파일 hash, 크기와 검토 범위.
