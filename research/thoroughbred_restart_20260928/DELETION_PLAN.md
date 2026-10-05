# 삭제 전 확정 목록 — 2026-09-28

현재 등록된 최종 3개 학습 모델(A, B/C, 순서축)과 실행 의존성을 보호한다. 과거 연도 가중치와 비채택 후보의 모델 파일 및 이전 예측 캐시를 삭제한다. 원천 DB·학습 표본·피처 생성 코드·현재 예측·연구 결과표·보고서는 유지한다.

| 연구 디렉터리 | 파일 수 | MiB |
|---|---:|---:|
| thoroughbred_boundary_20260918_v6 | 29 | 0.04 |
| thoroughbred_followup_20260918_v4 | 34 | 17.66 |
| thoroughbred_growth_return_20260922_v10 | 108 | 74.51 |
| thoroughbred_learning_curve_20260922_v12 | 108 | 203.95 |
| thoroughbred_model_20260918_v1 | 107 | 161.57 |
| thoroughbred_offline_20260918_v5 | 101 | 80.53 |
| thoroughbred_sampling_control_20260922_v11 | 72 | 49.74 |
| thoroughbred_seed_ensemble_20260925_v13 | 72 | 48.23 |
| thoroughbred_three_targets_20260918_v3 | 450 | 287.71 |
| thoroughbred_weight_20260919_v8 | 96 | 93.35 |
| thoroughbred_win_research_20260918_v2 | 140 | 68.40 |

합계 1,317개, 1,138,425,458 bytes. 정확한 경로·해시는 deletion_plan.json에 보존한다.

이전 manifest는 당시 완전한 산출물의 기록이다. 정리 후에는 삭제된 모델을 포함한 과거 전체 manifest 검사/과거 모델 재추론이 실패하는 것이 예상된다. 현재 운영 모델 검증은 별도로 유지한다.
