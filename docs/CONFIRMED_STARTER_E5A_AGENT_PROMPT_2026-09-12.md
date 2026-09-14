# E5-A: 목적함수 수학 보완·합성 API 검증·실행 명세 확정

작업 경로: `/Users/kimyongjin/Desktop/horse_racing`

E4 동결 진단은 독립 검증을 통과했다. 다음 실제 경마 학습에 앞서 이 작업 하나에서
수학 함수의 두 결함, group/custom-objective 연동, 미완료 protocol을 해결하라.

먼저 다음 문서를 읽어라.

- `docs/CONFIRMED_STARTER_E4_INDEPENDENT_REVIEW_2026-09-12.md`
- `docs/CONFIRMED_STARTER_RACE_OBJECTIVE_PROTOCOL_DRAFT_2026-09-12.md`

## 범위와 보존

실제 H1/E3/E4 데이터·예측·보고서·manifest·원본 source hash를 보존하라.
보완된 수학 함수와 adapter는 새 E5 연구 모듈에 구현하고, 새 학습 경로에서 기존 E4의 결함 함수를
참조하지 않게 하라. 기존 E4 코드와 봉인 manifest를 수정해 과거 증거를 덮어쓰지 않는다.

**합성 데이터로 작은 LightGBM 모델을 학습하는 API spike는 허용한다. 실제 경마 tree 학습은 하지 않는다.**
기존 H1 manifest·schema·봉인된 기간 메타데이터 확인은 허용하지만 추가 성능 탐색은 하지 않는다.
2026-06-01 이후 실제 행은 조회·탐색·평가하지 않는다. 운영 연결·registry 변경·배팅은 없다.

## R1/R2 수학 보완

1. CE를 shifted logits 좌표에서 계산해 큰 공통 이동의 cancellation을 없앤다.
   z=[0,0]와 z=[1e16,1e16], q=[0.5,0.5]에서 모두 log(2)를 반환해야 한다.
   [1000,0,-1000] 등의 극단값도 확률을 log 취하기 전에 0으로 만들어 loss를 잘못 clipping하지 않는다.
2. 순수 수학 입력의 q 합 검사를 명시적 절대 tolerance로 고정한다. q=[0.5,0.500001]은 거부한다.
   허용오차 안의 반올림을 정규화할지 또는 어떤 수식을 적용할지 고정해 loss와 gradient가 일치하게 한다.
3. 정확 gradient p−q, 전체 Hessian diag(p)−ppᵀ, 반환 대각 근사를 구분한다.
   중앙 유한차분으로 gradient와 전체 Hessian을 독립 검사한다.
4. 경주 내 순열, 경주 순열, 경주별 서로 다른 공통 이동, 다중 group, 단독/동착,
   극단 logit, 빈 입력·음수 label·비유한값·잘못된 group을 검사한다.
5. 큰 상수 이동 후 작은 차이 자체가 float64에서 소실된 경우와 계산식 cancellation을 구분한다.
   표현 불가능한 차이를 복원했다고 주장하지 않는다.

## 합성 API spike

설치된 LightGBM 4.7.0의 실제 public fit 경로를 사용하라. wrapper 코드 열람만으로 PASS 처리하지 않는다.
필요하면 공식 문서와 설치 source를 대조한다. Native Dataset(group=...) adapter를 사용해도 되지만
실제 선택한 경로 하나와 이유를 명시하고 두 후보의 prediction interface를 통일한다.

합성 경주는 서로 다른 두수, 단독 우승, 2두 및 3두 동착, 음성 라벨 출전마를 포함한다.
대략 수십 경주·수백 행, 최대 20 boosting round 정도의 기능 검사로 제한하며 성능 탐색을 하지 않는다.
min_data_in_leaf 등 toy 전용 설정은 실제 연구 설정과 구분한다.

다음 증거를 실제 callback에서 기록하고 assert하라.

- 전달된 label·raw margin·weight·group의 shape, dtype, 값, group 총합.
- group이 사전 정렬한 경주와 정확히 대응하고 fit/tune을 혼동하지 않음.
- custom objective와 eval callback이 raw margin을 받는지, BINARY 평가 경로가 받는 값은 무엇인지.
  built-in binary와 custom objective에서 callback prediction 의미가 같다고 추정하지 마라.
- float soft label, 특히 1/3의 buffer 표현 오차와 q 복원 정책. 원래 win indicator를 전달하고
  callback에서 경주별 q를 만드는 방식도 가능하나 정책을 명확히 고정한다.
- BINARY의 원래 winner indicator와 RACE_SOFTMAX의 정규화 q를 혼동하지 않음.
  built-in binary가 분수 label을 원하는 의미로 사용하는지는 확인 없이 가정하지 마라.
- 목적함수·metric이 인접 경주의 score를 섞지 않으며 경주별 상수 이동에 불변임.
- 원래 row 순서와 재정렬 후 key 복원, 저장/reload 후 raw margin·확률의 재현.
- Hessian이 0/극소가 되는 경우와 필요한 floor/근사 정책. floor를 적용하면 정확 대각과 구분한다.
- 명시적 group 없이 호출하거나 group 합이 틀린 입력을 거부함.
- early stopping에서 정확히 지정한 단일 custom metric이 사용되고 의도하지 않은 기본 metric이
  stopping을 좌우하지 않음.

## 최종 protocol v2

실제 데이터 학습을 시작하지 말고 바로 실행 가능한 다음 연구 protocol을 새 파일로 확정하라.
후보는 동일 A/136개 feature의 BINARY와 RACE_SOFTMAX 두 개, seed 42다.

반드시 숫자·산식·실제 API 경로까지 고정할 항목:

1. 두 후보의 라벨·loss·경주/행 가중·gradient 스케일, regularization 및 Hessian 처리.
   동일 hyperparameter가 동일한 최적화 곡률을 의미하지 않는다는 한계도 기록한다.
2. H1의 기존 fit/tune/calibration 날짜 경계와 행 수. 공통 encoder의 적합 범위와 hash.
3. tree 최대 수 1200, learning rate .03, num_leaves 31 등 기존 E3 기본 용량을 출발점으로 삼고
   정확한 두 후보 설정을 표로 고정한다. API상 변경이 필요하면 원인과 양 후보 적용 범위를 명시한다.
4. 단일 primary early-stopping metric, 동착 포함 여부 및 산식, patience, refit 범위와 iteration.
   권고는 전체 tune 경주의 soft-label CE를 동등 가중하는 것이다. winner-set NLL은 별도 보고한다.
5. 양 후보 모두 raw margin→race softmax→단일 temperature를 쓰는 공통 최종 변환.
   temperature는 과거 calibration 블록에서만 적합한다. 유한 log-temperature 범위와
   optimizer·tolerance·경계해·평평한 목적함수·실패 처리까지 결과를 보기 전에 고정한다.
6. validation을 후보/보정 선택에 재사용하지 않는 절차. 이미 반복 사용한 3~5월 개발 평가를
   독립 test라고 부르지 않으며, June 이후 실제 결과는 계속 열지 않는다.
7. 주 지표·보조 지표, 동점·동착·clipping 또는 안정적 log 확률 정책, 정확한 키 검증,
   원래 E3와 동일한 paired 경주/경주일 bootstrap 방식. E3와 확률변환이 달라진 사실을 명시한다.
8. 정확히 두 신규 연구 모델만 실행하는 예산, 재현 산출물, 운영 격리 및 실패 시 중단 조건.

실제 학습 실행에 추가적인 설계 선택이 필요 없도록 명세하되, 이 작업에서는 실행하지 않는다.

## 제출

새 E5-A 보고서, protocol v2, 수학 구현/테스트, 합성 fit 실행 코드, callback evidence JSON,
합성 bundle/reload 검증, 실행 및 원본 전후 해시를 제출하라.
관련 Ruff/format·전체 pytest·diff-check를 실행하고 범위 밖 기존 오류를 구분한다.

요약에는 R1/R2 반례의 before/after, 실제 검증한 public API, 사용한 Hessian 근사,
동착 및 temperature 정책, 다음 실제 연구의 정확한 변경점과 남은 한계를 적어라.
이 단계의 PASS는 경마 예측력 개선 증거가 아니다. 독립 검증 제출 후 실제 학습·운영 연결 없이 멈춰라.
