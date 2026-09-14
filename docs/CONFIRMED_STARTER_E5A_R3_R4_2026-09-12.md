# Confirmed-starter E5-A R3/R4 보완 보고서

작성일: 2026-09-12 KST

**R3 temperature 최적성 판정과 R4 BINARY raw-margin 평가 경로를 보완해 독립 검증에
제출한다. 실제 경마 모델이나 새 성능 비교는 실행하지 않았다.**

## R3: temperature 경계 판정

새 모듈은 `β=1/T`에서 경주평균 soft-label CE가 볼록하다는 성질을 사용한다. 모든 계산은
경주별 `z-max(z)` 좌표에서 수행한다. 양 endpoint의 objective·1차·2차 미분을 계산하고,
`F'(β_low)>=0`이면 log T 상한, `F'(β_high)<=0`이면 log T 하한으로 판정한다. 양 끝 미분의
부호가 반대일 때만 `scipy.brentq`로 내부 root를 구한다.

| 사례 | 보완 전 | endpoint derivative `(β_low,β_high)` | 보완 후 |
|---|---|---:|---|
| `z=[0,.01], y=[1,0]` | 내부해, log T≈3.999999896 | `(+0.005000458,+0.006332028)` | `boundary_logT_upper`, 중단 |
| `z=[0,1], y=[0,1]` | 내부해, log T≈−3.737984 | `(−0.495421218,−1.942e-24)` | `boundary_logT_lower`, 중단 |
| 완전분리 `z=[0,1000]` | CE 0 내부해 | `(−1.111e-5,0)` | `boundary_logT_lower`, 중단 |
| 동일 score | T=1 | `(0,0)` | 구조적 flat, T=1 |

동일 `z=[1,0]`인 세 경주에서 앞선 말 2승, 뒤진 말 1승인 분석적 내부해는
`β=log(2)`, `T=1/log(2)=1.4426950408889638`로 재현됐고 도함수는 `−3.70e-17`이었다.
경계 바로 안쪽의 실제 내부해와 경계 밖 최적점도 별도로 검사했다.

Flat은 모든 경주 score가 입력 float64에서 정확히 상수인 경우만 인정한다. 근사 flat은 허용하지
않으며, CE가 0으로 반올림돼도 score 차이가 있으면 endpoint 미분 부호로 판정한다. float64 입력
전에 소실된 차이를 복원한다고 주장하지 않는다. endpoint 비유한값이나 root solver 실패는 중단한다.

## R4: 실제 raw-margin early stopping

BINARY를 안정 weighted Bernoulli custom objective로 바꿨다. label은 기존 winner 0/1,
행 weight는 `1/field_size`, 초기 margin은 0이다. loss는 label에 따라
`w*logaddexp(0,±z)`, gradient는 `w*(sigmoid(z)-y)`, Hessian은
`w*sigmoid(z)*(1-sigmoid(z))`이며 별도 floor는 적용하지 않는다. 중앙 유한차분 검사를 통과했다.
이는 native binary와 수학적으로 같은 Bernoulli 목적이지만 Python callback과 native 구현의
합산·병렬·수치 경로가 bitwise 같다고 주장하지 않는다.

두 후보 모두 공개 `lightgbm.train` custom objective를 사용해 공통 feval에 raw margin을 직접
전달한다. 확률→logit 역변환은 제거했다. 40경주·240행 합성 spike에서 매 iteration callback
margin hash를 같은 iteration의 `Booster.predict(raw_score=true)`와 대조하고, 별도 CE 계산과
모두 오차 0으로 일치했다.

- BINARY: best iteration 10, early-stopping 종료 iteration 13, objective/metric 13회.
- RACE_SOFTMAX: best iteration 13, 종료 iteration 16, objective/metric 16회.
- 기본 metric 없음, `race_equal_soft_label_ce` 하나만 stopping에 사용.
- fit group/label/weight와 tune group/label을 모든 callback에서 hash로 분리 확인.
- BINARY 실제 weight `1/n`; RACE_SOFTMAX 실제 `get_weight() is None` 확인.
- 양 후보 `boost_from_average=false` 확인.
- best iteration로 합성 fit+tune refit 후 저장/reload raw margin·확률 최대오차 0.
- 무작위 source 순서를 group 정렬 후 key로 복원.

공개 init_score를 사용한 극단 callback probe에서 `[40,41]`의 CE는
`1.3132616875182228`, `[-40,-41]`은 `0.31326168751822286`으로 요청 margin과 callback margin,
독립 CE가 모두 정확히 일치했다. 이 probe의 min leaf 1, feature prefilter 해제, L2 `1e20`은
init-score 전달을 확인하기 위한 2행 toy 설정이며 실제 protocol에는 적용하지 않는다.

## Protocol v3와 보존

Protocol v3는 v2의 A 입력, 136개 feature, 시간 분할, seed 42, 정확히 두 후보, tree 예산,
validation 재선택 금지 및 운영 격리를 유지한다. 변경은 BINARY custom raw objective/metric과
β endpoint temperature 판정뿐이다. 실제 연구의 BINARY weight·RACE weight=None·early stopping·
refit·temperature 실패 정책을 실행 가능한 수식과 API 수준으로 고정했다.

H1/E3/E4/E5-A 원본, E5-A 코드·manifest, protocol v2와 운영 registry의 전후 hash는 동일했다.
실제 2026-06-01 이후 결과를 열지 않았고 실제 경마 tree 학습 수는 0이다.

남은 한계는 RACE_SOFTMAX가 전체 Hessian 대신 floor가 있는 대각 근사를 쓴다는 점, custom BINARY와
native 구현의 bitwise 동일성을 보장하지 않는 점, 합성 spike가 최대 20 round라는 점, 실제
calibration에서 temperature 경계해가 발생하면 연구 실행이 중단된다는 점, 단일 seed라는 점이다.
이번 합성 PASS는 예측력 개선이나 운영 승격 증거가 아니다.

관련 Ruff check/format은 통과했고 R3/R4 pytest는 10개가 통과했다. 전체 pytest는 496 passed,
2 warnings였다. 전체 Ruff의 기존 범위 밖 21건, 전체 format의 기존 범위 밖 98개 파일,
`src/horse_racing/web/racecourse.py:347`의 기존 EOF diff-check 1건은 수정하지 않았다.
