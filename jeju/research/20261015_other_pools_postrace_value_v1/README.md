# 단승·복승·쌍승·삼복승·삼쌍승 운영 모델의 동일 경주 사후 비교

**해석 핵심:** 120개 고정 전략 결과 중 ROI 날짜-bootstrap 95% 구간의 하한이 0을 넘는 전략은 없다. 삼쌍승(TRI) 전체 후보 max-EV 규칙은 222경주 중 단 1회 적중해 관측 ROI가 +150.14%였지만, 그 최대 당첨 ticket을 빼면 ROI는 −100.00%다. 단승(WIN) 전체 후보 max-EV 규칙도 467경주 ROI가 +0.49%에서 최대 당첨 1장을 제외하면 −9.29%로 바뀐다. 삼복승(TLA) primary 467경주 top3 max-EV 규칙은 +6.73%에서 최대 당첨 1장을 제외하면 −18.04%다. 두 수치는 사후 최종배당을 사용한 표본 결과이며 안정적 수익 근거가 아니다.

이 분석은 이전 operating 대 research 비교의 동일한 2026-01-02~09-12 normal common cohort 467경주·70일을 출발점으로 삼았다. WIN/QNL/EXA/TLA는 전체 467경주에 완전한 final-price 후보 집합을 확인했다. TRI는 API301의 invalid 9999.9 배당 sentinel이 하나 이상 포함된 245경주를 제외해 222경주만 complete-price 평가가 가능했다. 모든 다섯 pool을 같은 222경주에서 비교하는 표도 별도로 제공한다.

HY_R_FORM event p는 저장된 운영 score를 production full ordered Top3 joint distribution에 넣어 계산했다. WIN은 첫째, QNL은 처음 두 말의 무순서 쌍, EXA는 처음 두 말의 정확한 순서쌍, TLA는 unordered Top3 세트, TRI는 정확한 ordered 1-2-3 사건이다. 각 확률은 해당 사건에 속하는 모든 ordered mass의 합이다. native F1_STYLE6 research probability는 root가 독립 검산한 TLA set probability만 비교했다. 나머지 네 시장의 research 확률은 사용하거나 만들어내지 않았다.

모든 규칙은 결과를 보기 전에 PLAN.md에 고정했다: p rank 1–5, rank1 EV>0, all-candidate max EV>0, top3/top5 max EV>0, top3 max EV>0.20. 각 policy는 경주당 최대 1장·1,000원이며 `EV=p×final odds−1`이다. 배당은 결과 뒤에 보관된 final price이므로 EV/ROI는 사후 oracle 점수이며 사전 매수 가능성이나 미래 성과를 뜻하지 않는다. 2026 공통 기간은 여러 번 확인된 개발 자료이고 독립 OOS가 아니다.

## 결과

모든 표는 PLAN.md의 동일한 10개 정책 중 아래에서 지정한 세 규칙만 보여 준다. 95% 구간은 고정 2,000×269 날짜 schedule을 사용했고, 평가 cohort 밖 날짜는 선택 0건으로 계산했다. 전체 결과와 10개 규칙은 `strategy_summary.csv`, `strategy_bootstrap_ci.csv`에 있다.

### 다섯 풀 공통 222경주

TRI final-price candidate set이 완전한 222경주만 사용한 공통 cohort다. 이 조건으로 고른 하위 집합이므로 467경주 primary와 별도로 해석한다. 연구 native probability가 있는 삼복승(TLA)은 운영·research 둘 다 표시한다. 다른 pool의 research 확률은 보유 자료에서 지원되지 않는다.

| Pool | Model | Policy | Bets / eligible | Hits | Net (KRW) | ROI | ROI date-bootstrap 95% CI |
|---|---|---|---:|---:|---:|---:|---:|
| WIN | 운영 HY_R_FORM | p rank 1 | 222 / 222 | 64 | -34,700 | -15.63% | [-35.00, 6.70]% |
| WIN | 운영 HY_R_FORM | p ranks 1–3 max EV > 0 | 198 / 222 | 25 | -10,800 | -5.45% | [-51.17, 52.25]% |
| WIN | 운영 HY_R_FORM | all candidates max EV > 0 | 221 / 222 | 20 | 107,200 | 48.51% | [-22.08, 123.85]% |
| QNL | 운영 HY_R_FORM | p rank 1 | 222 / 222 | 32 | -47,600 | -21.44% | [-47.74, 4.24]% |
| QNL | 운영 HY_R_FORM | p ranks 1–3 max EV > 0 | 188 / 222 | 6 | -136,500 | -72.61% | [-94.56, -46.51]% |
| QNL | 운영 HY_R_FORM | all candidates max EV > 0 | 221 / 222 | 2 | -138,300 | -62.58% | [-100.00, 8.26]% |
| EXA | 운영 HY_R_FORM | p rank 1 | 222 / 222 | 15 | -93,100 | -41.94% | [-71.95, -6.25]% |
| EXA | 운영 HY_R_FORM | p ranks 1–3 max EV > 0 | 171 / 222 | 5 | -114,900 | -67.19% | [-93.09, -35.09]% |
| EXA | 운영 HY_R_FORM | all candidates max EV > 0 | 221 / 222 | 2 | -24,900 | -11.27% | [-100.00, 133.60]% |
| TLA | 운영 HY_R_FORM | p rank 1 | 222 / 222 | 11 | -40,100 | -18.06% | [-81.36, 84.21]% |
| TLA | 운영 HY_R_FORM | p ranks 1–3 max EV > 0 | 180 / 222 | 9 | 87,800 | 48.78% | [-57.12, 186.71]% |
| TLA | 운영 HY_R_FORM | all candidates max EV > 0 | 222 / 222 | 3 | -91,200 | -41.08% | [-100.00, 63.35]% |
| TLA | research F1_STYLE6 | p rank 1 | 222 / 222 | 9 | -58,600 | -26.40% | [-75.80, 38.57]% |
| TLA | research F1_STYLE6 | p ranks 1–3 max EV > 0 | 174 / 222 | 2 | -130,800 | -75.17% | [-100.00, -30.18]% |
| TLA | research F1_STYLE6 | all candidates max EV > 0 | 222 / 222 | 1 | -72,500 | -32.66% | [-100.00, 118.78]% |
| TRI | 운영 HY_R_FORM | p rank 1 | 222 / 222 | 2 | -188,300 | -84.82% | [-100.00, -61.55]% |
| TRI | 운영 HY_R_FORM | p ranks 1–3 max EV > 0 | 169 / 222 | 1 | -141,700 | -83.85% | [-100.00, -49.44]% |
| TRI | 운영 HY_R_FORM | all candidates max EV > 0 | 222 / 222 | 1 | 333,300 | 150.14% | [-100.00, 729.01]% |

### 삼복승 TLA primary 467경주: 운영 대 research

| Policy | Operating bets / hits; net; ROI [95% CI] | Research bets / hits; net; ROI [95% CI] | Paired operating−research ROI difference (pp) [95% CI] |
|---|---|---|---:|
| p rank 1 | 467 / 28; -113,400; -24.28% [-61.79, 28.65]% | 467 / 29; -125,100; -26.79% [-55.13, 6.92]% | +2.51 [-45.48, 57.50] |
| p ranks 1–3 max EV > 0 | 364 / 15; 24,500; 6.73% [-50.91, 81.25]% | 360 / 8; -75,000; -20.83% [-77.43, 47.93]% | +27.56 [-64.48, 126.82] |
| all candidates max EV > 0 | 467 / 4; -215,300; -46.10% [-98.56, 26.75]% | 467 / 1; -317,500; -67.99% [-100.00, 11.03]% | +21.88 [-76.32, 116.41] |

TLA의 `p ranks 1–3 max EV > 0` operating−research paired ROI 차이는 primary 467경주에서 +27.56 pp, 95% CI [-64.48, 126.82]로 0을 포함한다. 같은 규칙의 universal 222경주 차이는 +123.95 pp, 95% CI [8.71, 269.14]다. 222경주 결과는 TRI 가격 완전성에 따라 선택된 부분집합이므로 이를 467경주 전체의 일반적 우위로 해석하지 않는다.

전체 ROI 민감도에서 TRI의 유일한 당첨과 WIN의 최대 당첨 1건을 제외한 값은 위 해석 핵심에 명시했다. 모든 고정 규칙의 적중·stake 및 상위 1·3·5 당첨 제거 수치는 `strategy_summary.csv`에서 확인할 수 있다.

검증: root의 독립 확률·가격·선택·환급·bootstrap 검산은 [ROOT_VERIFICATION_RECEIPT.json](../20261015_other_pools_rootreview_v1/ROOT_VERIFICATION_RECEIPT.json)에 보관했다.

## Files

`candidate_quotes.csv` holds every expected API301 candidate quote, raw value, source run and supplying page SHA, including invalid sentinel rows. `candidate_rows.csv` joins native probabilities and final prices for all operating event candidates and native research TLA candidates, then records exact official event hits. `policy_decisions_pre_outcome.csv` pins choices made from p and fixed final prices before outcome labels are joined. `source_exclusions.csv` lists each TRI-incomplete race and sentinel count. See `SOURCE_PREFLIGHT.json`, `SOURCE_MANIFEST.json`, `probability_mass_audit.csv`, `probability_rank_calibration.csv`, `selection_rank_distribution.csv`, `strategy_bootstrap_ci.csv`, and `FINAL_MANIFEST.json` for audits and details.

Reproduce source audit with `.venv/bin/python -B jeju/research/20261015_other_pools_postrace_value_v1/source_preflight.py` and analysis with `.venv/bin/python -B jeju/research/20261015_other_pools_postrace_value_v1/analysis.py`.
