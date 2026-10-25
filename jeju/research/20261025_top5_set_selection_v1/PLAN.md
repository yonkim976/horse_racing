# 추천 5두를 정확 Top3 집합 확률로 선택하는 단일 비교

상태: **사전 계획.** `SOURCE_AUDIT.md`의 고정된 원천과 모집단으로, 기존 F1_STYLE6 점수와 동결된 pair-interaction joint 분포의 추천 5두를 비교한다. 모델 적합·새 점수 생성은 없다. 이 문서는 선택 구현과 결과 계산 전에 root가 검토한다.

## 질문과 해석

동결된 F1_STYLE6 runner score를 유지하면서, 경주당 정확히 5두를 고를 때 joint Top3 분포의 포함확률을 최대화하는 선택이 점수 상위 5두보다 실제 상위 3두 전원을 더 자주 포함하는가?

평가치는 후보 집합의 실제 포함률 차이다. `20261010_joint_relationship_v1`의 기존 6-ticket hit/NLL gate 실패는 그대로 보존한다. 5두는 다른 의사결정 수와 사건이므로 저장된 관계 분포를 쓰는 단일 후향 재평가로 기록한다. 같은 2024–2026 경주와 결과를 이미 여러 연구에서 보았으므로 결과는 반복 사용된 역사적 개발 비교이며 독립 미래 홀드아웃이 아니다. 지표를 확인한 뒤 선택 규칙·표본·경계·계수를 바꾸지 않는다.

## 고정 후보와 비교군

**비교군:** `baseline_runner_predictions.parquet`의 저장 `F1_STYLE6` `score`를 race 안에서 내림차순으로 정렬하고 같은 점수는 `horse_number` 오름차순으로 풀어 첫 다섯 `horse_id`를 고른다. `horse_id`는 결과 원장에 저장하고 모든 분포 키는 마번(`horse_number`)을 사용한다.

**유일한 후보:** 기존 `20261010_joint_relationship_v1` candidate arm의 전체 unordered exact-Top3 `probability` 분포를 그대로 쓴다. fold별 이미 저장된 H1 관계계수·runner scaler·pair RMS·H2 온도를 재사용한다. 기존 `matched_baseline` arm은 후보가 아니다. 관계 계수 재학습, 새 보정, F1_STYLE6 재학습, 점수·확률 혼합, odds/favorite gating은 없다.

## 정확한 집합 선택식

경주 `r`의 각 정확한 무순서 Top3 말 집합 `T`에 대해 저장 후보확률을 `P_r(T)`라 둔다. 정확히 5두인 집합 `S`의 효용은

\[
q_r(S)=\sum_{T\subseteq S,\ |T|=3}P_r(T)
       =\Pr_{P_r}(\text{실제 Top3 집합이 }S\text{에 포함됨}).
\]

candidate 선택은 `|S|=5`인 모든 조합 중 `q_r(S)`가 가장 큰 조합이다. 현재 편성 범위는 N=7–12라 경주당 최대 `C(12,5)=792`개 조합만 계산한다. 기존 약 10 MB parquet는 필요한 열만 일시적으로 메모리에 읽고, 경주별 probability map과 최대 792개 q 후보를 계산 중 메모리에 둔다. 전체 5두 조합 원장은 영구 저장하지 않는다. 각 `S`에서 합산하는 Top3 조합은 정확히 10개다. 확률은 저장된 full-field 분포에서 읽고 선택된 10개 티켓 안에서 다시 정규화하지 않는다.

선택 전 구조검사는 candidate 행이 각 경주에 정확히 `C(N,3)`개 있고, 각 unordered triple이 한 번만 나오고, horse-number triple이 동일 race roster에 속하고, 모든 확률이 유한·비음수가 되며, race별 전체 질량이 1과 절대오차 `1e-10` 이내인지 확인한다. root가 독립 복원한 `Q` 및 파라미터로 이 확률 파일을 출처까지 재구성해 일치 여부를 검토한다.

동률 처리는 선택 규칙의 일부다. horse number를 오름차순으로 정렬한 5-tuple에 대해 각 q를 binary64 순서 고정 `math.fsum`으로 계산한다. 먼저 `q_max`를 찾고, `q_max - 1e-12` 이내인 집합들을 수치상 동률로 취급한다. 그 후보들 중 기존 score Top5와 겹치는 마리 수가 가장 많은 집합을 고르고, 그 다음 horse-number tuple 사전식 오름차순으로 고른다. 선택 결과의 `q_max - q_selected`도 저장하고 반드시 `≤1e-12`인지 검증한다. baseline 동점은 raw score 값이 완전히 같을 때 마번 오름차순이다. 모든 race에서 선택 수는 정확히 5, ID는 고유하다고 검증한다.

같은 선택 함수를 기존 관계 연구의 `matched_baseline` unary additive distribution에도 적용하는 사전 negative control을 둔다. 전체 1,779경주에서 그 분포의 q-max top5가 저장 raw-score Top5와 모두 같아야 한다. 이 비교는 결과 label을 읽지 않으며 candidate 관계 선택 결과로 취급하지 않는다. 하나라도 다르면 계산을 중단하고 원인을 검토한다.

## 코호트와 결과 계약

- Primary: 거리 900/1000/1110/1200m, 1,503경주.
- Secondary: 같은 완전 roster의 전체 1,779경주(2024-01-05~2026-09-19, 269일; 2026년은 부분 연도).
- Roster, 선택, 계수, 확률, bootstrap 일정은 두 비교군에서 동일하다. 배당·인기순위로 제한하지 않는다. 제외 말 3005648은 결과·원천에 없다.
- Baseline와 candidate 선택 artifact가 저장되고 SHA-256이 기록되기 전까지 결과 label을 읽지 않는다. 결과 계산기는 저장된 선택 원장을 다시 읽어 hash를 확인한 후에만 baseline `y` label을 연다. race별 정답은 `y=1`인 정확히 3개의 `horse_id`로 만들고 세 개가 아니면 fail closed 한다.

Primary event는 실제 Top3의 세 horse ID가 선택된 다섯 ID 안에 모두 들어오는 것이다. 최소 한 두 포함과 혼동하지 않는다. 다음 지표를 race 단위로 두 arm에 대해 보고한다.

- Primary 및 full-cohort all-three hit rate, paired 차이, baseline-only hit, candidate-only hit, 둘 다 hit, 둘 다 miss.
- 선택 집합 변경 경주 수, 다섯 중 교집합 크기의 분포와 평균, 두 arm의 exact miss count(실제 Top3 중 선택되지 않은 말 0/1/2/3두)와 평균 captured 수.
- 연도별, 거리별, 경력 strata별 hit rate와 분모. 연도·거리·경력 결과는 사전 지정 기술값이며 primary gate를 대체하지 않는다.
- 각 선택 집합의 별도 joint-utility 값 `q_r(S)`: candidate 분포에서 baseline top5가 가지는 q와 candidate top5가 가지는 q. 이 예측 효용을 실제 hit 결과와 별도 열·별도 표로 표시한다.

경력 strata는 사전 가용 입력 `observed_starts`로만 만든다. 각 경주 roster의 중앙값을 계산하고, primary 모집단의 label-free 중앙값 분포에서 얻은 1/3·2/3 선형 보간 경계 13.5와 26.5를 고정한다: `≤13.5`, `(13.5, 26.5]`, `>26.5`. 동일 경계로 전체 경주도 보고한다. 주 결과를 본 뒤 경계를 바꾸지 않는다.

## 신뢰구간과 성공 판정

Primary candidate-minus-baseline hit-rate 차이에는 고정된 269-day `date_bootstrap_schedule.npy`를 그대로 사용한다(SHA-256 `d141b0c3f9a463cbfc9d1f4c61228b58757c31aee4ec74b79f41c5baeadaccbd`, 2,000회·날짜당 269 draw; 새 표본 일정 생성 금지). 각 replicate는 뽑힌 날짜의 해당 primary 경주를 모두 포함하고 경주 수로 가중한 차이를 낸다. Primary에는 모든 269 날짜에 경주가 있으므로 일정의 전체 날짜를 그대로 사용한다.

사전 성공 조건은 **primary hit-rate 점추정 차이 `>0`이고 paired date-bootstrap 95% CI 하한도 `>0`**인 경우다. 각 replicate의 paired race-equal 평균을 만든 뒤 `numpy.quantile`의 `method="linear"`로 0.025·0.975 분위수를 구한다. 어느 하나라도 아니면 성공 신호를 주장하지 않는다. 이는 이미 반복 검토된 자료에 대한 후향 연구 신호일 뿐, 독립 검증이나 운영 승격이 아니다.

## 단계 분리와 보존

1. Root가 이 계획, 저장 계수·온도·scaler와 source lock을 확인하고 candidate Q를 독립 재구성한다. 독립 검산 영수증은 성공, label-free, 새 적합 0회, 두 arm 최대 Q 차이 `≤1e-12` 및 같은 source hash chain을 충족해야 한다. 승인 전에는 선택 집합이나 label 기반 성과를 계산하지 않는다.
2. Root의 구체 설계·코드 검토 뒤, main selector의 source-only preflight와 선택 단계는 baseline `score`, ID/horse number, race metadata 및 label-free 경력 strata용 `observed_starts`만 읽고, joint 파일에서는 `race_id, distance_m, evaluation_year, arm, triple_numbers, probability`만 읽는다. 결과 label·`is_true_set`·odds·favorite는 선택 코드에서 사용하지 않는다. 선택 artifact SHA가 receipt에 잠기기 전까지 outcome 집계는 실행하지 않는다.
3. 선택 단계가 race마다 두 집합, 두 q 값, 필요한 race metadata를 새 selector artifact에 저장하고 자체 hash를 기록한다. 모든 5개 horse ID와 tie 규칙을 검증한다.
4. 별도 report 단계만 정답 label을 읽고 지표와 고정 bootstrap을 계산한다. 모든 출력·manifest는 이 연구 디렉터리에 새로 만들고 재실행으로 덮어쓰지 않는다.

영구 산출물은 source path/hash, 계수·온도 metadata 참조, 1,779행 이하의 선택·race comparison ledger, 요약 지표, receipt/manifest만 둔다. all-triples 후보, feature parquet, baseline parquet, bootstrap NPY의 사본과 전체 5집합/순열 원장은 만들지 않는다. 예상 신규 산출물은 20 MB 이하이며 팀 신규 영구저장 상한 300 MB 안에 둔다. DB, 원천 수집, 모델 registry, 운영 파일 변경은 범위 밖이다.

## 검토자 열람 범위 공개

검토자의 앞선 schema 확인 과정에서 일부 `y`/`logloss` 값이 있는 parquet를 `read_parquet(...).head(3)`로 열람했으며, 그 값은 선택·비교 규칙 결정에 사용하지 않았다. 이 연구에서 label-free라고 하는 보장은 main selector가 명시적 열 allowlist로 결과 열을 읽지 않는다는 뜻이다. 별도 outcome report는 선택 원장의 SHA-256을 확인한 뒤에만 정답 label을 읽는다. 따라서 팀 전체가 어떤 단계에서도 label을 열지 않았다고 주장하지 않는다.
