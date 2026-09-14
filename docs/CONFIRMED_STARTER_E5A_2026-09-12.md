# Confirmed-starter E5-A 수학 보완·합성 API 검증 보고서

작성일: 2026-09-12 KST

**판정: E5-A의 수학 보완, 합성 LightGBM API spike, 실행 protocol v2 확정을 완료해 독립
검증에 제출한다. 실제 경마 학습이나 예측력 개선은 검증하지 않았다.**

## R1/R2 반례와 수정

E4의 실험용 함수는 과거 봉인 증거로 보존하고 새
`src/horse_racing/analysis/confirmed_starter_e5.py`에 독립 구현했다. 새 학습 명세는 E4 함수를
참조하지 않는다.

| 반례 | E4 before | E5 after |
|---|---:|---:|
| `z=[0,0], q=[.5,.5]` CE | 0.6931471805599453 | 0.6931471805599453 |
| `z=[1e16,1e16], q=[.5,.5]` CE | 0 | 0.6931471805599453 |
| `q=[.5,.500001]` | 허용, gradient 합 약 −1e-6 | 절대오차 계약 위반으로 거부 |

새 CE는 `z-max(z)` 좌표에서 log-normalizer와 q 내적을 끝까지 계산한다. q 합 검사는
`math.isclose(sum(q),1,rel_tol=0,abs_tol=1e-12)`로 고정했다. 허용범위 안의 반올림은 q를 합으로
다시 나눈 뒤 loss와 gradient 모두에 같은 q를 사용한다.

정확 gradient `p-q`, 전체 Hessian `diag(p)-ppᵀ`, 정확 대각 `p(1-p)`를 각각 반환한다.
LightGBM에는 비대각을 버리고 `max(p(1-p),1e-6)`을 전달한다. 중앙 유한차분으로 gradient와 전체
Hessian을 독립 대조했다. 극단 logit에서 floor가 실제 적용되는 합성 검사도 포함했다.

경주 내·경주 간 순열, 경주별 서로 다른 공통 이동, 다중 group, 단독/2두/3두 동착, 음성 label,
극단 logit, 빈 입력, 음수/비유한 label, winner 없는 경주, 잘못된 group 합을 검사했다.
`1e16+1`이 float64에서 `1e16`과 같아지는 경우는 입력 전에 정보가 소실된 것이며 복원하지 않는다.
반면 표현 가능한 `nextafter(1e16,+∞)` 차이는 유지됨을 별도 검사했다.

## 실제 public API spike

LightGBM 4.7.0의 공개 `lightgbm.train`과 `lightgbm.Dataset(group=...)` 경로를 실제 실행했다.
40개 합성 경주·240행을 fit 30경주/180행, tune 10경주/60행으로 나눴다. 출전 수는 4~8두이며
단독, 2두, 3두 동착과 170개의 음성 label 행을 포함한다. 최대 20 round, patience 3,
toy 전용 leaves 7/min leaf 3을 사용했고 설정 탐색은 하지 않았다.

- BINARY metric callback은 변환된 probability를 받았고 1-round `raw_score=false` 예측 hash와
  일치했다. raw margin hash와는 달랐다.
- RACE_SOFTMAX objective와 metric은 raw margin을 받았다. custom objective Booster에서는
  `raw_score=false`도 변환을 적용하지 않아 raw hash와 같았으므로, 최종 interface는 항상
  `raw_score=true`를 명시한다.
- Dataset 내부 label·weight는 float32, group은 int32였다. 원래 0/1 winner indicator는 정확히
  보존됐다. callback에서 float64 q를 만들었고 3두 동착은 `0.3333333333333333`, 모든 경주 q 합은
  1이었다.
- Objective callback은 fit group 30개·합 180을, metric callback은 tune group 10개·합 60을
  받았다. 인접 경주를 섞지 않았고 명시적 group이 없으면 adapter가 거부했다.
- BINARY weight는 `1/field_size`였다. RACE_SOFTMAX의 1.0/1.25 교대 경주 weight는 non-null
  buffer 전달을 증명하기 위한 spike 전용이다. 실제 protocol은 weight를 생략하고 unit race
  weight로 해석한다.
- 기본 metric은 `None`으로 끄고 `race_equal_soft_label_ce` 하나만 best_score에 존재함을
  assert했다. `first_metric_only=true`였다.
- 합성 best iteration은 BINARY 10, RACE_SOFTMAX 11이었다. 이는 API 기능 증거일 뿐 성능 비교가
  아니다.
- 두 모델 모두 저장/reload raw margin과 grouped-softmax 확률의 최대오차가 0이었고 경주합 최대
  오차는 2.22e-16 이하였다. key 순서도 복원했다.

상세 callback shape, dtype, head 값, 전체 buffer hash, group 값, q, Hessian floor 및 호출 횟수는
`data/experiments/confirmed_starter_e5a_20260912/callback_evidence.json`에 있다.

## Protocol v2의 확정 변경점

실제 연구 후보는 동일 A/136 features/seed 42의 `BINARY`와 `RACE_SOFTMAX` 정확히 두 개다.
H1 A의 fit 8,719행·844경주, tune 2,001행·187경주, calibration 1,808행·169경주를 고정했다.
공통 encoder는 train 전체 12,528행에서 한 번 만들며 기존 category-map hash를 검사한다.

두 후보 모두 native API, 초기 margin 0, 최대 1,200 tree, learning rate .03, leaves 31,
min leaf 80, feature fraction .8, L2 1을 사용한다. 경주 단위 group bagging API가 없으므로 E3의
row bagging .9는 양쪽 모두 끈다. 동일 숫자가 서로 다른 목적함수의 곡률·regularization을
동일하게 만들지는 않는다.

Early stopping은 전체 tune 경주의 동등가중 soft-label CE 하나, patience 80이다. best iteration로
fit+tune을 처음부터 refit한다. 양 후보 모두 raw margin→race softmax→단일 temperature의 공통
최종 변환을 사용한다. temperature는 calibration만으로 log T `[-4,4]`에서 SciPy bounded optimizer,
`xatol=1e-8`, 최대 500회로 적합한다. 평평하면 T=1, 비유한/실패/경계해는 실행 중단이다.

주 보고 지표는 race-equal winner-set NLL이며 soft-label CE, binary NLL/Brier, expected-tie TopK를
보조로 기록한다. E3와 달리 BINARY도 sigmoid+합 projection이 아닌 raw margin softmax와
temperature를 쓰므로 E3 수치 재현 대조군이 아니다. 3~5월 validation은 설명적 비교에만 쓰고
후보나 보정을 다시 고르지 않는다.

## 보존, 검사와 남은 한계

H1/E3/E4 핵심 artifact, E4 source와 운영 registry의 전후 hash가 같았다. 별도 champion/active
파일은 기존 발견 범위에서 없었고 운영 registry를 수정하지 않았다. 실제 2026-06-01 이후 행을
조회·탐색·평가하지 않았고 실제 경마 tree는 0개 학습했다.

남은 한계는 native custom objective가 전체 Hessian을 받을 수 없어 대각/floor 근사를 쓴다는 점,
두 목적의 유효 curvature가 다르다는 점, API spike가 합성 데이터와 최대 20 round에 한정된다는 점,
temperature의 실제 calibration 경계해 여부는 실제 실행 전에는 알 수 없다는 점, 단일 seed가 학습
변동성을 나타내지 못한다는 점이다. v2 실행 결과가 좋아도 독립 test나 운영 승격 근거가 아니다.

관련 E5 Ruff check/format은 통과했고 E5 pytest는 14개가 통과했다. 전체 pytest는 486 passed,
2 warnings였다. 전체 Ruff의 기존 범위 밖 21건, 전체 format의 기존 범위 밖 98개 파일,
`src/horse_racing/web/racecourse.py:347`의 기존 EOF diff-check 1건은 수정하지 않았다.

최종 실행 명세는 `docs/CONFIRMED_STARTER_RACE_OBJECTIVE_PROTOCOL_V2_2026-09-12.md`다. 독립 검증
전에는 실제 연구 학습이나 운영 연결로 진행하지 않는다.
