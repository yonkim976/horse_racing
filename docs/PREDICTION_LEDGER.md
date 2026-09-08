# 공개 예측 검증 원장

최종 갱신: 2026-08-28

이 원장은 경주 전에 발표한 말별 확률을 사후 수정할 수 없게 고정하고, 공식 결과가 모두
들어온 뒤 동일한 원본에 대해 한 번만 정산한다. 목표는 적중 사례를 고르는 것이 아니라
모델의 장기 확률 품질을 누구나 재검산할 수 있게 만드는 것이다.

## 1. 불변 계약

1. `live` publication은 feature cutoff와 실제 DB 기록 시각 모두 모델의 as-of 시각
   (`start_minus_30m`이면 예정 출발 30분 전)보다 늦지 않아야 한다.
2. 한 publication은 같은 경주일만 포함하며, 해당 경주의 발행 시점 비취소 출전마를 모두
   포함해야 한다.
3. 경주별 확률합은 `P(win)=1`, `P(top2)=min(2,N)`, `P(top3)=min(3,N)`이어야 한다.
4. `P(win) ≤ P(top2) ≤ P(top3)`와 각 확률의 `[0,1]` 범위를 강제한다.
5. 정렬·정규화한 예측 payload와 모델 artifact에 각각 SHA-256을 기록한다.
6. `prediction_runs`, `model_predictions`, `prediction_settlements`,
   `prediction_outcomes`는 SQLite trigger가 `UPDATE`·`DELETE`를 거부한다.
7. 정산은 prediction publication당 한 번만 가능하다.
8. 이미 `live` 예측이 발행된 경주는 확률을 바꿔 다시 발행할 수 없다.
9. `historical` publication은 파이프라인·화면 검증용이며 사전 공개 누적 지표에서 제외한다.

## 2. 테이블

| 테이블 | 역할 |
|---|---|
| `prediction_runs` | 모델·feature cutoff·실제 발행시각·모드·두 SHA-256을 고정 |
| `model_predictions` | 경주 출전마별 win/top2/top3 확률 |
| `prediction_settlements` | 결과 snapshot hash와 publication 단위 지표 |
| `prediction_outcomes` | 출전마별 착순·라벨·win log-loss 기여도 |

정산 도중 발행 후 취소, 특수 착순코드, 착순 누락이 한 마리라도 발견되면 그 경주 전체를
제외한다. 일부 말만 제외한 뒤 확률합을 사후 보정하지 않는다. 정상 경주에 대해 win Log Loss,
Brier, ECE, Top1, Top3 포함률과 top2/top3 Log Loss를 저장한다.

## 3. 운영 명령

예정 경주에서 결과·라벨 없이 학습 때와 같은 feature를 만들고 고정 모델로 추론한 뒤
원장에 발행하는 표준 경로는 다음 한 명령이다.

```bash
uv run horse-racing predict-and-publish \
  --run-id 61336314-3615-4a87-bc3c-93a90f448c18 \
  --date 20260828
```

feature frame만 먼저 검사하려면 다음을 사용한다. 학습 run의 feature 108개와 열·순서·hash가
조금이라도 다르면 생성이 중단된다.

```bash
uv run horse-racing build-prediction-frame \
  --run-id 61336314-3615-4a87-bc3c-93a90f448c18 \
  --date 20260828
```

미래 경주에는 결과 행이 없으므로 말별 이력 끝에 착순이 null인 anchor를 붙여 학습 pipeline의
`shift(1)` 계산을 그대로 재현한다. 같은 날 결과는 이력에서 제외한다. 독립적으로 추정한
win/top2/top3 확률은 `dykstra_l2_v1` 최소 L2 projection으로 경주별 합계와
`P(win) ≤ P(top2) ≤ P(top3)`를 동시에 만족시킨다. feature frame·예측·manifest는
`data/predictions/YYYYMMDD/` 아래에 감사 산출물로 남는다.

외부에서 만든 예측 파일을 발행하는 저수준 경로도 유지한다.

예측 파일은 Parquet/CSV/TSV이며 다음 열이 필요하다.

```text
race_id, race_entry_id, horse_number, prob_win, prob_top2, prob_top3
```

```bash
# 실제 미래 경주: 명령 실행 시각이 모델 as-of 이전인지 검증됨
uv run horse-racing publish-predictions \
  --run-id 61336314-3615-4a87-bc3c-93a90f448c18 \
  --predictions-file data/predictions/2033-05-20.parquet \
  --feature-cutoff 2033-05-20T12:30:00+09:00

# 결과 수집 후 정산 가능한 publication 전체를 자동 정산
uv run horse-racing settle-predictions

uv run horse-racing list-predictions --mode live
uv run horse-racing verify-predictions --public-id UUID
```

과거 자료를 UI·정산 테스트에 넣어야 할 때만 다음처럼 명시한다.

```bash
uv run horse-racing publish-predictions \
  --run-id RUN_ID \
  --predictions-file FILE.parquet \
  --feature-cutoff 2026-06-01T12:00:00+09:00 \
  --mode historical --confirm-historical
```

조회 화면은 `/predictions`, JSON 조회는 `/api/predictions`다. 누적 headline 지표는
`live`이면서 정산된 정상 경주만 다시 모아 계산한다.

## 4. 첫 prospective 기록과 다음 운영 단계

2026-08-28 05:30:25 KST에 고정 M4 앙상블로 당일 예정 16경주·163출전의 첫 `live`
publication을 기록했다.

- public ID: `4cea003c-2c62-4503-9410-2b474015e57c`
- prediction payload SHA-256:
  `64d1ebe25e7d34ee5bd02bdf0771fd79c950fa9a774ca840eff09e93e728c5af`
- `verify-predictions`: `VERIFIED`
- 조기 예측이라 마체중 coverage가 0/163이었고, 모델의 결측 처리에 맡겼다는 사실을 note에 고정

다음 운영 단계는 각 경주 T-30분 직전 당일 체중·취소·기수변경을 다시 수집하고 경주별로
`predict-and-publish --race-id ...`를 실행하는 스케줄러다. 첫 기록은 조기 예측 표본으로
그대로 보존하며 사후에 교체하지 않는다.
