# 조교사 현역·국내 등록 종료 및 현재 이름 결정 — 2026-09-29

## 반영 범위

로컬 운영 SQLite와 Supabase `horse-racing-prod`에 같은 두 테이블을 추가했다.

- `trainer_status_observations`: 공식 `trNo`별 관측 시점, 현재 이름, 지역, 상태, 공식 종료일 및 API·은퇴 명단 근거. 2026-09-29 관측 59행.
- `trainer_identity_resolutions`: 이름 기반 `text:trainer:*` 임시 ID의 공식 `trNo` 연결, 당시 원문 이름과 최신 표시 이름, 근거 경주행 수 및 확정 여부. 65행.

2026-09-29 최초 적용에서는 기존 `trainers.name_ko`와 출전행을 변경하지 않고 연결표만 저장했다. 이후 사용자가 공식 성적표의 과거 기록도 최신 조교사 이름으로 표기된다고 확인하여, **확정된 11개 임시 조교사 행의 `trainers.name_ko`만 `canonical_name_ko`로 통일했다.** 이에 연결된 과거 출전행 3,574건은 기존 조교사 ID를 유지하면서 조회 시 최신 이름(이신우·윤영훈)을 표시한다. 당시 Text 원문 이름과 파싱 흔적은 `trainer_identity_resolutions.source_name_ko`에 보존된다. 출전행의 `trainer_id`, KRA 원문, 연구 산출물은 변경하지 않았다. 미확정 연결 54개는 이름을 바꾸지 않았다.

## 결정한 상태

| 공식 번호 | 현재 이름 | 지역 | 저장 상태 | 근거 |
|---|---|---|---|---|
| `070157` | 구자흥 | 서울 | `active` / 현역 | KRA 현역 웹 명단·API308 등록 종료일 없음. 별도 현역 API에서는 누락. |
| `070103` | 김윤섭 | 서울 | `active` / 현역 | 동일. |
| `070168` | 최용구 | 서울 | `active` / 현역 | 동일. |
| `070167` | 이신우 | 서울 | `active` / 현역 | 5개 임시 ID의 과거 2,239 출전행에서 공식 번호가 모두 같음. |
| `070133` | 윤영훈 | 영남 | `active` / 현역 | 6개 임시 ID의 과거 1,335 출전행에서 공식 번호가 모두 같음. |

`이신영` 계열 5개 임시 ID와 `윤영귀·윤주혁` 계열 6개 임시 ID는 `confirmed`로 저장했다. 임시 ID별 전체 운영 출전행 수가 보존된 공식 경주 결과 대조 자료의 행 수와 모두 같고, 각 임시 ID의 후보 공식 번호는 한 개뿐이다. KRA [이신우 프로필](https://race.kra.co.kr/trainer/profileTrainerPersonItem.do?Act=08&Sub=1&meet=1&trNo=070167), [윤영훈 프로필](https://race.kra.co.kr/trainer/profileTrainerPersonItem.do?Act=08&Sub=1&meet=3&trNo=070133)도 최신 이름을 뒷받침한다. 이름 앞의 `시`, `스`, `치` 같은 파싱 흔적까지 원본 이름으로 보존했다.

공식 종료일이 있으나 [KRA 은퇴 명단](https://race.kra.co.kr/trainer/profileTrainerListRetire.do?Act=09&Sub=1&meet=1)에 없는 공식 번호 54개는 `domestic_registration_ended` / **국내 등록 종료(은퇴 미확인)** 로 저장했다. 모두 API308 통산 20전 미만이다. 54개 Text 임시 ID는 각각 공식 번호 한 개와 경주행이 연결되지만, 사람의 생애 상태를 단정하지 않도록 `official_id_candidate`로 표시했다. 이는 `retired_confirmed`와 다른 상태이며, 해외에서 계속 활동하는지에 대해서는 주장하지 않는다.

## 향후 갱신 규칙

`trainer_status_observations`는 `(official_tr_no, observed_on)`별 관측 이력이다. 새 공식 자료에서 종료일이 확인되면 기존 `active` 관측을 지우지 않고 새 날짜 행을 저장한다. 종료일과 KRA 은퇴 명단 등재가 함께 확인되면 `retired_confirmed` / `은퇴 확정`, 종료일만 있으면 `domestic_registration_ended` / `국내 등록 종료(은퇴 미확인)`으로 분류한다. 최신 상태를 서빙할 때는 공식 번호별 가장 최근 `observed_on`만 사용한다. **자동 주기 갱신 작업은 이번에 설정하지 않았다.** 현재 2026-09-29 관측값을 최신 공식 자료와 다시 대조해야 상태가 바뀐다.

상태 분류가 전체 조교사 명단을 포괄하는 것은 아니다. 이번 표는 사용자가 결정한 예외·이름 변경·은퇴 명단 제외 그룹 59개 공식 등록에 한정한다. 기존 `trainer_affiliation_snapshots`와 `trainer_historical_regions`는 계속 원천 근거로 유지한다.

## 검증과 복구

- 로컬·Supabase 모두 상태 59행(`active` 5, `domestic_registration_ended` 54), 임시 ID 연결 65행(`confirmed` 11, `official_id_candidate` 54).
- 확정 연결의 경주행 합계 3,574행. 원래 `trainers` 653행과 `race_entries` 576,758행은 로컬 적용 전후 동일.
- 로컬 적용 전 SQLite 온라인 백업: `/private/tmp/horse_racing_trainer_status_20260929_pre.sqlite3`, `PRAGMA quick_check = ok`.
- 이름 통일 직전 별도 SQLite 온라인 백업: `/private/tmp/horse_racing_trainer_names_20260929_pre.sqlite3`, `PRAGMA quick_check = ok`.
- 이름 통일 후 로컬·Supabase 모두 이신우 계열 임시 ID 5개/출전 2,239행, 윤영훈 계열 6개/출전 1,335행의 표시 이름이 최신 이름이며, 별도 연결표의 원문 이름은 11개 모두 남아 있다. `trainers` 및 `race_entries` 행 수는 변하지 않았다.
- 로컬 Alembic `20260929_0024`; Supabase migration `20260929080214_trainer_status_and_identity`.
- 검증 명령: `PYTHONPATH=src:. .venv/bin/pytest -q tests/test_trainer_status_identity.py tests/test_trainer_affiliations.py tests/test_database.py`.
- 고정된 2026-09-29 근거의 재실행: `PYTHONPATH=src:. .venv/bin/python -m scripts.apply_20260929_trainer_status_identity --apply-local` (기본 실행은 읽기 전용 사전검사). 새로운 날짜 자료의 상태 갱신용 명령은 아직 아니다.
- 확정된 이름까지 통일하는 재실행 옵션: `--canonicalize-names`를 `--apply-local` 또는 `--apply-remote`와 함께 지정한다. 이미 통일한 행은 다시 변경하지 않는다.
