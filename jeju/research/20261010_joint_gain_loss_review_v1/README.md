# 관계모델 gained/lost 분석 독립 검토

## 검토 범위

고정된 관계모델 연구 산출물에서 전체 평가 코호트의 적중·미적중 그룹을 독립적으로 재구성했다. `race_metrics.csv`의 경주 키와 `runner_marginals.csv`의 말 키를 대조하고, runner의 명시적 `y_top3` 라벨로 실제 무순서 Top3 집합을 만든 뒤 각 팔의 여섯 저장 티켓 포함 여부를 직접 다시 계산했다. 분석 A의 코드나 helper는 불러오지 않았다. 11항 에너지와 true-set 대 경계 경쟁 조합을 재검산할 때는 과거에 별도로 고정된 C 독립검증 모듈의 결정적 피처 수학 함수만 재사용했다. 해당 모듈의 fitting·optimizer·온도 검색 경로는 실행하지 않았다.

원천 manifest SHA-256은 지시된 `d0d1a749afb6a6f894de1bb4263c9d67dd1e3b2d1a35bf1b5fd38d8948c656b0`과 일치한다. manifest가 잠근 관계 연구 보고서·계수 파일과 스타일 이력 피처 파일의 SHA도 모두 대조했다. 원천 파일은 읽기만 했다. 계산 상세와 race key는 [독립 재구성 receipt](outputs/core_reconstruction_receipt.json)에 있다.

추가로 피처·라벨·점수 키와 이력 시점을 확인했다. 고정 feature table의 평가 17,412개 `api_record_id`가 runner label과 일대일로 맞고, `finish_position <= 3`은 runner의 `y_top3`와 17,412행 모두 일치했다. 각 연도 저장 `evaluation_scores.parquet`도 같은 `api_record_id`로 정확히 덮는다. `history_cutoff`는 모든 행에서 경주일 −2일이고, 최신 이력이 cutoff 뒤에 있는 행은 0건이었다. 상세는 [입력 시점 receipt](outputs/source_timing_receipt.json)에 남겼다.

세 과거 스타일 요약은 과거 동일거리 최대 5회 실제 슬롯의 품질 선택 S1F·4C·G1F 상대 위치로부터 나온다. 상대 위치는 `(quality rank−1)/(N_started−1)`이며 결승 순위나 속도가 아니다. 두 변화량은 S1F→4C와 4C→G1F 지점 간 rank 차이다. 해당 입력 계약은 슬롯의 valid-time·quality status를 적용하고 지원 수 `n=0`이면 평균을 NULL로 두며 더 오래된 슬롯으로 대체하지 않는다. 이번 source join에서도 각 스타일 열 2,545/2,546/2,541행이 `n=0`·NULL이고, 지원 수와 평균의 결측 계약 위반은 없었다. 1300m의 S1F는 2C 뒤 측정이라는 원래 구간 정의가 유지된다.

## 독립 재구성 결과

1,779경주·17,412 출전행·269 경주일을 확인했다. race_id는 양쪽 CSV에서 완전히 일치하고 경주별 실제 Top3 라벨은 정확히 세 마리였다. 중복 경주·출전 키와 roster 밖 티켓은 없었다. 실제 집합 포함 여부를 다시 계산한 결과 기준 팔 407회, 후보 팔 423회였다.

| 실제 정답 포함 상태 | 경주 수 | 정의 |
|---|---:|---|
| gained | 50 | 후보 적중, 기준 미적중 |
| lost | 34 | 기준 적중, 후보 미적중 |
| bothhit | 373 | 두 팔 모두 적중 |
| bothmiss | 1,322 | 두 팔 모두 미적중 |

여섯 티켓의 무순서 집합은 1,077경주에서 달라지고 702경주에서 같았다. 나열 순서까지 같았던 경주는 244, 달랐던 경주는 1,535였다. 티켓 교체 수와 실제 정답 포함 상태 변화 수는 서로 다른 분모의 진단이다.

거리별로는 사례 수와 분모를 분리했다. `net`은 gained−lost 원시 경주 수이고, 마지막 열은 같은 차이를 해당 거리의 전체 경주 100건당 환산한 값이다.

| 거리 | 전체 경주 | gained | lost | net | 100경주당 net |
|---:|---:|---:|---:|---:|---:|
| 800m | 152 | 3 | 2 | +1 | +0.66 |
| 900m | 251 | 4 | 3 | +1 | +0.40 |
| 1000m | 508 | 14 | 15 | −1 | −0.20 |
| 1110m | 482 | 11 | 4 | +7 | +1.45 |
| 1200m | 262 | 12 | 7 | +5 | +1.91 |
| 1300m | 63 | 5 | 0 | +5 | +7.94 |
| 1400m | 52 | 1 | 3 | −2 | −3.85 |
| 1610m | 9 | 0 | 0 | 0 | 0.00 |

앞서 1110m·1200m·1300m가 많아 보인다는 초기 표현은 ‘가중치’로 읽힐 수 있어 수정한다. 이는 거리별 원시 차이며 조정 효과가 아니다. 1300m의 높은 100경주당 값은 63경주와 5 gained/0 lost에서 나온 작은 표본 비율이다. 1000m는 14/15로 순변화가 −1이다. 연도·거리 구성이 다른 만큼 전체와 같은 신호로 볼 수 없다.

연도별 전체 net도 2024년 −3(12 gained/15 lost, 637경주), 2025년 +15(25/10, 654경주), 2026년 9월 19일까지 +4(13/9, 488경주)로 다르다. 1000m에서는 2024년 −1(4/5, 170경주), 2025년 +3(8/5, 196경주), 부분 2026년 −3(2/5, 142경주)였다. 따라서 거리별 전체 평균만으로 안정적 관계를 주장하기 어렵다. 거리·연도별 교차 셀의 작은 분모도 함께 보아야 한다. 교차 셀 전체 원시 집계는 [독립 output receipt](outputs/independent_analysis_output_receipt.json)에 있다.

## 분석 A 산출물 독립 대조

현재 고정된 분석 A 산출물 13개의 receipt hash를 확인했고, 1,779 race ledger의 labels·true-set ticket·hit class를 원천 CSV에서 다시 만들었다. `condition_summary.csv`의 34개 전체/연도/월/거리/등급/field-size 그룹의 분모, hit 수, 비율, paired-date bootstrap CI를 모두 재계산했다. 2,000회·seed `20261008` interval의 최대 절대 차이는 `3.85e-13`이었다. 이 구간은 많은 pointwise 비교에 대한 family-wise 보정을 하지 않으며 확증적 유의성 검정이 아니다.

saved score·parameter·feature를 고정 원천에서 읽고 이전 C 독립검증 모듈의 결정적 함수로 후보 관계 피처를 다시 계산했다. actual true set의 1,779×11 기여는 A 표와 최대 `5.0e-13` 차이였고, contribution 합과 저장 관계 에너지의 최대 차이는 `2.3e-16`이었다. true-set/U 경계 비교는 1,779행 전부에서 `E(T*)−E(U) = [E0(T*)−E0(U)] + Σ[11 beta-term contrast]`를 만족했고, 최대 행별 잔차는 `8.9e-16`이었다. true set이 후보 top six 안이면 U는 원 rank 7, 밖이면 U는 rank 6이다. 이는 결과 순위를 알아야 선택 가능한 사후 진단이다.

rank 6−rank 7 에너지 exact tie는 baseline 83/1,779, candidate 81/1,779였고, 절대 여유 `<=1e-12`는 각각 83과 84였다. overall rank-boundary energy margin 중앙값은 baseline `0.0442574`, candidate `0.0492839`였다. gained/lost의 후보 중앙값은 각각 `0.0279343`/`0.0311634`였고, baseline은 `0.0351802`/`0.0241607`이다. 각 중앙값은 별도 요약치다. 중앙값끼리 덧셈 등식을 주장하지 않는다. 이 분포는 경계가 작은 경우 관계항을 끄면 된다는 규칙의 증거가 아니다.

분석 A의 mechanical example 9개도 계획의 연도별 선택 규칙과 race_id tie-break로 다시 골라 동일함을 확인했다. gained/lost 사례를 설명에 쓰면 50/34의 완전한 ledger와 함께 보아야 하며, 예시 자체는 효과를 대표하지 않는다.

## 보조 컨텍스트의 출처·시점

현재 result-side context 보조표는 `api_record_id` 기준 17,412/17,412 exact join, 1,779/1,779 race coverage, 실제 Top3 roster parity를 통과했다. race-level moisture/band/track은 경주 내 상수이며, band 분모는 건조 783, 다습 389, 불량 125, 양호 297, 포화 185다. 현재체중과 부담중량은 runner 수준 값이라 race 결과와 비교할 때 먼저 경주당 한 descriptor로 집계해야 한다. 보조표에는 raw source text와 누락/분포 정보를 보존했다. 재현 결과는 [supplemental context receipt](outputs/supplemental_context_receipt.json), 원천 설명은 [`CONDITION_AVAILABILITY_AUDIT.md`](../20261010_joint_gain_loss_context_v1/CONDITION_AVAILABILITY_AUDIT.md)에 있다.

이 exact join은 event record 연결을 증명하지만 예측 시각의 공개·확정 시각을 증명하지 않는다. 당일 체중·수분도·track band는 결과 측 사후 컨텍스트다. 부담중량·기수·마번·등급·실제 field size도 당시 선언/수정 이력이 입증되지 않았다. 이 값들은 이번 조건분석에서 prospective predictor로 취급하면 안 된다. `horse_number`는 physical gate가 검증된 값이 아니다. `field_n`은 scratch 반영 후 결과 레코드의 실현 참가 수일 수 있다. 29개 기수별 규칙이나 현재 기수 조건 선택은 계산하지 않았다.

## 해석 경계

84개 gained/lost 경주는 **실제 결과와 두 팔의 적중 상태를 보고 선택한 사후 집합**이다. 이 집합 내부의 조건 빈도나 관계 기여를 미래 경주 선별 규칙으로 읽을 수 없다. 조건표는 전체 1,779경주의 조건별 분모를 함께 두어야 한다. 조건 정의가 84건을 보고 만들어졌다면 탐색적 사후 설명으로 표시해야 한다.

실제 Top3 집합의 에너지, 전체 조합 중 순위 이동, 6위 경계와의 거리는 정답을 알아야 정해지는 **사후 진단**이다. 분석에서는 true set이 후보 상위 6개에 있으면 다음 최고 비정답 조합(원 rank 7), 밖에 있으면 후보 rank 6을 비교 대상으로 삼아야 한다. `E(true)−E(rival)`은 고정된 기준 점수 차와 true/rival 각각의 11개 관계항 기여 차로 분해해야 한다. true-set 에너지 자체의 부호만으로 순위 이동을 설명할 수 없다. 미래 입력은 complete whole-field 명단을 사용해야 하지만 이 역사 표본의 공개 예측 시각과 당시 최종 declared roster는 복구되지 않았다. 실제 정답 3두를 조건으로 사용한 계산을 사전 예측 피처나 게이트로 승격하면 안 된다. `n=0`·NULL은 결측 지원 상태로 남겨야 하며 0 관측으로 대체하면 안 된다.

평가 경주와 라벨은 이전 연구에서도 재사용된 후향 개발 자료다. 하위집단의 작은 표본과 다중 비교를 반영해야 하며, 연도·거리 구성 차이는 전체 분모와 날짜 단위 불확실성으로 분리해 보여야 한다. 거리만으로 향후 rule을 만들거나 운영 반영을 주장할 근거는 없다.

## 검토 상태

검토 receipt는 원천 잠금·cohort, 84개 그룹, 조건표와 bootstrap, 11항 true-set 기여, 1,779개 U 대조, 경계 여유, mechanical case 선택, 그리고 보충 context·정정표·교차표의 독립 재집계를 PASS했다. 상세는 [core 독립 검증 receipt](outputs/independent_analysis_output_receipt.json), [supplemental/addendum 독립 검증 receipt](outputs/independent_supplemental_verification_receipt.json), 원천 경계 재검산은 [boundary receipt](outputs/saved_boundary_reference.json)에 기록했다. v2 actual Top3 summary의 feature/unit 식별자와 18개 수치 행을 다시 대조했다. 최초 `all_1779` 라벨 오류가 있는 표와 feature 이름이 없던 첫 정정표는 보존·명시적으로 superseded 상태이며 현재 보고 표로 사용하지 않는다. 초기 run의 계약 바이트는 `contracts_as_run/`에서 원 receipt 해시와 대조했고, 명확화된 계약은 별도 correction receipt에 연결했다. A의 최종 README는 확인했으며 A의 최종 output manifest는 아직 생성 대기다. 이 독립 검토는 중앙 publication 승인이나 운영 반영 승인이 아니다.

저장소 루트에서 `./.venv/bin/python jeju/research/20261010_joint_gain_loss_review_v1/reconstruct_core.py`, `./.venv/bin/python jeju/research/20261010_joint_gain_loss_review_v1/audit_feature_timing.py`, `./.venv/bin/python jeju/research/20261010_joint_gain_loss_review_v1/audit_supplemental_context.py`, `./.venv/bin/python jeju/research/20261010_joint_gain_loss_review_v1/reconstruct_saved_boundaries.py`, `./.venv/bin/python jeju/research/20261010_joint_gain_loss_review_v1/validate_analysis_outputs.py`, `./.venv/bin/python jeju/research/20261010_joint_gain_loss_review_v1/validate_supplemental_outputs.py`를 실행하면 된다. 각 도구는 이 review 폴더 내부에 receipt를 기록한다. 분석 A 코드 자체를 실행하거나 변경하지 않는다.
