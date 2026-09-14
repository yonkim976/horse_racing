# Confirmed-starter 차기 목적함수 연구 protocol 초안

상태: **설계 초안만 작성. 학습·후보 선택·운영 연동 미실행.**<br>
작성일: 2026-09-12 KST

## 연구 질문과 고정 범위

동일한 confirmed-starter A 학습 대상과 동일한 136개 feature에서, 말별 binary cross-entropy로
학습한 tree와 경주별 softmax cross-entropy로 학습한 tree를 비교한다. 바꾸는 것은 win head의
학습 목적뿐이다. 데이터, 시간 분할, encoder 생성 범위, feature 순서, tree 용량, seed 42,
early-stopping 예산 및 최종 확률 변환 정책은 두 arm에서 동일하게 고정한다.

후보는 다음 두 개뿐이다.

1. `BINARY`: 현재와 같은 말별 binary objective로 win tree를 학습한다.
2. `RACE_SOFTMAX`: 경주별 logit에 softmax를 적용한 cross-entropy custom objective로 학습한다.

이번 E4에서 이 후보를 학습하지 않는다. E3의 N/A 비교나 보정 후보를 이 연구 후보에 섞지 않으며,
학습 모집단은 두 후보 모두 A로 고정한다. top2/top3 head는 이 연구 질문 밖이다.

## 확률과 손실의 관계

한 경주에 말 `i=1..n`, tree score `z_i`, softmax 확률
`p_i = exp(z_i - m) / sum_j exp(z_j - m)`, `m=max_j z_j`를 둔다.

- 말별 binary loss는 `sum_i -[y_i log sigmoid(z_i) + (1-y_i) log(1-sigmoid(z_i))]`다.
  각 말의 Bernoulli 주변확률을 독립적으로 적합하므로 한 경주 합 1은 학습 목적에 포함되지 않는다.
- 단일 우승마 경주의 race-softmax CE는 `-log p_w`다. 이는 같은 경주의 winner-set 평가
  `-log(sum_{i in W} p_i)`와 `|W|=1`일 때 정확히 같다.
- 공식 동착 승자 집합 `W`, `m=|W|>1`이면 학습 soft label은 승자마다 `q_i=1/m`, 나머지는
  0으로 둔다. 이때 CE는 `-(1/m) sum_{i in W} log p_i`로 승자들에게 질량을 고르게 배분하도록
  압력을 준다.
- 동착 winner-set 평가는 `-log(sum_{i in W} p_i)`다. 이는 승자 집합 전체의 확률 질량만 보고
  승자 간 배분은 보지 않으므로 soft-label CE와 같지 않다. 학습과 평가 양쪽 수치를 별도로 보고한다.
- DNF와 실격 출전마는 `q_i=0`을 유지한다. 한 경주에는 적어도 하나의 공식 승자가 있어
  `sum_i q_i=1`이어야 한다.

soft-label CE의 정확한 gradient는 `g_i=p_i-q_i`, 전체 Hessian은
`H=diag(p)-p p^T`다. LightGBM tree objective 인터페이스는 행별 gradient와 Hessian 배열을
받으므로 전체 비대각 항을 직접 전달할 수 없다. 첫 구현은 `h_i=p_i(1-p_i)`를 반환한다.
이는 **전체 Hessian의 정확한 대각 원소이지만, 최적화에서 비대각 항을 버리는 대각 근사**다.
정확한 Newton 업데이트라고 부르지 않는다.

참고로 winner-set loss의 gradient는
`g_j = p_j - 1[j in W] p_j / sum_{i in W} p_i`다. 동착에서 soft-label CE gradient와
일반적으로 다르므로 이번 후보 목적에 몰래 대체하지 않는다.

## 설치 API에 맞춘 구현 계약

현재 환경은 Python 3.12, LightGBM 4.7.0이다. 설치된
`lightgbm.sklearn._ObjectiveFunctionWrapper`는 custom objective를
`objective(y_true, y_pred[, weight[, group]]) -> (grad, hess)`로 호출하며, 네 번째 인자는
learning-to-rank task의 group 크기 배열이다. raw margin이 변환 전 `y_pred`로 전달된다.

구현 후보는 `LGBMRanker`의 ranking loss를 쓰는 것이 아니라, 경주별로 정렬된 행과 명시적
`group=[n_1,...,n_R]`를 전달하는 custom objective adapter다. adapter는 group 누적합으로 경계를
복원하고 각 경주 안에서만 stable softmax와 gradient/대각 Hessian을 계산한다. API spike에서
다음이 확인되지 않으면 실제 연구를 시작하지 않는다.

- custom objective가 네 인자와 group을 실제로 받는지
- float soft label이 custom objective 경로에서 변형 없이 유지되는지
- fit/tune 예측 순서가 사전 정렬한 `(race_date_local, race_id, race_entry_id)`와 동일한지
- custom evaluation metric도 같은 group 경계를 받거나 안전한 고정 closure로 경계를 복원하는지

group 전달이 불안정하면 `lightgbm.Dataset(group=...)`를 사용하는 native training adapter를
격리 구현하되 같은 estimator parameter와 prediction interface를 유지한다. 행 순서를 암묵적으로
추정하거나 race ID를 전역 변수에서 조회하는 구현은 허용하지 않는다.

## 공통 학습·early stopping·보정 정책

두 후보 모두 A 표의 동일 시간 분할과 같은 encoder를 사용한다. encoder는 train 내부에서만 fit하고
두 후보가 같은 category map과 feature matrix hash를 공유해야 한다. 기존 E3와 같은 fit/tune/
calibration 삼분할을 사용하되, 다음 연구 실행 전에 행·경주 수와 날짜 경계를 새 protocol에 봉인한다.

early stopping은 두 후보 모두 tune 경주의 **race-equal single-winner softmax NLL**을 사용한다.
공식 동착 경주는 soft-label CE와 winner-set NLL을 둘 다 기록하되, 사전 지정된 primary
early-stopping metric 하나만 사용한다. 현재 H1 validation에는 공식 동착이 없지만 정책은 코드로
고정한다. 평가 함수는 group별 손실을 먼저 만들고 경주를 동일 가중한다.

최종 확률은 두 후보 모두 tree raw margin에 경주별 softmax를 적용한다. calibration은 후보마다
train 내부 calibration 블록에서 **하나의 양수 temperature `T`**만 적합해
`softmax(z/T)`를 사용한다. `T=1`과 fitted `T` 중 validation 결과로 고르지 않는다. fitted
temperature 사용을 사전 고정하고 calibration 블록의 race-equal soft-label CE를 최소화한다.
winner-set NLL, binary NLL/Brier, expected-tie TopK는 보고 지표이며 보정 선택 기준이 아니다.

## 데이터 사용과 판정 절차

2026-03-01~2026-05-31 development validation은 E3/E4에서 반복 사용됐으므로 독립 test가 아니다.
다음 연구에서는 모델 수, 목적, seed, iteration budget, calibration을 모두 train 내부에서 확정한 뒤
development validation을 두 고정 후보의 **설명적 비교**에 한 번 사용한다. 그 결과로 후보,
temperature 방식, feature 또는 hyperparameter를 다시 선택하지 않는다.

개발 비교를 통과해도 승격하지 않는다. 별도 승인 후 더 늦은 미사용 시간 구간을 한 번 평가하는
후속 protocol을 작성한다. 그 시점에도 단일 seed 결과가 학습 변동성을 대표하지 못한다는 한계를
명시한다. 이번 초안은 2026-06-01 이후 실제 행을 조회하거나 기간·표본 수를 탐색하지 않는다.

## 합성 수학·경계 회귀 검사

실제 tree 학습 전에 다음 합성 검사를 모두 통과해야 한다.

- 순열 불변성: 경주 내 행과 label을 함께 순열해도 loss가 같고 gradient/Hessian은 같은 순열로
  이동한다.
- 공통 이동 불변성: 모든 `z_i`에 같은 상수를 더해도 loss, probability, gradient, Hessian이 같다.
- 확률합: 각 경주의 확률합이 `1 ± 1e-12`다.
- 극단 logit: `[1000, 0, -1000]`과 큰 공통 이동에서도 loss/gradient/Hessian이 유한하다.
- group 경계: 인접한 두 경주의 logit을 함께 전달해도 각 경주 softmax가 섞이지 않는다.
- 동착: 승자 두 명의 `q=[0.5,0.5,...]`, DNF/실격의 q=0, 전체 q 합 1을 검사한다.
- 유한차분: 중앙차분 gradient가 해석 gradient와 허용오차 `1e-6` 이내다. 전체 Hessian은
  별도 수학 검사에서 `diag(p)-pp^T`와 비교하고, trainer 반환값은 그 대각임을 명시한다.
- 잘못된 입력: 빈 경주, winner 없는 경주, 음수 label, label 합 불일치, 비유한 logit,
  group 합과 행 수 불일치를 거부한다.

E4에는 tree를 호출하지 않는 stable softmax/gradient 합성 검사가 이미 추가돼 있다. 차기 실행에서는
순열 및 다중 group adapter 검사를 더한 뒤에만 실제 후보 학습을 허용한다.

## 예산, 산출물, 중단 조건

- 후보: 정확히 2개 (`BINARY`, `RACE_SOFTMAX`).
- seed: 42 하나. 추가 seed 탐색 없음.
- feature: H1 A의 동일 136개. 추가·삭제 없음.
- tree budget: 두 후보에 같은 최대 tree 수, learning rate, leaves, min child, subsampling,
  early-stopping patience를 적용한다.
- 산출물: 새 격리 experiment root에 protocol, 공통 input manifest, 두 bundle, calibration parameter,
  validation predictions, per-race loss, comparison, code/output hash manifest를 둔다.
- 기본 `data/experiments/model_runs.jsonl`, champion/active 포인터 및 운영 prediction 경로를 쓰지 않는다.
  연구 전용 ledger만 사용한다.
- API group 계약, finite-difference, exact key/coverage, race probability sum, reload prediction 중 하나라도
  실패하면 학습 결과를 폐기하고 원인을 보고한다.
- 이 개발 결과만으로 winner 선언, 운영 승격 또는 post-development holdout 평가는 하지 않는다.

## 근거

- 로컬 trainer와 정규화: `src/horse_racing/analysis/lightgbm_model.py`
- 로컬 동점 기대값과 확률 손실: `src/horse_racing/analysis/metrics.py`
- E4 stable softmax 수학 검사: `src/horse_racing/analysis/confirmed_starter_e4.py`
- 설치 API 구현: `.venv/lib/python3.12/site-packages/lightgbm/sklearn.py`의
  `_ObjectiveFunctionWrapper`와 `LGBMModel` custom-objective 문서

이 초안은 목적함수 정렬의 가능성을 검증하기 위한 설계이며 성능 향상을 약속하지 않는다.
