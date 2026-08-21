# 단계별 개발 로드맵

최종 갱신: 2026-08-22

## 우선순위 원칙

```text
정확한 원천 확보
  → ID 기반 JOIN
  → 시점별 이력
  → 데이터 누수 검증
  → Feature Engineering
  → 모델링
  → 서비스화
```

## Phase 0. 로컬 데이터 기반 — 완료

- [x] Python/uv 프로젝트 구성
- [x] SQLite, SQLAlchemy와 Alembic 도입
- [x] Raw 파일 및 수집 이력 보존
- [x] 일정·출전표·결과·상세결과·확정배당 수집
- [x] 공식 ID 기반 말·관계자 정규화
- [x] 재개 가능한 기간 backfill
- [x] 2025년 전체 공식 결과 제공일과 배당 적재
- [x] 2026-08-21까지 결과 및 08-22~23 일정 적재
- [x] 일정·결과 로컬 대시보드
- [x] 기본 무결성 검사와 회귀 테스트
- [x] 프로젝트 문서 체계

## Phase 1. 데이터 범위 확장 — 다음 단계

### 1.1 공식 API 카탈로그

- [ ] 관련 KRA API 20~30개의 현재 공식 명칭과 공공데이터 ID 확인
- [ ] endpoint, operation, 파라미터, 응답 필드와 경마장 지원 범위 기록
- [ ] 갱신 주기, 일일 호출량, JSON/XML 지원 여부 확인
- [ ] AI학습용 계획·결과와 일반 상세 API 스키마 비교

완료 조건: 공식 링크와 확인일이 있는 API 카탈로그 문서 및 우선순위 표.

### 1.2 구간기록

- [ ] 공식 구간기록 API 검증
- [ ] S1F/G3F/G1F, 코너 통과순위와 group notation parser
- [ ] `race_section_results` 적재 및 품질 검사
- [ ] 레이스 전개를 표시하는 대시보드 시각화

완료 조건: 표본 기간에서 결과 출전 대비 구간기록 coverage와 결측 사유를 설명할 수 있음.

### 1.3 말과 관계자 이력

- [ ] 말 상세, 레이팅, 체중 이력
- [ ] 기수·조교사 기간별 성적
- [ ] 이름 변경과 소속 변경 처리
- [ ] snapshot의 `effective_at`, `observed_at`, `ingested_at` 설계

### 1.4 훈련·건강·변경정보

- [ ] 일별·수영·출발·언덕 훈련
- [ ] 진료·장구·폐출혈
- [ ] 기수변경·출전취소·심판리포트
- [ ] 결측과 공개 지연시간 조사

## Phase 2. Historical/Analytical Layer

### 2.1 KRA Text 자료실

- [ ] 다운로드 가능한 파일 종류와 최초 제공 연도 조사
- [ ] 파일명 규칙, encoding과 delimiter 확인
- [ ] checksum manifest와 재개 가능한 downloader
- [ ] Text parser와 API 중복 구간 비교

### 2.2 Parquet Dataset

- [ ] 정규화 DB에서 연도·경마장별 Parquet export
- [ ] DuckDB/Polars 분석 파이프라인
- [ ] dataset version, schema와 source range manifest
- [ ] raw-only 재파싱 및 재구축 명령

### 2.3 Data Quality

- [ ] stale ingestion run 정리 명령
- [ ] coverage·중복·결측 자동 리포트
- [ ] 원천 간 불일치 기록 테이블
- [ ] DB와 raw 백업·복원 절차 자동화

완료 조건: 동일 raw와 코드 버전으로 같은 analytical dataset을 재생성할 수 있음.

## Phase 3. Leakage-Free Feature Store

- [ ] 명시적인 `prediction_at` 정의
- [ ] feature별 원천, 공개시점과 lookback window 카탈로그
- [ ] point-in-time join 공통 함수
- [ ] 미래정보를 의도적으로 삽입해 실패를 확인하는 leakage 테스트
- [ ] 최근 form, 속도, 휴식, 체중, 기수·조교사 feature
- [ ] 경주 내 상대값과 rank feature

완료 조건: 각 학습 행에 해당 feature가 경주 전에 알려졌음을 프로그램으로 검증할 수 있음.

## Phase 4. Baseline Model

- [ ] 시간 순서 train/validation/test split
- [ ] 시장·인기·레이팅 기반 단순 기준 모델
- [ ] CatBoost/LightGBM/XGBoost 비교
- [ ] `P(win)`, `P(top2)`, `P(top3)` 생성
- [ ] 경주 단위 확률 정규화
- [ ] Log Loss, Brier, AUC, calibration과 Top1·Top3 리포트
- [ ] 기간·경마장·거리·등급별 안정성 분석

완료 조건: 코드와 데이터 버전이 고정된 재현 가능한 baseline 리포트.

## Phase 5. 시장 비교와 Backtest

- [ ] 확정배당의 승식별 암시확률 계산
- [ ] takeout을 고려한 경주 내 시장 확률 정규화
- [ ] 모델과 시장의 확률·calibration 비교
- [ ] 거래비용, 배당 확정시점과 선택 편향을 반영한 backtest
- [ ] 민감도와 최대 낙폭 등 위험 지표

실시간 배당 snapshot을 확보하기 전까지 확정배당을 경주 전 feature로 사용하지 않는다.

## Phase 6. 자동화와 서비스

- [ ] 경주 전·후 단계별 자동 수집 스케줄
- [ ] API 한도, 누락, 지연과 스키마 변경 알림
- [ ] 데이터 freshness와 수집 상태 화면
- [ ] 예측 결과·근거·calibration을 보여주는 대시보드
- [ ] 모델·feature·예측 실행 이력 저장
- [ ] 필요 시 PostgreSQL로 운영 계층 이전

## 바로 이어서 할 작업

다음 개발 세션은 아래 순서가 적절하다.

1. 현재 활용 승인된 KRA API 목록을 공식 문서 기준으로 카탈로그화한다.
2. 구간기록 API 한 종류를 표본 날짜에 수집해 `race_section_results`를 채운다.
3. 2025~2026 coverage와 결측 패턴을 리포트한다.
4. 말 레이팅·체중 이력으로 첫 point-in-time feature dataset을 만든다.
5. 그 이후에만 baseline 모델을 시작한다.

## 보류된 연구

- 연속 GPS/센서 위치 데이터의 KRA 제공 가능성 문의
- 영상 기반 말 추적의 기술·저작권·원본 품질 검토
- 특허 `10-1976988`의 KIPRIS 원문 및 독립 청구항 재검증
- 경주 전 실시간 배당 snapshot의 공식 제공 여부 조사

