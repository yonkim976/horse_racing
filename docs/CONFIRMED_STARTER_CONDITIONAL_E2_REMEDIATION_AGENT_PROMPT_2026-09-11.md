# E2 보완 담당자 지시서

/Users/kimyongjin/Desktop/horse_racing에서 E2-R1~R3 보완만 수행한다. 먼저 CONFIRMED_STARTER_CONDITIONAL_E2_INDEPENDENT_REVIEW_2026-09-11.md를 읽는다. A 분모와 라벨은 독립 검증에 통과했지만 선택 predictor의 실제 결함으로 학습 입력 승인은 보류됐다.

기존 E2 dataset/manifest/report/log, 이전 E1·canonical·run 및 production DB를 보존한다. dirty 사용자·동시 작업을 되돌리지 않는다. 실제 결과 조회는 2026-05-31 이하로 제한하고 미래 반례는 합성 자료로만 만든다. 새 모델 학습·성능 비교·운영 연결은 하지 않는다.

## R1: 모든 말의 Elo 상대값을 실제 A에서 계산

현재 DNF/실격 48행의 선택 feature ability_elo_vs_field가 모두 0이다. 각각을 단독 합성 race ID로 계산한 값이 최종 predictor에 남았다. 정상완주 401행도 A가 아닌 N의 상대 평균을 유지한다.

- 개별 사전 Elo/state와 현재 race field 파생값을 분리한다. A 전체의 개별 Elo가 완성된 뒤 실제 race ID의 상대 말 평균으로 ability_elo_vs_field를 재계산한다.
- 모든 A 행에 같은 산식을 적용한다. 개별 Elo 상태 갱신을 막기 위한 null anchor 격리는 유지할 수 있으나 그 합성 field에서 구한 상대값은 사용하지 않는다.
- 다른 history module의 field 파생 열도 같은 문제가 없는지 확인한다. 운영 ability 모듈의 기본 동작을 임의로 바꾸지 않는다.
- build_predictors 진입점에서 고정 A·고정 사전 이력으로 정상완주/DNF/실격 처리 경로를 바꾸는 반례를 검사한다. 단순히 결과 열을 drop하는 함수만 테스트하지 않는다. 선택 136개 predictor와 field 파생값이 결과 상태를 인코딩하지 않아야 한다.
- 현재 및 이후 결과·구간을 바꿔도 대상 predictor가 불변인지 검사한다. DNF anchor가 다른 말/미래 대상의 과거 상태를 갱신하지 않는 것도 확인한다.
- 실제 19361의 ability_elo_vs_field는 현재 개별 Elo 기준 A 재계산으로 약 +25.532652가 된다. 이 사례와 전체 A 행의 산식을 독립 검증한다. 특정 예시 값을 하드코딩하지 않는다.

## R2: 결측을 구분한 비교와 원인 검증

- _value_equal의 한쪽 null과 숫자를 같다고 처리하는 결함을 수정한다. 양쪽 null만 동일하고, null↔값은 변경이다. 유한 float tolerance 및 NaN/Inf 계약을 명시하고 테스트한다.
- 수정 전 제출본의 누락 사례는 exact_distance_top3_rate_race_z, entry 19362/19363/19366/19369, null→-0.447213595499958이다. 기존 허용 오차에서 정확한 변경 수는 9,278셀이다. R1 수정 후 최종 수는 달라질 수 있다.
- 'field-dependent 목록에 있으면 설명 완료' 방식을 제거한다. 개별 사전 입력을 고정한 N/A field 재계산 통제 또는 독립 산식으로 변화량을 설명한다. A/N 차이가 없는 경주의 선택 feature도 전수 확인한다.
- 변경 로그에 null 전환·유한값 변화·허용오차 내 차이, field 확대 효과·의도된 생성 경로 보완·설명 불가를 구분한다. 설명하지 못한 선택 predictor 차이가 남으면 학습 가능으로 제출하지 않는다.

## R3: 실행 가능한 calibration 명세

현행 lightgbm trainer는 calibration 구간으로 보정기를 적합하지만 auto 후보 선택은 development validation log loss로 한다. 보고서의 'validation으로 재선택하지 않음'과 다르다.

이번 범위에서는 기존 trainer를 바꾸지 말고, 후속 비교가 기존 auto를 그대로 사용하며 development validation이 후보 선택과 평가에 모두 사용된다고 정확히 정정한다. 미래 test나 선택과 독립된 평가라고 표현하지 않는다. 후보·선택 기준·각 데이터 사용 역할을 양쪽 모델에 동일하게 명세한다. 이번에 학습·후보 탐색은 실행하지 않는다.

## 제출물

1. 새 버전 E2 보완 dataset·manifest. 기존 제출본은 덮어쓰지 않는다. A 15,579행·1,488경주, train 12,528/validation 3,051, 48행 라벨·mask와 136개 선택 feature 계약을 다시 검사한다.
2. docs/CONFIRMED_STARTER_CONDITIONAL_E2_REMEDIATION_2026-09-11.md: 수정 전/후 반례, field 산식 검증, N/A 통제 결과, 정정한 calibration 명세.
3. data/logs/confirmed_starter_conditional_e2_remediation_20260911.json: 독립 키·상태·feature 변경 근거·현재/미래 불변성·source/code/data 해시와 보존 근거.
4. 보완 builder/연구 함수와 실제 진입점 회귀 테스트. 관련 검사와 전체 pytest/Ruff/diff-check를 분리 보고한다.

독립 재검증 후 다음 단계로 넘어간다. 이번 보완에서 정상완주 조건부 과거 이력 정책이나 성별 PIT까지 확장하지 않는다. 과거 A는 계속 retrospective actual-starter conditional이며 역사적 F_t가 아니다.
