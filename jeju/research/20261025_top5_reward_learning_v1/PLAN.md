# F1_STYLE6 고정점수 기반 Top5 보상 목적 학습

상태: **원천 경로·해시를 고정했고 계획과 fit-code를 root에 검토 요청할 단계다.** `outputs/ROOT_FIT_APPROVAL.json`에 계획·원천 감사·이 fit-code의 정확한 해시가 승인되기 전에는 어떠한 optimizer도 실행하지 않는다. 선택·결과 코드와 결과 열람은 이후 별도 검토를 거친다.

## 연구 질문과 통제 비교

현재 `F1_STYLE6`의 원점수 및 말 평가기는 고정한다. 질문은 그 원점수와 기존의 동일한 11개 runner 입력만 쓰는 작은 additive selector를 학습해, 경주당 5두를 결정적으로 고를 때 actual Top3 세 두를 전부 포함하는 비율을 개선하는지다. 이 연구가 학습하는 것은 F1_STYLE6 자체나 말별 입상확률이 아니라 5두 선택을 위한 별도 head다.

주 평가 모집단은 2024-01-05~2026-09-19의 900/1000/1110/1200m 1,503경주, 전체 1,779경주는 보조 모집단이다. 비교 arms는 같은 roster와 원천에서 재생한 기존 raw-score Top5, 직전 `20261025_top5_direct_learning_v1`의 partial-event NLL head, 이번 reward-objective head다. 각 arm은 경주별 정확히 5두를 고른다. 기존 결과는 그대로 참조하고 이 연구가 이전 폴더를 수정하지 않는다.

개발기간에 반복 사용된 역사 표본이다. 미래 holdout, 인과 효과, 구매 성능, 확률 보정 또는 운영 승격을 주장하지 않는다. 사용자 지정 기준 모델·registry·DB·기존 연구 파일은 변경하지 않는다.

## 고정 입력과 시간 분할

`F1_STYLE6` 원점수, 11개 입력, 전처리, feature 합산, score prior 및 expanding OOF windows는 직전 direct-learning study와 동일하게 고정한다. 입력 이름:

`log_observed_starts`, `log_same_starts`, `log_same_valid_times`, `mean5_rank_fraction`, `mean5_rank_fraction_missing`, `hist_s1f_relpos_mean5`, `log_hist_s1f_relpos_n`, `hist_s1f_to_c4_forward_mean5`, `log_hist_s1f_to_c4_pair_n`, `hist_c4_to_g1f_forward_mean5`, `log_hist_c4_to_g1f_pair_n`.

각 fold의 평균·모집단 표준편차(`ddof=0`)는 training runners에 동일 가중으로만 적합한다. 결측은 training 평균 대치(표준화 후 0), 상수 scale은 1, count는 `log1p`, style support는 기존 paired-NULL 검증, `mean5_rank_fraction`은 별도 결측 표식을 쓴다. 경주마다 score prior는 `z_i=(score_i−race_mean)/race_sd`, `ddof=0`, `sd=0`이면 전 runner 0이다. set feature는 다섯 runner의 standardized 11-vector 합이며 평균이 아니다.

라벨 연도 `c`의 training score는 고정 OOF provider `F1_STYLE6_{c+1}/calibration_scores.parquet`에서 읽고 metadata `refit_max ≤ race_date−2 days`를 검사한다. 평가연도별 label window는 `2019 ≤ year < Y`이고 2,492 / 3,129 / 3,783 training races다(Y=2024/2025/2026). 매 training race는 완전 `1..N` 순위와 정확히 세 개 Top3를 가져야 한다. 이 검사는 학습 전 label preflight 영수증에 기록한다. 평가연도 label은 fit에서 조회하지 않는다.

## 보상 정책과 목적함수 하나

모든 `C(N,5)` 후보집합 `S`를 일시 메모리에서 열거한다. 고정 에너지와 set 선택정책은

`E_r(S;β)=Σ(i∈S) z_i + βᵀ Σ(i∈S) x_i`, `πβ(S|r)=softmax_S(E_r(S;β))`.

관측한 actual Top3를 모두 담는 집합은 `good(S)=1{Σ(i∈S)1[i∈actualTop3]=3}`다. 이 조건은 5두 전체에 세 Top3가 들어가는 사건이며, 다섯 두가 모두 Top3라는 뜻이 아니다. 보상은 사전에 고정한 `R(S)=+1` if good, otherwise `−1`이다. 따라서 `Pgood_r=ΣS good(S)πβ(S|r)`, `E[R|r]=2Pgood_r−1`이며 fit 목적 하나는

`J(β)=mean_r[1−2Pgood_r] + (λ/2)||β||²`, `λ=1`.

analytic gradient는 `mean_r[2Pgood_r(E_all[x]−E_good[x])] + λβ`다. 모든 가능한 집합의 label을 사용해 exact expected reward와 policy gradient를 계산한다. sampling, PPO 또는 LLM fine-tuning은 사용하지 않는다. `π`는 set 선택분포이고 actual Top3를 조건부로 정의한 Gibbs 질량이므로 보정된 입상확률이 아니다. 최적화 목표와 추후 deterministic `argmax E`의 actual coverage 사이에는 surrogate gap이 있다. 결과물·보고서에서 이 둘을 분리한다.

float64, 영벡터 초기화, L-BFGS-B 1회(`maxiter=1000`, `ftol=1e-12`, `gtol=1e-8`)만 허용한다. restart·온도·추가 튜닝 없이 수렴 여부, finite 계수와 최종 최대 절대 gradient `≤1e-6`를 필수 검사한다. 실패하면 해당 사전 계획의 결과로 중단하고 재시작하지 않는다. 계수 0의 label-free 선택은 기존 raw-score Top5와 동일해야 한다.

## 실행 게이트와 결과 범위

1. Root는 `SOURCE_AUDIT.md`, 본 계획, `fit_selector.py`와 source receipt를 검토하고 이 세 파일 해시를 묶은 `outputs/ROOT_FIT_APPROVAL.json`을 승인한다. 승인 후 fit은 training labels만 preflight·학습에 사용해 세 model JSON, label preflight, fit receipt를 write-once 저장한다. 결과 지표는 계산하지 않는다.
2. 그 fit receipt를 검토한 후 root가 selection code를 별도로 승인한다. 선택 코드는 score/roster와 11개 fixed inputs만 허용하고, outcome/finish labels 없이 모든 1,779 race를 결정적으로 선택한다. 동률은 `1e-12` 이내에서 raw-score Top5와의 overlap 최대, 다음 horse-number tuple 오름차순이다. 전 경주 후보 matrix를 디스크에 저장하지 않는다.
3. Choice receipt와 source/old-choice receipts를 확인한 후 root가 outcome reporter를 별도 승인한다. 이 단계만 evaluation labels를 열고 3 arms를 동일한 17,412 runners / 1,779 races / 269 dates에서 비교한다. primary와 full-set paired Δ 및 기존 고정 2,000 date-bootstrap schedule의 95% CI, 연도·거리, changed sets, caught/lost, captured Top3 수를 요약한다. 성공 기준은 primary 두 쌍(`reward−raw`, `reward−old`) 모두 Δ>0이고 양쪽 95% lower bound도 >0일 때만이다. 두 쌍을 함께 보고하고 한 쪽만 통과하면 양쪽 우위 주장을 하지 않는다.

저장물은 이 폴더의 계획·코드, 3개 작은 model, 1,779행 choice ledger, outcome summary, hash receipts만이다. 원천 parquet, full features, OOF file, DB, 전체 후보 집합, 전체 matrix, 기존 모델/registry 복사는 금지한다. 새 산출물은 이상적으로 3MB 미만, 절대 300MB 미만으로 유지한다. conclusions 문서와 전역 manifest 갱신은 root가 맡는다.
