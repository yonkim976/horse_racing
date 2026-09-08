# 데이터 구조와 운영 가이드

최종 갱신: 2026-08-25

## 1. 현재 통합된 공식 API

| 데이터 | Endpoint | Operation | 주요 검색 조건 | 현재 용도 |
|---|---|---|---|---|
| AI 경주계획 | `/API154/racePlan` | `racePlan` | `rccrs_cd`, `race_dt` | 경주 일정·조건 |
| 출전표 상세 | `/API26_2/entrySheet_2` | `entrySheet_2` | `meet`, `rc_date` | 출전마·관계자·체중·레이팅 |
| AI 경주결과 | `/API155/raceResult` | `raceResult` | `rccrs_cd`, `race_dt` | 결과 존재 확인 및 기본 결과 |
| 경주상세결과 | `/API156/raceRsutDtl` | `raceRsutDtl` | `rccrs_cd`, `race_dt` | 상세 결과·상금·장구 |
| 전체 확정배당 | `/API301/Dividend_rate_total` | `Dividend_rate_total` | `meet`, `rc_date` | 승식별 최종 배당 조합 |
| 경주기록(구간) | `/API4_3/raceResult_3` | `raceResult_3` | `meet`, `rc_date` | 말별 구간기록 |
| 경주마 레이팅 | `/API77/raceHorseRating` | `raceHorseRating` | (전체) | 레이팅 스냅샷 |
| 출전마 체중 | `/API25_1/entryHorseWeightInfo_1` | `entryHorseWeightInfo_1` | `meet`, `rc_date` | 체중 이력 |
| 일별훈련 | `/API18_1/dailyTraining_1` | `dailyTraining_1` | `meet`, `tr_date` | 훈련 이력 |
| 마필진료 | `/API16_1/raceHorseClinic_1` | `raceHorseClinic_1` | `meet`, `clinic_date` | 진료 이력 |
| 경주마 상세 | `/API8_2/raceHorseInfo_2` | `raceHorseInfo_2` | `meet`, `act_gubun` | 프로필·혈통·통산 성적 |
| 기수변경 | `/API10_1/jockeyChangeInfo_1` | `jockeyChangeInfo_1` | `meet`, `rc_date` | 기수변경 |
| 출전취소 | `/API9_1/raceHorseCancelInfo_1` | `raceHorseCancelInfo_1` | `meet`, `rc_date` | 출전취소 |
| 장구·폐출혈 | `/API24_1/horseMedicalAndEquipment_1` | `horseMedicalAndEquipment_1` | `meet`, `rc_date` | 장구·폐출혈 |
| 등급변동 | `/raceHorseRatingChangeInfo_2/...` | `raceHorseRatingChangeInfo_2` | `meet`(선택) | 등급 이력 |
| 출발훈련 | `/API22_1/startingTranning_1` | `startingTranning_1` | `meet`, `tr_date` | 출발대 훈련 |
| 심판리포트 | `/API215/JudgeReport` | `JudgeReport` | `meet`, `rc_date` | 심판 판정 |

공통으로 페이지 번호와 페이지 크기를 사용한다. 출전표는 인증 파라미터 이름이 `ServiceKey`,
나머지 현재 통합 API는 `serviceKey`다. 서비스키는 공개 요청 메타데이터와 원본 파일명에 넣지
않는다.

경주마 상세의 현역/비현역은 응답 필드가 아니라 `act_gubun=y|n`으로 구분한다.
기본 수집은 현역(`y`)만 적재한다. 자세한 표와 건수는
[DATA_SOURCE_CATALOG §4.1](DATA_SOURCE_CATALOG.md)을 본다.

이 표는 **현재 코드에 통합된 API**만 나타낸다. 조사된 다른 KRA API가 모두 구현됐다는 뜻은
아니다. 전체 공식 원천과 다른 에이전트용 다운로드 절차는
[DATA_SOURCE_CATALOG](DATA_SOURCE_CATALOG.md)를 따른다.

## 2. 저장 흐름

```text
CLI
 ↓
KraApiClient: 요청, pagination, retry, 오류 분류
 ↓
Raw Store: data/raw 파일 저장 + SHA-256
 ↓
Pydantic Parser: 타입, 날짜, 시간, 체중, 주로 상태 정규화
 ↓
SQLAlchemy Service: 기준 객체 및 경주 데이터 upsert
 ↓
SQLite
```

한 페이지 처리의 원칙은 `원본 저장 → 파싱 → DB 반영 → 수집 이력 갱신`이다.

## 3. 파일 구조

```text
data/
├── horse_racing.sqlite3       정규화 DB
├── raw/kra/                   API 원본 JSON
├── raw/kra_text/dacom23/      주행심사 원본 CP949 RPT
│   ├── race_plan/
│   ├── entry_sheet/
│   ├── ai_race_result/
│   ├── detailed_race_result/
│   └── final_dividend/
├── parquet/                   향후 분석 데이터셋
└── exports/                   향후 외부 전달 결과물
```

Raw 경로는 데이터 종류/연/월/일/경마장/수집 실행/페이지 단위로 나뉜다. 로컬 데이터 전체는
Git에서 제외한다.

## 4. 현재 DB 관계

```text
racecourses 1 ── N races 1 ── N race_entries N ── 1 horses
                                      │
                                      ├── jockeys
                                      ├── trainers
                                      ├── owners
                                      ├── 0..1 race_results
                                      └── N race_section_results

races 1 ── N odds_snapshots

horses 1 ── N horse_rating_snapshots / weight_history / training / medical / profile_snapshots
       └── N grade_changes / start_training / jockey_changes / race_scratches / entry_equipment

race_steward_reports (meet + date + race_number)

ingestion_runs 1 ── N source_documents
```

### 테이블 책임

| 테이블 | 책임 |
|---|---|
| `ingestion_runs` | 데이터 종류별 수집 실행 상태와 처리 건수 |
| `source_documents` | 원본 경로, hash, endpoint, 공개 요청 파라미터와 시각 |
| `racecourses` | KRA 경마장 코드 기준정보 |
| `horses` | 공식 마번 기준 말 객체 |
| `jockeys`, `trainers`, `owners` | 공식 관계자 번호 기준 객체 |
| `races` | 경마장·날짜·경주번호 단위 일정과 조건 |
| `race_entries` | 경주×말 단위 출전 상태와 당시 관측값 |
| `race_results` | 출전별 최종 결과 |
| `race_section_results` | 출전별 구간 기록(S1F·코너·G3F·G1F 등). `API4_3/raceResult_3` 수집 |
| `odds_snapshots` | 경주·승식·선택조합·관측시각별 배당 |
| `horse_rating_snapshots` 등 말 이력 | 레이팅·체중·훈련·진료·프로필 스냅샷 |
| `jockey_changes` 등 보강 | 기수변경·출전취소·장구·등급·출발훈련·심판리포트 |

## 5. ID와 자연키

| 객체 | 외부 ID/자연키 |
|---|---|
| 경마장 | `kra_meet_code` |
| 경주 | 경마장 + 한국 날짜 + 경주번호 |
| 말 | `kra_horse_id` 문자열 |
| 기수 | `kra_jockey_id` 문자열 |
| 조교사 | `kra_trainer_id` 문자열 |
| 마주 | `kra_owner_id` 문자열 |
| 출전 | 경주 + 말, 경주 + 출주번호 |
| 결과 | 출전당 0 또는 1개 |
| 구간 | 출전 + 구간코드 |
| 배당 | 경주 + 승식 + 선택조합 + 관측시각 |

외부 ID는 숫자처럼 보여도 문자열이다. `0045333`과 같은 마번의 앞자리 0을 제거하면 안 된다.

## 6. 시간 의미

- `race_date_local`: 한국시간 기준 경주일
- `scheduled_at_ms`, `actual_start_at_ms`: UTC epoch milliseconds
- `requested_at_ms`, `retrieved_at_ms`: API 요청·수신 시각
- `observed_at_ms`: 배당 관측 시각

현재 API301 데이터는 **확정배당**이다. `observed_at_ms`가 경주 전 실시간 시세를 의미하지
않으므로 모델의 사전 feature로 사용할 수 없다. 시장 비교와 사후 backtest에만 사용한다.

## 7. 환경 설정

```bash
cp .env.example .env
```

```dotenv
HORSE_RACING_DATABASE_URL=sqlite:///data/horse_racing.sqlite3
HORSE_RACING_DATA_GO_KR_SERVICE_KEY=공공데이터포털_Decoding_인증키
```

`.env`는 절대 커밋하지 않는다.

## 8. 설치와 DB 초기화

```bash
UV_CACHE_DIR=/private/tmp/horse-racing-uv-cache uv sync --group dev --group web
UV_CACHE_DIR=/private/tmp/horse-racing-uv-cache uv run alembic upgrade head
UV_CACHE_DIR=/private/tmp/horse-racing-uv-cache uv run horse-racing db-info
```

현재 migration head는 `20260828_0009`이며, 불변 공개 예측·정산 원장 네 테이블을 포함한다.

### 공개 예측 원장

```bash
uv run horse-racing build-prediction-frame --run-id RUN_ID --date 20260828
uv run horse-racing predict-and-publish --run-id RUN_ID --date 20260828

# 외부 예측 파일을 직접 발행하는 저수준 경로
uv run horse-racing publish-predictions --run-id RUN_ID \
  --predictions-file FILE.parquet --feature-cutoff 2026-08-28T12:30:00+09:00
uv run horse-racing settle-predictions
uv run horse-racing list-predictions --mode live
uv run horse-racing verify-predictions --public-id UUID
```

`live` 발행은 feature cutoff와 실제 명령 실행시각이 모든 포함 경주의 모델 as-of 이전일 때만
성공한다. 전체 계약과
과거 검증 모드는 [PREDICTION_LEDGER](PREDICTION_LEDGER.md)를 본다.

## 9. 주요 수집 명령

### 하루 전체

```bash
uv run horse-racing collect-race-day --date 20260821 --meet 2
```

### 결과 기간 Backfill

```bash
uv run horse-racing backfill-results \
  --start 20260101 --end 20260821 --meets 1 2 3
```

### 결과와 배당 분리

API301 호출량이 많은 기간에는 결과 본체를 먼저 완료한다.

```bash
uv run horse-racing backfill-results \
  --start 20250101 --end 20251231 --meets 1 2 3 --skip-dividends

uv run horse-racing backfill-dividends \
  --start 20250101 --end 20251231 --meets 1 2 3 --page-size 10000
```

완료된 경마장·경주일은 자동으로 건너뛰므로 같은 명령을 재실행해도 된다. 공공데이터포털의
네트워크 접근이 제한된 실행 환경에서는 외부 네트워크 권한이 필요할 수 있다.

### 구간기록

결과가 이미 저장된 경주일에 한해 말별 구간기록을 적재한다. `sync-daily --mode results`에도
포함된다. 완료 판정은 정상 착순·착순 미정 출전을 대상으로 하며, 경주제외·출전취소·경주취소 등
특수 코드(`finish_position` ≥ 90)는 분모에서 제외한다.

상세 화면은 각 체크포인트에 `통과순위 / 구간기록 / 누적기록`을 함께 표시한다. 서울·부산
API의 G계열은 출발 후 누적 통과시각이지만, 제주와 Text 성적표의 G3F/G1F는 결승 기준
종반 구간기록이다. 화면 계층에서 이를 출발 기준 누적시각으로 정규화한 뒤 인접 체크포인트의
차이를 구간기록으로 계산한다. `FIN`의 구간값은 마지막 표시 지점부터 결승까지이고,
누적값은 최종 경주기록이다.
제주 G3F처럼 시간은 있지만 통과순위를 제공하지 않는 지점은 같은 지점의 누적시간으로
순위를 보완하고 화면에서 `*`로 구분한다.

```bash
uv run horse-racing collect-race-sections --date 20260822 --meet 1

uv run horse-racing backfill-sections \
  --start 20250101 --end 20251231 --meets 1 2 3
```

#### 2025·2026 백필 현황과 알려진 결측

- 2025·2026 완료 경주일 구간기록 백필을 완료했다 (`race_section_results` 합계 227,768행).
- **미완료는 수집기 오류가 아니라 API/결과 원천 공백**이다. 상세는
  [CURRENT_STATUS](CURRENT_STATUS.md)의 「구간기록 (2025·2026)」을 본다.
  - 2026-07-06·07: 서울·부산·제주 4건, 구간값 전부 0
  - 2025-12-13·20 제주, 2025-12-26 부산: 특정 R6만 착순·구간값 공백
- 제주 `2026-03-20`, `2026-03-21`, `2026-04-04`는 전 경주 취소라 구간기록이 없는 것이 정상이다.
### 미래 일정과 출발번호

```bash
uv run horse-racing collect-schedule \
  --dates 20260822 20260823 --meets 1 2 3

# API78 공식 출발번호만 개별 수집·대조
uv run horse-racing collect-gate-numbers --date 20260829 --meet 1

# DB에서 출발번호가 비어 있는 경주일만 백필
uv run horse-racing backfill-gates \
  --start 20250101 --end 20260831 --meets 1 2 3
```

`collect-schedule`과 `sync-daily --mode schedule`, `sync-latest`는 출전표가 있는 날
API78 `gtno`도 함께 수집한다. 공식 번호와 기존 출주번호 또는 마명이 다르면 해당 수집을
실패 처리해 잘못 연결되는 것을 막는다. API78 미공개일은 0건으로 정상 종료한다.

### 일일 동기화

경주가 없는 날도 포함해 매일 가볍게 돌린다. 결과가 없으면 자동으로 건너뛰고, 예외
경주일(대체휴일 등)도 놓치지 않는다.

```bash
# 전체 원천의 갱신 계획만 확인
uv run horse-racing sync-latest --as-of 20260827 --dry-run

# 일정·결과·보강·말 상태·주행심사·기준정보를 한 번에 최신화
uv run horse-racing sync-latest

# 계획만 확인
uv run horse-racing sync-daily --mode all --as-of 20260823 --dry-run

# 수동 실행: 다가올 일정 + 최근 결과
uv run horse-racing sync-daily --mode all

# 아침용: 오늘부터 3일 일정·출전표·출발번호
uv run horse-racing sync-daily --mode schedule

# 저녁용: 어제~오늘 결과·확정배당
uv run horse-racing sync-daily --mode results
```

`sync-latest`의 기본 창은 일정 7일, 결과·경주 보강 7일, 체중·훈련·진료·출발훈련 14일,
주행심사 14일이다. 마지막에는 레이팅·현역 말 프로필·등급변동을 갱신하고 관계자 연결을
복구한다. 날짜 범위는 `--schedule-days`, `--recent-lookback-days`,
`--history-lookback-days`, `--trial-lookback-days`로 조정한다. 웹의 `/data-status`에서
원천별 최신 날짜와 최근 수집 성공·실패를 확인한다.

현재 운영은 **수동 수집**을 기본으로 한다. launchd 자동 스케줄은 등록하지 않는다
(Desktop TCC로 exit 126 실패 이력이 있어 2026-08-24에 제거함).

```bash
# 아침/수시: 다가올 일정·출전표·출발번호
uv run horse-racing sync-daily --mode schedule

# 경주 종료 후: 최근 결과·확정배당·구간기록
uv run horse-racing sync-daily --mode results

# 또는 특정 날짜
uv run horse-racing collect-race-day --date YYYYMMDD --meet 1
uv run horse-racing collect-race-sections --date YYYYMMDD --meet 1
```

참고용으로 `scripts/install-launchd.sh` / `uninstall-launchd.sh`는 저장소에 남아 있으나
기본 운영 경로가 아니다.

### 관계자 링크 복구

```bash
uv run horse-racing repair-entry-links
```

같은 말의 다른 출전 전체에서 조교사 또는 마주가 정확히 한 명일 때만 채운다. 여러 사람이
있거나 근거 이력이 없으면 `NULL`을 유지한다.

### 말 이력 (레이팅·체중·훈련·진료·프로필)

```bash
uv run horse-racing collect-ratings
uv run horse-racing collect-horse-profiles --meets 1 2 3
uv run horse-racing collect-weights --date 20260822 --meet 1
uv run horse-racing backfill-weights --start 20250101 --end 20251231 --meets 1 2 3
uv run horse-racing collect-training --date 20260820 --meet 1
uv run horse-racing backfill-training --start 20250101 --end 20251231 --meets 1 2 3
uv run horse-racing collect-medical --date 20260820 --meet 1
uv run horse-racing backfill-medical --start 20250101 --end 20251231 --meets 1 2 3
```

현역/비현역: `collect-horse-profiles` 기본은 `act_gubun=y`. 비현역은 `--include-inactive`.

### KRA Text 자료실 과거 원본

```bash
# 안전한 소량 검증
uv run horse-racing download-text-archive \
  --file-type dacom11 --start 20250101 --end 20261231 \
  --meets 1 --max-files 1

# 2015~2024 경마성적표 원본
uv run horse-racing download-text-archive \
  --file-type dacom11 --start 20150101 --end 20241231 \
  --meets 1 2 3 --max-pages 500 --delay-ms 100

# 정규화 적재 전 파싱·기존 API 대조·공식 마번 연결 감사
uv run horse-racing ingest-text-results \
  --start 20150101 --end 20241231 --meets 1 2 3 --validate-only

# 감사 결과를 확인한 뒤 실제 적재. 공식 마번 미해결 말만 결정적 text: ID 허용
uv run horse-racing ingest-text-results \
  --start 20150101 --end 20241231 --meets 1 2 3 --allow-synthetic-horses
```

목록에서 발견한 즉시 `data/raw/kra_text/_manifests/<file-type>/manifest.jsonl`에 기록한다.
완료 파일은 로컬 존재 여부와 SHA-256으로 건너뛰며 `.part` 파일을 거친 원자적 rename으로
저장한다. 실패 이벤트도 manifest와 `ingestion_runs`에 남으므로 같은 명령으로 재개할 수
있다. `--start`와 `--end`는 함께 생략할 수 있으며, 날짜 없는 `db1`~`db7` 기준파일을 받을
때 사용한다. 파일을 받는 단계와 정규화 DB 적재 단계는 분리되어 있다. 기존 파일이 있지만
직전 실행이 DB 기록 전에 중단된 경우에는 재실행 시 `SourceDocument`도 복구한다.

2026-08-28 적재 결과는 원본 2,717파일, 24,586경주, 260,066출전/결과다. 공식 마번
연결은 260,057건, 미해결은 `마이공주` 9회뿐이었으며 실제 적재에서는 하나의 임시 말
객체로 합쳤다. 대량 적재 전 백업은
`data/backups/horse_racing_pre_2015_2024_dacom11_20260828.sqlite3`에 보존했다.

`dacom11`은 예정 출발시각을 제공하지 않아 과거 경주의 `scheduled_at_ms`가 비어 있다.
과거 train 구간은 `day_before_18` 정책으로 사용하고, `start_minus_30m` 정책은 추후
`dacom01`로 출발시각을 보강한 뒤 사용한다.

### 변경·장구·등급·출발·심판

```bash
uv run horse-racing collect-jockey-changes --date 20260726 --meet 1
uv run horse-racing collect-scratches --date 20260822 --meet 1
uv run horse-racing collect-equipment --date 20260822 --meet 1
uv run horse-racing collect-grade-changes --meets 1 2 3
uv run horse-racing collect-start-training --date 20260823 --meet 2
uv run horse-racing collect-steward-reports --date 20260822 --meet 1

uv run horse-racing backfill-jockey-changes --start 20260101 --end 20260825 --meets 1 2 3
uv run horse-racing backfill-scratches --start 20260101 --end 20260825 --meets 1 2 3
uv run horse-racing backfill-equipment --start 20260101 --end 20260825 --meets 1 2 3
uv run horse-racing backfill-steward-reports --start 20260101 --end 20260825 --meets 1 2 3
uv run horse-racing backfill-start-training --start 20260101 --end 20260825 --meets 1 2 3
```

현황은 [SESSION_SUMMARY_2026-08-25](SESSION_SUMMARY_2026-08-25.md)를 본다. 2025·2026 보강 백필은 완료.

## 10. 대시보드

```bash
uv run --group web horse-racing serve-dashboard
```

브라우저에서 `http://127.0.0.1:8000`을 연다. 현재는 인증이나 외부 배포가 없는 로컬 도구다.
디자인·인터랙션은 [SESSION_SUMMARY_2026-08-26](SESSION_SUMMARY_2026-08-26.md)을 본다.

| 경로 | 내용 |
|---|---|
| `/` | 경주 일정·결과 목록 |
| `/races/{id}` | 결과, 구간기록, 기수변경·출전취소·장구·심판리포트 |
| `/horses/{id}` | 프로필 + 레이팅·체중·훈련·진료·등급·장구·출발·기수변경·출전취소 |
| `/horses`, `/jockeys`, `/trainers`, `/owners` | 목록·검색 |

헤더 우측 버튼으로 다크/라이트 테마를 전환한다. 선택은 브라우저 `localStorage`
(`hr-theme`)에 남는다. CSS/JS는 `?v=3` 쿼리로 캐시를 무효화한다.

## 11. 검증

```bash
uv run ruff check .
uv run pytest -q
git diff --check
sqlite3 data/horse_racing.sqlite3 'PRAGMA integrity_check;'
```

Backfill 후 최소 다음 항목을 확인한다.

- 기대한 날짜 범위와 경마장·경주일 수
- 경주 수, 출전 수와 결과 수
- 완료 결과일의 확정배당 실행 이력
- 말·기수·조교사·마주 공식 ID 중복
- 경주 및 출전 자연키 중복
- 고아 결과와 관계자 연결 결측
- `running` 상태로 오래 남은 stale 수집 실행

## 12. 장애와 복구

### HTTP 429

API별 개발계정 호출량은 독립적으로 소진될 수 있다. 결과 본체를 `--skip-dividends`로 끝낸 뒤
API301 한도가 초기화되면 `backfill-dividends`를 재실행한다.

### 네트워크 중단

전송 오류는 지수 backoff로 제한 횟수 재시도한 뒤 실패 처리한다. 명령을 다시 실행하면 완료된
날짜를 건너뛰고 실패 날짜부터 이어진다.

### 프로세스 강제 종료

정규화 테이블의 자연키 upsert가 중복을 막는다. 다만 실행 중 프로세스를 종료하면
`ingestion_runs.status='running'`이 남을 수 있으므로 stale run 정리 기능이 필요하다.

### Raw 재처리

현재는 원본을 보존하지만 raw-only 재파싱 전용 명령은 아직 없다. 파서 변경 시 API를 다시
호출하지 않고 raw 파일에서 재구축하는 기능은 향후 추가한다.

## 13. 백업

최소 다음 두 영역을 함께 백업해야 완전한 복구가 가능하다.

- `data/horse_racing.sqlite3`
- `data/raw/`

실행 중인 SQLite를 단순 복사하기보다 SQLite backup 명령 또는 쓰기가 멈춘 시점의 복사본을
사용한다. `.env`는 별도의 안전한 비밀 저장소에서 관리한다.
