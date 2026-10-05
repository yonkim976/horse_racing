# 2026 기준 제주마 분석 뷰 구현

## 상태

스키마와 분석 뷰를 로컬 제주 DB에 적용했고, 요청된 1회 재실행에서 idempotency를 확인했다. 재실행은 DB에 변경을 가하지 않았다. root의 전체 독립 검증 결과는 root가 별도로 기록한다.

## 분석 정책

- `horse_analysis_2026`: 최신 API42 프로필 이름과 말 ID를 연결하고, 검증된 프로필 출생연도에 대해 `age = age_2026 = 2026 - birth_year`를 제공한다. `age_reference_year`는 고정값 2026이며, 생년이 없거나 유효하지 않으면 파생 나이를 NULL로 둔다.
- `jeju_race_analysis_2026`: `jeju_race_candidate_passing_with_corner_rank`의 기존 열을 명시적으로 유지한다. 표시 마명은 최신 API42 이름을 사용하고 원래 경주 마명은 `historical_horse_name_raw`에 둔다. API4 경주 나이와 성별은 `age_at_race_raw`, `sex`/`sex_at_race_raw`로 남기고 현재 프로필 성별은 `sex_current_profile`로 따로 둔다.
- `jeju_trial_analysis_2026`: 명시 제주 주행심사 원천 열을 유지하며 최신 이름과 2026 기준 나이를 붙인다. API20 나이·성별은 `age_at_trial_raw`, `sex`/`sex_at_trial_raw`에 남긴다.
- 세 뷰는 프로필을 `LEFT JOIN`하고 관측 ID·시각·해시·원문 경로를 제공한다. 과거 API 원천 행은 갱신하지 않는다.
- 말 ID 3005897의 과거 API4 성별 `수`와 현재 API42 및 사전 API20 성별 `암`은 `provenance_issues`의 `open` 원천 충돌로 기록한다. 사용자의 지시에 따라 기존 원천 행을 유지하며 원인 미확정 상태를 함께 남긴다.

## 파일

- 스키마 변경: `jeju/data/schema/migrations/20261001_add_horse_analysis_2026.sql`
- 기본 스키마에도 동일 SQL 블록을 마지막에 추가했다.
- 적용 도구: `jeju/scripts/apply_horse_analysis_2026.py` (`--apply` 명시 전용)
- 적용 결과와 백업 해시는 적용 도구가 `application_manifest.json`에 기록한다.

## 적용 결과

- 프로필 뷰 4,617행, 경주 분석 뷰 92,513행, 주행심사 분석 뷰 15,738행으로 원천 행 수를 보존했다.
- API4 record 326의 토종등극 행에서 경주 원천 성별 `수`, 현재 프로필 성별 `암`, 경주 원천 나이 8, 고정 기준 마령 32를 함께 확인했다. 사전 API20 주행심사 원천 성별 `암`과 나이 8도 원형 열로 남겼다.
- 3005897 원천 충돌은 `status='open'`, `user_decision='retain_existing_record_without_correction'`, `cause_status='unconfirmed'`로 한 건 기록했다.
- SQLite backup은 `backups/jeju_native_core_before_horse_analysis_20261001.sqlite3`에 보존했다. 크기 595,075,072 bytes, SHA-256 `e34b7410db591d8219c5c2145dde177f7ff34cca1bb5ca11d0022d5ab331eb47`, integrity `ok`, FK 위반 0이다.
- 첫 적용 후 같은 명령을 한 번 재실행했다. manifest 결과는 `idempotency_verified`, 두 번째 실행의 `database_changed`는 `false`다.
- 적용 결과·시간·백업 경로와 SHA는 [application_manifest.json](application_manifest.json)에 기록했다.
