# 모델·배팅 연구 통합 색인

기준일: **2026-09-11**

이 문서는 지금까지 진행한 모델·확률·전개·배팅 연구를 찾기 위한 단일 진입점이다.
세부 수치는 각 연구 문서를 원본으로 삼고, 모든 실행 이력은
[`model_runs.jsonl`](../data/experiments/model_runs.jsonl)에서 run ID로 확인한다.

## 1. 현재 사용할 모델

| 용도 | 모델·run ID | 상태 | 판단 |
|---|---|---|---|
| 서울·부경·제주 공통 실전 분석 이력 | RaceFit V5 Sand Event `a30cd09a-3b7b-402a-b010-5e7341fd4144` | 기존 발행 모델 | 명시적 모래 사건·최근성만 안정적으로 사용. 새 경주의 최종 champion 의미는 아님 |
| 제주 전용 1~5위 확률 | 제주 V2 `20047697-0b2e-4dac-9a4d-762271f5e1f9` | **현재 제주 후보** | 최근 모델 75%+장기 모델 25%. Top1 32.96%, 우승마 Top3 68.72%, test 미평가 |
| 배당·레이팅 제외 순수 능력 | Ability V5 `9ef33e36-dfd0-4fc4-b395-cbec2531bde3` | provisional challenger | valid 확률 품질과 Top1 개선, 신규 미래 표본 필요 |
| 초기 G1 통과 기준 모델 | M4 ensemble `61336314-3615-4a87-bc3c-93a90f448c18` | 동결된 비교 기준 | 단순 기준선 대비 G1 PASS, 시장 대비 G2 FAIL |
| Top5 전체 분포 | Margin V2 `a50d77d2-beb8-44d6-a300-fc9249934ab6` | 연구용 challenger | 누적 Top2~Top5 확률 개선, 단일 Top1 목적에는 자동 승격하지 않음 |

`운영`, `후보`, `연구용`은 구분한다. validation에서 가장 높은 적중률을 보였다는 이유만으로
운영 champion으로 승격하지 않으며, 미래 불변 원장 결과가 필요하다.

## 2. 연구 흐름과 결론

| 연구 단계 | 핵심 질문 | 결론·현재 상태 | 상세 문서 |
|---|---|---|---|
| 기준선·G1/G2 | 모델이 단순 Form과 시장을 이기는가 | 능력 기준선은 이겼지만 최종 시장에 독립 edge를 입증하지 못함 | [진행 현황](PROGRESS.md), [모델 로드맵](MODELING_ROADMAP.md) |
| 레이팅·배당 제거 | 말의 순수 능력을 별도 추정할 수 있는가 | Ability V5가 provisional 후보. 레이팅·배당은 구조적으로 차단 | [Ability V2~V6](ABILITY_V2_NO_RATING.md) |
| Plackett–Luce | 우승확률에서 순서 조합확률을 만들 수 있는가 | 순서 Top3 확률은 제공하지만 Top1 순서를 바꾸지 않음. 조합 calibration 필요 | [Full Ranking PL](FULL_RANKING_PLACKETT_LUCE.md) |
| Top5 분포 | 각 말의 정확한 1~5위·누적 확률을 만들 수 있는가 | 단승 champion 교체 없이 복합 승식용 challenger로 유지 | [Top5 순위분포](TOP5_RANK_DISTRIBUTION.md) |
| 장기+최근 결합 | 오래된 대규모 자료와 최근 정밀자료를 어떻게 결합하는가 | 동일 확률축의 앙상블이 단독 모델보다 안정적 | [Top5 Hybrid V1](TOP5_HYBRID_V1.md) |
| 착차 보조학습 | 4·5위와 큰 착차 패배를 구분할 수 있는가 | 착차 직접 relevance는 기각, 연속 착차 성능 보조축은 유효 | [Top5 Margin V2](TOP5_MARGIN_V2.md) |
| 조건·에너지 | 구간별 에너지 배분이 미래 성능을 설명하는가 | 누수 없는 에너지 변수를 RaceFit V1 핵심 입력으로 채택 | [RaceFit V1](RACEFIT_V1.md) |
| 잠재상태·당일 편향 | 컨디션과 당일 주로 변화를 반영할 수 있는가 | Kalman·학습형 페이스는 기각, 예측시각 이전 당일 편향만 후보 | [RaceFit V2](RACEFIT_V2.md) |
| 나이·출전주기·조교 | 생애주기와 훈련 변화가 분명한가 | 최근 상세 우승확률에는 유망, 장기·Top5 모델에는 미채택 | [RaceFit V3](RACEFIT_V3_LIFECYCLE.md) |
| 게이트×선행 전개 | 외곽의 빠른 선행마가 실제 이점을 얻는가 | 일반 규칙으로는 이점 불확실. 2단계 전개 모델 안에서만 일부 개선 | [RaceFit V4](RACEFIT_V4_GATE_PACE.md), [외곽 선행 연구](OUTER_FRONT_ADVANTAGE_STUDY.md) |
| 모래 반응·회복 | 모래 민감도가 지속되거나 사라지는가 | 명시적 사건·최근성은 채택, 회복 자체를 능력 상승으로 보지 않음 | [RaceFit V5](RACEFIT_V5_SAND_RESPONSE.md) |
| 기수 직접 조교·교정 | 동일 기수의 반복 조교가 별도 신호인가 | 표본이 희소하고 개선 구간이 0을 포함해 V5 유지 | [RaceFit V6](RACEFIT_V6_REMEDIATION.md) |
| 복병 탐지 | 모델 순위 밖 저평가마를 찾을 수 있는가 | 후보 탐지는 가능하나 미래 ROI 100%를 안정적으로 넘지 못함 | [RaceValue V1](RACE_VALUE_V1.md) |
| 배팅 포트폴리오 | 여러 승식과 최종배당 불확실성을 함께 다룰 수 있는가 | 가격 하한이 보수적이라 실집행 0건. 연구용이며 수익 모델 아님 | [RacePortfolio V1](RACE_PORTFOLIO_V1.md) |
| 제주 분리 | 다른 마종·기록 체계를 별도 학습해야 하는가 | 제주 전용 모델과 데이터 계약을 분리 | [제주 V1](JEJU_STANDALONE_V1.md), [제주 V2](JEJU_STANDALONE_V2.md) |

## 3. 제주·한라마 데이터 결정

- 한라마 2015~2022 자료는 운영 DB와 학습 경로에서 제거했다.
- 삭제 전 자료는 [`data/archives/halla_2015_2022_20260908`](../data/archives/halla_2015_2022_20260908)에 Parquet·스키마·manifest로 보존했다.
- 제주 경주의 `한국`/`제` 산지 표기는 원천 DB를 바꾸지 않고 feature 생성 단계에서
  `제주마`로 통합한다.
- 제주 V2 최근·장기 데이터셋은 모두 meet code 2만 포함하며 표기 혼용은 0건이다.
- 제주 구간기록 복구 내역은 [제주 구간기록 복원](JEJU_SECTION_REPAIR_2026-09-08.md)에 있다.

## 4. 배팅 조합 연구에서 확정된 공통 결론

과거 대화에서 단승·연승·복승·복연승·쌍승·삼복승·삼쌍승과 여러 박스 조합을 비교했다.
개별 숫자보다 다음 원칙이 현재의 재사용 가능한 결론이다.

1. 우승마 Top3 포함률은 삼복승 적중률이 아니다. 실제 1·2·3위가 모두 선택 조합에 들어가야 한다.
2. 후보를 넓히면 적중률은 오르지만 조합 수가 더 빠르게 늘어 환수율이 낮아질 수 있다.
3. 최종배당으로 정산되는 한국 경마에서는 구매 시점에 가격을 확정할 수 없으므로,
   적중확률만 높이는 전략이 양의 기대수익을 보장하지 않는다.
4. 과거 양의 ROI가 나온 일부 조합은 소수 고배당 적중에 크게 의존했다. 최고 수익 경주를
   제거하면 우위가 사라지는 경우가 있어 수익 증거로 채택하지 않았다.
5. 승식별 확률은 Plackett–Luce 공동분포와 별도 calibration으로 계산해야 하며,
   말별 단승확률을 단순 곱하면 안 된다.
6. 실전 승격은 사전에 동결한 후보·마권·금액·관측시점 배당을 불변 원장에 남기고
   미래 표본에서 판정해야 한다.

더 자세한 이론·외부 연구·지표 정의는 [예상·배팅 모델 연구 총정리](RESEARCH_REVIEW_2026-09-07.md),
운영 기록 구조는 [예측 원장](PREDICTION_LEDGER.md)을 본다.

## 5. 산출물 위치

| 종류 | 기준 위치 | 의미 |
|---|---|---|
| 실험 원장 | [`data/experiments/model_runs.jsonl`](../data/experiments/model_runs.jsonl) | run ID, 데이터 hash, feature, 기간, 지표, 모델 경로 |
| 학습 데이터 | [`data/datasets`](../data/datasets) | 버전/as-of별 `dataset.parquet`와 `manifest.json` |
| 모델 | [`data/experiments/models`](../data/experiments/models) | run ID별 `model.pkl`, validation 예측·비교 |
| 보고서 | [`data/experiments/reports`](../data/experiments/reports) | 자동 생성 실험 보고서 |
| 장기 검증 | [`data/experiments/walk_forward`](../data/experiments/walk_forward) | 연도별 expanding-window 예측 |
| 복병·배팅 | [`race_value_v1`](../data/experiments/race_value_v1), [`race_portfolio_v1`](../data/experiments/race_portfolio_v1) | 연구용 모델·manifest·정산 결과 |
| 실전 예측 | [`data/predictions`](../data/predictions) | 날짜·run별 feature snapshot과 예측 |
| 제거 데이터 보관 | [`data/archives`](../data/archives) | 복구 가능한 Parquet archive |

## 6. 비교할 때 지켜야 할 규칙

- 다른 기간·경마장·정보시점의 Top1과 log loss를 한 순위표에서 직접 비교하지 않는다.
- `valid`, 반복 탐색한 과거 `test`, 실제 미래 불변 원장을 구분한다.
- 적중률, 확률 품질, 수익률은 서로 다른 목표다.
- 환수율 100%는 원금 회수이며, 13배 적중 30%라는 식의 단순 계산은 구매한 조합 수와
  전체 지분을 포함하지 않으면 실제 ROI가 아니다.
- 현재 연구 결과는 수익을 보장하지 않는다.
