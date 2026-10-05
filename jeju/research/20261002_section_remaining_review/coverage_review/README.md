# API6 누락 6경주 원천 coverage 재검토 — 2026-10-02

## 결론

현재 보유한 공식 API6_1 전기간 원문에서는 여섯 완주경주의 정확한 `(rcDate, rcNo)` 키가 모두 없습니다. 따라서 보유 API6 원문에서 각 레코드의 시간 필드가 NULL이거나 비어 있다는 판단이 아니라, 경주 수준 API6 레코드 자체가 없습니다. API6는 말 ID를 갖지 않는 경주 수준 자료이므로 API4의 말별 행과 구분합니다.

| 경주일·경주 | API6 연간 원문 키 일치 | API303 경주 행 | API4 말 행 | API4 payload hash 확인 | API4/API303 통과순위 검토 |
|---|---:|---:|---:|---|---|
| 2025-01-10 1R | 0 | 1 | 10 | 전부 일치 | 비교 flag 0 |
| 2025-05-16 8R | 0 | 1 | 9 | 전부 일치 | 비교 flag 0 |
| 2025-05-23 3R | 0 | 1 | 10 | 전부 일치 | 비교 flag 0 |
| 2025-06-27 4R | 0 | 1 | 10 | 전부 일치 | 비교 flag 0 |
| 2025-07-04 5R | 0 | 1 | 10 | 전부 일치 | 비교 flag 0 |
| 2026-09-11 5R | 0 | 1 | 7 | 전부 일치 | 비교 flag 0 |

## 전체 시즌 페이지와 원문 범위

출처는 [API6_1 전기간 수집 원장](../../20260929_api_detail_sources/README.md)과 immutable annual run `20260929T143902.196014Z`다. 대상 2025·2026 연도 partition을 직접 재검증했다. 각각 `complete_year_partition`; API6 totalCount와 페이지에서 직접 파싱한 행 수가 710/710, 531/531로 일치하고, expected/actual pages가 모두 1/1이다. 요청한 연도와 모든 `rcDate`가 맞으며, 각 페이지의 SHA-256·byte 수·item 행 수를 manifest 원문과 대조해 모두 통과했다. 따라서 연간 수집의 페이지 잘림 또는 다음 페이지 누락은 여섯 경주 공백의 설명이 아니다.

상위 작업에서 2026-10-02에 같은 API6 연간 partition을 다시 요청했다. 최신 [재조회 manifest pointer](../latest_api_retry_pointer.json)가 가리키는 manifest에서 2025 `totalCount=710`, 2026 `totalCount=531`, actual rows와 page rows도 각각 그대로 일치했다. 두 fresh response의 SHA-256이 2026-09-29 archive 페이지와 완전히 같고, fresh annual payload에서 여섯 대상 `(rcDate, rcNo)`를 다시 찾은 결과도 각각 0행이다. 현재 재조회까지 포함하면 저장 스냅샷 이후 API 응답이 바뀌어 공백이 해소됐다는 근거는 없다. 상세 응답 해시·필터·대상키 대조는 [재조회 요약](current_api_recheck_summary.csv) 및 [coverage JSON](coverage_review.json)에 있다.

## 공식 홈페이지 대조

상위 작업에서 확인한 공식 KRA 결과 페이지 6건은 모두 HTTP 200이고 날짜·경주 식별이 검증됐다. 각 페이지의 `펄롱타임, 통과거리, 통과타임` 표에는 라벨만 있고 세 행의 값 칸은 전부 비어 있다.

| 경주일·경주 | 펄롱타임 | 통과거리 | 통과타임 |
|---|---|---|---|
| 2025-01-10 1R | 공란 | 공란 | 공란 |
| 2025-05-16 8R | 공란 | 공란 | 공란 |
| 2025-05-23 3R | 공란 | 공란 | 공란 |
| 2025-06-27 4R | 공란 | 공란 | 공란 |
| 2025-07-04 5R | 공란 | 공란 | 공란 |
| 2026-09-11 5R | 공란 | 공란 | 공란 |

이는 홈페이지의 해당 경주별 펄롱·거리·통과시간 표가 비어 있음을 뜻한다. 경주 말별 통과기록이나 코너 통과순위 표까지 전부 비었다고 확장하지 않는다. 원문 페이지 SHA-256, 확인 시각, exact URL, 세 행 원문은 [website evidence](../website_evidence.json)와 [요약표](website_gap_summary.csv)에 보존했다.

## 공식 TXT 보완 대조

상위 작업은 API 재조회와 홈페이지 확인 후 여섯 경주의 공식 TXT도 보완 대조했다. TXT에는 거리 격자와 경주 전체 3F·4F 합계가 있지만 상세 펄롱시간과 누적 통과시간은 모두 공란이다. 따라서 홈페이지에 없는 거리 표기가 TXT에 있다는 사실과 누락 시간 보충 가능 여부를 구분한다. 이 합계나 말별 시간을 이용해 API6의 누락 구간시간을 추정하지 않는다. [TXT 수집 원장](../supplemental_rpt_manifest.json), [여섯 경주의 원문 행과 대조 결과](../supplemental_rpt_review.json)를 따른다.

## API4·API303

API303은 여섯 경주 모두 정확한 날짜·장·경주번호 키로 1행이 있고, 각 원문에 `passtime_3f`, `passtime_4f`, `tempo` 및 주요 corner 필드가 보존돼 있다. `corner_1`·`corner_2`는 여섯 경주 모두 `-`, `corner_5`·`corner_6`·`corner_9`는 `X`; 이 값들은 결측 또는 사용 불가 상태로 둔다. API4에는 각각 7~10개의 공식 말별 결과 행이 있다. 각 source page의 SHA·1-based item 위치·경주/말 키와 원문 payload hash가 연결된 DB row와 모두 일치하고, API303의 같은 provenance 연결도 6건 전부 일치한다. 말별 구간시간·통과순위 필드별 key/null/0/양수 상태는 [API4 필드 coverage](api4_field_coverage.csv)에 기록했다.

기존 audit에 쓰인 비교 대응(`API303 corner_7 ↔ API4 sjS1fOrd`, `corner_1 ↔ sj_1cOrd`, `corner_2 ↔ sj_2cOrd`, `corner_3 ↔ sj_3cOrd`, `corner_4 ↔ sj_4cOrd`, `corner_8 ↔ sjG1fOrd`)으로 그룹 내 순위범위를 대조했다. 실제 값을 가진 비교 지점에서 여섯 경주 모두 API4 양수 순위는 보수적인 API303 통과조 그룹 순위 구간 안에 있었고, 숫자 누락·범위 밖 순위 flag는 0이었다. 1C·2C는 API303 값이 `-`여서 유효 대조 표본이 없다. 이 대응은 내부 검토용이며 API4와 API303의 정의가 완전히 같다는 주장이나 정정 규칙이 아니다. API303 3F/4F 시간은 별도 원문으로 보존하며 API4 말별 G3F 등의 시간과 같은 측정값이라고 간주하지 않았다.

API6 경주 전체 구간흐름을 API4 개별 말의 관측값으로 대체하지 않는다. 공식 출처가 제공하는 별도 API4/API303 값이 있다는 사실은 API6 결측 필드를 채우는 증거가 아니다.

## Live 재조회 방법

작업자가 재확인할 endpoint는 `GET /API6_1/raceDetailSectionRecord_1`, operation `raceDetailSectionRecord_1`이다. 서비스 키는 실행 환경에서만 전달하고 URL/log/manifest/보고서에는 넣지 않는다. 코드의 기존 공식 날짜 표본 요청 형식은 `meet=2`, `rc_date=YYYYMMDD`, `_type=json`, `pageNo=1`, `numOfRows=1000`이다. `rc_date`가 날짜 필터이므로 응답의 모든 페이지를 totalCount에 맞춰 받고, `rcDate`와 `rcNo`로 요청 경주를 확인한다. 재조회를 해도 대상 행이 없으면 현재 API 응답 공백으로 확인되고, 있다면 기존 2026-09-29 저장 연간 스냅샷과 달라진 시점/필터 결과로 기록한다. API4/API303 자료를 통해 API6 값이 있었을 것이라고 추정하지 않는다.

## 재현 자료

- 상세 row, 원문 path/hash, 페이지 검증, raw/API4 row별 field state, API303 payload 및 각 비교 flag: [coverage_review.json](coverage_review.json)
- race별 요약: [race_gap_summary.csv](race_gap_summary.csv)
- 홈페이지 펄롱/거리/통과시간 공란의 경주별 근거: [website_gap_summary.csv](website_gap_summary.csv)
- 상위 작업의 최신 연간 API 재조회 요약: [current_api_recheck_summary.csv](current_api_recheck_summary.csv)
- 말별 API4 시간·통과순위의 key 부재, NULL, 0, 양수 및 원시 필드 상태 집계: [api4_field_coverage.csv](api4_field_coverage.csv)
- 대상 6경주 목록: 기존 [completed_missing_source_keys.csv](../../20261002_section_passing_audit/root_audit/completed_missing_source_keys.csv)

본 재검토는 원문 artifact·DB를 읽기 전용으로 확인하고, 상위 작업에서 저장한 API 재조회와 홈페이지 원문 증거를 포함한다. 여기서는 외부 API 요청이나 DB 변경을 하지 않았다.
