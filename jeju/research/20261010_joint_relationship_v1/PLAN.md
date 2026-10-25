# F1_STYLE6 공동 관계 보정 사전 계획 초안

상태: 감사 에이전트와 root 검토용 초안. 결과 학습·평가 전이며, 감사와 root의 설계 승인 및 별도 학습 승인이 필요하다. 기존 `F1_STYLE6` 말 점수·말별 평가·저장 최대 6조합·운영 산출물은 변경하지 않는다. 새 연구는 같은 전체 출전집합의 무순서 정확 Top3 집합 분포에 저차원 pair 관계항을 더해 최대 6조합의 변화를 평가한다.

## 질문과 해석 범위

고정 질문은 “저장된 `F1_STYLE6` 말 평가를 그대로 두고, 출전말 쌍의 사전 관측 관계를 학습해 동일한 경주에서 전체 `C(N,3)` 후보 중 최대 6조합을 선택할 때 기존 조합보다 적중을 늘릴 수 있는가?”이다. 기존 평가 기간은 2024-01-05~2026-09-19, 1,779경주·17,412출전·269경주일이며 2026년은 부분 연도다. 이 경주·라벨은 앞선 연구에서 반복 사용됐다. 결과는 후향 개발 자료이고 독립 미래검증이나 운영 승격으로 부르지 않는다.

새 모델은 각 평가 연도의 기존 `F1_STYLE6_Y` 저장 원시 점수와 입력의 6개 과거 스타일 변수만 사용한다. horse ID와 pair ID는 학습 피처에서 금지한다. `F1_STYLE6`의 원래 말 점수, 말별 예측 및 기존 보고 지표는 고정한다. 관계 분포에서 합산해 얻는 새 Top3 주변확률은 별도 파생값으로 표시하며 원래 말별 예측을 덮지 않는다. 관계항은 착순 순서를 추정하지 않고, 무순서 정확 Top3 집합 확률만 만든다.

## 저장 자산과 OOS 점수 경로

`20261010_style_history_ablation_v1/run.py`의 `fit_one_year`는 평가연도 `Y`별로 2017~`Y-3` 학습, `Y-2` early-stop 및 refit, `Y-1` calibration, `Y` evaluation 순서를 사용한다. 동일 refit 모델이 `Y-1`의 `calibration_scores.parquet`와 `Y`의 `evaluation_scores.parquet`에 `raw_score=True`로 점수를 저장했다. 따라서 `Y-1` calibration 점수는 그 말과 경주의 라벨을 학습에 사용하지 않은 OOS 원시 점수다. 기존 F1 말 모델을 다시 fit하거나 과거 OOF 점수를 새로 생성할 필요가 없다.

`calibration_scores.parquet`는 `api_record_id:int64, score:float64` 두 열이다. 행 키로 `20261010_style_history_ablation_v1/outputs/features.parquet`에 연결한다. 피처 테이블의 `api_record_id`, `race_id`, `race_date`, `year`, `horse_id`, `horse_number`, `field_n`, `finish_position` 및 6개 스타일 입력은 경주 roster·라벨·관계 피처 작성에 사용한다. 라벨은 같은 완전 편성 정상 완주 코호트의 `finish_position <= 3` 말 ID 집합이다. 한 경주에서 정답이 정확히 3두가 아니거나 점수/피처 join, roster 또는 키 일치가 깨지면 fail closed 한다.

평가연도 `Y`에는 같은 저장 F1_STYLE6 모형이 만든 직전 연도 `Y−1`의 calibration 점수와 `Y`의 evaluation 점수를 사용한다. 모델 입력·T−2 이력은 저장된 style-history 입력 계약을 그대로 따른다. 저장된 `tau`는 calibration 연도 전체 라벨로 맞춰졌으므로 H1 학습 점수의 확률화·offset으로 쓰지 않는다. H1에는 raw score energy를 사용하고 최종 온도는 H2에서 따로 맞춘다.

## 시간 분할과 가용성 경계

각 평가연도별 calibration 연도를 1월 1일~6월 30일 H1 관계학습, 7월 1일~12월 31일 H2 확률보정으로 나눈다. 한 경주의 모든 출전 행과 그 날짜의 모든 경주는 함께 둔다. 사전 로컬 자산 점검에서 날짜 절반별 대략 경주 수는 calibration 2023년 321/336, 2024년 326/311, 2025년 329/325(H1/H2)다. 이는 T−2 purge 전 잠정 수이며, 사전검증에서 실제 경계 날짜와 purge 후 수를 기록·잠근다. H1 첫 실제 경주일 `D_H1`에 대해서도 저장 baseline의 `refit_max <= D_H1 - 2 calendar days`를 assert 한다.

T−2 조건은 H1/H2의 단순 날짜 분리만으로 충족됐다고 보지 않는다. 각 연도 H2에서 첫 실제 경주일을 `D_H2`라 하고, H1에서 `race_date <= D_H2 - 2 calendar days`인 날짜만 H1 fit에 둔다. 그보다 늦은 H1 날짜의 경주 전체를 사전 규칙으로 purge하고 과거 날짜로 대체하지 않는다. H2 마지막 실제 라벨 날짜도 다음 평가연도 첫 실제 경주일에서 2일 이상 앞서는지 검증한다. 평가연도 전체 예측은 이 조건을 충족하는지 별도 assert 한다. 실제 미래 입력 피처도 기존 원천 계약의 T−2 cutoff와 공개시각 한계를 그대로 표시한다.

각 평가 fold에서 H1 label만 계수 학습에, H2 label만 양쪽 방식의 최종 온도 보정에 사용한다. 정확한 assert는 `max(H1 label date) <= min(H2 race date)-2 days`, `saved model refit_max <= min(H1 race date)-2 days`, `max(H2 label date) <= min(evaluation race date)-2 days`다. H2 label은 다음 평가연도에만 쓰이며 해당 평가연도 예측 점수나 feature 변환을 고르는 데 재사용하지 않는다. 전체 H1/H2/evaluation key·날짜·점수 SHA는 사전 lock 후 fit 전후 대조한다.

## 최소 단일 관계 모형

경주 `r`의 전체 출전마 수를 `N_r`, 저장된 F1_STYLE6 원시점수를 `s_i`, 무순서 3두 집합을 `T`라 둔다. 기준 에너지는 기존 evaluator와 같은 정렬·합산 순서를 적용한 `E0_r(T) = sum_{i in T}(s_i)`다. 입력은 `score`와 다음 6열로 한정한다.

- `hist_s1f_relpos_mean5`, `hist_s1f_relpos_n`
- `hist_s1f_to_c4_forward_mean5`, `hist_s1f_to_c4_pair_n`
- `hist_c4_to_g1f_forward_mean5`, `hist_c4_to_g1f_pair_n`

각 평가 fold의 H1에서만 runner 변수별 평균·표준편차를 산출한다. 변수별로 경주당 총 가중치가 같도록 runner 행 가중치 `1/N_r`를 쓴다. 표준편차 0인 열은 0으로 둔다. 세 `mean5` 열의 유효값은 대응 `n>0`이고 값이 finite일 때만 인정한다. `n=0`이면 평균 NULL인지, `n`이 0~5 정수인지 검사한다. 불일치는 보간하지 않고 fail closed 한다. `n` 열은 관측 지원량 피처로 그대로 포함한다.

정규화된 값 `u_i`로 각 비순서 pair `{i,j}`의 고정 11차원 기저를 만든다: (1) raw score의 대칭 곱 `u_i,score * u_j,score`, (2) score와 6개 style 입력 각각의 절대차 `|u_i,k-u_j,k|`, (3) 세 style mean 각각에서 둘 중 하나라도 유효하지 않으면 1인 별도 결측 지시자. 결측 mean의 절대차는 0으로 두며 결측 지시자로 상태를 전달한다. pair 순서를 바꿔도 기저는 같고 말·쌍 ID나 마번은 기저에 넣지 않는다. runner 열별 표준화 평균·표준편차는 H1에서만 valid runner 가중치 `w_ri=1/N_r`로 산출한다. `mu_k=sum_{valid} w_ri*x_ri / sum_{valid} w_ri`, `sd_k=sqrt(sum_{valid}w_ri*(x_ri-mu_k)^2 / sum_{valid} w_ri)`인 weighted population SD다. 세 mean열은 대응 `n>0`이고 finite인 값만 분모에 넣고, count와 score는 모든 유효 finite값을 넣는다. 따라서 mean열의 race별 총 가중치는 유효 runner 비율에 비례하며, 이를 strict race-equal 평균이라 부르지 않는다. 분모가 0이거나 `sd_k <= 1e-12`인 열은 정규화값 0으로 고정하고 지원/퇴화 이유를 남긴다.

각 경주·각 기저 열에서 모든 roster pair 값 `phi_ij`를 가장 가까운 unary pair 효과 `a_i+a_j`에 최소제곱 투영해 관계 잔차 `R_ij = phi_ij - a_i - a_j`를 만든다. 완전 pair graph에서 `d_i=sum_{j!=i} phi_ij`, `S=sum_{i<j} phi_ij`이면 `a_i=(d_i-S/(N_r-1))/(N_r-2)`를 쓴다. 이 projection은 `sum_{j!=i}R_ij=0`을 만족한다. 전체 삼두 후보의 incidence matrix를 `A`(`A[T,i]=1` iff horse `i` is in triple `T`)라 하고 `G[T]=sum_{pairs in T} R_ij`라 하면 이 zero row-sum 때문에 `A.T @ G = 0`: horse `i`가 든 삼두에서 i와 붙은 pair 잔차의 합은 `(N_r-2)*sum_{j!=i}R_ij=0`이고, 나머지 삼두 pair들의 합도 전체 pair 잔차 합과 i의 row sum이 모두 0이므로 0이다. preflight에서 수치 허용오차 안의 `A.T @ G`를 확인한다. `N_r>=5`를 support 조건으로 고정한다. `C(N_r,3)>=6` 및 unary projection residual rank가 양수인지 preflight에서 확인하며 미지원 경주가 있으면 별도 제외하지 않고 root에 보고해 진행을 멈춘다.

각 평가 fold의 H1 잔차에서 pair 수가 아니라 race를 동일 가중하는 열별 RMS `rho_k=sqrt(mean_r(mean_{i<j}(R_{rij,k}^2)))`를 산출하고 이후 H2·평가에 고정 적용한다. `rho_k <= 1e-12`인 열은 정확히 0으로 고정하고 fit 변수에서 제거한다. 정규화 후 한 경주·열에서 `max(abs(R_ij)) <= 1e-12`이면 그 최대 절대값을 clean 전 값으로 기록하고 해당 경주·열을 정확히 0으로 정리한다. 다른 잔차는 반올림하지 않는다. projection 구현 preflight는 합성 unary-only `phi_ij=a_i+a_j+c` 입력에서 잔차가 0으로 정리되는지, candidate energies/probabilities가 baseline과 같은지 확인한다.

고정 모형은 하나뿐이다. `g_beta(i,j)=beta' R_ij`, `G_beta(T)=sum_{i<j in T} g_beta(i,j)`, `E_beta(T)=E0_r(T)+G_beta(T)`이며 `Q_beta,tau(T)=softmax_T(E_beta(T)/tau)`를 해당 경주의 **모든** `C(N_r,3)` 조합에서 정규화한다. H1에서 경주 균등 평균 exact-set negative log likelihood를 최소화한다.

`L(beta) = mean_r[ logsumexp_{T in C(N_r,3)} E_beta(T) - E_beta(T*_r) ] + (lambda/2) * ||beta||_2^2`

여기서 `lambda=1.0`을 고정하고 절편을 두지 않는다. 목적함수는 관계항 앞의 온도를 1로 고정한 raw score offset을 사용한다. 계수는 영벡터에서 시작하며 SciPy `minimize(method="L-BFGS-B")`, analytic gradient, `maxiter=500`, `ftol=1e-12`, `gtol=1e-8`로 한 번 fit한다. fold별 계수 3개만 저장하며 초기값·lambda·기저·optimizer를 결과에 따라 다시 고르지 않는다. 실패한 수렴은 재시도·대체 모델 없이 오류로 남긴다.

## 매칭 대조군과 확률 보정

매칭 baseline은 `beta=0`으로 고정한 same-raw-score 조건부 집합 모형이다. H2에서 baseline `E0`와 후보 `E_beta` 각각의 양의 온도만 race-equal exact-set NLL 최소화로 맞춘다. 양쪽 bounds는 기존 F1 계약의 `[0.35, 4.0]`, optimizer는 SciPy `minimize_scalar(method="bounded", xatol=1e-12)`로 고정한다. 보정에 사용한 H2 날짜·라벨 집합은 두 방식에서 동일하다. `beta=0`은 모든 에너지가 저장 baseline과 정확히 같아지는 영 관계 negative control이며, baseline saved six의 10,674행에 대해 `(race_id, selection_rank, numbers)`가 완전히 동일함을 assert하고 결과에 행 수와 비교 행 수를 기록한다. 투영 자체에 대한 합성 unary-only negative control은 위에 별도 정의했다.

기존 `F1_STYLE6` 저장 tau·확률·최대6조합은 별도 고정 참조로 보존한다. 양의 온도는 기존 additive model의 조합 순위를 바꾸지 않으므로 매칭 baseline 6조합은 저장 baseline 6조합과 같아야 한다. 온도와 probability 비교의 공정한 주 대조는 H2에서 같은 자료로 보정한 매칭 baseline이다. 원래 full-calibration-year tau를 새 H1 자료나 matched calibration에 섞지 않는다.

## 모집단·평가지표·사전 gate

평가 roster·경주·정답은 기존 저장 F1_STYLE6 평가 코호트를 그대로 쓴다. 각 평가 경주의 완전 roster에서 `C(N_r,3)`을 모두 열거하고 새 분포 전체를 정규화한 뒤, 같은 tie 규칙으로 상위 6개만 선택한다. baseline와 candidate 모두 각 경주 최대 6장, 동일한 1,779경주다. horse 행은 마번 오름차순, 조합은 기존 조합 열거 순서, baseline triple energy는 세 원시 점수를 정렬한 뒤 기존 `np.sum(axis=1)` 순서를 지킨다. 후보는 baseline energy에 세 pair residual 합을 더하고 stable descending 정렬을 쓴다. 저장 baseline 조합 선택 순서의 parity를 먼저 확인한다.

주 성능 gate는 candidate와 H2 matched baseline 사이 전체 1,779경주의 6조합 적중 차이(`candidate - baseline`)다. 날짜를 cluster 단위로 paired bootstrap 2,000회, seed `20261008`을 metric마다 reset해 95% pointwise interval을 산출한다. **연구 신호**로 분류하려면 전체 6-hit 차이의 점추정이 양수이고 CI 하한이 0보다 커야 하며, 동시에 exact unordered Top3 joint true-set NLL 차이의 CI 상한이 0 이하(허용 악화 margin 0)여야 한다. 두 조건 중 하나라도 못 넘으면 통과 신호로 부르지 않는다. gate는 연구 후보 판정이며 독립 미래검증·인과효과·운영 승격이 아니다.

보조표로 joint Brier, 선택 6장 예측 mass와 reliability, 관계 분포에서 계산한 marginal loss, 2024·2025·2026별 결과 및 기존 F1_STYLE6 저장 확률 대비 차이를 모두 표시한다. 보조 지표·부분집단·단일 연도는 사전 gate를 대체하지 않고, 2026은 9월 19일까지의 부분연도로 표시한다. 기존 F1_STYLE6 runner 성능표는 그대로 보존하고, 후보 joint의 marginal은 별도 산출로 구분한다.

## 금지 범위와 승인 순서

새 자료 수집, DB·운영모형·등록부·기존 파일·결론문서 변경, 더러브렛 계수 이식, horse ID 또는 과거 반복 pair ID 암기, 다중 후보·여러 lambda·입력 조합 탐색, 결과를 보고한 뒤의 날짜·feature·gate 변경은 범위 밖이다. 새 문서·코드·산출물은 이 폴더에만 둔다. 중간 파일은 삭제하지 않는다.

다음 순서는 (1) 감사 에이전트와 root가 수식·날짜 경계·purge·결측·tie·gate를 검토해 계약을 고정, (2) 코드 작성 후 source lock / 입력·roster·T−2 / 대칭성 / projection·degeneracy / exact zero-control parity를 outcome 없이 preflight, (3) preflight 검토와 별도 root 학습 승인, (4) 그 뒤에만 H1 관계계수 학습·H2 온도 보정, 먼저 계수·정규화·tau·fit receipt를 immutable new outputs에 기록, (5) 해당 고정 모형 파일을 읽는 별도 report 실행 및 결과 검증이다. report 실패 시 모델을 다시 맞추지 않고 저장 계수·tau로 결과만 재생성하는 no-fit finalizer를 제공한다. 현재 단계에서는 학습과 outcome 평가를 실행하지 않는다.
