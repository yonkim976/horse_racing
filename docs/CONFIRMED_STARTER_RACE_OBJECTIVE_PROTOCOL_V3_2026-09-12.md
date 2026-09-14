# Confirmed-starter 경주 목적함수 연구 protocol v3

상태: **R3/R4 보완 실행 명세 확정, 실제 경마 모델 미학습, 운영 승격 금지**<br>
확정일: 2026-09-12 KST

## 1. 동결 범위

후보는 동일 confirmed-starter A 표와 동일 136개 feature를 사용하는 `BINARY`와
`RACE_SOFTMAX` 두 개뿐이며 seed는 42다. N arm, top2/top3, 새 feature, calibration 후보,
추가 seed 및 hyperparameter 탐색은 금지한다.

- H1 dataset SHA-256:
  `9d508bfdea325482461fa5d4e1b9a3ea8543bfe146a9b40b5400f4084064d6a7`
- H1 manifest SHA-256:
  `f36cc08930c4010cc3be230575289d06110add010d4c3ad368dbdad5f142d801`
- 136개 feature-name hash:
  `b7f57b9939aac9b51993e29046d43a10c9f49fdcfac0b821807300459ef2ac48`
- 공통 category-map hash:
  `f3800b712d39af44a0d5ae7cfa9c74ca7ebdd9ff287e38c4a477a7b0c4b55d00`

| partition | 날짜 | 행 | 경주 | 공식 동착 경주 |
|---|---|---:|---:|---:|
| fit | 2025-01-04~2025-10-26 | 8,719 | 844 | 1 |
| tune | 2025-11-01~2025-12-27 | 2,001 | 187 | 1 |
| calibration | 2025-12-28~2026-02-28 | 1,808 | 169 | 1 |
| development validation | 2026-03-01~2026-05-31 | 3,051 | 288 | 0 |

공통 encoder는 A train 전체 12,528행·1,200경주에서 한 번 적합한다. 각 partition은
`(race_date_local,race_id,race_entry_id)`로 안정 정렬하고 동일 경주의 모든 행을 연속 배치한다.
group은 양의 정수 경주 크기 배열이며 합이 matrix 행 수와 정확히 같아야 한다. partition 간 group을
연결하지 않는다. 입력·matrix·key·group hash가 후보 간 다르면 첫 tree 전에 중단한다.

3~5월 validation은 반복 사용된 development 자료이며 독립 test가 아니다. 결과로 후보·보정·설정을
다시 선택하지 않는다. 2026-06-01 이후 실제 결과는 별도 승인 전 조회·탐색·평가하지 않는다.

## 2. 공통 public API와 raw-margin 계약

LightGBM 4.7.0 공개 `lightgbm.train`과 `lightgbm.Dataset(group=...)`를 사용한다. 두 후보 모두
custom objective로 학습해 `feval(predictions,dataset)`의 predictions가 원래 raw margin이 되게 한다.
확률을 clip한 후 logit으로 역산하는 코드는 사용하지 않는다. `metric="None"`, custom metric 하나,
`first_metric_only=true`를 강제한다.

매 iteration callback raw-margin 전체 hash를 같은 iteration의
`Booster.predict(raw_score=true,num_iteration=i)`와 대조한다. 공통 metric은 해당 raw margin으로
계산한 전체 tune 경주의 동등가중 soft-label CE 하나다. callback metric과 별도 구현 CE의 허용오차는
`1e-12`다. group·label·weight·partition hash도 callback마다 기대값과 대조한다. NaN/Inf margin은
확률로 바꾸거나 clip하지 않고 중단한다.

합성 public-API 검증에서 `[40,41]`은 CE `1.3132616875182228`, `[-40,-41]`은
`0.31326168751822286`을 callback까지 오차 0으로 유지했다. 이는
`data/experiments/confirmed_starter_e5a_r3_r4_20260912/callback_evidence.json`에 봉인한다.

## 3. BINARY 목적

Dataset label은 공식 winner indicator `y∈{0,1}`다. 동착 승자는 각각 1이고 DNF/실격은 0이다.
각 경주 n두의 행 weight는 `w_i=1/n`이며 한 경주의 총 weight는 1이다.

- 안정 loss: y=1이면 `w*logaddexp(0,-z)`, y=0이면 `w*logaddexp(0,z)`.
- 안정 sigmoid: z>=0이면 `1/(1+exp(-z))`, 아니면 `exp(z)/(1+exp(z))`.
- gradient: `w*(sigmoid(z)-y)`.
- Hessian: `w*sigmoid(z)*(1-sigmoid(z))`; 별도 floor 없음.

이 수식은 weighted native Bernoulli와 수학적으로 동등하지만 Python custom callback과 native
built-in 구현의 합산·병렬·수치 경로가 bitwise 동일하다고 주장하지 않는다. 중앙 유한차분으로
weighted gradient/Hessian을 검사한다. Dataset 내부 float32 weight를 생성 전 float64 값과
`1e-7` 이내로 비교한다. `boost_from_average=false`로 초기 margin을 0으로 고정한다.

## 4. RACE_SOFTMAX 목적

Dataset에는 같은 0/1 winner indicator를 넣고 callback에서 경주별 승자 수 d로 나눠 float64
`q_i=y_i/d`를 만든다. q는 비음수·유한이어야 하며 `rel_tol=0,abs_tol=1e-12`로 합 1을 검사한 뒤
합으로 재정규화한다. 승자가 없는 경주는 거부한다.

경주별 shifted score `x_i=z_i-max(z)`에 대해 loss는
`logsumexp(x)-sum_i q_i*x_i`, gradient는 `p_i-q_i`, 전체 Hessian은 `diag(p)-ppᵀ`다.
LightGBM에는 `max(p_i(1-p_i),1e-6)` 대각 근사만 반환하고 floor 적용 수를 기록한다.
Dataset weight는 실제 정책대로 생략하며 callback에서 `get_weight() is None`을 assert한다.
초기 margin은 0이다.

동착 soft-label CE와 `-log(sum_{winner}p)` winner-set loss는 단독 우승일 때만 같다. 학습과 평가에서
둘을 구분한다. 두 목적의 Hessian/gradient 곡률이 달라 같은 regularization 숫자가 같은 유효 제약을
뜻하지 않는다.

## 5. 공통 tree 예산과 early stopping/refit

| parameter | BINARY | RACE_SOFTMAX |
|---|---:|---:|
| objective | custom weighted Bernoulli | custom race softmax |
| metric | None | None |
| num_boost_round | 1,200 | 1,200 |
| learning_rate | 0.03 | 0.03 |
| num_leaves / max_depth | 31 / -1 | 31 / -1 |
| min_data_in_leaf | 80 | 80 |
| min_sum_hessian_in_leaf | 0.001 | 0.001 |
| feature_fraction | 0.8 | 0.8 |
| bagging_fraction / bagging_freq | 1.0 / 0 | 1.0 / 0 |
| lambda_l2 | 1.0 | 1.0 |
| boost_from_average | false | false |
| deterministic / force_col_wise | true / true | true / true |
| seed 계열 | 모두 42 | 모두 42 |
| num_threads / verbosity | -1 / -1 | -1 / -1 |

E3의 row-level bagging 0.9는 경주 전체 group을 보존하는 bagging API가 없어 양 후보 모두 끈다.
fit selector는 tune 전체 187경주의 soft-label CE 하나로 patience 80 early stopping한다. 공식 동착도
포함한다. best iteration은 1~1,200이어야 한다. 이후 공통 encoder로 fit+tune 10,720행을 합쳐
후보별로 처음부터 정확히 best iteration만 refit한다. refit에는 calibration/validation이나 early
stopping을 넣지 않는다.

## 6. R3 temperature 최적성 판정

양 후보 모두 refit raw margin에 `p(T)=softmax(z/T)`를 적용하고 calibration 169경주의 동등가중
soft-label CE로 단일 T를 적합한다. `u=log T∈[-4,4]`, `β=1/T∈[exp(-4),exp(4)]`다.

모든 목적·도함수는 경주별 `x=z-max(z)`에서 계산한다.

- `F(β)=mean_r[logsumexp(βx)-β q·x]`.
- `F'(β)=mean_r[E_p(x)-E_q(x)]`.
- `F''(β)=mean_r Var_p(x)>=0`; 따라서 F는 β에서 볼록하다.

flat은 **모든 경주에서 입력 float64 score가 구조적으로 정확히 상수**인 경우만 인정하고 T=1을
쓴다. 작은 score 차이, 작은 objective 범위, CE가 0으로 반올림된 구간은 근사 flat으로 인정하지
않는다. float64 입력 전에 소실된 차이를 복원했다고 주장하지 않는다.

`β_low=exp(-4)`, `β_high=exp(4)`의 objective·1차·2차 미분이 모두 유한해야 한다.

- `F'(β_low)>=0`: 제한 최적점은 β_low, 즉 log T=4 상한. 경계해로 중단.
- `F'(β_high)<=0`: 제한 최적점은 β_high, 즉 log T=-4 하한. 경계해로 중단.
- `F'(β_low)<0<F'(β_high)`: 유일한 내부 도함수 root를 SciPy `brentq`로 구한다.

root 설정은 `xtol=1e-12`, `rtol=4*float64_eps`, `maxiter=200`이다. 비유한 endpoint/derivative,
bracket 불일치, solver 실패는 중단한다. 경계 거리 tolerance나 bounded optimizer의 반환 위치로
경계 여부를 판단하지 않는다. endpoint와 solution의 β, log T, T, objective, 1차·2차 미분을 모두
저장한다.

필수 회귀값은 다음과 같다.

- 상한 반례 `z=[0,.01],y=[1,0]`: `boundary_logT_upper`, 중단.
- 하한 반례 `z=[0,1],y=[0,1]`: `boundary_logT_lower`, 중단.
- 알려진 내부해: 동일 `z=[1,0]` 세 경주에서 앞선 말 2승/뒤진 말 1승이면
  `β=log(2)`, `T=1/log(2)=1.4426950408889634`, 허용오차 `1e-10`.
- 완전 분리와 CE 반올림 사례도 구조적 flat이 아니라 하한 경계로 판정.

## 7. 최종 확률, validation, 지표

두 후보 모두 `Booster.predict(raw_score=true)`→경주 softmax→고정된 단일 T만 사용한다. E3의
sigmoid/isotonic 및 합-1 projection을 사용하지 않으므로 새 BINARY는 E3 저장 모델 재현 대조군이
아니다.

전체 validation 3,051행·288경주를 분모로 누락·추가·중복·마번, raw/probability 유한값,
[0,1], 경주합 `1e-8`, save/reload 오차 `1e-12`를 검사한다. inner join으로 분모를 줄이지 않는다.

주 지표는 race-equal winner-set NLL이며 stable log-domain으로 계산한다. 보조 지표는 race-equal
soft-label CE, entry-equal binary NLL/Brier, expected-tie Top1/3/5, 공식 동착, score/probability
동점, Hessian floor, best iteration, T다. 특수 상태 12경주/나머지 276경주는 기존 고정 진단만 한다.

delta는 `RACE_SOFTMAX-BINARY`다. E3와 같은 경주 및 경주일 cluster paired bootstrap을 각각
5,000회, seed 20260911, percentile 95% CI로 계산한다. 다수 subset 검정이나 재선택은 하지 않는다.

## 8. 산출물, 격리와 중단

신규 실제 연구 모델 예산은 정확히 두 개다. protocol은 첫 fit 전에 저장한다. 공통 input/encoder/
matrix/key/group/code hash, 후보별 selector callback·best iteration·refit Booster·temperature,
calibration/validation keyed 예측, per-race loss, paired comparison/bootstrap, reload 및 전체 artifact
manifest를 새 연구 root와 연구 전용 ledger에 저장한다.

기본 registry, champion/active pointer, 운영 prediction·배팅 경로는 수정하지 않는다. 입력 hash,
두 후보 matrix 동일성, q/group/weight, 매 iteration raw metric, 단일 stopping metric, refit, R3
temperature 상태, 전체 validation coverage 또는 reload 계약이 실패하면 비교를 중단한다. 실패를
설정 변경 후 숨기지 않고 attempt ledger에 기록한다.

3~5월 결과가 어느 후보에 유리해도 winner 선언이나 운영 승격을 하지 않는다. 이 protocol의 합성
PASS는 경마 예측력 개선 증거가 아니며, 독립 검증 전 실제 경마 학습을 시작하지 않는다.
