# Korean Horse Racing Data Platform

한국마사회 경주 데이터를 로컬에서 수집, 정규화, 분석하기 위한 프로젝트입니다.

## 프로젝트 문서

장기 설계, 현재 구현 상태, 데이터 운영법과 다음 개발 순서는 다음 문서에서 관리합니다.

- [문서 안내](docs/README.md)
- [완료와 다음 작업](docs/PROGRESS.md)
- [전체 프로젝트 블루프린트](docs/BLUEPRINT.md)
- [현재 상태와 작업 이력](docs/CURRENT_STATUS.md)
- [예측 모델 로드맵](docs/MODELING_ROADMAP.md)
- [공개 예측 검증 원장](docs/PREDICTION_LEDGER.md)
- [데이터 구조와 운영 가이드](docs/DATA_AND_OPERATIONS.md)
- [단계별 개발 로드맵](docs/ROADMAP.md)

## 기술 구성

- Python 3.12, uv
- SQLite, SQLAlchemy 2, Alembic
- Polars, DuckDB, Parquet
- LightGBM, CatBoost, scikit-learn
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

현재 표준 데이터셋의 모델 학습·비교 명령은 다음과 같습니다. 학습 명령은 valid까지만
평가합니다. G1·G2 holdout은 이미 1회 사용해 각각 PASS·FAIL로 기록했으며 재실행하지 않습니다.

```bash
uv run horse-racing train-model --version v2_trials --as-of start_minus_30m
uv run horse-racing train-catboost --version v2_trials --as-of start_minus_30m
uv run horse-racing run-ablation --version v2_trials --as-of start_minus_30m
```

G2 리포트는 `data/experiments/reports/g2_v2_trials_start_minus_30m_*.md`에 있다.

G2 이후 경로 B의 공개 검증 원장은 다음 명령으로 운영합니다. 실제 live 발행은 고정 모델의
as-of 시각 전에만 허용되며, 과거 검증자료는 별도 모드로 분리됩니다.

```bash
# 예정 경주 feature 생성 → 고정 모델 추론 → 불변 원장 발행
uv run horse-racing predict-and-publish --run-id RUN_ID --date 20260828

# 결과 수집 후 1회 정산
uv run horse-racing settle-predictions
uv run horse-racing list-predictions --mode live

# 외부에서 만든 예측 파일의 저수준 발행 경로
uv run horse-racing publish-predictions --run-id RUN_ID \
  --predictions-file FILE.parquet --feature-cutoff 2026-08-28T12:30:00+09:00
```

기본 DB 경로는 `data/horse_racing.sqlite3`입니다. 변경하려면 `.env.example`을 `.env`로
복사하고 `HORSE_RACING_DATABASE_URL`을 수정합니다.

## 데이터 모델

- 수집: `ingestion_runs`, `source_documents`
- 기준정보: `racecourses`, `horses`, `jockeys`, `trainers`, `owners`
- 경주: `races`, `race_entries`, `race_results`
- 흐름: `race_section_results`
- 시장: `odds_snapshots`
- 말 이력: `horse_rating_snapshots`, `horse_weight_history`, `horse_training`, `horse_medical`, `horse_profile_snapshots`
- 주행심사: `running_trials`, `running_trial_results`
- 보강: `jockey_changes`, `race_scratches`, `entry_equipment`, `horse_grade_changes`, `horse_start_training`, `race_steward_reports`

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

## 주행심사 수집

KRA Text 자료실의 `dacom23` 주행심사결과를 기간·경마장별로 내려받습니다. 원본 CP949
`.rpt` 파일을 보존하고, 심사 경주와 말별 판정·검사사유·기록·구간기록을 정규화합니다.
보고서에 공식 마번이 없으므로 기존 말은 같은 경마장과 이름을 우선 사용하고, 이름이 중복되면
성별·연령·생년으로 하나만 확정되는 경우에만 연결합니다.

```bash
UV_CACHE_DIR=/private/tmp/horse-racing-uv-cache uv run horse-racing collect-running-trials \
  --start 20250101 \
  --end 20260827 \
  --meets 1 2 3
```

이 명령은 공공데이터포털 서비스키가 필요하지 않습니다. 반복 실행하면 정규화 행은 자연키로
갱신되며 수집 실행과 원본 문서 메타데이터는 실행별로 보존됩니다.

## KRA Text 자료실 원본 다운로드

과거 경마성적표 등 다른 Text 분류는 공통 Downloader로 받습니다. 파일을 받기 전에
append-only manifest에 발견 이력을 기록하고, 같은 파일은 SHA-256과 로컬 경로를 확인해
건너뜁니다. 중단 후 같은 명령을 실행하면 이어받습니다.

```bash
# 먼저 파일 1건으로 연결과 저장 구조 확인
uv run horse-racing download-text-archive \
  --file-type dacom11 --start 20250101 --end 20261231 \
  --meets 1 --max-files 1

# 2015~2024 경마성적표 원본 전체 수집
uv run horse-racing download-text-archive \
  --file-type dacom11 --start 20150101 --end 20241231 \
  --meets 1 2 3

# 실제 적재 전에 전체 파싱·공식 마번 연결 상태 감사
uv run horse-racing ingest-text-results \
  --start 20150101 --end 20241231 --meets 1 2 3 --validate-only

# 감사 결과를 확인한 뒤 정규화 DB 적재
uv run horse-racing ingest-text-results \
  --start 20150101 --end 20241231 --meets 1 2 3 --allow-synthetic-horses
```

원본은 `data/raw/kra_text/<file-type>/...`, manifest는
`data/raw/kra_text/_manifests/<file-type>/manifest.jsonl`에 저장됩니다. 다운로드와
정규화 DB 적재는 의도적으로 분리되어 있습니다. `dacom11` 과거 경주에는 예정 출발시각이
없으므로 `start_minus_30m` 학습 정책은 추후 `dacom01` 시간 보강 뒤 사용합니다.

아직 결과가 나오지 않은 날짜는 경주계획과 출전표만 별도로 수집합니다.

```bash
UV_CACHE_DIR=/private/tmp/horse-racing-uv-cache uv run horse-racing collect-schedule \
  --dates 20260822 20260823 \
  --meets 1 2 3
```

## 일정·결과 대시보드

로컬 SQLite에 저장된 데이터를 날짜와 경마장별로 조회할 수 있습니다. 통합 달력은 공식
경주와 주행심사를 서로 다른 점으로 표시합니다. 공식 경주의 출전·결과·배당·구간 화면과
별도로, 주행심사도 참가마·판정·기록·구간·검사 사유를 전용 상세 페이지에서 확인합니다.
`/data-status`에서는 원천별 행 수·최신 날짜·최근 수집 실행 상태를 한눈에 볼 수 있습니다.

```bash
UV_CACHE_DIR=/private/tmp/horse-racing-uv-cache uv sync --group web
UV_CACHE_DIR=/private/tmp/horse-racing-uv-cache uv run --group web horse-racing serve-dashboard
```

브라우저에서 `http://127.0.0.1:8000`을 열면 됩니다. 개발 중 파일 변경을 자동 반영하려면
`serve-dashboard --reload`로 실행합니다.

## 일일 데이터 갱신

```bash
# 전체 최신화 대상만 확인
UV_CACHE_DIR=/private/tmp/horse-racing-uv-cache uv run horse-racing sync-latest --dry-run

# 일정·결과·보강·말 상태·주행심사·기준정보 전체 갱신
UV_CACHE_DIR=/private/tmp/horse-racing-uv-cache uv run horse-racing sync-latest

# 일정과 결과만 가볍게 갱신
UV_CACHE_DIR=/private/tmp/horse-racing-uv-cache uv run horse-racing sync-daily
```

자세한 운영법은 [DATA_AND_OPERATIONS](docs/DATA_AND_OPERATIONS.md)를 참고하세요.

## 향후 웹 구조

FastAPI가 JSON API와 HTML을 함께 제공합니다. HTML은 Jinja2 템플릿을 사용하고,
브라우저 동작과 스타일은 `web/static/js`, `web/static/css`의 일반 JavaScript와 CSS로
구성합니다.
