# E7-B 최근 출발별 이력 비교 protocol 초안 — 실행 금지

상태: **E7-A 독립 검증과 별도 실행 지시 전 학습 금지.** 이 문서는 사전 설계일 뿐 E7-B 실행 승인이 아니다.

## 가설·후보

후향 서울 H1 A 15,579행·1,488경주의 기존 136열을 기준으로, 최근 실제 출발 3회의 개별 관측·경과일이 추가 정보를 주는지 시험한다. 후보는 `BASE_136`과 `SEQUENCE_12_AUDITED` 두 개로 제한한다. 후자는 E7-A에서 감사한 각 슬롯의 canonical S1F 상대지수, canonical 마지막200m 상대지수, 출발별 보정 speed figure, 양수 경과일 12열을 기존 136열 뒤에 붙이는 잠정안이다. 최종 실행 열 목록은 E7-A 독립 검증에서 null·원천·기존 열 중복 진단을 승인한 뒤 봉인한다. 성능을 보며 열을 제거·교체하지 않는다. 중량, 등급, 레이팅, 배당, 심판문서, 신경망, 새 objective/seed/ensemble은 추가하지 않는다.

3개 슬롯은 전 경마장 동일 말의 target일보다 엄격히 이전인 최근 실제 출발을 날짜 역순으로 선택한다. DNF·실격도 슬롯을 차지하고 미출주는 제외한다. 더 최신의 미확정 출발 또는 같은 날 복수 출발로 순서를 확정할 수 없으면 그 슬롯과 이후 오래된 슬롯은 null로 격리한다. 구간·speed 관측이 없더라도 실제 출발일이 확인되면 `days_ago`는 유지한다. 12개 수치 이외의 상태·원천 metadata는 학습하지 않는다. 기존 136열·라벨·A 출전집합은 두 후보가 공유한다.

## 분할과 fit 예산

E6-B에서 사용한 F1/F2/F3의 12개 날짜 partition, 행·경주·경주일 분모와 평가 합계 4,218행·407경주를 그대로 사용한다. F1/F2/F3 평가 종료는 각각 2025-07-27, 2025-11-02, 2026-02-28이다. 2026-03~05 성능을 새로 시험하지 않고 2026-06-01 이후 실제 결과를 읽지 않는다. 407경주는 반복 사용된 개발 자료이지 새 독립 test가 아니다.

각 fold의 encoder는 selector fit 행에서만 적합하고 기존 136열의 매핑·행렬·키·group·label은 두 후보에서 동일해야 한다. 두 후보 모두 E6-B의 고정 custom weighted Bernoulli BINARY(1/field_size, seed42, learning rate .03, leaves31, min leaf80, feature fraction .8, L2 1, boost_from_average=false)를 사용한다. selector는 tune 경주 soft-label CE로 최대1,200round/patience80 조기 종료하고 fit+tune를 best iteration만큼 처음부터 refit한다. 별도 calibration에서 기존 beta endpoint/root로 T를 구하며 두 arm의 준비·진단이 통과한 뒤 E6-B 공통 gate를 통해서만 평가한다. 후보2×fold3×selector/refit으로 예정 fit은 **12회**다. 실패 시 해당 fold와 통합 비교를 중단하며 보정 경계를 넓히거나 추가 seed·설정·재학습을 시도하지 않는다. **E7-A 단계의 실제 fit은 0회다.**

## 평가·해석 경계

주 지표는 보정 raw margin의 stable log-domain 경주 동등가중 winner-set NLL이다. soft-label CE, entry-equal binary NLL(epsilon1e-15), Brier, 확률 동점 기대 Top1/3/5, 공식 동착·동점·확률합·비유한값 진단을 모두 저장한다. `SEQUENCE_12_AUDITED − BASE_136`의 fold별·통합 paired race 및 race-date cluster bootstrap을 각5,000회·seed20260911로 계산한다. 통합 주 손실은407경주 평균, entry 지표는4,218행 기준이다. 모든 fold와 TopK 방향을 보고하고 유리한 시기·원천 비결측 하위집합을 사후 선택하지 않는다.

저장 예측에 조건부인 CI는 재학습·가설 선택 불확실성을 포함하지 않는다. 후향 A 집합과 사후 수집 원천은 역사적 T-30 공개/PIT 보증이 아니다. 새 슬롯 정책과 관측 묶음이 동시에 바뀌므로 차이가 생겨도 순서 정보만의 순수 효과, 개별12열의 기여 또는 인과효과로 분리하지 않는다. 운영 승격·champion 변경은 별도 결정이다.
