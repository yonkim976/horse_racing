# 단계별 개발 로드맵

최종 갱신: 2026-08-28

한 장 요약(완료 vs 다음): [PROGRESS](PROGRESS.md).

이 문서는 "신뢰할 수 있는 데이터 기반"에서 출발해 **검증된 확률 모델로 실제 수익(또는
수익화 가능한 제품)을 만드는 지점**까지의 전체 경로를 정의한다. 설계 원칙과 목표
아키텍처는 [BLUEPRINT](BLUEPRINT.md), 현재 데이터 현황은 [CURRENT_STATUS](CURRENT_STATUS.md),
원천 목록은 [DATA_SOURCE_CATALOG](DATA_SOURCE_CATALOG.md)를 본다.

## 0. 전체 경로와 관문(Gate) 구조

우선순위 원칙은 변하지 않는다.

```text
정확한 원천 확보
  → ID 기반 JOIN
  → 시점별 이력
  → 데이터 누수 검증
  → Feature Engineering
  → 모델링
  → 시장 비교 · Backtest
  → (Gate 통과 시) 실전 검증 · 수익화
```

수익화 관점에서 냉정하게 인식해야 할 사실이 하나 있다. 한국 경마는 pari-mutuel
방식이고 승식별 공제율(takeout)이 대략 20~27% 수준으로 매우 높다. 즉 **모델 확률이
공제 후 배당이 요구하는 손익분기 확률을 일관되게 넘어야만 베팅 수익이 난다.** 이것은
세계적으로도 극소수만 달성한 난이도다. 따라서 이 로드맵은 "베팅 수익"을 유일한
목표로 두지 않고, 각 단계에서 저비용으로 성패를 판정하는 관문을 두어 헛된 투자를
차단하며, 관문 실패 시에도 가치가 남는 산출물(데이터 자산, 분석 제품)을 만든다.

| 관문 | 판정 질문 | 통과 시 | 실패 시 |
|---|---|---|---|
| **G1. 모델 품질** (Phase 5 말) | baseline이 레이팅·인기 기반 단순 모델을 Log Loss/calibration에서 명확히 이기는가? | Phase 6 진행 | feature·데이터 보강 후 1회 재도전, 그래도 실패면 경로 B 전환 |
| **G2. 시장 대비 edge** (Phase 6 말) | 기간 외(out-of-time) 표본에서 시장 암시확률 대비 양(+)의 증분 예측력이 있고, 공제율 반영 backtest ROI가 0을 넘는 구간이 존재하는가? | Phase 7 진행 | 경로 B(분석 서비스화) 전환 |
| **G3. 실전 재현성** (Phase 7 말) | 실시간(구매 시점) 배당 기준 paper trading 3개월에서 backtest와 유사한 성과가 재현되는가? | Phase 8 소액 실전 | 배당 이동·슬리피지 원인 분석 후 재검증 또는 경로 B |

**경로 A(주 경로)**: 베팅 수익. **경로 B(대안)**: edge가 공제율을 못 넘어도
"말별 확률 + 장기 검증 원장 + 데이터 시각화"는 국내에 공개 사례가 드문 제품이므로,
구독형 분석 서비스·데이터 제공으로 전환한다. 어느 쪽이든 Phase 2~5의 산출물은
그대로 재사용된다.

## 1. 현재 위치 (완료 요약)

### Phase 0. 로컬 데이터 기반 — 완료

- [x] Python/uv, SQLite, SQLAlchemy 2, Alembic 기반 구조
- [x] Raw 원본 보존 + SHA-256 + 수집 이력(`ingestion_runs`, `source_documents`)
- [x] 일정·출전표·결과·상세결과·확정배당 수집과 ID 기반 정규화
- [x] 재개 가능한 기간 backfill, 429 한도 대응, 배당 분리 백필
- [x] 2025 전체 + 2026-08-21까지 결과·확정배당 적재
- [x] 일정·결과 로컬 대시보드, 무결성 검사, 회귀 테스트, 문서 체계

### Phase 1. 데이터 범위 확장 — 사실상 완료

- [x] KRA OpenAPI 카탈로그 문서화 ([DATA_SOURCE_CATALOG](DATA_SOURCE_CATALOG.md))
- [x] 구간기록(S1F/코너/G3F/G1F) 2025·2026 백필 + 전개 차트 UI
- [x] 말 이력: 레이팅·체중·훈련·진료·프로필 수집 및 2025·2026 백필
- [x] 보강 6종: 기수변경·출전취소·장구·등급변동·출발훈련·심판리포트 2025·2026 백필
- [x] `sync-daily` 일일 갱신 명령 (수동 실행 기본)
- [ ] 수영·언덕 훈련, 기수/조교사 상세 API — **403 PENDING, 활용신청 대기** (Phase 2.2로 이관)
- [ ] 기수·조교사 기간별 성적 스냅샷 — Phase 2.2로 이관
- [ ] snapshot의 `effective_at`/`observed_at`/`ingested_at` 체계화 — T3·Phase 4.1 잔여

### Phase 4·5 진행 (2026-08-26, 상세는 [MODELING_ROADMAP](MODELING_ROADMAP.md))

- [x] leakage-free `build-dataset` + PIT join + 누수 카나리아 (M1)
- [x] Feature v2 108개(주행심사 12개 포함) + FEATURE_CATALOG (M2)
- [x] 실험 원장 `model_runs.jsonl` (M0)
- [x] 기준 모델 B0~B3, valid 실측 (M3). G1 실질 기준선 = B2 log loss **0.2905**
- [x] LightGBM·CatBoost + calibration + 5-seed·ablation·분해·앙상블 (M4)
- [x] Gate G1 test 1회 판정 (M5) — **PASS**, 후보 LL 0.2845 < B2 0.3034
- [x] Gate G2 test 1회 판정 (M6) — **FAIL**, β=-0.0006(p=0.503), 시장 LL 0.270410
      < 혼합 LL 0.270415, 고정 전략 test 베팅 0건

## 2. Phase 2. 데이터 완결 — 학습 표본 확대와 품질 확보

**목표**: 현재 2개 시즌(2025~2026)뿐인 학습 표본을 Text 자료실로 10년+ 규모로
확장하고, 모델 단계에서 데이터를 신뢰할 수 있게 품질 체계를 만든다.
**예상 기간**: 2~4주 (세션 6~10회). **이 단계가 모델 성능에 가장 큰 지렛대다.**
경주당 출전 두수가 10 안팎이고 연간 경주가 약 2,500개이므로, 2개 시즌만으로는
말·기수·조합 단위 feature의 표본이 얕다. 서울 `dacom11`(경마성적표)은 2003년까지
목록이 확인되어 있어 20년 이상의 결과 이력을 확보할 수 있다.

### 2.1 KRA Text 자료실 대량 importer (최우선)

- [x] **Downloader** (2026-08-28): `meet × fileType × pageIndex` 전체 순회, manifest 선기록,
      SHA-256 중복 스킵, 원자적 rename, 낮은 동시성 + backoff
      ([DATA_SOURCE_CATALOG §8.4](DATA_SOURCE_CATALOG.md) 요구사항 준수)
- [x] `dacom11` 서울·제주·부산경남 2015~2024 레이아웃과 EUC-KR/CP949 표본 조사
- [ ] **다음 파싱 대상 우선순위**: ① `dacom01` 출전표
      ② `dacom12` 체중 ③ `dacom55` 일별조교 ④ `db7` 마명변경 ⑤ `db1`~`db6` 기준정보
- [x] `dacom11` 고정폭 `.rpt` parser: 원본 무변환 보존, 파싱 시 CP949/EUC-KR 해석
- [x] **API 중복 표본 대조**: 2026-08-23 서울 10경주·97두 착순/기록 불일치 0
- [x] 2015~2024 결과·출전 backfill: 24,586경주·260,066출전/결과 적재
- [ ] 여력이 되면 2003~2014 확장 (파서가 견디는 범위까지)

완료 조건: 2015~2024 경주·출전·결과가 API 기간과 동일한 스키마로 적재되고, 중복
기간 대조 리포트가 존재하며, 연도별 coverage 표가 CURRENT_STATUS에 기록됨.

주의: 과거로 갈수록 배당·구간기록·훈련 데이터가 없거나 레이아웃이 다르다. 학습
데이터셋은 "이 연도에는 어떤 필드가 존재하는가" availability matrix와 함께 만든다.

### 2.2 잔여 API 통합

- [ ] 403 PENDING 활용신청: 기수 상세 `API12_1`, 조교사 상세 `API19_1`,
      수영 `API144`, 언덕훈련 (승인 즉시 수집기 추가)
- [ ] 기수·조교사·마주 기간별 성적 API(15089658, 15089711, 15089719 등) 통합
      — 30/90/365일 rolling feature의 교차검증용 (직접 계산값과 대조)
- [x] 비현역 프로필 전량 수집 (`--include-inactive`, 61,534건)
- [ ] `horses.is_active` 플래그 도입 — 활성 여부 자체는 현재 DB에 미보존
- [ ] 마명변경(`db7`) 기반 이름 alias 이력 테이블

### 2.3 데이터 품질 체계

- [ ] `data-quality-report` CLI: 연도·경마장별 coverage(경주/출전/결과/배당/구간/체중/훈련),
      중복, 결측, 고아 행을 한 번에 출력하고 Markdown으로 저장
- [ ] stale `running` ingestion run 정리 명령
- [ ] 원천 간 불일치 기록 테이블(`source_discrepancies`)
- [ ] DB·raw 백업/복원 스크립트 (외장 디스크 또는 클라우드 1곳)
- [ ] 개방 이슈 재시도: 2026-07-06/07 구간 공백, 2025 제주·부산 R6 공백 (주기 재수집)

완료 조건: 품질 리포트 1개 명령으로 재생성 가능, 백업 1회 이상 검증 완료.

## 3. Phase 3. Analytical Layer — Parquet/DuckDB

**목표**: 631MB SQLite를 반복 스캔하지 않고, 버전이 고정된 분석 데이터셋을 만든다.
**예상 기간**: 1~2주. Phase 2와 병행 가능.

- [ ] `export-parquet` CLI: 정규화 DB → 연도·경마장 파티션 Parquet
      (races, entries, results, sections, weights, training, medical, odds 등 테이블별)
- [ ] dataset manifest: schema hash, 생성 시각, 원천 범위(날짜·테이블 행수), 코드 버전
- [ ] DuckDB 분석 노트북/스크립트 표준화 (탐색적 분석은 SQLite가 아닌 Parquet에서)
- [ ] raw-only 재파싱 → DB 재구축 → Parquet 재생성 경로 1회 실증 (재현성 증명)

완료 조건: 동일 raw + 동일 코드 버전으로 byte-수준까지는 아니어도 행 수·통계가
일치하는 dataset을 재생성할 수 있고, manifest만 보고 어떤 데이터인지 알 수 있음.

## 4. Phase 4. Leakage-Free Feature Store

**목표**: "경주 전에 알 수 있었던 값"만으로 구성된 학습 행렬을 프로그램으로 보증한다.
**예상 기간**: 2~3주. **여기서의 부실은 Phase 5~6 전체를 무효화하므로 서두르지 않는다.**

> Phase 4~6의 실행 상세(실측 데이터 제약, feature 카탈로그, 분할·모델·판정 기준 수치,
> 선행 조사 태스크)는 [MODELING_ROADMAP](MODELING_ROADMAP.md)에 별도로 관리한다.

### 4.1 시점 체계

- [x] `prediction_at` 정의 확정: 기본 = 해당 경주 예정 출발시각 − 30분
      (발매 마감 직전 예측을 모사; 출전표 공개 직후 `day_before_18` 변형 지원)
- [ ] 원천별 **공개 시점 카탈로그**: 각 테이블·필드가 현실에서 언제 알 수 있는 값인지
      조사·기록 — 가정은 dataset manifest에 기록됨. 실측은 T3 잔여
      (예: 체중은 당일 공개, 훈련은 익일, 레이팅 스냅샷은 수집 시점만 신뢰)
- [ ] snapshot 테이블에 `effective_at`/`observed_at` 결측 보완 (가능한 범위에서)
- [x] point-in-time join 공통 함수: `analysis/pit.py` `join_asof` backward +
      `PIT_ALLOWED_SOURCES` 화이트리스트

### 4.2 Feature 구현 (v1 카탈로그) — 완료 (2026-08-26)

각 feature는 원천, 계산식, lookback, null 처리, 공개시점 근거, 누수 위험을
`docs/FEATURE_CATALOG.md`에 기록한다. **96개 구현·카탈로그 생성 완료.**

- [x] **말 Form**: 최근 착순 백분위, 출전 간격, 휴양, 속도(경마장별 필터),
      거리대·경마장 성적, 통산 출주수·승률(과거 결과에서 직접 집계)
- [x] **주행 스타일**: S1F 초반 위치, 막판 추입, pace fade, 4C, 스타일 범주
- [x] **체중**: 당일 체중, 직전 5회 평균 대비 편차·변동성 (`day_before_18`에서 자동 제외)
- [x] **훈련·건강**: 3/7/14/28일 훈련, 출발훈련, 진료, 장구 변경, 폐출혈 이력
- [x] **사람**: 기수·조교사 90/365일 승률, 말×기수 조합, 기수변경 플래그
- [x] **경주 컨텍스트**: 등급 파서, 거리, 두수, 부담, 계획 날씨·주로 (`*_planned`)
- [x] **경주 내 상대값**: 레이팅·form·속도·기수승률 등의 z-score와 rank

### 4.3 Leakage 방어 — 완료 (2026-08-26)

- [x] **누수 카나리아 테스트**: 착순 주입 시 AUC≥0.95 탐지 (pytest). 실데이터 96
      feature 전수에서 의심 컬럼 없음
- [x] PIT join 후 `assert_point_in_time` 자동 실행
- [x] 스냅샷 테이블 JOIN 금지 (`ForbiddenSnapshotJoinError`)

완료 조건: `build-dataset --as-of-policy start_minus_30m --version v1` 한 명령으로
학습 행렬(Parquet)이 생성되고, 시점 검증과 카나리아 테스트가 CI(pytest)에서 통과함.

## 5. Phase 5. Baseline 모델과 Calibration

**목표**: 재현 가능한 확률 모델을 만들고 단순 기준 대비 우위를 수치로 증명한다.
**예상 기간**: 잔여 1주 (기준선·원장은 2026-08-26 완료).

- [x] **분할**: 시간 순서. train ≤ 2026-02-28 / valid 2026-03~05 / test ≥ 2026-06-01
      (Text 백필 후 train만 과거로 확장, valid/test 유지)
- [x] **기준 모델 4종**: B0 균등 · B1 레이팅 softmax · B2 form softmax ·
      B3 시장 암시확률(비교 전용). valid 실측은 [PROGRESS](PROGRESS.md)
- [x] CatBoost / LightGBM 이진 분류 (`P(win)`, `P(top2)`, `P(top3)`) + 경주 단위 정규화
- [ ] 경주 단위 모델 1종 비교 (conditional logit / Plackett-Luce 또는 LightGBM ranking)
- [x] Isotonic / Platt calibration 후처리 비교
- [x] **리포트 자동 생성**: `evaluate-model` + 경마장·거리·등급·두수·월 분해
- [x] 실험 추적: `data/experiments/model_runs.jsonl` (M0)

완료 조건 = **Gate G1 판정**: test 기간에서 모델이 레이팅 softmax 기준 모델보다
Log Loss가 명확히 낮고(개선 폭 문서화), calibration이 시각적으로 수용 가능함.
리포트가 명령 1개로 재생성됨.

## 6. Phase 6. 시장 비교와 Backtest — 핵심 관문

**목표**: "시장을 이기는가"를 공제율·현실 제약 포함으로 판정한다. **완료: 2026-08-28.**

- [x] 확정배당(단승)에서 암시확률 계산: `p_i = (1/odds_i) / Σ(1/odds_j)`
      (경주 내 정규화로 overround 제거), 승식별 공제율 상수 문서화
- [x] 모델 vs 시장: Log Loss·calibration 직접 비교 + 혼합회귀
      (`market + model` 혼합이 market 단독보다 나은지 = 증분 예측력 검정)
- [x] **Backtest 엔진**: 단승 기대값 양(+) 베팅, flat / ¼ Kelly 비교. 복승은
      공동입상 조합확률을 낼 순위모형 이후로 이관
- [x] 선택 편향·다중검정 방어: 전략 파라미터는 valid에서만 튜닝, test는 1회 판정
- [x] 위험 지표: 월별 ROI 분포, 최대 낙폭, 연속 손실, 부트스트랩 신뢰구간
- [x] **backtest 한계 문서화**: 확정배당은 마감 후 값이므로 실제 구매 시점 배당과
      다르다(스마트머니 유입으로 통상 불리하게 이동). 이 낙관 편향을 리포트에 명시

완료 조건 = **Gate G2 판정**: 기간 외 test에서 ① 시장 대비 증분 예측력 통계적 확인
② 신뢰구간 하한이 과도하게 음수가 아닌 ROI 구간 존재 — 둘 다 만족해야 통과.
실패 시 경로 B로 전환하고 §9를 실행한다.

**G2 결과: FAIL.** 시장 대비 β가 유의하지 않고 test 혼합 LL도 개선되지 않았다.
경로 A의 paper trading·실전 베팅은 중단하고 §9 경로 B를 다음 본업으로 전환한다.

## 7. Phase 7. 실시간 배당 스냅샷과 Paper Trading (G2 통과 시 — 현재 중단)

**목표**: "구매 가능한 시점의 배당"으로 전략을 재검증한다. 확정배당 backtest의
낙관 편향을 제거하는 단계이며, 실전 수익화의 전제 조건이다. **예상 기간**: 수집기
1~2주 구현 + **3개월 관측 (다른 작업과 병행)**. 스냅샷은 되돌아가 모을 수 없는
데이터이므로 **수집기는 G2 판정 전이라도 가능한 한 빨리 켜 두는 것이 옳다.**

- [ ] 경주 전 실시간 배당의 공식 제공 경로 조사 (OpenAPI 유무, KRA 웹 실시간 배당
      페이지의 이용약관·robots·요청 부하 검토 후 수집 방식 결정)
- [ ] `odds_snapshots` 활용: T-60m부터 마감까지 5분 간격 스냅샷 + `observed_at_ms`
- [ ] 스냅샷 vs 확정배당 이동 분석: 어느 시점 배당이 최종과 얼마나 다른지, 모델이
      좋아하는 말의 배당이 마감까지 어떻게 움직이는지
- [ ] **Paper trading 원장**: 매 경주일 `prediction_at`에 예측 고정 → 구매 시점 스냅샷
      배당으로 가상 베팅 기록 → 결과·손익 자동 정산, 사후 수정 불가능한 append-only 저장
- [ ] 주간 자동 리포트: 누적 ROI, calibration 유지 여부, backtest 대비 괴리

완료 조건 = **Gate G3 판정**: 3개월 paper trading ROI가 backtest 예상 범위 내이고
양(+)의 기대값이 유지됨.

## 8. Phase 8. 소액 실전과 운영 자동화 (G3 통과 시)

**목표**: 실제 돈으로 재현하며 시스템을 무인 운영 수준으로 올린다.

- [ ] 마권 구매 채널·법적 제약 확인: KRA 공식 온라인 발매 가능 여부, 1인 구매 한도,
      세금 처리 (자동 구매 봇은 이용약관 위반 소지가 크므로 **주문 실행은 수동** 원칙)
- [ ] 소액 고정 뱅크롤(잃어도 무방한 금액)로 3개월 실전, paper trading 원장과 동일
      형식으로 기록 — 배당 이동·체결 슬리피지 실측
- [ ] 일일 파이프라인 완전 자동화: 아침 일정·출전표 → 예측 생성 → 대시보드 게시
      → 저녁 결과·정산, 실패 알림(API 한도·스키마 변경·freshness)
- [x] 예측·검증 지표를 보여주는 대시보드 페이지 (`/predictions`)와 JSON API
- [x] `prediction_runs`·`model_predictions`·정산 테이블: 모델 버전별 불변 예측 이력
- [x] 예정 경주 label-free feature frame → 고정 모델 추론 → 불변 원장 발행 한 명령 연결
- [ ] 월 단위 모델 재학습·성능 드리프트 감시 절차
- [ ] (필요 시) PostgreSQL 이전 검토 — 동시 쓰기·원격 접근 요구가 생길 때만

완료 조건: 사람의 개입이 "베팅 승인 클릭"뿐인 상태로 1개월 운영, 실전 손익이
paper trading과 통계적으로 유사함.

## 9. 경로 B. 분석 서비스 수익화 (G2/G3 실패 시 또는 병행)

edge가 공제율을 넘지 못해도 이 프로젝트의 자산은 판매 가능한 형태다. 국내에
"말별 확률 + 사후 수정 불가능한 장기 검증 원장"을 공개하는 서비스는 드물다.

- [x] 공개 검증 원장 인프라: 불변 prediction/settlement 테이블, SHA-256, 발행·정산 CLI,
      `/predictions`와 JSON API ([PREDICTION_LEDGER](PREDICTION_LEDGER.md))
- [x] 실제 미래 경주 feature frame·artifact 추론 연결, 첫 live 16경주·163출전 발행
- [ ] T-30분 직전 당일정보 재수집·경주별 발행·결과 정산 scheduler
- [ ] 무료 티어: 일정·결과·말 이력 조회 (현 대시보드의 공개 배포판)
- [ ] 유료 티어 후보: 경주별 확률·근거 리포트, 말 상세 분석, 데이터 API
- [ ] 공공데이터 재가공·재배포 이용조건 확인 (공공누리 유형), 예측 서비스의
      법적 지위 검토 (경마 정보 제공업 규제 여부)
- [ ] 배포 인프라: FastAPI를 저비용 VPS + PostgreSQL로 이전, 인증·과금

이 경로는 G2 판정 이후에만 본격 착수하되, 검증 원장(첫 항목)은 Phase 7과 동시에
시작하는 것이 이득이다 — 어느 경로로 가든 필요하다.

## 10. 일정 요약

| 단계 | 내용 | 예상 기간 | 병행 |
|---|---|---|---|
| Phase 2 | Text 자료실 10년+ 백필, 잔여 API, 품질 체계 | 2~4주 | — |
| Phase 3 | Parquet/DuckDB 분석 계층 | 1~2주 | Phase 2와 병행 |
| Phase 4 | Leakage-free feature store v1 | 2~3주 | — |
| Phase 5 | Baseline 모델 + calibration → **G1** | 2~3주 | — |
| Phase 6 | 시장 비교 · backtest → **G2** | 2주 | — |
| Phase 7 | 실시간 배당 수집 + paper trading → **G3** | 구현 1~2주 + 관측 3개월 | 수집기는 즉시 가동, 관측은 다른 작업과 병행 |
| Phase 8 | 소액 실전 + 자동화 | 3개월 | 경로 B 준비와 병행 |

합계: 모델 첫 판정(G1)까지 약 2~3개월, 실전 검증 완료까지 약 8~10개월.

## 11. 바로 이어서 할 작업 (다음 세션)

우선순위 근거는 [PROGRESS](PROGRESS.md). **경로 B 공개 검증 원장 MVP와 첫 live 발행은
완료됐다.** M5 G1은 PASS했지만 M6 G2는 시장 대비 독립 신호가 없어 FAIL했다.

1. **경로 B 운영화**: T-30분 직전 당일정보 재수집 → 경주별 예측·발행 → 결과 정산
   scheduler와 실패 알림.
2. (연구 병행, 시간이 지나면 복구 불가) 실시간 배당 스냅샷 원천 조사·수집기 착수.
3. T3 공개시점 실측, 403 PENDING 활용신청. (T2 공식 출발번호 API78은 완료)
4. G1 1차 실패 또는 M4 안정화 후: Text 자료실 downloader (`dacom11` 2015~2024).
5. `data-quality-report` CLI와 백업 스크립트.

## 12. 주요 리스크

| 리스크 | 영향 | 대응 |
|---|---|---|
| 높은 공제율로 edge 부족 (가장 가능성 높음) | 경로 A 실패 | Gate 구조로 조기 판정, 경로 B 전환 |
| Text 자료실 레이아웃 다양성으로 파싱 비용 폭증 | Phase 2 지연 | 분류·기간별 표본 검사 후 가치 높은 분류만 선별 파싱 |
| 미묘한 데이터 누수로 성능 과대평가 | G1·G2 오판 | 카나리아 테스트, 시점 검증 자동화, paper trading 교차확인 |
| 확정배당 backtest의 낙관 편향 | G2 통과가 실전에서 무효 | Phase 7 실시간 스냅샷으로 재검증을 필수화 |
| KRA API 명세 변경·중단 | 수집 중단 | 원본 보존으로 재파싱 가능, freshness 알림, Text 자료실 대체 경로 |
| 소표본 경마장(제주·부경) 과적합 | 특정 구간 손실 | 경마장별 분해 평가, 경마장별 최소 표본 기준 |
| 웹 스냅샷 수집의 약관·부하 문제 | 실시간 배당 확보 불가 | 공식 API 우선 조사, 저빈도 수집, KRA 문의 |

## 13. 보류된 연구

- 연속 GPS/센서 위치 데이터의 KRA 제공 가능성 문의
- 영상 기반 말 추적의 기술·저작권·원본 품질 검토
- 특허 `10-1976988`의 KIPRIS 원문 및 독립 청구항 재검증
- 해외 경마(일본 JRA 등) 데이터로의 방법론 이식 가능성
