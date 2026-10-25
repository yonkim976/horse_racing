# 과거 기록 지원도·변동성 정보를 더한 두 말 동시 Top3 확률 비교

상태: 사전설계 및 label-free 원천 감사 진행 중. 원천·설계·코드에 대한 root 검토와 이 폴더의 `outputs/APPROVAL.json` 작성 전에는 후보 optimizer나 H2 Platt map을 실행하지 않고 평가 예측·성과 지표도 만들지 않는다. 이 계획은 후보 결과를 보기 전에 고정한다.

## 질문과 고정 범위

현재 제주 F1_STYLE6 말 점수와 선택된 pair 모델을 보존하면서, 두 말이 함께 Top3에 들 확률에 그 두 말의 과거 관측 지원량·동일거리 이력 수·기록 변동성 정보를 추가하면 pair 확률과 pair 선택이 개선되는지 비교한다. 말별 점수는 다시 적합하지 않는다. HY_R_FORM, 운영 등록부, 기존 실험·DB 및 기존 60열 pair 입력·모먼트·기수 ID 어휘는 읽기 전용이다. 새 후보는 저장된 F1_STYLE6 점수의 `logit(p0)`를 offset으로 쓰며 기존 60개 계수와 새 7개 계수를 함께 재적합한다.

고정 주 비교는 [2026-10-12 기수 ID 후보](../20261012_pair_jockey_id_v1/outputs/evaluation_pair_predictions.parquet)의 선택 pair와 저장 확률 `jockey_id_candidate_calibrated_probability`다. 현재 파일은 1,779경주·76,848 무순서 pair이며 SHA-256은 `0d41ee66149edfae79f2b422ba588c422686a328aad0122071183ee9db6768d6`이다. 보조 비교는 저장 raw Top2 pair와 기수 기본 21열 후보다. 기존 결과를 재적합하거나 결과에 따라 비교 기준을 바꾸지 않는다.

## 보유 원천과 입력 정의

고정 runner 원천은 `20261010_style_history_ablation_v1/outputs/features.parquet` (SHA-256 `036939bd6d518a9e53d458a2f4eb2bf30bfecfa4bb80e21c78edd1f7f44f028f`)이다. 새 열은 `api_record_id`로 기존 점수 roster에만 붙이고 `race_id`, 공식 `horse_id`, 마번, 거리, 경주일을 모두 대조한다. 이름으로 연결하지 않는다. 각 행의 `history_cutoff`가 경주일 `T−2`와 같은지 확인한다. `observed_starts`, `same_starts`, `same_valid_times`, `days_since_same`, `mean5_s`, `valid_n5`, `std5_s`는 이전 고정 feature의 출처 정의를 그대로 쓴다.

- `observed_starts`는 캐시가 관측한 모든 거리의 과거 started 횟수다. `same_valid_times`는 대상 거리에서 보유 과거 범위 안에 확인된 정상 착순·양수 완주시간 횟수이며 최근 5회 수가 아니다. 둘 다 보유 원천 범위의 관측 경력이지 말의 평생 경력 전수 기록은 아니다. `observed_starts` 과거 집계에는 현재 모델 거리범위 밖인 400m의 started 이력도 들어갈 수 있다.
- `mean5_s`는 최근 최대 5개의 실제 같은 거리 출전 슬롯 중 유효한 양수 완주시간의 평균이고 `valid_n5`는 그 평균의 실제 관측 수다. 슬롯 결측을 건너 더 과거 출전으로 채우지 않는다.
- `std5_s`는 같은 최근 5개 실제 슬롯에서 유효한 완주시간의 표본 표준편차(`ddof=1`)이며 원천 정의상 `valid_n5 >= 3`일 때만 제공된다. 두 관측의 표준편차를 다시 계산하거나 결측을 0으로 놓지 않는다. CV 계산은 `valid_n5 >= 3`, `mean5_s > 0`, 유한한 `std5_s >= 0` 모두 만족할 때만 가능하다.
- `days_since_same`는 T−2까지의 가장 최근 같은 거리 started 출전과 목표 경주일 사이의 달력일 간격이다. 마지막 출전이 유효 완주 기록이 아닐 수 있어 완주 기록의 최신성으로 부르지 않는다. 후보는 `same_starts > 0`이고 간격이 유한·비음수일 때 이 값을 사용한다.

입력 원천에서 세 횟수 열은 모두 결측 없이 비음수 정수여야 한다. 실제 결측이나 정의 불일치가 있으면 임의로 0 대체하지 않고 사전감사를 실패시켜 root에 보고한다. 실제 경주 결과·평가 정답·시장 배당은 후보 피처·모먼트·선정·학습에 쓰지 않는다. 배당은 승인 후에도 2025~2026 고정 pair의 사후 잔차 설명 표로만 사용하며 이 연구에서 배당 기반 감점규칙은 만들지 않는다.

## 대칭 pair 입력 7개

각 pair `(i,j)`는 마번 순서를 바꿔도 동일한 7개 값만 받는다.

| 열 | 고정 정의 |
|---|---|
| `log1p_min_observed_starts` | `log1p(min(observed_starts_i, observed_starts_j))` |
| `log1p_min_same_valid_times` | `log1p(min(same_valid_times_i, same_valid_times_j))` |
| `min_valid_n5` | `min(valid_n5_i, valid_n5_j)` |
| `max_cv5_ratio` | 양쪽 모두 CV 계산 조건을 통과할 때 `max(std5_s/mean5_s)`; 아니면 NULL |
| `cv5_unavailable_runner_count` | CV를 계산할 수 없는 말 수 (0..2) |
| `max_log1p_days_since_same_start` | 양쪽 모두 `same_starts > 0`와 유한·비음수 간격을 가질 때 `max(log1p(days_since_same))`; 아니면 NULL |
| `same_start_gap_unavailable_runner_count` | 최근 동일거리 출전 간격을 계산할 수 없는 말 수 (0..2) |

CV는 완주시간의 상대 표본 변동량이지, 등급·주로·중량 등 조건 변화를 보정한 안정성·신뢰도나 인과 효과가 아니다. 신규 pair 값 중 4번·6번은 원천 정보가 양쪽 모두 있을 때만 값이 있고, H1에서 해당 열의 유한한 관측 pair에 가중 평균을 맞춘 뒤 결측 pair를 그 H1 평균으로 채워 z=0이 되게 한다. 5번·7번의 명시 결측 수 열은 그대로 별도 basis로 포함한다. 일곱 열의 평균·척도는 해당 평가 fold의 H1에서만 계산한다. H1 경주당 총 가중치는 동일하고 그 안의 pair는 균등 가중치다. nullable 열의 평균은 유한한 pair support로만 분모를 정규화하며, 분산은 H1 모든 pair 가중치에서 H1 평균 대치 후 계산한다.

## Split·fit 제한

기존 expanded split, OOS score-provider lineage, H1/H2 roster, 2일 purge, 동일 race/pair 조합 규칙을 재사용한다. 2024/2025/2026 fold의 H1 경주는 각각 2,147/2,818/3,458, H2는 각각 336/311/325다. 평가 roster는 637/654/488경주(총 1,779), 17,412 runner, 76,848 pair다. 2026년은 9월까지 부분기간이다.

root 승인 후에만 평가 fold별 단일 67열 후보를 적합한다: 기존 20개 style + 저장된 rolling365 scalar 1개 + 기존 H1 기수 ID effect basis 39개 + 새 신뢰도 basis 7개. ID vocabulary와 39개 범주 모먼트, 기존 60열에 포함된 나머지 모먼트는 원래 H1 저장 계약을 유지한다. 새 7개 모먼트만 후보 H1에서 계산한다. 기존 60개 계수는 후보 내에서 공동 재적합하되 기존 계수·예측 파일을 수정하지 않는다.

fit budget은 H1 pair logistic 3회와 H2 positive-slope Platt map 3회다. 고정 `lambda=1`, 기존 경주 균등 pair BCE, offset `logit(p0)`, intercept 없음, L-BFGS-B 허용오차와 수렴 기준을 그대로 적용한다. Baseline·F1_STYLE6·HY_R_FORM 재학습/재보정은 0회다. optimizer 실패는 중단으로 기록하며 재시도나 추가 fit을 하지 않는다. 기존 원천 code의 H1/H2 label design은 split arithmetics 확인에만 사용할 수 있고 후보 입력 선택이나 모먼트 계산에는 label을 참조하지 않는다. 평가 정답은 prefit feature·moment 계산에 포함하지 않는다.

## 사전 고정 평가

고정 비교 pair와 후보가 새로 선택한 pair를 분리한다.

- **Primary probability:** 현재 ID 후보가 선택한 고정 pair에서 이전 확률과 새 후보 확률의 경주 균등 Brier·log loss 차이를 보고한다. 두 손실 점추정치가 모두 개선되고, 같은 날짜 paired CI에서 적어도 하나의 95% 상한이 0 미만일 때만 확률 gate를 통과한다.
- **Primary selection safety:** 후보가 새로 선택한 pair의 실제 동시 Top3율과 고정 ID pair 대비 적중 차이를 보고한다. 적중 차이가 0 이상이고 paired date CI 하한이 0 초과일 때만 적중 개선을 확인한다. 아니면 미확정으로 표시한다.
- **All-pair guardrail:** 전체 pair의 경주균등 Brier·log loss를 비교한다. 둘 중 어느 하나라도 악화하면 보존/기각 판정에 별도로 반영하고 숨기지 않는다.
- 고정 pair(확률 calibration 효과)와 reranked pair(선택 효과)를 분리하고, 전체·2024·2025·2026, 거리, 관측 경력, 동일거리 유효시간 수별 표와 선택 변화의 gains/losses/ties를 남긴다.
- 날짜 CI에는 기존 `20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy` (2000×269, SHA-256 `d141b0c3f9a463cbfc9d1f4c61228b58757c31aee4ec74b79f41c5baeadaccbd`)를 그대로 쓴다. 날짜 정렬, paired group mask, 0 분모 반복 제외를 유지한다. 결과 확인 후 범위·임계값·스케줄을 바꾸지 않는다.
- 2025~2026 1,142경주의 고정 ID 선택 pair에서 배당 5구간은 사후 보조 잔차 진단만 한다. 배당·가격 계열은 학습·feature selection·threshold/감점·재정렬에 전혀 사용하지 않는다.

이 기간은 여러 선행 연구와 공유한 반복 개발 자료이며 2026년은 부분연도다. 날짜 CI는 이 개발표본의 변동을 설명하며 독립 미래 검증이 아니다. 선택 개선, 확률 보정, 인과적 기록 신뢰도를 서로 구분하고 운영 승격 근거로 해석하지 않는다.

## 사전 산출과 후속 산출

이번 단계는 `SOURCE_PREFLIGHT.json`과 `DESIGN_DRY_RUN.json`만 만든다. preflight는 label-free 원천/key/시점/split/정의 감사이고, design dry-run은 저장 split을 재구성해 67열 shape·H1 신규 모먼트·수렴 코드의 입력 조건을 확인하되 optimizer·H2 map·평가 예측·성과 지표를 실행하지 않는다. dry-run에서 기존 builder가 H1/H2 pair target vector를 구성한다면 그 사실과 사용 범위를 receipt에 적는다.

root 승인 뒤에만 `FOLD_FIT_2024/2025/2026.json`, `FIT.json`, `FIT_RECEIPT.json`을 만든다. 별도 후속 단계에서 승인된 fit의 해시와 새 예측 코드를 고정한 다음 prediction/report/CSV/README/artifact manifest를 완성한다. 중앙 `conclusions/`와 공통 연구 register/manifest는 결과와 root 검토가 완료된 뒤 root가 출판 정책에 따라 갱신한다.
