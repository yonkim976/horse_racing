# 두 말 동시 Top3 직접 pair 모형 평가

## 최신 후속: H1 기수 ID categorical effect 추가

저장 F1_STYLE6 말 점수, 기존 20개 style pair basis와 저장된 최근 365일 기수 이력 scalar를 유지하고, 각 평가 fold의 H1에서 관측한 공식 사건 기수 ID 39개 categorical main effect를 추가했다. 기존 21개 계수와 ID 효과를 함께 적합했다. ID의 숫자 크기와 이름은 입력으로 쓰지 않았고, H1 밖 ID의 categorical 기여는 0으로 두었다. H1 category vocabulary는 fold마다 별도로 만들었으며 rare ID pooling은 하지 않았다. H1 최소 support는 52 eligible starts다.

평가기간은 2024-01-05~2026-09-19이며 1,779경주·269경주일·17,412출전·76,848개 무순서 pair다. 2026년은 부분연도이고, 이미 반복 사용한 후향 개발 자료다.

| 저장 비교 방식 | 동시입상 | 경주 | 동시입상률 |
|---|---:|---:|---:|
| 기수 ID categorical 후보 | 438 | 1,779 | 24.62% |
| 기수 최근 이력 scalar 후보 | 429 | 1,779 | 24.11% |
| 확장 H1 직접 pair | 427 | 1,779 | 24.00% |
| 이전 직접 pair | 426 | 1,779 | 23.95% |
| 원시 F1_STYLE6 점수 상위 2두 | 429 | 1,779 | 24.11% |
| 저장 F1_STYLE6 P(Top3) 상위 2두 | 429 | 1,779 | 24.11% |
| 기존 joint 주변확률 상위 2두 | 434 | 1,779 | 24.40% |
| 기존 joint 최대 pair | 422 | 1,779 | 23.72% |
| 기존 matched 최대 pair | 429 | 1,779 | 24.11% |

사전 지정 **primary 추가 효과**는 저장 기수 scalar 후보 429회 대비 +9회, **+0.505902%p**였다. 같은 경주일 bootstrap 95% CI는 **[+0.112673,+0.903496]%p**로 하한이 0보다 높아 primary gate를 통과했다. 두 후보의 선택 pair가 달랐던 50경주 중 새 후보는 11승·2패·37동률이었다.

사전 지정 **secondary raw Top2 gate**도 점추정은 +0.505902%p지만, raw F1_STYLE6 Top2 역시 429회이고 두 선택 집합은 같지 않다. 날짜 bootstrap 95% CI **[−0.112488,+1.106333]%p**의 하한이 0보다 낮아 secondary gate는 통과하지 못했다. 따라서 primary 비교의 추가 효과는 확인됐지만, 두 사전 gate를 함께 요구하는 전체 우세 판정은 미확정이다. primary와 secondary의 점추정이 같다는 이유로 두 CI나 판정을 합치지 않는다.

연도별 후보 적중은 2024·2025·2026 부분연도에 155·157·126회였고, 저장 scalar 후보는 153·150·126회였다. 2026년에는 증가가 없었다.

## 확률 진단

전체 pair에서 ID 후보의 Brier/log loss는 **0.062868/0.236251**, 저장 scalar 후보는 **0.062911/0.236507**로 ID 후보가 조금 낮았다. 경주별 선택 pair에서는 ID 후보가 **0.177988/0.538109**, scalar 후보가 **0.175132/0.531468**로 더 높았다. 선택 결과의 적중 gate와 전체 pair 확률 품질, 선택 pair 확률 품질은 서로 다른 진단이며 한 쪽으로 다른 쪽을 대체하지 않는다. 세부 reliability·거리별 결과와 bootstrap schedule은 원본 report에 보존했다.

## 모형·해석·한계

각 pair에 대한 후보는 고정된 F1_STYLE6 기반 점수와 20개 style pair basis, rolling scalar를 사용하고, H1-only 기수 ID 효과를 표준화 basis로 추가했다. 각 fold에서 H1만으로 39개 vocabulary와 moments를 만들고 `W_r=(u_r−K*pi_r)/sigma_r`로 입력했다. 경주 균등 pair BCE와 표준화 계수 unit ridge를 사용했으며 별도 intercept는 없다. 후보 pair 계수는 H1에서 3회 공동 적합했고 H2에서 3개 Platt map을 만들었다. 말 모델은 재학습하지 않았고 저장 baseline·비교 selector도 다시 적합하지 않았다.

`theta`에서 환산한 `alpha`는 관측된 기수 ID와 배정 말의 질이 함께 섞인 weighted-centered 연관성이다. 이를 순수 기수 능력이나 인과효과로 해석하지 않는다. 원시 효과의 유효 ridge 강도는 ID별 `sigma`와 support에 따라 다르다. 현재 event jockey snapshot의 과거 최초 공개·변경 시각은 확인되지 않았다. 대상은 정상완주 완전편성 cohort이며, 반복 개발기간은 독립 미래 holdout이 아니다. 말별 저장 평가는 유지했지만 이 비교는 두 말 동시 Top3 pair 선택에 대한 제한된 실험이다.

독립 C 검토는 소스·범주, 60계수 적합, 76,848개 pair 예측, 날짜 bootstrap·확률 품질 보고를 재계산해 모두 PASS했다. 검토는 저장 예측·CI의 재현을 확인했으며 독립 미래 holdout을 만들지는 않는다. 현재 결론은 연구 후보 보존이며 운영 반영은 없다.

## 이전 결과 보존

직전 기수 최근 이력 scalar 후속은 429/1,779회로 확장 H1 직접 pair 427회보다 +0.112423%p였다. 95% 날짜 CI [−0.339568,+0.569492]%p로 추가 효과가 확인되지 않았고, raw score Top2 429회와도 동률이었다. 이번 ID categorical 실험은 그 rolling scalar 입력을 유지한 채 H1-only ID effect를 추가 비교한 후속이다.

그 이전 H1 확장 연구는 2,147/2,818/3,458경주로 학습창을 늘렸지만 427회였고, 원시 Top2 429회 대비 −0.112423%p, CI [−0.340716,+0.056917]%p로 개선이 확인되지 않았다. 최초 직접 pair는 426회였다. 이전 원본·검토 결과는 각각의 연구 경로에 보존했다.

## 재현 자료

- [최신 기수 ID categorical 연구](../20261012_pair_jockey_id_v1/README.md), [공식 report](../20261012_pair_jockey_id_v1/outputs/REPORT.json), [산출물 manifest](../20261012_pair_jockey_id_v1/ARTIFACT_MANIFEST.json)
- [독립 검토](../20261012_pair_jockey_id_review_v1/README.md), [예측·보고 검토 receipt](../20261012_pair_jockey_id_review_v1/independent_prediction_audit.json), [검토 artifact manifest](../20261012_pair_jockey_id_review_v1/ARTIFACT_MANIFEST.json)
- [이전 기수 최근 이력 scalar 비교](../20261012_pair_jockey_basic_v1/README.md) 및 [독립 검토](../20261012_pair_jockey_basic_review_v1/README.md)
- [직전 H1 확장 연구](../20261011_pair_top3_oos_expansion_v1/README.md), [직전 독립 검토](../20261011_pair_top3_oos_expansion_review_v1/README.md)
- [최초 직접 pair 연구](../20261011_pair_top3_direct_v1/README.md), [기존 설계·원천 감사](../20261011_pair_top3_direct_design_v1/SOURCE_AUDIT.md)

## 2026-10-13 후속: 적중·미적중 경주의 당첨배당

기수 ID 후보의 저장 pair 선택을 유지하고, 배당이 보유된 2025-01-03~2026-09-19의 1,142경주를 연결했다. 두 말 모두 Top3인 283경주의 실제 당첨 삼복승 배당은 평균 20.106배·중앙값 12.9배, 미적중 859경주는 평균 89.103배·중앙값 39.9배였다. 평균 차이는 68.997배이며 미적중군이 4.432배 높다. 실제 당첨 복승 배당의 평균은 각각 11.026배와 30.811배다. 적중한 선택 pair 자체의 복연승 배당 평균은 2.743배다.

2024년 637경주는 조합 배당 미보유로 제외했고 결측을 0으로 대체하지 않았다. 2026년은 부분연도다. 적중 분류는 두 말 동시 Top3이며 삼복승 3두 적중이나 복승 Top2 적중이 아니다. 위 삼복·복승 값은 해당 경주의 실제 당첨조합 배당을 비교한 사후 기술통계이며, 우리 조합의 실현 배당·수익률을 뜻하지 않는다. 말 평가·모델·운영 기준은 그대로 유지했다. [분석·원천 검증](../20261013_pair_payout_audit_v1/README.md).
