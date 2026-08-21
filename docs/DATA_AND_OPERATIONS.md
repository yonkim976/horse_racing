# 데이터 구조와 운영 가이드

최종 갱신: 2026-08-22

## 1. 현재 통합된 공식 API

| 데이터 | Endpoint | Operation | 주요 검색 조건 | 현재 용도 |
|---|---|---|---|---|
| AI 경주계획 | `/API154/racePlan` | `racePlan` | `rccrs_cd`, `race_dt` | 경주 일정·조건 |
| 출전표 상세 | `/API26_2/entrySheet_2` | `entrySheet_2` | `meet`, `rc_date` | 출전마·관계자·체중·레이팅 |
| AI 경주결과 | `/API155/raceResult` | `raceResult` | `rccrs_cd`, `race_dt` | 결과 존재 확인 및 기본 결과 |
| 경주상세결과 | `/API156/raceRsutDtl` | `raceRsutDtl` | `rccrs_cd`, `race_dt` | 상세 결과·상금·장구 |
| 전체 확정배당 | `/API301/Dividend_rate_total` | `Dividend_rate_total` | `meet`, `rc_date` | 승식별 최종 배당 조합 |

공통으로 페이지 번호와 페이지 크기를 사용한다. 출전표는 인증 파라미터 이름이 `ServiceKey`,
나머지 현재 통합 API는 `serviceKey`다. 서비스키는 공개 요청 메타데이터와 원본 파일명에 넣지
않는다.

이 표는 **현재 코드에 통합된 API**만 나타낸다. 조사된 다른 KRA API가 모두 구현됐다는 뜻은
아니다. API 카탈로그 확장은 로드맵의 별도 작업이다.

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
| `race_section_results` | 출전별 구간 기록을 위한 테이블, 수집은 미구현 |
| `odds_snapshots` | 경주·승식·선택조합·관측시각별 배당 |

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

### 미래 일정

```bash
uv run horse-racing collect-schedule \
  --dates 20260822 20260823 --meets 1 2 3
```

### 관계자 링크 복구

```bash
uv run horse-racing repair-entry-links
```

같은 말의 다른 출전 전체에서 조교사 또는 마주가 정확히 한 명일 때만 채운다. 여러 사람이
있거나 근거 이력이 없으면 `NULL`을 유지한다.

## 10. 대시보드

```bash
uv run --group web horse-racing serve-dashboard
```

브라우저에서 `http://127.0.0.1:8000`을 연다. 현재는 인증이나 외부 배포가 없는 로컬 도구다.

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

