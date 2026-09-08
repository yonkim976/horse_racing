# 2026-08-25 작업 총정리

기준 시각: **2026-08-25 19:45 KST**  
이 문서는 당일(및 직전 연속 작업)에 구현·수집·문서화한 내용을 한곳에서 본다.
일상 운영·전체 이력은 [CURRENT_STATUS](CURRENT_STATUS.md), 명령어는
[DATA_AND_OPERATIONS](DATA_AND_OPERATIONS.md), 원천 목록은
[DATA_SOURCE_CATALOG](DATA_SOURCE_CATALOG.md)를 본다.

---

## 1. 한줄 요약

경주 일정·결과·구간·배당 MVP에 이어, **말 이력(레이팅·체중·훈련·진료·프로필)** 과
**변경·건강·심판(기수변경·출전취소·장구·등급·출발훈련·심판리포트)** 수집기·스키마·대시보드
UI까지 붙였다. 2025·2026 체중·훈련·진료 백필은 완료. 보강 데이터(기수변경 등) 2025·2026년
전량 백필도 **완료**했다.

---

## 2. 구현 완료 (코드)

### 2.1 마이그레이션

| Revision | 내용 |
|---|---|
| `20260825_0004` | `horse_rating_snapshots`, `horse_weight_history`, `horse_training`, `horse_medical` |
| `20260825_0005` | `horses` 프로필 컬럼 + `horse_profile_snapshots` |
| `20260825_0006` | `jockey_changes`, `race_scratches`, `entry_equipment`, `horse_grade_changes`, `horse_start_training`, `race_steward_reports` |

적용: `uv run alembic upgrade head` (로컬 DB head = `20260825_0006`)

### 2.2 LIVE API 수집기 (신규·확장)

| 데이터 | Endpoint | CLI | 테이블 |
|---|---|---|---|
| 레이팅 | `/API77/raceHorseRating` | `collect-ratings` | `horse_rating_snapshots` |
| 체중 | `/API25_1/entryHorseWeightInfo_1` | `collect-weights` / `backfill-weights` | `horse_weight_history` |
| 일별훈련 | `/API18_1/dailyTraining_1` | `collect-training` / `backfill-training` | `horse_training` |
| 진료 | `/API16_1/raceHorseClinic_1` | `collect-medical` / `backfill-medical` | `horse_medical` |
| 경주마 상세 | `/API8_2/raceHorseInfo_2` | `collect-horse-profiles` | `horses` + `horse_profile_snapshots` |
| 기수변경 | `/API10_1/jockeyChangeInfo_1` | `collect-jockey-changes` / `backfill-…` | `jockey_changes` |
| 출전취소 | `/API9_1/raceHorseCancelInfo_1` | `collect-scratches` / `backfill-…` | `race_scratches` |
| 장구·폐출혈 | `/API24_1/horseMedicalAndEquipment_1` | `collect-equipment` / `backfill-…` | `entry_equipment` |
| 등급변동 | `/raceHorseRatingChangeInfo_2/...` | `collect-grade-changes` | `horse_grade_changes` |
| 출발훈련 | `/API22_1/startingTranning_1` | `collect-start-training` / `backfill-…` | `horse_start_training` |
| 심판리포트 | `/API215/JudgeReport` | `collect-steward-reports` / `backfill-…` | `race_steward_reports` |

부가 동작:

- 출전취소 적재 시 매칭 `race_entries.scratched = true`
- 장구 적재 시 매칭 `race_entries.equipment` 보강
- 경마장명 **`영남`·`부경` → meet 3(부산경남)** 별칭 (훈련·진료·심판리포트 등 파서)

### 2.3 대시보드 UI

서버: `uv run --group web horse-racing serve-dashboard` → `http://127.0.0.1:8000`

> 2026-08-26에 다크 퍼스트 디자인·테마 토글·차트/테이블 인터랙션을 개편했다.
> 시각·조작은 [SESSION_SUMMARY_2026-08-26](SESSION_SUMMARY_2026-08-26.md),
> 아래 표는 화면·데이터 범위다.

| 화면 | URL | 표시 내용 |
|---|---|---|
| 경주 목록 | `/` | 일정·결과 (기존) |
| 경주 상세 | `/races/{id}` | 결과, 구간차트, **기수변경·출전취소·장구·심판리포트**(해당 경주 데이터 있을 때) |
| 말 상세 | `/horses/{id}` | 프로필, 출전이력, **레이팅·체중·훈련·진료·등급·장구·출발훈련·기수변경·출전취소** |
| 말/기수/조교사/마주 목록 | `/horses`, `/jockeys`, … | 목록·검색 (말 목록에 이력 coverage) |

샘플(데이터 있는 경우):

- 말: http://127.0.0.1:8000/horses/1
- 경주(심판 등): http://127.0.0.1:8000/races/1

### 2.4 테스트

`tests/test_horse_history.py`, `tests/test_race_supplemental.py` 등. 관련 묶음 검증 시
`uv run pytest tests/test_race_supplemental.py tests/test_dashboard.py tests/test_horse_history.py -q`

---

## 3. 데이터 적재 현황 (DB 스냅샷)

확인 시각: 2026-08-25 ~16:10 KST  
DB: `data/horse_racing.sqlite3` (~631MB+) · Raw: `data/raw` (~956MB+)

### 3.1 기준·경주 (기존 MVP, 변동 없음 전제)

| 항목 | 대략 |
|---|---:|
| horses | 18,673 |
| race_section_results | 228,693 |
| 2025·2026 결과·배당·구간 | 이전 백필 완료 (구간 미완료 이슈는 CURRENT_STATUS 참고) |

### 3.2 말 이력 — 백필 **완료**

| 테이블 | 전체 | 2025 | 2026 | 비고 |
|---|---:|---:|---:|---|
| `horse_rating_snapshots` | 17,520 | — | — | 스냅샷(일자 백필 아님) |
| `horse_profile_snapshots` | 4,055 | — | — | 현역만 (`act_gubun=y`) |
| `horse_weight_history` | 43,243 | 26,076 | 17,167 | 2025·2026 백필 완료 |
| `horse_training` | 729,022 | 439,581 | 289,441 | 2025·2026 백필 완료 |
| `horse_medical` | 169,312 | 86,401 | 82,911 | 2025 로그 written 90,499 / DB 86,401 (재실행·upsert 차이 가능) |

로그:

- `data/logs/backfill-history-2025-full.log` — **ALL COMPLETE** (체중→훈련→진료)
- `data/logs/backfill-history-2026-full.log`, `data/logs/backfill-training-medical-2026.log`

### 3.3 보강 데이터 — 2025·2026 백필 **완료** (2026-08-25 19:44)

| 테이블 | 전체 | 2025 | 2026 | 상태 |
|---|---:|---:|---:|---|
| `horse_grade_changes` | 13,097 | — | — | 서울 5,203 / 제주 4,167 / 부산 3,727 |
| `entry_equipment` | 43,243 | 26,076 | 17,167 | 경주일 전량 (2025 294/294 meet-day) |
| `horse_start_training` | 67,577 | 42,126 | 25,451 | 달력일 전체 |
| `jockey_changes` | 854 | 526 | 328 | 발생일만 행 존재 |
| `race_scratches` | 512 | 303 | 209 | 발생일만 행 존재 |
| `race_steward_reports` | 4,111 | 2,481 | 1,630 | 경주일 전량 (2025 294/294 meet-day) |

로그:

- 2026: `data/logs/backfill-supplemental-2026.log` — 15:45 재개 → 16:03 ALL COMPLETE, 부산 심판 16:07
- 2025: `data/logs/backfill-supplemental-2025.log` — **19:22 START → 19:44 ALL COMPLETE** (실패 없음)

파서 보완: `hrName=None` → `(이름없음)`, 경마장 별칭 **`부경` → meet 3**.
기수변경·출전취소·장구·심판은 DB에 경주가 있는 날만 API 호출.

---

## 4. 결정·문서화된 정책

### 4.1 현역 / 비현역 (`act_gubun`)

- `y`(기본): 현역 → `collect-horse-profiles`
- `n`: 비현역 → `collect-horse-profiles --include-inactive`
- DB에 `is_active` 컬럼 없음. 통산·올해 성적은 **수집 시점 스냅샷**(과거 feature JOIN 시 누수)

### 4.2 배당 UI

- 실시간/확정배당 **대시보드 고도화는 보류**. 확정배당은 DB 적재만 (학습 feature 금지)

### 4.3 우선순위(당일 합의)

1. ~~말 상세 API~~ 완료  
2. ~~기수변경·출전취소·장구~~ 코드 + **2025·2026 백필 완료**  
3. ~~등급변동~~ 서울·제주·부산 적재. 기수/조교사 상세는 403  
4. ~~출발·심판~~ 코드 + **2025·2026 백필 완료**. 수영·언덕은 403  

---

## 5. PENDING (활용신청 / 미구현)

| 항목 | 상태 | 비고 |
|---|---|---|
| 기수 상세 `API12_1` | 403 | 활용신청 후 |
| 조교사 상세 `API19_1` | 403 | 활용신청 후 |
| 수영 `API144` | 403 | 활용신청 후 |
| 언덕훈련 | PENDING | endpoint·신청 재확인 |
| 비현역 프로필 전량 | 미실행 | `--include-inactive` (건수 큼) |
| Text 자료실 importer | 미착수 | ROADMAP Phase 2 |
| feature / 모델 / leakage | 미착수 | ROADMAP Phase 3+ |

---

## 6. 주요 파일 지도

```text
migrations/versions/20260825_000{4,5,6}_*.py
src/horse_racing/collectors/kra_api.py          # endpoint 상수
src/horse_racing/parsers/horse_history.py
src/horse_racing/parsers/race_supplemental.py
src/horse_racing/services/horse_history.py
src/horse_racing/services/race_supplemental.py
src/horse_racing/cli.py                         # collect-* / backfill-*
src/horse_racing/web/entities.py                # 말 상세 이력
src/horse_racing/web/race_page.py               # 경주 상세 보강
src/horse_racing/web/templates/entity_detail.html
src/horse_racing/web/templates/race_detail.html
tests/test_horse_history.py
tests/test_race_supplemental.py
docs/DATA_SOURCE_CATALOG.md                     # LIVE 표 갱신
docs/ROADMAP.md                                 # 1.3·1.4 체크
docs/DATA_AND_OPERATIONS.md                     # API·명령
```

---

## 7. 다음에 할 일 (짧은 체크리스트)

1. 활용신청 완료 시: 기수/조교사 상세, 수영, 언덕
2. ROADMAP: Text 자료실 / Parquet / leakage-free feature

---

## 8. 관련 문서

| 문서 | 역할 |
|---|---|
| [CURRENT_STATUS](CURRENT_STATUS.md) | 전체 데이터·개방 이슈·장기 이력 |
| [DATA_AND_OPERATIONS](DATA_AND_OPERATIONS.md) | 설치·CLI·복구 |
| [DATA_SOURCE_CATALOG](DATA_SOURCE_CATALOG.md) | 원천 API 카탈로그 |
| [ROADMAP](ROADMAP.md) | 다음 단계 |
| [BLUEPRINT](BLUEPRINT.md) | 목표 설계 |
