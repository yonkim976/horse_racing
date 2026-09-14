# Confirmed-starter E6-B 부담조건 묶음 비교 protocol v2 초안

상태: 독립 재검증 및 별도 승인 전 학습 금지. 2026-09-13 KST.

## 고정 후보와 해석

봉인 H1 서울 retrospective actual-starter A의 기존 136개 predictor를 같은 BINARY 절차로
비교한다. 후보는 정확히 BASE_136과 CURRENT_WEIGHT_A_PREV 둘이다. 후자는 감사한
condition_carried_weight_kg, condition_carried_weight_rel_A,
condition_carried_weight_delta_prev_start 세 수치 열을 함께 추가한다. 중간 arm, 새 objective,
seed 탐색과 추가 보정법은 없다. BINARY는 고정 대조법이며 E5-B 승자 선언이 아니다.
이 묶음 비교로 세 feature의 개별 기여나 중량의 인과효과를 분해하지 않는다.

현재 E6-A v2에서는 새 부경 직전 출발 중 원문이 없는 17개 target의 delta를 null로
격리했다. 후속 실행은 이 상태와 독립 검증을 명시적으로 승인받기 전 금지한다. 임의
DB 중량 복구, 이전 서울 출발 fallback 또는 후보 교체를 허용하지 않는다.

## 시간순 분할

모든 구간은 2026-02-28 이전이며 E6-A 검증 통과 숫자를 유지한다. 서로 다른 평가 경주의
전체 합계는 4,218행·407경주다. 2026년 3~5월 성능은 새로 계산하지 않는다.

| fold | 구간 | 날짜 | 행 | 경주 | 경주일 |
|---|---|---|---:|---:|---:|
| F1 | selector fit | 2025-01-04~03-30 | 2,767 | 259 | 24 |
| F1 | tune | 2025-04-05~04-27 | 883 | 84 | 8 |
| F1 | calibration | 2025-05-03~05-31 | 928 | 94 | 9 |
| F1 | evaluation | 2025-06-01~07-27 | 1,693 | 172 | 17 |
| F2 | selector fit | 2025-01-04~07-27 | 6,271 | 609 | 58 |
| F2 | tune | 2025-08-02~08-31 | 877 | 85 | 8 |
| F2 | calibration | 2025-09-06~09-28 | 860 | 84 | 8 |
| F2 | evaluation | 2025-10-04~11-02 | 834 | 77 | 7 |
| F3 | selector fit | 2025-01-04~11-02 | 8,960 | 866 | 82 |
| F3 | tune | 2025-11-08~11-30 | 936 | 88 | 8 |
| F3 | calibration | 2025-12-06~12-28 | 941 | 88 | 8 |
| F3 | evaluation | 2026-01-03~02-28 | 1,691 | 158 | 15 |

## 동일 절차와 공통 gate

각 fold에서 encoder는 selector fit 행에만 적합해 freeze한다. 기존 136개 열의 순서,
categorical mapping, 키·group·label은 두 후보에서 일치해야 한다. 새 열은 수치형이며
상태·가용성 metadata는 입력하지 않는다. H1 전체 키 coverage를 검사하고 inner join 축소,
누락·중복·추가 키는 첫 tree 전에 중단한다.

각 후보는 protocol v3의 weighted Bernoulli BINARY(1/field_size,
boost_from_average=false, raw-margin callback)와 고정 seed 42, learning rate .03,
leaves 31, min leaf 80, feature fraction .8, L2 1.0, 최대 1,200 round, patience 80을
공유한다. selector는 tune의 race-equal soft-label CE로 best iteration을 선택한다.
fit+tune refit은 처음부터 그 iteration만큼 학습한다. calibration은 별도 구간에서
기존 beta endpoint/root 규칙으로 단일 T를 구한다. fold당 후보 2개 × (selector+refit),
전체 12 fit만 예정한다.

run_e6b_fold 공통 gate는 봉인 protocol의 두 arm 집합을 prepare 전에 검사한다.
selector→refit→calibration 준비 결과의 후보 이름과 온도 진단이 모두 통과해야
evaluation 예측·지표·저장을 시작한다. structural-flat은 검증된 진단의 정확한
flat_use_T1,T=1, interior는 log(T)∈(-4,4)여야 한다. boundary·비유한·실패,
이름 바꿔치기 또는 한 후보 준비 실패면 두 후보 모두 evaluation 0이며 해당 fold 및
전체 통합을 중단한다. 성공 fold만 모아 비교하지 않는다.

## 지표와 불확실성

주 지표는 calibration T를 적용한 raw margin의 stable log-domain 경주 평균
winner-set NLL이다. 보조는 entry-equal binary NLL(epsilon=1e-15), Brier와
확률 동점 기대값 Top1/3/5이며 공식 동착과 확률 동점은 분리한다. 추가 후보−BASE의
paired race/race-date delta를 모든 fold별로 보고한다. 통합은 세 평가 구간의 전체
경주를 경주당 동등가중하고, paired 경주·경주일 cluster bootstrap 각각 5,000회,
seed 20260911을 사용한다. CI는 저장 예측 조건부이며 재학습·fold 선택 불확실성을
포함하지 않는다.

후향 A 모집단은 역사적 T-30 field가 아니며 세 원천 모두 사후 수집이다. 기존 136개에도
성별 snapshot 등 PIT/source 한계가 있다. fold를 늘려도 독립 test나 live 성능으로
바뀌지 않는다. 2026-06-01 이후 실제 결과, 운영 registry/champion은 열거나 변경하지 않는다.
