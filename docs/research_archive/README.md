# 연구 결과 보관본

이 디렉터리는 2026-09-22(KST) 대용량 연구 산출물 정리 전에 남긴 영구 기록이다.
`data/research`와 `data/experiments`에서 보고서, 판정 파일, 검증 결과, 작은 지표표와
차트를 원래 상대 경로를 유지한 채 `source/` 아래에 복사했다.

## 보관 범위

- Markdown 보고서·README 143개
- selection/decision/verification/manifest 등 JSON 210개
- 작은 CSV 지표표 183개
- PNG 차트 4개

대용량 SQLite/DuckDB/Parquet, 학습 중간 산출물, 비채택 모델 파일은 이 보관본에 넣지
않았다. 따라서 이 디렉터리는 연구의 목적·방법·수치·판정 이력을 확인하기 위한 것이며,
삭제된 모든 실험을 그대로 재실행할 수 있는 완전한 데이터 백업은 아니다. 일부 원문
보고서의 바이너리 산출물 링크는 정리 후 존재하지 않을 수 있다.

## 핵심 결론

| 연구 흐름 | 남은 결론 |
|---|---|
| 서울·부산 과거자료 | 백필, 임시 ID 연결, 주행심사·신선도 감사 결과를 보고서와 검증 파일로 보존했다. 대용량 중간 DB는 현행 예측 실행에 필요하지 않아 제거했다. |
| 제주 전용 모델 v1~v13 | 전이·컨텍스트·경험·구간·주행심사 후보를 비교했지만 최종 운영 모델은 `HY_R_FORM`이다. v13 이후 정확도·place·rolling 후보도 승격되지 않았다. |
| 더러브렛 A | v5 `rolling_all`이 현행 챔피언이다. |
| 더러브렛 B·C | v4 `top3_growth_strength`가 현행 챔피언이며, C의 순서 축은 v2 `H3_relative`를 사용한다. |
| 더러브렛 후속 v6~v9 | boundary, joint, 부담중량, 경마장 컨텍스트 후보는 전체 운영 모델을 교체할 관문을 통과하지 못했다. |
| RaceValue/RacePortfolio | 복병 탐지·배팅 배분 연구 기록은 보존했지만 안정적인 실전 수익성이 확립된 결과로 보지 않는다. |

세부 수치와 판정 근거는 [원문 보관 트리](source/)에서 연구 폴더별로 확인한다. 현재
운영 모델의 공식 선택과 해시는
[`config/prediction_model_registry.json`](../../config/prediction_model_registry.json)이
유일한 기준이다.

## 계속 유지하는 실행 자산

현행 모델의 해시 검증과 미래 경주 추론 준비에 연결된 다음 디렉터리는
`data/research`에 그대로 유지했다.

- `thoroughbred_model_20260918_v1`
- `thoroughbred_unified_20260918`
- `thoroughbred_win_research_20260918_v2`
- `thoroughbred_three_targets_20260918_v3`
- `thoroughbred_followup_20260918_v4`
- `thoroughbred_offline_20260918_v5`
- `thoroughbred_boundary_20260918_v6`
- `thoroughbred_weight_20260919_v8`
- `jeju_native_text_phase2_db_20260915`
- `jeju_native_top3_dataset_v1_20260915_r2`
- `jeju_native_h3_features_v1_20260916`
- `jeju_native_transition_features_v1_20260916`
- `jeju_native_transition_holdout_v13_20260916`
- `jeju_accuracy_candidates_20260919`

## 2026-09-22 정리 기록

- `data/research`의 비운영 연구 산출물 약 10.74 GiB를 제거했다.
- `data/experiments/race_portfolio_v1`, `race_value_v1`의 대용량 실행 산출물 약
  219 MiB를 제거하고 보고서·manifest를 `source/experiments/`에 보존했다.
- 삭제 전후에 더러브렛·제주 생산 모델 resolver를 실행해 registry, 필수 파일과
  SHA-256 검증을 통과시켰다.
- 삭제는 Git에 들어 있지 않은 로컬 연구 데이터 정리이며, 운영 DB와 `data/raw` 원천,
  현행 예측 모델 자산은 대상에 포함하지 않았다.
