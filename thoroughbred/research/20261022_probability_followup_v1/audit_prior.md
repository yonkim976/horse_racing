# 선행 대안 감사: 확률·순서·쌍 목표

작성: 2026-10-22. 기존 연구 문서, 코드, 저장된 결과·검증 보고서만 읽었다. 이 감사에서는 학습, 재평가, 운영 변경을 하지 않았다. 2024~2026 성적은 이미 반복 검토된 후향 자료이며 독립 신규 시험으로 보지 않는다.

## 결론

Top2 전용 학습은 확률 점수의 개선 신호를 보였지만 복승 적중률 우위를 확정하지 못했다. 별도 조건부 동반쌍 모델과 전개 stack은 기존 대조를 넘지 못했다. 현재 EL89 trio에 89입력 Top2 head를 조건부로 연결하는 안은 기존의 전-field pair 점수나 고정축 동반쌍 모형을 반복하는 대신, 이미 유망한 EL89의 Top3 집합분포를 보존하고 그 집합 안의 착순만 복승 목표에 맞게 재배분하는 제한 가설이다.

이 안은 축Top3와 복연 확률을 구조적으로 고정한다. 따라서 축이나 복연의 추가 개선을 시험하지 않으며, 그 지표들은 불변성·비악화 검증으로만 다룬다. 새 목표는 복승 pair 확률과 순서분포이며, 89입력 Top2 학습이 실제 복승 적중·확률품질을 올리는지는 미검증이다.

## 이미 확인된 대안

| 대안 | 저장된 결과 | 감사 해석 |
|---|---|---|
| 22→53/55입력 및 Top2 목표 분리 | [20261012 inner/front retention 결과](../20261012_inner_front_retention_v1/README.md)에서 Top2 라벨 55입력은 baseline22 Top2보다 Brier −0.001193 (95% 구간 −0.001628~−0.000743). 복승1은 12.38%→12.42%, paired 차이 +0.042%p (−0.749~+0.912); 복승3 +0.521%p (−0.437~+1.506). | target2 전용 입력의 확률품질 신호는 있으나, 적중률 개선을 확정하지 못했다. 복승 전용 모델을 만드는 접근을 완전히 배제하지 않지만 이미 비슷한 목표분리 실험이 있어 같은 55 입력을 되풀이할 이유는 없다. 55 대 full103 비교도 full103 대체 근거가 아니었다. |
| 축 고정 조건부 동반 pair 학습 | [20261009 axis companion pairs](../20261009_axis_companion_pairs_v1/README.md), 구현은 [run.py](../20261009_axis_companion_pairs_v1/run.py). 같은 축에서 후보군을 넓힌 점수합 6개는 27.01%·1,296경주, 조건부 구간/전개 pair 학습은 26.69%·1,281경주였다. 기존 좁은 축+상대4두 정책 대비 후보군 확장은 효과가 있었으나, 그 후보군 안에서 pair 학습은 점수합보다 낮았고 조건부 NLL/Brier도 악화했다. | 축을 고정하고 상대쌍을 학습하는 방식은 직접 시험되었다. 확대 후보군 효과와 쌍 학습 효과를 혼동하면 안 된다. 기존 105열 pair 모델 반복은 우선순위가 낮다. |
| 말별 입력·전개 예측 stack | [20261009 section/style/finish](../20261009_section_style_finish_v1/README.md), 이어진 [20261004 pace/finish stack](../20261004_pace_finish_stack_v1/README.md)와 [57J joint pace stack](../20261021_busan_joint_pace_stack/README.md). 부산의 20261004 성적에서 기록→이력 직접 입력은 삼복6조합 25.91%→27.74%였으나, 시간순 전개예측을 추가한 값은 27.49%로 감소했다. 57J에서는 B 축/복승 58.81%/10.78%, D 직접 이력 60.27%/11.18%, I 전개예측 60.27%/11.34%, J 공동 두수 예측 60.02%/11.44%였다. 주 pair 구간은 0을 포함하고, 2026 J 복승은 B 대비 −5경주였다. | 이력 직접 입력의 지역·목표별 신호와 stacking의 한계가 이미 관찰됐다. 더 많은 전개 보조확률을 묶는 실험을 다시 하는 것보다 현 EL89/Top2 조건부 factor의 역할을 분리해 보는 편이 새 질문이다. |
| 별도 축 교체/필터/선택기 | [20261012 joint axis guard](../20261012_joint_axis_guard_v1/README.md), [20261013 axis switch learning](../20261013_axis_switch_learning_v1/README.md). 필수조건 guard는 103축 입상 60.83%→60.58%였고, 2026에서 특히 악화했다. 별도 득실 학습은 122 대비 축 +0.292%p (95% −0.266~+0.852), 복승1 +1경주, 축복승3 −3경주였다. 로지스틱은 61.12%, 작은 트리는 60.70%였다. | 하드 게이트는 부정적, 교체 classifier도 작은 불확실 신호다. 현재 축 순위를 바꿔 교체하는 새 policy를 추가할 근거는 없다. |
| 직접 pair 특징 상호작용 | [20261022 결과 감사](../20261022_probability_comparison_v1/audit_results.md)와 [확률 비교](../20261022_probability_comparison_v1/README.md). full103_pair의 set/trio log loss 변화는 −0.00386 (95% −0.00603~−0.00179)로 개선했으나 축·복승·복연 선택 적중 차이 구간은 모두 0을 포함했다. front pair 계수는 6개 교정 구간 모두 음수, G3F pair 계수도 모두 음수, G1F는 대부분 양수이나 한 구간에서 음수였다. | 제한 상호작용이 분포 점수에는 신호를 보였지만 티켓 적중으로 이어지지 않았다. 세 계수의 조건부 방향도 일관되지 않아 pair 특성을 더 늘릴 이유가 없다. |
| 전체 pair 확률을 이용한 선택 정책 | [연구58 결론](../conclusions/58_THOROUGHBRED_PROBABILITY_COMPARISON.md)은 full103에서 축 고정 복승3 대신 전체 pair 확률 상위3을 고른 정책이 1,347→1,405경주(+58, +1.21%p, 95% +0.59~+1.92)라고 기록한다. | 모델 입력의 개선이 아니라 후향 선택정책 결과다. 복승 선택정책 비교로 분류하고 모델 학습 효과나 수익률로 확대 해석하지 않는다. 최종 정책 검증은 별도 확인 대상이다. |
| ordered Top3/정확3착 진단 | [20261003 baseline](../20261003_baseline_v1/README.md)는 ordered Top3 NLL을 주 목표로 하고 순서공동분포에서 축 marginals를 계산한다. [20261010 third-place hypothesis](../20261010_third_place_hypothesis_v1/README.md)는 실제 3착 Top5 포착 62.22% 대 2착 68.41%, 정확3착 한 마리 적중 14.39%를 보고했다. | 3착 포착 병목은 확인됐으나 별도 third-place head는 학습하지 않았다. ordered NLL은 LambdaRank 실험을 뜻하지 않는다. |
| 위험 보정과 calibration | [20261010 axis signal calibration](../20261010_axis_signal_calibration_v1/README.md)는 signals−simple calibration Brier −0.000706 (95% −0.001608~+0.000174), log loss −0.001459 (−0.003381~+0.000432)였다. 원축 순위는 변하지 않아 적중률도 바뀌지 않았다. | 소규모 calibration 신호는 탐색적이며 독립 미래검증이 없다. 평가자료의 전체 평균 pair 일치는 합계 제약 항등식이며, bin ECE도 bin이 너무 크거나 한 bin에 몰리면 둔감할 수 있다. |

관련 기초 결론: [57G](../conclusions/57G_BUSAN_ALL_DISTANCE_PROFILES.md), [57H](../conclusions/57H_BUSAN_PROFILE_GAIN_LOSS.md), [57I](../conclusions/57I_BUSAN_LEADER_PACK_OUTCOMES.md), [57J](../conclusions/57J_BUSAN_JOINT_PACE_STACK.md), [57K](../conclusions/57K_BUSAN_LATE_SURVIVAL_PAIRS.md). 57K는 특히 실제 선두권/동시 종반 생존 관계가 사후 관측임을 분명히 하고, 독립 pair 학습의 추가 적중 이득과 전 연도 일관성을 확인하지 못했다.

## baseline22 Top2 대 새 89입력 Top2 factor

기존 baseline22 Top2는 연구용 22입력 Top2 binary score head를 저장해 재사용한다. 지역×평가연도 6개 모형의 score는 [runner_predictions.parquet](../20261009_section_style_finish_v1/outputs/runner_predictions.parquet)의 `target==2`, `variant=='baseline22'` 행에 있다. 저장 모형과 메타데이터는 `outputs/finish_models/2_baseline22_{meet}_{year}/{model.txt,metadata.json}`이며 실행·재현 코드는 [section/style/finish run.py](../20261009_section_style_finish_v1/run.py)다. [pair budget run.py](../20261009_pair_trio_budget_v1/run.py)의 `pair_data()`와 `distributions()`가 각 비순서 2두 조합의 점수합을 이전 연도 temperature로 정규화해 복승분포 합 1을 확인한다. 이 모형은 후보 전체에서 무조건부 Top2 pair set을 선택하는 대조다.

새 89입력 Top2 factor는 additive89 입력으로 같은 Top2 label을 예측하는 신규 6개 regional/year heads를 뜻한다. 그 점수를 기존 무조건부 pair set softmax로 독립 출력하거나 주변확률처럼 섞지 않는다. 고정한 각 삼두 T 안에서는 `softmax(-s2_k/t2)`로 k가 3착일 조건부 확률을 두고, 남은 i,j의 순서는 F-score 차이의 logistic 분포로 둔다. 그러면

`P(i→j→k) = q89({i,j,k}) × P(k is third | {i,j,k}) × P(i before j | {i,j})`.

각 trio 안의 여섯 순서가 합쳐 `q89(T)`가 되므로 전체 ordered distribution 합은 1이다. Top3 runner marginals 및 QPL pair marginals는 기존 q89에서 유도한 그대로 유지되고, QN은 각 trio에서 세 번째 말을 고르는 조건부 점수에 따라 달라진다. 즉 baseline22 Top2는 저장된 old-feature full-field 복승분포 대조이고, 새 89입력 Top2는 EL89 삼두분포 안에서만 역할을 분담하는 factor다. 두 결과는 동일한 의미의 확률 head가 아니며, 평가도 그 차이를 반영해야 한다.

기존 target2 temperature는 전체 pair set 확률을 교정한 값이다. `softmax(-s2)`의 3-way within-trio 조건부 분포와 calibration target이 다르므로 자동 전용하지 않는다. 새로운 `t2`, `tF`는 각 평가연도보다 이전의 시간외 예측에서 조건부 third NLL과 top-two order NLL로 각각 한 값만 사전 고정해야 한다. 평가연도 결과로 온도, 모델, threshold를 조정하지 않는다.

## 후속 연구 우선순위

1. **한 번의 제한된 prospective/새 코호트 비교:** q89를 고정하고 (a) 현재 F-order factor, (b) baseline22 Top2 conditional-third factor, (c) 신규 89 Top2 conditional-third factor를 비교한다. 신규 head는 지역×연도 6개만 두고, 모델 수·입력·온도 fitting·tie rule·중단 기준을 평가 결과를 보기 전에 고정한다. 같은 2024~2026 결과는 새 시험으로 다시 부르지 않는다.
2. **목표 범위를 정확히 한정:** 축Top3와 QPL1/3은 설계상 보존된다. 주 성과는 QN1/3 적중률뿐 아니라 전체 non-ordered QN probability의 Brier/log loss, 선택 union 보정, paired 연도별 차이로 평가한다. 복연 예상 적중수와 하나 이상 적중확률을 구분한다. 축·QPL은 변화가 없는지 분포 수준으로 검증하되 개선 주장에는 사용하지 않는다.
3. **공동분포 검증:** trio별 순서 여섯 질량 합이 `q89(T)`와 같은지, 경주별 ordered sum=1, win/top2/top3 합=1/2/3, QN 합=1 및 QPL 합=3인지 확인한다. tie, 결측, 비입상 rank, 동일 점수 처리도 독립 enumeration으로 검증한다. 학습·calibration·evaluation의 대상 경주가 시간순으로 분리되고 입력시점이 경주 전인지 확인한다.
4. **전향자료를 쓰기 전에는 판단 보류:** 2024–2026은 반복된 개발자료이며 2026 서울·부산 통합의 종료일은 9월20일이다. 출발 명단과 현재 부담중량의 사전 timestamp도 미확인 한계다. 모델과 정책, 후보 명단, 계수를 freeze하고 진짜 새 코호트를 한 번 평가하는 계약이 선행되어야 한다.

`thoroughbred/research`의 코드·텍스트 검색에서 `lambdarank`/`rank_xendcg` objective 구현이나 그에 대한 검증 산출물은 찾지 못했다. 현 horse heads는 Top3/Top2 binary 점수, Top3 trio distribution, 조건부 순서분포를 사용한다. 따라서 LambdaRank를 “기존에 실패한 대안”으로 간주할 근거는 없으며, 그것을 추가하면 새 objective 실험이다. 같은 후향 기간에서 후보를 늘려 비교하기보다 현재 factor 가설의 고정된 미래 검증을 우선한다.
