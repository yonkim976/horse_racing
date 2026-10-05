# 2026년 결과 API 오류 경주 활성 데이터 제거 기록

2026-09-30, 결과 API에만 있던 72개 경주 키를 활성 연구 데이터에서 제거했다. 처음 판정한 20키는 [첫 판정 원장](planless_positive_result_review.csv), 추가 52키는 [추가 판정 원장](result_only_nonfinish_anomaly_review.csv)에 있다. 모두 이전 시행 경주와 출전마 집합이 정확히 같고, KRA 성적표에서 해당 경마장·날짜의 경주 자료가 없음을 직접 조회했다. 추가 52키는 결과 API에 말별 531행이 있었지만 착순과 양수 주파시간이 함께 있는 행은 0개였다. 원천 API 응답과 판정 원장은 감사 추적용으로 보존한다.

| 활성 산출물 | 제거한 행 | 재검증 |
|---|---:|---|
| 날짜·시행 원장 `race_execution_flags.csv` | 경주 키 72 | 대상 키 0, 확정 시행 29,710 유지 |
| 결과 원장 `race_events.csv`, `runner_results.csv` | 경주 72, 말별 결과 753 | 대상 키 0, 제외 위치 753개 `scope_exclusions.csv`에 기록 |
| 새 코어 `thoroughbred_core.duckdb` | 위 경주·결과 반영 | 대상 키 0, 확정 출전 330,465 유지 |
| 이전 연구 스냅샷 `thoroughbred.duckdb` 및 Parquet | 경주 56, 출전 581, 원천 구간 2,040 | 대상 키 0; 과거 성적 피처·학습 라벨 재계산 |
| 구간 원천 스냅샷 `section_passing_raw.duckdb` 및 Parquet | `spdb_finish_time` 180 | 대상 키 0 |
| 구간·출전 대조 Parquet 2개 | 각각 180 및 581 | 대상 키 0 |

운영 SQLite에는 72개 키의 경주행이 이미 0개여서 삭제할 행이 없었다. 날짜·결과·코어·이전 연구 스냅샷·구간 원천·대조 빌더에는 동일 키의 재유입을 막는 필터를 넣었다. KRA 성적표 취소 사유 검증과 2021~2025 공식 연간 통계 10개 조합 대조가 통과했다.

과거 실행을 재현하기 위한 `data/research/`의 이전 통합·구간 원천 DB와 기존 `data/datasets/` 모델 실험 파일은 변경하지 않았다. 이 파일들은 새 코어 DB의 입력이나 학습 기준으로 사용하면 안 된다. 특히 이전 구간 원천 `section_points_verified.sqlite3`와 `section_points_adjudicated.sqlite3`에는 서울·부산경남 오류 16키의 `finish_time` 180행이 남아 있으며, 현재 빌더는 이를 제외한다.
