# F1 → F1_STYLE6 확률 개선과 최대 6조합 적중 간격

## 핵심 결과

2024-01-05~2026-09-19(2026년은 부분 연도) 사이의 동일한 1,779경주·17,412출전·269일 후향 코호트에서 F1_STYLE6는 저장 tau 기준 말별 Top3 확률 손실뿐 아니라 무순서 정확 Top3 집합의 joint proper loss도 개선했다. 경주 균등 평균 runner log loss는 0.569469에서 0.568159로, Brier는 0.192724에서 0.192256으로 낮아졌다. Joint true-set NLL 차이(STYLE6−F1)는 −0.011824 (날짜 paired bootstrap 95% CI −0.020153~−0.003451), full-joint Brier 차이는 −0.000508 (95% CI −0.000923~−0.000090)이었다.

하지만 이 개선은 최대 6장의 실제 티켓 적중을 안정적으로 끌어올렸다고 보기 어렵다. 6조합 hit 비율은 22.32%에서 22.88%로 0.56%p 높아졌지만, 날짜 paired 95% CI는 −0.51~+1.64%p로 0을 포함한다. 선택 6장의 평균 예측 mass는 22.51%에서 23.01%로 높아졌다. 이는 적중 결과와 다른 확률 진단이며, 고정 구간 reliability 표는 `outputs/six_mass_reliability.csv`에 있다.

경주별 적중은 두 모델 모두 맞힌 경주 354건, F1만 맞힌 43건, F1_STYLE6만 맞힌 53건, 모두 놓친 1,329건이었다. 따라서 STYLE6의 순증은 10/1,779경주다. 연도별로는 2024년 새 적중 28건·기존 적중 손실 15건으로 순 +13건, 2025년 새 적중 15건·기존 적중 손실 17건으로 순 −2건, 2026년 새 적중 10건·기존 적중 손실 11건으로 순 −1건이었다. 2025년과 2026년의 hit rate 차이는 각각 −0.31%p와 −0.20%p다. 전체 runner loss 개선이 연도마다 같은 6-ticket 결과를 뜻하지 않는다.

## 티켓이 같은 경주와 달라진 경주

두 모델의 선택 6장이 같은 경주는 477건(26.8%), 달라진 경주는 1,302건(73.2%)이다. 티켓이 그대로인 477경주에서도 STYLE6의 runner log loss 평균 차이는 −0.001821, Brier 차이는 −0.000596이었다. 티켓이 바뀐 경주에서도 각각 −0.001122와 −0.000421이었다. 고정된 선택 집합에서도 점수와 확률 재분배가 runner proper loss를 바꿀 수 있으므로, runner loss 개선만으로 실제 조합 적중 변화를 예상할 수 없다.

경주 균등 runner 손실 기여를 실제 Top3와 나머지 출전으로 나누면, 양쪽 티켓 상태 모두 Top3 기여가 log loss와 Brier 개선의 대부분을 보였다. 예를 들어 티켓이 같은 경주의 Top3 log-loss 기여는 F1 0.324820에서 STYLE6 0.323407로 낮아졌다. 반면 나머지 출전의 Brier 기여는 티켓 변경 경주에서 0.064206에서 0.064352로 조금 높아졌다. 이 분해는 각 그룹의 출전 loss 합을 경주 전체 출전수로 나눈 뒤 경주 평균을 내며, `runner_rows`는 실제 출전 행 수다.

## 실제 Top3와 선택 6장의 위치

각 모델의 자기 선택 6장에 등장한 말의 합집합을 U6로 정의해 실현 Top3를 나눴다. F1은 hit 397, U6 안에 있지만 미선택된 조합(allocation miss) 463, U6 밖의 말이 있는 경우(union miss) 919건이었다. STYLE6는 각각 407, 468, 904건이었다. 따라서 STYLE6에서 현재 선택 기준의 union miss는 15건 줄었고, hit는 10건 늘었다. 이는 현재 선택 티켓에서 관측된 위치 분해일 뿐 원인 판정은 아니다. U6는 선택된 여섯 티켓에서 역으로 정해지므로 독립적인 후보 pool이 아니다.

실현 triple의 전체 순위에서 상위 3조합 안에 든 경주는 234→233, 상위 6조합 안은 397→407, 상위 10조합 안은 575→608이었다. hit@10 rate는 32.32%→34.18%, hit@20은 50.98%→51.43%다. 이산적인 순위와 joint proper loss는 서로 다른 평가값이므로 전체 joint loss 개선이 상위 6 hit 개선과 일치할 필요가 없다. k=10·20은 더 큰 티켓 예산을 참고하는 순위 진단일 뿐, 최대 6조합 개선이나 예산 확대 권고로 해석하지 않는다. 전체 rank와 k={1,3,6,10,20} 값은 `outputs/race_diagnostics.parquet`에 있다.

## 계산과 검증

모든 경주는 저장 F1 replay의 출전마와 라벨을 고정하고, 두 모델의 저장 raw score로 가능한 모든 무순서 3두 조합을 열거했다. 원 evaluator와 같은 full-precision 정렬 합, stable tie 순서, 전체 조합 정규화를 사용했다. 저장 결과와 재계산한 canonical 6장 선택 순서는 두 모델 모두 10,674행 전부 일치했고, 티켓 확률 오차는 1e-16 미만, 말별 marginal 및 runner loss 오차는 0이었다. 저장 tau와 tau=1에서 순위·top6 불일치는 없었고, 말 점수 순서와 Top3 marginal의 단조성 위반도 없었다. tau=1은 온도 진단만을 위한 고정 비교다.

원천 입력 해시, 승인된 PLAN/contract 해시, 실행 코드 해시와 tau는 `outputs/source_lock.json`에 기록했다. 입력 해시는 계산 시작과 끝에서 동일했다. 전체 triple 자료는 `outputs/all_triples.parquet`, paired 날짜 bootstrap은 `outputs/paired_date_bootstrap.csv`, 티켓 및 U6 분해는 `outputs/ticket_and_union_decomposition.csv`, 손실 cross는 `outputs/ticket_change_loss_cross.csv`에 있다. 집계 결과는 `outputs/RESULTS.md`, 산출 해시는 `outputs/MANIFEST.json`을 참조한다.

## 해석 범위와 다음 검증

이는 사후 정상 완주 코호트의 후향 비교다. 과거 당시 공개 가능 시각과 예측 대상 편성을 복원하지 못했고, 같은 기간 자료가 반복 사용되었으므로 미래 독립 성능을 나타내지 않는다. 여러 진단과 구간을 함께 살핀 CI는 각 지표의 pointwise 구간이며 다중 비교 보정은 하지 않았다. 저장 결과와의 수치 parity 및 이 문서에 표시한 분해는 확인됐지만, 왜 특정 triple을 놓쳤는지에 대한 인과 설명이나 미래 성능을 입증하지 않는다. 확률 모형은 무순서 정확 Top3 집합에 대한 것이며 착순을 복원하지 않는다. 모델 간 raw score 크기를 비교하지 않았다. 새로운 조합 규칙, 모델 fit, tau 탐색, 운영 승격은 이 범위에 포함하지 않는다.

후속 연구 후보는 현재 baseline을 유지하면서, 공정한 시계열 out-of-fold 검증 및 같은 6장 예산 아래 동반·공동 조합 관계를 별도 비교하는 것이다. 이는 검토 후보이지 개선이 확인된 방안이 아니다. 말 점수의 효과와 조합 배분에 관한 설명은 현재 결과만으로 확정하지 않고 별도 가설로 둔다.

독립 재계산과 A 산출물 전체 대조는 모두 PASS다. [C 독립 검증 receipt](../20261010_probability_combo_gap_review_v1/outputs/independent_verification.json), SHA-256 `21097696799f15e1c9ad1eb7256b29ddb8c56ed301d698f7097dc07a3fd42e14`; [A 산출물 대조 receipt](../20261010_probability_combo_gap_review_v1/independent_A_comparison_final.json), SHA-256 `e34254a30aaafb445de38bf65880b615a504e080f9dd35e5ec5c97de8ddbae45`. 전체 402,808 triple·3,558 race-variant 진단과 CI 표를 1e-12 허용오차로 대조했으며, runner 기여 차이의 최대 절대 오차는 1.11e-16이었다.
