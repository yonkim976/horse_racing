# F1_STYLE6 축과 확정 단승 최저배당 favorite 불일치 검토

2026-10-20. 이 폴더는 `20261020_axis_disagreement_conditions_v1`의 방법론과 해석을 별도로 검토하고, 고정된 두 진단을 원천 파일에서 다시 계산한 기록이다. 모델 학습, DB 연결, 조건 임계값 탐색, 외부 자료 수집은 하지 않았다. 원 분석 폴더는 편집하지 않았다.

## 고정 표본과 분모

F1_STYLE6 축과 고유 최저 단승배당 favorite가 모두 있는 1,477경주 중 다른 말을 택한 678경주를 주 조건 모집단으로 둔다. 678경주 안의 네 상태는 모델축만 Top3 126, favorite만 Top3 248, 둘 다 173, 둘 다 실패 131이다. 같은 말 선택이거나 어느 한쪽만 성공한 경주만 골라 126 대 248로 비교하는 XOR 374개는 결과로 선택된 부분집단이므로 조건의 예측력이나 전향 선택 규칙을 뜻하지 않는다. 하위군도 항상 네 상태와 678 분모를 함께 읽어야 한다.

전체 1,477경주의 축/favorite Top3 적중은 850/1,477(57.55%)와 972/1,477(65.81%)다. 이는 저장된 선택의 후향 입상률이다. 단승 우승과 Top3는 다른 사건이며, 단승 odds 역수는 Top3 확률이 아니다. 2026년은 9월 19일까지의 부분연도다.

## 저장 이력 변수의 실제 의미

주요 원천 정의는 `20261008_horse_profile_baseline_v1/run.py`, `20261009_finish_history_ablation_v1/CONTRACT.md`, `20261010_style_history_ablation_v1/CONTRACT.md`에서 확인했다. 불일치 리뷰의 원천 시점은 현재 경주일 기준 달력 T−2까지다. 이는 저장 이력 cutoff이며, 과거 정보가 그 시각에 실제 공개됐다는 증거는 아니다.

| 변수 | 저장 정의와 방향 | F1_STYLE6 30입력 여부 |
|---|---|---|
| `observed_starts` | 과거 전체 거리의 started 출전 수 | 포함 |
| `same_starts` | 목표 거리의 과거 실제 출전 슬롯 수 | 포함 |
| `same_valid_times` | 같은 거리 전체 과거 슬롯 중 정상 착순 1..89와 양수 시간 조건을 통과한 수 | 포함 |
| `valid_n5` | 최근 최대 5개의 실제 같은 거리 슬롯에서 유효한 기록 수. 무효 슬롯이 있어도 더 오래된 슬롯으로 채우지 않음 | 포함 |
| `last_time_s`, `mean5_s` | 가장 최근 같은 거리 시간, 최근 실제 같은 거리 최대 5슬롯의 유효 시간 평균. 초가 낮을수록 빠름 | 포함 |
| `best5_s` | 최근 실제 같은 거리 최대 5슬롯의 유효 시간 중 최솟값 | 미포함 |
| `std5_s` | 같은 최근 5슬롯 유효시간의 표본 표준편차. 유효 관측 3개 이상일 때 계산 | 미포함 |
| `trend_s` | 최근 6개의 실제 같은 거리 슬롯을 앞 3/뒤 3으로 나눈 평균시간 차이 `newer3 − older3`. 각 절반 유효 기록 2개 이상. 양수는 최근 느려짐 | 미포함 |
| `previous_top3` | 직전 전체 거리 출전에서 말 자체의 착순이 1..N일 때 1~3위 여부. 해당 경주 전체 순위 완결을 요구하지 않음 | 포함 |
| `previous_finish_relative_rank` | 직전 경주 전체 순위가 완결됐을 때 `(착순−1)/(N−1)`. 0은 1위, 1은 꼴찌 | 포함 |
| `previous_result_status` | 직전 경주 전체 착순의 `normal`/`non_normal_or_incomplete`/`unobserved` 상태. 말 자체의 Top3 유효성과 별개 | 포함 |
| `same_distance_last5_top3_rate` | 최근 같은 거리 최대 5실제 출전 중 정상 개별 착순 결과의 Top3 비율; 분모 0이면 NULL | 미포함. F2 후보 변수였으나 기존 순차 게이트에서 유지되지 않음 |

30개 실제 모델입력 여부는 `F1_STYLE6_2026/meta.json`과 원 분석 폴더의 `FEATURE_CATALOG.csv`로 대조했다. 저장 feature parquet의 55개 열 전체가 모델 입력인 것은 아니다. 특히 `trend_s`, `std5_s`, `best5_s`, 최근 Top3 비율은 이번 F1_STYLE6 점수에 들어가지 않는다.

최근 구간 스타일 입력의 방향은 `20261010_style_history_ablation_v1/CONTRACT.md`와 `prepare.py`에서 확인했다. 상대위치 `r=(순위−1)/(출전자수−1)`는 0이 선두, 1이 후미다. `hist_s1f_relpos_mean5`는 같은 거리 최근 유효 슬롯의 S1F 상대위치 평균이므로 낮을수록 출발 초반에 앞선 위치다. `hist_s1f_to_c4_forward_mean5`는 `r_S1F−r_4C`, `hist_c4_to_g1f_forward_mean5`는 `r_4C−r_G1F`이며 양수는 해당 구간에서 상대적으로 앞으로 이동한 값이다. G1F는 마지막 통과 위치이지 결승선 통과나 막판 속도가 아니다. 이 평균과 해당 support count 3쌍이 모두 모델 입력이다.

`valid_n5=0`을 신마·무경력으로 일반화하면 안 된다. 이 불일치 678개 중 favorite의 `valid_n5=0`은 158개이고, 이 고정 표본에서는 모두 `same_starts=0`이다. 이 중 저장 feature의 `observed_starts=0`으로 과거 시작이 관측되지 않은 말은 34개(2025년 13, 2026년 부분연도 21)이며, 이를 lifetime debut로 단정할 수는 없다. 나머지 124개는 타 거리 이력만 있다(2024년 44, 2025년 50, 2026년 부분연도 30). F1은 전체 관측 경력과 동일거리 지원량을 이미 입력으로 받지만, 타 거리의 능력 시간 자체를 옮기는 feature는 없다.

## 독립 재계산: 지원량 0과 고정 후보집합

`independent_diagnostics.py`는 동결 `selected_rows.csv`, `runner_ledger.csv`, `features.parquet`만 읽고 158개 분해와 248개 market-only 경주 후보집합을 다시 계산한다. selected/ledger hash와 크기를 그 폴더의 기존 `manifest.json`에 대조하고, 세 데이터 입력과 동결 source manifest 경로·크기·SHA-256을 `INDEPENDENT_DIAGNOSTICS.json`에 저장했다.

favorite `valid_n5=0`의 네 outcome 전체는 모델축만 31, favorite만 58, 둘 다 51, 둘 다 실패 18이다. 아래 연도×이력범위 표 역시 네 상태를 모두 보존한다.

| 연도 | 이력범위 | N | 모델만 | favorite만 | 둘 다 | 둘 다 실패 |
|---:|---|---:|---:|---:|---:|---:|
| 2024 | 타 거리 이력만 | 44 | 9 | 17 | 13 | 5 |
| 2025 | 저장 `observed_starts=0` | 13 | 1 | 8 | 4 | 0 |
| 2025 | 타 거리 이력만 | 50 | 12 | 18 | 14 | 6 |
| 2026 부분 | 저장 `observed_starts=0` | 21 | 3 | 11 | 5 | 2 |
| 2026 부분 | 타 거리 이력만 | 30 | 6 | 4 | 15 | 5 |

타 거리 이력만인 124개의 통합 방향(모델만 27, favorite만 39)은 2026 부분표본에서 뒤집혀 모델만 6, favorite만 4다. 2026년 n=30이 작고 이미 보았던 기간이므로, 타거리 이력군에 대한 개선 효과나 안정적 연도 재현으로 읽을 수 없다.

두 번째 고정 진단은 market-only 248경주에서 frozen F1 점수순 상위 3·5마 안에 실제 Top3가 몇 마 포함됐는지다. 내림차순 점수, 동점 낮은 마번 우선으로 순위를 독립 재생성했다. 상위 3마 실제 Top3 수 분포(0/1/2)는 30/149/69로, 하나 이상 포함은 218/248이다. 상위 5마 분포(0/1/2/3)는 3/68/125/52로, 하나 이상 포함은 245/248, 실제 Top3 세 마 모두 포함은 52/248이다. 연도별 완전 카운트는 다음과 같다.

| 연도 | N | Top3 내 실제 Top3 수 0/1/2 | Top3 하나 이상 | Top5 내 실제 Top3 수 0/1/2/3 | Top5 하나 이상 | 실제 Top3 전원 |
|---:|---:|---:|---:|---:|---:|---:|
| 2024 | 78 | 6/50/22 | 72 | 0/21/42/15 | 78 | 15 |
| 2025 | 102 | 13/64/25 | 89 | 1/30/49/22 | 101 | 22 |
| 2026 부분 | 68 | 11/35/22 | 57 | 2/17/34/15 | 66 | 15 |

market-only에서는 축 rank 1이 결과상 실패한 것이 정의에 포함되므로 상위 3 진단은 rank 2~3에 다른 실제 입상마가 들어 있었는지, 상위 5는 rank 4~5를 더 허용할 때 후보를 얼마나 포착했는지를 보여준다. 이는 결과를 알고 난 고정 후보집합 coverage다. 상위 5 전체 포착률을 미래 reranker 성능, 전략 수익, 새 선택 규칙으로 해석하면 안 된다.

## 조건 해석과 개선가설의 경계

직접 관측된 것은 전체 678에서 market-only가 model-only보다 122경주 많다는 점과 위의 고정 지원량·후보 coverage다. 별도 고정 버킷에서 모델 p가 favorite p보다 10%p 이상 높은 368경주(모델만 61, favorite만 144)나, 모델축의 최근시간 평균이 favorite보다 같거나 빠른 310경주(모델만 52, favorite만 122)에서도 market-only가 더 많다. `previous_top3` 축=1/favorite=0인 160경주도 27/66/45/22다. 이 방향은 원 분석 README가 제시한 기술통계와 맞지만, 축 선택·favorite 정체성·확률 차이·결과로 선택된 집단이라 원인 분리나 조건별 switching 규칙을 입증하지 않는다. 모든 거리에서 시장 favorite 쪽 marginal hit가 높다는 고정 표본 결과와도 함께 읽어야 한다.

따라서 “모델이 속도 또는 직전 성적을 과대 가중한다”는 원인 결론은 아직 없다. 후보군 안에 다른 Top3가 자주 있다는 사실은 축 선정/순위 문제의 후속 검증 필요성을 시사하는 가설이다. 후보군 밖으로 실제 Top3가 나온 3/248도 있으므로, reranker만으로 해결된다고 단정할 수도 없다. 확률 잔차 개선과 축 선택 개선은 다른 목표다. 양의 단조 확률 재보정은 점수 순위를 바꾸지 않으므로, F1 axis argmax를 개선한다고 주장할 수 없다.

현재의 assessment와 향후 모델 개선도 나눠야 한다. 시간 정보가 붙은 실제 구매 전 odds가 운영에서 존재한다면, 이는 별도 market-informed 선택전략의 평가가 될 수 있다. 이번의 최종 확정 odds는 시각이 불명확해 그 전략을 재구성하지 못하며, 현 상태에서 모델축/favorite 조건을 운영 switching 규칙으로 만들 수 없다. F1 axis 개선을 목표로 한다면 market identity를 쓰지 않는 고정 후보 reranker를 별도로 검증해야 한다.

안전한 후속 검증 방향은 세 가지다.

1. **저경력·타거리 이력 전달:** `observed_starts=0`, `observed_starts>0 & same_starts=0`, 동일거리 이력 있음의 cohort를 경주 내 모든 말에서 구분한다. 시장 favorite 여부를 조건에 쓰지 않고 T−2 cross-distance time/ability transfer의 지원량을 후보 입력으로 평가한다. 미래 날짜 holdout에서 전체 지표와 해당 사전 cohort를 함께 비교한다.
2. **고정 후보군 reranker:** 기존 F1 평가를 기준으로 계속 보존하고, 새 과거 기간의 out-of-fold runner 예측으로 사전에 정한 후보군 안의 순서만 학습·평가한다. 상위 5의 사후 포착률을 선택 임계값으로 삼지 말고, 새 날짜를 완전히 잠근 뒤 한 번 평가한다. Top1 개선과 후보군의 actual Top3 coverage를 별도 지표로 낸다.
3. **확률 품질과 선택 순위를 분리:** 현재 `calibration_by_group.csv`는 선택된 축/favorite의 그룹별 평균 `(실제 Top3−저장 p_top3)` 잔차다. 이는 전체 runner 단위 calibration curve나 보정 모형이 아니므로 “조건부 평균 예측잔차”로 표현하는 것이 정확하다. 확률 보정은 proper loss 및 전체 runner-level calibration으로 평가하고, rank-changing reranker 개선은 별도 고정 미래표본에서 판정한다.

final `winOdds`, 최저배당 favorite, odds rank, p-gap은 이 과거 자료에서만 만들 수 있는 사후 설명 변수다. 원자료의 가격 공개 시점이 검증되지 않았으므로 이를 사전 예측 feature나 구매 전략으로 쓰는 주장은 누출 위험이 있다. 모델 추론 경로에는 odds를 넣지 않았지만, 조건 버킷이 favorite identity를 이용하면 그 결과는 시장 정보를 보유한 상황에서만 쓸 수 있다.

## 독립 코드·산출물 감사

원 분석 `analysis.py`는 현재 F1_STYLE6 baseline, frozen odds snapshot, T−2 features, root verified ledger를 ID 단위로 대조한다. 코드를 읽어 root `case` 라벨 매핑(`same_hit`/`same_miss`를 `same_pick`으로, 네 불일치 상태를 각 네 case로) 수정을 확인했다. `REPORT.json`은 root flags/case labels 1,477/1,477, 선택 ID 2,954/2,954 일치를 보고한다. source hash 10개 및 manifest에 선언한 산출물 13개의 크기/SHA를 별도 다시 계산했고 모두 일치했다. `FEATURE_CATALOG.csv`에서 F1_STYLE6 정확한 입력은 30개다.

최종 배당은 `race_pair_features.parquet`/`examples.csv`의 설명용 열로 제한돼 있고, odds를 model input, 선택 점수 계산, calibration 수식에 쓰지 않는 것을 코드에서 확인했다. 분모·case 집계, feature join cutoff, 저장 확률/정답 라벨, odds 스냅샷의 수치 일치 검사는 통과했다. 주의할 문구는 `calibration_by_group.csv` 설명의 “확률 보정”이다. 현재 산출물은 모델이나 curve를 보정하지 않고, 특정 선택군에서 평균 잔차만 계산한다. 또한 `exclusive_distribution.csv`는 model-only/market-only outcome으로 이미 나눈 XOR 집단의 프로필 비교이므로 조건 발견이나 독립 확인 증거로 승격하면 안 된다.

검산을 재현하려면 이 폴더의 `independent_diagnostics.py`를 저장소 루트에서 `.venv/bin/python`으로 실행한다. 원천 데이터 해시, 정의 문서·코드 해시, 검토한 mainworker script/README/report/manifest snapshot hash와 산출은 `INDEPENDENT_DIAGNOSTICS.json`에 기록했다. `REVIEW_MANIFEST.json`에는 본 review README/script/진단 JSON의 SHA-256과 크기를 둔다. 원 분석 manifest 재검산은 읽기 전용으로 수행했다.
