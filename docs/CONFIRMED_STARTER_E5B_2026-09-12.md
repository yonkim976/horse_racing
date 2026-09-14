# Confirmed-starter E5-B BINARY vs RACE_SOFTMAX 개발 연구

작성일: 2026-09-12 KST

**Protocol v3의 동일 A 입력으로 BINARY와 RACE_SOFTMAX를 한 번씩 실행했다. 주 손실의
점추정치는 RACE_SOFTMAX 방향이지만 두 사전 지정 bootstrap CI가 모두 0을 포함하므로 확정적
개선이나 winner를 선언하지 않는다. 운영 승격도 하지 않는다.**

## 주 결과

| 지표 | BINARY | RACE_SOFTMAX | delta (RACE−BINARY) |
|---|---:|---:|---:|
| race-equal winner-set NLL | 1.955400310634 | 1.949394041144 | -0.006006269491 |

- paired race bootstrap 95% CI: `[-0.035857208528, 0.024592780171]`
- 경주일 cluster bootstrap 95% CI: `[-0.035832513154, 0.024451750214]`
- bootstrap은 각각 5,000회, seed 20260911이다. 경주일 bootstrap은 28개 경주일을 cluster로
  재표집하고 선택된 날짜의 전체 경주를 포함했다.
- 두 구간은 저장된 단일 seed 예측에 조건부이며 재학습·설정 탐색 변동성을 포함하지 않는다.

Validation에는 공식 동착 경주가 없어 이 구간에서 winner-set NLL과 soft-label CE는 같다.
구현과 합성 테스트에서는 두 손실을 별도로 계산하고 동착 반례에서 값이 달라짐을 확인했다.
주 손실은 raw margin에서 stable log-domain으로 직접 계산했으며 epsilon clipping을 사용하지 않았다.

## 실행 및 temperature

| 후보 | selector best / 보존 iteration | refit iteration | T | 상태 |
|---|---:|---:|---:|---|
| BINARY | 172 / 252 | 172 | 1.104256502424 | interior_optimum |
| RACE_SOFTMAX | 120 / 200 | 120 | 1.037539316644 | interior_optimum |

두 후보 모두 승인된 `lightgbm.train` public API와 custom objective를 사용했다. BINARY는
`1/field_size` float32 Dataset weight와 floor 없는 weighted Bernoulli 미분을 사용했다.
RACE_SOFTMAX는 weight=None, 경주별 q, 대각 Hessian floor `1e-6` 계약을 사용했다. 이번 실행의
floor 적용 수는 selector와 refit 모두 0이었다.

각 selector의 모든 보존 iteration에서 callback raw-margin 전체 hash를 같은 iteration의
`Booster.predict(raw_score=True, num_iteration=i)`와 대조했다. BINARY 252개, RACE_SOFTMAX
200개 iteration 모두 hash가 일치했고 독립 CE 최대 오차는 0이었다. selector는 best iteration
자동 적용을 피하기 위해 실제 종료 iteration을 명시해 저장했으며, 최종 refit artifact와 분리했다.

Temperature는 calibration 1,808행·169경주의 refit raw margin에만 적용했다. 양 endpoint의
목적·도함수·곡률 및 내부해를 저장했다. 두 후보 모두 endpoint 도함수의 부호가 내부 root를
형성했고 fallback이나 경계 확장은 없었다.

## 입력·coverage·재현성

- 봉인 H1: 15,579행·1,488경주, dataset/manifest/136-feature/category-map hash 일치.
- 공통 encoder: A train 12,528행·1,200경주에서 한 번 적합. validation 적합 참여 0행.
- 분할: fit 8,719/844, tune 2,001/187, calibration 1,808/169,
  validation 3,051/288.
- 양 후보는 동일 matrix/key/group/label/categorical 계약을 사용했다.
- validation coverage: 양 후보 3,051/3,051행, 288/288경주. 누락·추가·중복·마번 불일치 0.
- 확률 non-finite·범위 위반 0. 경주별 합 최대오차는 BINARY `3.33e-16`,
  RACE_SOFTMAX `2.22e-16`이다.
- 모델 저장/reload 후 calibration·validation raw margin 및 확률 최대오차는 양 후보 모두 0.
- 실제 fit 호출은 selector 2회와 refit 2회뿐이다. 재시도·추가 seed·설정 탐색은 0회다.

## 보조 지표

| 지표 | BINARY | RACE_SOFTMAX | delta |
|---|---:|---:|---:|
| race-equal soft-label CE | 1.955400310634 | 1.949394041144 | -0.006006269491 |
| entry-equal binary NLL | 0.269079540632 | 0.268646754983 | -0.000432785650 |
| entry-equal Brier | 0.076572728283 | 0.076787583403 | +0.000214855120 |
| expected-tie Top1 | 0.357638888889 | 0.309027777778 | -0.048611111111 |
| expected-tie Top3 | 0.631944444444 | 0.607638888889 | -0.024305555556 |
| expected-tie Top5 | 0.829861111111 | 0.829861111111 | 0 |

보조 binary NLL만 E3 비교 정의인 epsilon `1e-15` clipping을 사용했으며 실제 clipping 수는
양 후보 모두 0이다. validation의 score tie, probability tie, 확률 underflow 0 값도 모두 0이었다.
특수 상태 12경주와 나머지 276경주의 고정 진단은 `comparison.json`에만 기록하고 후보 재선택에
사용하지 않았다.

## 검사 결과

- 새 E5-B 평가·runner와 승인된 R3/R4 테스트: 16 passed.
- 전체 pytest: 502 passed, 2 warnings.
- 관련 세 파일 Ruff check/format: 통과.
- 전체 Ruff: 기존 범위 밖 21건.
- 전체 format: 기존 범위 밖 98개 파일, 192개 파일은 formatted.
- diff-check: 기존 `src/horse_racing/web/racecourse.py:347` EOF 빈 줄 1건.

## 보존과 한계

Protocol JSON은 첫 tree fit 전에 저장됐다. H1 입력, protocol v3, 승인된 math adapter,
E3/E4/E5-A manifest 및 기본 `data/experiments/model_runs.jsonl`의 실행 전후 hash는 동일하다.
연구 run은 연구 폴더 전용 ledger에만 기록했다. champion/active pointer와 운영 prediction·배팅
경로는 변경하지 않았다.

3~5월은 반복 사용된 development validation이며 독립 test가 아니다. 단일 seed이고 두 objective의
곡률과 regularization 효과가 동일하지 않으며 bootstrap은 저장 예측에만 조건부다. 실제
2026-06-01 이후 결과는 조회·탐색·평가하지 않았다. 이 결과는 미래 성능이나 운영 적합성을
입증하지 않는다. 독립 검증 후에도 별도 승인 없이 다음 연구나 운영 승격을 진행해서는 안 된다.

## 제출 경로

- 실행 protocol: `data/experiments/confirmed_starter_e5b_race_objective_20260912/protocol.json`
- 비교: `data/experiments/confirmed_starter_e5b_race_objective_20260912/comparison.json`
- 모델·callback·temperature·keyed prediction: 후보별 하위 폴더
- paired 경주 손실: `paired_validation_race_losses.parquet`
- 연구 전용 ledger: `research_model_runs.jsonl`
- 실행 이력: `attempts.json`
- 독립 reload 대조: `reload_audit.json`
- 전체 해시: `artifact_manifest.json`
