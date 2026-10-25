# F1→F1_STYLE6 확률 개선과 6조합 적중 간격 분석 계획

상태: 사전 계획. 결과 집계·새 성능 계산 전 root 검토본. 범위는 기존 저장 점수의 후향 분석이며 모델 fit, tau 최적화, 새 선택 정책, 운영 변경을 포함하지 않는다.

## 모집단과 입력

F1과 F1_STYLE6의 동일한 평가 모집단 1,779경주·17,412출전·269경주일을 사용한다. 연도는 2024, 2025, 2026년(2026-09-19까지)이며 연도별·기존 고정 거리별 결과를 보인다. 각 경주의 출전마, Top3 라벨, 키와 정렬 순서는 저장된 F1 replay 출력으로 고정한다. 후보 raw score는 연도별 `F1_STYLE6_{year}/evaluation_scores.parquet`, tau는 같은 폴더의 저장 `meta.json`에서 읽는다. F1 raw score와 Top3 marginal은 `f1_reproduced_runner_predictions.parquet`; F1 tau는 원 F1 연도별 저장 meta와 원 report/source lock에서 읽는다. API record ID로 일대일 연결하고 점수를 반올림하지 않는다. 전체 모집단·모델별 파일·모델·계약은 기존 `ARTIFACT_MANIFEST.json`, `outputs/prepared_lock.json`, replay/report receipt의 SHA와 대조한다.

각 경주에서 말 번호 오름차순 roster로 모든 무순서 3두 조합을 열거한다. 저장 raw score `s_i`의 triple energy `E_T`는 원 evaluator와 같은 정렬 후 합산 순서를 유지한다. 모델별 저장 tau에서 `Q(T)=softmax(E_T/tau)`를 전체 조합에 정규화하고 말별 Top3 확률은 `p_i=Σ_{T∋i}Q(T)`로 확인한다. 이 분포는 무순서 Top3 집합에 대한 가산 점수 모형이다. 정확한 1·2·3착 순서나 정확 2·3착 확률을 뜻하지 않는다. 두 모델의 raw score 척도는 서로 다르므로 점수 크기 차이를 해석하지 않는다.

## 고정 분석

- 기존 canonical 6조합을 원 evaluator의 stable 정렬·동점 규칙으로 다시 만들고 저장된 F1/STYLE6 조합과 선택 순서·확률을 대조한다. 동일 모델 안에서 저장 tau와 고정 tau=1의 triple rank 및 선택 티켓 불변을 확인한다. tau=1 비교 손실은 보정 동작을 보는 기술 진단으로만 표시한다. tau 탐색·성능 판정에는 쓰지 않는다.
- 실제 Top3 triple의 full ranking과 정확 동점 수, hit@k (`k=1,3,6,10,20`)를 진단한다. k>6은 순위 진단이며 6조합 개선으로 표현하지 않는다. Top5 말별 포착률은 6조합 hit의 상한으로 취급하지 않는다.
- 경주별 양쪽 선택 티켓의 변경 여부·교집합 수·대칭차 티켓 수와 hit both / F1 only / STYLE6 only / neither를 분해한다. 각 모델 `v`의 selected-six 티켓에 등장한 horse ID 합집합을 따로 `U6_v`로 둔다. 모델별로 hit (자기 6장에 실제 triple 포함), allocation miss (자기 티켓에는 없지만 실제 Top3 3두 모두 `U6_v` 안), union miss (실제 Top3 중 하나 이상 `U6_v` 밖)로 나눈다. 전체 경주 수는 각 모델 안에서 세 범주의 합이며 `all3inU6_v = hit + allocation miss`를 확인한다. `U6_v`는 선택된 여섯 티켓에서 역으로 정해지는 모델별 집합이므로 독립적으로 고정된 후보 pool이 아니다. 이 분해는 현재 선택의 위치를 설명하며, union miss 비율로 말 평가나 조합 모형의 원인을 확정하지 않는다. U6 구성원·크기·두 모델 간 교집합과 차집합도 보존한다.
- 저장 tau의 joint true-set NLL, full-joint multiclass Brier `Σ_T(Q(T)-1[T=truth])²`, Top3 marginal Bernoulli log loss/Brier, 선택 6장의 예측 mass와 관측 hit를 비교한다. Six-mass reliability 구간은 `[0,.1), [.1,.2), …, [.9,1]`로 고정하고 0·1 endpoint를 포함한다.
- runner proper loss는 기존 경주 균등 가중을 유지한다. 선택 6 변경/유지 경주와 실제 Top3/기타 출전별 기여는 경주마다 해당 하위집합 loss 합을 전체 출전수로 나눈 뒤 경주 평균을 내어, Top3 기여와 기타 기여의 합이 전체 race-equal loss와 일치하게 한다. 각 그룹에서 분자·출전 수·경주 수를 함께 보존한다.
- 모든 주 지표는 전체·연도·기존 고정 거리로만 나눈다. Paired CI는 날짜 단위 bootstrap 2,000회, seed 20261008을 지표별 재설정한다. 소표본 거리의 경주·날짜 수를 함께 표시한다.

## 산출 및 해석 경계

저장 parity, full-triple 분포·순위, 티켓 변경 및 세 miss 범주, joint/marginal proper loss, fixed-bin reliability, paired date CI를 새 폴더 안 산출물과 결과 설명에 남긴다. 관측으로 확인된 분해, 같은 과거 코호트의 후향 관찰, 미래 자료에서 별도 검증할 가설을 구분한다. 원인·인과 효과·미래 일반화 또는 새 6조합 규칙을 결론으로 제시하지 않는다. 기존 입력 해시와 새 입력 해시를 보존하고 모든 출력은 생성 전 경로 존재를 거부한다. 중앙 결론 문서는 이번 산출에서 수정하지 않는다.
