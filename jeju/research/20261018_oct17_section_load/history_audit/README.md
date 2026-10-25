# API6 1100/1110m 구간거리 이력 감사

## 핵심 결과

이 문서는 **10/17 적용 전 DB 스냅샷**을 조사한 읽기 전용 이력 감사입니다. `64행 중 rcDist=1110 18행`이라는 수치는 적용 전 상태이며, 이후 적재 결과는 상위 [적재 보고서](../README.md)에서 별도로 확인하세요.

- 실제 경주거리 `rcDist`/`race_distance_m`가 1100m인 경주는 이 조사 범위에서 0건입니다. 관련 경주의 실제 경주거리는 **1110m**입니다.
- API6에서 1110m 경주의 `dist_1f..dist_6f`는 `100, 300, 500, 700, 900, 1100`으로 저장됩니다. 마지막 구간 측정점 값 `1100`은 경주거리 1100m라는 뜻이 아닙니다.
- API4 `race_result_rows`의 원문 `payload_json.rcDist`와 정규화된 `race_distance_m`는 1110m 표본 12,945행 전부 일치했습니다. 해당 범위는 1,289경주(2011-04-23–2026-10-17)이며, 1100m는 0행입니다.
- API6 파일 아카이브 25페이지는 19,651경주를 담고 있습니다. 그중 `rcDist=1110` 1,259행은 전부 같은 100–1100 구간격자이고 `rcDist=1100`은 0행입니다. 이들은 DB에 적재된 API4 말별 행이 아니라 별도 API6 경주 단위 원문 파일입니다.
- `/20261007_foundation_v1/api6_distance_grids.json`의 1,062경주도 독립 재현 산출물과 동일했습니다. API6 원문키를 2017-01-01부터 2026-09-19까지의 API4 후보 경주키와 교차한 수치입니다. 연도별 수는 2017:18, 2018:70, 2019:82, 2020:49, 2021:77, 2022:103, 2023:144, 2024:190, 2025:194, 2026:135입니다.
- 보유 공식 HTML 5개(2016년 1개, 2021년 3개, 2026-10-17 5R 1개)의 1110m 경주는 `통과거리 110, 310, 510, 710, 910, 1110`을 보이고 API6는 `100, 300, 500, 700, 900, 1100`을 보입니다. 이는 10/17 5R의 홈페이지 근거 6칸 검토를 뒷받침하지만, 과거 경주 전체에 +10m를 적용할 근거로 확대하지 않습니다.

## DB 원천과 조회 이름

| 목적 | 테이블/뷰 | 의미 |
|---|---|---|
| API6 경주 단위 원행 | `refresh_section_records` | API6 `api_records`에 연결한 경주키 |
| API6 원문·출처 결합 조회 | `api6_section_records_current` | 원문 payload와 `source_artifacts` 경로·SHA 포함. API4 말별 결과에 합치지 않음 |
| API4 경주 결과 원행 | `race_result_rows` | 말별 결과·`race_distance_m`; 원문 `rcDist`는 `api_records.payload_json` |
| 프로필 필터 API4 현행 | `race_current` | API4 후보 결과를 최신 제주마 프로필 조건으로 제한 |
| 기존 API4 구간 품질 | `sections_current` | API4/API303 말별 품질 조회. API6를 결합하지 않음 |
| 새 구간별 거리 검토 | `api6_section_points_current` | API6 거리 원값과 별도 검토 후 유효 거리를 함께 제공. 10/17 5R 여섯 칸은 홈페이지 검토 상태로 분리 |

`api6_section_records_current` 및 `race_current`, `sections_current`의 정의는 [current_views.py](../../../refresh/current_views.py)와 [DB 스키마](../../../data/schema/jeju_native_core.sql)에 있습니다. `api6_section_points_current`의 정의는 [거리 검토 마이그레이션](../../../data/schema/migrations/20261018_add_api6_section_distance_reviews.sql)에 있습니다. JSON에는 적용 전 64 API6 행의 ID, 18개 1110m 경주 키, 9개 적재 artifact와 SHA를 담았습니다.

## 원문 증거

[전체 증거 JSON](api6_1100_1110_history_audit.json)에 다음을 저장했습니다.

- 적재 전 DB 경주/API6 집계와 행 ID 목록, `source_artifacts`의 기여 페이지 경로·SHA
- API6 연도별 25개 공식 원문 페이지의 상대경로, SHA-256, 행 수와 연도 예시
- `api6_distance_grids.json` 및 재현본의 해시와 1,062경주 검산
- 공식 HTML 표본의 경주키, API6 원문 페이지, HTML 원문 경로·SHA 및 두 거리 배열
- 2025·2026 재시도 원문은 연도별 아카이브와 내용 해시가 중복되므로 합산하지 않는다는 구분

HTML/API 직접 비교 중 10/17 5R은 기존 [홈페이지 대조 증거](../../20261018_oct17_sections_website_review/root_independent_verification.json)를 재사용했습니다. 여기서 시간 39/39, API 제공 통과조 29/29 값은 일치했고 거리 여섯 칸만 달랐습니다.

## 경계

관측된 반복 패턴은 API6 원값과 공식 HTML 간 1110m 거리 격자 불일치를 보여줍니다. 이 감사는 원인 규칙을 일반화하거나 다른 경주의 값을 정정하지 않습니다. 적용 승인 범위는 2026-10-17 5R의 홈페이지 근거 6칸이며, 다른 모든 경주에서는 API6 원문값을 그대로 보존합니다.
