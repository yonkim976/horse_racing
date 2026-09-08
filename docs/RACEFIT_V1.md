# RaceFit V1 — 조건 적합도와 에너지 배분 순위모델

## 결론

RaceFit V1의 첫 운영 후보는 **과거 구간기록의 에너지 배분을 추가한 LambdaRank**다.
잠재 컨디션 합성치와 3개 페이스 시나리오 혼합은 구현했지만 장기 walk-forward에서 기본
후보를 이기지 못했으므로 challenger로만 보존한다.

이 판정은 수익성 주장이 아니다. 확정배당을 사용한 과거 ROI 최적화는 하지 않으며, 실제
베팅 가치는 구매 시점 배당 snapshot과 미래 예측 원장으로 별도 검증해야 한다.

## 1. 모델 구조

### 운영 후보: `racefit_v1_core`

기존 `ability_v2_core`의 114개 누수 방지 feature에 다음 9개를 추가한다.

- 최근 5경주 S1F, G3F, G1F 경주 내 상대시간
- G1F−G3F 막판 상대개선
- G1F−S1F 초·후반 균형
- S1F+G1F 초반 사용 후 종반 유지력
- 막판 상대개선 추세
- 동일거리 초·후반 균형
- 유효 에너지 프로필 표본 수

최종 입력은 123개다. 배당, 공식 레이팅, 레이팅 대리변수, 과적합이 확인된 조합 문자열과
실험용 잠재 컨디션 합성치는 프로필 계약으로 제외한다.

### 에너지 기록 보정 계약

원시 S1F/G3F/G1F 값은 연도별 수집 의미가 달라 그대로 비교하지 않는다. 각 구간시간은 먼저
같은 경주의 중앙값에 대한 로그 상대지수로 변환한다.

```text
relative_section = 100 × log(race_median_time / horse_time)
```

그 뒤 말별로 현재 경주를 `shift(1)`해 제외하고 최근 최대 5경주만 집계한다. 현재 경주의
구간기록을 바꿔도 해당 경주의 feature가 변하지 않는 회귀 테스트를 둔다.

### 실험 challenger

`RaceFitModelBundle`은 기본 rank score에 다음 상호작용을 더하고 느림·중립·빠름 3개 페이스의
Plackett–Luce 주변확률을 혼합한다.

- 선행 압력 × 초반/종반 유지력
- 추입 성향 × 선행마 비중 × 막판 개선
- 게이트 × 선행 성향 × 선행 경합
- 부담중량 × 거리
- 함수율 × 막판 개선
- 거리 × 초·후반 에너지 균형
- 현재 컨디션과 관측 불확실성

이 모델은 1·2·3착의 일관된 주변확률과 ordered top-3 확률을 출력하지만, 현재 성능상 운영
후보로 선택하지 않는다.

## 2. 데이터와 평가

- 데이터셋: `racefit_v1_history/day_before_18`
- 전체: 2016~2026, 25,926경주, 272,904두-경주 행
- 모델 선택용 walk-forward: 2022~2025, 9,778경주, 101,744행
- 각 연도는 그 연도 이전 데이터만 학습
- 비교 대상: 동일 코드와 seed의 `ability_v5_speed_history/ability_v2_core`
- 사용하지 않은 정보: 배당, 현재 경주 결과·구간기록, 미래 경주의 성적

## 3. 결과

| 모델 | win log loss | AUC | Top1 | 우승마 Top3 |
|---|---:|---:|---:|---:|
| V5 동일코드 기준 | 0.273689 | 0.767820 | 31.1925% | 62.5997% |
| **RaceFit 에너지 운영 후보** | **0.272906** | **0.769632** | **31.4584%** | **63.0395%** |
| 컨디션+3페이스 시나리오 | 0.274025 | 0.767981 | 31.1925% | 62.6611% |

RaceFit 에너지 후보의 V5 대비 변화는 다음과 같다.

- win log loss: **−0.000783** (낮을수록 좋음)
- AUC: **+0.001812**
- Top1: **+0.266%p**
- 우승마 Top3 포함: **+0.440%p**

경주 단위 paired bootstrap 5,000회의 V5 대비 개선 구간은 다음과 같다.

- log loss 개선: 중앙값 +0.000784, 95% CI **[+0.000491, +0.001078]**,
  `P(개선>0)=1.000`
- Top1 변화: 중앙값 +0.256%p, 95% CI **[-0.174, +0.706]%p**
- Top3 변화: 중앙값 +0.450%p, 95% CI **[0.000, +0.880]%p**

즉 확률 품질 개선은 표본 내에서 일관되지만, Top1 적중률 상승 폭은 아직 불확실하다.
사용자가 목표로 둔 Top1 50%, Top3 90%와는 큰 차이가 있으며 이 모델을 그 수준의 확정
예측으로 표현해서는 안 된다.

최근 valid 블록의 운영 후보 성능은 win log loss 0.2645, AUC 0.7915, Top1 34.68%, 우승마
Top3 포함 66.67%다. 이는 모델 선택에 사용된 valid 결과이며 새로운 test나 실전 성적이 아니다.

## 4. 산출물과 재현

- 운영 후보 artifact run: `7dde1d6e-b288-4b76-8fe3-e5191e0f83b9`
- 운영 후보 walk-forward run: `00171147-b1f5-4e4f-980d-4e488421b558`
- 시나리오 walk-forward run: `606b19ca-89e3-4995-a5ce-d8165e33462d`

```bash
horse-racing build-dataset \
  --version racefit_v1_history \
  --as-of day_before_18 \
  --feature-set racefit_history

horse-racing run-walk-forward \
  --version racefit_v1_history \
  --as-of day_before_18 \
  --years 2022 2023 2024 2025 \
  --profile racefit_v1_core \
  --model ranking

horse-racing train-ranking \
  --version racefit_v1_history \
  --as-of day_before_18 \
  --profile racefit_v1_core \
  --calibration-objective winner
```

## 5. 다음 검증

1. 잠재 컨디션은 수동 가중합 대신 horse별 동적 상태공간 모델로 다시 설계한다.
2. 페이스 시나리오는 대칭 혼합이 아니라 관측 가능한 선행 경쟁으로 시나리오 확률 자체를
   학습한다.
3. 출발 전 예측을 불변 원장에 저장해 신규 미래 표본에서 calibration과 Top1/Top3를 확인한다.
4. 삼연승 4두 박스/선택 조합은 구매 시점 배당이 확보된 뒤 ordered probability와 비교한다.
5. ROI는 충분한 미래 표본과 경주 단위 bootstrap 구간으로만 판정한다.
