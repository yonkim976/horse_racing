# F1_STYLE6 기반 후보 3두 축 선택기 사전 계획

상태: **source/OOF 계약과 선택 모형을 사전 고정했다.** 이 단계에서 보조 모델 학습, 새 축 선택, Top3 성과 계산은 하지 않았다. root의 source preflight 검토와 별도 fit 승인 뒤에만 평가연도별 모델 세 개를 한 번씩 학습한다.

## 질문과 평가 범위

기존 F1_STYLE6의 말 평가와 raw score를 그대로 두고, 각 경주에서 기존 raw score 상위 3두 안의 축 한 마리를 별도 선택하는 작은 모형이 기존 `argmax(score)`보다 실제 Top3 적중률을 높이는지 본다. 이는 선택 순서만 조정하는 보조 모형이며 말별 F1_STYLE6 확률을 새로 만들거나 보정하지 않는다. 이름만 바꾼 Top3 분류기를 F1 개선이라고 부르지 않는다.

주 비교 모집단은 2024-01-05~2026-09-19의 900·1000·1110·1200m 1,503경주다. 2026년은 9월 19일까지의 부분연도다. 저장된 전체거리 1,779경주도 같은 결과를 보조로 보고한다. 확정 단승 최저배당이 유일한 1,477경주로 표본을 제한하지 않는다. 배당·favorite ID를 입력, 필터, 학습 라벨로 사용하지 않는다.

평가기간은 과거 분석에서 반복 사용된 개발 표본이다. 이 후향 비교는 독립 미래검증, 구매 전 예측, 수익성, 인과효과 또는 운영 승격으로 해석하지 않는다. 현재 F1_STYLE6 raw score와 `p_top3` 원값은 기준 비교 자료로 보존하고 selector 출력으로 덮어쓰지 않는다.

## OOS 점수 연결과 시간 분할

모델별 학습연도 `c`에는 해당 연도의 라벨을 학습하지 않은 `F1_STYLE6_{c+1}/calibration_scores.parquet` raw score만 연결한다. 대상 평가연도 `Y`에는 동결된 `F1_STYLE6_Y/evaluation_scores.parquet` raw score를 사용한다. 연결키는 `api_record_id`이며, 매 행에 provider fold 연도·역할·원본 경로·SHA-256·provider `refit_max`를 기록한다. provider 파일은 학습·평가연도 전체 편성을 정확히 덮어야 하며 `refit_max <= race_date - 2일`을 행별로 확인한다.

| selector 평가연도 | selector 학습 라벨 연도 | source 전체 경주/출전 | 학습 후보행(3×경주) | 학습 마지막 경주일 | 평가 경주/출전 |
|---:|---|---:|---:|---|---:|
| 2024 | 2019–2023 | 2,492 / 25,278 | 7,476 | 2023-12-30 | 637 / 6,329 |
| 2025 | 2019–2024 | 3,129 / 31,607 | 9,387 | 2024-12-28 | 654 / 6,410 |
| 2026 | 2019–2025 | 3,783 / 38,017 | 11,349 | 2025-12-27 | 488 / 4,673 |

2017–2018은 현재 recipe에 맞는 과거 OOS raw score가 없어 학습에서 제외한다. 연도별 expanding fit 세 번만 한다. 2024 평가 모델은 2024 라벨을 절대 사용하지 않는다. 2025 평가는 2019–2024, 2026 평가는 2019–2025만 사용한다. 무작위 분할·경주 내 출전 분할·글로벌 2024–2026 fit은 하지 않는다. 2024–2026 성과를 본 뒤 학습창·입력·규제·선택 규칙을 바꾸지 않는다.

학습 OOS 점수의 model vintage는 `F1_STYLE6_{c+1}`이고 평가점수는 `F1_STYLE6_Y`다. 서로 다른 시기별 F1_STYLE6 refit의 원시 점수를 쓰는 후향 설계이므로 이 vintage 혼합을 학습량만의 효과로 설명하지 않는다. 같은 해 결과로 맞춘 `tau`는 그 해 selector 학습 입력에 쓰지 않는다. 저장된 calibrated `p_top3`는 기존 기준값으로 보존할 뿐 selector 입력은 raw score와 사전 지정 이력 피처뿐이다.

## 후보와 고정 피처

각 경주의 출전마 전원을 raw score 내림차순, 동점은 낮은 마번 순으로 정렬한다. 앞의 세 마리를 K=3 후보로 고정하며 baseline argmax도 같은 정렬의 1위다. 모든 경주는 후보 3두 이상을 가져야 한다. Selector utility 동점은 baseline raw score 내림차순, 다시 낮은 마번 순으로 푼다.

후보 utility의 고정 선형 basis는 아래 11열이다. 입력은 frozen F1_STYLE6 30열 계약에 이미 포함된 사전 경주 이력과 해당 경주의 OOS raw score에서만 만든다.

| 열 | 변환 |
|---|---|
| `score_rank` | 전체 경주 raw score 순위, 1이 가장 높음 |
| `score_z` | 경주 전체 raw score의 평균·모집단 표준편차(ddof=0) 기준 z값; 표준편차가 0이면 0 |
| `log_observed_starts` | `log1p(observed_starts)` |
| `log_days_since_start` | `log1p(days_since_start)`; 결측은 0으로 대체 |
| `days_since_start_missing` | `days_since_start` 결측 표시 |
| `log_same_starts` | `log1p(same_starts)` |
| `log_same_valid_times` | `log1p(same_valid_times)` |
| `log_days_since_same` | `log1p(days_since_same)`; 결측은 0으로 대체 |
| `days_since_same_missing` | `days_since_same` 결측 표시 |
| `mean5_rank_fraction` | frozen 피처의 편성 대비 최근 동일거리 평균기록 순위 값; 결측은 0으로 대체 |
| `mean5_rank_fraction_missing` | `mean5_rank_fraction` 결측 표시 |

각 평가 fold에서 표준화 평균과 모집단 표준편차는 그 fold의 **학습경주 K=3 후보행만** 사용해 계산한다. 후보행은 경주마다 정확히 3개여서 후보 입력 표준화에서 각 경주가 같은 수의 행을 준다. 학습 표준편차가 0이면 저장 scale을 1로 고정하고 표준화 결과는 0으로 둔다. 학습과 동일한 평균·scale로 평가 후보를 변환한다. 평가연도·전체 표본으로 전처리 통계를 추정하지 않는다.

`score_rank`/`score_z`는 raw score 기반이다. `p_top3`, favorite·odds, 말·경주 식별자, 달력연도, 착순·Top3 label, 경주 후 기록은 selector 피처에서 제외한다. `horse_id`, 이름, 마번은 키·동점 규칙·결과 저장에만 쓴다. 30개 원래 F1_STYLE6 말 평가 입력과 동결된 2024–2026 raw score·`p_top3`는 값 그대로 유지한다.

## Pairwise logistic 축 선택

각 학습경주 `r`에서 K=3 후보 `i`의 정답은 `y_i = 1[finish_position_i <= 3]`다. 후보 둘의 정답이 같은 쌍은 selector 학습에서 제외한다. 정답이 다른 쌍은 실제 Top3 후보를 양성, 그 외 후보를 음성으로 방향화하고, 표준화 피처 차 `d_{r,ij}=z_{r,i+}-z_{r,j-}`를 만든다. 각 혼합 경주에는 정확히 2개의 유효 쌍이 있다. 후보 3두가 모두 같은 정답인 경주는 순위 학습 신호가 없으므로 제외한다. Preflight에는 전체 source 경주·출전, 후보행, 학습용 혼합경주 `R_mix`, 유효 pair 수만 기록하고 hit rate나 다른 성과 통계는 계산하지 않는다.

계수 `β`와 utility `u_i=βᵀz_i`는 아래 고정 목적함수 하나로 학습한다.

`L(β) = (1/R_mix) Σ_r [ (1/|P_r|) Σ_(i+,j-)∈P_r log(1 + exp(−βᵀ d_{r,ij})) ] + 0.5 ||β||²`.

여기서 `R_mix`는 Top3 정답이 후보 안에서 섞인 학습경주 수다. L2 규제 계수는 `λ=1.0`으로 고정하고 절편은 넣지 않는다. 목적함수는 경주마다 같은 가중치를 둔다. 시작점은 영벡터, 해석적 gradient를 쓰는 SciPy L-BFGS-B 한 번으로 제한한다(`maxiter=1000`, `ftol=1e-12`, `gtol=1e-8`). 성공 상태, 유한 계수·목적값·gradient, gradient 최대절댓값 `<=1e-6`을 모두 만족해야 수용한다. 실패하면 재시도나 대체 최적화 없이 중단한다. λ·basis·후보 수·threshold·모형군을 탐색하지 않는다.

평가 때는 고정 utility가 최대인 K=3 후보 한 마리를 선택한다. 이 utility는 새 Top3 확률이 아니다. 별도 확률 보정·threshold는 없다. 전체 1,779경주 평가에는 Top3 후보가 하나도 없는 경주와 셋 모두 Top3인 경주도 그대로 포함한다.

## 고정 평가

비교 기준은 같은 경주의 기존 `argmax(score)` 1두다. 주 지표는 선택 말의 실제 Top3 비율이며 selector−baseline 차이를 보고한다. primary gate는 1,503경주에서 차이의 점추정치가 양수이고, 동일한 frozen 경주일 paired bootstrap 95% 구간의 하한도 0보다 큰 경우다. 같은 경주일에 발생한 모든 경주는 함께 재표집한다.

기존 [2026-10-11 frozen date schedule](../20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy)을 2,000회 그대로 쓴다. schedule은 269개 날짜의 정렬 순서를 source date inventory hash로 확인한다. 1,503경주 주 mask의 분모·적중 수를 매 bootstrap draw마다 다시 계산한다. 분모가 0인 draw는 undefined로 세고 유효 반복 수를 보고한다. 이는 학습된 세 selector를 고정한 날짜 표본의 불확실도이며 매 반복 재학습하는 학습 불확실도가 아니다.

전체 1,779경주 결과, 연도별·거리별 결과, 기존 축과 선택이 바뀐 경주 비율, baseline만 적중·selector만 적중·둘 다/둘 다 실패 수를 함께 보고한다. 경력별 탐색은 평가 전에 고정한 baseline axis의 `observed_starts` 구간 0, 1–4, 5+로 나눈다. K=5는 baseline raw-score 상위 5두 중 실제 Top3 말이 적어도 하나 있는 경주 비율만 후보 coverage 진단으로 보고하며 K=5 selector는 만들지 않는다. 이 하위집단 결과는 희소성과 다중 탐색 한계를 명시하고 primary gate를 대체하지 않는다. 배당 수익·승식 조합·구매 전략은 계산하지 않는다.

## 실행과 산출

1. `SOURCE_LOCK.json`과 이 계획의 해시를 잠근 뒤 `preflight.py`로 소스 해시, OOS key/year coverage, provider `refit_max` T−2, feature lineage cutoff, complete roster·label 계약, baseline score/P/y 대응 및 date bootstrap schedule만 검증한다. Preflight는 모델을 학습하거나 축·적중·평가 성과를 계산하지 않는다.
2. root가 계획·source lock·preflight 영수증·코드를 확인하고 별도 fit 승인을 한 뒤, 이 고정 계약으로 세 selector를 한 번씩 fit한다.
3. 평가연도별 `model_2024.json`·`model_2025.json`·`model_2026.json`에 11개 이름, 학습 평균·scale, 계수, 목적함수·gradient·convergence, 최대 학습라벨 날짜, 전체 source/candidate/informative pair 수, 소스 해시를 보존한다. 후보 ledger에는 각 K=3 후보에 대한 `(api_record_id, race_id, year, base_score, score_rank, utility)`를 저장하고 경주별 old/new 축·정답을 따로 남긴다. 최종 산출물은 이 폴더 안에만 둔다. 기존 연구, DB, 운영 등록부, 모델 입력·모델 파일은 수정하지 않는다.
