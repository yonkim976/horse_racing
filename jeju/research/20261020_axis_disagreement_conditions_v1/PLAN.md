# 분석 계획: 모델축과 확정 단승 최저배당의 Top3 갈림

## 질문과 범위
유지 중인 F1_STYLE6 연구 기준축과 사후 확정 단승 최저배당 말이 다른 경주에서, 모델축만 실제 Top3(모델 전용), 시장축만 실제 Top3(시장 전용), 둘 다, 둘 다 아님이 어떤 사전 관측 조건과 함께 나타나는지 기술한다. 새 예측기나 선택 규칙을 학습·최적화하지 않으며, 결과는 후향 조건부 연관성이다.

## 동결 입력과 연결
고정 입력은 `SOURCE_HASHES.json`에 경로·크기·SHA-256으로 잠근다. 분석 단위는 사용자 제공 원천의 2024–2026-09-19 경주이며, 고유 26 최저표시배당 동률은 제외한다. 예측은 baseline runner predictions에서 F1_STYLE6 축을 식별하고, 말·경주 키로 frozen runner ledger/selected rows와 T−2 feature store를 일대일 연결한다. 축·마필의 API/경주/출전 ID, horse ID, 마번을 보존한다. 연결 중복/누락/충돌은 결과 전에 검증하고 보고한다. root verified race ledger/summary는 독립 원장 대조용이다.

## 사전 고정 표본·결과
주요 분석은 678개 disagreement races 전체의 네 상태를 모두 보존한다: model-only 126, market-only 248, both 173, neither 131 (전수 사전 집계값). XOR 374개는 설명 비교 전용이며 표본 선택을 피하기 위해 주요 조건표에는 쓰지 않는다. 1,477 unique-favorite races 전체를 배경으로 분모와 Top3율을 함께 표시한다. `actualhit`은 공식/동결 결과의 Top3 여부다.

## 조건 경계 (결과 확인 전 고정)
- 거리·grade 원문·field_n·연도: 원문 카테고리/값을 유지하고 거리와 교차해 표시한다.
- 확률차 `p_gap`은 signed `axis_p_top3 − favorite_p_top3`로 계산하고 <0.05, [0.05,0.10), ≥0.10으로 구간화한다. signed 확률·점수 차는 연속 요약도 함께 제공한다.
- 시장 favorite의 모델 순위: 2, 3, ≥4 (1위는 disagreement에서 빠지는지 분모로 명시).
- observed_starts: 0, 1–4, ≥5.
- valid_n5: 0, 1–2, 3–5.
- `days_since_start`와 `days_since_same` 각각 ≤14, 15–28, 29–56, >56일, null로 구간화한다. `same_starts`와 `same_valid_times`는 exact count와 missing을 표시한다.
- `previous_age`는 exact 값 및 missing, `previous_sex`는 원문 category 및 missing으로 표시한다.
- 두 비교 말의 paired-valid mean5: 모델축 ≤ 시장 favorite 대 모델축 > 시장 favorite; 두 피처 중 하나 미관측은 별도.
- 이전 기록: 모델축 previous_top3 × favorite previous_top3 네 상태와 missing; `previous_result_status` 원문 범주도 별도로 표시한다.
- Continuous profile은 사전 지정한 last/mean5/trend/std5/best5와 valid-count support, 편성 상대 rank/coverage/gap, style/passrank 과거 평균·support를 두 말 paired로 요약한다. `mean3_s`, `valid_n3`, `previous3_mean_s`, `previous3_valid_n`, `fast2mean5_s`도 보조 저장 피처로 표시하고 model input 포함 여부를 구분한다. 저장된 `trend_s`는 newer3 mean−older3 mean(각각 valid≥2)이며 양수는 최근 느려짐, `std5_s`는 3개 이상 유효한 최근 5회 표본 표준편차, `best5_s`는 최근 기록 중 최소 초다. `same_distance_last5_top3_rate`와 해당 support는 저장됐지만 F1_STYLE6 입력은 아니다. `previous_top3`는 개별 이전 순위가 1..N일 때 값이 정해지고 전체 경주 완결성은 요구하지 않는다. `previous_result_status`는 별도 완결 상태다.
- 연도별 2024/2025/2026(부분) 및 pooled 2024–25 vs 2026(부분): 방향 일관성을 설명하되 새 독립검증이라 부르지 않는다.

## 보고 항목과 제한
1. 전체 1,477/678 races의 네 outcome counts와 marginals, 연도/거리/grade/field size 분포.
2. 고정 조건별 네 상태의 n, outcome별 hit rate 및 model-minus-market 차, 지원수; 조건별 집계는 678개 전체를 대상으로 하며 sparse-cell flag를 붙인다. n<30 또는 outcome case n<10이면 exploratory flag다.
3. 126 vs 248 XOR에서 사전 피처 mean/median/n만 요약한다. 조건 경계를 추가 탐색하거나 유리한 조건을 순위화하지 않는다. continuous features는 쌍별 분포/지원/사분위 요약으로만 제시한다.
4. 선택된 두 축 말 모두의 calibration (actual − p) by group; calibration 표본 범위와 support를 명시한다.
5. 조합식 결과 설명: 최근/과거 성적, 편성 상대력, style/passrank support, model score/probability 및 axis−favorite gap, market 말의 모델순위·모델축의 사후 최종 odds rank. 입력 계약 포함 여부는 model meta의 exact input list 기준으로 각 피처에 명시한다.
6. 확정 win odds 및 final odds rank는 결과 설명 전용으로 별도 표기한다. 예측 가능 사전 입력·구매 전 전략으로 승격하지 않는다.
7. 모델명·마명은 frozen source 표기만 사용하고 현재 프로필/최근 마명으로 과거 엔트리를 잇지 않는다. 예시는 각 네 상태별 첫 날짜 순으로 소수 제시한다.

## 금지와 변경 경계
- 기존 모델/DB/과거 연구를 변경하지 않는다. 신규 모델 학습, threshold optimization, 외부 수집, DB 조회·쓰기 없음.
- 후보 relative10은 사용하지 않는다. 주 분석은 유지 중 F1_STYLE6 기준축이다.
- 저장 T−2 피처만 사전 조건으로 사용한다. 사후 odds, ranks, 결과는 예측 입력이나 구매 전략으로 제시하지 않는다.
- `favorite` ID 자체는 사후 확정 단승배당에서 고른 비교대상이다. favorite ID를 조건식에 포함한 결과와 p_gap은 설명용 후향 비교이며 사전 배포 조건이나 입력이 아니다.
- 출력은 이 새 연구 폴더 안에만 저장한다.

## 고정 분석 단계
1. 이 계획과 입력 해시 잠금 작성.
2. 원천 및 feature/prediction 스키마·모델 입력 계약을 점검하고 ID 연결 감사.
3. 사전 고정 조건으로 outcome 집계와 경계 표 작성.
4. XOR 분포, calibration, 날짜순 사례를 만들고 계산 검산.
5. 한국어 README에 관측된 차이, 불확실성, 개선 가설을 분리해 제시. 현실적인 개선 제안은 3–5개로 제한하고 기존 말 평가를 유지한다.

## 불확실성 보고 규칙
전체 678 disagreement의 paired hit-rate 차에는 race-date 단위 replacement bootstrap (2,000회, seed 20261020) 95% percentile 구간을 보고한다. 조건별 주변 hit rate에는 Wilson 95% 구간을, 같은 조건 안에서 축−favorite paired 차에는 Wald 95% 구간을 보조로 붙인다. 표본이 작거나 outcome 셀이 작으면 exploratory flag를 표시하고, 구간이나 결과를 본 뒤 경계를 바꾸지 않는다.

## 사후 추가 설명 진단
독립 검토자가 요청한 model Top-K candidate-pool coverage는 별도 CSV로 제공한다. 각 outcome case 안에서 상위 K에 actual Top3 runner가 한 명이라도 있었는지를 세는 hindsight diagnostic이며, 조건 경계 검색·구매 규칙·실전 성능 주장이 아니다. 이 진단은 사전 고정 조건표 및 결론과 분리해 표시한다.
