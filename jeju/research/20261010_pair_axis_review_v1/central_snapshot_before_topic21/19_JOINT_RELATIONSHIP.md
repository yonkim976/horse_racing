# F1_STYLE6 공동 입상관계와 최대 6조합 비교

**판정:** 저장된 F1_STYLE6 말 점수와 말별 평가를 유지한 채 관계항을 더한 후향 연구다. 사전 성능 게이트는 실패했고 운영 승격은 없다.

## 질문과 자료

기존 F1_STYLE6 점수는 그대로 두고, 말 쌍 관계항을 추가해 전체 무순서 정확 Top3 조합을 정규화하고 경주당 최대 6개 조합을 고르는 실험을 했다. 평가 코호트는 2024-01-05~2026-09-19의 1,779경주, 17,412출전, 269경주일이며 2026년은 부분연도다. 과거 개발 자료를 재사용했으므로 독립 미래 검증은 아니다.

주 비교는 같은 원시점수와 같은 H2 보정 기간을 사용한 매칭 점수 전용 대조군과 관계 후보였다. 시간 분할과 T−2 경계는 고정 계획을 따랐다. 기존 저장된 F1_STYLE6 점수·확률은 변경하지 않았다.

## 주 결과

| 결과 | 매칭 대조군 | 관계 후보 | 후보−대조군 | 날짜 paired 95% CI | 게이트 |
|---|---:|---:|---:|---:|---|
| 최대 6조합 정확 Top3 적중 | 407/1,779 (22.8780%) | 423/1,779 (23.7774%) | +0.8994%p | [−0.1137, +1.8997]%p | 실패: 하한이 0 이하 |
| 정확 Top3 집합 NLL | 4.287786 | 4.288421 | +0.000635 | [−0.004728, +0.006277] | 실패: 상한이 0 초과 |

날짜 단위 paired bootstrap은 2,000회, seed 20261008이다. 사전 규칙은 적중률 차이의 CI 하한이 0보다 크고 집합 NLL 차이의 CI 상한이 0 이하인 경우만 통과로 정했다. 두 조건 모두 충족되지 않아 연구 신호 게이트는 false다. 점추정의 적중 증가는 불확실하며 결합 NLL은 평균상 후보가 조금 나빴다.

## 검증과 해석 범위

C는 A의 계산 helper를 가져오지 않고 잠금 원천에서 H1 표준화·계수 목적함수와 gradient, H2 온도 stationarity, 1,779경주의 전체 triple 분포와 주변확률, 지표·날짜 bootstrap, 정확한 stable top-six 선택을 다시 계산했다. 저장 결과와 전량 대조, 순서·라벨 교란 불변성 검사는 PASS했다. 39개 잠금 원천 해시는 검토 중 바뀌지 않았다. 검증 PASS는 계산 재현성 판정이며 성능 게이트 PASS를 뜻하지 않는다.

이 연구는 사후 완전 roster와 과거 스타일 요약을 사용했으며 과거 공표 시각이나 당시 확정 출전 명단을 재구성하지 않았다. 관계 계수를 인과적 궁합으로 해석하거나 미래 성능으로 일반화할 수 없다. 말 점수·저장 확률·운영 모델·DB·운영 등록부는 바뀌지 않았다.

## 원본과 검증 기록

- [설계·코드·전체 결과](../20261010_joint_relationship_v1/README.md)
- [상세 결과와 제한](../20261010_joint_relationship_v1/RESULTS_AND_LIMITATIONS.md)
- [고정 산출물 manifest](../20261010_joint_relationship_v1/ARTIFACT_MANIFEST.json)
- [독립 원천 재구성 receipt](../20261010_joint_relationship_review_v1/outputs/postfit_independent_validation/independent_postfit_validation.json)
- [최종 검토 receipt](../20261010_joint_relationship_v1/outputs/root_final_review.json)
- [중앙 발행 receipt](../20261010_joint_relationship_review_v1/central_publication_receipt.json)


## gained/lost 후속 진단 (2026-10-10)

동일한 1,779개 후향 경주에서 baseline hit 407건과 candidate hit 423건의 차이는 +16건(+0.90%p)이었지만, 날짜 단위 95% 구간 [−0.11, +1.90]%p가 0을 포함해 원 성능 gate는 계속 실패다. 50 gained·34 lost·373 both-hit·1,322 both-miss이며, 무순서 top-six 집합은 1,077경주에서 달랐다. 이는 별도 holdout 검증이 아니다.

조건별 원시 차이는 하나의 안정된 규칙을 보이지 않았다. 거리별 net은 1000m 508경주에서 −1, 1110m 482경주에서 +7, 1200m 262경주에서 +5, 1300m 63경주에서 +5였다. 연도별 전체 net도 2024년 −3, 2025년 +15, 2026년 9월 19일까지 +4로 달랐다. 연도×거리 및 연도×수분 교차표는 전체 분모를 나누는 기술표이며, 조건 선택이나 효과 확증에 쓰지 않는다. 84개 gained/lost는 결과를 확인한 뒤 선택한 사후 집합이다.

true-set과 경계 경쟁 조합의 항별 에너지 차이는 행별 대수 분해로 재현된다. gained/lost 그룹에서 baseline 점수 차와 관계항 차의 평균 방향은 반대였지만, 이는 결과로 나눈 표본의 상관된 11개 항 분해이며 인과 기여나 support-count 정보 품질을 증명하지 않는다. 다음 검증 가설은 미관측 기간에서 style-mean 3항과 support-count 3항을 고정 ablation/shrinkage로 비교하고, 거리별 규칙 대신 충분한 지원의 연도×거리 구성을 pooled/shrunken 방식으로 시험하는 것이다. 같은 이벤트 체중·수분 등은 예측 시점 가용성이 확인되지 않은 사후 context다. 운영 모델, 확률, DB, fitting은 변경하지 않았다.

세부 결과와 수정 표는 [후속 분석 README](../20261010_joint_gain_loss_v1/README.md), [feature/unit이 명시된 실제 Top3 표](../20261010_joint_gain_loss_v1/outputs_followup_addendum/actual_top3_context_summary_corrected_v2.csv), [A 고정 manifest](../20261010_joint_gain_loss_v1/ARTIFACT_MANIFEST.json), [독립 보충 검토](../20261010_joint_gain_loss_review_v1/outputs/independent_supplemental_verification_receipt.json)를 따른다. 최초 오류 `all_1779` 표와 feature 이름이 빠진 첫 정정표는 보존되었으나 superseded 상태이며 해석에 사용하지 않는다.
