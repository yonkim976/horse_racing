# 최신 마명·2026년 마령 분석 기준

2026-10-01 사용자 지시에 따른 로컬 제주 DB 분석 정책이다.

## 기본 조회

DB: `jeju/data/jeju_native_core.sqlite3`.

| 분석 뷰 | 대상 | 기본 이름·나이 |
| --- | --- | --- |
| `horse_analysis_2026` | 수집한 제주마 프로필 전체 | 최신 API42 마명 / 2026년 기준 마령 |
| `jeju_race_analysis_2026` | 기존 제주마 경주 후보와 API4·API303 통과착순 | 공식 말 ID로 연결한 최신 마명 / 2026년 기준 마령 |
| `jeju_trial_analysis_2026` | API20에 제주로 명시된 기존 주행심사 | 공식 말 ID로 연결한 최신 마명 / 2026년 기준 마령 |

- `horse_id`: 경주·심사·프로필의 연결키. 이름 문자열로 연결하지 않는다.
- `horse_name`: 최신 프로필명. 동방라오(ID `3107458`)도 무명전설로 조회한다.
- `age`, `age_2026`: **2026 − 현재 프로필 출생연도**.
- `age_reference_year`: **2026 고정**. 실행 날짜·경주 날짜에 따라 기준연도를 바꾸지 않는다.
- `historical_horse_name_raw`: 해당 경주·심사 원문 이름.
- `age_at_race_raw`, `age_at_trial_raw`: 경주·심사 API 원문 나이.
- `sex`: 경주·심사 당시 API 원천 성별을 유지한다.
- `sex_current_profile`: 현재 프로필 성별. 과거 이벤트 성별과 함께 조회한다.

2026년 기준 마령은 해당 말의 경주 당시 나이를 뜻하지 않는다. 예를 들어 토종등극은 현재 출생연도 1994년 기준으로 분석 나이 32세이고 2002년 경주 원문은 8세다. 강줄기·득점기록도 사용자 지정 기준에 따라 현재 API42 출생연도로 계산하며 과거 생년 정정 여부를 확정하지 않는다.

## 이름·성별 처리

최신 이름은 공식 말 ID를 통해 경주·심사에 연결하므로 개명 표기 차이로 이력이 끊기지 않는다. 당시 원천명과 최신 표시명이 모두 조회된다. 최신이란 DB에 적재된 프로필 중 조회시각이 가장 최근인 관측이며, 이 뷰가 API를 자동 재조회하는 것은 아니다.

토종등극(ID `3005897`)은 경주 API4_3 record `326`의 **수**를 유지한다. 현재 API42 및 API20 심사 관측은 **암**이고, 원천 충돌은 `provenance_issues`에 기록한다. 사용자 처리 결정은 **현행 유지·정정하지 않음**이다. 원래 오류 위치·사유는 미확정으로 남긴다.

원천 JSON, 경주·심사 정규화 원장, 기존 후보 판정과 기존 조회 뷰를 보존하며 새 분석 뷰에서 정책을 적용한다. 기존 통과착순과 API303 출처 열도 새 경주 분석 뷰에 포함한다.

## 조회 예제

```sql
SELECT race_date, race_number, horse_number, horse_id,
       horse_name, historical_horse_name_raw,
       age, age_reference_year, age_at_race_raw,
       sex, sex_current_profile
FROM jeju_race_analysis_2026
WHERE horse_id = '3107458'
ORDER BY race_date, race_number;
```

향후 제주 로컬 DB 분석의 기본 조회는 이 세 뷰다. `jeju/AGENTS.md`와 `jeju/README.md`에도 같은 기준을 기록했다. 저장된 과거 모델 입력의 재현은 원래 계약을 유지한다.

## 구현 및 검증 산출물

- `jeju/data/schema/migrations/20261001_add_horse_analysis_2026.sql`: 분석 뷰 정의.
- `jeju/scripts/apply_horse_analysis_2026.py`: 백업 및 정책 적용·재실행 검증.
- `before_snapshot.json`: 적용 전 기존 11개 테이블의 행 수·전체 행 SHA와 7개 뷰 정의.
- `application_manifest.json`, `implementation_report.md`: GPT-6 Luna xhigh의 적용 기록.
- `verify_analysis_policy.py`, `root_verification.json`: 주 에이전트의 별도 읽기 전용 전수 검증.

## 적용·독립 검증 결과

GPT-6 Luna xhigh가 적용했고 주 에이전트가 읽기 전용으로 전수 대조했다. 적용 수량은 말 **4,617두**, 경주 후보 **92,513행**, 명시 제주 심사 **15,738행**이다.

- 모든 분석 이름은 말 ID의 최신 API42 이름과 일치하고, 모든 `age`/`age_2026`는 현재 출생연도에서 계산한 2026년 마령과 일치한다. 연결 누락·중복은 0건이다.
- 경주 분석의 기존 75개 원천 열을 비교했다. 최신 표시명으로 바꾼 `horse_name`의 원래 값은 `historical_horse_name_raw`와 일치하고, 나머지 열·통과착순·API303 출처 열은 전부 원래 값과 일치한다. 심사 원천 열도 같은 방식으로 전수 통과했다.
- 경주·심사 원문 나이와 성별은 각각 이벤트 API 원문과 전부 일치한다.
- 기존 11개 테이블의 모든 기존 행을 적용 전 SHA와 비교해 보존을 확인했다. 기존 뷰 7개 정의도 그대로다. 정책 metadata 4행과 토종등극 원천 충돌 메모 1행만 추가됐다.
- 토종등극의 분석 조회: 이름 **토종등극**, 2026년 마령 **32**, 2002-12-14 경주 원문 나이 **8**, 원문 성별 **수**, 현재 프로필 성별 **암**. DB 메모에 사용자 결정 `retain_existing_record_without_correction`을 기록했다.
- 같은 적용 명령의 지정된 1회 재실행은 DB 변경 없이 통과했다. 무결성 `ok`, 외래키 위반 0건이다.

[주 에이전트 독립 검증](root_verification.json), [서브에이전트 적용 원장](application_manifest.json)에 상세 결과가 있다. 적용 전 백업은 `backups/jeju_native_core_before_horse_analysis_20261001.sqlite3`이며 SHA-256은 `e34b7410db591d8219c5c2145dde177f7ff34cca1bb5ca11d0022d5ab331eb47`이다.
