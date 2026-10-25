# 제주 pair jockey-ID에 기승조건 묶음 하나 추가

상태: 사전 설계 초안. 원천 감사·독립 prefit 검토와 root의 구체적 승인 전에는 학습·보정·평가 예측을 실행하지 않는다.

## 질문과 고정 기준

기존 pair-jockey-ID 후보의 438/1,779 선택 적중에, 실제 직전 기수 연속성·직전/현재 기수의 T−2 기준 365일 성과 차이·말×현재 기수의 과거 기승 경험을 더하면 같은 코호트에서 선택과 확률 품질이 개선되는가? 대상은 선택한 두 말 모두 Top3인 기존 이진 목표다. 말 점수는 저장 `F1_STYLE6`을 고정한다. 기존 20개 style pair basis, 현재 기수 365일 scalar 1개와 공식 기수 ID 효과 39개를 유지한다. 신규 기승조건은 한 묶음, pair 입력 10열로만 추가한다. 기준 계수·점수·확률, 운영 모델·등록부, 중앙 결론은 변경하지 않는다.

기존 ID 비교의 시간분할과 fit 절차를 상속한다. 2024/2025/2026 평가 경주는 각각 637/654/488개(총 1,779경주·269경주일)다. H1 경주는 2,147/2,818/3,458개, 전년도 H2는 336/311/325개이며 H1–H2와 H2–평가 사이 2일 purge를 그대로 둔다. H1에서 기존 60열과 신규 10열을 함께 적합하고 H2에서 양의 기울기를 가진 Platt 보정만 수행한다. 평가기간은 반복 사용한 후향 개발자료며 독립 미래 검증이 아니다.

## 원천과 시간 기준

- 전체 출전·직전출전·말×기수 이력은 `research/20261008_horse_profile_baseline_v1/outputs_v2/source_snapshot.parquet`의 `started` 사건을 사용한다. `started`는 착순 1–89 또는 91/92이며, 2002-07-14~2026-09-19에 90,428행이 관측됐다. 400m와 DNF/실격 등 실제 출전도 포함한다. 평생 완전 이력이 아니라 보유 기록의 기승 경험이다.
- 스냅샷에는 기수 ID가 없으므로 `race_result_rows`의 공식 event `jockey_id`를 `api_record_id`로 연결한다. 이름, 마명, 현재 관계자, ID 숫자 크기로 연결·추정하지 않는다. 과거 직전 출전은 선택된 평가·학습 출전 안에서 찾지 않고, 전체 started 이력에서 T−2 이전 가장 최근 사건 하나를 찾는다. 그 사건의 event 기수 ID가 비었으면 더 오래된 유효 ID로 건너뛰지 않고 unknown으로 둔다.
- 현재·직전 기수의 성과력은 기존 pair ID scalar와 동일한 2017+ 8거리·정상완주·완전편성 `starts.csv` 코호트를 양쪽 모두에 적용한다. T−2는 `target race_date − 2 calendar days`; `T−2` 날짜를 포함하며 공개 timestamp는 확인되지 않았다. 365일 창은 `(T−2−365 days, T−2]`다. 각 기수 성과는 `R=(Σ[Top3−3/field_n])/(n+20)`이며 `n`은 해당 365일 창의 선택 코호트 실제 출전 수다. 직전 기수 성과를 현재 기수 성과에서 빼서 `current−previous`를 만든다. 양쪽 support가 있어야 delta를 정의하고, 부족/미상은 delta 0 대입과 별도 missing 입력으로 보존한다.
- 모든 날짜형 이력은 event 공개시각을 알 수 없다. `T−2` 절단은 과거 날짜 안전장치이며, 그때 실제로 공개됐다는 증거는 아니다. 당일·직후 결과의 사후 정정 가능성도 해소하지 못한다.

## 사전 고정 10열

각 runner의 값을 두 말 unordered pair에서 합해 대칭 pair 입력을 만든다. 표준화 평균·척도는 각 H1만으로 정한다. unknown 값은 0 대입만으로 숨기지 않고 해당 상태 열을 유지한다. 10개 사전 고정 열은 원천 감사·basis 산출물에 전부 보존한다. 각 fold의 H1 모든 pair에서 값 벡터가 완전히 같은 열은 첫 열만 fit에 남기고 나머지 중복 열은 원천 열 이름과 함께 학습 입력에서 제외한다. 그 뒤 scale이 `<=1e-12`인 열도 제외한다. 이 검사는 결과를 보지 않고 시행하는 설계 검증이며 feature 탐색이나 추가 arm이 아니다. 따라서 70열은 제외 전 합동 입력 수이고 실제 fit 열 수는 fold별 중복·상수 열 제외 기록에 따른다.

1. `previous_rider_retained_count`: 실제 직전 event rider ID와 현재 event rider ID가 같다고 확인된 두 runner 수.
2. `previous_rider_unknown_count`: 직전 출전 없음, 직전 event rider ID 미상, 또는 현재 event rider ID 미상인 runner 수. 직전 미상 ID를 건너뛰지 않는다.
3. `rider365_delta_sum`: support가 있는 runner별 `R(current rider)−R(previous rider)`의 합; 유효하지 않은 runner는 delta 기여 0.
4. `rider365_current_support_log1p_sum`: 현재 기수의 365일 support `log1p(n)` 합.
5. `rider365_previous_support_log1p_sum`: 실제 직전 기수의 365일 support `log1p(n)` 합; 직전 ID가 미상이면 0 기여.
6. `rider365_delta_unavailable_count`: 양쪽 성과 support가 없거나 어느 한쪽 ID/성과가 미상인 runner 수.
7. `horse_current_rider_rides_log1p_sum`: 보유 전체 started 이력의 말×현재 event 기수 과거 기승 수 `log1p(n)` 합.
8. `horse_current_rider_recency_log1p_sum`: 마지막 동일 말×기수 started 사건까지 T−2 기준 경과일 `log1p(days)` 합; 미관측은 0 기여.
9. `horse_current_rider_first_observed_pair_count`: 말의 과거 started 사건은 관측됐지만 해당 기수와의 말×기수 사건은 0인 runner 수. 이는 보유 자료의 첫 관측 조합이며 생애 첫 기승 확정이 아니다.
10. `horse_current_rider_history_unavailable_count`: 보유 이력에서 과거 말 출전이 없거나 현재 기수 ID가 없어 말×기수 경험을 판단할 수 없는 runner 수. 이 상태를 첫 기승으로 바꾸지 않는다.

말×기수 과거 기승 수가 1회 이상이면 재기승 관측이며 개수와 최근성이 각각 표시된다. 이 정의는 현재 기수 365일 scalar·ID 효과와 강하게 겹칠 수 있으므로 계수나 선택 변경은 조건부 증분 연관성으로만 해석한다. 작은 표본 하위군 결과를 가점·승부 의도·마방별 고정 규칙으로 만들지 않는다.

`rider365_delta_sum`의 runner 단위 delta는 양쪽 ID가 있고 `n_current>0` 및 `n_previous>0`일 때만 계산한다. 어느 쪽이든 support가 0이거나 ID가 없으면 0 placeholder를 쓰고 `rider365_delta_unavailable_count`로 상태를 보존한다. 각 지원도 열은 해당 ID가 미상일 때 0 placeholder를 쓴다. 10열의 H1 평균·척도는 각 fold H1의 모든 pair를 대상으로, race-equal pair weight를 주고 0 placeholder를 포함해 계산한다. missing/state 열도 같은 H1 분모를 쓴다. H1 모든 pair의 raw 값이 완전히 같은 중복 열은 사전 열 순서상 첫 열만 fit에 남기고 중복 대상 이름을 기록한다. `scale<=1e-12`인 열도 fold별로 제외하며 중복·상수 열 목록을 함께 저장한다.

## 비교와 보고

기준은 저장 pair jockey-ID 후보 438/1,779다. 신규 단일 묶음 후보만 이 기준의 60열 위에 더해 H1에서 함께 다시 적합한다. 점수 생성과 원천 입력·baseline 비교값은 고정한다. 기존 ID 연구와 같은 확률 목표, 평가경주·배당 없는 구성, positive-slope H2 Platt 절차를 쓴다. 후보 하나로 fold당 H1 fit 1회와 H2 Platt fit 1회, 총 3+3회만 수행한다. H1은 0 초기값·race-equal unordered-pair BCE·`logit(p0)` offset·intercept 없음·`lambda=1` ridge의 L-BFGS-B를 쓴다(`maxiter=500`, `ftol=1e-12`, `gtol=1e-8`, gradient infinity norm `<=1e-6`). H2는 초기값 `(A,B)=(0,1)`, `A∈[-20,20]`, `B∈[0.05,20]`, 동일 L-BFGS-B 허용오차와 projected gradient `<=1e-6`을 쓴다. 실패시 재시도·추가 fit·tuning 없이 중단한다. pair logit 동률 선택은 기존처럼 정렬 마번 pair 중 사전식 최소를 고른다.

보고에는 전체, 실제 직전 기수 유지/변경, 첫 관측 조합/재기승 관측, 거리·연도별 결과를 포함한다. 하위군의 분모는 새 후보가 선택한 pair의 상태가 아니라 저장 baseline ID 선택 pair의 상태로 고정한다. 유지/변경 말 수(0/1/2), 첫 관측 조합 수(0/1/2), 미상 수별 비교를 분리한다. baseline에서 선택이 바뀐 경주의 새 후보 승·기준 손실·동률을 분리하고 269개 경주일·기존 seed·2,000회 paired bootstrap CI를 그대로 사용한다. 전체 unordered pair 확률 손실과 기준 선택쌍에 고정한 Brier/log loss, calibration 및 coverage를 모두 보고한다. 별도의 Top3 순위 모델은 만들지 않는다. 이번 설계는 말별 Top3 목표를 바꾸지 않는다.

결정 gate도 결과 확인 전에 고정한다. (1) 새 후보 선택쌍 적중률에서 저장 ID 후보의 438/1,779를 뺀 점추정치가 양수이고 paired date CI 하한도 0보다 커야 선택 개선 PASS다. (2) 저장 ID 후보가 선택한 동일 pair에 새 확률을 적용한 Brier와 log loss 차이(candidate−ID)가 모두 `<=0`이고, 둘 중 적어도 하나의 paired date 95% CI 상한이 0 미만이어야 fixed-pair 확률 개선 PASS다. (3) 모든 pair의 경주균등 Brier와 log loss 차이가 각각 `<=0`이어야 all-pair guard PASS다. composite 개선은 세 조건이 모두 PASS일 때만 표시하고, 그 외에는 미확정/미채택 연구 후보로 둔다. raw F1_STYLE6 Top2 429/1,779 비교는 보조표로 별도 보고하며 composite gate에는 넣지 않는다.

독립 prefit 검토 후 승인된 파일 해시에 묶인 단일 arm만 fit한다. 재현 입력 해시·행 키·fold/source lineage·독립 계산 산출물을 새 폴더에 저장하고 기존 자료는 덮어쓰지 않는다.
