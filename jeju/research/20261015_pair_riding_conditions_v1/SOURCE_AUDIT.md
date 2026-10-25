# 기승조건 비교 원천 감사

상태: read-only 원천·키·시간·고정 코호트 검증 완료. 후보 feature table, H1 모먼트, fit, H2 보정, 평가 예측·성과는 아직 생성하지 않았다.

## 시작 원천과 사용 분리

- 실제 직전 출전과 말×현재 기수 경험 원천은 `20261008_horse_profile_baseline_v1/outputs_v2/source_snapshot.parquet`다. 전체 92,513행 중 저장 정의 `finish_position 1–89 또는 91/92`에 맞는 started 사건은 90,428행이며 2002-07-14~2026-09-19 범위다. 이 중 32,552건은 2017년 전, 57,876건은 2017년 이후이고 5,539건은 400m다. 완주·완전편성·8거리 조건으로 자르지 않는다. 보유 자료의 사건 수이며 평생 전체 기승 경력을 뜻하지 않는다.
- 이 스냅샷에는 기수 ID가 없으므로 `jeju/data/jeju_native_core.sqlite3`의 `race_result_rows.jockey_id`를 `api_record_id`로 결합했다. DB 연결은 SQLite `mode=ro`와 `PRAGMA query_only=ON`으로 열었다. 90,428 started 행이 모두 일대일로 연결됐다. `race_date`, `race_id`, `horse_id`, `horse_number`, 거리, 착순 불일치는 각각 0이다. 연결 기수 ID 누락·비6자리·`000000`·`999999` sentinel은 각각 0이다. 센티널·ID 결측을 처리하는 unknown 경로는 코드에도 유지한다.
- 같은 말·날짜의 started 중복 그룹은 0개였고, 말별 최대 하루 1회였다. 따라서 이 source cohort에서는 날짜만으로 직전 started 사건을 정할 때 당일 경주 순서 충돌이 없다. 실제 직전 출전은 대상별 `T−2` 이하의 전체 started 이력에서 찾는다. 직전 행의 기수 ID를 알 수 없으면 더 오래된 event ID로 건너뛰지 않는다.
- 신규 365일 기수 성과 delta만 기존 [`starts.csv`](../20261009_jockey_effects_v1/input01/starts.csv) 계약(52,155행, 5,206경주, 2017-01-13~2026-09-19, 800/900/1000/1110/1200/1300/1400/1610m 정상완주·완전편성)으로 한정한다. `api_record_id` 연결한 전체 52,155행의 기수 ID·말 ID·날짜·경주 ID가 현재 native 원천과 모두 일치했다. 현재·직전 기수 성과의 분모가 같은 모집단이다.
- 기존 말 점수/roster는 frozen STYLE6 출력과 기존 pair-ID 결과를 읽기 전용으로 참조한다. pair-ID saved evaluation은 76,848 unordered pair, 1,779경주, 269경주일이며 선택 적중 438/1,779다. 공식 말 ID·`api_record_id`로만 조인한다. 신규 특징은 점수 생성이나 기존 60열 입력을 바꾸지 않는다.

## 기본 analysis view 정합과 절단 진단

현재 기본 `jeju_race_analysis_2026`와 `race_result_rows`를 2026년 started 사건 48건(고정 표본 seed `20261015`, 경주일·만남/경주/마번 키)에서 대조했다. 모든 48건의 event `api_record_id`, 말 ID, 거리, 기수 ID가 native 행과 일치했고 불일치는 0이다. 전체 view를 반복 조회하지 않았다. 분석 roster 전체는 기존 평가 입력 17,412 runner이며, 대상 경주일 하루 전(T−1)에 같은 말의 started 기록이 있는 runner/경주는 0/0건이었다. T−1 기록은 새 피처에 사용하지 않는다.

모든 신규 history cutoff는 날짜 기준 `target race_date − 2 calendar days`이고 T−2 날짜를 포함한다. 기존 rolling helper와 같은 365일 창 `(T−2−365 days, T−2]`을 쓴다. 경주 결과 최초 공개 timestamp, 당시 기수 배정 공개 timestamp와 정정 시각은 저장 자료에서 확인되지 않는다. 따라서 T−2 날짜 절단도 그 정보가 실제 당시 공개됐다는 증거는 아니다.

## 기존 평가·시간분할 잠금

기존 `20261012_pair_jockey_id_v1` saved prediction을 기준 비교로 고정한다. 평가 경주 수는 2024/2025/2026에 637/654/488, 경주일은 합계 269다. 기존 H1 2,147/2,818/3,458, H2 336/311/325, 2일 purge, 전체 20 style + current rider365 1 + H1-only ID39 구조를 유지한다. 후보는 이 60열에 사전 고정한 기승조건 10열을 추가한다. 2026년은 9월 19일까지의 부분연도이며 반복 개발자료다.

확인하지 않은 정보: 당시 등록 출전집합, 사전 배정 상태, event 기록의 최초 공개·정정 timestamp. 신규 공개 자료 수집은 하지 않았다. 비정상 결과·동착·결측 처리와 Top3 pair label은 기존 pair-ID 평가 계약을 상속한다.

## 파일 해시

아래 파일 해시는 `SOURCE_HASHES.json`에 기록했다. 원천 snapshot hash는 기존 preparation receipt와 일치한다. 해당 receipt의 원래 DB hash(`a878a40f…`)와 이 감사 시점에 한 번 streaming hash한 DB hash(`c52d2ab9…`)는 다르다. 따라서 receipt 시점의 DB 상태를 추정하지 않는다. 현재 DB를 읽기 전용으로 대조한 90,428행 결과와 기본 view 표본을 확인 근거로 삼는다.

이제 최초 event-rider 추출을 할 때만 현재 DB hash를 한 번 더 검사하고, 추출 행을 study-local `source_started_event_rider.parquet`에 동결한다. 추출 receipt에는 검사 시점 DB hash와 추출 parquet의 SHA·행 수를 함께 저장한다. feature 작성, preflight, fit, prediction은 DB를 다시 읽지 않고 동결 cache만 읽는다. 이후 shared DB 전체 hash가 바뀌어도 동결 cache의 hash/행키와 상류 snapshot hash가 일치하면 피처 원천은 그대로 유지되며, DB 변경 자체의 원인 확인은 별도 read-only 감사로 한다.
