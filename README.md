# Korean Horse Racing Data Platform

한국마사회 경주 데이터를 로컬에서 수집, 정규화, 분석하기 위한 프로젝트입니다.

## 프로젝트 문서

장기 설계, 현재 구현 상태, 데이터 운영법과 다음 개발 순서는 다음 문서에서 관리합니다.

- [문서 안내](docs/README.md)
- [전체 프로젝트 블루프린트](docs/BLUEPRINT.md)
- [현재 상태와 작업 이력](docs/CURRENT_STATUS.md)
- [데이터 구조와 운영 가이드](docs/DATA_AND_OPERATIONS.md)
- [단계별 개발 로드맵](docs/ROADMAP.md)

## 기술 구성

- Python 3.12, uv
- SQLite, SQLAlchemy 2, Alembic
- Polars, DuckDB, Parquet
- 향후 웹 계층: FastAPI + HTML/CSS/JavaScript

## 저장 구조

```text
data/raw/                    원본 HTML, JSON, XML
data/horse_racing.sqlite3    정규화된 운영 데이터
data/parquet/                분석 및 모델 학습 데이터
data/exports/                외부 전달용 결과물
```

로컬 데이터는 Git에 포함하지 않습니다. 수집 원본은 덮어쓰지 않고 보존하며, SQLite에는
원본 파일 경로와 SHA-256 체크섬을 기록합니다.

## 시작하기

```bash
UV_CACHE_DIR=/private/tmp/horse-racing-uv-cache uv sync
UV_CACHE_DIR=/private/tmp/horse-racing-uv-cache uv run alembic upgrade head
UV_CACHE_DIR=/private/tmp/horse-racing-uv-cache uv run horse-racing db-info
UV_CACHE_DIR=/private/tmp/horse-racing-uv-cache uv run pytest
```

기본 DB 경로는 `data/horse_racing.sqlite3`입니다. 변경하려면 `.env.example`을 `.env`로
복사하고 `HORSE_RACING_DATABASE_URL`을 수정합니다.

## 데이터 모델

- 수집: `ingestion_runs`, `source_documents`
- 기준정보: `racecourses`, `horses`, `jockeys`, `trainers`, `owners`
- 경주: `races`, `race_entries`, `race_results`
- 흐름: `race_section_results`
- 시장: `odds_snapshots`

모든 관측 시각은 UTC epoch milliseconds로 저장하고, 경주일은 한국시간 기준 날짜로
별도 저장합니다.

## 출전표 수집

공식 공공데이터포털의 `한국마사회 출전표 상세정보` API를 사용합니다. 먼저 해당 API를
활용 신청한 뒤 `.env.example`을 `.env`로 복사하고 일반 인증키 중 `Decoding` 값을
설정합니다. `.env`는 Git에서 제외됩니다.

```dotenv
HORSE_RACING_DATA_GO_KR_SERVICE_KEY=발급받은_Decoding_인증키
```

DB를 최신 상태로 만든 뒤 날짜와 경마장을 지정해 실행합니다.

```bash
UV_CACHE_DIR=/private/tmp/horse-racing-uv-cache uv run alembic upgrade head
UV_CACHE_DIR=/private/tmp/horse-racing-uv-cache uv run horse-racing collect-entry-sheet \
  --date 20260822 \
  --meet 1
```

경마장 코드는 `1=서울`, `2=제주`, `3=부산경남`, `4=영천`입니다. API 응답 원문은
`data/raw/kra/entry_sheet` 아래에 먼저 보존되고, 서비스키를 제외한 요청 메타데이터와
SHA-256 체크섬이 `source_documents`에 기록됩니다. 이후 경주, 말, 기수, 조교사, 마주,
출전정보가 정규화 테이블에 반복 실행 가능한 upsert 방식으로 저장됩니다.

## 하루치 기본 데이터 수집

완료된 경주일을 대상으로 다음 5개 데이터를 순서대로 수집할 수 있습니다.

1. 경주계획
2. 출전표 상세정보
3. AI 경주결과
4. 경주상세결과
5. 최종 배당률

각 원본 응답을 먼저 보존한 뒤 경주, 출전마, 관계자, 결과, 배당을 하나의 데이터 모델로
연결합니다. 동일한 날짜를 다시 실행하면 정규화 테이블은 upsert되어 중복 행이 생기지
않으며, 수집 이력과 원본 문서는 실행별로 보존됩니다.

```bash
UV_CACHE_DIR=/private/tmp/horse-racing-uv-cache uv run alembic upgrade head
UV_CACHE_DIR=/private/tmp/horse-racing-uv-cache uv run horse-racing collect-race-day \
  --date 20260821 \
  --meet 2
```

최종 배당률 API는 한 경주일의 조합별 배당이 많으므로 기본 페이지 크기는 1,000건이며,
전체 건수가 더 많으면 자동으로 다음 페이지까지 수집합니다.

기간 내 결과가 존재하는 경주일을 자동 탐색하여 일괄 수집할 수도 있습니다. 완료된
날짜는 경주·결과·확정배당 저장 상태를 확인한 뒤 자동으로 건너뜁니다.

```bash
UV_CACHE_DIR=/private/tmp/horse-racing-uv-cache uv run horse-racing backfill-results \
  --start 20260101 \
  --end 20260821 \
  --meets 1 2 3
```

확정배당 API의 일일 호출 제한에 도달한 경우 결과 본체와 배당을 분리해 이어받을 수
있습니다. 배당 전용 백필은 이미 완료된 날짜를 자동으로 건너뜁니다.

```bash
UV_CACHE_DIR=/private/tmp/horse-racing-uv-cache uv run horse-racing backfill-results \
  --start 20250101 --end 20251231 --meets 1 2 3 --skip-dividends
UV_CACHE_DIR=/private/tmp/horse-racing-uv-cache uv run horse-racing backfill-dividends \
  --start 20250101 --end 20251231 --meets 1 2 3 --page-size 20000
```

출전취소처럼 원천 API에서 조교사·마주 ID를 생략한 출전행은 같은 말의 다른 출전에서
관계자가 한 사람으로 일관될 때만 다음 명령으로 안전하게 복구합니다.

```bash
UV_CACHE_DIR=/private/tmp/horse-racing-uv-cache uv run horse-racing repair-entry-links
```

아직 결과가 나오지 않은 날짜는 경주계획과 출전표만 별도로 수집합니다.

```bash
UV_CACHE_DIR=/private/tmp/horse-racing-uv-cache uv run horse-racing collect-schedule \
  --dates 20260822 20260823 \
  --meets 1 2 3
```

## 일정·결과 대시보드

로컬 SQLite에 저장된 데이터를 날짜와 경마장별로 조회할 수 있습니다. 경주 목록에서 한
경주를 선택하면 출전마, 기수, 조교사, 부담중량, 마체중, 레이팅과 함께 완료 경주의 순위,
기록, 단승·연승 배당 및 상금을 확인할 수 있습니다.

```bash
UV_CACHE_DIR=/private/tmp/horse-racing-uv-cache uv sync --group web
UV_CACHE_DIR=/private/tmp/horse-racing-uv-cache uv run --group web horse-racing serve-dashboard
```

브라우저에서 `http://127.0.0.1:8000`을 열면 됩니다. 개발 중 파일 변경을 자동 반영하려면
`serve-dashboard --reload`로 실행합니다.

## 향후 웹 구조

FastAPI가 JSON API와 HTML을 함께 제공합니다. HTML은 Jinja2 템플릿을 사용하고,
브라우저 동작과 스타일은 `web/static/js`, `web/static/css`의 일반 JavaScript와 CSS로
구성합니다.
