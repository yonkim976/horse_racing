# 사후 QPL 배당을 미리 안다고 가정한 선택 가능성 탐색 계획

## 질문과 해석

저장된 경주별 pair 선택과 그 확률을 그대로 두고, **사후 최종 QPL 표시배당을 미리 알고 있었다고 가정할 때** 배당을 포함한 조건이 어떻게 보이는지 기술한다. 사전 배당은 수집·검증할 수 없으므로 이 분석은 실행 가능한 사전 전략, 수익성 검증 또는 독립 검증이 아니다. 사후 점수 `p × final_quote − 1`은 알려진 최종배당을 이용한 oracle 조건부 점수이며 확률의 참값·실제 기대값·수익 상한을 뜻하지 않는다. 특정 경계의 채택·추천은 하지 않는다.

## 고정 입력과 선택쌍

- 고정 예측: `jeju/research/20261012_pair_jockey_id_v1/outputs/evaluation_pair_predictions.parquet`, SHA-256 `0d41ee66149edfae79f2b422ba588c422686a328aad0122071183ee9db6768d6`.
- 주 분석 선택: `selected_jockey_id_candidate == 1`, 확률 `jockey_id_candidate_calibrated_probability`.
- 보조 비교: `selected_jockey_basic_candidate == 1`, 확률 `candidate_calibrated_probability`. 열 대응은 `pair_jockey_id_report.py`의 `POLICIES`로 확인했다.
- 대상 고정 환급 cohort: 기존 `jeju/research/20261013_pair_qpl_roi_v1/race_returns.csv`에서 각 방법의 2025년 654 + 2026년 488 = 1,142경주. 저장된 선택쌍, 적중 여부, `qpl_quote_odds`를 사용한다. `paid_qpl_odds`는 미적중 0으로 치환된 실현 지급액이므로 가격·선별에는 절대 사용하지 않는다.
- QPL(복연)만 분석한다. 저장 확률은 선택 두 말이 함께 Top3에 들 확률이며 QNL(복승) 확률로 사용하지 않는다.
- 고정 `qpl_quote_odds`를 각 선택쌍의 최종 가격으로 취급하기 전에 로컬 API301 완전 페이지 원문에서 경주일·제주·경주번호·QPL·정확한 조합을 맞춰 2,284 selector-race를 전수 대조한다. 기존 읽기 전용 `pair_payout_audit_v1/analyze.py` helper의 원문 페이지 파서와 완료된 최신 날짜별 페이지 run 선택 규칙을 사용하고, 페이지 파일 SHA와 source registry SHA가 일치하는 것만 인정한다. 원문 index에는 URL, 인증값, 요청 파라미터를 기록하지 않는다.
- 가격 유효성은 결과와 무관하게 정한다: finite이고 `>0`이며 `9999.9`가 아닌 값만 EV 조건·ROI 표본에 포함한다. 9999.9·비양수·결측 건수와 각 방법별 유효 가격 분모를 보고한다. 선택 가능한 조건의 coverage 분모는 고정 1,142경주다.

## 점수, 환급 및 조건

1장당 10,000원. `posthoc_score = p × final_quote − 1`. EV 조건은 `posthoc_score >= threshold`다. 적중 시 실현 환급은 `final_quote × 10,000원`, 미적중 환급은 0원이며, ROI는 `(환급−투입)/투입`이다. 미적중에도 원문과 일치하는 최종 QPL 표시배당이 확인되어야 점수·필터를 계산한다. 이것은 oracle 점수에 따른 사후 선별이다.

고정 12조건을 모두 보고 어떤 조건도 최적 규칙으로 선택하지 않는다.

1. `all_purchase`: 유효 가격 전체
2. 확률만: `p >= 0.30`, `p >= 0.40`
3. 사후 점수만: `score >= 0`, `0.05`, `0.10`, `0.20`, `0.50`, `1.00`
4. 혼합: `p >= 0.30 AND score >= 0`, `.10`, `.20`

각 조건을 전체·2025·2026 부분연도로 나눠 `n`, 고정 1,142 대비 coverage, hits, hit rate, `p` 평균, quote 평균·중앙값, 적중 평균 최종배당, score 평균, stake·payout·net·ROI를 산출한다. 선택된 결과에서 환급이 가장 큰 당첨 1·3·5경주를 각각 제외하고 그 경주의 투입도 분모에서 제거한 ROI 민감도를 계산한다. 조건별 고액 기여 상위 5경주와 EV score 구간 `[-1,0)`, `[0,.10)`, `[.10,.25)`, `[.25,.50)`, `[.50,1)`, `[1,∞)` 보조표를 제공한다. score `< -1`이 발견되면 별도 구간에 보존한다.

## 날짜 재표집과 검증

- 고정 schedule `jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy`, SHA-256 `d141b0c3f9a463cbfc9d1f4c61228b58757c31aee4ec74b79f41c5baeadaccbd`; 원래 예측 날짜 269개 ISO 정렬 목록에 대한 저장된 2,000×269 int32 draw를 그대로 쓴다. 새 draw를 만들지 않는다.
- 모든 fixed condition의 전체·2025·2026 hit rate 및 ROI percentile 95% 날짜 bootstrap CI를 요약한다. 각 replicate에서 조건·가격 유효 mask를 먼저 적용한다. mask 후 선택 경주가 0이면 해당 반복을 제외하고 개수를 기록한다.
- 독립 검산 코드는 분석기 구현을 import하지 않고 저장 예측·환급·원문과 output CSV를 다시 읽어 각 행/분모/산식을 재계산하고 CI schedule/hash 재사용을 확인한다.

## 범위 및 제한

새 수집·네트워크·live probe·학습·재예측을 하지 않는다. SQLite는 `mode=ro`, `PRAGMA query_only=ON`, read transaction으로만 조회한다. 산출물은 이 폴더에만 둔다. 전체 DB 파일을 해시하지 않고 관련 최종 QPL 인용배당·공식 결과 행의 정규화 해시만 기록한다. 2024년은 배당자료 미보유, 2026년은 부분연도, 2025–2026년은 반복 개발자료다. 누출된 사후 가격을 사용하며 확률 불확실성·조건부 기대배당·구매로 인한 시장가격 변화는 반영하지 않는다. 결과는 조건부 사후 진단이지 진정한 수익상한이나 향후 수익의 근거가 아니다.
