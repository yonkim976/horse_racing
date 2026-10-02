# 구간 지점 DB 인수인계 · 2026-09-25

**2026-09-28 정리 후 상태:** 아래의 사용 금지 중간 파일 `section_points_ext.sqlite3`와 `section_points_repaired.sqlite3`는 고유 말 ID를 포함한 원천 키·시간값 및 보조표의 보존 여부를 대조하고 독립 검토를 거쳐 삭제했다. 기본 `section_points.sqlite3`는 완전 대체 여부가 확인되지 않아 보존하며 분석에는 사용하지 않는다. verified와 adjudicated는 그대로 유지했다. [삭제·검증 기록](../thoroughbred/maintenance/20260928_cleanup/REPORT.md)을 따른다. 과거 extend/repair 중간 단계는 삭제된 파일을 재생성하지 않고 그대로 재실행할 수 없다.

다른 에이전트가 구간 시간을 읽거나 고칠 때 쓰는 문서다. 정의의 근거는 [구간 지점 정의와 적재 방안](SECTION_POINT_LOAD_PLAN_2026-09-24.md), 첫 적재 숫자는 [구간 지점 DB 적재 보고](SECTION_POINT_DB_REPORT_2026-09-25.md)에 있다. **현재 수치와 검증 결과는 [원본 대조·판정 결과](SECTION_POINT_DB_SOURCE_ADJUDICATION_2026-09-25.md)를 기준으로 한다.**

## 1. 어느 파일을 읽나

| 파일 | 상태 |
|---|---|
| `data/research/section_point_db_20260925/section_points_adjudicated.sqlite3` | 사용. 보관 원문·현재 KRA 성적표까지 대조한 최신 연구용 DB |
| `data/research/section_point_db_20260925/section_points_verified.sqlite3` | 보존. 원본 대조 전 검증본. 최신 조회에는 사용하지 않음 |
| `data/research/section_point_db_20260925/section_points_repaired.sqlite3` | 이전 수정본. 순위 결측과 미정 3행 설명이 남아 있어 사용 금지 |
| `data/research/section_point_db_20260925/section_points_ext.sqlite3` | 사용 금지. 페이스 추정이 부산 누적과 막판을 뒤섞음 |
| `data/research/section_point_db_20260925/section_points.sqlite3` | 사용 금지. 2015년 이후 부산 누적·구간 필드가 없는 중간 파일 |
| `data/horse_racing.sqlite3` | 운영 DB. 이번 작업에서 수정하지 않음 |

운영 DB, Supabase, 예측 원장, 모델, 기존 연구 DB에는 쓰지 않았다. 이 구간 DB를 모델 입력으로 연결하지 않는다.

## 2. 어떻게 나누기로 했나

말별 구간은 한 테이블 `section_time`에 둔다. 경마장·거리·지점·시간 종류가 행을 가른다. 거리마다 표를 만들지 않는다.

시간 종류는 세 가지다.

| 종류 | 의미 |
|---|---|
| `cumulative` | 출발부터 그 지점까지 |
| `closing` | 그 지점부터 결승까지 |
| `segment` | 두 지점 사이의 구간. 부산 400m 안팎 |

공통으로 비교하는 구간 항목만 `common_point`에 둔다. 완주기록은 별도 `finish_time` 테이블에 있다.

| 항목 | 비교 |
|---|---|
| S1F 누적, 출발 후 200m | 제주 1,110m·1,610m는 210m라 공통에서 뺌 |
| G3F 누적 | 결승 600m 전 지점까지. 출발 후 거리는 경주거리마다 다름. 거리끼리 비교하지 않음 |
| G3F 막판 | 마지막 600m. 길이가 같아 거리끼리 비교 가능 |
| G1F 누적 | 결승 200m 전 지점까지. 거리끼리 비교하지 않음 |
| G1F 막판 | 마지막 200m. 거리끼리 비교 가능 |
| 완주기록 | 별도 `finish_time` 테이블. 같은 거리에서만 비교 |

누적과 막판은 둘 다 있을 때만 한 쌍이다. 없는 쪽을 0으로 채우거나 한쪽을 다른 쪽으로 복사하지 않는다. 둘의 합은 완주기록과 0.2초 안이면 일치로 본다. 0.2초는 0.1초 단위 기록의 반올림 허용이다.

나누지 않기로 한 것:

- 코너는 200m 펄롱이 아니다. 미터를 비운다. 서울·제주 코너를 부산 G8F·G6F·G4F로 바꾸지 않는다.
- 부산 G2F는 부산만의 지점이다. 서울 4C(결승 530m 전)와 같지 않다.
- 통과 순위는 시간과 다른 열이다. 제주 G3F 순위 필드는 API에 있으나 값이 0이라 순위로 저장하지 않는다.
- 내주로·외주로는 `track_condition`이 아니다. 그 열은 주로 상태다. 거리별 경로는 `track_by_distance`에 따로 둔다. 부산 1,500m·1,700m는 공식 거리 설명이 없어 비운다.

## 3. 지금 어떻게 나뉘어 있나

`section_time` 4,190,591행. 운영·부산 연구 원천의 양수 시간을 모두 보존했고 시간 값은 만들지 않았다.

| 표시 | 행 | 의미 |
|---|---:|---|
| `canonical` | 3,881,243 | 시간 종류별 대표 원천값 |
| `redundant` | 309,300 | 대표값과 0.2초 안으로 같은 중복. 뷰에서 제외 |
| `conflict` | 36 | 같은 말·지점·시간 종류인데 값이 0.2초보다 다름. 뷰에서 제외 |
| `geometry_excluded` | 12 | 1,300m 경주의 G8F. 결승 1,600m 전이라 출발보다 앞. 뷰에서 제외 |

`common_point`는 원본 대조 후 1,933,700행만 본다. 충돌 35행은 현재 KRA 공식 화면과 맞아 포함됐고, 제주에서 마지막 200m가 마지막 600m보다 긴 두 말의 네 행은 제외됐다. 이 뷰 안에서 같은 출전·지점·시간 종류 중복은 0이다. 제주 210m S1F도 0이다. 원천 순위는 `section_time.position`, 지점별 운영 순위는 `point_position`, 조회에 안전한 순위는 `common_point.position`으로 구분한다. 연구 API 시간을 대표값으로 골라도 순위는 같은 지점의 운영 기록에서 독립적으로 가져온다. 99 같은 특수값과 적재된 출전 수를 초과하는 순위는 `position_raw`에만 남긴다.

대표값을 고를 때 부산 연구 DB의 API 필드를 운영 DB 행보다 먼저 둔다.

### 시간 종류를 정한 방법

| 대상 | 방법 | 표시 |
|---|---|---|
| S1F, 코너, FIN | 코드 의미로 누적 | `fixed_code` |
| 서울에 `time_basis`가 있는 G3F·G1F | 원천 라벨 | `source_basis` |
| 부산 API 필드 | 필드 이름 | `api_field` |
| 운영 DB 값이 그 API 필드와 0.2초 안인데 종류가 달랐던 행 | 필드 이름으로 고침. 5,911행 | `aligned_to_api_field` |
| 제주 등 라벨이 없는 G3F·G1F | 완주 페이스와 비교해 추정 | `pace_vs_finish` |
| 완주기록이 없어도 지점 시간이 거리 순으로 증가 | 누적으로 추정 | `monotonic_without_finish` |
| 완주기록도 없고 비교할 지점도 없음 | 부산 API 필드 대조 후 현재 미정 0행 | `unresolved` |

`pace_vs_finish`는 마사회 라벨이 아니다. 부산은 API 필드가 있으면 그 추정을 쓰지 않는다. 제주 G3F·G1F 175,057행 중 130,317행은 보관 KRA 보고서 또는 API JSON과 값이 정확히 맞아 `section_source_evidence`에 원본 경로·해시가 기록됐다. 이 근거로 14행의 시간 종류를 막판으로 정정했다. 남은 44,740행(2002–2014)은 여전히 페이스 추정이며 공식 분류로 사용하지 않는다. 상세 수치는 [원본 대조·판정 결과](SECTION_POINT_DB_SOURCE_ADJUDICATION_2026-09-25.md)를 본다.

### 원천

| 원천 | 내용 |
|---|---|
| 운영 DB 양수 구간 2,447,635행 | 서울 2000–2014 `historical_research` 누적. 서울 2015–2024 `dacom11` 누적+막판. 서울 2025–2026 `API4_3` 누적. 제주 2002–2014 `race_result`. 제주 2015–2026은 출처가 비어 있고 2026년에만 `API4_3` 1,866행. 부산 2015–2026은 출처가 비어 있는 행이 대부분이고 2026년 `API4_3` 누적 1,023행. 영천 2026 `API4_3` 누적 |
| 부산 연구 DB 1,742,956행 | `thoroughbred_unified.duckdb`의 양수 API 필드 전부. 2005-01-07–2026-09-11. 이 중 2015년 이전은 756,800행 |

부산 2005–2014는 운영 구간표에 없다. 연구 DB 필드만 있다. 공식 API를 다시 호출해 이 파일을 만든 것은 아니다.

최신 수록일은 서울·영천 2026-09-20, 제주 2026-09-19, 부산 2026-09-18이다. 연구 DB 부산 필드는 2026-09-11에서 끝난다.

### 부산 API 필드

| 필드 | 지점 | 시간 종류 |
|---|---|---|
| `buS1fAccTime` | S1F | cumulative |
| `buG8fAccTime` … `buG1fAccTime` | G8F, G6F, G4F, G3F, G2F, G1F | cumulative |
| `bu_3fGTime`, `bu_1fGTime` | G3F, G1F | closing |
| `bu_10_8fTime`, `bu_8_6fTime`, `bu_6_4fTime`, `bu_4_2fTime`, `bu_2fGTime` | 해당 구간 | segment. 길이는 [구간기록 설명](https://race.kra.co.kr/raceScore/cornerRecordDesc.do) |

`buS1fTime`은 저장하지 않았다. `buS1fAccTime`과 다른 18두는 `s1f_field_mismatch`에만 있다. 차이는 0.1–0.2초다.

현재 운영 수집기 `src/horse_racing/parsers/race_section.py`는 부산 누적 필드만 읽고 막판·구간 필드를 버린다. 제주는 G3F·G1F를 막판으로 고정한다. 그 파서로 다시 받으면 이 문서의 구분보다 나빠진다.

## 4. 남은 문제

합이 0.2초를 넘는 G3F·G1F 쌍은 14개다. 전부 부산이다. 반올림이 아니다. 공식 기록은 0.1초 단위이고, 반올림으로 생기는 차이는 0.2초 안에 들어온다. 해당 28개 원천행은 `quality_issue.pair_mismatch`로 표시돼 기본 조회에서 제외되지만 삭제되지 않았다.

| 경주 | 내용 | 차이 |
|---|---|---|
| 2009-11-29 부산 1경주, 1,000m, 10두 | G1F. 연구 DB 누적+막판 | 전부 +0.3초 |
| 2009-12-18 부산 5경주, 1,200m, 2두 | G3F. 연구 DB 누적+막판 | +0.7초, −0.7초 |
| 2017-03-03 부산 3경주 1두 | G3F. 연구 DB의 누적 + 막판 | −0.9초 |
| 2017-03-03 부산 8경주 1두 | G1F. 연구 DB의 누적 + 막판 | −0.3초 |

이 14쌍은 현재 KRA 웹 성적표에도 동일한 값과 완주기록으로 존재한다. `pair_adjudication`에 확인 근거를 남기고 기본 조회에서는 계속 제외했다. 지우거나 임의 정정하지 않았다. 적재 보고서의 3,480건은 수정 전 중복이 섞인 수다. 오류 건수로 쓰지 않는다.

그 밖에 뷰 밖에 남겨 둔 것:

- 출전과 연결되지 않은 부산 연구 원천 1,454행. 날짜·경주번호·마번으로 남아 있다.
- 거리가 없어 공식 구간 길이를 못 정한 segment 30행. 위 1,454행 안의 10두다.
- 시간 종류 미정은 현재 0행이다. 이전 미정 3행도 같은 출전의 부산 API 누적 필드로 확인됐다.
- 원천 간 0.2초 초과 충돌 36건 중 35건은 현재 KRA 웹의 해당 필드와 연구 DB 값이 같아 `source_adjudication` 근거를 남기고 기본 조회에 포함했다. 나머지 1건은 누적시간이 완주시간을 넘으므로 제외했다. 원래 `quality_issue`와 양쪽 원천값은 보존한다.
- 제주 2두의 G1F가 같은 말의 G3F보다 길다. 원문에도 있는 값이지만 물리적으로 모순이므로 `closing_subset_violation` 네 행을 기본 조회에서 제외한다.
- 주로별 출발 경로 `track_by_distance`는 공식 경주로 설명을 옮긴 표다. 경주에서 측정한 값이 아니다.

말별 통과 순위는 운영 `race_section_results.position`에서 이 DB의 `section_time.position`과 `point_position`으로 복사했다. 기본 뷰에서 사용 가능한 순위는 957,365행이다. 경주 전체 대열과 주로빠르기는 이 DB에 없고 운영 `race_passing_summaries`에 있다. 주로빠르기 ①–⑤만 `tempo_level`로 바뀌고, 서울·부산의 ⑥–⑨는 `tempo_raw`에만 있다.

## 5. 다시 만들 때

깨끗한 환경에서 두 원천 DB를 읽기 전용으로 사용해 검증본을 만들고, 보관 보고서·API JSON·현재 KRA 성적표를 대조해 최종본을 만든다. 결과 파일이 이미 있으면 덮어쓰지 않고 중단한다. 이전 `main`·`extend`·`repair` 명령은 중간 파일용이므로 사용하지 않는다.

```bash
.venv/bin/python scripts/build_section_point_db.py build-verified
PYTHONPATH=src .venv/bin/python scripts/adjudicate_section_points.py
.venv/bin/python -m pytest -q tests/test_section_point_db_builder.py tests/test_adjudicate_section_points.py
```

`data/research/`는 Git에서 제외된다. 다른 개발자는 약 1.3GB의 최종 결과 DB를 별도로 받거나 운영·연구 원천 DB, 보관 KRA 원문·API JSON과 KRA 웹 접근 권한을 갖춰 위 명령으로 재생성해야 한다. 이 문서·스크립트·테스트도 현재 Git 미추적 상태이므로 공유 전에 Git 반영 여부를 확인한다.

다음 수집은 부산 2026-09-12 이후만 대상이다. 누적·막판·구간 필드를 이름 그대로 저장한다. 전체 과거를 현재 파서로 다시 받지 않는다.
