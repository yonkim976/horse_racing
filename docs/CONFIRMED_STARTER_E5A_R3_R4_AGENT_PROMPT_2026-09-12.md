# E5-A R3/R4 보완 지시

작업 경로: `/Users/kimyongjin/Desktop/horse_racing`

E5-A의 기존 R1/R2 및 합성 native API spike는 독립 검증을 통과했다.
아래 두 계약 결함만 보완하고 독립 검증용 새 버전을 제출하라.
먼저 `docs/CONFIRMED_STARTER_E5A_INDEPENDENT_REVIEW_2026-09-12.md`를 읽어라.

실제 경마 모델 학습·새 성능 비교·feature 변경·운영 연결은 수행하지 않는다.
합성 데이터의 수학·callback·early stopping·reload 기능 검증은 허용한다.
H1/E3/E4/E5-A 원본 artifact·문서·코드·registry의 봉인 해시를 보존한다.
수정은 새 연구 모듈/스크립트/테스트 및 protocol v3로 분리해 이전 manifest를 무효화하지 않는다.

## R3: temperature 경계 판정

현재 재현 반례를 먼저 저장한다.

- z=[0,0.01], y=[1,0], group=[2]: 진짜 최소점은 log T=4지만 현재 내부해로 통과한다.
- z=[0,1], y=[0,1], group=[2]: 진짜 최소점은 log T=-4지만 CE의 수치 평탄 구간을 내부해로 통과한다.
- 현재 테스트의 모든 우승마가 score 1위인 'signal' 예제도 내부해로 기대하면 안 된다.

고정된 log T 범위 [-4,4]와 경계해 발생 시 중단 정책을 유지한다.
optimizer 반환점과 경계의 거리만 보지 말고 경계 목적·미분과 최적성 조건을 사용해
경계/내부/실제 평탄 상태를 판정하라. beta=1/T에서의 볼록성과 도함수를 활용해도 된다.
모든 미분은 큰 공통 score에서 차이를 잃지 않는 경주별 shifted 좌표에서 계산한다.
CE가 0으로 반올림됐다는 이유만으로 해당 구간이 실제 평탄하다고 판정하지 않는다.

보완 전후 결과, endpoint 목적과 미분, optimizer 반환점, 최종 상태를 JSON으로 저장하라.
endpoint tolerance를 임의로 키워 위 반례만 피하는 수정은 불충분하다.
진짜 flat의 판정 기준, 근사 flat 허용 여부, optimizer 실패/NaN 처리도 명세에 고정한다.

합성 검사에는 다음을 포함한다.

- 실제 상수 score: T=1 정책.
- 위 상한/하한 반례: 경계 상태를 검출하고 명세대로 중단.
- 분석적으로 알려진 내부해: z=[1,0]인 세 경주, y=[1,0],[1,0],[0,1].
  기대 T=1/log(2). 수치 tolerance를 명시한다.
- 동착, 작은 score 차이, 큰 공통 이동, loss가 작아져 반올림되는 완전 분리 사례.
- 경계 부근의 진짜 내부해와 진짜 경계해를 구분하는 검사.

## R4: early-stopping metric에 실제 raw margin 전달

현행 sigmoid probability를 clip한 뒤 logit으로 되돌리는 방식은 사용하지 않는다.
label=[1,0]에서 raw [40,41]의 CE=1.313261687518..., raw [-40,-41]의
CE=0.313261687518...를 공통 평가 경로가 보존해야 한다.

실제 설치된 public API를 확인해 최소한의 안전한 구현을 선택하라.
예를 들어 native binary를 유지하면서 Booster의 원래 margin을 평가하는 공개 iteration callback,
또는 raw-margin을 직접 제공하는 수학적으로 동등한 binary custom objective가 가능하다.
어느 경로든 선택 근거와 API 검증 증거를 제시하라. 확률 포화 후 값을 역추정하지 않는다.

BINARY의 weighted Bernoulli loss, winner 0/1 label, 경주별 row weight 1/n,
초기 margin 0, 실제 protocol의 regularization을 유지한다.
custom binary로 바꾸면 sigmoid의 안정 계산과 weighted gradient/Hessian을 독립 유한차분으로
검증하고 native binary와의 의미적 동등성 및 구현상 차이를 기록한다.

공통 stopping metric은 전체 tune 경주의 raw-margin soft-label CE 하나다.
실제 학습 callback의 매 iteration 값과 별도로 계산한 원래 margin CE가 일치하는지 검사한다.
기본 metric이 개입하거나 callback 순서 때문에 한 iteration 뒤의 score로 평가하지 않게 하라.
callback state, group, partition, weight가 서로 섞이지 않는지도 확인한다.

실제 공개 fit을 사용하는 합성 spike에서 다음을 확인한다.

- 위 ±40 포화 반례는 실제 callback/evaluation 경로까지 검증한다. 필요하면 공개 init_score로
  합성 극단 margin을 공급하되 실제 연구의 초기값 0 정책과 구분한다.
- 일반 범위에서는 두 후보 모두 원래 raw margin CE와 일치한다.
- 명시적 boost_from_average=false, RACE_SOFTMAX의 실제 weight=None 경로도 검사한다.
  전 spike의 교대 1.0/1.25 weight 전달 검증을 실제 정책의 검증으로 대체하지 않는다.
- 단일 metric·early stopping·best iteration·refit/reload·키 복원 계약을 유지한다.
- NaN/Inf 등 잘못된 callback 값을 유효한 확률로 조용히 바꾸지 않는다.

## Protocol v3와 제출

v2의 A 입력·136개 feature·시간 분할·두 후보·seed·tree 예산·후보 선택 금지·운영 격리를 유지한다.
R3 최적성 판정과 R4 실제 raw evaluation API를 실행 가능한 수준으로 갱신한다.
API 변경에 꼭 필요한 차이 외에 새로운 모델/보정/탐색을 추가하지 않는다.

새 보완 보고서, protocol v3, 수학/adapter 구현, 실제 합성 spike 코드, callback 및 temperature
증거 JSON, 새 synthetic bundle/reload 검증, 원본 전후 hash manifest를 제출하라.
관련 Ruff/format·전체 pytest·diff-check를 실행하고 기존 범위 밖 오류는 구분한다.
실제 2026-06-01 이후 결과는 열지 않는다. 실제 경마 tree 학습 및 운영 연결 없이 제출 후 멈춰라.
