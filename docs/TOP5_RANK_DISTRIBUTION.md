# Top5 말별 순위확률 모델

## 목적

한 경주의 각 말에 대해 다음 두 종류의 확률을 동시에 만든다.

- 정확한 순위 확률: `prob_rank1` … `prob_rank5`
- 누적 입상 확률: `prob_win`, `prob_top2` … `prob_top5`

각 경주에서 정확한 순위별 확률 합은 1이고, 한 말의 누적확률은
`P(1위) ≤ P(2위 이내) ≤ … ≤ P(5위 이내)`를 만족한다. 출전마가 K두보다 적으면
존재하지 않는 순위 확률은 0이다.

## 구현

- LambdaRank relevance: 1착=5, 2착=4, 3착=3, 4착=2, 5착=1, 그 외=0
- 확률 계층: Plackett–Luce
- 확률 보정: 학습기간 말미 calibration block의 ordered-top5 NLL로 temperature β 선택
- Top5 주변확률: 순열 전체를 열거하지 않고 선택된 말의 부분집합을 상태로 하는 정확한 DP
- 동착: 공식 착순과 일치하는 모든 유효 순서를 주변화
- 검증: 과거만 학습하고 다음 연도를 평가하는 expanding-window walk-forward

## 실제 성능

데이터는 `racefit_v1_history/day_before_18`, feature는 `racefit_v1_core` 123개를 사용했다.

### 2022–2025 walk-forward

| 항목 | 결과 |
|---|---:|
| 경주 / 출전행 | 9,778 / 101,744 |
| win log loss / AUC / ECE | 0.275803 / 0.769160 / 0.017604 |
| Top1 / 우승마 Top3 포함 | 31.2436% / 62.8554% |
| Top2 log loss / AUC | 0.4255 / 0.7511 |
| Top3 log loss / AUC | 0.5226 / 0.7410 |
| Top4 log loss / AUC | 0.5840 / 0.7310 |
| Top5 log loss / AUC | 0.6121 / 0.7244 |
| truncated Top5 RPS | 0.159579 |
| 실제 순위 버킷 NLL | 1.363421 |

기존 승리 중심 RaceFit V1 LambdaRank는 같은 9,778경주에서 win log loss 0.272906,
Top1 31.4584%, 우승마 Top3 포함 63.0395%였다. Top5 모델은 이 세 지표가 소폭
악화됐지만 Top3 누적확률 log loss는 0.5275에서 0.5226으로 개선됐다. 따라서 현재 판정은
**단승 운영모델을 교체하지 않고, 1–5위 분포와 복합 승식용 challenger로 유지**다.

### 2026-03-01~2026-05-31 valid

- win: log loss 0.2704, AUC 0.7901, Top1 33.03%, 우승마 Top3 포함 66.22%
- Top2/3/4/5 log loss: 0.4106 / 0.5073 / 0.5621 / 0.5829
- truncated Top5 RPS 0.152942, 실제 순위 버킷 NLL 1.332099

## 실제 착순 비교 산출물

`rank_comparison*.parquet`은 말별로 다음 값을 한 행에 둔다.

- 경주·말 식별자와 `finish_position`
- `prob_rank1` … `prob_rank5`
- `prob_win`, `prob_top2` … `prob_top5`
- 실제 누적 결과 `win`, `top2` … `top5`
- `actual_rank_bucket`: 1~5, 6위 이하는 6
- `expected_rank_bucket`: 6위 이하를 6으로 묶은 예측 기댓값
- `prob_actual_rank_bucket`: 실제 순위 버킷에 모델이 부여한 확률

주요 산출물:

- valid 모델: `data/experiments/models/090408f4-4893-4d19-b5dc-0f445ebc7ecc/`
- valid 비교: 위 디렉터리의 `rank_comparison_valid.parquet`
- walk-forward: `data/experiments/walk_forward/0844303c-8bb4-4438-b46f-70844eeb5540/`
- walk-forward 비교: 위 디렉터리의 `rank_comparison.parquet`

## 재현

```bash
horse-racing train-ranking \
  --version racefit_v1_history --as-of day_before_18 \
  --profile racefit_v1_core \
  --calibration-objective full_top5 --relevance-depth 5

horse-racing run-walk-forward \
  --model top5_ranking \
  --version racefit_v1_history --as-of day_before_18 \
  --profile racefit_v1_core --years 2022 2023 2024 2025
```

이 평가는 모델 개발용 과거 시뮬레이션이다. 신규 미래 데이터의 사전 확률을 고정하는 공개
원장 검증을 대체하지 않는다.
