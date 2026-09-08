# 진행 현황: 완료와 다음 작업

기준 시각: **2026-09-01**

이 문서는 "지금 어디까지 됐고, 다음에 무엇을 하는가"만 본다.
목표·아키텍처는 [BLUEPRINT](BLUEPRINT.md), 단계별 전체 경로는 [ROADMAP](ROADMAP.md),
모델 설계·판정 수치는 [MODELING_ROADMAP](MODELING_ROADMAP.md), 데이터 건수는
[CURRENT_STATUS](CURRENT_STATUS.md)를 본다.

---

## 1. 한줄 위치

**데이터 수집·정규화(Phase 0~1), 누수 없는 학습 파이프라인(M0~M4), M5 Gate G1,
M6 Gate G2까지 완료됐다.** 고정 앙상블은 단순 기준을 이겨 **G1 PASS**했지만 최종
시장에 독립 신호를 더하지 못해 **G2 FAIL**했다. 경로 B의 사전 예측·공개 검증 원장을
구축하고 첫 live 표본까지 발행했으며, 다음은 T-30분 직전 경주별 자동 운영이다.

별도 연구선으로 배당·레이팅을 쓰지 않는 **2차 순수 능력모델**을 시작했다. 현재 valid
challenger는 경기장·정확거리·주로·당일 variant 보정 속도지수와 자체 Elo·장기 사람
이력·Ranking을 결합한 hybrid이며 win log loss 0.2652, Top1 36.3%, 우승마 Top3 포함
65.6%다. 기존 후보보다 확률 품질과 Top1은 개선됐지만 아직 신규 미래 test를 사용하지 않은
provisional 상태다. 상세는
[ABILITY_V2_NO_RATING](ABILITY_V2_NO_RATING.md)을 본다.

```text
원천 확보 ── JOIN ── 이력 ── 누수 검증 ── Feature ── 기준선 ── 본 모델 ── G1 ●
                                                                            ↓
                                                               시장 비교(G2) ×
                                            → 분석 서비스·공개 검증 원장(경로 B)
                                            ↘ 실시간 배당 snapshot 연구(병행)
```

수익화 관문은 그대로다. G1은 "단순 기준을 이기는가", G2는 "시장 대비 edge가 있는가",
G3는 "구매 시점 배당으로도 재현되는가".

**2026-08-28 live 시작**: `predict-and-publish`가 예정 경주 label-free feature 생성,
고정 앙상블 추론, 확률 일관성 projection, 불변 원장 발행을 한 번에 수행한다. 첫 기록은
16경주·163출전이며 payload SHA-256 재검증을 통과했다. 상세는
[PREDICTION_LEDGER](PREDICTION_LEDGER.md)를 본다.

---

## 2. 완료된 것

### 2.0 2차 순수 능력모델 V5 보정 속도지수 challenger — 2026-08-31

- 배당·레이팅 feature를 학습 직전에 구조적으로 차단하는 모델 프로필 구현
- robust 최근 Form·경주 내 상대속도·정확거리 적성·선행 경합 feature 추가
- 과거 등급 변형·제주 마종/등급체계·부담구별 오염 정규화 추가
- `ability_v5_speed_rich`: 4,097경주·42,375출전·167 feature
- 장기 공통층: 2016~2026년 25,926경주·272,904출전, 2015년 burn-in
- 자체 multiplayer Elo, 장기 기수·조교사 rolling, LambdaRank 구현
- 과거 상위 3두 기반 경기장×정확거리×주로 par, 개최일 track variant, 하위권 검열 구현
- 속도지수 최근 이력 커버리지 94.0%, 동일거리 77.8%, 누수 카나리아 0개
- 2022~2025 binary/Ranking 75:25 walk-forward: LL 0.2731, AUC 0.7694, Top3 63.2%
- challenger run_id `9ef33e36-dfd0-4fc4-b395-cbec2531bde3`
- valid win log loss 0.2652, AUC 0.7901, Top1 36.3%, 우승마 Top3 포함 65.6%
- V4 대비 LL bootstrap 개선 확률 100%, 95% CI 0.00127~0.00317
- V4 대비 Top3 포함은 0.75%p 하락해 미래 표본에서 별도 관찰
- 17경주·169두 label-free end-to-end 추론 및 확률 합 계약 검증
- 단독 누수 카나리아 0개

다음은 모델을 동결하고 2026-08-30 이후 진짜 미래 holdout을 축적하는 것이다.

### 2.0.1 V6 거리·계절 게이트 보정 실험 — 2026-09-01

- 대상 경주 이전 3년만 이용하는 경기장×정확거리×게이트 입상지수 구현
- 계절·주로 희소 조합은 정확거리 부모값으로 계층 수축하고 무표본은 100으로 fallback
- 누수 방지·3년 이동창·희소거리 테스트 추가
- 6개 전체 지수는 최근 valid win LL을 악화시켜 기각
- 거리+계절 2개만 쓰는 `ability_v2_gate` 프로필 추가
- 최근 valid 5-seed 평균: LL 0.267423→0.267235, Top1 +0.42%p, Top3 +0.66%p
- 2022~2025 9,778경주: LL 0.273526→0.273440, Top1 -0.19%p
- 장기 LL bootstrap 95% CI -0.000189~+0.000361로 0 포함
- 결론: **유망하지만 효과가 작아 V5는 유지하고 V6는 실험 후보로 보존**

상세 계약과 결과는 [ABILITY_V2_NO_RATING](ABILITY_V2_NO_RATING.md#v6-거리계절-게이트-보정-실험--2026-09-01)을 본다.

### 2.1 데이터 플랫폼 (Phase 0·1) — 2026-08-25까지

상세 건수·백필 로그는 [CURRENT_STATUS](CURRENT_STATUS.md),
당일 구현 목록은 [SESSION_SUMMARY_2026-08-25](SESSION_SUMMARY_2026-08-25.md).

- 로컬 SQLite + Alembic (head `20260828_0009`)
- KRA OpenAPI LIVE: 일정·출전표·공식 출발번호·결과·확정배당·구간기록
- 말 이력: 레이팅·체중·훈련·진료·프로필 (2025·2026 백필)
- 보강 6종: 기수변경·출전취소·장구·등급변동·출발훈련·심판리포트 (2025·2026 백필)
- FastAPI 로컬 대시보드 (경주·말·기수·조교사·마주; 2026-08-26 디자인 개편)
- `sync-daily` 일일 갱신 명령
- 원본 raw 보존 + SHA-256 + `ingestion_runs`

학습에 쓰는 표본(완료 경주, 2025-01-03 ~ 2026-08-23): **4,108경주 / 42,495행**
(원천 43,463행에서 취소·특수착순·착순 NULL 제외).

### 2.2 모델링 선행 조사 (T1·T2·T4·T5·T6) — 2026-08-28

| 태스크 | 결과 | 문서 |
|---|---|---|
| T1 날씨·주로 누수 | 계획/결과 컬럼 분리. feature는 `*_planned`만 사용 | 마이그레이션 `20260826_0007` |
| T2 출발번호 | API78 `gtno` 수집·검증. 표본 300행 전부 기존 출주번호와 일치 | `services/gate_entry_sheet.py` |
| T4 주파기록 품질 | 오기입 없음. 제주는 속도대가 다름 → 경마장별 필터 | [FINISH_TIME_QUALITY](FINISH_TIME_QUALITY.md) |
| T5 등급 파서 | `국6등급` → (국산, 6, open=False) 등 17종 | `analysis/grades.py` |
| T6 라벨 엣지 | 동착은 올림픽 스킵, 특수코드 91–95·99 실측 | [LABEL_POLICY_AUDIT](LABEL_POLICY_AUDIT.md) |

미완료 선행: **T3**(훈련·진료 실제 공개 시각). 보수적 lookback(경주일 전만 사용)으로
우회 중이라 파이프라인을 막지는 않는다.

### 2.3 학습 파이프라인 (M0~M3) — 2026-08-26

| 마일스톤 | 산출물 | 상태 |
|---|---|---|
| M0 실험 원장 | `analysis/experiments.py`, `data/experiments/model_runs.jsonl`, `list-model-runs` / `compare-runs` | 완료 |
| M1 데이터셋 | `build-dataset` → Parquet + manifest, PIT join, 누수 카나리아, 라벨 정책 | 완료 |
| M2 Feature v1 | 그룹 A~I + 주행심사 **108개**, [FEATURE_CATALOG](FEATURE_CATALOG.md) 자동 생성 | 완료 |
| M3 기준 모델 | B0~B3 + `run-baselines` + valid 리포트 | 완료 |

**재현 명령**

```bash
uv run horse-racing build-dataset --version v2_trials --as-of start_minus_30m
uv run horse-racing build-dataset --version v2_trials --as-of day_before_18
uv run horse-racing write-feature-catalog
uv run horse-racing run-baselines --version v1_full --as-of start_minus_30m
uv run horse-racing list-model-runs --metric valid_log_loss
```

현재 데이터셋: `data/datasets/v2_trials/{start_minus_30m,day_before_18}/`

- `start_minus_30m`: 42,495행 / 4,108경주 / 108 feature / hash `10a8ea33c306`
- `day_before_18`: 42,495행 / 4,108경주 / 103 feature / hash `6421ea7a7101`
  (당일 공개 체중 5개 자동 제외 — PIT 규칙 확인)

두 데이터셋 모두 주행심사 feature 12개를 포함한다. 아래 B0~B3 수치는 주행심사를 추가하기
전 `v1_full` 96-feature 산출물로 측정한 역사적 기준선이며, 비교 가능성을 위해 그대로 보존한다.

**누수 점검**: 실데이터 수치형 87개 단독 AUC 전수. 0.95 초과 없음.
최강 신호는 `form_recent5_pct`·통산 입상률·기수 승률(상식과 일치).

### 2.4 기준선 숫자 (valid, 건드리지 말 것)

기간: 2026-03-01 ~ 2026-05-31, **669경주**. test(2026-06-01~)는 G1 판정 전까지 미평가.

| ID | 내용 | log loss | AUC | top1 |
|---|---|---|---|---|
| B0 | 균등 1/N | 0.3157 | 0.534 | 9.7% |
| B1 | 레이팅 softmax | 0.3137 | 0.571 | 11.6% |
| B2 | 최근 5경주 form softmax | **0.2905** | 0.711 | 28.1% |
| B3 | 시장(확정배당, 비교 전용) | 0.2540 | 0.816 | 38.3% |

해석:

- G1의 "B1 대비 3%"는 거의 자동 통과. **실질 기준선은 B2 = 0.2905**.
- 본 모델이 파고들 공간은 B2(0.2905)와 시장(0.2540) 사이.
- 확정배당은 경주 **후** 값이므로 feature로 쓰지 않는다. B3는 상한 참조다.
- 리포트: `data/experiments/reports/baselines_v1_full_start_minus_30m.md`

구현 위치: `src/horse_racing/analysis/{dataset,pit,metrics,baselines,experiments,grades,features}/`

### 2.5 M4 본 모델·안정성 검증 — 2026-08-27

표준 데이터셋은 `v2_trials/start_minus_30m` 108 feature다. 학습 기간 내부를 시간순
fit·tune·calibration으로 나누고 valid는 모델·보정법 선택에만 사용했다. test는 미평가다.

| 모델 | win log loss | AUC | ECE | top2 LL | top3 LL |
|---|---:|---:|---:|---:|---:|
| LightGBM seed 42 | 0.2737 | 0.7701 | 0.0036 | 0.4156 | 0.5117 |
| LightGBM 5-seed 평균 | 0.2730 | 0.7721 | 0.0042 | 0.4148 | 0.5108 |
| CatBoost seed 42 | 0.2738 | 0.7688 | 0.0051 | 0.4140 | 0.5105 |
| **LightGBM+CatBoost 50:50** | **0.2726** | **0.7726** | **0.0040** | **0.4134** | **0.5094** |

- LightGBM 5-seed win log loss 평균 0.27374, 표준편차 0.00056
- 최종 valid 후보는 5-seed LightGBM과 CatBoost의 50:50 확률 평균
- B2(0.2905) 대비 win log loss **6.15% 개선**
- 서울 0.2713(B2 0.2862), 부산경남 0.2523(B2 0.2764), 제주 0.3018(B2 0.3166)
- ablation 최대 악화: 말 Form +0.0031, 주행심사 +0.0029. 한 그룹 독점 의존 없음
- run_id: `61336314-3615-4a87-bc3c-93a90f448c18`

### 2.6 M5 Gate G1 — PASS (2026-08-27)

고정 후보와 비교 코드를 동결한 뒤 `run-g1-gate --confirm-test`로 holdout test를 한 번
평가했다. gate run_id는 `bab34c2f-682c-4fbc-b676-dba56784f05d`다.

| 모델 | test log loss | AUC | ECE | Top1 | Top3 |
|---|---:|---:|---:|---:|---:|
| B1 레이팅 | 0.3236 | 0.5563 | 0.0086 | 12.3% | 34.9% |
| B2 최근 Form | 0.3034 | 0.6971 | 0.0092 | 22.7% | 53.4% |
| **고정 앙상블** | **0.2845** | **0.7593** | **0.0018** | **30.9%** | **63.7%** |

- 전체: B1 대비 12.06%, B2 대비 6.20% log loss 개선
- 서울: 후보 0.2834 / B2 0.3025, 부산경남: 0.2846 / 0.3004
- 제주 참고: 후보 0.2860 / B2 0.3075
- G1 여섯 조건 전부 PASS. 같은 후보의 test 재평가는 금지한다.

### 2.7 M6 Gate G2 — FAIL (2026-08-28)

`run-g2-gate --confirm-test-market`로 고정 후보의 최종 단승배당 비교를 1회 실행했다.
gate run_id는 `fbda1b74-a258-413d-9bb7-3f233a4a419e`다.

| 항목 | valid / 고정값 | test |
|---|---:|---:|
| 모델 증분계수 β | **-0.0006 ± 0.0816**, 단측 p=0.503 | — |
| 시장 log loss | 0.254344 | **0.270410** |
| 시장+모델 혼합 log loss | 0.254307 | 0.270415 |
| 혼합 개선 bootstrap 95% CI | — | [-0.000231, +0.000214] |
| EV 임계값 | θ=0.05 | 고정 기준 베팅 0건 |

- valid·test 시장 사용 경주: 668/669, 571/582. `9999.9` 센티널·배당≤1 경주는 제외
- overround 중앙값 valid 1.2501 / test 1.2500
- β 양(+) 유의성, test 시장 LL 개선, ROI 중앙값 조건이 모두 실패
- valid 양(+) EV 43건도 6경주에 집중됐고, θ=0.05 선택 표본은 33건/4경주뿐이었다.
  test에서는 선택 베팅이 0건이어서 재현되지 않았다
- 리포트: `data/experiments/reports/g2_v2_trials_start_minus_30m_fbda1b74-a258-413d-9bb7-3f233a4a419e.md`
- 확정배당은 구매 가능 시점 가격이 아니므로, 이 실패를 재튜닝해 뒤집거나 실전 베팅으로
  이어가지 않는다

G1 PASS는 “과거 성적 기반 단순 모델보다 예측력이 좋다”는 뜻이었고, G2 FAIL은 “그 정보가
최종 시장가격에는 이미 반영되어 있다”는 뜻이다.

---

## 3. 앞으로 할 것

### 3.1 바로 다음 — 경로 B 공개 검증 원장

1. 경주 전 `prediction_at`에 말별 win/top2/top3 확률을 append-only로 고정
2. 결과 후 log loss·calibration·Top1/Top3를 자동 정산하고 장기 원장을 공개
3. 기존 대시보드에 확률·근거·검증 이력을 연결해 분석 제품 MVP 구성
4. 공공데이터 재가공·예측정보 서비스의 이용조건과 법적 범위를 확인

**원장 인프라 완료 (2026-08-28):** Alembic `20260828_0009`, SQLite 불변 trigger,
발행·정산·목록·hash 검증 CLI, `/predictions`와 `/api/predictions`를 구현했다.
과거 자료는 `historical`로 분리하며 실제 live 원장은 아직 0건이다. 상세 규칙은
[PREDICTION_LEDGER](PREDICTION_LEDGER.md).

다음 구현은 예정 경주를 결과 라벨 없이 feature화하는 `build-prediction-frame`과 고정 artifact
추론을 연결해, 실제 다음 경주부터 출발 전 publication을 시작하는 것이다.

### 3.2 연구 병행 — 실시간 배당·경주 단위 모델

- 구매 시점 배당 snapshot 원천 조사·저빈도 수집. 과거 시세는 복구할 수 없음
- Plackett–Luce 상위 4두 순서 3두 확률·EV 진단 구현. valid 표본 ROI는 양수였지만
  bootstrap 구간이 0을 넓게 포함하고 고배당 소수 적중에 의존하므로 미래 검증 대기
- Full Plackett–Luce 순위확률·공동착순 주변화·ordered-top3 calibration 구현. 2022~2025
  9,778경주 walk-forward에서 top2/top3 log loss와 ECE는 개선됐지만 win log loss는 악화되어
  단승 기본 모델을 교체하지 않고 삼연승 조합확률 challenger로 유지
- 말별 정확한 1~5위와 누적 TopK 확률을 내는 Top5 LambdaRank+Plackett–Luce를 구현하고
  실제 착순 비교 Parquet를 생성했다. 2022~2025 9,778경주에서 Top1 31.24%, 우승마 Top3
  62.86%, Top5 RPS 0.159579였다. 승리 중심 V1보다 win 지표는 소폭 낮고 Top3 누적확률
  log loss는 0.5275→0.5226으로 개선되어 복합 승식용 challenger로 유지한다. 상세는
  [TOP5_RANK_DISTRIBUTION](TOP5_RANK_DISTRIBUTION.md)
- RaceFit V1 구간 에너지 9개와 잠재 컨디션·3페이스 시나리오를 구현. 동일코드 2022~2025
  9,778경주 비교에서 에너지 운영 후보는 V5 대비 win LL을 0.273689→0.272906,
  Top1을 31.19%→31.46%, Top3를 62.60%→63.04%로 개선했다. LL 개선 paired bootstrap
  95% CI는 [+0.000491,+0.001078]. 컨디션+시나리오 모델은 win LL 0.274025로 열위여서
  challenger로 유지. 상세는 [RACEFIT_V1](RACEFIT_V1.md)
- RaceFit V2에서 2상태 Kalman 컨디션, cross-fit S1F 페이스→LambdaRank, 당일 앞 경주
  편향을 분리 검증. 앞의 두 축은 장기 win LL이 악화되어 제외했다. 출발 30분 전 당일 편향은
  2025 학습→2026 1,657경주에서 동일모델 LL 0.273379→0.270011, Top1
  31.44%→33.19%, Top3 64.15%→65.78%로 개선했고 paired bootstrap 세 지표의 95% CI
  하한이 모두 0보다 높았다. 아직 2026을 선택에 사용했으므로 challenger이며 2026-09 이후
  미래 원장으로 승격 판정한다. 상세는 [RACEFIT_V2](RACEFIT_V2.md)
- conditional logit과 latent rank score listwise 학습, 복승 조합확률 연구
- 새 정보원이나 더 긴 train 백필 후에는 **새로운 미래 holdout**을 정해 G2 가설을 재검증

현재 test를 다시 보며 feature·θ를 조정하는 것은 금지한다.

### 3.3 병행해도 되는 일

| 항목 | 이유 | 시점 |
|---|---|---|
| **실시간 배당 스냅샷 수집기** | 지나간 시세는 복구 불가. G2 전에도 켜 두는 것이 옳다 | 가능하면 M4와 병행 |
| T3 공개시점 실측 | 훈련·진료 lookback을 완화할 수 있음 | 표본 조사 |
| 403 PENDING 활용신청 | 기수/조교사 상세, 수영·언덕 | 승인 대기 |
| UI `SPECIAL_FINISH_LABELS` | T6 실측과 표기 불일치 | 소규모 |
| `data-quality-report` · DB 백업 | 운영 품질 | 여유 시 |

### 3.4 고의로 나중인 것

| 단계 | 내용 | 착수 조건 |
|---|---|---|
| Phase 2 Text 자료실 10년+ 백필 | 학습 표본 확대. G1 실패 시 재도전의 주 수단 | G1 1차 실패 후, 또는 M4 안정화 후 병행 |
| Phase 3 테이블별 Parquet export | 탐색 분석용. 학습 행렬(`build-dataset`)은 이미 있음 | 필요해질 때 |
| Phase 7 paper trading | 구매 시점 배당으로 3개월 재검증 | 현재 중단; 새로운 미래 G2 신호 확인 후 |
| Phase 8 소액 실전 | 수동 주문 원칙 | G3 통과 |
| 경로 B 배포 | 공개 검증 원장·구독 | **현재 바로 다음** |
| PostgreSQL · 영상/GPS | 운영·연구 | 요구가 생길 때 |

---

## 4. 하지 말 것 (현재 위치에서)

- 이미 사용한 test split을 재튜닝에 쓰거나 G2를 재실행하기
- 확정배당(B3)을 feature로 넣기
- `horses` 프로필 통산성적·최신 레이팅 스냅샷을 과거 경주에 JOIN
- G1 전에 Text 백필에 세션을 전부 쓰기 — 파이프라인 버그를 늦게 발견한다
- 제주 소표본 성능으로 전체 판정

---

## 5. 문서 지도

| 궁금한 것 | 문서 |
|---|---|
| 지금 / 다음 (이 문서) | [PROGRESS](PROGRESS.md) |
| 왜 이 제품인가 | [BLUEPRINT](BLUEPRINT.md) |
| Phase·Gate 전체 | [ROADMAP](ROADMAP.md) |
| 모델 설계·수치 기준 | [MODELING_ROADMAP](MODELING_ROADMAP.md) |
| feature 목록 | [FEATURE_CATALOG](FEATURE_CATALOG.md) |
| DB 건수·수집 이력 | [CURRENT_STATUS](CURRENT_STATUS.md) |
| API·명령어 | [DATA_AND_OPERATIONS](DATA_AND_OPERATIONS.md), [DATA_SOURCE_CATALOG](DATA_SOURCE_CATALOG.md) |
