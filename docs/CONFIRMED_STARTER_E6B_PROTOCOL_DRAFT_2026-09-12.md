# Confirmed-starter E6-B 부담조건 소거실험 protocol 초안

상태: **독립 검증 전 초안, 실제 학습 금지**<br>
작성일: 2026-09-12 KST

## 1. 연구 질문과 고정 후보

서울 retrospective actual-starter A에서 동일 BINARY 절차를 고정 대조법으로 사용해 부담조건의
증분 정보만 비교한다. BINARY는 E5-B winner로 선언된 것이 아니다. arm은 다음 셋이며 성능을 본 뒤
열이나 조합을 바꾸지 않는다.

1. `BASE_136`: 봉인 H1의 기존 136개 predictor.
2. `CURRENT_WEIGHT_A`: 기존 136개 + `condition_carried_weight_kg` +
   `condition_carried_weight_rel_A`.
3. `CURRENT_WEIGHT_A_PREV`: `CURRENT_WEIGHT_A` +
   `condition_carried_weight_delta_prev_start`.

상태·가용성 metadata는 model feature가 아니다. 공식 레이팅, 등급 대리변수, 배당, 당일 마체중
부담률, RACE_SOFTMAX, 새 보정법과 추가 seed는 포함하지 않는다. 세 부담조건 값은 E6-A에서
후향 일관성은 통과했으나 T-30 가용성은 미확인이다. 따라서 실험이 실행돼도 historical live
PIT 성능으로 해석하지 않는다.

## 2. 공통 입력과 알려진 한계

- H1 dataset: 15,579행·1,488경주, 2025-01-04~2026-05-31.
- 기존 feature 이름·순서 hash:
  `b7f57b9939aac9b51993e29046d43a10c9f49fdcfac0b821807300459ef2ac48`.
- 부담조건 keyed parquet는 H1 키 15,579개를 그대로 보존해야 한다. arm별 inner join 축소를
  금지하며 누락·추가·중복을 fit 전에 중단한다.
- A는 사후 실제 출발집합이고 역사적 T-30 `F_t`가 아니다. 기존 136개에도 성별 snapshot 등
  알려진 PIT/source 한계가 남아 있다. fold 추가로 이 자료를 독립 test라고 부르지 않는다.
- 이번 초안과 후속 실행에서 2026-03-01~2026-05-31을 평가·선택에 사용하지 않는다.

## 3. 고정 시간순 3-fold

모든 기간은 A 전체 경주를 사용하고 날짜 경계를 걸치는 경주는 없다. 각 fold에서
`selector fit → tune early stopping → fit+tune refit → 별도 calibration → 이후 evaluation`을
수행한다. evaluation 기간은 서로 겹치지 않는다. 숫자는 E6-A 원천 감사 통과 후 H1 전체 키로
확정했다.

| fold | partition | 날짜 | 행 | 경주 | 경주일 |
|---|---|---|---:|---:|---:|
| F1 | fit | 2025-01-04~2025-03-30 | 2,767 | 259 | 24 |
| F1 | tune | 2025-04-05~2025-04-27 | 883 | 84 | 8 |
| F1 | calibration | 2025-05-03~2025-05-31 | 928 | 94 | 9 |
| F1 | evaluation | 2025-06-01~2025-07-27 | 1,693 | 172 | 17 |
| F2 | fit | 2025-01-04~2025-07-27 | 6,271 | 609 | 58 |
| F2 | tune | 2025-08-02~2025-08-31 | 877 | 85 | 8 |
| F2 | calibration | 2025-09-06~2025-09-28 | 860 | 84 | 8 |
| F2 | evaluation | 2025-10-04~2025-11-02 | 834 | 77 | 7 |
| F3 | fit | 2025-01-04~2025-11-02 | 8,960 | 866 | 82 |
| F3 | tune | 2025-11-08~2025-11-30 | 936 | 88 | 8 |
| F3 | calibration | 2025-12-06~2025-12-28 | 941 | 88 | 8 |
| F3 | evaluation | 2026-01-03~2026-02-28 | 1,691 | 158 | 15 |

평가 분모는 합계 4,218행·407경주이며 경주 중복은 0이어야 한다. 각 fold의 fit 창은 앞선
evaluation까지 포함해 확장되지만 해당 fold의 tune/calibration/evaluation보다 항상 이르다.

## 4. encoder와 feature 계약

각 fold의 encoder는 해당 fold의 selector fit 행에만 한 번 적합해 freeze한다. validation,
tune, calibration은 encoder 적합에 참여하지 않는다. 기존 136개 열의 category map은 세 arm이
같이 사용하고 새 세 열은 Float64 수치형이다. 미지 category와 결측은 기존 encoder 정책을 유지한다.
arm별 기존 136개 matrix cell과 key/group/label hash가 다르면 첫 tree 전에 중단한다.

상대중량은 각 경주의 retrospective A 유효 중량 평균을 사용한다. 유효 중량이 2개 미만이거나
target 중량이 결측이면 null이다. 직전 변화량은 날짜가 엄격히 이전인 가장 최근 실제 출발만
사용하며 직전 중량이 결측이면 더 오래된 경주로 건너뛰지 않는다. left truncation과 첫 관측
출발 metadata는 보존하되 feature로 넣지 않는다.

## 5. 학습·보정 예산

모든 arm과 fold는 protocol v3 BINARY 수식을 사용한다.

- custom weighted Bernoulli, winner 0/1, 행 weight `1/field_size`.
- `boost_from_average=false`, raw-margin callback metric.
- learning rate 0.03, leaves 31, max depth -1, min leaf 80,
  min Hessian 0.001, feature fraction 0.8, bagging off, L2 1.0.
- deterministic/force_col_wise true, 모든 seed 42, 최대 1,200 round, patience 80.
- selector는 tune의 race-equal soft-label CE 하나만 사용한다.
- fit+tune refit은 best iteration만큼 처음부터 학습하고 calibration/evaluation을 넣지 않는다.
- temperature는 각 refit의 별도 calibration에서 protocol v3 beta endpoint/root 규칙으로 하나만
  적합한다. boundary·비유한·solver 실패는 해당 fold 전체 비교를 중단하며 T=1 fallback이나
  경계 확장을 금지한다.

각 fold에서 세 arm의 selector/refit/calibration이 모두 승인된 뒤에만 공통 evaluation 경계를
연다. 하나라도 실패하면 그 fold의 evaluation 호출과 산출물은 세 arm 모두 0이어야 한다.
총 예정 fit 호출은 3 folds × 3 arms × (selector+refit) = 18회다. 재시도, 추가 seed와 설정 탐색은
별도 승인 없이는 금지한다.

## 6. 지표와 불확실성

주 지표는 temperature 적용 raw margin에서 stable log-domain으로 계산한 경주 평균 winner-set
NLL이다. epsilon clipping을 사용하지 않는다. 보조는 entry-equal binary NLL(`epsilon=1e-15`),
Brier, expected-tie Top1/3/5다. 공식 동착과 score/probability tie를 분리한다.

각 추가 arm의 delta는 `additional arm − BASE_136`이며 음수 loss delta가 개선 방향이다.
모든 예정 fold를 보고하고 좋은 fold만 선택하지 않는다.

- fold별 지표와 paired race/race-date cluster 결과를 모두 제시한다.
- 통합값은 세 evaluation의 모든 경주를 연결해 경주당 동일 가중으로 계산한다.
- 통합 paired race 및 경주일 cluster bootstrap은 각각 5,000회, seed 20260911이다.
- 경주일 bootstrap은 선택된 날짜의 전체 경주를 유지한다.
- CI는 저장 예측에 조건부이며 재학습·fold 설계·가설 선택 변동성을 포함하지 않는다.

## 7. 실패·보존 및 해석

입력/feature/key/group/label/categorical hash, callback raw-margin, objective 반환값, temperature,
coverage, 확률합 또는 save/reload 계약 위반 시 fail closed한다. 누락 arm만 비교하거나 성공 fold만
통합하지 않는다. 실패 증거와 시도 원장을 보존하고 설정을 바꿔 조용히 재실행하지 않는다.

기존 H1/E3/E4/E5-A/E5-B와 기본 registry/champion을 수정하지 않는다. 2026-03-01 이후 실제
성능을 새로 계산하지 않으며 2026-06-01 이후라는 이유만으로 금지되는 것이 아니라, 본 초안은
명시된 2026-02-28 이전 개발 구간만 사용한다. 실제 실행은 독립 검증과 별도 지시 후에만 가능하다.
관측된 연관을 부담중량의 인과효과나 독립 미래 성능으로 표현하지 않는다.
