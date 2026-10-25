# 단일 연승 축 확률·사후 배당 결과

고정 F1_STYLE6 저장 점수로 경주당 한 마리를 선택했습니다. 8두 이상은 저장된 exact-Top3 주변확률을 평가했고, 7두 경주는 실제 Top2 결과·수익만 포함하며 확률은 unavailable로 남겼습니다. 확률 bins/threshold, 1,000원 고정 stake, 결과/배당 원천 및 날짜 bootstrap 일정은 승인된 연구 계획에 고정되어 있습니다. PLC 가격은 API301 사후 odds quote이며 사전 공개 가능 시점은 확인되지 않았습니다. 미적중 총환급은 0원으로 계산했습니다.

`single_place_summary.csv`에는 전체·연도·필드크기·확률구간·고정 threshold별 분모, 평균 확률, 적중률, 보정차이, Brier/log loss, 환급/ROI 및 날짜 CI가 있습니다. `mean_hit_odds`는 당첨마 odds multiplier 평균이고, `mean_hit_return_krw`는 적중당 총환급원입니다. 손익분기 적중률은 평균 적중 odds의 역수이며 `break_even_odds`는 실제 적중률의 역수입니다.

`single_place_race_results.csv`는 경주별 선택·결과·확률·사후 odds quote·가정 총환급입니다. 이 자료는 평가에 사용된 과거 경주의 사후 기술통계이며 독립 미래검증이나 배당 전 기대수익을 뜻하지 않습니다.
