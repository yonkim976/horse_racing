# 고정 말점수 기반 공동입상 관계모형 사전 감사

검토일: 2026-10-10. 상태: 읽기 전용 설계·누출 감사. 이 문서는 학습·τ 재추정·평가 결과 계산을 하지 않았다. 새 말 모형 학습, 데이터베이스·운영 등록부 쓰기, 기존 결과 수정, 외부 자료 수집도 하지 않았다.

## 판정

제안된 비교는 기존 `F1_STYLE6` 말점수 출력을 그대로 고정한 채, 무순위 Top3 집합에 순서불변 pair residual을 더하는 조건부 분포 실험으로 설계할 수 있다. 저장된 F1_STYLE6 연도별 `calibration_scores`가 각 해당 평가 모형의 refit 종료일 뒤에 생성된 out-of-sample 점수여서 2단계 관계모형 학습에 쓸 수 있다. 따라서 이 비교에 새 말 모형 fit은 필요하지 않다.

주요 승인 전 조건은 다음이다.

- 모든 경주에서 가능한 `C(N,3)` 삼두 집합 전체를 분모로 하는 단일-positive 조건부 NLL을 쓴다. 말별 세 분류 또는 pairwise positive/negative 독립 분류로 목표를 바꾸지 않는다.
- 두 모형은 경주당 정확히 같은 여섯 개의 무순위 조합을 고른다. 핵심 hit 사건은 실제 Top3 무순위 집합과 정확히 같은 조합이 여섯 장 중 하나인지다.
- 두 단계 입력은 날짜순으로 분리하고 경주일을 나누지 않는다. H1 학습 라벨은 첫 H2 경주일보다 최소 2일 먼저 끝나야 하며 H2 보정 라벨도 첫 평가 경주일보다 최소 2일 먼저 끝나야 한다.
- 저장된 연도별 전체 calibration τ는 사용하지 않는다. 동일 H2에서 additive 기준선과 관계모형 각각의 단일 joint-NLL temperature를 다시 맞춘다. 기준선의 공식 고정 선택표는 별도로 재현해 보존한다.
- pair 에너지의 모든 삼두 후보 값에서 말별 가산 공간을 제거한다. 그래야 pair 모형이 기존 말점수를 반복 학습하는 통로를 막을 수 있다.
- 평가 결과는 반복 사용된 2024~2026 후향 코호트 결과로만 보고한다. 새 독립 미래 검증이나 운영 성능의 증거로 부르지 않는다.

구현 담당자의 잠정 계획을 받은 뒤 교차검토 내용을 아래에 추가한다. 결과 실험은 사전 계약과 승인 전에는 시작하지 않는다.

## 고정된 말점수와 OOS 자산

`20261010_style_history_ablation_v1/CONTRACT.md` 및 `outputs/prepared_lock.json`은 F1 24입력 말 모형을 보존하고 고정 입력 30개를 쓰는 `F1_STYLE6`을 선언한다. F1_STYLE6 평가는 17,412 출전·1,779 경주·269 경주일이며 2026년은 9월 19일까지의 부분연도다. 말점수는 LightGBM raw score이며 set 확률은 가능한 모든 무순위 삼두에 점수 합을 부여해 정규화한다.

연도별 저장 calibration 파일은 해당 평가연도 모형의 미래 테스트가 아니라 그 모형의 refit 종료 다음 해를 예측한다. 이 점수는 관계모형이 학습할 캘린더 해의 결과가 해당 말 모형 fit에 들어가지 않았음을 뜻한다.

| 평가 모형 | 말 모형 refit 종료일 | OOS calibration 기간 | 저장 출전 수 | 경주 수 |
|---|---|---|---:|---:|
| F1_STYLE6_2024 | 2022-12-24 | 2023-01-06–2023-12-30 | 6,506 | 657 |
| F1_STYLE6_2025 | 2023-12-30 | 2024-01-05–2024-12-28 | 6,329 | 637 |
| F1_STYLE6_2026 | 2024-12-28 | 2025-01-03–2025-12-27 | 6,410 | 654 |

이 자산을 각 대응 평가연도 실험의 2단계 기간으로 나누면 같은 고정 F1_STYLE6 모형의 H1·H2·다음 해 평가 점수를 쓸 수 있다. H1은 절반기 초반 경주일, H2는 절반기 후반 경주일로 나누고 같은 날짜의 경주를 한쪽에 함께 둔다. H1 관계학습 점수와 다음 해 평가 점수는 같은 연도별 말모형이 생성하므로 그 fold 안에서 raw-score 눈금이 일치한다. H1/H2 경주 수·날짜 수·최초/최종 날짜는 결과를 보지 않는 입력 preflight에서 기록할 수 있으나, fold가 두 날의 purge 규칙을 충족하지 않으면 분할을 바꾸지 말고 사전 계약을 다시 검토해야 한다.

기존 `20261009_axis_companion_pairs_v1/outputs/oof_runners.parquet`는 2020–2023 R1_21 기반 OOF 36,800행이다. 시간순 OOF와 순서불변 pair-input 구현의 선행 사례로 참고할 수 있지만, 입력·점수·모형이 F1_STYLE6과 달라 고정 F1_STYLE6의 관계모형 학습 점수로 바꾸어 사용하면 비교가 달라진다. 새로운 F1_STYLE6 말 모형을 만들지 않기로 한 현재 설계에서는 이 R1 OOF를 직접 합치지 않는다.

H1/H2 운영 계약은 다음과 같이 잠가야 한다.

1. 평가연도 Y에 매핑된 calibration-score 모형 하나만 사용한다. 그 파일의 raw `score`와 같은 연도·모형의 고정 `features.parquet` 행을 공식 `api_record_id`로 일대일 연결한다. key는 조인용으로만 두며 모델 입력으로 전달하지 않는다.
2. 각 경주일을 통째로 H1 또는 H2에 배치한다. 첫 H2 경주일을 D라고 할 때 H1에 넣는 label 날짜는 `race_date <= D − 2일`이어야 한다. 2023-06-30 label을 2023-07-01부터 보정에 쓰는 식의 인접일 분리는 purge 실패다.
3. H2의 마지막 label 날짜는 첫 평가 경주일 E보다 `race_date <= E − 2일`이어야 한다. 메타의 단순 연도 경계만 믿지 말고 실제 경주 날짜에서 두 조건을 검사한다.
4. H1 score가 해당 말 모형의 `refit_max` 이후인지 전수 확인한다. 평가 라벨이나 평가연도 예측값은 관계모형 계수, feature scaling, 하이퍼파라미터, 임계값, 보정에 사용하지 않는다.
5. OOF라는 용어는 이 저장 calibration score가 해당 F1_STYLE6 모형의 학습에서 제외된 다음 해 점수라는 의미로만 쓴다. 반복 연구에 이미 사용된 결과 연도는 독립적·신선한 테스트 집합이 아니다.

## 최소 실행가능 분포 모형

정상 완전 경주 r의 전체 출전집합을 `H_r`, 실제 순위 1·2·3위의 무순위 집합을 `T*_r`라 한다. F1_STYLE6 raw score `z_h`를 고정하고 기존 evaluator와 같은 좌결합 sorted-score 합으로 기준 energy를 계산한다.

`U_r(T) = ((z_i + z_j) + z_k)` for `T={i,j,k}`.

선택한 작은 사전 고정 pair basis `φ_m(i,j)`는 `φ_m(i,j)=φ_m(j,i)`를 만족해야 한다. 관계 learner는 말별 점수·기존 F1_STYLE6 입력의 대칭 pair 표현만 사용한다. 경주 ID·출전 ID·말 ID·마번·날짜·결과, 레이스별 target 순위, 당일 또는 사후 기록은 모델 입력에 넣지 않는다. 마번/공식 ID는 조인·안정 tie-break 및 감사 원장에만 둔다.

각 삼두 후보에 대해 원 pair 합을 `D_{r,T,m}=Σ_{i<j, i,j∈T} φ_m(i,j)`로 만든 뒤, 말 incidence 행렬 `A_r[T,h]=1[h∈T]`의 column space로 `D`를 투영해 그 성분을 뺀다.

`R_{r,:,m} = (I − P_{A_r}) D_{r,:,m}`

여기서 `P_A=A A⁺`는 수치 안정적인 QR/SVD 또는 동등한 Moore–Penrose least-squares 투영이며, 모든 `C(N,3)` 행에서 계산한다. 말별 가산 성분은 제거된다. 예를 들어 pair function이 `g(i,j)=a_i+a_j+c`뿐이면 `D_T=2Σ_{h∈T}a_h+3c`이고 이는 `col(A)`에 있으므로 `R=0`이다. 이 불변성은 단순 점수 복제·가산 재학습이 관계효과처럼 통과하는 것을 수학적으로 차단한다. 정규화·rank tolerance·N<5 같은 퇴화 roster 처리는 입력계약에 미리 적고 검증해야 한다.

관계 score는 `G_r(T)=βᵀR_{r,T}`다. 단일 conditional set distribution은 다음과 같다.

`Q_r(T | H_r) = softmax_{T ∈ C(H_r,3)} [(U_r(T)+G_r(T))/τ_r]`.

H1에서 `U`는 고정 offset이며 계수·F1 점수를 다시 학습하지 않는다. 경주별 true-set NLL의 산술평균에 미리 고정한 작은 ridge penalty `λ||β||²`를 더해 `β`를 적합한다. feature scaling은 H1만으로 산출한다. H2에서는 additive 대조군 `U`와 pair 후보 `U+G` 각각의 동일한 bounds·동일한 race-equal true-set NLL 최적화로 단일 positive temperature를 정한다. 저장된 전체 calibration year τ는 H2의 label을 이미 포함하므로 재사용하지 않는다. 이 구조에 별도의 base-score offset 계수나 말별 모델 gradient를 더하지 않는다.

이 모형은 무순위 Top3 집합 분포만 제공한다. 한 경주의 모든 후보 삼두가 정규화 분모에 포함되고, true set 하나가 positive다. 말별 Top3 marginal은 이 분포에서 합산해 진단할 수 있으나 winner, 순서별 2·3착, 삼쌍승 또는 순서가 있는 어떤 승식도 출력한다고 표현하지 않는다.

## Pair 복제 방지와 음성 대조

제안 모형과 최소 음성 대조는 같은 수식 안에서 확인할 수 있다.

- **주 후보:** `β`만 H1 conditional NLL로 학습하는 저차원 ridge pair-residual 모델. feature와 `λ`를 사전 고정한다. 결과를 보고 변수, λ, H1/H2 경계, tau bounds를 선택하지 않는다.
- **0-residual 대조:** `β=0`이면 candidate energies가 원래 F1_STYLE6 energies와 bitwise 같아야 하며, matched-temperature 확률은 평가 H2가 정한 additive 기준선과 같아야 한다. 고정 공식 baseline ticket file과 각 경주의 6행을 정확히 대조한다. 1,779경주 전체면 변형당 10,674개 ticket 행이다.
- **Unary-only negative control:** pair basis를 `g(i,j)=a_i+a_j+c` 꼴 unary-only 함수로 대체해 같은 incidence projection을 통과시킨다. residual max norm이 정한 floating tolerance 안에서 0이고 conditional set 확률 및 canonical 6 ticket이 additive 기준선과 일치해야 한다. 이를 만족하지 못하면 진짜 pair 실험을 막는다.
- **대칭성·순열검사:** 각 pair endpoint를 바꾸어도 `φ`·`G`가 같고, 출전 행을 무작위 순열해 되돌려 key별 결과가 같아야 한다. pair order 또는 row order를 관계 입력으로 쓰지 않는다.

관계 basis는 기준선에만 이미 있는 출전별 입력에서 미리 지정한 극소수의 cross-horse 차이/곱/유사도 항으로 만든다. 대칭 연산(`min/max`, 합/평균, 절대 차이, 곱 등) 후 모든 항을 위 set-level unary projection으로 처리한다. 스타일의 의미·결측 정책·스케일을 새로 만들 경우 각각 입력계약에 적고, 결측을 중립값이나 낮은 말 능력으로 자동 취급하지 않는다. F1 점수 하나만 pair로 변환한 후보는 관계 효과보다 비선형 score calibration일 수 있으므로, 이를 핵심 관계 basis라고 부르지 말고 별도 control로 해석한다.

## 동일 여섯 장·평가와 통계

매 평가 경주에서 additive 기준선과 관계모형은 자신의 전체 `Q`에서 정렬된 최상위 정확히 여섯 무순위 삼두를 선택한다. 동점은 horse-number 조합 열거와 stable 정렬 규칙을 사용하되 마번은 관계 입력이 아니다. `C(N,3)<6`인 경주가 확인되면 exact-six 공통 코호트와 분모를 사전에 명시하고 후보/기준선에 동일 적용한다. 확률은 선택 pool이 아니라 전체 `C(N,3)`에서 정규화한다.

primary는 intended action을 직접 나타내는 race-level `exact_unordered_top3_hit@6`다. 한 경주의 실제 Top3 ID 집합이 같은 세 말로 된 선택 티켓 중 하나와 완전히 일치하면 1, 아니면 0이다. 말 하나 포착, 2마리 pair 포착 또는 순서 일치는 hit가 아니다. 비교는 같은 여섯 장의 경주별 hit에 대한 관계모형−기준선 paired 차이를 race-day cluster 단위 bootstrap으로 계산한다.

필수 proper-loss guardrail은 전체 집합분포 true-set NLL이다. 전체 `C(N,3)`에서 계산하고 경주마다 같은 가중치를 둔다. full-joint Brier와 marginal Top3 log loss/Brier, 여섯 티켓 예측 mass `Σ_{selected 6}Q(T)` 및 그 관측 hit 빈도의 calibration은 보조로 보고한다. Hit@6는 의사결정상 직접 관련되지만 분포 전체에 proper한 점수는 아니며 큰 표본에서도 운에 민감하다. winner나 ordered PL 지표와 섞지 않는다.

성능 승인 규칙은 실행 전 한 가지로 고정한다. 여섯 장 선택 개선을 묻는 이 비교의 주지표는 paired `hit@6`이며, 이를 만족해도 joint-NLL가 사전 비열등 한계를 넘어 악화하면 관계모형 유지 신호로 승인하지 않는다. NLL 비열등 한계와 각 CI 방식은 결과를 보기 전에 root가 계약에 명시해야 한다. 두 지표를 모두 개선 요구로 두려면 그것도 사전에 한 번만 선언한다. 여러 지표 중 유리한 것만 골라 결정하지 않는다.

전체 2024–2026 date bootstrap은 날짜를 cluster로 뽑고 같은 경주의 두 모형 차이를 함께 유지한다. 경주를 독립 표본처럼 bootstrap하지 않는다. 2026년은 9월 19일까지의 부분연도이며 연도별 결과와 269일 전체 paired 범위 및 지원량을 제시한다. 이 기간은 기존 STYLE6/조합 연구 등에서 이미 반복 사용한 라벨이므로 bootstrap CI가 독립 holdout을 만들지는 않는다.

## 사전 gate·누출 차단

학습·metric 실행 전 작성 계획에서 반드시 확인할 항목은 다음과 같다.

1. 연도별 `meta.json`, `calibration_scores.parquet`, F1_STYLE6 `features.parquet`, 저장 model/evaluation scores와 source lock의 SHA·행키 일치. calibration raw score와 feature/label 조인이 1:1이고 평가연도·경주/말 수가 기준과 일치하는지 확인한다.
2. input feature, lineage, `race_id`, `api_record_id`, `horse_id`, 마번, race date, finish/place label 및 대상군 조건이 모델 matrix에서 빠졌는지 확인한다. 해당 변수들은 join, partition, tie-break, audit 용도만 허용된다.
3. 완전한 `1..N` 착순을 가진 정상 경주만 기존 모집단 그대로 사용하고, 대상 삼두는 모든 unordered combination으로 생성한다. 결과로 유망 말/조합만 후보에 남기지 않는다. 모든 feature/as-of 계약은 F1_STYLE6의 원래 데이터 사후 코호트 제한을 상속한다고 표시한다.
4. actual date split에서 `max(H1 label date) <= min(H2 race date)-2 days`와 `max(H2 label date) <= min(evaluation race date)-2 days`를 검증한다. 하나라도 실패하면 fit 전에 중단한다. 미래 날짜의 label, full-year saved τ, test outcome-derived grouping 또는 자료 경계 수정은 금지한다.
5. pair endpoint swapping과 runner row reordering에서 동일 확률, unary projection 음성 대조에서 정확한 무효, β=0 ticket parity 및 all-combination probability sum 1을 preflight로 확인한다.
6. 평가출력은 saved F1_STYLE6의 평가 raw scores를 그대로 받는다. 결과를 보기 전에는 feature, ridge penalty, cohort, temperature bound, ticket count, primary metric, bootstrap seed/draw를 수정하지 않는다.

## 교차검토 결과 (구현 계획 대기)

2026-10-10에 구현 초안 [`20261010_joint_relationship_v1/PLAN.md`](../20261010_joint_relationship_v1/PLAN.md)와 [`SOURCE_AVAILABILITY.md`](../20261010_joint_relationship_v1/SOURCE_AVAILABILITY.md)를 교차검토했다. 첫 읽기 당시 PLAN SHA-256은 `dbdbd9d1b28ea5d176450b9dfc44c7e63478cbe834dbbb13b89792714dfe7db4`였다. 감사 의견과 root 요구 반영 뒤 최신 읽기 PLAN SHA-256은 `01d81246c3dbb07e4d3302f366d49cda4b31d3db9d553a3892dd2bc016f4829c`, availability note SHA-256은 `32dd5c93f7cf11e033ae7bbc2b6677dff5981bbac6097520ecdd1327512ee608`다. 최신 PLAN은 이 시점에 source-lock 승인 전 초안이며, 정식 고정 해시가 별도 선언되어야 한다.

초안의 핵심 방향은 승인 가능하다고 판단했다. 11개 대칭 pair 기저를 두고 H1에서 raw F1_STYLE6 triple energy를 고정 offset으로 조건부 NLL 학습하며, H2에서 additive와 후보의 단일 양수 temperature를 같은 joint-NLL 계약으로 보정하는 구조는 말점수 재학습·저장 연도 전체 τ 누출을 피한다. 목표 단위도 전체 무순위 `C(N,3)` one-positive 집합 분포다. H1/H2를 경주일 단위로 나누고 첫 H2일에서 2일 purge한다는 조건은 T−2 시간 기준에 부합한다. 저장 calibration score를 사용하므로 새 base horse fit이 필요하지 않다.

pair unary 투영식은 올바른 것으로 확인했다. 완전 무방향 pair graph에서 `d_i=Σ_{j≠i}φ_ij`, `S=Σ_{i<j}φ_ij` 및 `a_i=(d_i−S/(N−1))/(N−2)`이면 `R_ij=φ_ij−a_i−a_j`가 각 i에 대해 `Σ_{j≠i}R_ij=0`을 만족한다. 또한 `Σ_{T:h∈T}Σ_{i<j∈T}R_ij=0`이므로, 모든 C(N,3) 조합에서 triple pair-sum은 말별 가산 energy 공간과 직교한다. 초안이 사용한 계산법은 root의 요구한 unary incidence projection과 수학적으로 동등하다. 독립 코드 검증에는 쌍 행합뿐 아니라 후보 삼두 행렬 `AᵀG=0`을 직접 확인하는 것이 가장 분명하다.

root는 방향에 동의했고 첫 교차검토 뒤 plan에 다음 구체 조건을 더 요청했다. 최신 읽기본에는 모두 반영됐다.

1. pair residual RMS normalization과 valid-value 표준화를 race-equal로 정의한다. pair행 수가 많은 큰 필드가 λ=1 정규화에 더 큰 비중을 갖지 않게 각 경주 평균 뒤 경주 평균을 취한다. valid 분모를 명시하고 std 및 pair RMS가 `≤1e−12`인 열은 degenerate로 고정한다.
2. `C(N,3)≥6`을 동일-six 코호트 preflight 조건으로 고정한다. fold별 `H1/H2/evaluation` actual key, triple 개수, `refit_max < H1 min` 또는 OOS가 확인되는 경계를 검사한다. H1/H2와 H2/test의 각 purge inequality를 exact assert한다.
3. unary-only 합성 대조 `φ_ij=a_i+a_j+c`가 projection을 통과한 뒤 zero로 소거되고 additive 기준선 확률 및 canonical ticket과 일치하는지 확인한다.
4. β=0 parity는 race ID·선택 순위·조합 마번이 모두 같은지 전수 비교하고, 1,779경주면 variant 당 10,674 행임을 기록한다. triple energy도 원 evaluator의 세 점수 sort 후 `np.sum(axis=1)`과 정확히 같은 계산 순서를 보존한다.
5. H2 last label과 다음 평가 첫 race date 사이의 purge는 `max(H2 label date) <= min(eval race date)-2 days`로 적는다. 평가에 사용된 모든 점수는 사전에 고정된 saved test scores에 한정한다.

최신 draft의 조건부 분포 수식과 workflow는 사전 비교를 위해 충분히 구체적이다. `A.T @ G = 0`는 pair graph의 zero row-sum 증명과 맞는다. 동일 six 지원에서 삼두 모형을 비교하고 `N>=5`, 모든 후보 set의 정규화, positive temperature, 저장 baseline selection parity를 요구한 점도 적절하다. 연구 신호 gate는 hit@6 paired CI 하한 양수와 joint true-set NLL paired CI 상한 0 이하를 함께 요구하므로 actionable hit와 full-distribution proper loss를 혼합해 선택하지 않는다.

mean 스타일 scaler의 분모는 root 결정으로 명확해졌다. 현재 계약의 `Σ_{valid}(1/N_r)x / Σ_{valid}(1/N_r)`와 이에 맞춘 weighted population SD를 유지한다. 완전 지원 score/count는 경주별 총 가중치가 같지만, valid row만 남기는 mean style 열은 유효 관측 비율이 낮은 경주일수록 mean과 SD에 덜 기여한다. 이를 엄격한 경주 균등 scaler라고 부르지 않고 `valid-runner-weighted, 1/N_r` 표준화라고 부른다. Pair RMS와 conditional objective는 별도이며 경주 균등이다.

이 보완은 결과 실험을 허용하지 않는다. 현재 교차검토에서 model fit, temperature optimization, outcome metric 계산은 하지 않았고 구현/실행 코드도 여기 만들지 않았다. PLAN source lock 및 C preflight 이후에는 허용된 입력·시점·대칭성·투영·degeneracy 검토만 한다. H1 관계계수 적합, H2 온도 보정, 평가 라벨 기반 결과 계산은 C preflight 통과 및 별도 root 승인이 있을 때까지 금지다.

### outcome-free 코드 정적 검토

계획에 맞춘 최초 `joint_model.py`와 `preflight.py`를 읽어 설계·누출·Python 파일 경계만 검토했다. 검토 시점 해시는 각각 `e1ccc7e34a092b4bdccb321accfd8fa0fe4f6682d0e1419ea28f56707284f742` 및 `60484c541d9596e822600e24a3fab357cc653549af1ecb41566e30474c13c3d0`이다. 코드를 실행하지 않았다.

코드의 input columns는 고정 score와 여섯 STYLE6 열뿐이다. horse/race/API ID와 마번은 조인·중복 확인·정렬 용도다. pair endpoint 대칭성, pair residual row-sum, 삼두 `AᵀG` 직교성, synthetic unary-only control, positive τ 및 full-combination softmax 경로가 함수 계약과 일치한다. `exact_set_objective`의 gradient는 `Σ_T Q(T)R(T)−R(T_truth)`이며 H1 race 평균 뒤 고정 ridge 항을 더한다. 보정은 baseline/candidate의 같은 H2 set-NLL을 각각 최적화하고 날짜 paired bootstrap은 날짜 전체를 cluster로 재표집한다. 파일 경로는 고정된 repo 경로이며 JSON output은 create-new 모드다. 코드에는 network, database, subprocess 또는 동적 실행 경로가 없다.

최초 정적 읽기에서 C preflight 보완 세 가지를 구현 담당자에게 전달했다.

- `race_groups()`는 당시 세 개의 `finish_position<=3`만 확인했다. 아래 순위에 중복이 있어도 정답 세 두만 있으면 통과할 수 있으므로 완전 정상 코호트의 전체 순위가 `1..N`의 고유 순열인지 assert해야 한다.
- `split_calibration()`은 `meta.evaluation_min`을 purge 날짜로 신뢰했지만, 실제 evaluation score와 join된 경주 날짜의 min/max가 이 메타 값과 일치하는 검사와 calibration 기간 min/max 검사 없이 있었다. actual joined date를 cutoff로 쓰고 meta parity를 확인해야 한다.
- 계획에 요청한 `inspect_roster()`는 구현돼 있으나 preflight 호출에서 빠져 있었다. 모든 H1/H2/evaluation race에서 pair design rank 및 residual rank를 계산·기록해야 한다.

preflight ticket 비교의 Pandas 문자열 dtype 차이는 최신 읽기 코드에 `actual` 및 `stored` 양쪽의 동일 dtype cast가 반영되어 있다. 다만 아직 locked source hash와 실행 영수증을 확인하지 않았고 실행도 하지 않았다. 구현 담당자가 위 수정 완료본과 outcome-free preflight 산출물을 공유하면 추가 정적 교차검토를 진행한다.

