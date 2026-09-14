# E6-A: 평가 실행 경계 보완과 부담조건 정보 감사

작업 경로: `/Users/kimyongjin/Desktop/horse_racing`.

E5-B 독립 검증에서 제출 지표와 재현성은 통과했다. 우월 후보는 선언하지 않는다. 이번 작업은 다음 두 산출물까지 완료하라: (1) 다음 연구에서 재사용할 평가 실행 경계와 합성 반례 검사, (2) 부담조건 feature의 원천·시간 계약 감사와 제한된 후속 실험 protocol. 실제 경마 모델 학습·성능 탐색은 이번 범위에 포함하지 않는다. 사용자가 이 지시를 전달하면 이 범위는 승인된 것이므로 재확인을 요구하지 않는다.

먼저 다음을 읽어라.

- `docs/CONFIRMED_STARTER_E5B_INDEPENDENT_REVIEW_2026-09-12.md`
- `docs/CONFIRMED_STARTER_E5B_AGENT_PROMPT_2026-09-12.md`
- `docs/CONFIRMED_STARTER_RACE_OBJECTIVE_PROTOCOL_V3_2026-09-12.md`
- `docs/CONFIRMED_STARTER_E5B_2026-09-12.md`
- H1 manifest 및 E1/E2/H1의 모집단·시간·결과 불변성 계약.

## 1. 양 후보 통과 후 평가하는 실행 구조

기존 E5-B runner는 한 후보의 학습·temperature·validation 평가를 모두 끝낸 뒤 다음 후보를 시작한다. 두 번째 후보가 실패하면 첫 후보 validation 결과가 이미 생성된다.

기존 E5-B 파일 및 artifact를 수정하지 말고 별도 연구용 orchestrator/helper에 다음 구조를 구현하라.

1. 후보별 selector→refit→calibration 검사까지 준비한다.
2. 기대한 두 후보가 정확히 존재하며 모두 승인된 상태인지 공통 검사한다.
3. 통과한 경우에만 validation 예측·라벨 결합·지표 산출·comparison 저장을 시작한다.

합성 데이터와 stub/spies로 실제 실행 함수를 검사하라. 별도로 만든 가짜 함수만 테스트하지 않는다.

- 두 번째 후보 boundary 실패 시 validation 예측·평가 호출 0, validation 산출물 0, 실패 사유 보존.
- 첫 후보 실패, 누락·중복 후보, 비유한 temperature도 같은 실패 계약.
- 두 후보 정상 또는 허용 structural-flat이면 공통 통과 뒤 양쪽 평가가 정확히 한 번 실행.
- 후보 실행 순서를 바꿔도 계약 유지. 한 후보 성공만으로 비교하지 않음.

기존 Booster 재로드는 허용하지만 이 보완 때문에 실제 tree를 다시 학습하지 않는다. 과거 E5-B의 실행 순서를 사후 변경된 것처럼 기술하지 않는다.

## 2. 추가 정보 가설: 부담조건

현재 136개 feature를 기준으로 다음 세 후보만 감사하라. 성능을 보고 목록을 바꾸지 않는다.

- `condition_carried_weight_kg`: 해당 출전의 부담중량.
- `condition_carried_weight_rel_A`: 해당 중량−A 내 관측 가능한 유효 중량의 평균. 결측 포함 시 분모·최소 관측수·전부 결측 정책을 명시한다. 사후 정상완주집합 N을 사용하지 않는다.
- `condition_carried_weight_delta_prev_start`: 해당 중량−그 말의 날짜가 엄격히 이전인 가장 최근 실제 출발의 중량. 그 직전 출발의 중량이 결측이면 결측이며, 편의상 더 오래된 비결측 경주로 건너뛰지 않는다. 실제 첫 출발, 이력 관측 범위 밖, 미확정 이전 출발은 구분한다.

공식 레이팅·등급 대리변수·배당·당일 마체중 기반 부담률은 이 후보 목록에 추가하지 않는다. 부담중량은 능력 배정과도 연관되므로 발견된 관계를 중량의 인과효과라고 주장하지 않는다.

감사 범위는 서울 H1 A의 15,579행·1,488경주, 2026-05-31까지다. 과거 이력이 필요하면 그 이전 자료의 기간과 쿼리를 명시한다. DB는 읽기 전용, 시간가변 원천은 모두 상한 조건을 적용한다. June 이후 실제 행을 열거나 수집하지 않는다.

각 후보에 대해 다음을 증거로 남겨라.

- 실제 원문 필드→parser→DB→feature 변환 경로, 단위·유효성 규칙·결측률·출처.
- event/effective 시각과 observed/published 시각의 구분. 경주 후 수집 원문이 과거 cutoff 상태를 증명하는지 여부.
- 출전 시점 중량과 결과 확정 중량의 구분, 변경 이력·override·정정에 대한 가용 증거.
- DNF/실격/미출주와 이전 실제 출발 분류. target 결과가 바뀌어도 target의 기존 A와 predictor가 바뀌지 않는 계약.
- H1에 이미 있는 비선택 열은 이름만 믿지 말고 독립 원천·산식과 대조. 이전 이력의 시작 범위와 left truncation을 명시.

T-30에 관측되었다는 증거가 없으면 `retrospective_only / availability_unverified`처럼 구분한다. 공개될 법하다는 추정으로 PIT 통과시키지 않는다. 후향 연구도 정당화할 수 없는 중량이면 격리하고 실패 이유를 제출한다. 일부 원천 문제 때문에 다른 두 작업까지 중단하지는 않는다.

가능한 행에는 새 보조 feature parquet을 별도 경로로 만들고, H1의 전체 키를 보존하라. 선택 제외나 결측 때문에 inner join으로 행을 줄이지 않는다. 상태·가용성 표시는 metadata로 유지하고 임의로 학습 입력에 추가하지 않는다. 원본 136개 predictor·라벨·원천 H1은 변경하지 않는다.

독립 집계로 전수 검증하고, 실제 모듈에 target 결과 삭제/변경·당일 결과 변경·합성 미래행 추가·행 순서 변경 반례를 적용하라. 이전 출발 상태는 이력 계약에 따라 다룬다. 관측 가능 시각과 모집단을 고정하지 않고 결과만 지우는 형식적 테스트로 대체하지 않는다.

## 3. 후속 E6-B protocol 초안만 작성

후속 비교는 동일한 BINARY 학습 절차의 기존 136개 vs 감사 통과한 부담조건 추가 두 후보로 제한한다. BINARY는 고정 대조법으로 사용하는 것이며 E5-B 승자로 선언하는 것이 아니다. RACE_SOFTMAX·seed 탐색·추가 보정법을 동시에 바꾸지 않는다.

개발 검증은 2026-02-28 이전 데이터 안에서 확장 학습창을 쓰는 시간순 fold 3개를 제안하라. 각 fold에 selector fit/tune→fit+tune refit→별도 calibration→그 이후 평가 경주를 분리하고, 평가 기간끼리 겹치지 않게 한다. 최소 표본을 확인한 뒤 날짜와 행·경주 수를 숫자로 고정한다. 원천 적합성 감사가 끝나기 전에 임의 날짜를 확정하지 않는다.

encoder는 각 fold의 selector fit 범위에만 적합해 freeze하고, 후보 간 기존 열의 mapping을 공유한다. 현재 H1 feature 자체에 남아 있는 snapshot PIT 및 과거 source 한계를 별도 표시한다. fold를 추가했다고 기존 정보를 독립 test로 바꾸어 부르지 않는다.

주 지표는 동일 정의의 경주 평균 winner-set NLL, 보조는 binary NLL/Brier/Top1/3/5다. 모든 예정 fold를 보고하고 좋은 fold만 고르지 않는다. uncertainty는 같은 경주 paired 및 경주일 cluster 방식, 전체 경주 가중 통합과 fold별 결과를 함께 명세한다. 독립 미래 성능 주장은 하지 않는다.

3~5월 validation은 이번 단계에서 새 성능을 계산하거나 선택에 사용하지 않는다. 6월 이후 결과 개방과 운영 승격도 하지 않는다. 구체적인 후보·분할·예산·실패 규칙을 작성한 뒤 독립 검증에 제출한다. 실제 학습은 후속 지시에서 수행한다.

## 제출 및 보존

새 보고서, 원천 감사 JSON, keyed 보조 feature/evidence parquet, feature 계약과 테스트, 실행 경계 테스트, 후속 protocol 초안을 제출하라. 기존 H1/E3/E4/E5-A/E5-B·registry의 hash를 전후 대조하고 원본은 덮어쓰지 않는다. 새 파일 이름에는 E6-A를 명시한다.

관련 Ruff/format·필요한 회귀 테스트·전체 pytest·diff-check를 실행하고 기존 범위 밖 오류를 구분한다. 정보 부족으로 배제된 후보와 남은 가정도 결과다. 통과를 위해 원천을 추정하거나 가설을 바꾸지 말고, 검증 가능한 산출물까지 완성한 뒤 실제 학습 없이 종료하라.
