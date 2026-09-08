# 예측 모델 상세 로드맵

최종 갱신: 2026-08-28

한 장 요약(완료 vs 다음): [PROGRESS](PROGRESS.md).

이 문서는 [ROADMAP](ROADMAP.md)의 Phase 4(Feature Store) ~ Phase 6(시장 비교)을
실행 가능한 수준까지 상세화한다. 모든 설계는 2026-08-26 로컬 DB 실측값에 근거한다.

## 0. 산출물 정의

최종 산출물은 다음 함수다.

```text
(경주, 출전마, prediction_at)  →  calibrated P(win), P(top2), P(top3)
```

- 확률은 경주 단위로 정규화된다 (한 경주의 P(win) 합 = 1).
- 모든 입력은 `prediction_at` 이전에 공개된 값만 사용함을 프로그램으로 증명한다.
- 학습·평가·리포트는 명령 1개로 재현된다.

넘어야 할 기준선은 하나다. **단승 배당의 암시확률(시장)**. 시장을 못 이겨도
G1(단순 모델 대비 우위)만 통과하면 다음 단계 진행 가치는 있지만, 최종 목표는
시장 대비 증분 예측력이다.

## 1. 실측 데이터 제약 (2026-08-26 DB 확인)

모델 설계를 좌우하는 사실들. 설계 결정의 근거이므로 변경 시 재확인한다.

| 실측 | 값 | 설계에 미치는 영향 |
|---|---|---|
| 완료 경주 / 출전 | 4,145 / 43,463 | GBM에는 충분, 딥러닝·세밀한 상호작용에는 부족. Text 백필(Phase 2)로 표본 확대 전까지 모델 복잡도 억제 |
| `scheduled_at_ms` 존재율 | 100% | `prediction_at = scheduled_at − 30분` 정의 가능 |
| `race_entries.rating` 결측 | 12행 (0.03%) | 핵심 feature로 사용 가능. 결측은 경주 내 중앙값 대체 |
| `body_weight_kg` 결측 | 471행 (1.1%) | 사용 가능. 결측 플래그 병행 |
| `gate_number` | **43,977/43,977 저장** | API78 `gtno`를 공식 원천으로 사용. 3개 경주일 300행 대조에서 기존 출주번호와 전부 일치 (§8 T2) |
| `running_style` | **100% NULL** | 스타일은 구간기록에서 직접 유도해야 함 (§4 D그룹) |
| `finish_position` 분포 | 정상 42,495 / 특수(≥90) 837 / NULL 131 | 라벨 정책 필요 (§2.2) |
| 구간 coverage | S1F·G1F·G3F 각 ~42.4k(거의 전량), 3C·4C 29.2k, G2F·G4F 13k, 1C·2C 소량 | S1F/G3F/G1F를 1급 feature로, 코너·기타는 거리 의존 결측 허용 설계 |
| 확정배당 | WIN 42,801 / PLC 42,698 (+ QNL·EXA·QPL·TRI·TLA) | 전 기간 시장 기준선·backtest 가능. 단 **경주 전 시세 아님** — 평가 전용 |
| `races.weather` / `track_condition` | 계획 API(`wetr`)와 결과 API(`rsutWetr`)가 **같은 컬럼을 덮어씀** | 현재 값은 결과 시점 값일 수 있어 그대로 쓰면 **누수**. 계획 시점 값 분리 필요 (§8 T1) |
| 등급 문자열 | `국6등급`, `혼4등급`, `제5등급`, `1등급`, `혼OPEN` 등 | 접두(국산/혼합/제주)와 숫자 등급을 분리하는 파서 필요 |

## 2. 문제 정의

### 2.1 예측 단위와 시점

- 행 단위: `race_entry` (경주 × 출전마)
- `prediction_at` v1: `scheduled_at_ms − 30분` (발매 마감 직전 모사)
- `prediction_at` v2(변형): 경주 전일 18:00 (출전표 공개 직후 모사) — 체중·기수변경이
  아직 없는 시점. 두 변형을 같은 파이프라인의 파라미터로 지원한다.

### 2.2 라벨 정책

| 상황 | 처리 |
|---|---|
| `finish_position` 1~정상 | win = (pos==1), top2 = (pos≤2), top3 = (pos≤3) |
| `scratched = true` 또는 `finish_position ≥ 90` (제외·취소·주행중지) | 학습·평가 행에서 제외. 단 **경주 내 두수 계산에는 출주 두수만 반영** |
| `finish_position IS NULL` (131행) | 해당 행 제외, 경주는 유지. 경주 전체가 NULL이면(취소일) 경주 제외 |
| `disqualified` / `rank_remark` 존재 | 공식 확정 착순(`finish_position`)을 그대로 신뢰. 재조정하지 않음. **실측: `disqualified` 플래그는 전 행 0 — 착순·비고만 사용** |
| 동착(같은 착순 2두) | 라벨 그대로 (win 2두 가능). **실측: 49경주, 전량 올림픽 스킵(1,1,3) — pos≤2/≤3 라벨이 공식과 일치** |

라벨 정책 구현 후 연도·경마장별 제외 행 통계를 리포트에 포함한다.

### 2.3 최소 요건 필터

- `status = 'completed'` 경주만
- 출주 두수(취소 제외) ≥ 5 (그 미만은 학습·평가 모두 제외하고 건수 보고)
- 신마전(전적 없는 말 다수) 여부는 제외하지 않고 `is_debut` feature로 흡수

## 3. 마일스톤 개요

| 마일스톤 | 내용 | 산출물 | 예상 |
|---|---|---|---|
| M0 | 실험 인프라 | `model_runs` 기록 체계, CLI 뼈대 | 2~3일 |
| M1 | 학습 데이터셋 v1 | `build-dataset` + 시점 검증 + 누수 카나리아 | 4~6일 |
| M2 | Feature v1 | ~~8개 그룹 구현 + FEATURE_CATALOG~~ **완료 (2026-08-26)** | — |
| M3 | 기준 모델 | ~~B0~B3 + 평가 리포트 자동화~~ **완료 (2026-08-26)** | — |
| M4 | 본 모델 | GBM 이진 + 경주 단위 모델 + calibration | 1주 |
| M5 | 평가·판정 | ablation, 안정성 분해, **G1 판정** | 3~5일 |
| M6 | 시장 비교 | 암시확률, 증분 예측력, backtest, **G2 판정** | 1~2주 |

M0~M5 합계 약 5~7주. Phase 2(Text 백필)와 독립적으로 2025~2026 데이터만으로
전체 파이프라인을 먼저 완성하고, 백필 완료 시 동일 파이프라인에 데이터만 늘려
재학습하는 전략을 취한다. **파이프라인 완성이 데이터 확대보다 먼저다** — 그래야
백필의 성능 기여도도 측정할 수 있다.

## 4. M2. Feature v1 카탈로그 (그룹별) — 완료 (2026-08-26)

**전 그룹(A~I)과 주행심사 구현 완료: 108개 feature.** 구현체는
`src/horse_racing/analysis/features/` (context/entry/form/style/condition/trials/people/
relative), 자동 생성 카탈로그는 [FEATURE_CATALOG](FEATURE_CATALOG.md)
(`horse-racing write-feature-catalog`). 실데이터 검증 결과:

- `v2_trials/start_minus_30m`: 42,495행 × 108 feature, hash `10a8ea33c306`
- `v2_trials/day_before_18`: 42,495행 × 103 feature, hash `6421ea7a7101`
  (당일 공개 체중 5개 자동 제외)
- 기존 `v1_full` 96-feature 산출물과 B0~B3 결과는 역사적 기준선으로 보존한다.
- 단독 AUC 카나리아 전 feature 통과 (최대 이탈 |AUC−0.5| ≈ 0.21,
  `form_recent5_pct` 계열·기수 승률이 최강 신호 — 상식 부합, 0.95 초과 없음)
- null 50% 초과 feature 없음 (최고는 코너 위치 계열 ~39%, 거리 의존 결측)

각 feature는 `FeatureSpec`으로 원천 테이블, 계산식, lookback, null 정책,
공개시점 근거, 누수 위험 등급(low/med/high)을 기록한다. 아래는 구현 목록과 원천이다.

### A. 경주 컨텍스트 (원천: `races`)

- 거리, 경마장, 두수, 부담구별(`burden_type`), 연령·성별 조건
- 등급 파서: `국6등급` → (혼합구분=국산, 등급=6) 두 feature로 분해
- 날씨·주로상태: **`*_planned` 컬럼만 사용** (T1 완료. `weather`/`track_condition`
  원본 컬럼은 결과 시점 값일 수 있어 feature 금지)
- 요일, 경주 번호(당일 몇 번째), 월(계절성)

### B. 출전 정적 (원천: `race_entries`, `horses`)

- 공식 출발번호(+두수 대비 상대 위치), 부담중량(절대 + 경주 평균 대비)
- 레이팅(절대 + 경주 내 z-score·rank), 말 나이(월 단위), 성별, 산지
- `is_debut`(과거 결과 0건), 통산 출주수(과거 결과에서 직접 집계 — 프로필 스냅샷 금지)

### C. 말 Form (원천: 과거 `race_results` + `races`)

- 최근 1/3/5/10경주: 착순, 두수 정규화 착순 백분위, 입상률
- 출전 간격(일), 장기 휴양 후 복귀 플래그(>90일)
- **속도지수 v0**: `finish_time_ms`를 (경마장 × 거리 × 주로상태 미사용 버전은
  경마장 × 거리) 그룹의 학습기간 중앙값으로 나눈 비율. 최근 3/5경주 평균과 최고값.
  입력 필터는 [FINISH_TIME_QUALITY](FINISH_TIME_QUALITY.md)의 경마장별 속도 범위 규칙 준수
- 동일 거리대(±200m)·동일 경마장 과거 성적
- 승급·강급 직후 여부 (`horse_grade_changes.start_date_local` 기준 point-in-time)

### D. 주행 스타일 (원천: 과거 `race_section_results`)

- 초반 위치: 과거 경주 S1F `position` / 두수 평균 (최근 5경주)
- 막판 추입: G1F 구간의 위치 상승량, G3F→G1F pace 변화
- 코너(3C·4C) 위치 평균 — 결측(거리 의존)은 결측 플래그와 함께
- 스타일 분류(선행/선입/추입/자유)를 규칙 기반으로 유도해 범주 feature화
- 주의: 구간 원천 공백일(2026-07-06/07 등)은 결측으로 자연 처리됨

### E. 체중 (원천: `race_entries` + `horse_weight_history`)

- 당일 체중, 공식 증감값, 직전 5회 평균 대비 편차, 변동성(표준편차)
- 공개시점: 체중은 당일 계량 후 공개 — `prediction_at = 출발−30분`에서는 사용 가능,
  전일 18:00 변형에서는 **자동 제외**되어야 함 (point-in-time join이 보장)

### F. 훈련 (원천: `horse_training`, `horse_start_training`)

- 최근 3/7/14/28일: 훈련 횟수, 총 `duration_seconds`, 구보(`canter_count`)·
  습보(`gallop_count`) 합, 습보 비중(강도 proxy)
- 마지막 훈련 후 경과일, 출발대 훈련 횟수(최근 28일)
- 공개시점 가정: 훈련 데이터는 익일 공개로 가정하고 `training_date < 경주일` 만 사용
  (보수적). 실제 공개 지연은 T3에서 실측

### G. 건강·장구 (원천: `horse_medical`, `entry_equipment`)

- 최근 14/30/60일 진료 횟수, 마지막 진료 후 경과일
- 폐출혈 이력(`bleeding_count`, 마지막 발생 후 경과일 — `bleeding_date_raw` 파싱)
- 장구 변경: 직전 출전 대비 `equipment_raw` 차이 (첫 착용 blinker 등은 표기 관행
  조사 후 세분화)

### H. 사람·조합 (원천: 과거 `race_entries`+`race_results`, `jockey_changes`)

- 기수: 직전 30/90/365일 승률·복승률·출주수 (전 기간 직접 집계, point-in-time)
- 조교사: 동일 방식. 마주는 v1 제외(효과 낮고 표본 얕음)
- 기수 경마장별·거리대별 승률, 말×기수 과거 조합 성적과 첫 조합 플래그
- 기수변경 발생 플래그와 변경 시점(`jockey_changes.observed_at_ms`가
  `prediction_at` 이전인 경우만)
- 주의: 기수 상세(감량 견습 여부 등)는 API 403 PENDING — 승인 후 v2에서 추가

### I. 경주 내 상대값 (파생)

- 레이팅, 속도지수, 최근 착순 백분위, 체중편차의 경주 내 z-score와 rank
- "경주 내 1위 feature 개수" 같은 요약값

v1 목표 규모는 그룹 합계 60~90개. 그 이상은 표본 대비 과적합 위험이 커진다.

## 5. M1·M0. 데이터셋과 실험 인프라

### M1. `build-dataset` — 완료 (2026-08-26)

- [x] CLI: `build-dataset --version v1 --as-of start_minus_30m|day_before_18`
      → `data/datasets/{version}/{policy}/dataset.parquet` + `manifest.json`
      (행수·경주수·기간·제외 통계·라벨 비율·컬럼 스키마·공개시점 가정·git commit)
- [x] point-in-time join: `analysis/pit.py`의 `point_in_time_join`(polars join_asof
      backward) + `PIT_ALLOWED_SOURCES` 화이트리스트. 스냅샷 테이블
      (`horse_rating_snapshots`, `horse_profile_snapshots`, `horses` 프로필)은
      `ForbiddenSnapshotJoinError`로 join 거부
- [x] 시점 검증기: `assert_point_in_time` — 관측시각 > 예측시점 행 발견 시 예외.
      PIT join 후 자동 실행
- [x] 누수 카나리아: `leakage_canary` — 단독 AUC ≥0.95 feature 탐지 (자체 구현
      Mann-Whitney AUC, 외부 의존성 없음). 착순 주입 시 탐지됨을 pytest로 검증
- [x] 라벨 정책 구현 (`apply_label_policy`): v1 실측 — 원천 43,463행 중 **42,495행 /
      4,108경주** 적재 (취소 512, 특수코드 326, 착순 NULL 130 제외, 소두수·무승자
      경주 0). 라벨 비율 win 0.0968 / top2 0.1936 / top3 0.2902. `day_before_18`
      정책에서는 당일 공개 컬럼(체중)이 자동 제외됨
- [x] `weather_planned` 결측률 1.06% (T1 복구 후) — v1 feature 사용 가능

### M0. 실험 기록 — 완료 (2026-08-26)

- [x] 실험 원장: `src/horse_racing/analysis/experiments.py`의 `ModelRun`(Pydantic) →
      append-only JSONL `data/experiments/model_runs.jsonl`. run_id(UUID), dataset
      version·manifest, feature 목록+SHA-256 해시, 모델 종류·파라미터, seed, 기간,
      지표, git commit 자동 기록. 중복 run_id 거부
- [x] `set_global_seed` 시드 고정 유틸 (`tests/test_experiments.py` 6건 통과)
- [x] CLI: `list-model-runs`(--metric 정렬), `compare-runs`
- [x] `train-model`, `train-catboost`, `evaluate-model`, `run-ablation`,
      `build-ensemble` 구현. test는 명시적 `--include-test`에서만 접근

## 6. M3·M4. 모델

### 분할 (2025~2026 데이터 기준 v1)

경주 단위로 분할하고 시간 순서를 엄수한다.

```text
train  2025-01-03 ~ 2026-02-28  (~2,900 경주)
valid  2026-03-01 ~ 2026-05-31  (~600 경주)   ← 튜닝·전략 선택 전용
test   2026-06-01 ~ 2026-08-21  (~550 경주)   ← 최종 1회 판정 전용
```

- 학습 중 교차검증은 train 내부의 expanding window 3-fold (경주 그룹 유지)
- test는 G1·G2 판정에서 각 1회만 사용. 반복 조회로 오염시키지 않는다
- Text 백필 완료 후: train을 과거로 확장하고 valid/test는 유지 → 백필 기여도 측정

### M3. 기준 모델 4종 — 완료 (2026-08-26)

구현: `analysis/baselines.py`(B0~B3, 시간 분할, β 황금분할 적합) +
`analysis/metrics.py`(log loss·Brier·AUC·ECE·경주 단위 top1/top3, 동점은
기대값 처리). CLI `run-baselines`가 평가·마크다운 리포트·실험 원장 기록까지
수행한다. 리포트: `data/experiments/reports/baselines_v1_full_start_minus_30m.md`

**valid(2026-03~05, 669경주) 실측:**

| ID | 모델 | log loss | AUC | top1 적중 | 비고 |
|---|---|---|---|---|---|
| B0 | 균등확률 1/N | 0.3157 | 0.534 | 9.7% | 지표 하한 |
| B1 | 레이팅 z-softmax (β=0.29, train 적합) | 0.3137 | 0.571 | 11.6% | 레이팅 단독은 약함 |
| B2 | 최근 5경주 착순 백분위 z-softmax (β=0.76) | 0.2905 | 0.711 | 28.1% | **G1 실질 기준선** |
| B3 | 시장 암시확률 (확정배당, overround 정규화) | 0.2540 | 0.816 | 38.3% | 상한 참조 — 비교 전용 |

- B3 배당 커버리지 100% (전 경주 WIN 확정배당 존재), overround 중앙값 ~1.2대
- G1 수치 목표 환산: 본 모델 valid log loss < 0.3043(B1×0.97)이자 **< 0.2905(B2)**
  — B2가 구속 조건. train→valid 성능이 안정적(과적합 징후 없음)
- test split은 미평가 (G1 판정 1회 원칙, `--include-test`로만 접근)

### M4. 본 모델

- [x] **주력**: LightGBM / CatBoost 이진 분류 3종(win/top2/top3), 경주별 확률 합
      1/2/3 제약, 시간순 fit·tune·calibration 분리
- [ ] **경주 단위 비교군**: conditional logit(경제학 정석), LightGBM lambdarank
      + softmax, (여유 시) Plackett-Luce
- [x] LightGBM 5-seed 안정성(LL 평균 0.27374, 표준편차 0.00056) + 확률 평균 앙상블
- [x] calibration: raw 확률에 isotonic/Platt 적용 → 이후 경주 정규화 → ECE 재측정
      (정규화가 calibration을 깨뜨리는 정도를 수치로 기록)
- [x] feature-group ablation + 경마장·거리·등급·두수·월 분해 리포트
- [ ] 범주 인코딩: 기수·조교사 ID는 GBM native categorical 또는 시간 인과적
      target encoding (미래 정보 평균 금지 — expanding mean만)

**M4 고정 후보 (2026-08-27, test 미사용):** 5-seed LightGBM 평균과 CatBoost seed 42의
50:50 확률 앙상블. valid win log loss 0.2726, AUC 0.7726, ECE 0.0040;
B2 대비 6.15% 개선. 서울·부산경남·제주 모두 각 경마장 B2보다 낮다. ablation 최대
delta는 말 Form +0.0031, 주행심사 +0.0029로 특정 한 그룹 독점 의존은 관찰되지 않았다.
run_id `61336314-3615-4a87-bc3c-93a90f448c18`을 M5 후보로 고정한다.

## 7. M5·M6. 평가와 관문 판정

### 지표 (모든 리포트 공통)

- Log Loss, Brier, AUC (win 기준 주지표)
- ECE + calibration curve (10분위)
- 경주별 Top1 적중률, Top3 포함률(모델 상위 3두 안에 우승마)
- 분해: 경마장 × 거리대 × 등급 × 두수 × 월
- 리포트는 `evaluate-model` 한 명령으로 Markdown + 차트 생성

### M5. Gate G1 판정 기준 (수치)

test 기간에서 다음을 **모두** 만족하면 통과.

1. 모델 Log Loss가 B1(레이팅 softmax) 대비 **3% 이상** 낮다
2. B2(form softmax) 대비도 낮다
3. ECE ≤ 0.03, calibration curve에 구조적 왜곡 없음
4. 서울·부산경남 각각에서 1번이 성립 (제주는 표본상 참고만)
5. ablation에서 성능이 특정 1개 feature 그룹에만 의존하지 않음

실패 시: feature 그룹별 기여 분석 → 데이터 보강(Text 백필·PENDING API) 1회
재도전 → 재실패 시 [ROADMAP §9 경로 B](ROADMAP.md) 전환 판단.

**판정 완료 (2026-08-27): PASS.** holdout test 1회 결과 후보 log loss 0.2845,
B1 0.3236, B2 0.3034, ECE 0.0018. 서울 후보/B2 0.2834/0.3025,
부산경남 0.2846/0.3004이며 여섯 조건을 모두 통과했다. gate run_id는
`bab34c2f-682c-4fbc-b676-dba56784f05d`; 동일 후보의 G1 test 재평가는 금지한다.

### M6. 시장 비교와 Gate G2 판정 기준 (수치)

- [x] 단승 암시확률 계산 + 승식별 공제율 상수 문서화 (overround 실측 포함)
- [x] **증분 예측력**: `logit(p) = α·logit(market) + β·logit(model)` 혼합 회귀를
      valid에서 적합, test에서 혼합 Log Loss < market 단독 Log Loss (부트스트랩
      1,000회 95% 신뢰구간으로 유의성 확인, β > 0)
- [x] **단승 backtest**: 기대값 `EV = p_mix × odds − 1 > θ`, θ·베팅 비중
      (flat / ¼ Kelly)은 valid에서만 튜닝, test 1회 판정
- [x] 위험 리포트: 월별 ROI, 최대 낙폭, 연속 손실, 베팅 수, 부트스트랩 ROI 분포
- [x] 낙관 편향 명시: 확정배당은 마감 후 값. 실전 검증은 실시간 스냅샷 필수
- [ ] 복승 backtest: 공동입상 조합확률을 낼 경주 단위 순위모형 이후로 이관

G2 통과 = ① β > 0 유의 ② test flat-stake ROI 부트스트랩 분포의 중앙값 > 0.
(②는 표본이 작아 신뢰구간이 넓을 것이므로, ①이 성립하면 스냅샷 데이터가 쌓이는
동안 판정을 유보하는 중간 결론도 허용한다.)

**판정 완료 (2026-08-28): FAIL.** valid β=-0.000575, race-cluster SE=0.081641,
단측 p=0.5028로 독립 모델 신호가 없었다. test 시장/혼합 log loss는
0.270410/0.270415, 개선량 bootstrap 95% CI는 [-0.000231, +0.000214]였다.
valid에서 선택한 θ=0.05는 33베팅/4경주의 소표본이었고 test 베팅은 0건이었다.
gate run_id `fbda1b74-a258-413d-9bb7-3f233a4a419e`; 동일 후보의 G2 재평가는 금지한다.

## 8. 모델링 전 선행 조사 태스크

M1 착수 전(또는 병행) 해결해야 하는 데이터 이슈. 각각 반나절 이하.

- [x] **T1. 날씨·주로상태 누수 차단** (2026-08-26 완료): `races`에 `weather_planned`,
      `track_condition_planned`, `track_moisture_percent_planned` 추가(마이그레이션
      `20260826_0007`). 계획 API upsert만 planned를 기록하고 결과 API는 건드리지 않음.
      `repair-planned-weather`로 raw racePlan 재파싱 → 4,145경주 중 4,074건(98.3%) 채움
      (racePlan 원본 없음 20건, 계획 응답에 날씨 공란 51건). v1 feature는 planned 컬럼만 사용
- [x] **T2. 게이트 결측 조사·구현** (2026-08-28): 신규 출전표 API78의 `gtno`를
      공식 출발번호로 확인했다. 2025-01-04 서울, 2026-08-28 제주, 2026-08-29 서울의
      300행을 기존 출전표와 대조해 `gtno = horse_number` 및 마명 일치 100%를 확인했다.
      `collect-gate-numbers`와 일정 동기화에 수집·불일치 차단을 구현하고, 검증 근거로
      기존 43,977행의 `gate_number`를 보정했다. 기존 모델 artifact 호환을 위해 feature명
      `horse_number`는 유지하되 값은 `gate_number`를 우선 사용한다.
- [ ] **T3. 공개시점 실측**: 훈련·진료·기수변경의 `observed_at_ms`(수집 시점)와
      실제 공개 시점 차이를 sync-daily 로그로 표본 조사 → F·G·H 그룹 lookback 근거
- [x] **T4. `finish_time_ms` 품질** (2026-08-26 완료, [FINISH_TIME_QUALITY](FINISH_TIME_QUALITY.md)):
      정상 착순 42,495건 결측 0, 20 m/s 초과 오기입 0. 단 **제주는 제주마라 속도대가
      다름**(중앙 ~11.7 m/s) — 공통 12~20 m/s 컷 금지. 권장 필터: 정상 착순 +
      암시속도 서울·부산 12~18 / 제주 10~13.5 m/s (손실 4건, 0.01%). 착순·기록 역전
      4경주는 모두 착변(재결 변경)으로 정상
- [x] **T5. 등급 문자열 파서** (2026-08-26 완료): DB 고유값 17종 전수 확인.
      `analysis/grades.py`의 `parse_race_grade` — `국6등급` → (국산, 6, open=False),
      `혼OPEN` → (혼합, None, open=True). 접두 없는 값은 `1등급`·`2등급`뿐.
      NULL·미지 패턴은 예외 없이 tier=None 처리. 테스트 22건
- [x] **T6. 동착·특수코드 전수 확인** (2026-08-26 완료,
      [LABEL_POLICY_AUDIT](LABEL_POLICY_AUDIT.md)): 라벨 정책 골격 유효 확인.
      동착 49경주/50그룹(항상 2두, 전량 올림픽 스킵 1,1,3 — top2/top3는 pos≤2/≤3
      유지가 공식과 일치). `disqualified` 플래그는 전 행 0이라 사용 금지, 착순·비고
      기준. 특수코드 실측: 91 실격 / 92 주행중지 / 93 출발제외 / 94 경주제외 /
      95 출전취소 / 99 경주취소 (90·96·97·98 없음). scratched·정상착순 모순 0건.
      주의: 웹 UI의 `SPECIAL_FINISH_LABELS` 표기가 이 실측표와 어긋남 — UI 수정 필요

## 9. 흔한 함정 체크리스트 (구현 중 상시 참조)

- 현재 스냅샷(레이팅 최신값·프로필 통산성적)을 과거 경주에 JOIN — **금지, 화이트리스트로 강제**
- target encoding에 전체 기간 평균 사용 — expanding(과거만) 평균만 허용
- valid로 튜닝한 뒤 valid 성능을 보고서에 최종 성능처럼 기재 — test 1회 원칙
- 취소마 포함 두수로 정규화 — 출주 두수 기준
- 확정배당을 "그 시점에 알 수 있던 시세"처럼 feature 사용 — 평가 전용
- calibration 후 정규화로 ECE 악화 방치 — 순서와 영향 수치 기록
- 소표본 제주 성능으로 전체 판단 — 경마장별 분해 필수
- 스냅샷성 테이블의 `observed_at`은 "수집 시각"이지 "공개 시각"이 아님 — T3로 보정
