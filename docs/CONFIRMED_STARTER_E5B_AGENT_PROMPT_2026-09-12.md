# E5-B 실행 지시: 동일 A 입력의 BINARY vs RACE_SOFTMAX 개발 연구

작업 경로: `/Users/kimyongjin/Desktop/horse_racing`

E5-A R3/R4 독립 검증을 통과했다. **protocol v3의 실제 경마 개발 연구 학습과 비교를 실행하라.**
본 지시서는 해당 연구 실행을 승인한다. 추가 확인을 위해 멈출 필요 없이 아래 범위를 완료하고
독립 검증용 산출물을 제출하라. 운영 승격 및 June 이후 실제 결과 개방은 승인하지 않는다.

먼저 다음 문서를 읽어라.

- `docs/CONFIRMED_STARTER_E5A_R3_R4_INDEPENDENT_REVIEW_2026-09-12.md`
- `docs/CONFIRMED_STARTER_RACE_OBJECTIVE_PROTOCOL_V3_2026-09-12.md`
- E3/E4 보고서는 배경으로만 참고한다. 그 결과에서 새 후보나 설정을 고르지 않는다.

## 동결 계약

protocol v3 SHA256:
`d539b7333b7dd2eb0ec8d7589879ca7de2a7e623d654c56f8c9349bd91da6984`

`src/horse_racing/analysis/confirmed_starter_e5_r3r4.py` SHA256:
`55c7dcf686e4bf068b488beb396ffe18fd37a9f179939195494b21f9f35982d0`

H1 입력 폴더:
`data/datasets/confirmed_starter_e2_h1_remediation_retrospective/start_minus_30m/`

- dataset SHA256: `9d508bfdea325482461fa5d4e1b9a3ea8543bfe146a9b40b5400f4084064d6a7`
- manifest SHA256: `f36cc08930c4010cc3be230575289d06110add010d4c3ad368dbdad5f142d801`
- 136개 feature 이름·순서 hash: `b7f57b9939aac9b51993e29046d43a10c9f49fdcfac0b821807300459ef2ac48`
- 공통 category-map hash: `f3800b712d39af44a0d5ae7cfa9c74ca7ebdd9ff287e38c4a477a7b0c4b55d00`

기존 dataset·source·모델·manifest·보고서·dirty work는 보존한다.
새 E5-B runner·평가 모듈·테스트가 필요하면 별도 연구 파일에 구현한다.
승인된 math/adapter를 몰래 수정하거나 과거 오류 함수로 fallback하지 않는다.
실행 중 계약 결함을 발견하면 실패 증거를 저장하고 보고한다.

## 학습 전 작업

새 `data/experiments/confirmed_starter_e5b_race_objective_20260912/` 연구 폴더를 사용한다.
이미 존재하면 덮어쓰지 말고 명확한 새 attempt 경로를 사용해 이력을 남긴다.

첫 tree fit 전에 protocol JSON을 작성한다. 승인된 v3의 입력·두 후보 설정·분할·가중치·metric·
temperature 규칙·bootstrap·검증 tolerance·중단 조건을 기계 판독 가능하게 고정한다.
코드 hash, 환경 버전, git HEAD/dirty 상태, 입력 및 운영 registry 전후 해시를 저장한다.

H1의 15,579행·1,488경주와 독립 manifest 키, 라벨·특수 상태 mask를 검사한다.
공통 encoder는 A train 12,528행에서만 한 번 적합한다. encoder 적합에 validation은 넣지 않는다.

| partition | 행 | 경주 |
|---|---:|---:|
| fit | 8,719 | 844 |
| tune | 2,001 | 187 |
| calibration | 1,808 | 169 |
| validation | 3,051 | 288 |

날짜는 v3 그대로다. 각 partition을 날짜/race_id/entry_id로 정렬하고 전체 경주를 연속 배치한다.
key·group·label·matrix 및 categorical feature 계약을 양 후보에서 동일하게 검증한다.
feature 결측은 기존 encoder 정책을 유지한다. 임의의 값 채움이나 feature 재계산은 하지 않는다.

## 정확히 두 후보 실행

후보는 win head의 BINARY, RACE_SOFTMAX 두 개다. N arm이나 E3 저장 모델을 baseline으로
재사용하지 않는다. 양 후보 모두 승인된 custom objective와 raw-margin metric을 사용한다.

각 후보는 fit selector→tune early stopping→fit+tune refit 절차를 한 번 실행한다.
따라서 2개 selector와 2개 최종 refit fit 호출은 정상 예산이다. 추가 seed/설정 탐색은 없다.
selector에서 v3의 최대 1200 round·patience 80·기타 parameter를 그대로 적용한다.
refit은 공통 encoder를 유지하고 10,720행에서 선택된 best iteration만큼 처음부터 학습한다.

BINARY는 winner indicator 0/1, float32 buffer의 1/field_size weight를 검사한다.
RACE_SOFTMAX는 원래 winner indicator에서 q를 복원하고 weight=None, 대각 Hessian floor 1e-6을
유지한다. native Dataset에 공통 categorical feature 정의를 명시한다.

runner의 callback 경계에서 들어오는 margin, label/group/weight와 반환 gradient/Hessian의
유효성을 검사한다. 비유한 값을 clip·치환하거나 모델 내부에서 조용히 정규화해 숨기지 않는다.
Hessian floor count를 iteration과 partition별로 기록한다.

모든 selector iteration의 raw margin hash와 독립 CE를 v3대로 대조한다.
early stopping 이후에도 그 검증이 가능하도록 `keep_training_booster=True` 등 검증된 보존 경로를
사용하고, 필요하면 best iteration 이후까지 포함한 selector를 명시적 num_iteration으로 저장한다.
default best_iteration 자동 적용 때문에 마지막 iteration 감사가 잘못된 모델을 읽지 않게 하라.
최종 refit artifact와 selector artifact를 구분해 저장한다.

## Temperature 및 실패 처리

두 refit의 calibration raw margin에만 승인된 beta endpoint/root 절차를 적용한다.
endpoint/solution의 목적·도함수·곡률·상태와 T를 저장한다.
양 후보가 승인된 flat 또는 interior 상태를 통과한 뒤에만 validation 비교를 수행한다.

temperature가 경계해이거나 다른 계약이 실패하면 비교를 중단하고 실패 manifest·attempt ledger를
제출한다. 범위를 넓히거나 T=1로 바꾸거나 calibration 후보를 추가하지 않는다.
실패를 숨기는 재실행, 한 후보만 성공한 상태의 우월성 보고도 하지 않는다.

## 공통 평가와 산출물

validation 3,051행·288경주의 사전 키를 분모로 두 후보 예측을 각각 검증한다.
coverage·누락/추가/중복·마번·확률합·finite·save/reload 계약은 v3 그대로다.
합성 probe에 사용한 init_score/L2/leaf 설정을 실제 연구에 옮기지 않는다.

주 지표는 stable log-domain의 race-equal winner-set NLL이다.
temperature가 적용된 raw margin으로 직접 계산하고, 저장 확률이 underflow해 0이 됐다고
주 손실을 epsilon으로 잘라내지 않는다. soft-label CE와 winner-set NLL은 동착에서 구분한다.
서로 다른 score를 가진 우승/패배마의 극단 synthetic 사례로 log-domain 산식을 독립 검증한다.

보조는 v3의 CE, entry-equal binary NLL/Brier, 저장 prob_win의 동점 기대 Top1/3/5다.
binary NLL은 E3와 비교 가능한 epsilon 1e-15 clipping 정의와 발생 수를 명시한다.
이는 주 지표의 log-domain 정책과 다른 보조 정의임을 구분한다.
score 동점·probability 동점·underflow·Hessian floor 수를 각각 기록한다.

delta=RACE_SOFTMAX−BINARY, 음수 loss delta가 후보 개선이다.
paired 경주 및 경주일 cluster bootstrap은 각각 5000회, seed 20260911, percentile 95% CI다.
경주일은 그 날의 전체 경주를 묶고 반복 추출해 표본 내 경주 평균을 계산한다.
저장 예측에 조건부인 구간이며 재학습·탐색 변동성을 포함하지 않는다고 명시한다.
12개 특수 상태 경주/나머지 276개는 사전 고정 진단만 수행한다.

저장할 항목:

- 사전 protocol, input/encoder/matrix/key/group/code hashes.
- 두 후보의 selector, callback 감사, best iteration, refit Booster와 새 연구 run ID.
- calibration·validation keyed raw margin/확률, T 진단, 독립 reload 대조.
- 경주별 CE/winner-set loss/paired delta, comparison JSON, bootstrap, 보고서.
- attempts, 검사 결과, 연구 전용 ledger, 전체 output hash manifest, 기존 자료 보존 검사.

새 runner/평가 계약을 의미 있는 합성 반례로 검사하고 관련 Ruff/format, 전체 pytest,
diff-check를 실행한다. 기존 범위 밖 오류를 구분한다.

결과 보고서는 주 지표와 CI를 먼저 제시하고 T·iteration·coverage·재현성·보조 지표를 덧붙인다.
3~5월은 반복 사용한 개발 평가다. 개선이 보여도 독립 test 통과나 운영 승격으로 해석하지 않는다.
실제 2026-06-01 이후 자료, DB/운영 prediction·배팅 경로, 기본 registry/champion은 변경하지 않는다.
두 후보의 결과 또는 명세된 실패 증거를 제출하고 다음 연구 없이 멈춰라.
