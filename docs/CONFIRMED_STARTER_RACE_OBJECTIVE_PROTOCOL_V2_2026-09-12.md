# Confirmed-starter 경주 목적함수 연구 protocol v2

상태: **실행 명세 확정, 실제 경마 모델 미학습, 운영 승격 금지**<br>
확정일: 2026-09-12 KST

## 1. 연구 질문과 동결 계약

동일한 confirmed-starter 조건부 A 학습행과 동일한 136개 feature에서 win head의 학습 목적만
비교한다. 후보는 정확히 `BINARY`와 `RACE_SOFTMAX` 두 개이며 seed는 42 하나다. N arm,
top2/top3, 신규 feature, 추가 seed, calibration 후보, hyperparameter 탐색은 포함하지 않는다.

동결 입력은
`data/datasets/confirmed_starter_e2_h1_remediation_retrospective/start_minus_30m/dataset.parquet`
(SHA-256 `9d508bfdea325482461fa5d4e1b9a3ea8543bfe146a9b40b5400f4084064d6a7`)과 manifest
(SHA-256 `f36cc08930c4010cc3be230575289d06110add010d4c3ad368dbdad5f142d801`)다.
feature 이름 136개의 hash는
`b7f57b9939aac9b51993e29046d43a10c9f49fdcfac0b821807300459ef2ac48`다.

두 후보는 같은 A 행을 `(race_date_local, race_id, race_entry_id)`로 안정 정렬한다. 각 partition에서
동일 race의 모든 출전행은 연속해야 하며 `group`은 연속한 경주별 행 수다. group은 양의 정수,
합은 matrix 행 수와 정확히 같아야 한다. fit/tune/calibration/validation 사이에 group이나 행을
연결하지 않는다. 예측 후 원래 키 순서는 `(race_id, race_entry_id)`로 복원한다.

## 2. 고정 시간 분할과 encoder

| partition | 날짜 | 행 | 경주 | 공식 동착 경주 |
|---|---|---:|---:|---:|
| fit | 2025-01-04~2025-10-26 | 8,719 | 844 | 1 |
| tune | 2025-11-01~2025-12-27 | 2,001 | 187 | 1 |
| calibration | 2025-12-28~2026-02-28 | 1,808 | 169 | 1 |
| development validation | 2026-03-01~2026-05-31 | 3,051 | 288 | 0 |

공통 encoder는 A train 전체 fit+tune+calibration 12,528행·1,200경주에서 한 번만 적합하고 두
후보가 같은 객체를 사용한다. E3 A와 같은 정책이며 category-map hash는
`f3800b712d39af44a0d5ae7cfa9c74ca7ebdd9ff287e38c4a477a7b0c4b55d00`이어야 한다.
feature matrix와 각 partition 키 hash를 실행 protocol에 기록한다. 두 후보의 matrix hash가
다르면 tree 학습 전에 중단한다.

2026년 3~5월은 이미 반복 사용한 development validation이며 독립 test가 아니다. 이 protocol을
실행할 때 두 고정 후보를 설명적으로 비교하되, 그 결과로 모델·보정·feature·설정을 재선택하지
않는다. 2026-06-01 이후 실제 행은 별도 승인 전까지 조회·탐색·평가하지 않는다.

## 3. 라벨, 손실, 가중 및 미분

### BINARY

- Dataset label: 공식 우승 indicator `y_i∈{0,1}`. 동착 승자는 각각 1이고 DNF/실격은 0이다.
- objective: LightGBM built-in `binary` cross-entropy.
- Dataset row weight: 경주 출전 수가 `n_r`이면 각 행 `1/n_r`. 따라서 한 경주의 weighted
  binary loss는 출전행 평균이고 모든 경주는 총 weight 1이다.
- callback buffer가 float32이므로 저장 전 계산한 float64 weight와 실제 Dataset weight를
  허용오차 `1e-7`로 대조한다.
- 초기 margin: `boost_from_average=false`, 즉 모든 행 0.

### RACE_SOFTMAX

경주 r의 score `z_i`, `m=max_i z_i`에 대해
`p_i=exp(z_i-m)/sum_j exp(z_j-m)`다. Dataset에는 BINARY와 같은 원래 0/1 winner indicator를
전달한다. callback은 각 경주 승자 수 `d_r`를 세어 `q_i=y_i/d_r`를 float64로 복원한다.
DNF/실격은 0이다. 승자가 없거나 q가 유한·비음수가 아니거나 합 1의 절대 허용오차 `1e-12`를
벗어나면 중단한다. 허용범위 안의 q는 합으로 다시 나눠 정확히 정규화한다.

- race loss: `L_r=log(sum_j exp(z_j-m))-sum_i q_i(z_i-m)`.
- total training objective: `sum_r L_r`; 경주 수나 출전 수로 gradient를 추가 나눗셈하지 않는다.
- exact gradient: `g_i=p_i-q_i`.
- exact full Hessian: `diag(p)-ppᵀ`.
- LightGBM 반환 Hessian: `max(p_i(1-p_i), 1e-6)`.

반환값은 전체 Hessian이 아니라 비대각 항을 버린 대각 근사이며, floor가 적용된 원소는 정확한
대각도 아니다. floor 적용 수를 partition과 iteration별로 기록한다. Dataset weight는 생략한다.
`get_weight() is None`을 의미상 경주 weight 1로 해석하며 adapter 내부에서 1 배열로 만든다.
명시적 weight가 주어지면 한 경주 안에서 상수이고 양수인 경우에만 gradient/Hessian 전체에
곱한다. 실제 연구에서는 이 선택 경로를 사용하지 않는다. 초기 margin은 custom objective 기본값
0이며 BINARY와 같다.

BINARY의 `1/n_r` weighted Bernoulli loss와 RACE_SOFTMAX CE는 경주별 총 scale을 맞추지만
gradient 및 곡률은 같지 않다. `lambda_l2`, `min_sum_hessian_in_leaf`와 같은 숫자가 같아도 두
목적의 유효 regularization이나 최적화 경로가 동일하다고 해석하지 않는다.

공식 동착의 soft-label CE `-(1/d_r)sum_{i∈W}log p_i`와 평가 winner-set loss
`-log(sum_{i∈W}p_i)`는 다르다. 단독 우승일 때만 같다.

## 4. 실제 API와 두 후보의 tree 설정

두 후보 모두 검증된 공개 `lightgbm.train` 4.7.0과 `lightgbm.Dataset(group=...)`를 사용한다.
`LGBMRanker`의 ranking objective는 쓰지 않는다. BINARY callback은 built-in objective가 변환한
확률을 받으므로 `log(p)-log1p(-p)`로 margin을 복원한다. RACE_SOFTMAX objective와 metric
callback은 raw margin을 직접 받는다. 이 차이는
`data/experiments/confirmed_starter_e5a_20260912/callback_evidence.json`에서 실제 fit으로
검증됐다.

| parameter | BINARY | RACE_SOFTMAX |
|---|---:|---:|
| objective | built-in `binary` | E5 custom callable |
| metric | `None` | `None` |
| num_boost_round | 1,200 | 1,200 |
| learning_rate | 0.03 | 0.03 |
| num_leaves | 31 | 31 |
| max_depth | -1 | -1 |
| min_data_in_leaf | 80 | 80 |
| min_sum_hessian_in_leaf | 0.001 | 0.001 |
| feature_fraction | 0.8 | 0.8 |
| bagging_fraction | 1.0 | 1.0 |
| bagging_freq | 0 | 0 |
| lambda_l2 | 1.0 | 1.0 |
| boost_from_average | false | false |
| seed / bagging_seed / feature_fraction_seed / data_random_seed | 42 | 42 |
| deterministic / force_col_wise | true / true | true / true |
| num_threads | -1 | -1 |
| verbosity | -1 | -1 |

E3의 최대 tree 수·learning rate·leaves·depth·min leaf·feature fraction·L2를 유지한다. E3의
row-level 0.9 bagging은 경주 전체를 보존하는 group bagging API가 없으므로 양 후보 모두에서
비활성화한다. 이는 목적 외 차이를 막기 위한 사전 고정 변경이며 성능 개선 조정이 아니다.

## 5. Early stopping과 refit

fit에서 selector를 학습하고 tune의 단일 primary metric
`race_equal_soft_label_ce = mean_r L_r`로 early stopping한다. tune의 단독 및 공식 동착 경주를
모두 포함한다. `metric=None`, `first_metric_only=true`, patience 80이며 다른 built-in metric이
stopping에 참여하면 실행을 실패 처리한다. 두 후보 모두 최대 1,200 round다.

selector의 `best_iteration`을 정수로 저장한다. 그 iteration이 없거나 1~1,200 밖이면 중단한다.
공통 encoder를 유지한 채 fit+tune 10,720행을 합쳐 후보별 tree를 처음부터 정확히
`best_iteration` round refit한다. refit에는 early stopping과 calibration/validation 행을 넣지
않는다. selector와 refit tree의 목적 및 모든 parameter는 iteration 수 외에 같아야 한다.

## 6. 공통 최종 확률과 temperature

두 후보 모두 최종 tree의 `Booster.predict(raw_score=true)` margin을 경주별로 나누고 하나의 양수
temperature를 적용한다: `p_i(T)=softmax(z_i/T)`. BINARY의 sigmoid 확률이나 E3의 합-1 projection,
sigmoid/isotonic calibrator를 사용하지 않는다. 따라서 새 BINARY는 E3 저장 BINARY의 단순 재평가가
아니며 E3 수치와 직접 동일해야 할 계약이 없다.

각 후보의 T는 calibration 169경주의 `mean_r soft_label_CE_r`만 최소화한다.

- parameterization: `u=log T`, 경계 `[-4,4]`, 즉 `T∈[e^-4,e^4]`.
- optimizer: SciPy `minimize_scalar(method="bounded")`.
- `xatol=1e-8`, `maxiter=500`.
- lower/0/upper 세 목적값 중 비유한값이 있으면 중단한다.
- 세 값의 범위가 `<=1e-12`이면 평평한 목적함수로 판정하고 `T=1`을 사용한다.
- optimizer 실패 또는 비유한 최적값은 중단한다.
- 해가 log 경계에서 `10*xatol` 이내면 clipping하거나 다른 값을 고르지 않고 중단한다.
- 그 외에는 유일한 반환 interior T를 그대로 사용한다. `T=1`과 validation 성능을 비교해 고르지 않는다.

## 7. Development validation 평가

전체 사전 정의 키 3,051행·288경주를 분모로 사용한다. 후보마다 누락·추가·중복·마번 불일치,
비유한 raw margin/확률, 확률 [0,1], 경주합 `1±1e-8`을 검사한다. inner join 교집합으로 분모를
줄이지 않는다. 저장/reload raw margin과 확률의 최대오차는 `1e-12` 이하여야 한다.

주 지표는 E3 연속성을 위한 race-equal winner-set NLL
`mean_r[-log(sum_{i∈W_r}p_i)]`이다. 확률을 먼저 0으로 만들고 log-clipping하지 않으며 stable
logsumexp/log-sum-exp difference로 직접 계산한다. 유한 score에서는 값이 유한해야 한다.

보조 지표는 다음과 같다.

- race-equal soft-label CE
- entry-equal binary NLL와 Brier
- 결과와 무관한 균등 동점 선택의 expected Top1/Top3/Top5
- 공식 동착 수, score/probability 동점 수, 특수 상태 포함 고정 12경주와 나머지 276경주
- temperature, best iteration, Hessian floor 수

불확실성은 E3와 같은 저장 예측 조건부 paired 방식만 사용한다. delta는
`RACE_SOFTMAX−BINARY`; 경주 bootstrap과 경주일 cluster bootstrap 각각 5,000회, seed 20260911,
percentile 95% CI다. 재학습 변동성이나 단일 seed 불확실성을 포함하지 않으며 다수 subset 검정을
추가하지 않는다.

## 8. 실행 예산, 격리와 중단

신규 실제 연구 model은 정확히 두 개다. 실패 run을 설정 변경 후 조용히 대체하지 않으며, 실패
원인과 tree 생성 여부를 development-attempt ledger에 기록한다. protocol은 첫 tree fit 전에 쓰고
다음 산출물을 새 experiment root에 저장한다.

- protocol과 H1/feature/matrix/key/code hash manifest
- 공통 encoder
- 후보별 selector metadata, best iteration, refit Booster, temperature
- calibration 및 validation raw margin/확률 keyed parquet
- per-race soft-label CE와 winner-set loss
- exact coverage/reload/callback/Hessian audit
- paired comparison/bootstrap, 실행 환경, 관련 검사 결과
- 연구 전용 registry와 전체 artifact manifest

기본 `data/experiments/model_runs.jsonl`, champion/active pointer, 운영 prediction/배팅 경로는 쓰거나
수정하지 않는다. 입력 hash, group 경계, q, 단일 stopping metric, temperature, validation coverage,
reload 중 하나라도 실패하면 결과 해석과 모델 비교를 중단한다.

3~5월 결과가 어느 후보에 유리하더라도 이 단계에서 winner를 선택하거나 운영 승격하지 않는다.
별도 독립 검증과 승인 뒤에만 더 늦은 미사용 시간 구간의 일회성 검증 protocol을 작성한다.
이 v2 자체는 실제 경마 학습이나 예측력 개선의 증거가 아니다.
