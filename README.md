# Korean Horse Racing Data Platform

한국마사회 경주 데이터를 로컬에서 수집, 정규화, 분석하기 위한 프로젝트입니다.

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

## 향후 웹 구조

FastAPI가 JSON API와 HTML을 함께 제공합니다. HTML은 Jinja2 템플릿을 사용하고,
브라우저 동작과 스타일은 `web/static/js`, `web/static/css`의 일반 JavaScript와 CSS로
구성합니다.

