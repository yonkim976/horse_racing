# 경주결과 미연결 주행심사 후보 611마리: 나이·활동 기록 점검

기준일: 2026-09-30 KST. 추가 API 호출 없이 기존 공식 API 원문을 읽기 전용으로 대조했다. 대상은 `target_ids.jsonl`의 `api20_jeju_supplement` 611개 말 ID다. 이 ID들은 핵심 DB의 `jeju_race_population_candidates`에 경주결과 출전행이 없고, API20_1 주행심사에서 `majong=제주`가 관측됐다.

## 나이

- 611마리 모두 API20_1의 가장 최근 주행심사 원문에 `age` 값이 있다. 이는 **심사 당시 연령**이다. 마지막 심사일은 말마다 2002-07-19부터 2026-09-16까지 다르다.
- 마지막 심사가 2026년인 80마리의 당시 `age`는 2: 42마리, 3: 34마리, 4: 4마리다.
- 전체 마지막 심사 `age` 중 5건은 17·18·20·24·31이다. 원문값을 보존하되, 이 값이나 과거 `age`만으로 2026년 현재 나이를 계산하지 않는다.
- 기존 API42_1 일괄 표본에는 611마리 중 1마리(`hrNo=3107865`)만 포함된다. 그 조회 시점 프로필의 `birthDt=20230215`, `age=3`, `breed=제주마`, `useNm=경주용(휴양)`을 확인했다. 나머지 610마리의 API42_1 현재 프로필은 아직 조회하지 않았다.

## 2026년 활동 단서와 현역 여부

- API20_1 주행심사: 80마리에서 2026년 기록 확인.
- API22_1 출발조교: 80마리에서 2026년 기록 확인.
- API18_1 일별조교: 85마리에서 2026년 기록 확인(1–8월 월별 수집 및 9월 완결 표본, 최근 관측 2026-09-28).
- 세 자료의 2026년 기록이 있는 말 ID의 합집합은 **85마리**다. 나머지 **526마리**는 이 세 원천에서 2026년 활동이 확인되지 않았다.

활동 기록은 해당 날짜의 관측이며, 현재 경주마 등록·현역 상태를 뜻하지 않는다. 세 원천에는 611마리의 현재 현역 여부를 일괄 확정하는 필드가 없다. 2026년 기록이 없는 526마리를 은퇴마로 분류하지 않는다. API42_1의 기존 1마리 `경주용(휴양)` 표기도 조회 시점의 용도값으로만 보존한다.

## 근거

- API20_1: `jeju/data/jeju_native_core.sqlite3`의 `running_trial_rows` 및 `api_records.payload_json`의 `age`, `majong`.
- API22_1: `jeju/research/20260929_api_detail_sources/raw/full_year_clinic_judgement_start_training/20260929T150517.740550Z/starting_training/`.
- API18_1: `jeju/research/20260929_api_monthly_history/raw/daily_training/2026MM/` 및 `jeju/research/20260929_api_detail_sources/raw/samples/20260929T142137.341471Z/source_pages/daily_training_202609/`.
- API42_1 일괄 표본: `jeju/research/20260929_horse_breed_profile_api/attempts/20260929T140522.696450Z-probes/source_pages/bulk_page1_numRows20000.json`.
- [한국마사회 주행심사 상세결과 공식 안내](https://www.data.go.kr/data/15056974/openapi.do)는 제공 항목에 연령을 명시한다.

다음 API42_1 재개에서 611마리의 `birthDt`, `age`, 용도·입퇴사·휴양 관련 원문 필드를 조회해 현 시점 프로필을 별도로 검증한다. 원문 필드에 공식 현역 정의가 있는지는 추가 확인이 필요하다.
