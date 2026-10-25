# 거리별 구간 상대기록 후보 비교

## 결론

900·1000·1110·1200m의 거리별 과거 구간 상대기록 평균과 관측 수를 추가한 단일 후보는 주 표본의 log loss와 Brier 점추정치가 `F1_STYLE6`보다 소폭 낮았지만, 두 지표 모두 사전 고정 95% 날짜 bootstrap 구간이 0을 포함했다. 사전 성과 gate는 통과하지 못했다. 이 후보는 채택하거나 운영에 올리지 않으며 기존 `F1_STYLE6`을 유지한다.

| 주 표본 지표 | F1_STYLE6 30열 | 후보 40열 | 후보−기준선 | paired 95% CI 상한 |
|---|---:|---:|---:|---:|
| 경주 동일가중 Top3 이진 log loss | 0.5689268769 | 0.5688217082 | −0.0001051687 | +0.0008861667 |
| 경주 동일가중 Top3 Brier | 0.1926429239 | 0.1926067859 | −0.0000361380 | +0.0003975259 |

주 표본은 2024–2026년 네 대상거리의 14,714출전·1,503경주다. 차이는 후보−기준선이며, 고정 269일 일정의 2,000회 paired date bootstrap을 사용했다. 후보 두 점추정치는 모두 음수였지만 두 신뢰구간 상한 모두 양수여서 gate 조건을 충족하지 못했다.

같은 기존 canonical 최대 6개 3두 조합 선택 규칙의 적중 경주는 전체 1,503경주에서 346회에서 350회로 늘었다. 거리별 적중은 900m 65→62, 1000m 116→108, 1110m 104→111, 1200m 61→69였다. 이는 보조 지표이며 채택 gate를 바꾸지 않는다. 전체 결과와 범위별 세부 표는 [고정 점수 평가 보고서](../20261019_distance_section_relative_evaluation_v1/README.md)와 [evaluation summary](../20261019_distance_section_relative_evaluation_v1/outputs/evaluation_summary.json)에 있다.

## 실험과 모델

저장된 기준 `F1_STYLE6`의 30개 입력과 2024·2025·2026 저장 모델을 고정했다. 기준선 모델은 다시 학습하지 않았고, 저장 모델을 새 경로에서 재생해 말별 점수·경주 지표·canonical 최대 6개 조합을 정확히 재현했다. 재현 결과는 [baseline replay receipt](outputs/baseline_replay_verification.json)에 기록되어 있다.

후보는 전체 52,155행·5,206경주 모집단에서 기존 30개 입력에 구간별 잔차 평균 5개와 유효 관측 수 5개를 더한 한 묶음의 40열 모델이다. 900·1000·1110·1200m 행에만 해당 거리의 값을 채우며, 그 밖의 거리에서는 10개 신규 입력을 모두 NULL로 둔다. 기존 입력 값과 전체 행 순서는 그대로 보존했다.

각 대상의 저장된 최근 5회 동일거리 출전 슬롯을 사용하고 경주일−2일까지 포함한다. source 경주마다 같은 거리·구간의 과거 적격 경주 median을 경주별 동일 가중으로 평균하며, 과거 경주가 20개 미만이면 기준값을 만들지 않는다. 잔차는 `과거 benchmark − 실제 구간 초`라서 양수는 과거 같은 거리·구간 기준보다 빠른 기록을 뜻한다. 잘못된 슬롯을 제외한 뒤 더 오래된 출전으로 보충하지 않는다. 1110m S1F는 210m 구간으로 기록하지만 초 단위 잔차를 길이로 나누거나 거리 간에 환산하지 않는다. 전체 정의는 [실험 계약](CONTRACT.md)에 있다.

세 후보 fold는 각각 199, 199, 190개 tree를 선택했고, 온도 계수는 각각 1.0935748741, 1.0902779494, 1.0155677679였다. 이 비교는 후보 3모델, LightGBM 6회 학습, 온도 최적화 3회만 수행했다. 결과를 본 뒤 추가 튜닝이나 재학습은 하지 않았다. 모델·score·meta 파일 SHA-256은 [model artifact manifest](outputs/model_artifact_manifest.json)에 고정했다.

## 원천과 사전검증

원천은 동결 F1 snapshot의 55,860개 시작 출전·5,668개 경주다. 38,193개 대상 출전의 저장된 최근 5회 슬롯은 135,855개이고, 구간별 총 679,275개 슬롯×구간 중 678,044개가 유효 상대잔차로 계산됐다. 1,151개는 원천 구간·품질 조건을 통과하지 못했고, 80개는 과거 적격 경주 20개를 채우지 못했다.

현재 DB에서만 확인된 추가 54개 출전은 전체 field 품질 마스크 확인에만 사용하고 기준 median에는 포함하지 않았다. frozen roster가 한 출전자만 가진 초기 7개 경주는 전체 roster 품질 마스크가 불완전해 관련 구간을 fail-closed 처리했다. 해당 경주의 median은 동결 roster의 적격 출전자만을 반영하므로 전체 field의 median을 대표하지 않을 수 있다. 일부 양수 구간 시간은 `api_positive_unreviewed` 상태에서도 사전 정의한 원천 품질 기준을 통과할 수 있어 실제 계측 정확도가 확인된 값으로 해석하지 않는다.

독립 feature core가 race×구간 median 28,340개, 대상 slot×구간 benchmark 21,770개, 전체 대상 slot×구간 잔차 679,275개를 원천 산출물과 대조했다. 기준선 30개 입력과 행 순서 보존, 10개 신규 열, 날짜 cutoff, 최근5 lineage, NULL/0 관측수 정책 및 고정 bootstrap 입력을 포함한 사전 잠금은 [source preflight](outputs/source_preflight.json)과 [prepared lock](outputs/prepared_lock.json)에 기록돼 있다. root가 모든 잠금 파일을 독립 검증한 뒤 fit을 승인했다.

## 재현 파일

- 전체 40열 feature table: [features parquet](outputs/features_f1_style6_distance_section_relative10.parquet)
- 대상별 최근 슬롯·구간 감사 ledger: [relative history parquet](outputs/target_relative_section_history.parquet)
- 대상 profile과 source ID: [feature profiles parquet](outputs/target_relative_feature_profiles.parquet)
- 거리·연도·구간별 관측수: [prefit support CSV](outputs/prefit_feature_support_by_distance_year.csv)
- 고정 키로 선택한 피처 사례: [prefit examples CSV](outputs/prefit_feature_examples.csv)
- 학습 완료 영수증: [candidate training completion](outputs/candidate_training_completion.json)
- 모델·점수·meta 최종 해시: [model artifact manifest](outputs/model_artifact_manifest.json)
- 전체 점수 평가 폴더: [20261019_distance_section_relative_evaluation_v1](../20261019_distance_section_relative_evaluation_v1/README.md)

이 연구는 후향 개발 비교다. 원천 공개 시점은 확인되지 않았고, `T−2`는 사전 합의된 retrospective cutoff이지 해당 자료가 경주 전에 예측자에게 제공되었음을 입증하지 않는다. 후보는 전체 거리 cohort를 다시 학습했으므로 신규 입력이 NULL인 말의 점수도 기존 저장 모델 점수와 동일하다고 보장하지 않는다. 운영 모델·등록부·DB와 기존 pair/order 모델은 변경하지 않았다.
