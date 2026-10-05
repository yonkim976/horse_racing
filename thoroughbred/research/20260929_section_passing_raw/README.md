# 2010년 이후 구간기록·통과조 원천 적재

## 범위와 방식

서울·부산은 2010-01-01부터, 영천은 2026년 자료 시작일부터 현재 원천에서 확인되는 구간기록과 통과조를 별도 스냅샷으로 적재했습니다. 원천 테이블마다 컬럼 이름과 순서를 보존하고, 값은 원천 테이블 단위로 유지했습니다. 말별 출전 행에 통과조를 펼쳐 넣지 않았습니다.

산출물 위치는 `data/section_passing_raw_2010plus_20260929_v1/`입니다. DuckDB, 테이블별 Parquet, 컬럼 목록·행 수·기간을 기록한 `coverage.json`이 있습니다. 입력은 읽기 전용으로 열었습니다.

## 적재 결과

| 원천 데이터 | 적재 행 | 범위 |
|---|---:|---|
| `section_time` 표준 구간 데이터 | 2,791,247 | 서울 1,047,533 · 부산 1,743,101 · 영천 613; 2010-01-08–2026-09-20 |
| `finish_time` 완주·결과 | 327,320 | 오류 경주 16키의 180행 제외; 2010-01-08–2026-09-20 |
| `point_position` 구간 위치 | 1,011,106 | `finish_time`과 연결된 2010년 이후 행 |
| 품질 이슈·S1F 불일치 | 4,069 · 13 | 품질 이슈 4,069행, S1F 불일치 13행 |
| 출처 판정·쌍별 판정·거리별 트랙 | 36 · 2 · 19 | 원천 스키마 그대로 |
| 운영 DB `race_section_results` | 530,490 | 2010-01-09–2016-12-31 |
| 운영 DB `race_section_times` | 1,536,143 | 서울·부산은 2017년부터, 영천은 2026-09-13부터; 최신 2026-09-20 |
| 운영 DB `race_passing_groups` | 80,180 | 서울·부산은 2017년부터, 영천은 2026-09-13부터; 16,547경주 |
| 운영 DB `race_passing_summaries` | 14,649 | 서울·부산은 2018년부터, 영천은 2026-09-13부터; 14,649경주 |

`section_source_evidence`는 원천에 130,317행이 있지만 확인된 meet 코드가 제주(2)뿐이라 이 더러브렛 스냅샷에서는 0행입니다. 테이블과 원래 7개 컬럼은 유지했습니다. 2010년 이후 출전 결과 행의 날짜 범위와 별도 품질 정보를 `coverage.json`에 기록했습니다.

## 테이블 구성

- `spdb_*`: `section_points_adjudicated.sqlite3` 원천 테이블. `finish_time`, `section_time`, `point_position`, 품질·판정·트랙별 거리 정보를 포함합니다.
- `op_*`: `horse_racing.sqlite3` 원천 테이블. `race_passing_groups`, `race_passing_summaries`, `race_section_results`, `race_section_times`를 포함합니다.
- `op_race_context`, `op_entry_context`: 원천 테이블을 변경하지 않고 내부 `race_id`·`race_entry_id`를 경주장, 날짜, 경주 번호, 말 ID 및 공통 `canonical_race_id`에 연결하는 별도 브리지입니다.
- `parquet/`: 각 DuckDB 원천 테이블과 브리지의 Parquet 복사본입니다.

통과조 표는 경주 단위 자료입니다. `race_passing_groups`와 `race_passing_summaries`의 행 수는 말별 출전 수가 아닙니다. 말별 구간기록은 각 원천의 `race_entry_id`와 별도 출전 브리지를 사용해 연결합니다.

현재 원천 DB의 최신 확정일은 서울·영천 2026-09-20, 부산 2026-09-18입니다. 운영 DB에는 확인된 결과 API 오류 경주 72키가 없습니다. 이전 구간기록 연구 원천에는 그중 서울·부산경남 16키의 `finish_time` 180행이 남아 있었으므로 이 스냅샷과 Parquet에서 제거했습니다. 빌더도 [첫 판정 원장](../20260929_calendar_api_v1/planless_positive_result_review.csv)과 [추가 판정 원장](../20260929_calendar_api_v1/result_only_nonfinish_anomaly_review.csv)의 72키를 재생성 시 제외합니다. 이전 연구 원천 DB 자체는 감사 추적을 위해 보존합니다.

## 재생성

프로젝트 루트에서 실행합니다.

```bash
.venv/bin/python thoroughbred/research/20260929_section_passing_raw/build.py
```

기존 산출 경로는 덮어쓰지 않습니다. 새 스냅샷이 필요하면 빌드 버전과 출력 경로를 함께 올립니다.
