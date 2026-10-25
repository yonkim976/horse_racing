# 운영 HY_R_FORM과 저장 연구 모델의 동일 경주 사후 가치 비교

이 회고 비교에서는 **고정 규칙에서 지속 가능한 수익을 확인하지 못했다.** QPL의 사후 EV 최대 선택은 양쪽 모델 모두 장부상 플러스였지만 당첨 상위 3건을 빼면 음수로 바뀌고, operating−research ROI 차이의 날짜 paired 95% 구간도 0을 포함한다. PLC는 사전 고정한 8개 규칙 모두 순 ROI가 음수였다. 이 결과는 반복 분석된 2026년 부분연도 개발 자료에 한정되며 안정적 수익이나 사전 구매 전략을 입증하지 않는다.

## 동일 경주 비교 결과

QPL은 완전한 공통 cohort 467경주·70일의 모든 pair와 동일한 최종 표시 배당을 썼다. `all_max_ev_gt_0`는 operating에서 467경주 중 466회 선택, 26회 적중, 순이익 50,700원, ROI 10.88%였다. 저장 `pair_id_baseline`은 467회 선택, 20회 적중, 순이익 110,400원, ROI 23.64%였다. 다만 최고 환급 적중 1건을 각각 빼면 ROI는 operating -2.86%, research +9.96%이고, 최고 환급 3건을 빼면 각각 -22.89%, -12.89%다. 동일한 날짜 재표집을 사용한 ROI 차이(operating−research)는 -12.76%p, 95% 구간 [-72.14, 44.53]%p로 0을 포함한다.

PLC에서는 operating `top3_max_ev_positive`가 436경주 중 306회 선택, 133회 적중, -1,900원, ROI -0.62%였고 F1_STYLE6는 284회 선택, 88회 적중, -36,600원, ROI -12.89%였다. ROI 차이 +12.27%p의 paired 95% 구간 [-8.17, 33.06]%p는 0을 포함한다. 이 규칙에서 적중 수 차이는 operating에 유리했지만 수익 우위는 확인되지 않았다. 비교한 PLC 8개 규칙은 operating과 research 모두 순손실이었다.

## 범위와 해석

운영 모델은 등록부에서 확인한 `jeju-hy-r-form-20260919-v1` / `HY_R_FORM`이며 현재 pkl 및 `prediction_lock.json` 고정 bundle의 SHA-256은 `f1b9531e068cab51dff906961d56f51c7c4b0e5a86f378c9aa1f03f159ec9706`이다. HY의 frozen 평가 결과는 2026-01-02~09-12에 한정된다. 학습 기간은 2018-08-31~2025-06-28, 종료 선택은 2025-07-04~09-27, 확률 보정은 2025-10-02~12-27이다. 따라서 2025년은 OOS 비교 대상이 아니며, 보존된 2025 HY OOS raw-score archive도 없어 제외했다. 이 HY 파일은 2026년 실제 경주일 live 게시 기록이 아니라 offline frozen 평가 산출물이다. 경주 이력은 T−2까지 순차 갱신된다.

QPL 공통 cohort는 전체 말 ID 집합·마번·거리·결과가 확인된 정상 편성 467경주다. HY 저장 510경주 중 43경주는 기존 정상 공통 cohort 밖이고, 연구 전용 21경주는 운영 평가 cutoff 이후인 2026-09-17~19라 제외했다. PLC는 같은 경주 중 8두 이상인 436경주·69일로 맞췄으며 7두 이하 31경주는 양쪽 모델에서 동일하게 제외했다. 2025년을 넣지 않았고 어떤 모델도 다시 fit 또는 calibrate하지 않았다.

최종 표시 배당은 결과 확인 후 확정되는 가격이므로 `p × final odds − 1`은 사후 oracle 점수다. 실제 사전 구매 시점에 쓸 수 있었던 가격·예측 성적의 증거가 아니다. 13개 QPL 및 8개 PLC 고정 규칙은 prior 연구 PLAN에 명시된 그대로 적용했다. 각 경주에서 정책별 최대 1장, 1,000원이며 당첨 환급은 stake를 포함한 최종 표시 배당을 곱했다. 최대 QPL EV 동률은 낮은 unordered 마번 쌍, PLC 최대 EV 동률은 확률 rank와 낮은 마번 순으로 해결했다.

모든 ROI 불확실성 구간은 기존 고정 2,000×269 날짜 bootstrap을 썼다. 기존 269일 inventory 중 이번 공통 cohort에 없는 날짜는 해당 정책의 선택 0건으로 남겼다. paired 차이는 같은 draw에서 계산했다. 상위 환급 hit 1·3·5건과 해당 ticket stake를 뺀 ROI 민감도는 각 summary CSV에 있으며, QPL rank 1–5 및 PLC runner-rank 확률·실제 적중률·Brier score는 calibration CSV에 있다. 0-ticket을 포함한 모델 간 paired 비교 결과를 함께 보고, 사후 가격을 기준으로 고른 최대 ROI 규칙을 best strategy로 해석하지 않는다.

## 재현 및 파일

다음 명령으로 source 검증부터 결과 생성까지 재현한다:

```sh
.venv/bin/python -B jeju/research/20261015_operating_postrace_value_comparison_v1/analysis.py
```

핵심 결과는 `qpl_strategy_summary.csv`, `plc_strategy_summary.csv`, `qpl_paired_differences.csv`, `plc_paired_differences.csv`, `qpl_rank_calibration.csv`, `plc_rank_calibration.csv`, `qpl_selection_rank_distribution.csv`, `plc_selection_rank_distribution.csv`에 있다. 전체 pair 및 runner 후보확률·final quote·결과는 `qpl_pair_rows.csv`와 `plc_runner_rows.csv`, 실제 고정규칙 선택은 `qpl_selected_rows.csv`와 `plc_selected_rows.csv`다. Cohort 포함/제외 근거, source hash, 실행 지표는 각각 `cohort.csv`, `SOURCE_AUDIT.json`, `SOURCE_MANIFEST.json`, `REPORT.json`, `FINAL_MANIFEST.json`을 참조한다.
