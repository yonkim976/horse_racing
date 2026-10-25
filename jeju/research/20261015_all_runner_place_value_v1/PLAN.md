# F1_STYLE6 전체 출전마 연승 기대값 사후 평가 계획

## 목적과 범위

저장된 `F1_STYLE6` 말별 Top3 주변확률과 사후 API301 `PLC` 연승 가격을 결합해, 확률 상위 말 및 `p × odds − 1 > 0`로 선택한 말의 과거 환급·ROI를 기술한다. 기수 조건부 동반 후보의 확률을 말 확률처럼 쓰지 않는다. 모델 재학습·재예측·확률 재보정은 하지 않는다.

모든 결과는 2025년부터 2026-09-19까지 가격이 보유된 경주 중, native Top3 확률을 지원하는 8두 이상 경주를 대상으로 한다. 현재 고정 자료에서는 예상 1,106경주다. 7두 이하 36개 가격 경주는 native Top2 확률 부재로 확률·EV 선택에서 제외한다. 2024년은 PLC 가격 원문이 없어 제외한다. 경주 결과 상한은 2026-09-19다.

## 고정 원천과 코호트 게이트

- 확률·착순 출전 roster: `jeju/research/20261010_style_history_ablation_v1/outputs/report/runner_predictions.parquet`, SHA-256 `706bca01e5f5e780a8ffbe9e2ad4553fea9e3d76df097b4c9648d7aabac44e56`.
- 사후 PLC 가격: `jeju/research/20261014_single_place_returns_v1/source_audit/PLC_PRICE_ROWS.csv`, SHA-256 `257326a9788a88f3fc6f8462c03af1f11b6b4e62e04a4e885d5d812c8bd4e52b`.
- 전체 공식 착순 roster: `jeju/research/20261014_single_place_returns_v1/source_audit/OFFICIAL_RUNNER_RESULTS.csv`, SHA-256 `4ae6133d9d537f9ca6b351ed909a945b88a428cb4babcdf15659e266a68f2df6`.
- 가격 source gate 및 독립 검토: `SOURCE_AUDIT_FINAL.json`은 PLC 원문·페이지 506개 해시 검증 PASS, `ROOT_PLC_SOURCE_REVIEW.json`은 가격 원문 검토 PASS, `ROOT_OFFICIAL_SOURCE_REVIEW.json`은 공식 결과·모델 roster 대조 PASS여야 한다. 각 파일 해시도 산출물 manifest에 기록한다.
- 예측 행은 `race_id + 공식 KRA horse ID + horse_number`로 전체 결과·가격 roster와 각각 일대일 조인한다. field size는 모든 출전말 수와 공식 결과에 맞아야 한다. 가격 cohort 경주에서 모든 실제 출전말의 PLC 가격이 존재하는지 먼저 확인한다. 0, 9999.9, NaN, 비수치 가격은 허용하지 않는다. 승패 여부로 quote 행을 선별하지 않는다.
- native `p_top3`는 저장된 `F1_STYLE6` 집합 주변확률이며 개별 sigmoid 확률이 아니다. `field_n >= 8`에서만 사용한다. 7두 이하 경주에는 Top2 확률을 만들어내지 않고 제외한다.

## 고정 선택 정책

한 정책은 각 해당 경주에서 최대 한 마리만 선택하며 선택 단위는 1,000원이다. 정책별로 독립 집계한다.

1. `p_rank_1`, `p_rank_2`, `p_rank_3`: 저장 점수 내림차순 순위 1·2·3을 매 경주 선택한다. 점수가 실제로 같으면 낮은 마번을 먼저 둔다. 저장 `p_top3`의 아주 작은 부동소수점 표현 차이로 동일 점수의 순서를 바꾸지 않는다.
2. `p_rank_1_ev_positive`: 1위 말의 EV가 양수일 때만 선택한다.
3. `all_runners_max_ev_positive`: 전체 출전말 중 EV 최대인 말이 양수일 때만 선택한다.
4. `top3_max_ev_positive`: 확률 상위 3두 중 EV 최대인 말이 양수일 때만 선택한다.
5. `p_ge_0_40_max_ev_positive`, `p_ge_0_50_max_ev_positive`: 해당 확률 경계 이상인 말 중 EV 최대인 말이 양수일 때만 선택한다.

`EV = p_top3 × 원문 PLC 표시 배당 − 1`로 계산한다. EV 최대 동률은 확률 순위, 마번 순으로 선택한다. 경계값 추가 탐색, 성과 기반 선택, 최적 경계 추천은 하지 않는다. 양수 EV 후보가 없으면 미선택으로 기록하며 stake는 0원이다.

## 성과 계산과 불확실성

공식 순위상 연승 자격은 8두 이상에서 Top3로 정의한다. 선택마 적중 시 gross return은 `1,000 × 원문 배당`, 미적중이면 0원이다. 배당에는 원금이 포함되며 `ROI = gross return / 실제 stake − 1`로 계산한다. 세전 가정이며 사후 표시 배당을 사전 구매 가능 배당으로 해석하지 않는다.

전체 및 연도별로 경주 수, 선택 수·무선택 수, 적중 수·적중률, 평균 예측확률·평균 원문 배당, 평균 모델 EV, gross 환급·순손익·ROI를 낸다. `n=0` 비율/평균은 0이나 100%로 채우지 않고 정의 불가로 둔다. 2026년은 부분연도다.

F1 고정 평가의 269개 날짜·2,000회 date bootstrap schedule을 그대로 재사용한다. 전략별 적중률·ROI의 95% percentile 구간과 valid/zero-stake(ROI 정의 불가) draw 수를 기록한다. 비율 구간은 `%`, 정책 간 차이 구간을 별도 계산할 때는 `percentage point (pp)`로 표시한다. 이 보조 분석은 고정 정책의 사후 기술 평가이며 독립 미래검증·실제 구매전략 검증이 아니다.

최대 환급 관측의 영향을 보이기 위해 각 정책에서 총환급이 가장 큰 적중 wager 1·3·5건을 통째로 제외한다. 해당 행의 환급과 1,000원 stake를 함께 분모·분자에서 빼는 민감도로 계산한다. 선택 사례는 rank3 당첨·미적중을 모두 포함하며, 최종 선택과 확률 1위의 예측값·착순·가격·EV를 함께 제시한다.

## 산출물

`analysis.py`, `README.md`, `REPORT.json`, `selected_rows.csv`, `case_examples.csv`, `summary.csv`, `source_hashes.json`을 이 디렉터리에만 저장한다. 원본 파일, 운영 자료, DB는 수정하지 않는다.
