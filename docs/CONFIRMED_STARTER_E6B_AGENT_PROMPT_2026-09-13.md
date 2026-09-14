# E6-B 실행 지시: 부담조건 세 feature의 시간순 개발 비교

작업 경로: `/Users/kimyongjin/Desktop/horse_racing`.

E6-A v2의 R1~R4 독립 재검증을 통과했다. **봉인된 원문 미확인17건의 null 격리를 유지한 상태로, 두 후보·3-fold·총12 fit의 실제 후향 개발 연구를 실행하라.** 이 지시를 사용자가 전달하면 이 범위의 실행은 승인된 것이다. 추가 확인 때문에 멈추지 말고 결과 또는 명세된 실패 증거를 완성해 독립 검증에 제출하라. 운영 승격·추가 연구·새 후보 탐색은 승인하지 않는다.

먼저 다음을 읽어라.

- `docs/CONFIRMED_STARTER_E6A_V2_INDEPENDENT_REVIEW_2026-09-13.md`
- `docs/CONFIRMED_STARTER_E6B_PROTOCOL_V2_DRAFT_2026-09-13.md`
- `docs/CONFIRMED_STARTER_RACE_OBJECTIVE_PROTOCOL_V3_2026-09-12.md`
- `docs/CONFIRMED_STARTER_E5B_INDEPENDENT_REVIEW_2026-09-12.md`

## 봉인 입력

H1 폴더: `data/datasets/confirmed_starter_e2_h1_remediation_retrospective/start_minus_30m/`.

- dataset SHA256: `9d508bfdea325482461fa5d4e1b9a3ea8543bfe146a9b40b5400f4084064d6a7`.
- manifest SHA256: `f36cc08930c4010cc3be230575289d06110add010d4c3ad368dbdad5f142d801`.
- 기존136개 이름/순서 hash: `b7f57b9939aac9b51993e29046d43a10c9f49fdcfac0b821807300459ef2ac48`.

E6-A v2 폴더: `data/experiments/confirmed_starter_e6a_v2_20260913_attempt4/`.

- artifact manifest SHA256: `24c667ed059fbf59eabc7676ee9222279fbd895711f958a6241efd2b0789d3b2`.
- `confirmed_starter_e6a_v2_features.parquet` SHA256: `b6bc85abfcd6ce2fd1ee4dce621ad91d573942008308341a68af48b7ac45ae0d`.
- `e6b_protocol_v2_draft.json` SHA256: `c9e8be81659da5f1315355845a46a0f32809f4c4a04de76e719265f9826490ad`.
- v2 helper SHA256: `d400aac796518a9e2da78a95849de330f6962d64d392f746697c257e5baacb4c`.
- 기존 수학 adapter `confirmed_starter_e5_r3r4.py` SHA256: `55c7dcf686e4bf068b488beb396ffe18fd37a9f179939195494b21f9f35982d0`.

manifest hash뿐 아니라 기재된 실제 파일들도 대조한다. 기존 dataset·source·실험·코드·dirty 변경·registry는 보존하고 별도 E6-B runner/평가 파일/테스트와 `data/experiments/confirmed_starter_e6b_20260913/`를 사용한다. 경로가 있으면 덮어쓰지 말고 새 attempt를 명시한다.

기존 draft JSON은 후보 확인용 봉인 참조로 유지한다. `load_sealed_protocol_candidates`는 그 draft를 그대로 읽게 하고, 본 지시의 실행 승인을 참조하는 **새 execution protocol JSON**을 첫 tree 전에 저장한다. draft 상태 문자열이나 기존 helper를 몰래 수정하지 않는다. 실행 명세에 모든 날짜·분모·parameter·예산·실패 규칙·환경과 소스 hash를 고정한다.

## 입력·후보·분할

후보는 정확히 `BASE_136`과 `CURRENT_WEIGHT_A_PREV`다. 후자는 다음 순서의 세 수치열만 기존136열 뒤에 추가해139열을 사용한다.

1. condition_carried_weight_kg
2. condition_carried_weight_rel_A
3. condition_carried_weight_delta_prev_start

H1의 전체15,579키를 기준으로 parquet를 1:1 대조해 누락·추가·중복을 거부한다. 기존136열과 label을 재계산하지 않는다. 원문 미확인17건은 키를 유지하고 delta null을 그대로 사용한다. 값 재조회·복구·과거 서울 출발 fallback·행 제거·임의0대치는 없다. 기존 encoder의 결측 표현 정책만 사용한다. 상태·원천·가용성 metadata는 학습 열이 아니다.

E6-B protocol v2의 12개 partition 날짜·행·경주·경주일을 그대로 사용한다. 각 fold 내 경주별 연속 배치와 날짜/race_id/entry_id 정렬을 고정한다. 평가 구간은 서로 겹치지 않는 총4,218행·407경주다. 2026-02-28 이후 행은 모델 적합·encoder 적합·평가에서 제외한다. H1 전체를 읽는 것은 hash/키/feature 계약 확인에 한정한다.

각 fold encoder는 해당 selector fit 행에서만 적합해 동결한다. 두 후보의 기존136열 category mapping과 변환 행렬을 공유하고, 확장 후보에는 수치3열을 덧붙인다. 기존 E5-B의 전체 train encoder를 재사용하지 않는다. fit/tune/calibration/evaluation 모두 기존136열 행렬·키·group·label의 양 후보 일치를 검증한다. 범주형 정의와 미지 category 정책을 명시한다.

## 학습·보정·공통 평가 경계

두 후보 모두 기존 승인된 custom weighted Bernoulli BINARY를 사용한다. objective 이름과 arm 이름을 구분한다. 각 경주의 0/1 winner indicator와 행 weight=1/field_size, float32 Dataset buffer를 검사한다. 동착 indicator를 임의 한 우승자로 바꾸지 않는다. soft-label CE metric에서는 경주별 winner indicator로 q를 복원한다.

고정 parameter는 protocol v3 및 E5-B BINARY와 같다: learning_rate .03, num_leaves31, max_depth -1, min_data_in_leaf80, min_sum_hessian_in_leaf .001, feature_fraction .8, bagging_fraction1/bagging_freq0, lambda_l2 1, boost_from_average false, deterministic/force_col_wise true, 모든 seed42, num_threads -1. native LightGBM train을 사용하고 기본 metric은 끈다.

각 fold/arm에서 selector fit→tune CE early stopping(최대1200round, patience80)→fit+tune를 best_iteration만큼 처음부터 refit→별도 calibration으로 T 적합을 각각 한 번 수행한다. 예정 fit은 총12회이며 성공 여부를 바꾸기 위한 추가 재학습·seed·설정 탐색은 없다.

callback raw margin·label/group/weight 및 objective gradient/Hessian의 finite/양수 Hessian 계약을 유지한다. 모든 selector iteration의 raw-margin hash와 독립 경주 CE를 저장 Booster의 해당 iteration에서 대조한다. best_iteration 이후까지 감사 가능하도록 전체 selector를 보존하고, selector와 최종 refit artifact를 구분한다.

temperature는 기존 diagnose_temperature의 beta endpoint/root 절차만 사용하고 진단을 `prepare_diagnosed_arm` 또는 `prepare_calibrated_arm`으로 공통 gate에 전달한다. 경계를 넓히거나 T=1 fallback하지 않는다. **각 fold에서 두 arm의 준비·temperature 진단이 모두 통과한 뒤에만 `run_e6b_fold`를 통해 evaluation 예측·라벨 결합·지표·저장을 실행한다.** 기존 E5-B의 후보별 조기 validation 경로를 재사용하지 않는다.

어떤 계약이라도 실패하면 해당 fold 평가와 전체 통합 비교를 중단한다. 실패 전에 완료된 fold의 artifact는 보존하되 성공 fold만으로 통합하거나 우월성을 보고하지 않는다. 실패 stage와 실제 fit 호출 수를 즉시 원장에 남기고 종료한다. 모든12fit을 억지로 채우지 않는다.

## 평가·해석

주 지표는 calibrated raw margin에서 계산한 stable log-domain 경주 동등가중 winner-set NLL이다. 주 손실에 epsilon clipping을 쓰지 않는다. 공식 동착의 winner-set NLL과 soft-label CE를 구분해 둘 다 저장한다. 보조는 entry-equal binary NLL(epsilon1e-15), Brier, 동점 기대 Top1/3/5다. score/probability tie, underflow, clipping 수와 전체 키·확률합·finite 계약을 함께 기록한다.

delta는 `CURRENT_WEIGHT_A_PREV − BASE_136`이며 loss의 음수가 개선 방향이다. fold별 모든 지표와 두 bootstrap을 보고한다. 통합 주 지표는407경주 전체 평균으로 계산하며 fold 평균을 단순 평균하지 않는다. 통합 entry 지표는4,218행 기준이다. fold별 및 통합 paired race/race-date cluster bootstrap은 각5000회, seed20260911로 고정한다. 경주일 resampling에서는 그 날짜의 전체 경주를 유지한다.

CI는 저장 예측에 조건부이고 재학습·연구 선택 불확실성을 포함하지 않는다. 단일 seed와 반복 사용한 개발 데이터라는 한계를 유지한다. 유리한 fold·결측 여부별 표본·성능 좋은 구간을 사후 골라 후보를 바꾸지 않는다. 세 feature 묶음의 효과만 비교하며 개별 feature 기여·중량 인과효과를 주장하지 않는다. NLL 개선과 TopK 방향을 함께 제시하고 독립 미래 우월 후보나 운영 champion을 선언하지 않는다.

## 저장·검증·종료

execution protocol, 입력/encoder/matrix/key/group/label/code hashes, 각 fold/arm selector·refit Booster, callback 감사, best iteration, calibration/evaluation keyed raw margin·확률·T진단, 재로드 대조, 경주별 paired loss, 모든 fold·통합 comparison, 시도/fit 원장, 환경·검사 결과·artifact manifest·연구 보고서를 저장한다. 별도 연구 원장만 사용한다.

저장 refit 재로드에서 calibration/evaluation raw margin 및 확률을 원예측과 검증한다(최대 오차1e-12). 원본 input 및 운영 registry의 전후 hash도 대조한다. 새 runner의 공통 gate와 fold통합 실패 처리, 분할 및 key 계약을 실제 함수에 대한 합성 반례로 검사하고 관련 Ruff/format·전체 pytest·diff-check를 실행한다. 범위 밖 기존 오류를 구분한다.

실제2026년3~5월 성능을 새로 계산하거나6월 이후 실제 결과를 열지 않는다. 운영 prediction·배팅 경로·registry/champion 변경은 없다. 두 후보의 제한된 개발 결과 또는 실패 증거를 제출한 뒤 후속 연구 없이 종료하라.
