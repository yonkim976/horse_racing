# F1_STYLE6 확률·최대 6조합 독립 재산출 결과

입력은 승인된 PLAN/data contract 해시와 기존 source lock으로 확인한 저장 raw score, saved tau 및 F1 replay roster다. 새 fit·tau 최적화·DB 조회를 하지 않았다. 이 결과는 기존 후향 코호트 진단이며 미래 검증이나 원인 인과 추론이 아니다.

## 전체 코호트

| 지표 | F1 | F1_STYLE6 | STYLE6−F1 | 날짜 paired 95% 구간 |
|---|---:|---:|---:|---:|
| Top3 주변 log loss | 0.569469 | 0.568159 | -0.001309 | [-0.002245, -0.000356] |
| Top3 주변 Brier | 0.192724 | 0.192256 | -0.000468 | [-0.000849, -0.000089] |
| 정답 세두 joint NLL | 4.298868 | 4.287044 | -0.011824 | [-0.020153, -0.003451] |
| 전체 joint Brier | 0.979955 | 0.979447 | -0.000508 | [-0.000923, -0.000090] |
| canonical six 적중률 (= hit@6) | 0.223159 | 0.228780 | +0.005621 | [-0.005065, +0.016394] |
| 선택 six 예측 질량 | 0.225091 | 0.230067 | +0.004976 | [+0.004033, +0.005867] |
| hit@1 | 0.062957 | 0.060146 | -0.002811 | [-0.011016, +0.004992] |
| hit@3 | 0.131535 | 0.130972 | -0.000562 | [-0.010729, +0.009735] |
| hit@10 | 0.323215 | 0.341765 | +0.018550 | [+0.006738, +0.030153] |
| hit@20 | 0.509837 | 0.514334 | +0.004497 | [-0.006660, +0.015928] |

## 연도별 적중과 proper loss

| 연도 | F1 six hit | STYLE6 six hit | 차이 | 주변 LL 차이 | joint NLL 차이 |
|---:|---:|---:|---:|---:|---:|
| 2024 | 0.215071 | 0.235479 | +0.020408 | -0.001805 | -0.016323 |
| 2025 | 0.214067 | 0.211009 | -0.003058 | -0.001073 | -0.009576 |
| 2026 | 0.245902 | 0.243852 | -0.002049 | -0.000978 | -0.008965 |

## A 출력과 독립 대조

별도 구현으로 A의 전체 402,808 triple, 3,558 race 진단, 공통 180행 날짜 bootstrap, runner loss 기여, ticket-change loss cross, six-mass reliability, 3,558행 U6 구성·분해를 비교했다. 비교 receipt는 `independent_A_comparison_final.json`이며 수치 최대 절대차는 공통 bootstrap 및 race/triple 지표에서 0, runner contribution에서 1.2e-16 미만이다. 연도별 hit 교체 수도 2024년 신규/상실 28/15, 2025년 15/17, 2026년 10/11로 일치한다.

167개 race에서 runner marginal의 exact argsort 순서가 score exact argsort와 달랐으나, pairwise score–marginal 검사에서 1e-12를 넘는 역순은 0건이었다. 이는 exact score tie 또는 허용오차 내 확률 차이에 관한 runner-order 진단이며 canonical triple rank/top6 변경이 아니다. 저장 tau와 tau=1의 canonical six mismatch는 0건이다.

첫 실행은 계산과 부분 출력 저장 후 Markdown renderer의 `F1_STYLE6` 행 인덱싱 오류로 중단했다. root 보존 지시를 받기 직전 첫 부분 출력 디렉터리를 삭제했으므로 복원할 수 없다. 수정 후 동일한 잠금 입력으로 전체 재계산했으며 시작·종료 해시는 일치한다. 첫 실행 실패는 보고서 harness 오류였고 입력 데이터·모델·DB에는 영향이 없다. 상세 이력은 receipt에 기록했다.

## 재현 및 U6 분해

독립 계산은 34,824개 runner 행, 3,558개 variant-race 행, 21,348개 canonical ticket을 확인했다. 저장 raw score와 marginal, ticket 번호·순위·확률을 1e-12 허용오차로 대조했고 모두 일치했다. 각 경주에서 전체 joint 합은 1, runner marginal 합은 3이었다. 저장 tau와 tau=1의 canonical six가 모두 같음을 직접 검증했다.

| 모델 | hit | allocation miss | union miss | 평균 U6 크기 |
|---|---:|---:|---:|---:|
| F1 | 397 | 463 | 919 | 6.274 |
| F1_STYLE6 | 407 | 468 | 904 | 6.279 |

U6_v는 각 모델의 선택된 여섯 ticket에서 사후적으로 나온 말 합집합이다. 이 분해는 현재 선택 결과의 기술이며 독립적으로 고정한 후보 pool이 아니므로 union miss만으로 말 평가의 원인이나 조합 학습의 필요성을 확정하지 않는다.

## 추가 순위·hit 별칭 진단 (주 평가 gate 아님)

| 진단 | delta | 날짜 paired 95% 구간 |
|---|---:|---:|
| six_hit_alias | +0.005621 | [-0.005065, +0.016394] |
| true_triple_rank | -0.254075 | [-0.589893, +0.081425] |

`six_hit`는 `hit_at_6`의 별칭이며 이 bootstrap은 주 지표 CI와 별도 보조 진단으로 분리했다. 정답 triple 평균 순위도 선택된 여섯 장 성능을 대체하지 않는 순위 진단이다.

가산 triple 분포가 고정되면 canonical top6은 그 분포에서 기대 적중이 가장 큰 여섯 ticket이다. 관측 hit은 같은 과거 코호트에서의 실현 결과로만 해석한다. tau=1 표는 tau 최적화가 아닌 확률 크기 민감도 진단이다.

주변 LL/Brier와 정답 triple joint NLL/full-joint Brier를 함께 보고 주변확률만 개선됐다는 식으로 미리 원인을 정하지 않았다. `ticket_change_loss_cross.csv`는 변경/유지별 개선·악화·동률을, `loss_vs_ticket_change_cross.csv`와 `runner_loss_contributions.csv`는 연도·거리·hit 상태·U6 상태/크기 및 Top3/기타 출전 기여를 교차한다. 손실 변화는 |delta|≤1e-12를 동률로 분류했다.

Six mass 신뢰도는 고정 구간별 평균 예측 mass와 실제 hit rate로 제시한다. 날짜 bootstrap CI 및 모든 상세표는 `outputs/`에 있다. 전체 triple 확률·순위는 `outputs/all_triples.parquet`, 경주 진단은 `outputs/race_diagnostics.parquet`, U6/ticket 집계는 `outputs/ticket_and_union_decomposition.csv`다.
