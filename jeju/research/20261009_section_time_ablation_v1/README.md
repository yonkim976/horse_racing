# F1 + 과거 구간시간 최소 ablation

2026-10-09에 고정한 후향 비교다. 기존 F1의 24개 입력에 같은 말의 같은 거리 최근 실제 출전에서 얻은 S1F·G3F·G1F 시간 평균과 각 필드의 유효 관측 수를 더해 30열 F1S 후보 3개를 평가했다. 세 필드의 시간 정보 묶음은 전체 점추정에서 F1보다 조금 낮은 손실을 보였지만, 사전 고정 연구 유지후보 gate를 통과하지 못했다. 따라서 이 결과는 구간시간 묶음의 전체 가치나 개별 필드 효과를 확정하지 않으며, F1S를 운영 모델로 제안하지 않는다.

F1S는 로그손실과 Brier 점추정 모두 F1보다 낮았다. 날짜 단위 paired bootstrap에서 두 95% 구간의 상한은 모두 0보다 높았으므로 gate 조건을 만족하지 않았다. 로그손실 차이 상한만 음수인 경우에도 통과하도록 정의된 gate였지만, 이번에는 해당 조건도 성립하지 않았다. 이 단일 후향 표본에서의 작은 점추정 차이로 구간시간이 전반적으로 유용하거나 무용하다고 일반화할 수 없다.

## 고정 설계

- 모집단은 F1과 완전히 같다: 2017-01-13~2026-09-19, 52,155출전·5,206경주. 이는 공식 ID 연결, 6두 이상 편성, 전체 정상 착순 1..N, 전체 양수 완주시간 등으로 **결과를 확인한 뒤 선정된 F1 연구 코호트**다. 모든 제주 출전·취소·DNF·실격·불완전 순위 경주를 포괄하지 않으며, 그 모집단에 대한 예측 성능으로 일반화할 수 없다. 2017년 이전은 warm-up 이력에만 쓰고, 경주일 한국시간 T−2 cutoff를 포함한다. 삭제 대상 말 3005648은 제외돼 있으며 평가표본에는 포함되지 않았다.
- 평가는 2024~2026의 17,412출전·1,779경주·269일이다. 연도별 평가 행·경주는 2024년 6,329·637, 2025년 6,410·654, 2026년 4,673·488이다.
- 각 연도 Y에서 초기 학습은 2017~Y−3, 조기종료 및 refit은 Y−2까지, 온도 보정은 Y−1, 평가는 Y다. 기존 F1과 같은 LightGBM 설정·seed 20261008·경주당 `1/field_n` 가중치·additive-3-score 평가기를 사용했다. 한 해마다 후보를 한 번 학습해 총 6회의 train 호출과 3회의 온도 최적화를 했다. 결과에 따른 재학습·추가 탐색은 하지 않았다.
- F1S는 기존 24개 열을 그대로 두고 다음 6개 열만 추가했다: `history_s1f_mean5_seconds`, `history_s1f_valid_n`, `history_g3f_mean5_seconds`, `history_g3f_valid_n`, `history_g1f_mean5_seconds`, `history_g1f_valid_n`.
- 각 값은 기존 F1 lineage의 정확히 같은 거리 최근 최대 5개 실제출전 슬롯에서 계산했다. 슬롯은 유지하고 필드별 결측을 독립 처리했다. 유효 관측 수 1~5의 산술평균을 저장하고, 0이면 평균 NULL·n 0을 보존했다. 0초 대체·창 backfill·다른 구간의 값 전파는 없다.
- 시간은 `jeju_race_postrace_sections_quality_2026`가 선택한 `time_seconds/time_status`를 사용했다. 시간 상태가 `website_corrected` 또는 `api_positive_unreviewed`이고 선택값이 양수이며 기존 `valid_time=True`인 경우만 유효하다. S1F/G1F에서 동일 race-point의 통과착순·통과조 품질상태가 `conflict`, `not_applied`, `source_changed`를 포함하거나 누락되면 그 지점의 전체 말 시간을 후보 피처에서 NULL로 마스킹했다. 원천 감사에 남은 미해결 착순 70건·통과조 20지점은 우회하지 않았고, 이번 F1 slot에서 실제 참조한 6개 S1F와 6개 G1F race-point에만 보수적 마스크를 적용했다. G3F 순위·통과조는 생성하지 않았다. 광해청명 G1F 미해결값과 네 개의 감사된 정정·미해결 사례는 원천 상태 그대로 보존했다.
- S1F는 ‘원천 S1F 지점시간’이다. 보편적인 200m/210m 기록으로 가정하거나 거리 간 환산하지 않았다. G3F와 G1F는 별개인 종반 원천시간으로 유지했다. 1300m의 출발→2C→S1F 순서 계약도 바꾸지 않았다.

이력 `valid_time=True`는 과거 source record의 구간 피처 유효성을 정하는 별도 입력 gate다. 이는 현재 평가 경주 코호트 선택 조건과 다르다. T−2·lineage 검증 및 30열 입력 불변 확인은 이 고정 후향 코호트 안에서의 피처 시점과 행 보존을 확인했을 뿐, 결과 확인 전에도 코호트 포함·제외를 알 수 있었다는 증거가 아니다.

## 전체 평가

주 손실은 경주를 같은 비중으로 계산한 Top3 log loss와 Brier다. 차이는 F1S−F1이며, 날짜별 paired bootstrap 2,000회·seed 20261008의 점별 95% 구간이다. 여기서 F1과 F1S가 보고하는 최대 6개 조합은 모두 additive-3-score 방식의 native 조합 분포에서 계산했다.

| 지표 | F1 | F1S | 차이 F1S−F1 | 95% 구간 |
|---|---:|---:|---:|---:|
| 경주균등 log loss | 0.569469 | 0.568732 | −0.000736 | [−0.001946, +0.000445] |
| 경주균등 Brier | 0.192724 | 0.192393 | −0.000331 | [−0.000855, +0.000176] |

두 점추정은 개선 방향이지만 두 구간의 상한이 0보다 크다. 사전 gate는 “두 손실의 점추정이 모두 낮고, 둘 중 적어도 하나의 날짜 paired 95% 구간 상한이 0 미만”이었다. 결과는 **gate 실패**다.

| 평가연도 | 경주 수 | log loss F1 → F1S | Brier F1 → F1S | 해석 |
|---|---:|---:|---:|---|
| 2024 | 637 | 0.568598 → 0.567349 | 0.191952 → 0.191284 | 점추정 개선 |
| 2025 | 654 | 0.567216 → 0.566068 | 0.191741 → 0.191341 | 점추정 개선 |
| 2026 | 488 | 0.573624 → 0.574108 | 0.195050 → 0.195250 | 두 손실 점추정 악화 |

전체 Top5 실제 Top3 포함률은 F1 69.0650%, F1S 69.3835%였고 차이의 날짜 paired 구간은 [−0.282, +0.954]%p다. 실제 Top3 세 두를 Top5에 모두 담은 비율은 29.1175%→29.1737%로 차이가 +0.056%p였다. 최대 6개 조합 적중률은 22.3159%→23.1591%(+0.843%p), 95% 구간 [−0.337, +2.064]%p였다. 이 보조 점추정도 0을 포함하는 구간이며 주 gate의 결론을 바꾸지 않는다.

## 거리·경력·유효 관측 수

거리별 경주 손실과 paired 구간은 전체 하위집단 표에 저장했다. 800~1400m는 거리별 52~508경주였다. 1610m는 9경주·9일이라 결과 표에서 설명용 표식 `small_support`로 표시했다. 표식 기준은 30경주 미만이며 후처리 보고용이다. 1610m log loss 차이는 +0.000638, Brier 차이는 +0.000847이지만 각 구간이 넓고 0을 포함해 해석하지 않는다. 이 표식은 주 gate나 평가 집단 선택에 영향을 주지 않는다. 거리별 S1F 측정 정의가 동일하다고 가정하거나, 지원이 작은 거리를 전체 거리의 대표로 보지 않는다.

출전 경력은 전체 출전 수 0, 1~4, 5+로 나눴고, 동일거리 실제 슬롯 수는 0, 1~4, 5+로 나눴다. 후보 F1S 기준 각 그룹의 `rows`와 고유 `races`는 [runner group 표](outputs/f1s_runner_metrics_by_group.csv)에 있다. 필드별 유효 구간기록 수 0~5의 행 수·경주 수도 같은 표에 별도 실었다. 모든 하위집단 결과는 설명용이며, 30경주 미만은 작은 지원으로 표시했다. 소표본 표식은 평가 결과를 골라내거나 주 gate를 바꾸는 데 사용하지 않았다.

## 구간시간 원천 가용성 감사

가용성 감사는 F1의 보존된 최근 실제출전 슬롯 178,459개와 연결된 source ID 50,491개를 대상으로 했다. 감사는 F1의 실제 입력 후보 슬롯에 대한 것이며, 다른 기간·완주군을 대상으로 만든 더 넓은 구간시간 통계의 분포를 이 모집단의 지원으로 대체하지 않았다. 원천 이력은 2008-05-04~2026-09-05이고, F1 lineage에서 참조된 원천 경주는 6,269개다.

| 지점 | F1 실제 슬롯 | 유효 선택 시간 슬롯 | 마스킹으로 제외된 유효 값 |
|---|---:|---:|---:|
| S1F | 178,459 | 178,184 | 170 |
| G3F | 178,459 | 178,354 | 0 |
| G1F | 178,459 | 178,199 | 151 |

G1F는 품질 충돌 race-point에 속한 슬롯 159개 중 기존 결측·무효 8개를 제외한 유효 후보값 151개를 마스킹했다. S1F는 해당 마스크에서 유효 후보값 170개를 제외했다. 이 값들은 실제출전 슬롯 수와 별도 집계다. 조회는 품질 뷰의 constituent 선택값·상태 필드만 사용했고 SQLite를 `mode=ro`, `query_only=ON`으로 열었다. 전체 기간을 섞은 백분위·느린 꼬리 기준, 원문 우회, 임의 이상치 제거, 전체기록 보정계수의 구간시간 전이는 없었다.

S1F/G3F/G1F의 source-level `n=0..5` 지원, 연도·거리별 가용성은 [가용성 표](outputs/source_availability_by_group.csv), [n 분포](outputs/source_valid_n_distribution.csv), [감사 JSON](outputs/source_availability_audit.json)에 보존했다. 이 표의 모수는 후보 입력을 구성하는 실제 slot 기록이며, 모델 평가의 17,412행과 분모가 다르다.

## 별도 2026 공통 467경주 비교

이 표는 기존 F1 연구의 공통 467경주·4,475출전만 떼어 기존 운영 모델 HY_R_FORM과 나란히 제시한 보조 비교다. F1/F1S의 최대 6개 조합은 additive-3-score native 분포에서, HY_R_FORM 조합은 그 운영 모델의 기존 Plackett–Luce(PL) 절차에서 각각 산출했다. 조합법과 개발·운영 절차가 다른 완성 모형의 비교이므로 구간시간 묶음의 기여를 식별하거나 주 gate를 대체하지 않는다.

| 모형 | Log loss | Brier | 최상위 후보 Top3 입상률 | Top5 capture | Top5 전체 적중 | 최대 6개 조합 적중 |
|---|---:|---:|---:|---:|---:|---:|
| F1 | 0.573442 | 0.194940 | 58.2441% | 69.5218% | 30.1927% | 24.4111% |
| F1S | 0.574293 | 0.195270 | 56.7452% | 70.5924% | 31.0493% | 26.3383% |
| HY_R_FORM | 0.555417 | 0.187645 | 61.0278% | 75.0178% | 38.9722% | 30.8351% |

F1S−F1의 467경주 log loss 차이는 +0.000851 [−0.001769, +0.003449], Brier 차이는 +0.000330 [−0.000775, +0.001490]이었다. 이 표는 467경주에 국한된 보조 비교이며 전체 평가 gate에 섞지 않았다.

`최상위 후보 Top3 입상률`은 점수가 가장 높은 말이 3위 안에 들었는지의 비율이며 우승 적중률이 아니다. 최대 6개 조합 적중은 각 모형이 자기 고유 조합 절차로 만든 상위 여섯 조합 안에 실제 상위 세 두 조합이 있는지를 측정한다. 조합은 성과 평가용 예측 집합이며 실제 발행 티켓이나 수익률이 아니다.

## 실행·검증 기록과 한계

F1 원 모델은 학습하지 않았다. fit 전 저장된 세 F1 모델의 점수·확률·지표·6조합 재현은 17,412행·1,779경주·10,674 조합에서 PASS였다. 후보 fit은 사전 검토 후 고정한 정확한 세 모형만 학습했으며 tree 수/온도는 2024 `151 / 1.065777`, 2025 `200 / 1.132552`, 2026 `199 / 1.049928`이다.

첫 실행은 6회 train과 3회 온도 최적화를 마친 뒤 보고 단계의 기존 context 열 중복 병합에서 멈췄다. 저장 모형·메타·보정 점수의 SHA를 고정한 뒤 별도 finalizer가 세 저장 모형과 메타데이터의 고정 온도만 읽어 평가 산출물을 재생성했다. 후처리 복구는 모델 fit이나 온도 최적화를 반복하지 않았다. [중단·복구 기록](outputs/fit_execution_interruption.json), [saved model integrity lock](outputs/postfit_saved_model_integrity_lock.json), [완료 receipt](outputs/fit_execution_completion.json), [after-fit 보호 검사](outputs/after_fit_integrity_check.json)에 실행 횟수와 해시를 남겼다. 완료 receipt는 중간 무저장 후처리 점검도 포함하도록 실행 이력 대조 후 보완했다.

독립 사전 source 감사와 fit harness review는 [source 가용성·T−2 lineage 검사 receipt](../20261009_section_ablation_review_v1/independent_outputs/independent_source_availability_receipt.json), [피처 재구성 및 저장 F1 재현 receipt](../20261009_section_ablation_review_v1/independent_outputs/independent_feature_and_f1_replay_receipt.json), [fit harness 검토 receipt](../20261009_section_ablation_review_v1/independent_fit_harness_review.json)에 저장됐다. 최종 F1S 예측·경주·6조합·paired/group/calibration 및 467 비교 표는 [독립 finalizer 비교 receipt](../20261009_section_ablation_review_v1/independent_outputs/independent_f1s_finalizer_output_review.json)에서 모두 PASS했고, C가 후보 helper를 재사용하지 않고 저장 모형을 다시 평가한 [독립 replay v2 receipt](../20261009_section_ablation_review_v1/independent_outputs/independent_f1s_saved_model_replay_v2_receipt.json)와도 일치했다. 두 사후 검증 모두 fit이나 온도 재최적화를 하지 않았다.

추가 [row-specific outcome/time perturbation receipt](../20261009_section_ablation_review_v1/independent_outputs/row_specific_leakage_invariance_receipt.json)는 7개 사례에서 target 결과·완주시간·유효성·구간시간을 메모리에서 바꾸어도 F1 24열과 F1S 30열, 모델 점수·입상확률·해당 경주 6조합이 동일함을 확인했다. 선택 이력이 target T−2까지인지와 T−2 뒤의 동일 말·거리 출전이 제외되는지도 검사했다. 이 제한된 사례 검사는 고정 코호트 안의 row-level 입력 불변성 확인이며 전체 코호트 선정이 결과 공개 전에 가능했다는 증거가 아니다.

후향 평가가 통과하더라도 실제 미래 시점 입력 가용성, 다른 기간에서의 재현, S1F 거리별 정의의 이식 가능성, 세 지점 중 어느 한 지점의 독립 효과를 증명하지 않는다. 구간 피처 중요도는 개별 구간의 효과나 인과 기여로 해석하지 않는다. 모든 연구 파일은 이 버전에 보존하며 운영 모델·등록부·DB 및 중앙 conclusions는 변경하지 않았다.

## 산출물

- [사전 계약](CONTRACT.md), [구현 계획](IMPLEMENTATION_PLAN.md)
- [품질 가용성 감사 코드](audit_source_availability.py), [피처 생성 코드](build_candidate_features.py), [F1 재현 코드](replay_saved_f1.py), [한 번 fit하는 고정 runner](fit_candidate.py), [saved-model 후처리 finalizer](finalize_saved_f1s_outputs.py)
- [F1S 30열 피처](outputs/features_f1s.parquet), [저장 F1 재현 receipt](outputs/f1_saved_model_replay.json), [후보 사전 검증](outputs/candidate_feature_preflight.json), [fit harness preflight](outputs/fit_runner_preflight.json)
- [전체 경주 지표](outputs/f1s_race_metrics.csv), [F1S−F1 paired 결과](outputs/f1s_paired_differences.csv), [연도·거리 경주 그룹 표](outputs/f1s_metrics_by_group.csv), [경력·구간 n 말 그룹 표](outputs/f1s_runner_metrics_by_group.csv), [최대 6개 조합](outputs/f1s_six_combinations.csv)
- [운영 467경주 지표](outputs/f1s_operating_common_467_summary.csv), [고정 gate](outputs/f1s_gate.json)
- [fit 전 lock](outputs/prefit_lock.json), [C fit harness review](../20261009_section_ablation_review_v1/independent_fit_harness_review.json), [fit 중단 기록](outputs/fit_execution_interruption.json), [모델 해시 lock](outputs/postfit_saved_model_integrity_lock.json), [완료 receipt](outputs/fit_execution_completion.json), [보호 파일 검사](outputs/after_fit_integrity_check.json)
