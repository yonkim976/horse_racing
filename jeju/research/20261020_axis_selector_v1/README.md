# F1_STYLE6 상위 후보 축 선택기

## 결론

동결된 F1_STYLE6 raw score 상위 3두 중 축 한 마리를 다시 고르는 선택기는 사전 주 평가 gate를 통과하지 못했다. 900·1000·1110·1200m 1,503경주에서 기존 raw score 1위는 861회 Top3에 들었고, selector 선택마는 857회였다. 차이는 −0.27%p이며 날짜 paired bootstrap 95% 구간은 [−1.08, +0.59]%p다. 개선 점추정치가 아니고 구간 하한도 0보다 크지 않아 기준선을 유지하고 selector는 연구 후보로 보류한다.

선택기는 세 평가연도에 대해 사전 고정한 expanding 학습창으로 한 번씩 적합했다. 결과 확인 후 재학습, 피처 변경, 규제 변경, threshold 탐색은 하지 않았다. F1_STYLE6 말 평가, 30개 입력, 평가기간의 raw score와 `p_top3`는 보존했으며 selector utility는 새 확률로 쓰지 않는다. Root와 별도 reviewer의 독립 재검산은 모두 **PASS**했다. 후보 utility 5,337개는 최대 절대 차이 0.0으로 재현됐고, 두 검토 모두 전체 1,779경주 축 선택과 2,000회 bootstrap을 확인했다. 세 모델의 scaler·loss·gradient·시간 provenance와 37개 source hash도 독립 대조했으며 추가 refit이나 DB 접근은 없었다. Root 검산 영수증은 [ROOT_REPLAY_REVIEW.json](../20261020_axis_selector_rootreview_v1/ROOT_REPLAY_REVIEW.json)이고, 별도 검토 결과와 그 독립 산출물 manifest는 [FIT_REVIEW.json](../20261020_axis_selector_review_v1/outputs/FIT_REVIEW.json) 및 [review FINAL_MANIFEST.json](../20261020_axis_selector_review_v1/FINAL_MANIFEST.json)에 고정되어 있다.

## 주 평가

표본은 2024-01-05~2026-09-19의 900·1000·1110·1200m 14,714출전·1,503경주다. 같은 경주에서 기존 축과 selector 축의 실제 Top3 여부를 비교했다. 차이는 selector−기존축이며 날짜를 cluster로 묶은 사전 동결 2,000회 paired bootstrap을 적용했다. 모든 2,000 draw가 유효했다.

| 축 | Top3 적중 | 비율 |
|---|---:|---:|
| 기존 raw score 1위 | 861 / 1,503 | 57.29% |
| selector 선택 | 857 / 1,503 | 57.02% |
| 차이 | −4경주 | −0.27%p |

95% paired date-cluster bootstrap 구간은 **[−1.08, +0.59]%p**다. 사전 gate는 점차이 > 0 및 95% 구간 하한 > 0을 모두 요구했으며 실패했다. 50경주(3.33%)에서 축이 바뀌었다. 새 축만 적중한 경주는 13개, 기존 축만 적중한 경주는 17개, 둘 다 적중한 경주는 844개, 둘 다 놓친 경주는 629개였다.

## 전체 거리·연도·거리별 결과

전체 거리 1,779경주에서는 기존 축이 1,023회(57.50%), selector가 1,016회(57.11%) Top3에 들어 차이는 −0.39%p였다. 전체 표본에서 58경주 축이 바뀌었고 selector만 적중한 경우 14회, 기존 축만 적중한 경우 21회였다. 주 평가와 다른 결과만 골라 채택 근거로 삼지 않는다.

| 평가연도 | 경주 | 기존 축 | selector | 차이 | 바뀐 축 | 새 적중 / 기존만 적중 |
|---:|---:|---:|---:|---:|---:|---:|
| 2024 | 499 | 54.91% | 54.91% | 0.00%p | 20 | 6 / 6 |
| 2025 | 559 | 58.68% | 57.78% | −0.89%p | 25 | 5 / 10 |
| 2026¹ | 445 | 58.20% | 58.43% | +0.22%p | 5 | 2 / 1 |

| 거리 | 경주 | 기존 축 | selector | 차이 | 바뀐 축 | 새 적중 / 기존만 적중 |
|---:|---:|---:|---:|---:|---:|---:|
| 900m | 251 | 60.56% | 60.16% | −0.40%p | 5 | 0 / 1 |
| 1000m | 508 | 57.87% | 57.09% | −0.79%p | 24 | 3 / 7 |
| 1110m | 482 | 54.15% | 53.53% | −0.62%p | 13 | 4 / 7 |
| 1200m | 262 | 58.78% | 60.31% | +1.53%p | 8 | 6 / 2 |

¹ 2026년은 9월 19일까지의 부분연도다. 연도별·거리별 수치는 보조 탐색이며 primary gate를 대신하지 않는다.

## 경력별 진단과 후보 coverage

경력 구간은 baseline 축의 `observed_starts`로 정의했다. 0회 경력 구간은 4경주뿐이다. 아래 값은 표본이 작은 하위집단 분석이며 확정적인 비교가 아니다.

| 기존 축 `observed_starts` | 경주 | 기존 축 적중 | selector 적중 | 차이 | 바뀐 축 | 새 적중 / 기존만 적중 |
|---:|---:|---:|---:|---:|---:|---:|
| 0 | 4 | 2 | 2 | 0.00%p | 0 | 0 / 0 |
| 1–4 | 525 | 345 | 344 | −0.19%p | 3 | 0 / 1 |
| 5+ | 974 | 514 | 511 | −0.31%p | 47 | 13 / 16 |

별도 K=5 selector는 만들지 않았다. 기존 raw score 상위 5두 안에 실제 Top3 말이 하나 이상 포함된 비율은 주 평가에서 1,477/1,503(98.27%), 전체 거리에서 1,750/1,779(98.37%)였다. 이는 후보 coverage 진단이며 축 선택기 성능이나 배당 수익을 뜻하지 않는다.

## 설계와 시간 경계

기존 F1_STYLE6를 그대로 둔 채 후보 3두만 비교하는 별도 pairwise logistic 순위 모형이다. 학습은 라벨 연도별 다음 fold의 calibration raw score로 2019–2025 자료를 연결했고, 평가에는 해당 연도 frozen evaluation raw score를 사용했다. expanding 학습창은 아래와 같으며 평가연도 결과를 같은 연도 selector fit에 넣지 않았다.

| 평가연도 | 학습 라벨 연도 | 전체 학습 출전/경주 | 후보 학습행 | 혼합 정답 경주 `R_mix` | 유효 pair | 마지막 학습 라벨일 |
|---:|---|---:|---:|---:|---:|---|
| 2024 | 2019–2023 | 25,278 / 2,492 | 7,476 | 2,106 | 4,212 | 2023-12-30 |
| 2025 | 2019–2024 | 31,607 / 3,129 | 9,387 | 2,645 | 5,290 | 2024-12-28 |
| 2026 | 2019–2025 | 38,017 / 3,783 | 11,349 | 3,205 | 6,410 | 2025-12-27 |

각 경주에서 전체 raw score를 내림차순, 낮은 마번 순으로 정렬해 K=3 후보를 고정했다. selector의 고정 11열 basis는 전체경주 raw score 순위·z값, 동결 이력의 출전수·최근성·동일거리 support·편성 대비 평균기록 순위 및 지정 결측표시다. 후보행만으로 표준화하고 경주마다 같은 가중치를 둔 pairwise logistic loss에 `λ=1.0` L2 규제를 적용했다. 전체 basis와 단일 최적화 조건은 [PLAN.md](PLAN.md)에 동결되어 있다.

과거 OOS 점수 공급자는 해당 라벨연도를 학습하지 않은 다음 연도 F1_STYLE6의 calibration raw score다. 2024·2025·2026 평가는 저장된 해당 연도 F1_STYLE6의 evaluation raw score와 baseline `p_top3`를 그대로 쓴다. `p_top3`, favorite·odds, 식별자, 라벨, 경주 후 정보는 선택기 입력이 아니다. source preflight는 features 52,155행·5,206경주, baseline 17,412행·1,779경주·269일, 주 코호트 1,503경주, 경주일−2일 이력 cutoff, full roster 및 시간 경계를 검증했다. 제외마 ID `3005648`은 없고 odds/favorite 입력도 없다. 최종 적합 후에도 잠금된 37개 입력과 세 계획 artifact의 SHA-256을 다시 대조했고 source hash가 바뀌지 않았다.

2024–2026은 이미 반복 분석한 개발기간이지 새로운 미래 holdout이 아니다. 학습과 평가의 F1_STYLE6 raw score는 서로 다른 모델 vintage다. bootstrap 구간은 세 selector를 고정한 날짜 표본의 변동이며 학습 불확실성을 포함하지 않는다. 이 자료는 당시 실제 공개 시각을 증명하지 않는다.

## 재현 파일

- [PLAN.md](PLAN.md): 결과 확인 전 고정한 basis, loss, 표준화, 시간창 및 성공 기준.
- [SOURCE_AUDIT.md](SOURCE_AUDIT.md): source/OOF 감사.
- [preflight.py](preflight.py): 모델 적합이나 성과 계산 없는 source 계약 검증.
- [fit_selector.py](fit_selector.py): 승인된 뒤 정확히 세 expanding selector를 적합하고 사전 지정 비교를 계산하는 코드.
- [SOURCE_LOCK.json](outputs/SOURCE_LOCK.json) / [PREFLIGHT.json](outputs/PREFLIGHT.json): 고정 source hashes / source-only PASS 영수증.
- [ROOT_FIT_APPROVAL.json](outputs/ROOT_FIT_APPROVAL.json) / [FIT_RECEIPT.json](outputs/FIT_RECEIPT.json): 승인과 세 번의 fit·고정 평가 완료 영수증.
- [REPORT.json](outputs/REPORT.json) / [bootstrap_draws.parquet](outputs/bootstrap_draws.parquet): 집계 결과와 paired date bootstrap 반복.
- [race_choices.parquet](outputs/race_choices.parquet) / [candidate_predictions.parquet](outputs/candidate_predictions.parquet): 경주별 기존/새 축 선택 및 후보 점수 ledger.
- `outputs/model_2024.json`, `model_2025.json`, `model_2026.json`: 계수, 표준화, optimizer 진단, 학습 경계, provider provenance 및 source hashes.
- [FINAL_MANIFEST.json](outputs/FINAL_MANIFEST.json): 최종 산출물, 해시 목록과 두 독립 재검산 자료.
