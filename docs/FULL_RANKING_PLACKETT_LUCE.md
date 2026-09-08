# Full Plackett–Luce 순위확률 실험

기준일: 2026-09-01

## 구현 범위

LightGBM LambdaRank의 말별 점수를 경주 단위 Plackett–Luce 분포로 변환한다. 모든 서로 다른
1·2·3착 순서를 열거하고 이를 주변화해 다음 확률을 한 분포에서 동시에 만든다.

- `prob_win = P(1착)`
- `prob_top2 = P(1착 또는 2착)`
- `prob_top3 = P(1착, 2착 또는 3착)`
- 말이 3두 이상인 정상 경주는 각 확률합이 각각 1, 2, 3이다.
- 공동착순은 임의 순서를 고르지 않고 공식 결과와 일치하는 모든 순서의 확률을 합한다.
- `full_top3` 온도는 학습 말미 calibration 구간의 ordered-top3 경주 NLL로만 선택한다.

이 단계는 LambdaRank 자체를 Plackett–Luce 우도로 다시 학습한 것이 아니라, 기존 rank score에
정합적인 순위분포와 full-top3 온도 보정을 붙인 challenger다.

## 고정 valid 비교

데이터셋은 `ability_v5_speed_history/day_before_18`, profile은 `ability_v2_core`, seed는 42다.
미래 test split은 평가하지 않았다.

| 지표 | winner 보정 | full_top3 보정 | 변화 |
|---|---:|---:|---:|
| win log loss | 0.2647 | 0.2667 | +0.0020 (악화) |
| top2 log loss | 0.4035 | 0.4053 | +0.0018 (악화) |
| top3 log loss | 0.5070 | 0.5046 | -0.0024 (개선) |
| ordered-top3 race NLL | 5.743887 | 5.735622 | -0.008265 (개선) |
| win ECE | 0.0088 | 0.0160 | 악화 |
| top2 ECE | 0.0128 | 0.0244 | 악화 |
| top3 ECE | 0.0212 | 0.0155 | 개선 |
| Top1 | 34.53% | 34.53% | 동일 |
| 우승마 Top3 포함 | 67.56% | 67.56% | 동일 |

- winner run: `ae293968-c220-493c-aee8-28005437ae6c`
- full_top3 run: `501535ea-57b9-4d72-a66b-c93e4569a324`

## 2022–2025 expanding walk-forward 비교

각 fold는 해당 평가연도 이전 자료만 학습했다. 총 9,778경주, 101,744출전이다.

| 지표 | winner 보정 | full_top3 보정 | 변화 |
|---|---:|---:|---:|
| win log loss | 0.273689 | 0.274395 | +0.000706 (악화) |
| top2 log loss | 0.4268 | 0.4253 | -0.0015 (개선) |
| top3 log loss | 0.5289 | 0.5243 | -0.0046 (개선) |
| win ECE | 0.0030 | 0.0103 | 악화 |
| top2 ECE | 0.0144 | 0.0076 | 개선 |
| top3 ECE | 0.0271 | 0.0097 | 개선 |
| Top1 | 31.19% | 31.19% | 동일 |
| 우승마 Top3 포함 | 62.60% | 62.60% | 동일 |

- winner run: `b8225f44-9e35-4061-938e-e238c8938c5c`
- full_top3 run: `5455b471-440f-478e-8dc1-b826318f674b`

## 판정

`full_top3`는 말의 순서를 바꾸지 않으므로 Top1·Top3 적중률을 높이지 않는다. 대신 장기
워크포워드에서 top2/top3 확률과 특히 top3 calibration을 개선했다. 따라서 현재 단승 확률의
기본 모델을 교체하지 않고, 상위 4두의 24개 ordered-top3 조합확률과 삼연승 EV를 계산하는
challenger로 사용한다. 실제 수익성 판정은 구매 가능한 시점의 배당과 미래 원장 표본이 필요하다.

새 full_top3 artifact의 상위 4두·24개 ordered-top3 확정배당 사후진단에서는 EV>0 조합
6,947건/612경주의 ROI가 **-0.87%**, 경주 bootstrap 95% 구간은 **-38.65%~+42.87%**였다.
EV 임계값을 사후에 높이면 표시 ROI가 상승하지만 신뢰구간은 모두 0을 넓게 포함한다. 따라서
이 결과는 확신 베팅이나 양(+) 수익성을 지지하지 않는다. 진단 run은
`0de8dc05-6e1f-475e-91f0-1162c5cae146`이다.

순위 적중률 자체를 더 높이려면 다음 실험은 온도 보정이 아니라 latent rank score 학습을 바꿔야
한다. 우선순위는 시간순 OOF score stacking, 실제 Plackett–Luce listwise loss 학습, 경마장·거리별
부분 풀링이며 같은 walk-forward 기준으로 비교한다.

## 재현 명령

```bash
uv run horse-racing train-ranking \
  --version ability_v5_speed_history \
  --as-of day_before_18 \
  --profile ability_v2_core \
  --calibration-objective full_top3

uv run horse-racing run-walk-forward \
  --version ability_v5_speed_history \
  --as-of day_before_18 \
  --profile ability_v2_core \
  --model full_ranking \
  --years 2022 2023 2024 2025
```
