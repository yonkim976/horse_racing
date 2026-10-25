# Top5 직접 선택기 독립검토

## 범위

이 폴더는 `20261025_top5_direct_learning_v1`의 수학·입력 식별성·fit/선택/결과 코드를 별도로 검토하고, 잠금된 선택과 승인된 결과를 독립 재계산한 기록이다. 모든 검토 파일은 이 폴더에만 저장했다. 주 연구의 모델, 선택기, DB, registry 및 원천 parquet는 수정하지 않았다.

학습 objective는 정답 Top3 세 마리가 들어가는 모든 정확히 5마리 set의 Gibbs mass를 키우는 partial-event NLL이다. 이는 실제 deterministic argmax의 coverage 확률이나 보정확률이 아니다. additive runner head의 deterministic argmax, single-start 비볼록 fit, local optimum와 feature 공선성 한계를 결과와 함께 해석해야 한다.

## 독립 검산

- 고정 score/feature 원천과 hash-locked root 승인을 확인했다. 선택 검산은 `y`, finish rank, outcome 지표를 읽지 않았다.
- 선택 replay는 전 1,779경주에서 411,084개 5두 조합을 직접 비교해 저장된 말 ID·마번·에너지·조합 수를 모두 재현했다. Primary는 1,503경주다.
- β=0 raw-score Top5 identity, 입력 행 역순 변경에도 같은 결과, additive runner utility Top5 identity가 각각 1,779/1,779 통과했다. 저장된 raw score와 frozen evaluation score는 2024–2026 모두 완전 일치했다.
- 결과 단계는 root outcome approval, 선택/fit/report hash와 output receipt를 먼저 확인한 뒤 고정 outcome allowlist의 이진 `y`만 사용했다. 모든 1,779 race ledger 행, summary, 연도·거리 하위집단, caught/lost, 0/1/2/3 captured/missed 분포 및 bootstrap 값을 main report와 독립 대조해 일치했다.

## 결과

| 모집단 | Selector | Raw-score Top5 | 차이 | Caught / lost |
|---|---:|---:|---:|---:|
| Primary (1,503경주) | 435/1,503 (28.9421%) | 439/1,503 (29.2083%) | −0.2661%p | 31 / 35 |
| Full (1,779경주) | 520/1,779 (29.2299%) | 519/1,779 (29.1737%) | +0.0562%p | 38 / 37 |

Primary의 고정 2,000회 race-date cluster bootstrap(269일, NumPy linear quantiles) 95% CI는 rate 단위 `[-0.0134334, 0.0077527]`, 즉 약 `[-1.3433, +0.7753]`%p다. 사전 성공 gate(Primary 차이 `> 0` 및 CI 하한 `> 0`)는 충족되지 않았다. 이 표본은 반복 사용된 과거 개발 기간이며 독립 미래 holdout이 아니다.

## 산출물

- `INDEPENDENT_DESIGN_REVIEW.md`: objective·gradient·해석 한계 검토
- `FEATURE_SUPPORT_IDENTIFIABILITY_AUDIT.json`: train-only feature 지원·식별성 감사
- `FIT_CODE_REVIEW.md`, `STAGE_CODE_REVIEW.md`: 최종 소스 hash에 대한 코드 검토와 replay 결과
- `verify_locked_choices.py`, `REPLAYED_LOCKED_CHOICES.jsonl`, `REPLAYED_CHOICES_RECEIPT.json`: label-free 선택 검산
- `verify_locked_outcomes.py`, `REPLAYED_LOCKED_RACE_OUTCOMES.jsonl`, `REPLAYED_OUTCOME_METRICS.json`, `REPLAYED_OUTCOME_RECEIPT.json`: 승인 후 독립 결과 검산
- `FINAL_REVIEW_MANIFEST.json`: 주요 source·approval·output·review artifact SHA-256 및 검산 상태
