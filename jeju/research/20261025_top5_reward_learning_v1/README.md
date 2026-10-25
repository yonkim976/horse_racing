# F1_STYLE6 보상 목적 Top5 학습 결과

상태: **3개 fold 학습, label-free 5두 선택, 같은 경주 3-arm 결과 비교 완료. 사전 성공 기준은 통과하지 못했다.** 이 자료는 반복 사용된 과거 개발기간의 비교 결과다. 새 holdout이나 미래 예측 검증이 아니며 운영 모델·DB·registry는 변경하지 않았다.

## 질문과 보상 정책

F1_STYLE6 말 평가기와 원점수를 고정하고, 같은 11개 과거력 입력만 받는 작은 additive 선택 head를 실제 학습했다. 경주별 모든 `C(N,5)` 집합에 대해

`E_r(S;β) = Σ(i∈S) z_i + βᵀΣ(i∈S) x_i`

를 계산했다. `z_i`는 고정 F1_STYLE6 원점수의 경주 안 `ddof=0` 표준점수이며 `x_i`는 fold별 학습 runner에서 표준화한 고정 11개 feature다. 선택 정책은 `πβ(S | 사전 경주 입력)=softmax(E_r(S;β))`다. **이 정책분포는 사전 입력만 사용하고 actual Top3를 조건으로 하지 않는다.** Training race의 결과 라벨은 good action을 표시할 때만 사용했다: `G_r={S: actual Top3 ⊆ S}`, `Pgood_r=Σ(S∈G_r)πβ(S|사전 입력)`, `E[R|r]=2Pgood_r−1`. 즉 `Pgood`와 reward 계산에는 관측한 actual Top3가 필요하지만, 그 라벨은 정책의 선택분포 자체에 들어가지 않는다.

각 경주에서 actual Top3 세 두를 모두 포함한 다섯 두 집합은 `+1`, 그 밖의 집합은 `−1`로 두고, 고정 목적함수 `J(β)=mean_r[1−2Pgood_r]+0.5||β||²`를 최소화했다. `λ=1`, temperature `1`, 영벡터 시작 L-BFGS-B 1회(`maxiter=1000`, `ftol=1e-12`, `gtol=1e-8`)만 사용했다. 재시작이나 탐색은 없었다. 이 방법은 모든 행동집합과 보상을 열거한 exact expected-reward/policy-gradient 학습이다. PPO나 LLM fine-tuning이 아니다.

학습한 Gibbs 집합 확률과 expected reward는 실제 입상 확률로 보정되지 않았다. 학습 목적과 결과에서 평가한 결정적 `argmax_S E_r(S;β)` 선택 사이에는 surrogate gap이 있다. 최종 비교는 deterministic 선택의 실제 all-three coverage만 집계했다.

## 데이터와 학습

원천은 고정된 feature parquet와 저장된 OOF F1_STYLE6 raw scores다. 2019–2022 score는 OOS expansion 결과, 2023–2025 score는 style-history ablation 결과의 `F1_STYLE6_{label year+1}` provider를 사용했다. metadata `refit_max ≤ race_date−2 days`를 각 학습 runner에 검사했다. 입력 구성·11개 feature·`log1p` count 변환·결측 평균대치/표준화·ddof·additive set 합산은 직전 partial-event NLL head와 동일하다. feature scaling은 각 fold의 training runner만으로 적합했다.

| head 평가연도 | 사용한 결과 라벨 연도 | training races / runners | 전수열거 set 수 | good set 수 | 최종 목적함수 | train stochastic expected reward | 최종 gradient 최대 절대값 |
|---:|---|---:|---:|---:|---:|---:|---:|
| 2024 | 2019–2023 | 2,492 / 25,278 | 769,121 | 55,516 | 0.6438863 | −0.632283 | 1.64e−9 |
| 2025 | 2019–2024 | 3,129 / 31,607 | 925,207 | 68,660 | 0.6415156 | −0.629255 | 1.94e−9 |
| 2026 | 2019–2025 | 3,783 / 38,017 | 1,076,359 | 81,662 | 0.6375118 | −0.625714 | 2.21e−9 |

각 결과 라벨 cutoff는 `2019 ≤ year < 평가연도`다. 매 training race의 완전한 `1..N` finish와 정확히 세 개 Top3 라벨을 optimizer 전에 확인했다. 평가연도 라벨은 fit에서 열지 않았다. Training expected reward가 음수인 것은 광범위한 `C(N,5)` action space에서 correct set에 주어진 Gibbs mass의 진단값이다. 결정적 선택의 실제 hit rate 또는 미래 race 확률로 읽지 않는다.

## 선택과 같은 경주 비교

비교 대상은 같은 17,412 runner / 1,779 race roster다: 고정 원점수 Top5, 기존 partial-event NLL selector, 이번 expected-reward selector. 기존 선택 원장·모델은 그대로 hash 참조했다. 주 평가집단은 2024-01-05~2026-09-19의 900/1000/1110/1200m 1,503경주이며 1,779경주 전체는 보조 평가다. 269개 경주일의 고정 2,000회 paired date bootstrap을 썼고 percentile은 NumPy linear quantile다.

| 모집단 | 선택기 | all-three hit | 비율 | 선택 Top5에 포착한 actual Top3 평균 | 포착 수 0 / 1 / 2 / 3 |
|---|---|---:|---:|---:|---|
| 주 1,503경주 | raw-score Top5 | 439 | 29.208% | 2.072 | 26 / 279 / 759 / 439 |
| 주 1,503경주 | 기존 partial-event NLL | 435 | 28.942% | 2.071 | 28 / 272 / 768 / 435 |
| 주 1,503경주 | 새 reward head | 434 | 28.876% | 2.063 | 27 / 285 / 757 / 434 |
| 전체 1,779경주 | raw-score Top5 | 519 | 29.174% | 2.073 | 29 / 331 / 900 / 519 |
| 전체 1,779경주 | 기존 partial-event NLL | 520 | 29.230% | 2.074 | 30 / 328 / 901 / 520 |
| 전체 1,779경주 | 새 reward head | 515 | 28.949% | 2.064 | 30 / 341 / 893 / 515 |

| paired 차이 (후보 − 기준) | 모집단 | 차이 | 고정 date-bootstrap 95% CI | 둘 다 hit | 기준만 hit / 후보만 caught | 둘 다 miss | 선택 집합 변경 |
|---|---|---:|---:|---:|---:|---:|---:|
| reward − raw | 주 | −0.333%p | [−1.646, +1.047]%p | 387 | 52 / 47 | 1,017 | 370 |
| reward − old NLL | 주 | −0.067%p | [−1.318, +1.136]%p | 391 | 44 / 43 | 1,025 | 356 |
| reward − raw | 전체 | −0.225%p | [−1.525, +1.125]%p | 456 | 63 / 59 | 1,201 | 464 |
| reward − old NLL | 전체 | −0.281%p | [−1.454, +0.905]%p | 465 | 55 / 50 | 1,209 | 436 |

사전 primary 성공 기준은 reward−raw와 reward−old NLL 모두 paired 차이 `>0`이고 95% CI 하한도 `>0`인 경우였다. 두 비교 모두 평균 차이가 음수이고 CI 하한도 0보다 작아 기준을 통과하지 못했다. 이 자료에서 expected-reward 목적이 원점수 Top5나 이전 head보다 더 나은 실제 deterministic all-three 선택을 만들었다는 증거는 없다. 전체 표본 보조 결과도 새 head가 두 기준선 모두보다 낮았다.

주 집단의 연도·거리별 hit 수와 paired 차이는 아래와 같다. 2026년은 9월 19일까지의 부분연도다. 이 하위집단 수치는 기술통계로만 보며 별도 성공 판정이나 유의성 탐색에 사용하지 않았다.

| 분할 | 경주 수 | raw hit | old NLL hit | reward hit | reward−raw | reward−old NLL |
|---|---:|---:|---:|---:|---:|---:|
| 연도 2024 | 499 | 140 | 133 | 132 | −1.603%p | −0.200%p |
| 연도 2025 | 559 | 164 | 167 | 167 | +0.537%p | 0.000%p |
| 연도 2026* | 445 | 135 | 135 | 135 | 0.000%p | 0.000%p |
| 거리 900m | 251 | 74 | 68 | 69 | −1.992%p | +0.398%p |
| 거리 1000m | 508 | 155 | 154 | 146 | −1.772%p | −1.575%p |
| 거리 1110m | 482 | 136 | 142 | 142 | +1.245%p | 0.000%p |
| 거리 1200m | 262 | 74 | 71 | 77 | +1.145%p | +2.290%p |

선택기는 primary 경주의 1,503개 중 raw 대비 370개, 기존 partial-NLL 대비 356개의 집합을 바꿨다. 전체 1,779개에서는 각각 464개, 436개를 바꿨다. 거리·연도별 편차가 있지만 primary 전체의 두 paired 기준을 통과하지 않았다.

## 사전 수학 검산 및 실행 독립 검토

초안 코드의 수학 검산에서 실제 objective 값은 맞았지만 grouped helper가 모든 race를 합친 기대 feature 한 벡터만 반환한 뒤 race별 `Pgood`를 곱하는 오류가 발견됐다. 이를 수정해 race별 `(race_count, 11)` 기대 feature 행렬을 반환하도록 했고, 실패 receipt는 덮어쓰거나 삭제하지 않고 이전 코드의 차단 증거로 남겼다. 오류 코드 hash `808e0cde0e04a6046bc4345cb0072b28c6d3d3eb10f364125e129315500b4f8a`의 audit은 objective 값 오차 0, 독립 gradient 및 finite-difference 오차 약 0.125를 기록했다. Fit 전에 수정 코드를 다시 검증했다: root actual-code audit은 유한차분 최대 오차 `3.36e−10`, 독립 policy-gradient 최대 오차 `9.99e−16`, brute-force reward-loss 오차 `1.11e−16`, feature expectation shape `(3,11)`, 전체 positive-mask·행 순열 불변성·필드수 5 all-good control을 통과시켰다. 수정된 승인 코드 hash는 `043c669ad6f8d7a9d66bb5846002758385c3e0811e7e6720727b2e5c1e9b85dc`다.

별도 fitted-model 검산은 세 fold 모두 전처리·목적함수·계수를 독립 재계산하고, target-fold evaluation labels를 읽지 않았으며, 각 fold의 gradient maximum을 `2.22e−9` 이하로 확인했다. 독립 selector는 1,779경주 선택 전부와 일치했고 zero-β baseline identity 및 runner order invariance를 확인했다. 독립 outcome 재계산도 세 arm의 1,503/1,779경주 집계와 고정 bootstrap 결과를 확인했다. 해당 audit들은 본 연구 폴더에 복사하지 않고 root-review 경로·hash로 연결했다.

## 자료 정정과 한계

이 분석은 전체기간을 반복 사용한 과거 개발 분석이다. 거리별 결과를 본 독립 미래 검증으로 해석하지 않는다. 단일 additive runner utility라 5두 간 상호작용을 학습하지 않는다. 기대 보상 목적은 비볼록일 수 있으나 사전에 고정한 영벡터 시작 1회 fit만 했고, 실패 후 재시작·파라미터/feature 탐색은 하지 않았다. 계수는 개별 말 확률이나 인과효과가 아니다.

새 외부 자료, database 또는 network 접근은 사용하지 않았다. 선택에 쓰인 11개 입력은 T−2 feature snapshot이고, outcome 단계는 사전 고정된 evaluation 결과 열만 읽었다.

이전 `20261025_top5_direct_learning_v1/FINAL_MANIFEST.json`의 raw baseline hash 필드에 기록 오기가 있었고 기존 manifest는 변경하지 않았다. 원천 baseline의 올바른 SHA-256은 `c3fc8a2bf10d3fa1678ab3c5463209089021f51f6d0bf500fc2db6006fda13c1`이다. 기존 root source audit와 새 선택 코드가 이 hash를 검사했으며, correction receipt `20261025_top5_direct_gain_loss_rootreview_v1/SOURCE_HASH_METADATA_CORRECTION.json`(SHA-256 `dfa60f6e7ced44f6c565be406a6cbd5e6784da74c5752d9dada608c7e8bd648d`)에 오타/정정 이력이 보존되어 있다.

## 재현 파일과 영수증

`fit_selector.py`, `select_sets.py`, `report_outcomes.py`는 각각 fit, label-free exhaustive selection, 승인 후 outcome 집계 단계로 분리했다. 각 단계는 plan/source/code/artifact hash가 맞는 별도 root approval 없이 실행하지 않는다. 원천 feature 파일·baseline·OOF files·DB·기존 model/registry는 복사하거나 수정하지 않았다. 모델 3개와 1,779행 선택원장, 1,779행 결과원장 및 작고 hash-고정된 receipts만 저장했다. 상세 파일 SHA와 실제 저장 바이트는 [FINAL_MANIFEST.json](FINAL_MANIFEST.json)에 있다.

추가 계획·원천 정의는 [PLAN.md](PLAN.md), 고정 원천 경로·hash는 [SOURCE_AUDIT.md](SOURCE_AUDIT.md), fold별 계수·학습 검증·source checks는 [`outputs/FIT_RECEIPT.json`](outputs/FIT_RECEIPT.json), label preflight는 [`outputs/LABEL_PREFLIGHT.json`](outputs/LABEL_PREFLIGHT.json), 선택과 paired 평가 원장은 각각 [`outputs/CHOICES_RECEIPT.json`](outputs/CHOICES_RECEIPT.json)·[`outputs/OUTCOME_RECEIPT.json`](outputs/OUTCOME_RECEIPT.json)에서 확인할 수 있다.
