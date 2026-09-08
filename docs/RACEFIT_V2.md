# RaceFit V2 — 동적 상태·학습형 페이스·당일 편향 검증

## 결론

세 개선축을 분리 검증한 결과 **당일 앞 경주 편향만 운영 challenger로 채택**했다.

- 동적 Kalman 컨디션: 장기 win log loss 악화 → 제외
- 학습형 S1F 페이스 → LambdaRank: win log loss 악화 → 제외
- 예측시각 이전 당일 선행·내측 편향: 2026 연도 분리에서 개선 → V2 후보 채택

V2는 `start_minus_30m` 전용이다. 전일 18시 예측에서는 같은 날 앞 경주가 존재하지 않으므로
V1 에너지 모델을 계속 사용한다.

## 1. 시간 계약

당일 편향에 사용할 수 있는 과거 결과의 조건은 다음과 같다.

```text
prior_race.scheduled_at + 20분 <= target.prediction_at
```

같은 날짜·같은 경마장의 경주만 후보로 삼고, 현재 경주와 이후 경주는 제외한다. 20분은
결과·구간자료 공개 지연을 위한 보수적 buffer다. 실제 지연이 20분보다 긴 경주는 완전히
차단하지 못할 수 있으므로 미래 원장에서 이 가정을 계속 감사해야 한다.

당일 편향 feature는 다음 8개다.

- 사용 가능한 앞 경주 수와 수축 신뢰도 `n/(n+3)`
- 과거 동일 경마장·거리 par 대비 당일 top3 속도 편차
- 앞 경주 top3 S1F로 계산한 선행 편향
- 앞 경주 top3 게이트로 계산한 내측 편향
- 선행 편향 × 해당 말의 과거 주행 스타일
- 내측 편향 × 해당 말의 상대 게이트
- 선행 편향 × 해당 말의 초후반 에너지 균형

현재 경주의 착순·구간시간을 바꿔도 현재 feature가 변하지 않는 회귀 테스트를 둔다.

## 2. 탈락한 개선축

### 2상태 Kalman 컨디션

보정 속도관측을 느린 장기 능력과 60일 반감기의 단기 컨디션으로 분리했다. 같은 날짜의
관측은 target feature를 출력한 뒤 갱신한다. 2022~2025 9,778경주에서 결과는 다음과 같다.

| 구성 | win log loss | AUC | Top1 | Top3 |
|---|---:|---:|---:|---:|
| 동적 상태 제외 | **0.272992** | **0.769650** | 31.28% | **62.88%** |
| 동적 상태 포함 | 0.273356 | 0.768399 | **31.33%** | 62.71% |

2024년 악화가 커서 운영 프로필에서는 제외했다. 구현은 추후 상태 방정식·관측오차 재추정을
위해 feature set에 보존한다.

### 학습형 페이스

첫 단계 LightGBM이 S1F 위치 백분위를 expanding cross-fit으로 예측하고, 두 번째 LambdaRank가
예측 초반 위치·선행마 수·경합 압력·에너지 상호작용만 사용한다. 실제 S1F 라벨은 결과모델에
직접 들어가지 않는다.

- 2022~2025 pace MAE: 약 0.20
- win log loss: 0.273520
- Top1: 31.15%
- Top3: 62.97%

Top3는 기준보다 약간 높지만 win 확률과 Top1이 악화되어 조합확률 challenger로만 남긴다.

## 3. 채택 후보 결과

데이터셋은 `racefit_v2_rich/start_minus_30m`이며, 출발시각이 있는 2025-01-03~2026-08-29
4,130경주다. 당일 앞 경주 feature는 3,496경주(84.78%)에 존재하고, 행별 평균 사용 경주는
3.76개, 최대 12개다.

2025년만 학습하고 2026년 1,657경주를 평가했다.

| 구성 | win LL | AUC | Top1 | 우승마 Top3 | top2 LL | top3 LL |
|---|---:|---:|---:|---:|---:|---:|
| 당일 편향 제외 | 0.273379 | 0.776091 | 31.44% | 64.15% | 0.4245 | 0.5332 |
| **당일 편향 포함** | **0.270011** | **0.784525** | **33.19%** | **65.78%** | **0.4207** | **0.5306** |

경주 단위 paired bootstrap 5,000회 결과:

- win log loss 개선: +0.003368, 95% CI **[+0.001766,+0.004977]**,
  `P(개선>0)=1.000`
- Top1: +1.750%p, 95% CI **[+0.240,+3.319]%p**, `P(개선>0)=0.985`
- Top3: +1.629%p, 95% CI **[+0.059,+3.259]%p**, `P(개선>0)=0.975`

다만 2026년 결과를 V2 선택에 사용했으므로 이는 새로운 untouched test가 아니다. 운영 승격은
2026년 9월 이후 불변 예측 원장의 미래 경주로 다시 판정한다.

## 4. 산출물

- V2 artifact run: `e853238b-ded1-428b-9f4c-b260c77294b8`
- V2 2026 walk-forward run: `49706438-0c9b-41d8-814e-89e386c50335`
- paired 기준 run: `320847a7-bd3c-4fc8-8806-44092fd35c81`
- 동적 상태 실험 run: `706ce6b2-4dee-41fe-8eda-16b170ccd5dc`

```bash
horse-racing build-dataset \
  --version racefit_v2_rich \
  --as-of start_minus_30m \
  --feature-set racefit_v2_rich

horse-racing run-walk-forward \
  --version racefit_v2_rich \
  --as-of start_minus_30m \
  --years 2026 \
  --profile racefit_v2_core \
  --model ranking

horse-racing train-ranking \
  --version racefit_v2_rich \
  --as-of start_minus_30m \
  --profile racefit_v2_core \
  --calibration-objective winner
```

## 5. 운영 판정

- `day_before_18`: RaceFit V1 에너지 모델 유지
- `start_minus_30m`: RaceFit V2 당일 편향 모델을 challenger로 발행
- 실제 베팅 및 ROI 판단: 아직 금지. 구매시점 배당과 미래 원장 표본이 필요
- 다음 승격 조건: 미래 최소 500경주, LL 개선 CI 하한>0, calibration 악화 없음
