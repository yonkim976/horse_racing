# 제주 경주결과 재노출 행 삭제 기록

2026-09-30에 사용자 요청에 따라 제주 전용 DB `jeju/data/jeju_native_core.sqlite3`의 결과 정규화 테이블 `race_result_rows`에서 재노출 자료 19경주·182행을 삭제했다. 대상은 2026-07-07 제주 1~4R 40행, 2026-08-25 제주 1~8R 75행, 2026-08-26 제주 1~7R 67행이다. 출전집합과 결과의 다른 날짜 재노출 근거는 [원인 감사](../../research/20260930_zero_time_cause_audit/README.md)에 있다.

| 지표 | 삭제 전 | 삭제 후 |
|---|---:|---:|
| `race_result_rows` | 191,786 | 191,604 |
| `jeju_race_population_candidates` | 92,695 | 92,513 |
| 후보 경주키 | 9,513 | 9,494 |
| `api_records` 원문 행 | 246,096 | 246,096 |

삭제 직전 대상 정규화 행은 [`deleted_race_result_rows.jsonl`](deleted_race_result_rows.jsonl)에 백업했고 SHA-256은 `281820d298cd60594144af922fc413d08e58d0bccc6955b9e14169512afd2326`이다. KRA API4_3 보존 응답과 `api_records` 원문 행은 감사·재검증을 위해 유지했다. 결과층만 삭제했으므로 원문 페이지의 다른 정상 경주를 훼손하지 않았다.

[`remove_replayed_result_rows.py`](remove_replayed_result_rows.py)는 세 날짜의 행 수·원문 페이지 SHA-256·완주시간 조건을 확인하고 트랜잭션에서 삭제했다. [`cleanup_report.json`](cleanup_report.json)에 전후 집계와 검증 결과를 남겼다. 처리 후 SQLite `integrity_check=ok`, 외래키 위반 0건이다. 재구축 적재기 [`build_native_core_from_api_raw.py`](../../scripts/build_native_core_from_api_raw.py)는 해당 원문 182행을 `api_records`에는 보존하면서 `race_result_rows`에는 넣지 않도록 변경했다. 2026년 보존 응답을 임시 DB에 적재한 검증에서는 원문 5,482행, 결과 정규화 5,300행, 대상 잔여 0행이었다.

이번 삭제는 당시 사유 미확정 76경주·680행이나 취소·불성립으로 확인된 71경주·713행에 적용하지 않았다. 이후 [마사회 홈페이지 재확인](../../research/20260930_zero_time_cause_audit/README.md)으로 76경주 중 69경주·650행의 명시적 취소 사유를 확인했다. 남은 7경주·30행은 [2026-10-01 사용자 확인](../../research/20261001_user_cancellation_confirmation/README.md)에 따라 취소 확인·사유 미표시로 반영했다. 취소 여부 미확정은 0경주다.
