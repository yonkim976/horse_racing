# 순위 단계별 온도 보정 방법 감사

2026-10-22. 기존 연구 문서·코드·요약 산출물을 읽어 다음 확률 개선 방향을 비교했다. 새 적합, score/Q 생성, 성능 재계산, 대형 파일 열기, DB 조회, 외부 자료 수집은 하지 않았다. 연구 폴더에는 이 `audit/` 보고서와 소형 입력 참조 JSON만 작성한다.

## 먼저 고정해야 할 수식 구분

우선 가설인 단계별 온도 3개는 **전체 출전마 roster 위의 순차 Plackett–Luce**에 적용해야 식별된다.

`Q(i,j,k) = P1(i | R; T1) × P2(j | R\{i}; T2) × P3(k | R\{i,j}; T3)`

여기서 2·3착 단계의 softmax 분모는 Top3에 든 말만이 아니라 앞서 선택한 말을 제외한 **전체 남은 출전마**다. 3착 뒤의 미선택 말도 `T3`의 risk set에 들어야 한다. 현 제주 정상 완주 코호트의 최소 편성은 7두라 3착 선택 때 대안이 남으며 `T3`가 식별 가능하다. 이 full-field 형태에서는 확률 질량이 자동으로 1이고, WIN은 `T1`, Top2는 `T1,T2`, exact Top3는 `T1,T2,T3`에 순차적으로 의존한다.

반대로 10/17 방식처럼 기존 Top3 집합 `{i,j,k}`를 먼저 고정하고 그 집합 안 순서만 나누면, 첫 말·둘째 말이 정해진 뒤 세 번째는 남은 한 마리로 결정된다. 이 방식의 별도 3착 `T3`는 식별되지 않는다. 여기서는 최대 두 개의 비자명한 조건부 순서 온도가 가능하다. 새 설계 계약에서 이 두 분포를 같은 것으로 취급하면 안 된다.

## 후보 방법 비교

| 방법 | 자유도와 선행 상태 | 중복 여부·근거 | 누수·일반화 위험 | 판단 |
|---|---|---|---|---|
| **Full-field 단계별 PL 온도** | 양수 `T1,T2,T3`, 전 기간 전역 3개 모수. 각 stage의 conditional NLL 항이 분리되므로 stage별 scalar 적합 또는 동등한 3변수 적합으로 고정 가능 | 같은 세 단계 온도 실험은 검토한 10/10 STYLE6, 10/10 관계, 10/11 pair, 10/17 조건부 순서, 10/22 단일 T 자료에서 발견하지 못했다. 직전 PL의 `T=1` 대 공통 `T=1.1837152`는 전 rank 공통 단일 온도였다. TRI NLL은 개선했지만 단승은 악화했고 2025·2026 TRI Brier는 소폭 악화 | 2019–23 labels로만 fit하면 직접 누수는 낮고 새 feature도 없다. 다만 같은 2024–26 평가기간은 반복 사용된 개발 자료이며 독립 검증이 아니다. 같은 해에 fit된 provider `tau`/확률을 쓰지 말고 raw `score`만 사용해야 한다 | **다음 한 후보로 가장 작고 직접적**. 식과 분모를 사전 고정하고 이전 1,779경주 결과는 반복개발 증거로 한정 |
| Native Top3 집합 `q(T)` + 조건부 순서 온도 | `T_set,T_order` 전역 2개를 둔 단순 변형이면 2개. `q=softmax(sum(sort(score_T))/T_set)`, 집합 안 PL 순서에 `T_order`; 조건부 집합 안 3착 온도는 없음 | 정확히 이 2-온도 global fit은 찾지 못했지만 native `q`와 conditional-order PL을 합치는 구조는 10/17에서 이미 구현·검증됐다. 그 연구는 `q`를 고정하고 10개 beta 계수 + fold별 order T를 사용했다. 10/17 고정 점수 대조군 대비 조건부 순서 NLL은 1.8340→1.7419였지만, 2026 공통 HY 467경주에서는 네 풀 NLL/Brier가 모두 더 나빴다 | 두 점수 기반의 일관된 Q가 가능하다. 단, 같은 라벨 연도의 저장 native `tau_Y`를 새 입력으로 쓰면 보정 라벨이 섞일 수 있다. 새 `T_set,T_order`를 2019–23 raw-score 라벨에서만 잠그고 동일 평가 데이터를 재검증으로 부르지 않아야 한다 | 조건부 순서 NLL과 집합 NLL을 분리하는 대체 가설. 이미 있는 10/17 연구와 차별점·질문을 분명히 할 때만 후보 |
| F1_STYLE6 집합 보존 conditional-order head | fold별 10개 beta + 1개 order temperature(3 fold 총 33개 scalar fit); native `q(T)`는 고정 | 이미 수행됨. H1 계수 학습, H2 온도 보정, T−2 purge. 실제 Top3 set 안의 순서분포를 재배치하며 set mass와 Top3 marginal은 그대로다. 조건부 PL 대조군보다 TRI NLL은 통과했으나 HY 공통 467의 NLL 차이는 WIN/QNL/EXA/TRI에서 +0.1300/+0.1558/+0.1767/+0.1813으로 불리했다 | 정한 H1/H2 분할과 purge는 직접적인 시간 누수를 제한한다. 다만 최종 2024–26 기간은 반복 사용됐고 출판 시각은 미검증이다. 실제 set을 주는 conditional-only 평가를 전체 경주 성능으로 혼동하면 안 된다 | **재실행 중복**. 재현 가능한 기존 증거로만 참조 |
| Pairwise 관계항으로 Top3 set 에너지 조정 | fold당 11개 beta와 baseline/candidate H2 온도 2개; 3 평가 fold에서 33 beta + 6 calibration scalar | 이미 수행됨. 11개 고정 무순서 pair 특징을 추가해 C(N,3) set 분포를 정규화했다. 6-ticket 적중 게이트와 exact set NLL 보호 게이트 모두 실패; NLL 후보−대조군 +0.000635 | H1/H2 시간 분리는 했지만 스타일 요약 관계대리변수, 연도별 계수 변동, 같은 반복 평가기간 문제가 있다. 더 많은 구조 자유도는 stage T보다 과적합·선택자유도 부담이 크다 | **후보 재탐색 금지**. 이전 결과만 남기고 새 개선 가설로 반복하지 않는다 |

별도 거부 근거: direct pair 예측은 기존 보고에서 427/1,779로 raw-score Top2 429/1,779보다 낮아 주 게이트를 통과하지 못했고, 모든 pair 확률 질량이 3이라는 공동분포 보장도 없다. 승식별 독립 calibrator도 합산 일관성, `WIN≤Top2≤Top3`, Q에서 유도되는 조합 확률을 보장하지 않으므로 이 과제의 후보로 적절하지 않다.

## 점수 계약과 시점

새 단계별 PL은 기존 점수 계약 변경이 필요하지 않다. 이미 고정된 raw-score 자산의 입력은 `api_record_id:int64, score:float64`이고, 출전 roster·`finish_position`·race/date 키는 frozen feature table에 있다. 2019–2025 OOS provider의 총 규모는 3,783경주·38,017행이며, 직전 기준선은 2019–2023의 2,492경주·25,278출전 행에서 T를 맞췄다. 이미 있는 2024–2026-09-19 평가는 1,779경주·17,412출전 행·269일이다. 개별 score 경로·연도·행수·해시는 [`input_references.json`](input_references.json)에 기존 asset manifest를 통해 참조했다. Parquet/feature를 복사하거나 이번 감사에서 읽지 않았다.

후보도 직전 기준선과 동일하게 `calibration_scores.parquet`의 raw `score`만 사용하고 provider `tau` 또는 calibrated probability는 사용하지 않아야 한다. 특히 2023–2025 label-year provider tau는 같은 라벨 연도 calibration 기록에 fit됐다. 저장 cutoff와 refit 시점은 기존 manifest에서 이미 검증됐으나, T−2는 날짜 경계일 뿐 최초 공개 시각 보장이 아니다. 지금 단계에서 평가 구간을 다시 사용해도 새 holdout이 생기지 않는다.

## 근거 위치와 제안

- 직전 비교 수식·단일 온도 T=1.1837152·2024–26 결과는 [기준선 최종 보고](../../20261022_joint_wager_baseline_v1/README.md#L52)와 [고정 계획](../../20261022_joint_wager_baseline_v1/experiment/PLAN.md#L26)에 있다. 전체 TRI NLL 차이는 −0.018267이며 bootstrap CI 상한이 0 아래였지만, WIN NLL은 +0.003477 악화했다. 2025/2026 TRI Brier 차이도 +0.000064/+0.000032였다.
- native 집합 확률과 10/17 순서 헤드 정의·학습 자유도는 [10/17 계획](../../20261017_conditional_order_head_v1/PLAN.md#L9) 9–17행, 38–52행, 기존 결과는 [10/17 보고](../../20261017_conditional_order_head_v1/README.md#L5) 5–29행이다.
- 관계 모형의 11차원 pair 기저·temperature 역할과 사전 게이트는 [관계 계획](../../20261010_joint_relationship_v1/PLAN.md#L37) 37–59행, 결과는 [관계 보고](../../20261010_joint_relationship_v1/README.md#L9) 9–18행에 있다.
- direct pair 반복 평가의 427 대 429 및 coherence 한계는 [pair 확장 보고](../../20261011_pair_top3_oos_expansion_v1/README.md#L1) 1–21행에 있다.
- frozen score 행·경주 수, 경로·hash·same-year tau 경고는 [직전 자산 감사 manifest](../../20261022_joint_wager_baseline_v1/assets_audit/assets_manifest.json)와 [자산 감사 보고](../../20261022_joint_wager_baseline_v1/assets_audit/README.md)에 있다.

권고는 **full-field 순차 PL의 global stage temperature 3개를 하나의 사전 후보로만 검토**하는 것이다. baseline은 동일 score의 세 단계 모두 T=1로 둔다. 후보는 2019–23 raw OOS score와 정확 1→2→3 라벨로 race-equal joint NLL을 최소화하고, 2024–26의 이미 반복 사용한 cohort에서 7승식/순위 주변확률을 같은 Q로 평가한다. 각 `T_s`의 분모는 당시 남아 있는 전체 출전마로 한다. order-only Top3-set head 안에 `T3`를 추가하거나, 결과를 본 뒤 stage별·연도별·거리별 후보를 더 늘리지 않는다. 적합·예측은 현재 승인 범위가 아니며 main의 승인 및 별도 worker 작업 전에는 실행하지 않는다.
