# 모델축과 단승 최저배당 favorite가 갈린 조건

## 질문과 범위

이 후향 기술 분석은 저장된 F1_STYLE6 모델축과 동결된 API4 단승 최저표시배당 favorite가 다른 경주에서, 실제 Top3 결과가 네 상태로 어떻게 나뉘었는지와 사전 저장 T−2 프로필의 차이를 살폈다. 2024-01-05부터 2026-09-19까지 4개 거리의 동결 자료를 사용했다. 26개 최저배당 동률 경주는 단일 favorite가 아니므로 제외했고, 고유 favorite가 있는 1,477경주 중 축과 favorite가 다른 678경주를 주 조건 분석에 포함했다.

경주-말 연결은 `api_record_id`, `race_id`, `horse_id`, 마번을 모두 확인했다. frozen F1_STYLE6 원장의 14,714개 출전이 저장 baseline predictions의 동일 출전과 맞았고, 축 1,503마 및 고유 favorite 1,477마는 T−2 feature row와 일대일로 연결됐다. 원천 SHA-256은 `SOURCE_HASHES.json`에 고정했다. root verified ledger의 선택 ID와 case도 고유 favorite 1,477경주 전체에서 일치했다. relative10 후보는 사용하지 않았다.

## 확인된 결과

전체 1,477경주의 축/favorite Top3율은 각각 57.5%와 65.8%였고, 그 차이는 -8.3%p다. 다른 축·favorite 678경주에서는 네 상태가 다음과 같았다.

| outcome | races |
|---|---:|
| model-only: 축만 Top3 | 126 |
| market-only: favorite만 Top3 | 248 |
| both | 173 |
| neither | 131 |

이 678경주에서 축 Top3율은 44.1%, favorite Top3율은 62.1%로, model-minus-market 차이는 -18.0%p였다. XOR는 126 model-only와 248 market-only다. 이는 선택한 두 말의 이분형 Top3 빈도 차이며 우승 확률이나 승식 수익률이 아니다.

사전에 고정한 조건 경계별 네 outcome의 지원수·Top3율·차이는 `condition_summary.csv`에 있으며, 주요 조건행의 population은 `all_disagreements_678`이다. 같은 표에 `unique_favorite_background_1477`을 배경으로 따로 제공한다. 조건 경계를 고정했다는 뜻이지 favorite ID를 사전에 알 수 있다는 뜻은 아니다. favorite ID는 사후 확정 단승배당으로 고른 비교대상이다. 거리별 grade와 field 분포는 함께 달라질 수 있어 grade 단독 차이를 거리와 무관한 효과로 읽지 않는다. 표본 n<30 또는 네 outcome 중 하나라도 n<10인 셀은 `exploratory_flag=true`다. 2026은 9월 19일까지의 부분연도이며, 2024–25 대 2026 방향 비교는 새 독립 검증이 아니다.

### 고정 조건에서 확인된 차이

아래는 결과를 보고 경계를 바꾸지 않은 4개 핵심 조건이다. 각 행은 678개 disagreement 전체에서 네 outcome을 함께 보이며, XOR만 골라 집계하지 않았다. `favorite`는 사후 확정 단승배당으로 정해진 비교 대상 말 ID이므로 favorite ID를 이미 안다고 가정한 조건은 배포 가능한 사전 선택 규칙이 아니다. `p_gap`은 그 favorite와 축의 저장 p_top3 차이다.

| 조건 (저장 T−2 피처 × 사후 favorite ID) | 지원·네 outcome 수·Top3율 |
|---|---|
| p_gap ≥ 0.10 | n=368; MO/Mkt/Both/Neither=61/144/98/65; axis 43.2%, favorite 65.8%, 차 -22.6%p |
| paired mean5: 축 ≤ favorite | n=310; MO/Mkt/Both/Neither=52/122/76/60; axis 41.3%, favorite 63.9%, 차 -22.6%p |
| 축 observed_starts 1–4 | n=174; MO/Mkt/Both/Neither=27/73/54/20; axis 46.6%, favorite 73.0%, 차 -26.4%p |
| favorite valid_n5=0 | n=158; MO/Mkt/Both/Neither=31/58/51/18; axis 51.9%, favorite 69.0%, 차 -17.1%p |

기간별 같은 경계의 방향은 다음과 같다. `MO/Mkt`는 model-only / market-only 경주 수이며, Top3율은 해당 조건 표본에서 각각 축/favorite의 주변 적중률이다. 조건부 차이는 원인이나 배당 기반 전략이 아니다.

| 조건 | 기간 | n | MO/Mkt | 축 / favorite Top3율 | 차 |
|---|---|---:|---:|---:|---:|
| p_gap ≥ 0.10 | 2024 | n=118 | 16/37 | 40.7% / 58.5% | -17.8%p |
| p_gap ≥ 0.10 | 2025 | n=130 | 22/61 | 40.8% / 70.8% | -30.0%p |
| p_gap ≥ 0.10 | 2026 (부분) | n=120 | 23/46 | 48.3% / 67.5% | -19.2%p |
| p_gap ≥ 0.10 | 2024–25 합산 | n=248 | 38/98 | 40.7% / 64.9% | -24.2%p |
| paired mean5: 축 ≤ favorite | 2024 | n=112 | 18/38 | 38.4% / 56.2% | -17.9%p |
| paired mean5: 축 ≤ favorite | 2025 | n=102 | 14/47 | 40.2% / 72.5% | -32.4%p |
| paired mean5: 축 ≤ favorite | 2026 (부분) | n=96 | 20/37 | 45.8% / 63.5% | -17.7%p |
| paired mean5: 축 ≤ favorite | 2024–25 합산 | n=214 | 32/85 | 39.3% / 64.0% | -24.8%p |
| 축 observed_starts 1–4 | 2024 | n=47 | 6/19 | 42.6% / 70.2% | -27.7%p |
| 축 observed_starts 1–4 | 2025 | n=67 | 13/28 | 49.3% / 71.6% | -22.4%p |
| 축 observed_starts 1–4 | 2026 (부분) | n=60 | 8/26 | 46.7% / 76.7% | -30.0%p |
| 축 observed_starts 1–4 | 2024–25 합산 | n=114 | 19/47 | 46.5% / 71.1% | -24.6%p |
| favorite valid_n5=0 | 2024 | n=44 | 9/17 | 50.0% / 68.2% | -18.2%p |
| favorite valid_n5=0 | 2025 | n=63 | 13/26 | 49.2% / 69.8% | -20.6%p |
| favorite valid_n5=0 | 2026 (부분) | n=51 | 9/15 | 56.9% / 68.6% | -11.8%p |
| favorite valid_n5=0 | 2024–25 합산 | n=107 | 22/43 | 49.5% / 69.2% | -19.6%p |

각 거리별로 전체연도를 합친 주변치와 각 연도별로 네 거리를 합친 주변치에서는 favorite Top3율이 축보다 높았다. 이는 거리×연도 교차 셀까지 모두 같은 방향이라는 뜻은 아니다. 예를 들어 2026 부분연도의 1110m 교차 셀은 n=52에서 축 55.8%, favorite 51.9%로 차이가 +3.8%p다. 세 핵심 구간은 각 연도에 같은 방향이지만, 이미 검토된 기간의 기술적 일관성이지 새 검증이 아니다. 거리·연도별 주변 수치는 다음과 같다.

| 구간 | n | 축 / favorite Top3율 | 차 |
|---|---:|---:|---:|
| 2024년 | n=233 | 42.1% / 58.4% | -16.3%p |
| 2025년 | n=249 | 43.0% / 63.9% | -20.9%p |
| 2026년 | n=196 | 48.0% / 64.3% | -16.3%p |
| 900m | n=124 | 46.0% / 69.4% | -23.4%p |
| 1000m | n=234 | 46.6% / 65.0% | -18.4%p |
| 1110m | n=210 | 41.9% / 58.1% | -16.2%p |
| 1200m | n=110 | 40.9% / 55.5% | -14.5%p |

전체 paired hit-rate 차이의 race-date cluster bootstrap 95% 구간은 **-17.99%p** (2,000회, 255개 날짜 클러스터; [**-23.24**, **-12.91]%p**)다. 표의 조건별 marginal hit rate에는 Wilson 95% 구간, paired 차에는 Wald 95% 구간이 함께 기록돼 있다. 조건을 훑어 고른 듯한 해석을 피하고 sparse flag를 확인해야 한다.

favorite의 `valid_n5=0`은 debut와 같지 않다. 이 조건의 favorite 158마 전부 saved `same_starts=0`이었지만, saved `observed_starts=0`으로 관측된 이전 출발이 없는 말은 34마였고 나머지 124마는 다른 거리 이력만 있었다. 이 원천 counter만으로 lifetime debut를 확정하지 않으며, 전체 저경력 말에 일반화하지 않는다.

### 후보군 진단과 확률 잔차

market-only 248경주 중 실제 Top3 말이 모델 score 순위 상위 K에 하나라도 포함된 비율은 다음과 같다. 이는 결과를 알고 계산한 후보군 덮임 진단이며 구매 규칙이나 실전 성과 추정이 아니다.

| 모델 상위 K | 실제 Top3 포함 race | 비율 |
|---:|---:|---:|
| 1 | 0/248 | 0.0% |
| 3 | 218/248 | 87.9% |
| 5 | 245/248 | 98.8% |

`calibration_by_group.csv`는 확률 보정 곡선이나 보정 모델이 아니라, 선택된 축/market favorite 말에 대한 조건부 평균 잔차 `actual Top3 indicator − saved p_top3`다. 전체 runner 집합의 calibration을 뜻하지 않는다. 단조 확률변환은 score 순서를 유지하므로 현재 축의 순위나 선택을 바꾸지 않는다. 순위 선택을 바꾸려면 별도 순위 모델·규칙을 미래 시간분리 OOF 평가로 검증해야 한다.

## 조건 패턴을 읽는 법

`exclusive_distribution.csv`는 사전 변수의 mean/median/quartile/support를 model-only 126경주와 market-only 248경주에서 나란히 제시한다. `axis_minus_favorite` 행은 모델축 말 값에서 market favorite 말 값을 뺀 paired 차이다. 연속 변수는 표본 분포 요약이며 조건을 새로 찾거나 원인으로 해석하는 분석이 아니다. `race_pair_features.parquet`는 고유 favorite 전체 1,477경주의 개별 T−2 프로필, case labels, ID와 고정 범주를 담는다.

`calibration_by_group.csv`는 선택된 말의 조건부 평균 예측잔차(actual Top3 indicator − saved p_top3)를 기록한다. 이를 전체 runner calibration이나 실제 보정 곡선으로 해석하지 않는다.

`trend_s`는 newer3 평균 초−older3 평균 초이며 각 구간에 유효 기록이 둘 이상 있어야 한다. 양수는 최근 기록이 느려진 방향이다. `std5_s`는 최근 5회 표본 표준편차(유효 3개 이상), `best5_s`는 최근 5회 최소 초다. `previous_top3`는 이전 순위가 1~3위인지 여부이고, 전체 경주가 완결됐는지는 보장하지 않는다. `previous_result_status`는 별도 상태다.

## 확정 배당의 제한

마지막 확정 win odds와 모델축의 사후 odds rank는 `race_pair_features.parquet`, `examples.csv`에 설명용으로 별도 저장했다. favorite ID도 사후 확정 단승배당으로 정한 비교대상이며 예측 입력으로 사용할 수 없다. odds 공개 시점은 확인되지 않았으므로 배당과 해당 ID를 구매 전 전략으로 사용할 수 없다. 최저 단승배당은 단순 역수로 Top3 확률이 되지 않는다.

## 현실적인 개선 방향

관측 결과만으로 model-only 경주를 사전 판별하는 안정적인 단일 규칙은 확인되지 않았다. `p_gap`, favorite의 모델 내 순위, 두 말의 최근 평균 시간과 이력 지원량은 다음 검증에서 사전 등록할 가설이지, 현재 선택 기준이 아니다.

1. 현재 F1_STYLE6 말 평가를 기준선으로 보존한다. 보조 순위기를 검토한다면 기존 축 선정을 대체하지 않는 model-side 후보 재순위기로 설계하고, 저장된 사전 입력만 사용한다. 사후 favorite ID나 최종 배당을 예측 입력으로 쓰지 않는다. 학습이 필요해지면 시간 분리 OOF 점수로만 만들고 미래 홀드아웃에서 비교한다. 이번 분석에서는 학습하지 않았다.
2. `valid_n5=0`을 debut와 타거리 이력만 있는 말로 나눠 프로필 지원량을 보고한다. 두 집단을 섞지 않고, 말의 이력 조건이 시장 favorite 성능과 어떤 관계를 갖는지 독립된 미래 기간에서 재검증한다.
3. mean5·상대 rank·gap·coverage와 style/passrank support를 거리·grade·field를 함께 고려한 사전 지정 평가 후보로 둔다. 단변량 조건 결과를 원인으로 읽지 않고, 안전한 거리 전이 피처는 별도 계획과 시간분리 기준을 갖춘 뒤 베이스 후보로만 검토한다.
4. 목표가 단일 축 적중이 아니라 Top3 후보군이라면 top-K 후보군 덮임을 별도 평가목표로 사전 정의한다. 이번 top-K 값은 사후 결과를 이용한 진단이며, 예측 성능이나 전략 수익으로 승격하지 않는다.
5. 확률 잔차 진단은 runner 단위 전체 예측과 선택된 말 조건부 표본을 구분해 유지한다. 단조 calibration만으로는 순위와 축 선택이 달라지지 않으므로, 확률 보정과 순위 변경을 별도 문제로 다룬다.

이 제안은 보존된 말 평가와 현재 F1_STYLE6를 유지하는 분석 방향이다. 본 작업에서는 기존 모델·DB·과거 연구를 수정하지 않았고, 모델 학습·threshold optimization·외부 수집·DB 접근을 하지 않았다.

## 산출물

- `PLAN.md`, `SOURCE_HASHES.json`, `SCHEMA_AND_LINK_AUDIT.json`: 사전 계획, 잠금 입력, 스키마/연결 감사
- `race_pair_features.parquet`: 고유 favorite 전체 1,477경주, IDs, raw T−2 profiles, fixed categories
- `condition_summary.csv`: 678 disagreement 및 1,477 background의 네 outcome counts, marginal hit rates, support와 sparse flags
- `exclusive_distribution.csv`: 126 model-only와 248 market-only의 paired profile distribution
- `calibration_by_group.csv`: 선택된 축/favorite의 조건부 평균 예측잔차 by role and fixed group
- `condition_summary_by_period.csv`: 사전 고정 조건의 연도별·2024–25 합산 일관성 표
- `model_topk_pool_diagnostic.csv`: 사후 실제 Top3 후보군 덮임 진단
- `FEATURE_CATALOG.csv`: 저장 55개 열 각각의 F1_STYLE6 exact input 여부
- `examples.csv`, `REPORT.json`, `analysis.py`, `OUTPUT_MANIFEST.json`: 날짜순 사례, 집계/검산, 재현 스크립트 및 output hash
