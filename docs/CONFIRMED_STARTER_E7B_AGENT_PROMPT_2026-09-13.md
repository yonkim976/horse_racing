# E7-B 실행 지시: 최근 실제 출발3회 관측 묶음 비교

작업 경로: `/Users/kimyongjin/Desktop/horse_racing`.

E7-A 독립 검증을 통과했다. **감사된12열 전체를 추가하는 두 후보·3-fold·총12 fit의 실제 후향 개발 연구를 실행하라.** 사용자가 이 지시를 전달하면 이 범위의 실행은 승인된 것이다. 추가 확인 때문에 멈추지 말고 결과 또는 명세된 실패 증거를 완성해 독립 검증에 제출한다. 운영 승격과 이후 연구는 범위 밖이다.

먼저 다음 문서를 읽어라.

- `docs/CONFIRMED_STARTER_E7A_INDEPENDENT_REVIEW_2026-09-13.md`
- `docs/CONFIRMED_STARTER_E7B_PROTOCOL_DRAFT_2026-09-13.md`
- `docs/CONFIRMED_STARTER_E6B_AGENT_PROMPT_2026-09-13.md`
- `docs/CONFIRMED_STARTER_E6B_INDEPENDENT_REVIEW_2026-09-13.md`

본 지시에서 변경한 feature/arm 부분을 제외한 학습·보정·평가 계약은 E6-B와 동일하다. 기존 파일은 보존하고 새 E7-B runner/evaluator/tests 및 `data/experiments/confirmed_starter_e7b_20260913/`를 사용한다. 경로가 있으면 새 attempt를 명시하며 덮어쓰지 않는다.

## 입력 봉인과 확정 후보

H1:

- `data/datasets/confirmed_starter_e2_h1_remediation_retrospective/start_minus_30m/dataset.parquet`
- dataset SHA256: `9d508bfdea325482461fa5d4e1b9a3ea8543bfe146a9b40b5400f4084064d6a7`.
- 같은 폴더 manifest SHA256: `f36cc08930c4010cc3be230575289d06110add010d4c3ad368dbdad5f142d801`.
- 기존136열 이름/순서 hash: `b7f57b9939aac9b51993e29046d43a10c9f49fdcfac0b821807300459ef2ac48`.

E7-A 최종 폴더: `data/experiments/confirmed_starter_e7a_20260913_attempt4/`.

- artifact manifest SHA256: `4a2a9aad7c6c7c24f99bf57c201a9b3820736d769361ef56034875fd0f772ce3`.
- sequence_features.parquet SHA256: `4cf65df396542271c5b7574584b4c1991f52a4d05896e0b7ee4af8b2849fefea`.
- sequence_evidence.parquet SHA256: `ca02f11923f354e90f429fd2c06e7209f591ca6c0a3b6c77c6a4468aff41fd08`.
- E7-A feature module SHA256: `d3744f478fdb2fc0a9f597d3c652057fcf7b02c7031ba0378614d98b0a287682`.
- E7-B 초안 문서 SHA256: `d6a1dafb6af62d29e2eb2efc158650a9c1ad65969b0e854d1049d3ffff7c531d`.

후보는 정확히 `BASE_136`과 `SEQUENCE_12_AUDITED` 두 개다. 후자는 기존136열 뒤에 아래12열을 순서대로 추가해148열을 사용한다.

1. sequence_start1_early_rel
2. sequence_start1_last200_rel
3. sequence_start1_speed_figure
4. sequence_start1_days_ago
5. sequence_start2_early_rel
6. sequence_start2_last200_rel
7. sequence_start2_speed_figure
8. sequence_start2_days_ago
9. sequence_start3_early_rel
10. sequence_start3_last200_rel
11. sequence_start3_speed_figure
12. sequence_start3_days_ago

첫 speed와 경과일의 높은 중복률은 승인된 설계에 포함된다. 열을10개로 줄이거나 결측 indicator·중량·레이팅·배당 등을 추가하지 않는다. 기존136열을 교체하거나 재계산하지 않는다. 새12열은 슬롯이 없는 경우와 DNF·구간/보정 관측이 없는 경우의 봉인 null을 유지한다. 부경 basis 미확인536슬롯을 closing으로 추정하거나 과거 서울 출발로 채우지 않는다. metadata는 학습하지 않는다.

H1 전체15,579키와 새 feature의1:1 대응, evidence46,737슬롯, 이름/순서/Float64/finite·null 계약을 검사한다. 전체 키 검사 이후 모델 입력은2026-02-28까지의 해당 fold로 제한한다. 기존 raw/DB를 읽어 feature를 재구성하지 않고 감사된 parquet를 사용한다.

## 실행 전 명세와 공통 구현

첫 tree 전에 새 execution_protocol.json을 저장하라. 본 실행 승인 문서 및 기존 draft의 hash, 실제 code/환경/input hashes, 후보2개·열 목록·148/136차원, 아래 날짜·분모·학습 예산·실패 규칙을 고정한다. 기존 draft를 덮어쓰지 않는다.

기존 E6-B helper 중 arm 이름이나 추가열3개가 고정된 함수는 그대로 호출하면 안 된다. 새 E7-B wrapper/evaluator에서 두 arm과12열을 명시하고 기존136열 slice의 동일성을 검사하라. 봉인 E6-B 코드와 수학은 수정하지 않는다. 온도와 공통 gate는 검증된 `confirmed_starter_e6a_v2`의 두 후보 gate를 이용할 수 있으나, 기대 arm은 새 봉인 실행 명세에서 받는다. `scripts` 모듈을 쓰는 실행 명령은 프로젝트 루트의 `python -m ...`처럼 재현 가능한 형태로 기록한다.

## 분할·학습·보정

E6-B의 F1/F2/F3, 각 fit/tune/calibration/evaluation의 **12개 날짜 구간 및 행·경주·경주일 분모**를 그대로 사용하고 execution JSON에 풀어 적는다. 평가 구간 합계4,218행·407경주, 마지막 평가일2026-02-28이다. 평가 경주 중복은0이어야 한다.

encoder는 각 fold selector fit에서만 적합한다. 기존136열 mapping과 행렬은 두 후보가 공유하고 새12열은 수치로 덧붙인다. fit/tune/calibration/evaluation의 키·group·label·기존136열 matrix hash를 양 후보에서 대조한다. category unknown/null은 기존 encoder 정책이며 임의값 대치하지 않는다.

양 후보 모두 승인된 native LightGBM custom weighted Bernoulli BINARY와0/1 winner indicator, float32 buffer의1/field_size weight를 사용한다. 정상완주·DNF·실격의 봉인 win 라벨을 유지한다. 공동우승을 임의 한 우승자로 바꾸지 않는다. raw-margin 경주 soft-label CE metric에서만 q를 경주별로 복원한다.

고정 parameter는 E6-B와 같다: learning_rate .03, num_leaves31, max_depth -1, min_data_in_leaf80, min_sum_hessian_in_leaf .001, feature_fraction .8, bagging_fraction1/bagging_freq0, lambda_l2 1, boost_from_average false, deterministic/force_col_wise true, 모든 seed42, num_threads -1. 기본 metric은 끄고 tune CE 하나로 최대1200round/patience80의 selector를 실행한다.

각 fold/arm selector fit→tune 조기종료→fit+tune를 best iteration만큼 처음부터 refit→별도 calibration T를 한 번씩 수행한다. 총12fit이며 baseline도 계획대로 재학습한다. 모든 selector iteration의 raw-margin hash와 독립 CE를 저장 Booster 해당 iteration과 대조할 수 있게 보존한다. objective 반환 finite/양수 Hessian, label/group/weight 계약도 유지한다.

T는 기존 beta endpoint/root 진단만 사용한다. 각 fold의 두 arm 준비·진단이 모두 통과한 뒤에만 공통 gate로 evaluation 예측/라벨 결합/지표/저장을 수행한다. flat은 근거 있는 정확한T=1, interior는 승인 범위 내부이며 boundary·비유한·실패면 평가하지 않는다. 경계 확장이나 fallback은 없다.

BASE_136은 같은 입력·절차이므로 E6-B 각 fold의 baseline best iteration106/78/131과 calibration/evaluation keyed raw margin·T·지표를 재현하는지도 대조한다. raw margin/확률 허용오차1e-12, T1e-10을 명시한다. 불일치하면 입력/설정/환경 차이를 보고하고 추가 fit으로 맞추려 하지 않는다.

## 평가·실패·해석

주 지표는 calibrated raw margin의 stable log-domain 경주 평균 winner-set NLL이다. soft-label CE를 별도로 저장하며 F3 공식 동착을 구분한다. 보조는 entry binary NLL(epsilon1e-15), Brier, 동점 기대 Top1/3/5다. exact keys·마번·coverage·finite·범위·확률합·score/probability 동점·underflow를 모두 기록한다.

차이는 `SEQUENCE_12_AUDITED − BASE_136`. fold별·통합 paired race/race-date cluster bootstrap을 각각5000회·seed20260911로 계산한다. 통합은407경주 평균과4,218행 entry 지표이며 fold 평균을 단순 평균하지 않는다. 모든 fold와 TopK 방향을 제시한다.

어느 계약이든 실패하면 해당 fold 평가와 전체 통합 비교를 중단한다. 이전 완료 fold는 보존하되 성공 fold만 모아 우월성을 보고하지 않는다. 실제 fit 호출을 시작/완료 시점별 ledger에 기록하고 추가 seed/열 조합/온도/재학습 탐색은 하지 않는다.

이 비교는 슬롯 정책·관측 묶음·거의 중복인 입력도 포함한다. 차이를 순서 정보만의 순수 효과나 개별12열 기여로 주장하지 않는다. 동일407경주는 반복 개발 자료이며 CI는 저장 예측 조건부다. 독립 미래 우월성·운영 승격의 증거로 해석하지 않는다.

## 제출·종료

execution protocol, input/encoder/matrix/key/group/label/code hashes, 각 fold/arm의 selector/refit·callback 감사·T·keyed calibration/evaluation 예측·재로드 대조, E6-B baseline 재현 대조, 경주별 paired loss·전체 comparison·fit ledger·보고서·검사 결과·manifest를 저장한다. 기존 upstream102경로·E7-A 출력·관련코드·registry의 전후 hash를 대조한다. DB는 학습에 사용하지 않으며 새 원천 수집도 하지 않는다.

새148열 계약·공통 gate·후보 이름·실패 fold 통합 금지·예측 키 축소·공식 동착을 실제 함수의 합성 반례로 검사한다. 관련 Ruff/format, console pytest와python -m pytest, diff-check를 실행하고 범위 밖 오류를 구분한다.

2026년3~5월 새 성능과6월 이후 실제 결과를 열지 않는다. 운영 prediction·배팅 경로·registry/champion을 변경하지 않는다. 두 후보 결과 또는 명세된 실패 증거를 제출한 뒤 후속 연구 없이 종료하라.
