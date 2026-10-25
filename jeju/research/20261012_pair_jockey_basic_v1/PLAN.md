# F1_STYLE6 두 말 동시 Top3 pair에 기수 기본정보를 더하는 단일 arm

상태: source audit 완료, 사전 설계 승인 대기. 이 문서는 후보 결과를 확인하기 전에 만든다. 새 fit·evaluation prediction·candidate outcome metric은 root의 구체적인 승인 전까지 생성하지 않는다.

## 질문과 고정 범위

현재 제주 F1_STYLE6 말 평가·점수와 2026-10-11 최신 expanded direct-pair 결과를 고정하고, 기수의 기본 이력 한 항목이 한 경주에서 두 말 모두 Top3에 들 pair를 고르는 데 추가 정보를 주는지 비교한다. F1_STYLE6 말 점수, 평가 cohort, 기존 직접 pair coefficients와 결과는 다시 적합하거나 수정하지 않는다. 새 입력은 pair-selection 단계에만 붙인다.

선행 자료원 및 공식-ID coverage는 [SOURCE_AUDIT.md](SOURCE_AUDIT.md)에 기록했다. 제외 말 `3005648`, 400m, 정상 완주하지 못한 경주, 경주 상한 2026-09-19는 기존 pair cohort와 동일하게 유지한다. 2026년은 부분연도다. 새 입력 원천은 기존 공식 출전 ID에 연결한 기수 기본 이력뿐이다. 마방, 기수 교체, 거리·각질 전문성, 말×기수 상호작용, 새로운 loss, hyperparameter 탐색은 포함하지 않는다.

## 후보 입력 하나

대상 출전의 event ID `api_record_id`에서 사건 당시 공식 기수 ID를 연결한다. 기수 ID는 과거 출전을 묶는 범주형 key로만 쓰고, 숫자 크기나 one-hot 기수 계수로 pair model에 직접 넣지 않는다. 이름은 입력·join에서 쓰지 않는다.

말 `h`의 대상 경주일을 `T`라 하고 cutoff를 달력 날짜 `C=T−2일`로 둔다. 같은 공식 기수 `r`의 최근 기록은 cutoff 기준 아래 구간에 있는 eligible start들로만 계산한다.

```text
history(r,T) = {past event e: jockey_id(e)=r, C−365일 < race_date(e) <= C}
n_r(T)       = count(history)
s_r(T)       = count(finish_position(e) <= 3)
e_r(T)       = sum(3 / field_n(e))
d_r(T)       = (s_r(T) - e_r(T)) / (n_r(T) + 20)
```

`3/field_n`은 해당 과거 편성 크기의 중립 Top3 기대 비율이며 20은 결과를 본 뒤 조정하지 않는 고정 shrinkage pseudo-start 수다. `n=0`이면 `d=0`으로 중립 처리한다. `n`은 분모와 source-support 진단에만 쓰며 별도 model input으로 추가하지 않는다. `d`는 최근의 **과거 관측 편성 대비 Top3 빈도 지표**다. 기수 능력·인과 효과를 뜻하지 않는다. 거리·마방별 분해나 장기 기수 효과는 만들지 않는다.

각 무순서 pair `(i,j)`에 추가할 유일한 basis 값은 `x_jockey(i,j)=d_{r_i}(T)+d_{r_j}(T)`다. 합은 대칭이므로 마번 순서가 바뀌어도 같다. H1 내 매 출전의 `d`는 그 출전의 T−2 이전 결과만 사용하므로 같은 경주 label은 해당 경주의 feature에 들어오지 않는다. H1 과거 결과가 이후 경주의 rolling history에 들어가는 것은 당시 가용 자료를 모사하는 시간순 누적이다. `n=0`은 과거 eligible history 미관측을 뜻하며 실제 무능력·미입상을 뜻하지 않는다.

H1에서만 이 scalar pair basis의 표준화와 계수 `gamma`를 학습한다. 기존 direct model의 정확한 unordered Top3 pair label, 경주 균등 Bernoulli log loss, `lambda=1`, intercept 없음, pair enumeration·exact tie rule을 그대로 쓴다. 기존 20개 대칭 style basis는 그대로 유지하고 이 scalar 한 열만 21번째 basis로 붙인다. 첫 20개 입력의 H1 표준화 moments는 최신 expanded direct model의 저장 moments와 그대로 같게 고정한다. candidate는 저장 baseline을 덮어쓰지 않고, candidate fit 안에서만 기존 20개 계수와 새 `gamma`를 함께 재적합한다. Pair logit은 다음과 같다.

```text
eta_ij = logit(p0_ij) + z_style20(i,j) · beta + z_jockey(i,j) * gamma
```

이것은 rider-ID별 H1 categorical effect 모형이 아니다. 전체기간 기수 고정효과, 기존 기수 연구의 계수 복사, rider score를 F1_STYLE6 말 점수에 더하기도 하지 않는다. 새 feature의 표준화 평균·척도만 H1에서 적합한다.

## Cohort·fit·calibration budget

고정된 expanded split을 상속한다. H1은 2024/2025/2026 평가 fold에서 각각 2,147/2,818/3,458경주이고, H2는 336/311/325경주이며, evaluation은 637/654/488경주다. H1 source는 2019년부터 평가 fold 직전년 기존 Jan–Jun 구간까지이며, H1 마지막 경주일은 첫 H2 경주일보다 최소 2일 앞선다. H2는 기존 후속연도 7–12월, evaluation roster·label은 2024-01-05~2026-09-19 범위다. Split key·score provider fold/role·race ID의 유일성은 기존 source-lock 규칙을 따른다.

Root가 승인하면 단일 candidate arm만 적합한다.

- H1 pair model: 평가 fold마다 한 번, 총 3회. 역사 F1_STYLE6 refit, 기존 saved H1 model 재학습, baseline pair model refit은 0회.
- H2 candidate probability calibration: 평가 fold마다 candidate positive-slope Platt map 1개, 총 3회. 기존 latest direct model과 기타 baseline의 저장 calibration map은 read-only로 재사용한다. 별도 baseline calibration fit은 0회. H2의 map은 pair 순위를 바꾸지 않는다.
- Evaluation: 고정 1,779경주·76,848 unordered pair를 한 차례 예측한다. 별도 bootstrap schedule은 생성하지 않는다.

예산 상한은 3 H1 + 6 H2 fit이며 이 계획은 3 H1 + 3 candidate H2 fit만 사용한다. 기존 optimizer의 tolerance·convergence gate·support weighting을 바꾸거나 fit에 맞춰 수정하지 않는다. root 승인 후 입력 key, T−2, pair labels, H1/H2 counts, H1-only standardization, H2 calibration 범위와 code hash를 source lock/approval에 고정한다. 승인 후 optimizer 실패가 나도 재시도·추가 fit은 하지 않고 해당 run을 중단한다.

## 사전 고정 평가

주된 feature-effect 비교는 candidate pair selection minus `latest expanded direct pair`의 427/1,779다. 기존 2026-10-11 날짜 bootstrap schedule 2,000 draw와 paired date resampling을 그대로 사용한다. feature-effect 성공은 점추정치 양수와 95% CI 하한 양수를 요구한다. 추가로 이전 연구의 raw F1_STYLE6 score Top2 429/1,779 improvement gate를 유지한다. 원시 Top2 대비 candidate 차이도 점추정치와 같은 paired CI로 보고하며, 두 기준이 함께 충족될 때만 pair-selection 개선 gate 통과로 표시한다.

다른 고정 comparator도 출처의 저장값으로 보고한다: 이전 direct 426, saved F1_STYLE6 P(Top3) Top2 429, existing joint marginal Top2 434, existing candidate maximum joint pair 422, matched maximum joint pair 429. 이 비교를 위해 base candidate coefficients를 재현·재학습하지 않는다. 동점, 한 경주 한 쌍 선택, `math.fsum`, 평가 pair set은 기준 연구와 동일하다.

승식 수익·시장 배당 해석은 하지 않는다. 결과에는 고정 pair-hit과 year/date별 paired CI 외에 all-pair 및 selected-pair Brier/log loss, 기존 고정 확률 구간의 coverage와 적중률, 연도별 결과, pair 합계의 확률 일관성 진단, 서로 다른 선택 pair에서의 newly right/wrong/tied 결과를 보존한다. 이 지표를 본 뒤 cutoff·입력·계수·gate를 바꾸지 않는다. 이 기간은 반복 개발 자료이며 독립 미래 holdout이 아니다.

## 산출 순서

1. source preflight와 독립 검토에서 공식 ID join·해시·T−2·rolling support·split/label·선택 cohort를 확인한다. 결과 label 요약 또는 candidate 성과 지표는 내지 않는다.
2. root가 구체적으로 승인한 뒤 한 번의 3 H1 fit과 3 H2 candidate map fit을 수행하고, 각 단계 artifact hash·optimizer 상태·source lineage를 기록한다.
3. 고정 평가 pair prediction을 생성하고, 기존 date bootstrap schedule 및 frozen comparator로 한 번 평가한다. 재실행/추가 arm 없이 결과·제한·실패 사유를 저장한다.
4. README·artifact manifest와 독립 재현 검토를 완성한다. `RESEARCH_PUBLICATION_POLICY.md`에 따라 중앙 결론 문서/등록부 갱신은 전체 결과와 review가 준비된 뒤 root가 별도 발행 판단을 한다. 운영 모델·DB·공통 resolver는 변경하지 않는다.
