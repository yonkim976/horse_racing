# 현재 상태와 작업 이력

기준 시각: **2026-08-28** (`sync-latest` 이후 비현역 프로필과 2015~2024 Text 결과 적재 포함)

> **완료 vs 다음 작업:** [PROGRESS](PROGRESS.md)<br>
> **수집·백필·UI:** [SESSION_SUMMARY_2026-08-25](SESSION_SUMMARY_2026-08-25.md)<br>
> **대시보드 디자인:** [SESSION_SUMMARY_2026-08-26](SESSION_SUMMARY_2026-08-26.md)

## 1. 한눈에 보기

로컬 데이터 플랫폼(수집·정규화·대시보드)에 더해, **누수 없는 학습 파이프라인,
기준 모델(B0~B3), M4 LightGBM·CatBoost·앙상블까지 붙어 있다.** M5 Gate G1은
PASS했지만 M6 Gate G2는 시장 대비 증분 신호가 없어 FAIL했다.

- GitHub 저장소 연결 및 `main` 브랜치 푸시 완료
- SQLite/Alembic 정규화 스키마 (`20260828_0009` head, 주행심사·불변 예측 원장 포함)
- 공식 KRA OpenAPI **다수 LIVE 통합** (일정·출발번호·결과·구간·배당 + 말 이력 + 보강 6종)
- 원본 응답 파일과 수집 메타데이터 보존
- 2025·2026 결과·확정배당·구간기록 백필 완료 (구간 일부 API 공백은 아래 개방 이슈)
- FastAPI 로컬 대시보드: 공식 경주·주행심사 통합 달력, 두 이벤트의 별도 상세,
  말·기수·조교사·마주, 원천별 최신화 현황 `/data-status`
- `sync-daily`와 전체 원천 통합 `sync-latest` 구현
  (운영은 수동 수집 기본; launchd는 Desktop TCC로 등록 해제)
- 2026-08-27 `sync-latest` 실운영 검증: 수집 15단계 전부 성공, 관계자 링크 1건 복구·
  원천 정보가 부족한 2건은 추정 연결 없이 미해결 유지
- 말 이력 백필: **2025·2026 체중·훈련·진료 완료**, 레이팅·현역 프로필 스냅샷 적재
- 보강 데이터: **수집기·UI 완료**, 2025·2026 전량 백필 **완료**
  ([SESSION_SUMMARY §3.3](SESSION_SUMMARY_2026-08-25.md))
- KRA OpenAPI·Text 자료실 카탈로그 문서화, `dacom23` 주행심사 수집·파싱 완료
- KRA Text `dacom11` 장기 결과 적재 완료: 2015~2024 원본 2,717파일,
  24,586경주·260,066출전/결과. 서울·제주·부산의 연도별 레이아웃 차이를 처리하고
  2026 API 중복 표본 97두 불일치 0건 확인
- **학습 데이터셋 `v2_trials`** (`build-dataset`): 42,495행 / 4,108경주,
  시작 30분 전 기준 108개 feature, 전일 18시 기준 103개 feature;
  주행심사 12개 포함, point-in-time join + 누수 카나리아
- **기준 모델 B0~B3** (`run-baselines`): valid log loss B2=0.2905 / 시장 B3=0.2540
  — 상세는 [PROGRESS](PROGRESS.md), [MODELING_ROADMAP](MODELING_ROADMAP.md)
- **M4 고정 후보**: 5-seed LightGBM + CatBoost 50:50 확률 앙상블, valid win log loss
  **0.2726** / AUC 0.7726 / ECE 0.0040, B2 대비 6.15% 개선
- **M5 Gate G1 PASS**: test win log loss **0.2845** / B1 0.3236 / B2 0.3034,
  ECE 0.0018; 서울·부산경남 조건 포함 6개 기준 전부 통과
- **M6 Gate G2 FAIL**: valid 시장 혼합회귀 β=-0.0006(p=0.503), test 시장/혼합
  log loss 0.270410/0.270415, 고정 EV 기준 test 베팅 0건
- **경로 B 원장 MVP**: `prediction_runs`·`model_predictions`·정산/결과 테이블,
  SQLite 수정·삭제 방지 trigger, 발행·자동정산 CLI, `/predictions`·JSON API 구현
- **예정 경주 실추론·발행**: label-free anchor feature frame, 108-feature 계약 검사,
  고정 앙상블 추론·확률 일관성 보정·원장 발행을 `predict-and-publish` 한 명령으로 연결.
  2026-08-28 첫 live 기록 **16경주 / 163출전**, hash 재검증 완료

아직 없는 것: T-30분 직전 당일정보 재수집·경주별 자동 발행 scheduler,
`dacom11` 이외 Text 대량 importer, 실시간 배당 스냅샷.
수영·언덕·기수/조교사 상세는 **403 PENDING**.

## 2. 로컬 DB 현황

DB 파일: `data/horse_racing.sqlite3`<br>
DB 크기: 약 **816MB** (2026-08-28)<br>
Raw: `data/raw` 약 **1.2GB**

출발번호: `race_entries.gate_number` **43,977/43,977 저장, 결측 0**. API78 표본
300행에서 기존 출주번호·마명과 전부 일치했고, 신규 일정 수집 때마다 재검증한다.

### 경주 데이터

| 범위 | 경마장·경주일 | 경주 | 출전 | 결과 | 배당 행 |
|---|---:|---:|---:|---:|---:|
| 2015~2024 Text 완료 경주 | 2,717 | 24,586 | 260,066 | 260,066 | 518,830 |
| 2025 완료 경주 | 294 | 2,481 | 26,076 | 26,076 | 3,018,487 |
| 2026 완료 경주, 08-21까지 | 196 | 1,630 | 17,047 | 17,047 | 1,937,104 |
| 2026-08-22~23 일정 | 4 | 34 | 340 | 0 | 0 |

2015~2024 `dacom11` 적재 검증(2026-08-28): 파싱 오류·경주 자연키 중복·경주 내
출전번호 중복·외래키 오류가 모두 0건이다. 공식 마번 연결은 260,057/260,066건이었고,
공식 프로필에서 찾지 못한 `마이공주`의 9회 출전만 하나의 결정적 `text:` ID로 연결했다.
과거 성적표에는 정확한 예정 출발시각이 없으므로 `scheduled_at_ms`는 비어 있다.
`start_minus_30m` 시점 데이터셋에 쓰려면 `dacom01` 출전표로 시간을 보강해야 하며,
그 전에는 날짜 기반 `day_before_18` 정책으로만 과거 train 구간을 확장한다.

### 말 이력·보강 (2026-08-25 DB)

| 테이블 | 행 수 | 상태 |
|---|---:|---|
| `horses` | 18,673 | — |
| `horse_rating_snapshots` | 17,520 | 스냅샷 |
| `horse_profile_snapshots` | 4,055 | 현역만 |
| `horse_weight_history` | 43,243 | 2025: 26,076 / 2026: 17,167 |
| `horse_training` | 730,731 | 2025: 439,581 / 2026: 291,150 |
| `horse_medical` | 170,025 | 2025: 86,401 / 2026: 83,624 |
| `horse_grade_changes` | 13,097 | 서울 5,203 / 제주 4,167 / 부산경남 3,727 |
| `entry_equipment` | 43,757 | 2025: 26,076 / 2026: 17,681 |
| `horse_start_training` | 67,937 | 2025: 42,126 / 2026: 25,811 |
| `jockey_changes` | 854 | 2025: 526 / 2026: 328 (발생일만 행 존재) |
| `race_scratches` | 512 | 2025: 303 / 2026: 209 (발생일만 행 존재) |
| `race_steward_reports` | 4,111 | 2025: 2,481 / 2026: 1,630 |
| `race_section_results` | 228,693 | 2025·2026 백필 완료 |
| `running_trials` | 845 | 2025-01-02~2026-08-27, 세 경마장 |
| `running_trial_results` | 8,480 | 말 연결 8,463 / 미연결 17 (99.8% 연결) |

### 구간기록 (2025·2026)

원천: `API4_3/raceResult_3` → `race_section_results`<br>
완료 판정(`section_day_is_stored`)은 정상 착순·착순 미정만 분모에 넣고, 특수 코드
(`finish_position` ≥ 90: 경주제외·출전취소·주행중지·경주취소)는 제외한다.

| 연도 | 적재 행 | 완료 경마장·일 | 미완료 | 비고 |
|---|---:|---:|---:|---|
| 2025 | **138,514** | 291 / 294 | **3** | 아래 부분 공백. 전원 수집 시도 완료 |
| 2026 | **89,254** | 194 / 198 | **4** | 아래 API 원천 공백 4건 + 취소 3일은 정상 결측 |
| 합계 | **227,768**+α | — | 7 | DB 합계는 이후 소량 증가 가능 |

2025 백필: `20250101~20251231`, 경주일 294 전부 신규 수집, 소요 약 38분 (2026-08-23).

#### 개방 이슈 A: 2026-07-06·07 API4_3 구간값 전부 미제공

확인일: 2026-08-23. 강제 재수집과 live API 재조회 모두 구간값이 0.
`backfill-sections`가 이후에도 재시도한다.

| 날짜 | 경마장 | meet | API 행 | covered/expected | 비고 |
|---|---|---:|---:|---|---|
| 2026-07-06 | 서울 | 1 | 82 | 0/82 | 일부 착순 `NULL`, R7만 정상 착순 |
| 2026-07-06 | 부산경남 | 3 | 33 | 0/33 | 국제 트로피 경주일, 착순 전부 `NULL` |
| 2026-07-07 | 서울 | 1 | 65 | 0/64 | 정상 착순 있음, 구간값만 공백 |
| 2026-07-07 | 제주 | 2 | 40 | 0/40 | 정상 착순 있음, 구간값만 공백 |

인접일(예: 2026-07-05 서울)은 동일 API에서 구간값이 정상이다.

```bash
uv run horse-racing collect-race-sections --date 20260706 --meet 1
uv run horse-racing collect-race-sections --date 20260706 --meet 3
uv run horse-racing collect-race-sections --date 20260707 --meet 1
uv run horse-racing collect-race-sections --date 20260707 --meet 2
```

#### 개방 이슈 B: 2025 일부 경주(R6) 구간값·착순 공백

확인일: 2026-08-23. 해당 경마장·일의 다른 경주는 적재됐고, **특정 경주만** API 구간값이
비어 있으며 DB 착순도 `NULL`이다. 수집기 매칭 실패는 아님.

| 날짜 | 경마장 | meet | 누락 | covered/expected | 비고 |
|---|---|---:|---:|---|---|
| 2025-12-13 | 제주 | 2 | 12 | 50/62 | R6 전원 착순 `NULL`, 구간값 0 |
| 2025-12-20 | 제주 | 2 | 8 | 49/57 | R6 전원 착순 `NULL`, 구간값 0 |
| 2025-12-26 | 부산경남 | 3 | 12 | 91/103 | R6 전원 착순 `NULL`, 구간값 0 |

```bash
uv run horse-racing collect-race-sections --date 20251213 --meet 2
uv run horse-racing collect-race-sections --date 20251220 --meet 2
uv run horse-racing collect-race-sections --date 20251226 --meet 3
```

#### 정상 결측: 2026 제주 경주취소 3일

제주 `2026-03-20`, `2026-03-21`, `2026-04-04`는 전원 `ord=99` / AI `rk=경주취소`라
구간기록이 없는 것이 정상이다. 완료 판정에서는 특수 코드로 분모 제외되어 **완료**로 본다.

2025년 공식 결과 제공 범위는 2025-01-03~2025-12-28이다. 2025년 저장된 294개
경마장·경주일 모두 확정배당 완료 이력이 있으며 누락일은 0개다.

### 기준 객체

| 객체 | 행 수 | 고유 공식 ID 수 | 중복 ID |
|---|---:|---:|---:|
| 말 | 5,092 | 5,092 | 0 |
| 기수 | 108 | 108 | 0 |
| 조교사 | 115 | 115 | 0 |
| 마주 | 767 | 767 | 0 |

경주 자연키 중복, 경주 내 출전번호 중복과 고아 결과는 모두 0건이다. 말과 기수 연결 결측은
0건이다.

원천 API가 조교사·마주 ID를 모두 생략한 취소 출전 1건이 남아 있다.

- 2025-01-26 서울 7경주, 5번 `히트파워` (`0045333`)
- AI 상세결과와 공식 경주기록 보조 API 모두 조교사·마주를 `null`로 반환
- 추정값을 넣지 않고 `trainer_id`, `owner_id`를 `NULL`로 보존

## 3. 구현된 수집 흐름

### 출전표

경주, 말, 기수, 조교사, 마주와 출전정보를 upsert한다. 숫자로 전달되는 마번의 앞자리 0을
보존하도록 정규화한다.

### 완료 경주일

다음 순서로 수집한다.

1. AI 경주계획
2. 출전표 상세정보
3. AI 경주결과
4. 경주상세결과
5. 전체 확정배당

### 미래 일정

결과가 없는 날짜는 경주계획과 출전표만 저장한다. 결과가 공개된 뒤 완료 경주 수집기로
동일 행을 갱신한다.

### Backfill과 장애 복구

- 날짜·경마장별 결과 존재 여부를 가볍게 확인한다.
- 이미 완료된 날짜는 자동으로 건너뛴다.
- 결과 본체와 확정배당 수집을 분리할 수 있다.
- 결과가 저장된 경주일에 한해 `API4_3/raceResult_3`로 말별 구간기록(S1F·코너·G3F·G1F)을
  `race_section_results`에 적재한다.
- HTTP 429는 전용 오류로 분류하고 일일 한도 초기화 후 이어받는다.
- 확정배당의 큰 페이지 크기를 지원해 호출량을 줄인다.
- 취소 행이 빈 관계자 값으로 기존 연결을 덮어쓰지 않게 한다.
- 동일 말의 다른 이력에서 관계자가 한 명으로 일관될 때만 누락 링크를 복구한다.

## 4. 구현된 대시보드

FastAPI + Jinja2 + 일반 JavaScript/CSS로 만든 로컬 대시보드가 있다.
실행: `uv run --group web horse-racing serve-dashboard` → `http://127.0.0.1:8000`

표시 데이터는 2026-08-25와 같다.

- 날짜 및 경마장 필터, 전체 경마장 필터
- 경주 일정과 완료 상태
- 출전마, 기수, 조교사, 부담중량, 체중과 레이팅
- 착순, 기록, 단승·연승 배당과 상금
- 경주 상세: 구간 차트, 기수변경·출전취소·장구·심판리포트
- 말 상세: 프로필·레이팅·체중·훈련·진료·등급·장구·출발훈련·변경 이력

2026-08-26에 시각·조작만 전면 개편했다. 상세는
[SESSION_SUMMARY_2026-08-26](SESSION_SUMMARY_2026-08-26.md).

- 다크 퍼스트 + 라이트 토글 (`localStorage` `hr-theme`)
- Pretendard / JetBrains Mono, 에메랄드·라임 포인트
- 테이블 컬럼 정렬, 요약 숫자 카운트업, 경주 상세 목차 스크롤 스파이
- 구간 차트: 곡선, 그리기 애니메이션, 테마별 팔레트

현재 대시보드는 상시 서비스가 아니라 명령으로 실행하는 로컬 개발 도구다.

## 5. 지금까지의 조사와 의사결정

### 한국 시장과 예측 서비스

- 한국에도 경마 데이터·예상·분석을 제공하는 사이트가 여러 곳 존재한다.
- 일부 서비스는 예상 순위나 추천마를 제공하지만, 말별 확률과 장기간 검증 원장을 공개하는
  경우는 제한적이다.
- 광고성 적중 사례보다 전체 경주 표본, 검증 기간, 배당 포함 여부와 사후 수정 가능성을 함께
  보지 않으면 적중률을 비교하기 어렵다.
- 우리 서비스는 단순 적중률보다 확률 calibration과 재현 가능한 기간 외 평가를 우선한다.
- 예측 사업자가 직접 베팅만 하지 않고 서비스를 판매하는 이유에는 수익의 반복성, 자본·변동성
  제한, 고객층 확대와 정보상품화가 있다. 서비스 판매 자체가 예측 우위를 증명하지는 않는다.

### 특허 조사

특허번호 `10-1976988`을 AI 경마 분석 관련 특허로 조사한 대화가 있었다. 다만 당시 조회한
청구항 원문과 출처 메모가 저장소에 보존되어 있지 않다. 이 특허를 제품 요구사항이나 회피설계
근거로 사용하기 전 KIPRIS 원문, 법적 상태와 독립 청구항을 다시 확인해 별도 조사 문서로 남겨야
한다.

### 레이스 중 위치 데이터와 영상

- 공개 API에서 말별 연속 GPS 좌표를 확보하지 못했다.
- 현재 공개 데이터로는 구간 기록, 코너 통과순위와 영상이 레이스 전개 분석의 현실적인 원천이다.
- 영상 분석은 카메라 보정, 말 식별, 가림 처리와 시간축 정렬이 필요해 별도 연구 단계로 미뤘다.
- 연속 위치·중계 원본·센서 데이터 제공 가능 여부는 KRA에 직접 문의하는 경로를 검토했다.

### 로컬 저장과 기술 스택

- 초기에는 로컬 저장으로 빠르게 데이터 구조와 품질을 검증하기로 했다.
- SQLite는 단일 개발자, 단일 머신 MVP에는 충분하다고 판단했다.
- Alembic은 DB 스키마 변경 이력, Polars는 컬럼형 처리, DuckDB는 로컬 분석 SQL, Parquet은
  분석·학습 데이터 교환 형식으로 선택했다.
- 프론트는 FastAPI가 HTML과 API를 제공하고 HTML/CSS/JavaScript를 사용하는 구조로 정했다.
- 동시 수집·다중 사용자·원격 운영 요구가 생기면 PostgreSQL로 이전한다.

### 공공데이터 API

- 공공데이터포털 API별로 개별 활용신청이 필요함을 확인하고 관련 신청을 완료했다.
- 서비스키는 `.env`의 `HORSE_RACING_DATA_GO_KR_SERVICE_KEY`로 관리하며 Git에서 제외한다.
- API301 확정배당은 개발계정 일일 3,000회 제한에 도달할 수 있어 결과와 배당 백필을 분리했다.
- 전체 공식 소스 목록, 상태 구분과 다운로드 절차는
  [DATA_SOURCE_CATALOG](DATA_SOURCE_CATALOG.md)에 정리했다.

## 6. Git 작업 이력

| 커밋 | 내용 |
|---|---|
| `aefb5d6` | 프로젝트, SQLite/SQLAlchemy/Alembic 기본 구조 생성 |
| `4318d01` | 출전표 API 수집 및 정규화 구현 |
| `9332b9a` | 숫자 KRA 마번의 앞자리 0 정규화 |
| `f78e195` | 경주계획·결과·상세결과·확정배당 파이프라인 구현 |
| `2467b59` | 일정·결과 대시보드 구현 |
| `ad9d147` | 재개 가능한 결과 backfill과 일정 수집 구현 |
| `8aebe7e` | 대시보드 전체 경마장 필터 수정 |
| `686a5c3` | 배당 분리 backfill, 호출 한도 대응과 관계자 링크 복구 |

## 7. 품질 검증 결과

2026-08-22 기준 다음 검증을 통과했다.

- SQLite `PRAGMA integrity_check`: `ok`
- 2025 확정배당 완료 경마장·경주일: 294/294
- 공식 객체 ID 중복: 0
- 경주 자연키 중복: 0
- 경주 내 출전 자연키 중복: 0
- 고아 결과: 0
- Ruff: 통과
- pytest: 22개 통과

실패 이력은 원본 데이터 오류를 뜻하지 않는다. API 일일 한도, 네트워크 중단과 사용자가 중단한
시도도 `ingestion_runs`에 남긴다. 2025년 backfill 도중 프로세스가 중단되어 `running`으로 남은
확정배당 실행 이력 1건이 있으며, 해당 날짜의 후속 완료 이력과 데이터는 정상적으로 존재한다.
추후 stale run 정리 명령을 추가할 필요가 있다.

## 8. 아직 구현되지 않은 범위

우선순위와 다음 세션은 [PROGRESS](PROGRESS.md)를 본다.
수집 당일 완료분은 [SESSION_SUMMARY_2026-08-25](SESSION_SUMMARY_2026-08-25.md).

**다음 본업**

- G2 실패 경로 B: 예정 경주 `build-prediction-frame` + artifact 추론을 원장 발행에 연결

**데이터·운영 (파이프라인을 막지 않음)**

- KRA Text 다음 분류: `dacom01` 출전표, `dacom12` 체중, `dacom55` 훈련,
  `db7` 마명변경 이력
- 수영·언덕 훈련, 기수/조교사 상세 API (**403 PENDING** 활용신청 필요)
- 비현역 여부를 보존할 `horses.is_active` 및 이름 alias 테이블
- T3 훈련·진료 공개시점 실측
- 테이블별 Parquet export (학습 행렬은 `build-dataset`으로 이미 존재)
- 실시간 배당 snapshot / 배당 UI 고도화 — 지나간 시세는 복구 불가, 가능하면 조기 착수
- PostgreSQL 운영 전환
- 수집 실패 알림과 freshness 모니터링
- 웹 UI `SPECIAL_FINISH_LABELS`가 T6 실측 특수코드와 불일치 — UI 수정 필요

## 9. 말 이력 (레이팅·체중·훈련·진료·프로필)

구현·백필 요약은 [SESSION_SUMMARY §2–3](SESSION_SUMMARY_2026-08-25.md)과 동일하다.

| 테이블 | CLI | 원천 |
|---|---|---|
| `horse_rating_snapshots` | `collect-ratings` | API77 |
| `horse_weight_history` | `collect-weights` / `backfill-weights` | API25_1 |
| `horse_training` | `collect-training` / `backfill-training` | API18_1 |
| `horse_medical` | `collect-medical` / `backfill-medical` | API16_1 |
| `horse_profile_snapshots` (+ `horses` 프로필 컬럼) | `collect-horse-profiles` | API8_2 |
| `running_trials` + `running_trial_results` | `collect-running-trials` | KRA Text `dacom23` |

말 상세(`/horses/{id}`)에 프로필·레이팅·체중·훈련·진료 섹션을 표시한다.
통산·올해 성적은 수집 시점 스냅샷이며 과거 경주 feature로 그대로 JOIN하면 누수다.

### 현역 / 비현역 (`act_gubun`)

경주마 상세 API(`API8_2`)는 응답에 현역 플래그가 없고, 요청 파라미터 `act_gubun`으로 목록을 나눈다.

| 값 | 의미 | CLI |
|---|---|---|
| `y` (기본) | 현역 | `collect-horse-profiles` |
| `n` | 비현역 | `collect-horse-profiles --include-inactive` |

2026-08-28 비현역 수집 합계 **61,534**두(서울 28,348 / 제주 20,956 /
부산경남 12,230)를 추가 수집했다. DB에는 아직 `is_active` 컬럼이 없어 활성 여부 자체는
보존하지 않으며, 프로필 스냅샷과 공식 마번 연결 보강에 사용한다.
상세는 [DATA_SOURCE_CATALOG §4.1](DATA_SOURCE_CATALOG.md)을 본다.

### 백필 완료 요약

| 연도 | 체중 | 훈련 | 진료 | 로그 |
|---|---:|---:|---:|---|
| 2026 | 17,167 | 289,441 | 82,911 | `backfill-history-2026-full.log` 등 |
| 2025 | 26,076 | 439,581 | 86,401 | `backfill-history-2025-full.log` **ALL COMPLETE** |

훈련·진료 1차 시도는 API 경마장명 `영남`(부산경남) 미매핑으로 중단됐다가
`영남`·`부경` → meet 3 별칭 추가 후 재백필했다.

```bash
uv run horse-racing collect-ratings
uv run horse-racing collect-horse-profiles --meets 1 2 3
uv run horse-racing collect-weights --date 20260822 --meet 1
uv run horse-racing collect-training --date 20260820 --meet 1
uv run horse-racing collect-medical --date 20260820 --meet 1
```

## 10. 변경·장구·등급·출발·심판 (2026-08-25)

마이그레이션 `20260825_0006`과 수집 CLI·UI를 추가했다. **2025·2026 전량 백필 완료**.
표·재개 명령·PENDING API는 [SESSION_SUMMARY §3.3·§5](SESSION_SUMMARY_2026-08-25.md).

| 테이블 | CLI | UI |
|---|---|---|
| `jockey_changes` | `collect-jockey-changes` / `backfill-jockey-changes` | `/horses/{id}`, `/races/{id}` |
| `race_scratches` | `collect-scratches` / `backfill-scratches` | 동일 (+ `scratched` 플래그) |
| `entry_equipment` | `collect-equipment` / `backfill-equipment` | 동일 (+ `equipment` 보강) |
| `horse_grade_changes` | `collect-grade-changes` | `/horses/{id}` |
| `horse_start_training` | `collect-start-training` / `backfill-start-training` | `/horses/{id}` |
| `race_steward_reports` | `collect-steward-reports` / `backfill-steward-reports` | `/races/{id}` |

**403 PENDING:** 기수 상세 `API12_1`, 조교사 상세 `API19_1`, 수영 `API144`, 언덕훈련.

## 11. 주행심사 (2026-08-27)

마이그레이션 `20260827_0008`과 KRA Text `dacom23` 목록·다운로드 수집기, 세 경마장
보고서 파서를 추가했다. 2025-01-01~2026-08-27 범위를 전량 조회했다.

| 항목 | 값 |
|---|---:|
| 공식 원문 파일 | 249개 |
| 심사 경주 | 845개 |
| 말별 심사 결과 | 8,480개 |
| 기존 말 연결 | 8,463개 (99.8%) |
| 미연결 | 17개 |

서울·부산경남은 기본 1,000m, 제주는 보고서 제목의 800m를 저장한다. 판정 `합/불/유/연/출`
외에도 악천후 취소 `심`과 주행중지 `주`를 보존한다. 마체중 0은 실제 체중이 아닌 취소
표기이므로 `NULL`로 정규화한다. 보고서에는 공식 마번이 없어 경마장·이름을 우선 사용하고,
중복 이름은 성별·연령·생년까지 하나로 확정될 때만 연결한다. 미연결 17건은 추정 ID를 넣지
않고 `horse_name_raw`로 보존했다.

말 상세 페이지의 `주행심사` 탭과 `/running-trials/{id}` 전용 상세에서 판정·기록·구간·
검사사유를 조회할 수 있다. 통합 달력에는 보라색 점과 `주행심사` 배지로 공식 경주와
구분한다. 학습
파이프라인에는 과거 심사만 사용하는 feature 12개를 추가했다. 심사일과 경주일이 같으면 공개
시점을 확정할 수 없으므로 feature에서 제외한다. 2026-08-07~21 smoke 데이터셋 1,335행 중
580행에 최근 180일 심사가, 1,125행에 과거 심사 이력이 연결됐다.

전체 `v2_trials/start_minus_30m` 데이터셋은 42,495행 / 4,108경주 / 108 feature이며,
16,220행에 최근 180일 심사, 22,870행에 과거 심사 이력, 22,750행에 기록이 있는 과거
심사가 연결됐다. `day_before_18`은 동일 행에 당일 공개 체중 5개를 제외한 103 feature다.

```bash
uv run horse-racing collect-running-trials \
  --start 20250101 --end 20260827 --meets 1 2 3
```

다음 작업은 [PROGRESS](PROGRESS.md)와 [ROADMAP](ROADMAP.md)을 본다.
