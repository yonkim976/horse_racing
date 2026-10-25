# F1_STYLE6 Top5 head의 적중·누락 조건 후향 진단

상태: **계획 잠금·원천 감사·조건 집계·선택 에너지 분해 완료.** 기존 F1_STYLE6 점수, Top5 직접 학습 head, 운영 등록부, DB를 수정하거나 다시 학습하지 않았다.

## 질문과 요약

기존 raw-score Top5와 고정된 additive head의 결과가 다른 primary 66경주(새 head만 맞힌 31, 기존 Top5만 맞힌 35)는 어떤 사전 조건과 말 교체에서 나왔는지 살폈다. 조건별 분모는 66경주가 아니라 primary 전체 1,503경주다. 66경주는 결과를 보고 정해진 집합이므로 이를 별도 발견 표본으로 삼거나 조건별 운영 규칙을 만들지 않는다.

| Primary 결과 | 경주 | 설명 |
|---|---:|---|
| 양쪽 모두 실제 Top3 3두 포함 | 404 | 선택이 같거나 달라도 양쪽 hit |
| head만 포함 (`caught`) | 31 | head가 actual Top3를 모두 담고 baseline은 하나 이상 누락 |
| baseline만 포함 (`lost`) | 35 | baseline은 모두 담고 head는 하나 이상 누락 |
| 양쪽 모두 1두 이상 누락 | 1,033 | 두 선택 모두 all-three miss |
| 합계 | 1,503 | 900/1000/1110/1200m, 2024-01-05~2026-09-19 |

전체거리 1,779경주는 보조 모집단이다. **전체 1,779경주**의 결과는 38 caught, 37 lost, 482 both-hit, 1,222 both-miss다. 그중 **선택이 바뀐 304경주**만 보면 38 caught, 37 lost, 53 both-hit, 176 both-miss다. 둘은 분모가 다른 별도 요약이며 primary 결과와 합치지 않았다. 2026년은 9월 19일까지의 부분연도다.

Primary에서 baseline은 439/1,503 (29.208%), head는 435/1,503 (28.942%)를 맞혔다. 차이는 **−0.266%p**이고 고정 날짜-cluster bootstrap 95% 구간은 **[−1.343, +0.775]%p**다. head는 baseline과 254경주에서 다른 5두를 골랐다. 이 반복 사용 역사자료에서 우위 신호가 확인되지 않았다.

## 어떤 조건에서 달랐나

가장 뚜렷한 선택 조건은 baseline 점수 5위와 6위의 간격이었다. 이 간격을 경주 안 점수 표준편차(ddof=0)로 나눈 사전 고정 구간으로 보면, head 변경의 177/254가 `z gap ≤0.10`에서 나왔다. 그 구간은 430경주 전체에서 23 caught, 27 lost로 순차이 **−0.93%p** (날짜 bootstrap 95% CI **[−4.35, +2.38]%p**)였다. 중간 구간 `(0.10,0.25]`은 450경주 중 7/8, **−0.22%p** (CI **[−1.77, +1.33]**)였다. `>0.25`에서는 623경주 중 선택이 바뀐 사례가 3건뿐(1 caught, 0 lost)이어서 **+0.16%p**를 일반화할 수 없다 (CI **[0.00, +0.50]**).

나머지 주요 고정 조건에서도 차이는 작고 날짜별 불확실성이 컸다.

| 조건 | 전체 경주 | 변경 | caught/lost | 순차이, %p (95% 날짜 CI) |
|---|---:|---:|---:|---:|
| 2024 | 499 | 106 | 11/18 | −1.40 [−3.54, +0.66] |
| 2025 | 559 | 92 | 11/8 | +0.54 [−0.72, +1.84] |
| 2026-09-19까지 | 445 | 56 | 9/9 | 0.00 [−2.27, +1.90] |
| 900m | 251 | 34 | 2/8 | −2.39 [−5.02, 0.00] |
| 1000m | 508 | 90 | 12/13 | −0.20 [−2.05, +1.75] |
| 1110m | 482 | 94 | 14/8 | +1.24 [−0.64, +3.05] |
| 1200m | 262 | 36 | 3/6 | −1.15 [−3.46, +1.13] |

등급·출전수, 경력, 같은 거리 기록 수, 직전 출전 간격 및 style-support 표도 각 셀의 전체 경주, 변경, caught/lost, 양쪽 hit/miss, head와 baseline 적중률 및 순차이를 모두 포함한다. 날짜 재표집 2,000회에서 조건 셀의 경주 수가 0이 되는 반복이 있으면 해당 CI는 정의되지 않는 것으로 표시했다. 65개 조건 셀의 날짜 CI를 살펴보면 **유리한 방향의 95% CI 하한이 0보다 큰 셀은 없었다.** 다만 불리한 방향의 CI가 0을 넘지 않은 두 style-support 셀이 있다. `hist_s1f_relpos_n=4`는 110경주에서 0 caught/4 lost, −3.64%p (CI [−7.34, −0.85])이고, `hist_s1f_to_c4_pair_n=4`는 116경주에서 같은 0/4, −3.45%p (CI [−6.92, −0.81])였다. 두 셀의 lost 사례는 **같은 4경주**라 서로 독립된 반복 신호가 아니다. 이 exact-support 비교는 다중 사후 검토 중 발견된 것이므로 불리한 조건 규칙으로도 채택하지 않는다. 다른 소표본 셀 역시 표기만 하고 셀 선택이나 유의성 탐색에 사용하지 않았다.

Primary 1,503경주의 실제 출전수는 7두 32경주, 8두 64, 9두 92, 10두 1,315다. 12두는 primary에 없고 전체거리 보조 모집단의 2경주에서만 나타난다.

## 실제 5두 교체에서 본 차이

선택 변경 254 primary 경주를 결과 구성별로 나누면 caught 31, lost 35, 양쪽 hit 45, 양쪽 miss 143이다. caught 31건 중 30건과 lost 35건 전부가 1두 교체였다. 이 66건에서는 추가말이 실제 Top3였는지가 결과를 설명한다. caught에서 새로 넣은 Top3 말은 31두 합계, 제거말 중 Top3는 0두였다. lost에서는 추가말 중 Top3가 0두, 제거말 중 Top3가 35두였다. 두 결과군의 추가·제거말 사전 프로필은 비슷했다.

아래 추가·제거 프로필 수치는 **runner-weighted 평균**이다. caught는 31경주에서 32 added/32 removed 말(한 경주에서 2두 교체), lost는 35경주에서 35/35두다. 변수별 결측 때문에 유효 말 수가 달라진다. 말별 관측 수와 경주별 added-minus-removed race-equal 차이는 `CHANGED_RUNNER_LEDGER.csv`와 `CHANGED_RUNNER_CONTRASTS.csv`에서 확인한다.

| 바뀐 말의 사전 평균 | caught: 추가 / 제거 | lost: 추가 / 제거 |
|---|---:|---:|
| baseline raw-score 순위 | 6.31 / 4.75 | 6.09 / 4.49 |
| 관측 출전수 | 21.6 / 44.1 | 18.6 / 39.7 |
| 동일 거리 유효시간 수 | 6.16 / 17.94 | 5.14 / 15.49 |
| 최근 5회 유효시간 수 | 3.25 / 4.84 | 2.91 / 4.60 |
| 최근 평균 순위 비율 (`mean5_rank_fraction`) | 0.740 / 0.276 | 0.724 / 0.245 |
| 초반 상대 위치 (`hist_s1f_relpos_mean5`) | 0.392 / 0.636 | 0.408 / 0.558 |

두 결과군 모두 제거말은 더 많이 출전했고 최근 유효 기록도 많았다. 새로 넣은 말의 `mean5_rank_fraction`은 더 높았고, 이 값은 과거 비교 집단 안에서 **높을수록 최근 평균기록의 상대 순위가 느린 쪽**이다. 반면 초반 상대 위치 값은 더 낮았으며 **낮을수록 과거 S1F에서 상대적으로 앞선 위치**를 뜻한다. 이러한 프로필 차이는 caught와 lost에 공통으로 나타나 31건과 35건의 결과를 나누는 사전 분기 조건으로 보이지 않았다. 말 지표는 유효 관측 수가 다른 표본 평균이므로 서로 독립 효과로 해석하지 않는다.

시간 피처는 거리별로 나눠 저장했다. `last_time_s`는 같은 거리의 직전 실제 slot 값이며 그 값이 무효이면 NULL로 남고 마지막 유효 기록으로 대체하지 않는다. `best5_s`는 유효 기록의 최소 초, `fast2mean5_s`는 빠른 유효 기록 두 개 평균, `std5_s`는 유효 기록이 3개 이상일 때의 표본 표준편차다. `trend_s`는 최근 3 slot 평균 초에서 그 이전 3 slot 평균 초를 뺀 값이며 양쪽 구간 모두 유효 기록이 2개 이상이어야 계산된다. 요약표에는 거리·결과별 비결측 수, 최근 3·5회와 이전 3회의 support 분포를 함께 뒀다. 시간 초를 서로 다른 거리 사이에서 평균하지 않았다.

Style 입력은 현 경주의 위치나 속도를 뜻하지 않는다. `hist_s1f_relpos_mean5`는 과거 기록의 정규화 상대위치 평균이고 낮을수록 앞선 위치다. S1F→4C 및 4C→G1F 전이값은 앞 지점 상대위치에서 뒤 지점 상대위치를 뺀 값이며 양수는 상대적으로 앞으로 이동한 기록이다. 각 평균은 해당 support count와 함께 해석한다.

### 누락이 생긴 방식

변경된 primary 양쪽-miss 143경주 중 129경주는 실제 Top3 말 하나 이상이 baseline Top5와 head Top5 **둘 다의 합집합 밖**에 있었다. 이 129경주에서 선택 두 개의 합집합이 놓친 실제 Top3 말은 155두다. 나머지 14경주는 actual Top3가 두 선택의 합집합 안에는 있었지만 어느 한 5두 집합도 세 마리를 모두 담지 못했다. 이 둘은 후보 표현/순위 부족과 집합 선택 구성의 서로 다른 실패 경로다.

양쪽 hit 45경주에서는 추가말과 제거말이 실제 Top3에 하나도 속하지 않았고 세 Top3는 5두 선택의 교집합에 남았다. 즉 선택이 바뀌어도 all-three 결과가 달라지지 않았다. 이 결과는 추가말이 적중을 만든 원인이라는 뜻이 아니다.

## 선택 에너지의 정확한 분해

모든 변경 경주 304건의 선택 에너지 차이를 재구성했다. 여기서 `baseline_energy` 필드는 raw-score z prior 합만 뜻한다. baseline 선택의 전체 head 에너지로 잘못 사용하지 않았고, 저장된 head JSON의 연도별 표준화 기준과 11개 계수로 `E_head(Snew) − E_head(Bold)`를 다시 계산했다. 선택 영수증의 신집합 에너지와 일치했고 분해 잔차는 수치 오차 수준이었다.

| Primary changed 결과 | prior Δ | 경력 | 동일거리 경험 | 순위 | style 평균 | style support | head 전체 Δ |
|---|---:|---:|---:|---:|---:|---:|---:|
| 전체 254 변경 | −0.1031 | +0.0253 | +0.0294 | +0.1007 | +0.0306 | +0.0246 | +0.1075 |
| caught 31 | −0.1234 | +0.0332 | +0.0392 | +0.1041 | +0.0343 | +0.0283 | +0.1157 |
| lost 35 | −0.0830 | +0.0326 | +0.0350 | +0.0922 | +0.0218 | +0.0310 | +0.1296 |

각 셀은 변경 경주마다 같은 가중치를 주어 계산한 평균 에너지 기여다. Prior는 대체로 새 선택에 불리한 방향이었고 11개 입력의 더해진 기여가 이를 상쇄했다. caught와 lost의 묶음 기여가 비슷하므로 이 분해는 적중원인이나 피처의 독립 중요도 증거가 아니다. `same_starts`와 `same_valid_times`, style support log-count 사이 상관이 매우 높고, 개별 계수·기여의 인과 해석은 하지 않는다.

## 다음 실험 방향

1. 변경 결과를 우선 후보집합 실패와 집합 구성 실패로 나눠 고정한다. 이번 143 both-miss 변경 경주에서 129건은 actual Top3가 두 기존 선택의 합집합 밖에 있었고 14건은 합집합 안에 있었지만 5두 조합이 달랐다. 다음 검토는 이 실패 유형을 기준으로 runner ranking과 set objective 중 어디를 개선할지 별도 설계한다.
2. 현재 head는 말별 효용을 단순 합산하는 additivity 구조라 말 사이 보완·중복을 직접 표현하지 않는다. 관계항이나 pair/set-level 표현은 자료에서 확인된 원인으로 단정하지 않고 사전 고정한 비교가설로만 제안한다.
3. 31/35에서 추가말 프로필은 서로 비슷하고 점수차가 작은 경주에서 변경이 집중됐지만 해당 층의 CI는 0을 넓게 포함했다. 다음 모델 선택이나 조건 규칙은 새로운 미사용 경주일로 만든 전향 holdout과 성공 기준을 먼저 잠근 뒤 평가한다. 이번 표본으로 조건별 rule을 채택하지 않는다.

## 원천과 보관

핵심 source path와 SHA는 [SOURCE_AUDIT.json](outputs/SOURCE_AUDIT.json), 선택 영수증·모델·출력 SHA와 크기는 [ANALYSIS_RECEIPT.json](outputs/ANALYSIS_RECEIPT.json)에 기록했다. 원천 parquet, 데이터베이스, 전체 출전 roster, 학습 행렬, 후보 5-set 표는 복사하지 않았다.

기존 `20261025_top5_direct_learning_v1/FINAL_MANIFEST.json`의 baseline source SHA 한 필드에는 오타가 보존되어 있다. 실제 baseline parquet SHA는 `c3fc8a2bf10d3fa1678ab3c5463209089021f51f6d0bf500fc2db6006fda13c1`이며 기존 selection code의 `BASELINE_SHA256` 및 root source audit가 지정한 해시와 일치한다. `CHOICES_RECEIPT.json` 자체에는 baseline SHA가 직접 기록되어 있지 않다. 기존 manifest는 수정하지 않았고, 새 rootreview의 [source metadata correction receipt](../20261025_top5_direct_gain_loss_rootreview_v1/SOURCE_HASH_METADATA_CORRECTION.json)에 정정 근거를 보존했다.

### 파일 길잡이

- [PLAN_LOCK.md](PLAN_LOCK.md): 사전 고정 모집단, 변수·bin, 분모 및 교차표 한도.
- [analyze_gain_loss.py](analyze_gain_loss.py): source hash 확인, 분리 label read, audit, conditions, runner ledger 및 energy 재구성 코드.
- [PRIMARY_RACE_LEDGER.csv](outputs/PRIMARY_RACE_LEDGER.csv): primary 1,503경주와 raw Top5 5위 경계말 사전 입력·결과.
- [PRIMARY_CONDITION_SUMMARIES.csv](outputs/PRIMARY_CONDITION_SUMMARIES.csv): 각 조건 내 전체 경주 분모와 결과 건수·날짜 CI.
- [GAP_CONTINUOUS_SUMMARY.csv](outputs/GAP_CONTINUOUS_SUMMARY.csv), [BOUNDARY_FORM_STYLE_SUMMARY.csv](outputs/BOUNDARY_FORM_STYLE_SUMMARY.csv): 점수 간격 연속 통계와 primary 경계말의 거리별 form/style 요약·support.
- [CHANGED_RACE_LEDGER.csv](outputs/CHANGED_RACE_LEDGER.csv), [CHANGED_RUNNER_LEDGER.csv](outputs/CHANGED_RUNNER_LEDGER.csv), [CHANGED_RUNNER_CONTRASTS.csv](outputs/CHANGED_RUNNER_CONTRASTS.csv): 전체거리 변경 304건의 primary/secondary 표시, added/removed 실제 Top3 및 교체 비교. 여러 말 교체에서는 경주 내 집합 평균만 비교하고 임의 말짝을 만들지 않았다.
- [ENERGY_DECOMPOSITION.csv](outputs/ENERGY_DECOMPOSITION.csv), [ENERGY_DECOMPOSITION_SUMMARY.csv](outputs/ENERGY_DECOMPOSITION_SUMMARY.csv): 전체거리 변경 304건의 exact head Δ 기여 분해와 primary/secondary 요약.
