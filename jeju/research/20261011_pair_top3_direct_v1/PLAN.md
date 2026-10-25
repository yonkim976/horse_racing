# F1_STYLE6 직접 Top3 동시입상 pair 모델 사전 계획

상태: 설계 검토용 초안. 새 모델 fit과 새 평가 지표 계산은 아직 하지 않았다. 먼저 root가 이 계획과 입력 계약을 승인해야 한다. 승인 뒤에는 입력·분할 preflight만 실행하고, preflight 검토와 별도 root fit 승인이 끝난 뒤에만 세 H1 모델을 fit하고 평가한다. 저장된 `F1_STYLE6` 점수·말별 확률·평가와 기존 공동분포 산출물은 읽기 전용이다.

## 질문과 범위

질문은 “저장된 `F1_STYLE6` 말별 점수와 기존 6개 스타일 입력을 고정해 두고, 각 경주에서 Top3에 함께 든 두 마리 pair를 직접 학습하면 기존 상위 두 마리와 기존 공동확률 기반 pair보다 pair 적중을 높일 수 있는가?”다. 경주마다 모든 비순서 pair를 점수화하고 예측 확률이 가장 높은 pair 하나를 고른다.

평가는 `20261010_style_history_ablation_v1`의 완전 편성 정상 완주 코호트, 2024-01-05~2026-09-19의 1,779경주·17,412출전·269경주일을 사용한다. 2026년은 9월 19일까지의 부분연도다. 이 결과들은 앞선 연구에서 반복 사용된 과거 라벨이므로 후향 개발 분석이다. 독립 미래검증, 인과효과, 수익성 또는 운영 승격으로 해석하지 않는다.

이 모델은 `P(두 마리 모두 실제 Top3)`의 pair별 Bernoulli 예측이다. 정확한 순위, 복승, 나머지 세 번째 말을 포함한 완성 조합을 예측하지 않는다. pair 확률은 일관된 공동 Top3 분포가 아니므로 한 경주 안에서 모든 pair 확률의 합이 정확히 3이 되도록 강제하지 않는다.

## 입력과 고정 시간 분할

평가연도 `Y`마다 저장된 `F1_STYLE6_Y`의 `calibration_scores.parquet`를 직전 연도 원시 OOS 점수로 쓴다. 파일 경로의 연도는 평가 fold를 나타내며, 예를 들어 `F1_STYLE6_2024/calibration_scores.parquet`의 경주 라벨 연도는 2023이다. 이 원시 점수는 해당 경주 라벨을 학습에 넣지 않은 같은 refit 모델이 만들었다. `F1_STYLE6_Y/evaluation_scores.parquet`는 평가연도 Y의 원시 OOS 점수다. 원래 `tau`로 계산한 확률은 H1 학습 입력으로 쓰지 않는다.

직전 연도 원시 점수와 여섯 스타일 열을 경주일 단위로 나눠 1~6월 H1에서 계수를 한 번 학습하고 7~12월 H2에서 최종 pair 확률만 보정한다. H1에서 H2로 넘어갈 때 첫 H2 실제 경주일 `D_H2`를 기준으로 `race_date <= D_H2 - 2 calendar days`인 H1 경주일만 유지한다. 이 경계 뒤 H1 경주일은 전부 사전 규칙으로 purge하며 과거 날짜로 대체하지 않는다. H2 라벨의 마지막 실제 경주일은 평가연도의 첫 실제 경주일보다 최소 2일 앞서야 한다. 기존 C preflight의 split inventory는 (평가 2024) H1/H2 312/336경주, (2025) 326/311, (2026) 329/325이며 신규 preflight에서 이 race count와 날짜 경계를 다시 확인한다.

각 fold에서 반드시 `saved F1_STYLE6 refit_max <= first H1 race_date - 2 days`, `max(H1 race_date) <= min(H2 race_date)-2 days`, `max(H2 race_date) <= min(evaluation race_date)-2 days`를 확인한다. 모든 경주일의 전체 경주는 같은 구간에 둔다. 저장된 full-year `tau`는 H1이나 새 pair 모델의 대조군 보정에 재사용하지 않는다. 공개 시각이 역사적으로 완전히 복구되지 않은 한계는 기존 입력 계약을 따른다.

## pair 라벨과 입력 무결성

말 입력은 저장 원시 `score`와 기존 여섯 열만이다: `hist_s1f_relpos_mean5`, `hist_s1f_relpos_n`, `hist_s1f_to_c4_forward_mean5`, `hist_s1f_to_c4_pair_n`, `hist_c4_to_g1f_forward_mean5`, `hist_c4_to_g1f_pair_n`. 피처는 `api_record_id`로 연결하고 경주 키는 `race_id`, 출전 키는 `(race_id, horse_number)`로 확인한다. `horse_id`, 마번, 경주 ID는 학습 입력에 넣지 않는다. 마번은 완전한 동점일 때만 선택 순서를 고정한다.

한 경주의 실제 Top3 말은 저장 완주 코호트의 `finish_position <= 3`으로 정한다. pair 라벨은 `y_ij = 1[(finish_i <= 3) and (finish_j <= 3)]`이다. 모든 H1/H2/evaluation 경주는 field size `N_r >= 4`이고 Top3 말이 정확히 3두여야 하며 따라서 양성 pair도 정확히 3개여야 한다. 원시 score·피처·라벨 join, 중복, roster, 결측 의미 또는 이 개수가 맞지 않으면 임의 보정 없이 fail closed 한다.

세 `mean5` 입력은 대응 `n`이 1~5의 정수이고 값이 finite일 때만 유효하다. `n=0`이면 mean은 NULL이어야 하고, `n>0`이면 mean은 finite여야 한다. 세 `n` 열은 0~5 정수여야 하며 raw score는 모든 출전에서 finite여야 한다. 반대 결측 패턴은 fail closed 한다. 결측 평균을 0이라는 실제 관측으로 취급하지 않는다.

## 대칭 pair 표현과 고정 모형

말 `i`의 일곱 입력을 `x_i`라 한다. H1에서만 열별 평균·표준편차를 추정한다. raw score와 count 열은 경주당 총 가중치가 같은 `1/N_r` runner 가중치로 표준화하고, mean 열은 해당 값이 유효한 runner만 사용해 같은 방식으로 표준화한다. 표준편차가 `<=1e-12`인 열은 0으로 둔다. 결측 mean은 H1 표준화 평균으로 대체해 표준화 값 0으로 두고, 별도 결측 표시를 보존한다.

비순서 pair `{i,j}`의 고정 basis는 각 일곱 열 `k`에 대해 `z_ik + z_jk`와 `|z_ik - z_jk|` 두 항, 그리고 각 세 mean 열 `m`에 대해 `missing_im + missing_jm`와 `missing_im * missing_jm` 두 항이다. 총 20개다. 결측 패턴 두 항은 각각 `(0,0)=둘 다 관측`, `(1,0)=정확히 하나만 결측`, `(2,1)=둘 다 결측`으로 서로 구별한다. 따라서 말을 서로 바꿔도 같은 basis가 나오고, 개별 말의 수준과 pair 간 유사·차이를 함께 표현한다. 모든 basis 열은 H1에서 pair 가중치 `1 / C(N_r,2)`로 평균·표준편차를 한 번 더 맞춘다. 퇴화 열은 0으로 고정하며 그 사유와 지원량을 저장한다.

각 경주에서 먼저 현재 저장 raw score만으로 기준 무순서 Top3 분포를 고정 계산한다. 모든 `T in C(N_r,3)`에 대해 `q0_r(T)=softmax_T(fsum_{h in T} score_h)`를 둔다. triple은 오름차순 numeric horse number로 열거하고, 각 triple energy는 Python `math.fsum`으로 계산한다. softmax 분모와 pair 주변확률도 동일한 canonical triple 순서의 항을 `math.fsum`으로 합산한다. 이 합산 규칙은 exact-score tie에서 순서에 따른 부동소수점 누적 차이가 선택 pair를 바꾸지 않도록 고정한다. 여기서는 temperature `tau=1`을 쓰며 저장된 full-year `tau`는 사용하지 않는다. pair 기준확률은 `p0_r,ij=fsum_{T: i,j in T} q0_r(T)`다. 이는 기존 개별 score의 additive exact-Top3 기준분포가 주는 pair 주변확률이다. 이 분포의 maximum pair는 raw-score 상위2와 이론적으로 일치한다. preflight는 모든 평가 경주에서 canonical `p0` maximum pair가 raw-score 상위2 pair와 일치하는지 확인하며 불일치 시 중단한다.

표준화 basis를 `v_ij`라 할 때 pair 후보는 기준확률에 대한 직접 Bernoulli correction만 학습한다.

`p_ij = sigmoid(logit(p0_r,ij) + beta' v_ij)`.

학습 목표는 H1 경주마다 같은 총 가중치를 주는 Bernoulli log loss에 고정 ridge를 더한 값이다.

`L(beta) = (1/R) * sum_r[(1/M_r) * sum_{i<j} BCE(y_ij, p_ij)] + (1/2) * ||beta||_2^2`, `M_r=C(N_r,2)`.

`lambda=1.0`을 고정한다. 절편은 추가하지 않는다. 따라서 `beta=0`은 정확히 `p0`인 영효과 negative control이고, 각 경주에서 p0 maximum pair 및 raw-score 상위2와 같은 pair를 골라야 한다. zero 계수 재현성과 선택 parity는 preflight에서 모든 평가 경주에 대해 검증한다. 동점은 수치 허용오차 없이 정확한 float equality로만 판정하며 오름차순 `(horse_number_i, horse_number_j)`로 푼다. 0에서 시작해 analytic gradient의 SciPy L-BFGS-B, `maxiter=500`, `ftol=1e-12`, `gtol=1e-8`로 fold마다 한 번만 최적화한다. 세 평가 fold 밖의 학습, 여러 lambda·피처 조합·threshold 탐색, 평가 결과를 본 뒤의 재학습은 금지한다. fit은 `success=True`, 유한한 계수·목적함수·gradient, 경계 투영 gradient infinity norm `<=1e-6`을 모두 만족해야 수용한다. H1에는 box bound가 없으므로 gradient 자체의 infinity norm을 검사한다. 실패하면 재시도 없이 중단하고 기록한다.

## H2 보정과 pair 선택

H1 모델의 H2 원시 logit `eta_ij`에 양의 기울기 Platt 보정 `sigmoid(A_candidate+B_candidate*eta_ij)`, `B_candidate>0`을 한 번 맞춘다. 기준 `logit(p0)`에도 같은 H2 labels, objective, optimizer, bounds로 양의 기울기 Platt 하나를 별도 fit한다. 초기값은 `(A,B)=(0,1)`이고 두 fit에서 같은 analytic gradient, race-equal pair BCE, bounds를 쓴다. 이 둘은 서로 다른 선택 정책의 확률 품질을 맞춰 비교하는 calibration pair다. `beta=0`에서는 두 입력 logit이 같으므로 결정적 fit 결과와 확률이 같아야 함을 assert한다. 양의 기울기라 각 보정은 선택 순위를 바꾸지 않는다. 수치 bounds와 optimizer 설정은 `INPUT_CONTRACT.md`에 고정한다. 평가연도별 candidate/baseline 2개씩 총 6개의 H2 보정을 완료하고 그 여섯 설정과 H1 계수·입력 해시를 평가 경주를 열기 전에 저장한다.

평가 경주마다 H1의 원시 correction logit `eta_ij=logit(p0_ij)+beta'v_ij`가 가장 높은 pair 하나를 고른다. 완전한 점수 동점은 오름차순 `(horse_number_i, horse_number_j)`로 정한다. H2 Platt의 기울기 `B>0`이므로 이 순서는 보정 확률 순서와 같아야 한다. 이 parity를 assert하고 각 평가 pair의 raw/calibrated 확률과 선택 여부를 모두 저장한다. `beta=0` negative control에서는 p0 maximum pair가 raw-score 상위2 pair와 같은지 전 경주에서 재검증한다.

## 고정 대조군

다음 선택 정책을 모두 같은 경주와 실제 pair 라벨에서 비교한다.

1. 저장 raw `F1_STYLE6` score가 높은 두 말.
2. 저장된 원래 `F1_STYLE6` 말별 `P(Top3)`가 높은 두 말 (`runner_marginals.csv`의 `saved_f1_style6_p_top3`).
3. 기존 candidate joint `q`에서 말별 Top3 주변확률이 높은 두 말 (`candidate_joint_marginal`). 기존 pair-axis 결과에서 이 pair는 434/1,779 경주 적중했다.
4. 기존 candidate joint `q`의 `maximum_joint_pair`: 각 pair를 포함한 모든 exact-Top3 triple probability의 합이 가장 큰 pair. 과거 적중은 422/1,779다.
5. 기존 matched-baseline joint `q`의 `maximum_joint_pair`. 과거 적중은 429/1,779다. 이는 같은 cohort에 대한 맥락 비교로 표시한다.

두 저장 F1_STYLE6 기준은 단조 변환으로 원칙상 같은 상위2를 고르지만, 저장 확률 합산의 ULP 오차가 raw-score rank-2 경계 exact tie에서만 순위를 바꿀 수 있다. 따라서 저장 말 확률 상위2 pair는 raw-score 상위2 pair와 별도 comparator로 보존한다. preflight는 rank-2와 rank-3 raw score가 서로 다르면 두 선택 pair가 같음을 assert하고, exact boundary tie에서는 저장 확률 pair가 raw-score top-two tie block 안에 있으며 rank-1보다 높은 말을 보존하는지 확인한다. 경계 tie 예외 6건은 `AMENDMENT.md`에 source-only 진단으로 기록한다. joint q의 `candidate_joint_marginal` 상위2와 `maximum_joint_pair`는 각기 다른 기존 방식으로 유지한다. 기존 `423/1,779`는 정확 Top3 조합 티켓 적중이므로 pair 적중률로 사용하지 않는다. 기존 `matched_baseline`과 `candidate` arm을 혼합하거나 결과에 따라 한 arm을 선택하지 않는다.

## 평가지표, 신뢰도와 고정 gate

주 지표는 경주마다 하나씩 선택한 pair가 실제 Top3 두 말을 모두 포함한 비율이다. 모든 비교의 차이는 `direct_pair_model - comparator`로 표시한다. 각 비교는 경주일을 cluster로 삼는 paired bootstrap 2,000회, seed `20261011`로 95% 구간을 계산한다. 같은 재표집 schedule을 모든 비교에 적용한다. 연도·거리별 표에도 경주 수, 경주일 수, 적중률과 날짜 paired CI를 함께 쓴다. 2026년은 부분연도이며 소표본 하위집단은 그 사실을 표시한다.

주 비교는 direct pair 모델 대 기존 `F1_STYLE6` raw-score 상위2 pair 하나로 고정한다. 연구 신호 gate는 전체 pair hit-rate 점추정이 이 대조군보다 높고, paired date-cluster 95% 구간 하한도 0보다 큰 경우다. 이는 pair 선택 성능만 판정한다. 원래 `F1_STYLE6 P(Top3)` 상위2, 기존 joint `candidate_joint_marginal` 상위2, candidate 및 matched-baseline maximum-joint-pair의 결과도 모두 보고하되 gate를 대체하지 않는다.

확률 품질은 선택 적중 gate와 분리한 진단이다. 모든 candidate pair와 경주별 선택 pair에서 race-equal Brier 및 Bernoulli log loss를 계산하고, H2에서 별도 보정된 `p0` 기준확률과 비교한다. 각 평가 경주에서 candidate와 baseline 각각 calibrated pair 확률의 합과 기준값 3의 signed·absolute 차이 `sum_ij(p_cal_ij)-3`을 개별 출력과 요약 분포로 보고한다. 이 차이는 pair별 marginal 예측이 공동 Top3 분포가 아님을 보여주는 일관성 진단이지 별도 gate가 아니다. 확률 신뢰도표의 고정 bin은 `[0,.05)`, `[.05,.10)`, `[.10,.20)`, `[.20,.30)`, `[.30,1]`이다. All-pair reliability는 각 pair에 `1/M_r` weight를 주고 bin 안의 예측·관측 평균을 그 weight로 계산한다. Selected-pair reliability는 race당 한 pair에 weight 1을 준다. 각 bin에 pair 수·경주 수·가중 평균 예측값·가중 관측 적중률을 표시하고 빈 bin은 undefined로 표기한다. 선택 pair `p_cal >= .20` 부분집합의 적중률은 평가 중 고정한 예측 마스크로 계산하며 경주 수·coverage·경주일 수·연도/거리 구성을 함께 표시한다. CI는 전체 269개 평가 경주일을 매회 복원추출하고 이 고정 마스크를 재사용한다. 어떤 재표집에서 subset 분모가 0이면 해당 반복은 undefined로 세고, 유효 반복 수와 undefined 수를 보고한다. 평가 결과를 본 뒤 cutoff나 bin을 바꾸지 않는다.

실제 정확 Top2, ordered pair, 복승 확률, 조합 완성률, 배당·수익, 운영 적합성은 이번 연구 목표가 아니다. pair marginal 확률들의 합이 3과 다를 수 있음을 모든 결과 설명에 명시한다.

## 실행과 중단 기준

1. root가 PLAN과 INPUT_CONTRACT를 승인한다.
2. 승인 뒤 source hash·schema·행 키·roster·라벨 산술·날짜 분할·T−2·대조군 재현에 한정한 preflight를 실행한다. 원래 STYLE6 feature lineage에서 `history_cutoff`와 `latest_history_date` 시점 metadata는 preflight 전용으로 확인해 각 style 입력의 과거 이력이 해당 경주일 T−2 cutoff를 넘지 않음을 검사한다. 이 metadata는 model input이나 성능 산출에 사용하지 않는다. `distance_m`은 기존 triple 산출물에 이미 저장된 경주 메타데이터를 연도·거리 보고용으로만 쓴다. preflight는 성능 지표나 pair hit 결과를 산출하지 않는다.
3. preflight source lock과 독립 검토를 root에 올린다. 어떤 지원량, 키, 결측, 저장 점수, split, 후보 pair 선택 재현이든 계약과 다르면 중단하고 그 문제만 보고한다.
4. 별도 root fit 승인을 받은 뒤에만 평가연도별 H1 모델 3개와 fold마다 candidate/baseline 두 개씩 총 6개의 H2 Platt map을 각각 한 번 fit한다. H2도 `success=True`, finite parameter/objective/gradient, bound 준수, 경계 투영 gradient infinity norm `<=1e-6`을 모두 만족해야 수용한다. bound에 도달한 파라미터는 경계·gradient와 함께 기록한다. 이후 잠긴 gate대로 평가한다.
5. 결과 원본, 전체 pair 확률, 경주별 선택 pair, 기존 대조군, paired CI, 연도·거리·신뢰도표, 한국어 README, manifest 및 재현 검증은 이 새 디렉터리에만 저장한다. DB·네트워크·운영 등록부·기존 연구 폴더·말별 F1_STYLE6 결과·더러브렛 입력은 변경하지 않는다.

승인 전에는 모델 계수, 새 pair hit, calibration score, 연도·거리 성능표를 계산하지 않는다.
