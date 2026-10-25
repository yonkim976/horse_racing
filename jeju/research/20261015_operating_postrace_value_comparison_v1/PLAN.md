# 운영 HY_R_FORM과 저장 연구 모델의 사후 가치 비교 계획

## 질문과 해석

저장된 현재 운영 `HY_R_FORM`의 native 확률과 각 상품에 지정된 저장 연구 모델 확률을 사용해, 기존 두 사후 가치 연구에서 결과 확인 전에 고정한 구매 규칙의 선택·환급을 동일한 2026 경주에서 비교한다. 사후 최종 표시 배당은 경주 후 가격이므로 `p × final odds − 1`은 회고적 oracle 점수다. 사전 기대수익이나 실제 구매 가능 전략의 검증으로 표현하지 않는다.

현재 frozen HY 평가 산출물은 2026-01-02~09-12뿐이다. 그 모델은 2018-08-31~2025-06-28 학습, 2025-07-04~09-27 종료 선택, 2025-10-02~12-27 확률 보정을 사용했다. 2025년 저장 예측은 평가 OOS가 아니므로 제외한다. 2026년은 반복 확인된 부분연도 개발 자료이며 독립 미래 검증이 아니다. HY 운영 모델은 등록부의 `jeju-hy-r-form-20260919-v1` / `HY_R_FORM`로 확인했고 모델 SHA-256은 `f1b9531e068cab51dff906961d56f51c7c4b0e5a86f378c9aa1f03f159ec9706`이다.

## 동일 경주와 결과 원천

- QPL은 기존 운영 대 연구 일치 원장에서 전체 말 ID 집합·마번·거리·Top3 결과가 일치한 467경주·70일(2026-01-02~09-12)을 사용한다. 467경주 전부 기존 API301 전체 조합 가격 감사의 완전 유효 가격 cohort에 포함된다. 각 경주에서 운영과 `pair_id_baseline`을 동일한 전체 unordered-pair roster 및 동일 final QPL quote에 비교한다.
- PLC는 같은 467경주 중 field size 8두 이상이고 native F1_STYLE6 Top3 확률이 지원되는 436경주·69일을 사용한다. 기존 고정 규칙에서 지원하지 않는 7두 이하 31경주는 양쪽에서 함께 제외한다. 운영과 `F1_STYLE6`을 동일 runner roster·공식 결과·final PLC quote로 비교한다.
- 2026-09-17~19의 21 연구 경주는 운영 평가 상한 뒤라 포함하지 않는다. 기존 운영 정상 편성 공통집합 밖의 43경주도 비교에 넣지 않는다. 미포함 사유별 수와 7두 이하 field 지원 제외는 `cohort.csv`와 source audit에 기록한다.
- 기존 직접 JSON / API301 및 공식 결과 검토가 PASS인 가격 원문과 reference를 사용한다. 말 ID·마번·경주일·경주키·거리·전체 편성·라벨을 대조하고, 모든 말/쌍 가격을 hit 여부를 보기 전에 전수 연결한다. 당첨 가격만 골라 붙이거나 미적중 가격을 지급액에서 유추하지 않는다.

## 확률 계산 계약

- HY pair QPL 확률은 `frozen_scores.parquet`의 저장 set score와 beta로 원 운영 함수 `jeju_hybrid_evaluation.distribution`을 재실행해 얻는 native 정확한 Top3-set 확률에서 계산한다. 각 unordered pair의 확률은 그 두 말이 함께 들어 있는 **모든** 정확한 Top3 집합 확률의 합이다. runner Top3 주변확률의 곱, 단일 unordered Top3-set 확률, 순위 score의 별도 softmax는 사용하지 않는다.
- HY PLC 확률은 같은 native 분포가 내는 runner Top3 주변확률을 사용한다. 저장 `pl_place_probability`와 1e-12 이내 일치해야 한다.
- QPL 연구 확률은 prior primary study의 저장 `jockey_id_candidate_calibrated_probability` (`pair_id_baseline`)만 사용한다. PLC 연구 확률은 prior fixed-policy study의 저장 `F1_STYLE6` native `p_top3`만 사용한다. 연구 모델을 다시 맞추거나 재보정하지 않는다.
- 정확한 QPL 확률 동률은 낮은 unordered 마번 쌍 순으로, runner 확률 rank는 저장 model score 동률일 때 낮은 마번 순으로 정한다. 최대 QPL EV 동률은 기존 all-pair 연구 계약대로 unordered `horse_i`, `horse_j` 오름차순으로 정한다. 최대 PLC EV 동률은 기존 F1_STYLE6 연구 계약대로 확률 rank, 마번 순으로 정한다.

## 고정 구매 규칙

한 선택은 경주당 최대 한 장, 1,000원이다. 각 model·rule을 독립적으로 집계하고 공통 eligible race denominator를 유지한다.

QPL 13개 규칙은 prior all-pair study와 동일하다: 확률 rank 1–5 각각, rank 1의 EV>0, 전체 pair 최대 EV>0, rank 1–3 최대 EV>0, rank 1–5 최대 EV>0, p≥0.20 최대 EV>0, p≥0.30 최대 EV>0, rank 1–3 최대 EV>0.20, p≥0.20 최대 EV>0.20.

PLC 8개 규칙은 prior F1_STYLE6 study와 동일하다: 확률 rank 1·2·3, rank 1의 EV>0, 전체 말 최대 EV>0, rank 1–3 최대 EV>0, p≥0.40 최대 EV>0, p≥0.50 최대 EV>0.

환급은 적중하면 `1,000 × final gross-return odds`, 미적중이면 0이다. 배당은 stake 포함 표시 배수로 해석하고 `ROI=(gross−stake)/stake`로 계산하며 추가 수수료는 빼지 않는다. 임계값이나 모델을 결과를 보고 조정하지 않는다.

## 요약·불확실성

각 상품·모델·rule별로 eligible races, bets, coverage, hits, hit rate, mean selected p/quote/`p×odds−1`, stake, gross, net, ROI를 보고한다. QPL은 probability rank 1–5별 count, mean p, observed hit rate, Brier score, 선택된 pair의 probability-rank 분포를 낸다. PLC는 prior study 정책과 같이 native score rank 및 선택 rank를 보고한다. 각 rule에서 최대 gross 환급 hit 1·3·5건을 그 ticket stake와 함께 제거한 ROI 민감도를 계산한다.

모든 rule과 model 비교는 `jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy`의 고정 2,000×269 draw를 동일하게 사용한다. 원 source의 고정 269일 inventory를 검증하고, 이번 2026 공통 cohort에 속하지 않는 날은 해당 전략에서 0건으로 둔다. ROI/hit-rate percentile 95% 구간, 0 stake draw 수, 동일 날짜 draw의 operating−research ROI 차이 구간을 낸다. 이 구간은 과거 경주일 변동만 반영한다.

## 산출물과 범위 제한

이 폴더에만 분석 코드와 `README.md`, `REPORT.json`, `cohort.csv`, QPL/PLC 선택·요약·rank calibration·rank distribution·bootstrap 결과, source audit/manifest를 저장한다. 운영 등록부, resolver, DB, 운영 예측, 이전 연구는 변경하지 않는다. Network, training, fit, calibration fit, promotion은 없다. 새 비교의 수치는 기존 기간의 후향 기술 분석으로 표시한다.
