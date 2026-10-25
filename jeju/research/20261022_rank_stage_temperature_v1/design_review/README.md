# 순위 단계별 온도 후보 — 설계 검토

검토일: 2026-10-22 (Asia/Seoul)  
검토 범위: 수학적 계약·실패 가능성·평가 게이트 설계만 검토. 이 문서는 실제 온도 적합, Q 생성, 결과 재계산, 후보 구현 또는 운영 채택을 하지 않는다.

## 판단 요약

양의 단계별 온도 `T1,T2,T3`를 동일 raw score `F1_STYLE6`에 적용하는 순차 Plackett–Luce 분포는 전체 ordered Top3 공간에서 정확히 정규화된다. 한 개 공통 온도는 `T1=T2=T3`인 대각선 부분모형이므로, `T=1.1837152381349905`와 원래 `T=1` 모두 후보군에 포함된다. 모든 승식과 말별 주변확률을 같은 Q에서 합산하면 기존 규칙·라벨 계약의 일관성이 유지된다.

양의 역온도 `β_l=1/T_l`를 쓰면 과거 정답을 조건으로 한 ordered-triple NLL은 세 개의 독립적인 1차원 convex 목적함수 합으로 분리된다. 이는 계산·검토를 단순하게 하는 장점이다. 다만 stage-specific 모델은 추정 자유도가 늘고, 공동 온도보다 평가기간에서 좋아진다는 보장은 없다. 단계 온도가 다르면 높은 raw score 순서가 모든 ordered ticket의 최대확률 순서라고 보장되지 않는다. WIN 최고확률 말만은 `T1>0`에서 raw score 순서가 보존된다.

제안된 TRI 주 게이트와 WIN 보호 게이트는 명확한 손실 교환을 제한하는 안으로 타당하다. 그러나 2024–2026-09-19 평가는 기존 joint-wager 비교에서 이미 노출된 개발 자료다. 새 게이트를 지금 고정해도 독립적인 confirmatory holdout이 되지 않는다. 재평가는 탐색적·재사용 평가로 표기해야 하며, 독립 성능 주장은 아직 불가능하다.

## 분포 정규화 및 공동 승식 일관성

경주 roster를 `H`, 점수를 `s_h`, 양의 온도를 `T_l`, `β_l=1/T_l`이라 두면 stage별 조건부 확률은 다음과 같다.

```text
π1(i)       = exp(β1 s_i) / Σ_{h∈H} exp(β1 s_h)
π2(j | i)   = exp(β2 s_j) / Σ_{h∈H\{i}} exp(β2 s_h)
π3(k | i,j) = exp(β3 s_k) / Σ_{h∈H\{i,j}} exp(β3 s_h)
Q(i,j,k)    = π1(i) π2(j | i) π3(k | i,j),  i,j,k distinct
```

모든 `T_l>0`이고 `|H|≥3`이면

```text
Σ_{i∈H} π1(i) × Σ_{j∈H\{i}} π2(j|i) × Σ_{k∈H\{i,j}} π3(k|i,j) = 1.
```

따라서 모든 Q triple을 정확히 순회하거나 동일한 완전 공간에 대해 합산하면 `ΣQ=1`이다. 단계별 온도를 달리해도 체인룰상 정규화는 바뀌지 않는다. 상위 조합 일부만 뽑아 재정규화하면 이 성질은 더 이상 보장되지 않는다.

기존 규칙 계약을 그대로 유지할 수 있다.

- `P1(i)=Σ_{j,k}Q(i,j,k)`, `P2(i)=Σ_{j,k}Q(j,i,k)`, `P3(i)=Σ_{j,k}Q(j,k,i)`에서 `Σ_i P1=1`, `Σ_i PTop2=2`, `Σ_i PTop3=3`이다.
- WIN, QNL, EXA, TLA, TRI 티켓 공간의 사건확률 합은 각각 1이다.
- PLC Top2/Top3의 전체 말별 확률 합은 각각 2/3이고 QPL 모든 무순위 pair의 확률 합은 3이다. PLC·QPL은 다중 적중 사건이므로 1로 정규화하지 않는다.
- QNL/EXA/TLA/TRI/PLC/QPL은 모두 똑같은 Q에서 집계한다. 확률 손실도 기존 계약대로 단일 당첨 승식의 categorical NLL 및 sum Brier, PLC/QPL의 경주 내 평균 binary logloss/Brier를 유지한다.
- `T1=T2=T3=T`이면 기존 common-T 분포와 수식상 완전히 같다. 따라서 기존 `T=1.1837152381349905` comparator와 `T=1` baseline을 각각 재현할 수 있어야 한다.

단계 영향은 다르다. `T1`은 WIN 주변확률을 직접 바꾸며 뒤 단계 사건 전체에도 경로 가중치를 통해 영향을 준다. `T2`는 주어진 첫 말 뒤의 2착 선택을 바꾸지만 Q를 전부 합산한 WIN 확률에는 영향을 주지 않는다. `T3`은 처음 두 착순이 주어진 뒤의 세 번째 선택을 바꾸고, QNL/EXA/Top2 주변에는 영향을 주지 않는다. `T3`는 적어도 네 말 roster에서 세 번째 선택집합에 둘 이상의 말이 있을 때만 식별 가능하다. `N=3` 경주에서는 3착 조건부 선택이 결정적이므로 해당 경주가 `T3` 적합 정보가 되지 않는다.

## 적합 목적의 분리·볼록성

2019–2023 보정 자료의 race `r`에서 실제 착순을 `y_{r1},y_{r2},y_{r3}`라 두고, 정답을 조건으로 만든 risk set을 `R_{r1}=H_r`, `R_{r2}=H_r\{y_{r1}}`, `R_{r3}=H_r\{y_{r1},y_{r2}}`라 두면 negative log-likelihood는

```text
L(β1,β2,β3)
 = (1/R) Σ_r Σ_{l=1}^3
     [ log Σ_{h∈R_{rl}} exp(β_l s_{rh}) - β_l s_{r,y_{rl}} ]
 = L1(β1) + L2(β2) + L3(β3).
```

각 race·stage 항은 `logsumexp(β_l s)`에서 선형식을 뺀 형태다. 2차 미분은 각 risk set에서 해당 score의 softmax 가중 분산 합이므로 `L_l''(β_l)≥0`; 각 `L_l`은 convex다. 서로 다른 β 사이 교차항이 없어 목적함수는 **separable**하며, 3차원 동시 탐색 대신 각 stage의 1차원 문제를 따로 최소화할 수 있다. 실제 착순이 risk set에 관여해도 고정된 학습자료에서 stage별 가산성은 그대로다.

이는 `T_l` 좌표의 convex성을 뜻하지 않는다. `T`로 직접 최적화하면 비선형 역수 변환이 있어 일반적으로 convex objective가 아니다. 기존 baseline 범위 `[Tmin,Tmax]=[0.35,4.0]`를 각 stage에 그대로 재사용한다면 convex 좌표의 bounds는 `β∈[1/4,1/0.35]`이다. 새 범위를 선택하는 대신 기존 범위 재사용을 권한다.

볼록이라고 해서 내부 유일 최적점이 항상 있는 것은 아니다. 모든 risk set의 점수가 같으면 목적이 평평하다. 결과가 risk set별로 완전히 분리 가능하면 likelihood는 `β→∞` 방향으로 계속 좋아지고 유한 최적점이 없을 수 있다. 점수가 거의 같거나 표본의 조건부 순위정보가 약하면 최적 온도가 불안정할 수 있다. 실행 시에는 각 stage의 경계 도달 여부, Hessian/score-variance가 0 또는 극소인지, 유한 objective와 optimizer 수렴 여부를 별도 기록해야 한다. 경계 처리와 동률 최적해 규칙은 결과를 보기 전에 고정한다.

세 stage 모두 같은 calibration race 수를 사용하고 race당 각 stage의 조건부 로그손실을 한 번씩 더해야 한다. stage loss를 서로 다른 표본 수로 합산하거나 관측 횟수만으로 한 stage에 가중치를 더하면 common-T 비교와 다른 목적이 된다. 온도 세 개는 calibration 2019–2023 OOS 원점수와 정답만으로 fit하고, evaluation 원점수·정답은 어떤 T 선택에도 사용하면 안 된다.

## 정답 risk set과 정보 누수

정답 착순을 이용해 **훈련 likelihood의 관측된 조건부 경로**를 적는 것은 누수가 아니다. 이는 `P(y1) × P(y2|y1) × P(y3|y1,y2)`의 joint probability를 계산하는 표준 조건부 likelihood다. 실제로 2착 risk set은 정답 1착마를 제외하고, 3착 risk set은 정답 1·2착마를 제외해야 해당 관측 경로의 likelihood를 계산한다.

반대로 예측 시 모델을 위해 한 번만 risk set을 만들 때 검증/평가의 실제 1착·2착마를 빼면 명백한 target leakage다. 예측은 각 **가상 경로**에 대해 만든다. `Q(i,j,k)`는 첫 선택 후보가 `i`인 risk set, 다음으로 `j`를 고른 뒤의 risk set을 사용한다. 전체 event probability는 모든 후보 경로 Q를 합산한다. 평가 정답은 최종 loss에서 실제 경로의 Q를 지정하는 데에만 쓰며, 점수·온도·다른 ticket 확률 생성의 입력으로 되돌아가면 안 된다.

정상적인 과거 calibration fit에는 calibration label을 쓰는 것이 허용된다. 하지만 평가 2024–2026 실제 순위를 통해 온도, 경계, 후보 또는 gate를 조정하면 해당 평가는 개발 데이터가 된다. 본 후속 제안 자체가 이전 평가 결과를 본 뒤 발생했으므로 결과를 재계산해도 새 독립 검증이라고 부르지 않는다.

## 공통 온도 대비 후보의 성질·선택 위험

세 온도 family는 common-T family를 포함한다. 같은 bounds·표본·가중치라면 stage별 convex fit의 보정 NLL은 common-T 공동 최소 NLL보다 보정표본에서 나빠지지 않아야 한다. 이는 nested family의 학습 내 성질일 뿐 평가 성능에 대한 보장은 아니다. 3개의 상대적으로 자유로운 parameter는 단계별 miscalibration을 맞출 수 있지만, 각 stage의 조건부 표본이 가진 우연한 편차와 과거 반복 사용을 더 흡수할 수 있다.

양의 `β_l`에서 각 stage의 **주어진 risk set 내부 조건부 argmax**는 항상 raw score 최고 말이다. 하지만 Q는 단계확률 곱이고, 이전 선택이 이후 risk set을 바꾼다. 따라서 **전체 ordered ticket의 확률순위/MAP가 raw score 내림차순 또는 common-T 선택과 같을 필요는 없다.** 예를 들어 인접 stage `l,l+1`에서 `s_a>s_b`, `δ=s_a-s_b`, 다른 잔여 후보의 stage `l+1` 가중치합을 `C`라 두면, 동일한 prefix와 suffix에서의 swap 비율은

```text
Q(...,a,b,...)/Q(...,b,a,...)
 = exp((β_l-β_{l+1})δ)
   × [exp(β_{l+1}s_a)+C] / [exp(β_{l+1}s_b)+C].
```

공통 역온도에서는 score가 큰 `a`를 먼저 두는 쪽이 더 크다. β가 다르면 첫 항이 그 선호를 상쇄할 수 있다. 최소 합성 예로 3두 점수 `(3,2,1)`, `β1=0.01`, `β2=1`을 두면 마지막 선택은 단일 말이라 `β3`에 무관하고, `Q(2,1,3)`는 약 `0.294`, score 정렬 `Q(1,2,3)`은 약 `0.246`이다. 즉 stage-specific parameter는 ordered-ticket 순위를 바꿀 수 있다. 이 수치는 수식 예시일 뿐 실제 코호트 계산이 아니며, `N=3`는 `T3`를 식별하지 못하는 최소 예다.

WIN의 최고확률 말은 `T1>0`인 한 `argmax s_i`로 불변이다. 다른 pool의 무순위/순위 ticket 확률 합에는 단계온도와 경로가 다르게 반영되므로 QNL·EXA·PLC·QPL·TLA·TRI의 최고확률 ticket은 바뀔 수 있다. 특정 데이터에서 실제로 바뀌는지는 새 평가 전 계산하지 않는다. 선택 성능 개선을 보장하지 않으며, 선택 진단 결과가 0 또는 근소한 차이면 확률 동률·부동소수 순서가 아닌 원장된 정확한 계산과 고정 tie-break로 판정해야 한다.

## 평가 gate 검토

사전 계약으로 다음을 모두 요구하는 안이 합리적이다.

1. **주 gate:** 평가 cohort 전체 ordered TRI에서 `candidate − common T=1.1837152381349905`의 날짜 paired-bootstrap NLL 차이 95% CI 상한이 0 미만.
2. TRI categorical sum-Brier 차이(`candidate − common T`) 점추정치가 `≤0`.
3. **WIN 보호 gate:** WIN categorical NLL과 sum-Brier의 점추정 차이가 모두 `candidate − original T=1 ≤0`.
4. 모든 나머지 6승식의 loss·reliability·연도별 결과와 pool denominator를 보고하되 다른 pool 결과로 위 gate를 뒤집거나 사후 gate를 새로 추가하지 않는다. 승식별 기존 label/minimum/unknown denominator 계약을 그대로 쓴다.

NLL의 paired date bootstrap은 기존 고정 2,000×269 schedule, 같은 날짜별 race aggregation, 같은 평가 분모를 재사용해야 한다. 최적화된 세 온도는 bootstrap 동안 고정한다면 결과 CI는 평가일 재표집 변동만 반영하고 calibration/fit uncertainty는 포함하지 않는다. TRI Brier와 WIN 보호 gate가 점추정만 쓰는 것은 명확하고 단순한 안전선이나 “통계적으로 비열등함”의 증명은 아니다. 보고서에 관측된 손실차와 함께 이 한계를 적는다. 기존 결과 요약은 common-T 후보가 WIN NLL/Brier를 악화했다고 표시했으므로, WIN gate는 해당 trade-off를 제한하는 목적을 갖는다. 결과를 보고 만든 보호 gate이므로 추가로 탐색적이라는 표기가 필요하다.

현재 evaluation 기간(2024-01-05~2026-09-19)은 common-T 기준선에서 이미 성능·선택 진단에 사용되었다. Stage-specific 후보와 gate 설계가 그 결과를 확인한 뒤에 정해졌으므로, 같은 구간 재평가를 독립 confirmatory 시험이라고 부르지 않는다. gate 통과는 이전에 사용한 표본에 대한 개선 증거이고, 2026 이후나 사전 봉인된 미관측 기간의 성능·운영 적합성·모델 승격을 뜻하지 않는다.

## 실패 가능성 및 독립 재검산 권고

- **비정상화/경로 누락:** stage2/3 denominator에 실제 결과만 적용하거나 일부 triple만 만들면 전체 Q 질량이 잘못된다. 예측 파이프라인은 가능한 prefix마다 risk set을 만들어야 한다.
- **유출 위험:** 실제 평가 1·2착마를 빼서 후보별 probability를 계산하면 안 된다. labels 사용은 training objective와 scoring lookup으로 한정한다.
- **온도/역온도 혼용:** 기존 optimizer 범위는 T 단위다. β 최적화로 옮길 때 bounds를 역수 변환하고, 보고서에는 둘 다 같은 온도 표기로 환산해 기록한다.
- **stage 최적화 실패:** 경계 도달, non-finite logsumexp, stage별 score variance 결핍, 평탄 optimum, `N=3`-only stage3 위험, 또는 독립 구현 값 불일치를 PASS로 처리하지 않는다.
- **결과 과해석:** 보정 sample NLL의 비악화는 일반화 증거가 아니며, Q의 정합성은 PL의 score-only 선택독립 가정이 옳다는 증거가 아니다. 평가 기간은 재사용 개발자료다.
- **결정 안정성:** 세 온도는 동일 score/race source, 동일 roster 및 정답, 동일 strict top3 cohort, 동일 PLC 1,743 및 나머지 6 pool 1,779 분모, 동일 exclusion ledger에 고정한다. 기존 규칙 계약이나 source, 운영 기준은 변경하지 않는다.

추후 허가된 실행 전 독립 검산자는 원 구현 코드를 가져다 부르는 방식만으로 확인하지 말고 별도 작은 reference calculation을 작성해야 한다. 서로 다른 세 온도로 roster 4–5두의 모든 `N(N−1)(N−2)` 경로를 계산해 `ΣQ=1`, 주변합 1/2/3, 각 pool 사건합과 cross-pool identity를 검사한다. 같은 T 세 개에서는 이전 common-T reference와 모든 triple이 허용 오차 내 일치하는지 확인하고, score 상수 이동이 Q에 영향 없는지 검사한다. synthetic N=3 counterexample로 ticket 확률순위 변화 및 T3 비식별성을 확인한다. 마지막으로 calibration likelihood가 독립 stage 1차원 합과 같은지, 후보 입력/온도 선택에 2024–2026 결과가 섞이지 않았는지 source/hash·코드 경계로 확인해야 한다. 이 검토는 해당 실행이나 코드를 작성·실행하지 않았다.

## 참조 계약

- [선행 joint-wager experiment plan](../../20261022_joint_wager_baseline_v1/experiment/PLAN.md) — 고정 F1_STYLE6 점수, 시간 분할, NLL/Brier 및 bootstrap 계약.
- [선행 7승식 규칙 계약](../../20261022_joint_wager_baseline_v1/rules_contract/README.md) — 승식 사건합, PLC opening-field 분기, unknown/제외 분모, 점수 정의 및 시장 해석.
- [선행 supervisor decision](../../20261022_joint_wager_baseline_v1/supervisor/DECISION.json) — 공통 `T=1.1837152381349905`, TRI gate 및 이전 WIN 손실 악화 상태.
- [선행 experiment results](../../20261022_joint_wager_baseline_v1/experiment/README.md) — 실행된 결과 설명·표본 범위·선택 진단. 숫자를 여기서 다시 산출하지 않았다.
