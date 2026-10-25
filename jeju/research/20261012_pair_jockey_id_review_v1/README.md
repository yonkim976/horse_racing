# 독립 검토: pair jockey ID 효과

승인된 60열 후보(기존 21열 + H1-only 기수 ID 39열)의 소스, 적합, 평가 예측과 보고 수치를 재구성했다. 적합·예측·보고 파일은 변경하지 않았다. 검토 계산은 `.venv/bin/python -B`로 실행했으며 추가 최적화는 호출하지 않았다.

소스·범주 검토와 60열 적합 검토, 76,848개 pair 예측 검토가 모두 PASS다. 기존 20개 말 pair 모멘트와 rolling 21번째 모멘트는 세 fold 모두 정확히 유지됐다. H1에서 ID 39개가 fold마다 관측됐고 최소 지원은 52회다. 범주 `μ/π/σ` 직접 pair 열거 오차는 `1.16e−14` 이하였다. unknown ID 두 마리의 기여는 정확히 0이며 known/unknown pair는 알려진 기수 효과만 남긴다.

기존 21열과 ID 항을 함께 적합한 60계수 기울기·손실 및 H2 양의 기울기 Platt 보정은 저장값과 독립 계산에서 일치했다. 전체 평가 pair 76,848개의 ID 점수 최대 오차는 `1.16e−14`, 확률 최대 오차는 `2.45e−15`였다. 기존 선택기와 비교기 열은 모두 보존됐다. 별도로 재계산한 적중, 날짜 bootstrap, Brier/log loss, reliability, probability-mass와 threshold 지표는 저장 보고서와 일치한다. bootstrap은 기존 int32 2,000×269 일정(SHA `d141b0c3…eadaccbd`)을 직접 로드했다.

ID 후보는 438/1,779회, 저장 rolling 후보는 429/1,779회 적중했다. 사전 지정 primary 비교는 +0.506%p, paired 날짜 bootstrap 95% CI +0.113~+0.903%p로 통과한다. raw Top2 대비 secondary 비교도 점 추정은 +0.506%p지만 CI −0.112~+1.106%p라 0을 포함해 통과하지 않는다. 따라서 두 사전 gate가 모두 통과한 결과는 아니다.

정확도 개선과 함께 선택 pair의 확률 품질은 저장 rolling 후보보다 나빠졌다. 선택 pair Brier는 0.17513에서 0.17799로, log loss는 0.53147에서 0.53811로 증가했다. ID 항 결과는 기수 능력이나 인과효과로 볼 수 없다. 기수 배정과 마방·말의 연관, event snapshot 최초 공개시각 부재, 반복 개발 평가자료 및 부분연도 2026이라는 한계가 있다.

모든 downstream 결과와 이 검토의 source 감사는 최종 승인된 `SOURCE_PREFLIGHT.json` SHA `be743852ee0a5fd8c4a2b5fdae93c90b8bfcec0f2263fdbeae5d763b48276675` 및 basis SHA `0b5f18e49ba0e4671a18cf972924d05c698fd507e7401ad7341877f61efaf3ef`를 기준으로 한다. 이전 사전 승인 snapshot은 downstream 계산에 사용하지 않았다. source preflight의 각 입력 hash 17개를 다시 확인했다.

검토 결과는 [source/category audit](independent_source_category_audit.json), [fit audit](independent_fit_audit.json), [prediction/report audit](independent_prediction_audit.json)에 있다. 외부 입력과 참조 코드의 SHA는 [artifact manifest](ARTIFACT_MANIFEST.json)에 고정했다.
