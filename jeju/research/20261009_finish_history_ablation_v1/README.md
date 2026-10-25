# 직전 착순·최근 동일거리 입상 이력 비교

**감독 판정:** F1은 R1 대비 사전 고정한 손실 gate를 통과해 다음 연구의 연구 유지후보다. F2는 F1 대비 순차 gate에 실패해 추가 입력 후보로 채택을 보류한다. 모든 평가는 반복 사용된 과거 표본의 후향 개발 비교다. 독립 미래검증이나 운영 승격이 아니다. 운영 모델·등록부는 변경하지 않았다.

## 비교와 결과

고정된 R1은 21열(J0 13+상대능력 8), F1은 직전 완결경주의 상대착순 `(착순−1)/(실제 출전자 수−1)`·말의 직전 Top3 여부·직전 경주 완결상태를 더한 24열, F2는 최근 최대5회 정확한 동일거리 실제출전 창의 정상착순 Top3율·실제 슬롯 수·정상 결과 수를 더한 27열이다. 상대착순은 직전 경주 착순이 정상적으로 완결되고 실제 출전자가 2두 이상일 때만 계산한다. Top3 여부는 해당 말의 정상 착순 1..N이 직접 확인될 때만 0/1이며, 다른 말의 비정상 결과로 경주 전체가 불완결이어도 개별 결과는 보존한다. 직전 결과상태는 경주 전체 기준 `normal`, `non_normal_or_incomplete`, `unobserved`다. 비정상 결과는 최하위 수로 대체하지 않고 슬롯과 NULL로 보존했다. 같은거리 Top3율은 정상 개별 착순만 분모로 사용하며 정상 결과 0개면 NULL이다. F2율은 이전 조건탐색에서 쓴 실제 출전 전체 분모 Top3율과 정의가 다르다. 당일 결과·중량·기수·게이트·계절 입력은 추가하지 않았다.

데이터는 2017-01-13~2026-09-19이고, 과거 이력은 한국 경주일 기준 T−2 날짜까지 연결했다(사전 이력 warm-up 포함). 2024~2026 평가에는 17,412출전·1,779경주·269일이 있다. 각 평가연도 Y에서 초기학습은 2017~Y−3, early-stop은 Y−2, 해당 iteration까지 refit은 Y−2까지, calibration은 Y−1, test는 Y다. 따라서 2026 모형은 2017~2024 학습/refit, 2025 calibration, 2026-01-02~2026-09-19 test다. 주 손실은 경주별 말 손실 평균 후 경주를 균등 가중했다. 신뢰구간은 2,000회 경주일 paired bootstrap, seed 20261008, 95% 점별 구간이다. 아래 차이는 왼쪽 모형−오른쪽 모형으로 음수면 손실 감소다.

| 모형 | 경주 log-loss | 경주 Brier | Top3 capture | Top5 capture | Top5에 실제 Top3 3두 모두 | 최대6 조합 적중 |
|---|---:|---:|---:|---:|---:|---:|
| R1 | 0.580507 | 0.197053 | 45.92% | 65.60% | 23.89% | 19.90% |
| F1 | 0.569469 | 0.192724 | 47.72% | 69.07% | 29.12% | 22.32% |
| F2 | 0.569168 | 0.192549 | 48.30% | 69.01% | 28.89% | 23.16% |

| 사전 고정 비교 | log-loss 차이 (95% 구간) | Brier 차이 (95% 구간) | gate |
|---|---:|---:|---|
| F1−R1 | −0.011039 (−0.013410, −0.008771) | −0.004328 (−0.005341, −0.003378) | 두 손실이 모두 낮고 구간도 음수: **통과** |
| F2−F1 | −0.000301 (−0.000729, +0.000139) | −0.000175 (−0.000361, +0.000013) | 두 점추정은 낮지만 두 구간 모두 0 포함: **실패** |
| F2−R1 | −0.011339 (−0.013743, −0.009021) | −0.004504 (−0.005511, −0.003535) | 보조 비교만; F2 순차 gate 대체 불가 |

F1은 R1보다 상위5두에 Top3 전원 포함률이 +5.23%p (95% 구간 +3.05~+7.30%p), 최대6 조합 적중이 +2.42%p (+0.72~+4.17%p)였다. F2−F1은 Top3 capture +0.58%p (+0.19~+0.98%p), 최대6 조합 적중 +0.84%p (+0.11~+1.63%p)였지만 손실 gate에는 실패했다. 손실 후보판정과 조합 결과는 별도로 해석했다.

연도별 경주 log-loss/Brier는 아래와 같다. 2026은 부분 연도 후향 평가이며 독립 미래검증이 아니다.

| 연도 (경주) | R1 | F1 | F2 |
|---|---:|---:|---:|
| 2024 (637) | 0.577827 / 0.195576 | 0.568598 / 0.191952 | 0.568161 / 0.191739 |
| 2025 (654) | 0.580207 / 0.196941 | 0.567216 / 0.191741 | 0.566629 / 0.191458 |
| 2026 (488) | 0.584409 / 0.199130 | 0.573624 / 0.195050 | 0.573884 / 0.195068 |

2026에서는 F2가 F1보다 log-loss +0.000260, Brier +0.000018로 소폭 나빴다. 연도·거리·경력 및 상태 하위군, runner-level paired 결과와 보정 구간은 산출물 표를 참조한다. 직전 Top3가 정상 착순으로 직접 관측된 하위군(5,315출전)의 실제 입상률은 43.87%였다. 잔차를 `실제−예측`으로 두면 R1 +6.58%p, F1 +1.24%p, F2 +1.19%p다. 직전 Top3가 아닌 하위군(11,433출전)의 실제 입상률은 24.68%이고 잔차는 R1 −3.18%p, F1 −0.66%p, F2 −0.63%p다. 이는 조건부 잔차 기술통계이며 이 비율을 입력으로 넣지 않았다. 상단 보정 bin은 표본이 작아 단정하지 않았다.

최근 동일거리 실제출전 슬롯별 F2−F1 runner 손실도 증분 효과가 작고 CI가 0을 포함한다.

| 최근5 슬롯 | 출전 | log-loss 차이 (95% 구간) | Brier 차이 (95% 구간) |
|---|---:|---:|---:|
| 0 | 2,539 | −0.000613 (−0.001406, +0.000112) | −0.000294 (−0.000652, +0.000033) |
| 1~2 | 3,838 | −0.000907 (−0.001958, +0.000109) | −0.000423 (−0.000869, +0.000012) |
| 3~5 | 11,035 | −0.000004 (−0.000461, +0.000490) | −0.000056 (−0.000249, +0.000146) |

## 공통 운영 비교

기존 운영비교와 동일한 467경주·4,475출전·70일에서 맞춘 비교다. HY_R_FORM은 보존된 PL 분포를 사용했다. R1/F1/F2의 6조합은 각 모형의 세 말 점수합을 온도 보정해 만든 집합분포에서 확률이 높은 상위 6개 조합이다(PL로 계산하지 않음). 과거 실제 게시표 실적이나 수익률이 아니다.

| 모형 | Brier | log-loss | 최고점 입상 | Top5 capture | Top5에 Top3 전원 | 최대6 조합 적중 |
|---|---:|---:|---:|---:|---:|---:|
| HY_R_FORM 운영 | 0.187645 | 0.555417 | 61.03% | 75.02% | 38.97% | 30.84% |
| R1 | 0.199224 | 0.584759 | 54.39% | 67.02% | 26.12% | 21.41% |
| F1 | 0.194940 | 0.573442 | 58.24% | 69.52% | 30.19% | 24.41% |
| F2 | 0.194929 | 0.573648 | 57.39% | 69.74% | 30.19% | 25.05% |

F1−HY_R_FORM Brier는 +0.007295 (95% 구간 +0.003824, +0.010864), log-loss +0.018025 (+0.009711, +0.026535), 최대6 조합 적중 −6.42%p (−10.78~−2.22%p)였다. 이 결과는 운영 변경 근거가 아니다.

## 학습·복구·검증

R1의 저장된 2024~2026 모형을 재로딩해 기존 17,412 점수·확률, 1,779 경주 지표와 10,674 조합을 재현했다. R1 재학습은 0회다. 후보는 F1/F2×3개 연도, 최종 모형 6개다. 후보 메타데이터는 early-stop 초기학습과 iteration refit을 합쳐 12 LightGBM 호출, 온도 최적화 6회를 기록하며, 코드에는 후보별 각각 2회/1회 호출이 있다. 독립 검토에서 메타데이터와 호출 구조를 확인했다. 고정 분할은 평가 Y별 train 2017~Y−3, early stop Y−2, refit through Y−2, calibration Y−1, test Y다. 모수·가중치·seed·조합 규칙은 R1 계약과 동일하다.

최초 `run.py fit`은 여섯 모델과 핵심 예측·경주·조합을 저장한 뒤 context의 `observed_starts` 중복 조인 때문에 후속 집계 단계에서 멈췄다. 여섯 후보 `top3.txt` 파일은 KST 05:58:40~05:58:53에 저장됐다. 중간 파일은 [`runner_predictions_fit_stage.parquet`](outputs/runner_predictions_fit_stage.parquet)에 보존했다. [`complete_outputs.py`](complete_outputs.py)는 중복값의 일치성을 확인해 context를 정규화하고 여섯 저장 모형을 다시 불러와 보정·점수·예측·지표·조합을 재현했다. 재학습은 하지 않았다.

사전 독립 lineage/preflight 및 R1 replay가 통과했고, [`final_verification.json`](outputs/final_verification.json)은 52,236 말별 확률과 5,337 variant-race의 확률합·canonical 최대6 조합, 참조 46개·보호 4개 해시를 확인했다. 독립 전수 재검증도 [review receipt](../20261009_finish_and_condition_review_v1/independent_verification.json)에서 통과했다. reviewer는 대조 R1 3개와 후보 F1/F2 6개, 총 9개 모델을 실제 재로딩·재점수화하고 보정 점수 57,735개, 예측 52,236행, 경주 5,337행, 조합 32,022행, group/bootstrap 표와 운영 467 표를 독립 확인했다. 이 receipt는 F1 gate 통과·F2 순차 gate 실패, DB/production 불변과 독립 미래검증이 아님을 기록한다.

자료는 T−2 날짜 proxy로 과거 결과를 연결하고, 이미 정정된 사후 원장 결과를 사용했다. 당시 발표·정정 시각과 신고 출전 집합을 재구성하지 않았다. 같은 후향 표본·다수 지표를 반복 사용했고 다중비교 보정은 하지 않았다. 결론은 연구 후보 구분에 한정되며 운영 승격·인과효과·독립 검증으로 부르지 않는다.

## 파일

- 고정 계약과 판정: [`CONTRACT.md`](CONTRACT.md), [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md), [`SUPERVISOR_GATE_ADDENDUM.md`](SUPERVISOR_GATE_ADDENDUM.md)
- lineage·사전 검증·완료 receipt: [`source_audit_summary.json`](outputs/source_audit_summary.json), [`historical_lineage.parquet`](outputs/historical_lineage.parquet), [`preflight_verification.json`](outputs/preflight_verification.json), [`r1_replay_verification.json`](outputs/r1_replay_verification.json), [`training_completion.json`](outputs/training_completion.json), [`final_verification.json`](outputs/final_verification.json)
- 주결과: [`race_metrics.csv`](outputs/race_metrics.csv), [`paired_differences.csv`](outputs/paired_differences.csv), [`metrics_by_group.csv`](outputs/metrics_by_group.csv), [`runner_metrics_by_group.csv`](outputs/runner_metrics_by_group.csv), [`runner_paired_differences.csv`](outputs/runner_paired_differences.csv), [`calibration_bins.csv`](outputs/calibration_bins.csv)
- 최근5 보충군: [`last5_history_group_metrics.csv`](outputs/last5_history_group_metrics.csv), [`last5_history_paired_differences.csv`](outputs/last5_history_paired_differences.csv), [`last5_history_supplement_verification.json`](outputs/last5_history_supplement_verification.json)
- 운영 공통 표: `outputs/operating_common_467_*`
- 입력·코드·모델·출력 파일별 크기/SHA-256 inventory: [`ARTIFACT_MANIFEST.json`](ARTIFACT_MANIFEST.json)
