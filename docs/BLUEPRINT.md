# 한국 경마 데이터·AI 분석 플랫폼 블루프린트

최종 갱신: 2026-08-22

## 1. 프로젝트 목적

한국마사회(KRA)가 공개하는 데이터를 장기간 축적하고 시계열적으로 정확하게 결합하여,
특정 경주가 시작되기 전에 알 수 있었던 정보만으로 각 출전마의 승리·입상 확률을 산출하고
검증할 수 있는 한국 경마 데이터 플랫폼을 구축한다.

모델보다 먼저 해결해야 하는 것은 안정적인 원천 수집, ID 기반 정규화, 원본 보존과 데이터
누수 방지다. 첫 번째 제품은 예측 서비스가 아니라 신뢰할 수 있는 데이터 기반이다.

```text
KRA 공식 데이터
    ↓
변경하지 않는 원본 보관
    ↓
경주·말·관계자·결과·훈련·시장 데이터 정규화
    ↓
예측 시점 기준 시계열 스냅샷
    ↓
Feature Store / 학습 데이터셋
    ↓
승리·Top2·Top3 확률 모델
    ↓
Calibration / Backtest / 시장 비교
    ↓
FastAPI 기반 분석·조회 서비스
```

## 2. 성공 기준

플랫폼이 다음 질문에 재현 가능하게 답할 수 있어야 한다.

- 특정 날짜와 경마장의 모든 경주·출전마·결과를 조회할 수 있는가?
- 같은 말, 기수, 조교사와 마주가 기간 전체에서 하나의 공식 ID로 연결되는가?
- 어떤 API 응답에서 한 값이 만들어졌는지 원본까지 추적할 수 있는가?
- 과거 경주 예측에 당시 알 수 없었던 미래 정보가 포함되지 않았는가?
- 한 경주의 승리 확률 합이 해석 가능한 형태로 관리되는가?
- 모델 확률이 실제 빈도와 일치하는지 calibration으로 검증되는가?
- 시장 확률 및 단순 기준 모델보다 일관되게 나은지 기간 외 테스트로 검증되는가?

## 3. 핵심 원칙

### 3.1 공식 원천 우선

한국마사회와 공공데이터포털을 기준 원천으로 사용한다. 민간 사이트는 탐색과 교차 확인에는
활용할 수 있지만, 공식 데이터가 없는 값을 근거 없이 운영 DB에 넣지 않는다.

### 3.2 원본과 정규화 데이터 분리

API 응답은 정규화 전에 파일로 보존한다. 요청 시각, 수신 시각, 공개 파라미터, endpoint,
HTTP 상태, 파일 경로와 SHA-256을 함께 기록하여 파서 수정 후 재처리할 수 있게 한다.

### 3.3 이름이 아닌 공식 ID로 연결

말은 KRA 마번, 관계자는 KRA 기수·조교사·마주 번호를 기준으로 연결한다. 이름 변경, 동명이인,
숫자 ID의 앞자리 0 유실을 고려해 ID는 문자열로 정규화한다.

### 3.4 시점 일관성과 데이터 누수 방지

모든 feature는 예측 시점 이전에 공개된 값으로만 계산한다. 결과 후 확정되는 착순, 최종 배당,
실제 출발시각과 사후 갱신 통계는 학습 입력으로 사용하지 않는다.

장기적으로 다음 시간 개념을 구분한다.

- `effective_at`: 현실에서 값이 효력을 갖는 시점
- `observed_at`: 원천에서 관측한 시점
- `ingested_at`: 우리 시스템이 저장한 시점
- `prediction_at`: 모델이 예측을 생성한 시점

### 3.5 반복 실행과 검증 가능성

수집 명령은 중단 후 재실행할 수 있어야 하고 정규화 테이블에 중복을 만들지 않아야 한다.
모델과 리포트는 데이터 범위, 코드 버전, feature 버전과 평가 기간을 기록한다.

### 3.6 확률 품질 우선

단순 적중률만으로 모델을 평가하지 않는다. Log Loss, Brier Score, calibration, 경주별 Top1·Top3
정확도와 기간 외 성능을 함께 본다. 수익률 평가는 확률 모델 검증 이후의 별도 단계다.

## 4. 목표 아키텍처

```text
                         KRA
                          │
             ┌────────────┴────────────┐
             │                         │
       Text/File Archive          OpenAPI Collectors
       대량 과거 자료              신규·보완 자료
             │                         │
             └────────────┬────────────┘
                          ↓
                    Immutable Raw
                 JSON/XML/Text + hash
                          ↓
                 Parser / Normalizer
                          ↓
        ┌─────────────────┼─────────────────┐
        │                 │                 │
     Race Core       Horse History      People History
  schedule/result   rating/weight/     jockey/trainer
   section/odds     training/medical      statistics
        └─────────────────┼─────────────────┘
                          ↓
                  Temporal Feature Store
                          ↓
               Parquet + DuckDB Datasets
                          ↓
          Baseline / Ranking / Calibration Models
                          ↓
             Evaluation, Backtest, Dashboard
                          ↓
                 FastAPI + HTML/JS/CSS
```

## 5. 데이터 계층

### 5.1 Raw Layer

- 응답 본문을 가능한 한 받은 그대로 저장한다.
- 인증키는 URL, 로그, 메타데이터에서 제거한다.
- 같은 요청을 다시 수행해도 실행별 원본과 수집 이력은 보존한다.
- Text 자료실을 도입할 때 파일명, 인코딩, 구분자와 제공 기간을 함께 기록한다.

### 5.2 Normalized Operational Layer

분석의 기본 단위는 `경주 × 출전마`다.

- 경주: 일정, 조건, 날씨, 주로, 상태
- 출전: 말, 출주번호, 게이트, 관계자, 부담중량, 체중, 레이팅, 장구
- 결과: 착순, 기록, 착차, 상금, 실격·취소 상태
- 구간: S1F/G3F/G1F, 코너 순위, 구간 기록
- 시장: 승식, 선택 조합, 배당, 관측시각
- 이력: 말·기수·조교사의 시점별 상태와 통계

### 5.3 Analytical Layer

정규화 DB를 직접 반복 스캔하지 않고, 예측 시점 기준으로 고정된 Parquet 데이터셋을 만든다.
DuckDB/Polars로 feature를 생성하고 스키마, 생성 시각, 원천 범위와 코드 버전을 기록한다.

### 5.4 Serving Layer

초기에는 FastAPI가 HTML과 조회용 JSON을 함께 제공한다. 프론트는 Jinja2, 일반 JavaScript와
CSS를 사용한다. API 소비자나 사용량이 늘면 프론트와 API를 분리할 수 있다.

## 6. 목표 도메인 모델

### 현재 핵심

- `racecourses`
- `races`
- `horses`
- `jockeys`
- `trainers`
- `owners`
- `race_entries`
- `race_results`
- `race_section_results`
- `odds_snapshots`
- `ingestion_runs`
- `source_documents`

### 추가할 이력 영역

- `horse_rating_history`
- `horse_weight_history`
- `horse_training`
- `horse_swim_training`
- `horse_start_training`
- `horse_hill_training`
- `horse_medical`
- `horse_equipment_history`
- `horse_pedigree`
- `jockey_stats_history`
- `trainer_stats_history`
- `race_changes`
- `steward_reports`
- `prediction_runs`
- `model_predictions`
- `feature_dataset_versions`

## 7. 데이터 소스 전략

### Historical Backfill

대량 과거 자료는 KRA Text/File 자료실을 우선 검토한다. API 호출량을 절약하고 장기 이력의
초기 적재 시간을 줄이기 위해서다. 파일별 최초 제공 연도, 인코딩, 구분자와 누락 기간을 공식
자료로 다시 검증해야 한다.

### Incremental Update

공공데이터포털 OpenAPI로 일정, 출전표, 결과와 변경 데이터를 증분 수집한다. 경주 전·후에
데이터 확정 시점이 다르므로 하나의 일일 작업이 아니라 여러 시점의 작업으로 나눈다.

```text
D-1 또는 경주일 오전: 일정·출전표
T-60 ~ T-1: 변경정보·가능하다면 실시간 배당 스냅샷
경주 종료 후: 상세결과·구간기록
일 마감 후: 확정배당·정정 데이터
D+1: 누락 및 정정 재검증
```

## 8. Feature 설계 방향

### 말의 최근 Form

- 최근 1/3/5/10경주 착순과 기록
- 거리·경마장·등급별 기록
- 휴식일과 출전 간격
- 최근 체중과 평소 체중 대비 변화

### 주행 능력

- S1F, G3F, G1F와 코너 위치
- 초반 속도, 막판 추입력, pace decay
- 선행·선입·추입 성향

### 훈련과 건강

- 최근 3/7/14일 훈련 시간 및 횟수
- 구보·습보, 수영·출발·언덕 훈련
- 최근 진료, 장구 변경과 폐출혈 이력

### 사람과 조합

- 기수·조교사의 30/90/365일 성적
- 거리·경마장별 성적
- 말×기수, 기수×조교사 조합 성적

### 경주 내 상대값

- 레이팅과 최근 속도의 경주 내 순위
- 출전군 평균 대비 차이
- 동일 경주 softmax 및 정규화 확률

모든 feature에는 원천, 계산식, lookback window, null 처리, 예측 시점 사용 가능 여부와 누수
위험을 기록한다.

## 9. 모델과 평가

### 첫 모델

CatBoost, LightGBM 또는 XGBoost로 재현 가능한 baseline을 만든다. 딥러닝보다 데이터 누수,
분할 전략, calibration과 feature 품질 검증을 우선한다.

### Target

- `P(win)`
- `P(top2)`
- `P(top3)`

초기 이진 분류 확률은 경주 단위로 정규화한다. 이후 learning-to-rank, field softmax,
Plackett-Luce 같은 경주 단위 모델을 비교한다.

### 평가

- 시간 순서 기반 train/validation/test 분할
- Log Loss, Brier Score, AUC
- calibration curve와 Expected Calibration Error
- 경주별 Top1·Top3 정확도
- 경마장·거리·등급·기간별 안정성
- 시장 암시확률 대비 증분 예측력

확정배당은 사후 평가용이며 경주 전 feature가 아니다. 실시간 배당을 확보한 경우에만 해당
관측시각 이전의 snapshot을 feature 또는 시장 기준선으로 사용한다.

## 10. 기술 스택 방향

### 현재 로컬 MVP

- Python 3.12, uv
- httpx, Pydantic, Tenacity
- SQLite, SQLAlchemy 2, Alembic
- Polars, DuckDB, Parquet
- FastAPI, Jinja2, HTML/CSS/JavaScript
- pytest, Ruff

### 확장 기준

SQLite는 단일 머신의 수집·개발·조회에는 충분하다. 다음 조건이 발생하면 PostgreSQL로
운영 계층을 이전한다.

- 여러 수집기와 사용자가 동시에 지속적으로 쓰는 경우
- 원격 서비스가 DB를 공유해야 하는 경우
- 작업 큐, 권한, 고가용성과 정교한 관측성이 필요한 경우

대규모 분석은 DB 종류와 무관하게 Parquet + DuckDB/Polars로 분리한다.

## 11. 범위 단계

### MVP

- 공식 일정·출전·결과·확정배당 수집
- 원본 보존과 ID 기반 정규화
- 중단 후 재개 가능한 historical backfill
- 일정·결과 로컬 대시보드
- 데이터 품질 검사와 문서화

### V2

- 구간기록, 말 상세·레이팅, 훈련, 진료와 장구 수집
- KRA Text 자료실 historical importer
- 시간 스냅샷과 leakage audit
- Parquet feature dataset v1
- CatBoost/LightGBM baseline 및 calibration report

### V3

- 자동 증분 수집과 모니터링
- 실시간 변경·배당 snapshot 조사 및 수집
- 경주 단위 ranking model과 모델 레지스트리
- 예측 API, 모델 비교와 backtest UI
- PostgreSQL 또는 관리형 운영 DB 전환 검토

## 12. 블루프린트 완료 정의

이 프로젝트의 최종 완료는 단순히 높은 적중 사례를 만드는 것이 아니다. 공식 원천에서
예측 시점까지의 데이터만 재현하고, 확률 품질과 시장 대비 성능을 장기간 검증하며, 결과가
좋지 않은 기간까지 포함해 투명하게 설명할 수 있을 때 플랫폼의 목적을 달성한 것으로 본다.

