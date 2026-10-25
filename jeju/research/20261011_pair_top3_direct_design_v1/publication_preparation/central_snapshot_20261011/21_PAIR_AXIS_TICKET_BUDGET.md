# 제주 저장 Top3 분포의 축 고정·조합 예산 비교

**판정:** 저장된 무순서 exact Top3 분포를 바탕으로 선택 정책만 비교한 회고 연구다. 전체 코호트에서 최대 joint-pair 축의 같은 예산 티켓 적중이 unrestricted 선택보다 안정적으로 높다는 근거는 없었다. 새 모델 학습이나 운영 반영은 없다.

## 질문과 자료

각 경주에서 pair axis는 두 말이 실제 Top3에 함께 드는 사건이고, single axis는 한 말이 Top3에 드는 사건이다. pair ticket의 나머지 말은 실제 Top3 집합의 남은 구성원이며 3위 착순을 뜻하지 않는다. exact Top2 pair와 승리 확률은 unordered Top3 분포에서 식별되지 않는다. exact Top2 결과는 선택 후 실제 라벨로만 보조 집계했다.

분석은 저장된 `matched_baseline`과 `candidate` 무순서 분포를 각각 사용했다. 2024-01-05~2026-09-19의 정상완주 완전편성 1,779경주, 17,412출전, 269경주일이며 2026년은 부분연도다. 이전 연구에서 이미 살펴본 경주이므로 독립 미래검증이 아니다. 두 arm 중 어느 쪽도 이 결과만으로 선택하지 않는다.

다섯 정책을 K=3·4에서 모두 보고했다. 주 비교는 `maximum_joint_pair`와 같은 K의 `unrestricted_top_k`이며, 전체 코호트 적중률 차이는 다음과 같다.

| Arm | K | Maximum joint pair | Unrestricted | 차이 | 날짜 paired 95% 구간 |
|---|---:|---:|---:|---:|---:|
| matched baseline | 3 | 236/1,779 | 233/1,779 | +0.17%p | −0.46~+0.79%p |
| matched baseline | 4 | 294/1,779 | 298/1,779 | −0.22%p | −1.18~+0.68%p |
| candidate | 3 | 246/1,779 | 248/1,779 | −0.11%p | −0.83~+0.61%p |
| candidate | 4 | 292/1,779 | 302/1,779 | −0.56%p | −1.51~+0.39%p |

모든 구간이 0을 포함했다. 최대 pair 축은 candidate 422/1,779, baseline 429/1,779에서 실제 Top3에 함께 들었다. Pair가 적중한 경주 중 선택 ticket의 조건부 완성은 candidate K=3에서 246/422, K=4에서 292/422였고, baseline은 각각 236/429와 294/429였다. pair miss와 completion miss는 별도 분모로 집계했다.

Single-anchor 축은 candidate 1,020/1,779, baseline 1,023/1,779에서 실제 Top3에 들었다. 이 축이 적중한 경주 중 K=3 ticket 완성은 각각 247/1,020, 233/1,023이었고, K=4는 300/1,020, 296/1,023이었다. 따라서 축 적중률은 전체 조합권 적중률과 다르다.

## 고정 확률 부분집합

저장된 single-anchor 확률 ≥0.8 부분집합은 candidate 55/1,779경주(3.09%), baseline 60/1,779경주(3.37%)였다. 축 자체는 각각 45/55와 48/60경주에서 실제 Top3에 들었다. 두 arm 모두 이 부분집합에서 single-anchor와 unrestricted의 티켓 목록이 K=3·4 모두 완전히 같았고, 따라서 티켓 적중 수도 candidate K=3 11/55·K=4 12/55, baseline K=3 9/60·K=4 12/60으로 같았다. 이 구간은 과거 자료에서의 축 성공을 기술하지만, 축 고정으로 티켓을 바꾼 효과를 보여 주지 않는다. ≥0.6 부분집합은 684경주와 693경주였고, 같은 subset 내 single-anchor 대비 unrestricted 적중 차이는 K=3에서 양쪽 0건, K=4에서 각각 −1건과 +1건이었다. 이는 사후 과거 subset 요약이며 미래 coverage를 보장하지 않는다.

저장된 baseline은 additive unary energy를 사용하므로 pair 축 정책 일부가 같은 선택을 반복한다. 전 코호트에서 maximum-joint pair, top-two marginal pair, K-ticket-mass pair 축은 baseline 1,779경주 모두 같았고, baseline single-anchor K=3 티켓은 unrestricted K=3과 모든 경주에서 같았다. 이를 독립적인 정책 투표로 세지 않는다.

## 범위와 연결

이 연구는 전용 pair 모델이나 ordered-finish 모델을 학습하지 않았다. 고정 pair K=6은 7두 편성 경주에서 티켓 6장을 만들 수 없어 제외했으며, unrestricted K=6은 기존 결과 407/1,779 및 423/1,779의 parity 확인으로만 보존했다. exact Top2 결과, 배당 가치, 수익 또는 운용 준비를 주장하지 않는다.

다음 검증 가설은 단일 축 신뢰도 보정과 조건부 companion 두 마리 학습을 시간순 OOF 및 새 기간에서 평가하는 것이며, 아직 검증되지 않았다.

- [원 연구 및 전체 결과](../20261010_pair_axis_v1/README.md)
- [독립 검토 메모](../20261010_pair_axis_review_v1/REVIEW_MEMO.md)
- [전수 독립 검증 receipt](../20261010_pair_axis_review_v1/outputs/independent_validation_receipt.json)
- [고정 cutoff 보충 검증 receipt](../20261010_pair_axis_review_v1/outputs/supplemental_fixed_cutoff_receipt.json)
- [기존 축+조건부 동반 학습 연구](12_AXIS_COMPANION_PAIRS.md)와 [joint relationship 연구](19_JOINT_RELATIONSHIP.md)는 질문과 산출물이 다른 별도 연구다.

상태: `retrospective_no_fit_policy_comparison_completed_no_promotion`. 모델 학습, 기존 말 평가, DB, 운영 등록부와 예측 체계는 변경하지 않았다.
