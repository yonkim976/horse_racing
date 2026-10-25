# F1_STYLE6 고정점수 기반 Top5 직접 학습 선택기

상태: **사전 계획과 fit-code 초안 완료, root의 첫 fit 승인 대기.** 이 단계에서는 새 선택 head를 학습하거나 평가 선택을 만들지 않았다. root가 이 문서, source audit, `fit_selector.py`, 그리고 root source receipt를 검토하고 그 해시를 묶은 `outputs/ROOT_FIT_APPROVAL.json`을 기록하기 전까지 fit script는 실행할 수 없다. 선택 코드와 결과 코드는 fit과 별도로 각각 root review/승인을 거친다.

## 질문과 구분

F1_STYLE6의 말 평가 모델·원점수는 그대로 두고, 그 원점수와 기존 사전 F1 입력만 받는 작은 별도 head가 경주당 정확히 5두를 고를 때 실제 Top3 3두 전원을 모두 포함하는 사건을 학습할 수 있는지 본다. 비교선은 같은 경주에서 원점수 내림차순·동점이면 마번 오름차순으로 고른 기존 raw-score Top5다. 새 head는 말별 Top3 확률이나 새로운 F1 점수를 만들지 않는다. 그 출력을 이용해 2024–2026 경주에 사후 적용한 결과는 반복 사용된 과거 개발 표본이며 독립 미래 검증이 아니다.

주 모집단은 2024-01-05~2026-09-19의 900/1000/1110/1200m 1,503경주다. 전체 1,779경주는 사전 고정한 보조 모집단이다. root source audit에서 제외 말 `3005648` 부재, 고정 raw-score/feature roster 연결, 출전키 및 T−2 source contracts를 확인했다. 다만 그 audit는 `finish_position`/evaluation outcome을 읽지 않았다. 학습승인 후 fit script가 2019..Y−1의 training labels만 열어 경주별 완전 `1..N` finish와 Top3 3두를 검증한다. 결과를 본 뒤 표본, 기간, 거리, 모델, feature, 규제 또는 선택 규칙을 바꾸지 않는다.

## 시간 분할과 입력

학습경주 연도 `c`의 말별 F1_STYLE6 원점수는 `F1_STYLE6_{c+1}/calibration_scores.parquet`에서만 가져온다. 2019–2022 점수는 저장된 historical OOS calibration 파일, 2023–2025 점수는 기존 style ablation의 calibration 파일이다. 평가 연도 `Y`의 head는 2019..`Y−1` 라벨만 학습에 사용한다:

| 평가연도 | 학습 라벨 연도 | 학습 경주 수 | 평가 경주 수 |
|---:|---|---:|---:|
| 2024 | 2019–2023 | 2,492 | 637 |
| 2025 | 2019–2024 | 3,129 | 654 |
| 2026 | 2019–2025 | 3,783 | 488 |

각 training score provider의 실제 metadata `refit_max`를 읽고 모든 점수행에 대해 `refit_max ≤ race_date − 2 days`를 검사한다. feature lineage도 고정한 T−2 cut-off를 따른다. 2019–2025 과거 라벨은 fit 당시 평가연도보다 앞선 정상 경주에서만 읽는다. 2024–2026 선택 단계는 baseline 파일에서 `api_record_id, race_id, race_date, year, distance_m, horse_id, horse_number, score, variant`만 허용하고 feature에서 고정 입력 열만 읽는다. `y`, `p_top3`, 로그손실, Brier, finish rank, odds, favorite는 선택 단계에 전달하지 않는다. 평가 raw score는 저장된 baseline과 frozen evaluation score 간 완전 일치 여부만 확인한다.

## 후보 에너지와 목적함수 하나

각 경주에서 고정 prior는 `z_i = (score_i − race_mean(score)) / race_sd(score)`이며 `ddof=0`, `sd=0`이면 모두 0이다. 이 변환은 경주 안의 원점수 순서를 보존하고, 저장된 원점수 자체를 바꾸지 않는다. 고정된 set energy는

`E_r(S; β) = Σ(i∈S) z_i + βᵀ φ_r(S)`, `|S|=5`.

`φ_r(S)`는 아래 **11개 F1_STYLE6 입력 잔차의 합**이다. 말별 입력은 해당 평가 fold의 학습 연도 runner rows에서만, 각 runner에 같은 weight를 주어 평균·모집단 표준편차를 산출해 표준화한다(상수열 scale=1). 결측 입력 열은 비결측 학습 runner들만으로 평균·표준편차를 적합하고, 그 학습 평균으로 대치(표준화 후 0)한다. 평가는 같은 fold의 scaler를 사용하며 후보 set 수에 따른 가중은 없다. 로그 변환하는 count는 `log1p`를 쓴다. `mean5_rank_fraction`의 결측 표식은 별도 열이다. style support count는 값 결측 여부와 지원량을 나타내며, 감사에서 count/NULL 불일치 0건을 확인했다. 다섯 말 입력을 평균하지 않고 합산해 prior와 같은 additive 단위를 사용한다.

| `φ` 열 | 말별 변환 |
|---|---|
| `log_observed_starts` | `log1p(observed_starts)` |
| `log_same_starts` | `log1p(same_starts)` |
| `log_same_valid_times` | `log1p(same_valid_times)` |
| `mean5_rank_fraction` | 원 입력, 결측은 학습 평균 대치 |
| `mean5_rank_fraction_missing` | NULL=1, 그 외 0 |
| `hist_s1f_relpos_mean5` | 원 입력, 정수 support 0..5 중 0인 NULL은 학습 평균 대치 |
| `log_hist_s1f_relpos_n` | `log1p(hist_s1f_relpos_n)` |
| `hist_s1f_to_c4_forward_mean5` | 원 입력, 정수 support 0..5 중 0인 NULL은 학습 평균 대치 |
| `log_hist_s1f_to_c4_pair_n` | `log1p(hist_s1f_to_c4_pair_n)` |
| `hist_c4_to_g1f_forward_mean5` | 원 입력, 정수 support 0..5 중 0인 NULL은 학습 평균 대치 |
| `log_hist_c4_to_g1f_pair_n` | `log1p(hist_c4_to_g1f_pair_n)` |

각 training race `r`에서 `G_r={S: actual Top3 ⊆ S}`를 positive set으로 두고 모든 `C(N,5)` 집합을 열거한다. 유일한 목적함수는

`J(β) = mean_r[ logsumexp_{all S} E_r(S;β) − logsumexp_{S∈G_r} E_r(S;β) ] + 0.5 ||β||²`.

이는 partial-label/Gibbs 학습 objective다. `Pgood`는 관측한 actual Top3에 조건부인 Gibbs **무작위** 유효 5-set 선택 질량이다. 실제 deterministic argmax의 all-three coverage 확률이나 보정된 확률로 보고하지 않는다. 학습목표와 deterministic argmax 간 일치 보장은 없다. 최종 비교 지표는 outcome 단계에서 새 head의 **결정적 argmax set**이 실제 Top3 전체를 포함한 비율이다. 계수 0에서는 fixed score prior가 기존 raw-score Top5와 정확히 같은 set을 고르는 negative control을 label-free로 확인한다.

목적함수는 generalized difference-of-logsumexp여서 비볼록일 수 있다. 이 구조적 한계를 숨기지 않는다. λ는 평균 loss 단위의 `1.0`으로 한 번 고정하며 탐색하지 않는다. float64, 영벡터 초기화, analytic gradient, SciPy L-BFGS-B 1회(`maxiter=1000`, `ftol=1e-12`, `gtol=1e-8`)만 사용한다. 수렴 실패·비유한 값·최종 analytic gradient max absolute value `>1e-6`이면 재시작/대체 optimizer 없이 중단한다. gradient는 race별 `E_all[φ]−E_good[φ]` 평균에 `β`를 더한다. 입력 중 `same_starts`/`same_valid_times` 및 세 style-support log count는 근접 공선성이 확인되어 계수 개별 해석은 하지 않는다. 정규화는 더 단순하고 사전 고정한 train-runner equal-weight (`ddof=0`) 기준으로 고정한다. candidate set 수에 비례한 scaler weight는 쓰지 않는다.

이 additive head는 실제 5-set feature interaction 모델이 아니다. 출력 에너지는 기존 말 원점수와 잔차 입력을 합친 set utility이며, 5개 runner별 utility 합으로 정확히 최적 5-set을 계산한다. 따라서 `F1_STYLE6` 말 평가를 새로 학습하거나 raw score를 덮어쓰지 않는다.

## 평가와 단계 잠금

1. `fit_selector.py`는 root가 계획·source audit·fit code를 검토하고 해시가 맞는 `ROOT_FIT_APPROVAL.json`을 만든 뒤에만 실행한다. 먼저 filter로 `2019 ≤ year < evaluation_year` 학습 라벨만 반환하고, 경주별 완전 `1..N` rank 및 정확히 3개 Top3인지 검사해 `LABEL_PREFLIGHT.json`을 write-once 저장한다. 검증이 통과된 뒤에만 3개 head를 fit하고 compact model 및 fit receipt를 쓴다. 그 후 root가 label preflight와 fit 영수증을 읽고 선택 코드 단계로 진행한다.
2. `select_sets.py`는 별도 root code approval과 fit receipt hash 확인 후 원점수 및 고정 입력 allowlist만 읽고 1,779개 deterministic argmax를 고른다. 경주마다 모든 `C(N,5)` 후보를 검사한다. 집합 utility가 `1e-12` 안에서 동률이면 raw-score Top5와 교집합이 큰 집합, 다음 마번 tuple 사전식 오름차순으로 고른다. zero-β control은 전 경주 baseline Top5와 일치해야 한다. 전체 후보 원장은 저장하지 않는다. race별 선택 1,779행과 hash receipt만 저장한다.
3. 선택 원장 hash를 root가 확인하고 outcome code에 별도 `ROOT_OUTCOME_APPROVAL.json`을 기록한 뒤 `report_outcomes.py`만 outcome labels를 연다. primary/full all-three hit, paired 차이, 고정 2,000회 date bootstrap 95% CI, 사전 지정 연도·거리 집계를 계산한다. Bootstrap schedule은 20261011의 269-date inventory, SHA-256 `e4aa73b866eac00b361d0354fdd62b7b2bd98915e003f250adc40a8df0a66b84`와 schedule SHA-256 `d141b0c3f9a463cbfc9d1f4c61228b58757c31aee4ec74b79f41c5baeadaccbd`를 확인하고, CI quantiles는 NumPy `method="linear"`로 고정한다. Race-level ledger 요약에는 raw/candidate all-three hit, baseline-only/candidate-only caught/lost, captured Top3 count 0/1/2/3, 연도·거리별 분모와 hit count를 기록한다. primary 성공 gate는 차이 `>0`이며 bootstrap lower bound도 `>0`일 때만 충족한다. 선택을 본 뒤 fit/재선택/규제 조정은 하지 않는다.

선택 집합 및 결과 JSON, 세 model JSON, fit/choice/outcome receipt만 이 연구의 새 하위 폴더에 저장한다. source parquet, 전체 후보 sets, features, models, database, registry는 복사·수정하지 않는다. 연구 완료 시 conclusions 폴더의 topic 파일과 README/SOURCES/register/manifests 갱신은 root가 맡는다.

## 성공·해석 경계

성공은 오직 사전 gate가 충족됐을 때 primary 결과에서 “이 반복 사용 역사표본에서 direct selector가 raw Top5보다 개선 신호를 보였다”로 기록한다. 실패하면 기각 또는 보류하고 추가 튜닝은 하지 않는다. 어느 결과도 새 holdout, 구매 성능, 인과 효과, 운영 모델 승격을 뜻하지 않는다. 이 정책은 existing model, registry, database, model inputs를 변경하지 않는다.
