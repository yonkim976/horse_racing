# F1_STYLE6 full-field PL 7승식 최소 기준선

상태: 코드 검토 및 구조 preflight 단계. 명시적인 supervisor 코드 검토 PASS 전까지 온도 적합·평가 확률·성능 지표를 계산하지 않는다.

## 질문과 보존 경계

고정 `F1_STYLE6` raw score에 순차 Plackett–Luce(PL)를 적용해 모든 출전마의 ordered Top3 공동분포를 만들면, 과거 OOS raw score에서 맞춘 공통 temperature 한 개가 `T=1` 기준선보다 확률 정확성을 높이는가?

말 점수 모델은 재학습하지 않는다. 기존 raw score artifact를 읽기 전용으로 재사용하며 같은 해의 보정 probability나 저장 `tau`는 입력으로 쓰지 않는다. 기존 native additive `q(T)`·말별 확률, `20261017_conditional_order_head_v1`의 q-preserving 순서 헤드, 운영 `HY_R_FORM`, `20261020` 축 선택기, 미통과 관계/pair 후보의 출력과 등록부를 변경·대체하지 않는다. 본 작업은 완전 출전집합에 새 최소 PL 분포를 만드는 확률 기준선 비교다. 기존 10/17 순서 헤드는 이전 연구 증거만 참고하며 이번 비교 arm은 아니다.

공식 계약을 확인한 `rules_contract` 산출물을 따라 7승식을 계산한다. 본 확률은 해당 정상 완주 코호트 내 사건확률이며, 과거 승식별 발매·정산 자료를 전수 재현한 수익률이나 실제 풀 가용성으로 해석하지 않는다. PL의 선택독립성 구조는 검증된 말 간 상호작용을 뜻하지 않는다.

## 하나의 비교와 시간 분할

두 arm은 같은 F1_STYLE6 raw score와 runner/race key를 쓴다.

- 기준선: `T=1`.
- 단일 후보: 2019–2023 OOS raw score와 해당 정확 1→2→3 라벨로 경주 균등 joint ordered-Top3 NLL을 최소화한 공통 양의 scalar `T` 한 개. 새 입력, 관계항, 규제, 선택 규칙 탐색은 없다.
- 보정 기간: 2019-01-11–2023-12-30, 2,492경주·25,278출전. 2019–2022는 기존 `20261011_pair_top3_oos_expansion_v1/outputs/F1_STYLE6_{2020..2023}/calibration_scores.parquet`; 2023은 `20261010_style_history_ablation_v1/outputs/F1_STYLE6_2024/calibration_scores.parquet`의 raw `score`만 사용한다.
- 평가 기간: 2024-01-05–2026-09-19, 기존 고정 `evaluation_scores.parquet` 1,779경주·17,412출전·269경주일. 연도별 모델 vintage는 2024/2025/2026 저장 evaluation raw score다. 2024·2025 결과로 temperature를 갱신하지 않는다.

각 raw score의 제공 모델 `refit_max`는 해당 평가/보정 경주보다 앞서며, 기존 피처 계약의 race-date T−2 경계도 유지한다. score key는 frozen feature의 `api_record_id`로 1:1 연결한다. input/라벨/score coverage 불일치, 중복 키, 비유한 score 또는 불완전 race/착순은 조용히 제외하지 않고 사전 quarantine ledger에 기록한 뒤 이 사전 계약의 고정 분모가 달라지면 실행을 멈춘다. 날짜 경계는 역사적 게시시각 증명이 아니다.

## 확률 정의와 temperature fit

경주 `r`의 실제 starter 수를 `N`, raw score를 `s_i`, temperature를 `T>0`, 효용을 `u_i=s_i/T`라 한다. 출전집합 전체의 순차 PL 분포는

`Q_T(i,j,k) = exp(u_i)/sum_h exp(u_h) × exp(u_j)/sum_{h≠i}exp(u_h) × exp(u_k)/sum_{h∉{i,j}}exp(u_h)`

이며 `i,j,k`는 서로 다른 starter다. 이 수식은 log-sum-exp로 안정 계산한다. 전체 `N(N−1)(N−2)` ordered Top3 질량을 경주 단위로 순회하고 1이어야 한다. 모든 Q를 여러 경주에 걸쳐 저장하거나 저장된 상위 조합만 재정규화하지 않는다.

단일 후보 T는 아래 경주 균등 objective를 2019–2023 점수·라벨에서 최소화한다.

`L(T)= (1/R) × Σ_r −log Q_T(actual_1, actual_2, actual_3)`

temperature 범위 `[0.35, 4.0]`은 frozen F1_STYLE6 calibration 계약의 범위를 따른다. `scipy.optimize.minimize_scalar(method="bounded", xatol=1e−12)`를 한 번 실행하고 두 bound의 objective와 optimizer 반환점 중 최솟값을 고른다. 수렴 실패, 비유한 값, 빈 calibration cohort이면 중단한다. 어떤 평가 결과도 선택·재적합·범위 변경에 쓰지 않는다. 최종 후보 T는 모든 2024–2026 평가 race에 고정한다.

합성 검사는 유틸리티의 상수 이동 불변성, 전체 순열 합 1, 말별 win/Top2/Top3 주변 질량 1/2/3, 승식 사건 질량, 공식 연승 경계, 결정적 tie-break를 확인한다.

## 7승식 사건과 정산 범위

ordered Q를 합산해 아래 사건을 얻는다. ticket key는 말 번호의 오름차순(무순위) 또는 순서 tuple(순위 승식)이다.

| 승식 | 티켓 확률 사건 | race별 당첨 티켓 수 | loss 정의 |
|---|---|---:|---|
| 단승 | 말이 1위 | 1 | categorical NLL 및 sum Brier |
| 연승 | 말이 발매 시작 시 두수 기준 Top2/Top3 | 2 또는 3 | 당첨/비당첨 ticket Bernoulli log loss·Brier의 race 내 평균 |
| 복승 | 무순위 두 말이 1·2위 | 1 | categorical NLL 및 sum Brier |
| 쌍승 | 말 A→B가 1→2위 | 1 | categorical NLL 및 sum Brier |
| 복연승 | 무순위 두 말이 모두 Top3 | 3 | 당첨/비당첨 ticket Bernoulli log loss·Brier의 race 내 평균 |
| 삼복승 | 무순위 세 말이 정확 Top3 집합 | 1 | categorical NLL 및 sum Brier |
| 삼쌍승(TRI) | 말 A→B→C가 정확 1→2→3위 | 1 | 전체 ordered triple space의 categorical NLL 및 sum Brier |

복연승은 규칙상 5두 이상 발매 가능, 사건은 항상 Top3 중 두 말이다. 연승은 발매 시작 시 5–7두면 Top2, 8두 이상이면 Top3다. 입력에 발매 개시 roster는 없으므로 final `field_n≥8` race는 “발매 후 추가 출전마 없음”을 조건으로 opening 두수의 하한을 사용해 Top3가 확정된다. opening 두수 미관측과 실제 승식 발매 여부 미확정도 저장한다. 최종 `field_n=7`인 평가 36경주(2025년 4, 2026년 32)는 연승의 Top2/Top3 범위를 정할 수 없어 이 승식의 loss·calibration 분모에서만 quarantine한다. 해당 race는 primary TRI 및 다른 6개 승식 평가에는 남는다. 합성 검사는 opening 5–7의 연승 Top2, opening 8+의 Top3, 복연승 Top3를 각각 확인한다.

현 frozen normal-finish/complete-field 코호트에서 race별 `field_n`은 모든 runner 행 수와 같고, 1·2·3위는 각각 유일하다. 동착, 출전수 불일치, 취소/불성립 또는 정확한 최종 착순을 확인할 수 없는 race가 추후 발견되면 모든 arm·pool에서 제외하고 race/pool/reason을 quarantine ledger에 남긴다. DNF는 점수·착순 원천의 frozen full-starter 계약 밖에서 추정하지 않는다. 정상 유효 경주의 확정 최종착순만 사용하며, 원천이 상위 세 순위의 유일성·complete-field 조건을 보장하지 않으면 해당 race를 통과시키지 않는다. race/pool 계약 원장에는 전체 평가 경주에 `official_race_status=not_audited`, `pool_offered_status=not_audited`, 관측된 `N_at_open=null`을 기록한다. actual `field_n≥8`은 `N_at_open_lower_bound=8`, provenance=`actual_starter_lower_bound_assuming_no_post_open_additions`, `plc_top3_robust=true`로 구분한다.

## 평가·신뢰도·채택 gate

주 지표는 race-equal TRI categorical NLL이다. 후보−T1 차이의 같은-date paired 95% bootstrap CI 상한이 0 미만이고, TRI sum-Brier 점추정 차이도 0 이하일 때만 연구용 calibration candidate gate를 통과한다. bootstrap은 prior direct-pair 연구의 고정 `2,000×269` schedule을 복사 없이 읽고, 정확히 같은 날짜 인덱스를 사용한다. 적합된 T는 bootstrap 반복 중 고정이므로 fit/calibration uncertainty는 CI에 포함하지 않는다.

7승식별 전체 평가 확률의 NLL/Brier, 고정-bin reliability, 2024/2025/2026 연도별 sample 수 및 결과를 따로 보고한다. 각 bin은 모든 가능한 ticket을 하나의 binary event로 펼쳐 고정 경계에 넣는다. bin 표는 pooled event-count weighting(각 ticket event 한 표)으로 집계하고, 이는 race-equal 주 손실과 다른 가중 방식임을 함께 표시한다. 단일 당첨 사건 공간(단승·복승·쌍승·삼복승·삼쌍승)은 categorical NLL 및 `Σ_ticket(p−y)²` sum Brier, 복수 당첨 사건 공간(연승·복연승)은 ticket별 binary log loss/Brier를 race 내 평균한 뒤 race 균등 평균한다. Bernoulli log loss는 `ε=1e−15`로 p를 `[ε,1−ε]`에 clip하고 categorical NLL은 `−log(max(p_true, ε))`로 계산한다. Brier에는 clip하지 않은 원 확률을 쓴다. pool별 loss의 서로 다른 절대 크기로 승식 간 우열을 비교하지 않는다.

고정 reliability bin edge: `[0, 0.00001, 0.00005, 0.0001, 0.00025, 0.0005, 0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 0.75, 1.0]`. 구간은 왼쪽 포함·오른쪽 제외이며 마지막 구간은 1.0을 포함한다. 보정 결과를 본 뒤 경계는 변경하지 않는다.

보조 선택 진단은 승식별 최대 확률 ticket 1개이며 완전히 같은 최대값이면 마번 사전순 tuple을 택한다. 고정 구매수에 대한 확률 순위 적중률만 보고하며 배당, ROI, 시장 우위는 계산하지 않는다. 모든 pool 결과는 그 pool의 정확한 가용 정산 범위와 분모를 함께 보고한다. TRI gate 통과도 기존 `q(T)`·말별 확률·운영 모델 승격 근거가 아니다. 어떤 다른 pool 성능도 TRI gate 판정을 뒤집지 않는다.

## 구조 preflight와 저장 제한

구조 preflight는 hash, source metadata, schema, key/score coverage, race roster/label arithmetic, feature `history_cutoff=race_date−2일`, 각 provider `refit_max≤첫 race date−2일`, 날짜/field 수, quarantine 범위만 검사한다. temperature, Q, 후보 점수, outcome loss, 성능 CI는 만들지 않는다. 명시적 `--fit-evaluate`도 고정된 `supervisor/BASELINE_EXECUTION_APPROVAL.json`이 현재 PLAN·코드·`source_preflight.json`·assets manifest·공식 rules contract SHA에 대해 `PASS`일 때만 허용한다.

원천 파일/모델은 읽기 전용이고 복사하지 않는다. 저장하는 결과는 source/코드/environment hashes, 고정 T와 fit receipt, 1,779경주×7승식 계약 원장, race 단위 두 arm 지표 ledger, pool-year 요약, 고정-bin 집계, quarantine ledger 및 pool/race/arm당 선택 티켓 1개의 `ticket_key`, 확률, 적중 여부, 실제 양의 사건들의 확률·평균 NLL 요약이다. 복수 적중 승식의 실제 이벤트 키는 정렬된 JSON 배열로 보존한다. 별도 소형 runner 원장에는 `p_win`, `p_exact2`, `p_exact3`, `p_top2`, `p_top3`만 저장한다. 모든 ordered Q는 경주에서 aggregate된 후 버린다. 모든 티켓 예측 테이블은 영구 저장하지 않는다. code는 experiment 디렉터리만 쓴다. 신규 저장 목표는 30MB 미만이며 hard stop은 이 실험 250MB, 감독 전체 300,000,000 bytes다.
