# E2 독립 검증: 데이터셋 보완 후 재검증

검증일: 2026-09-11 KST. 판정: **A 집합·라벨·기본 보존 검증은 통과하지만, 선택 predictor에 실제 결함이 있어 학습 입력 승인은 보류한다.** 검증자는 제출 데이터 전수 대조와 코드·회귀 검사를 수행했다. 전체 builder 재실행·학습·운영 코드/DB 수정은 하지 않았다. 실제 결과는 2026-05-31 이하로 제한했다.

## 1. 확인한 성과

- A 15,579행·1,488경주의 키가 E1 v2 독립 증거의 실제 출발 키와 정확히 일치한다.
- train 12,528행, development validation 3,051행 및 DNF/실격 48행의 비입상 라벨·순위/완주시간 mask를 확인했다.
- 136개 선택 feature 이름·순서·hash가 참조 run과 정확히 일치한다.
- 저장 dataset 및 manifest에 기록된 5개 source 해시가 현재 파일과 일치한다.
- 전체 pytest: 444 passed, 2 warnings, 13.10초. 관련 Ruff/format: 통과. 전체 diff-check에는 기존 web/racecourse.py:347 EOF 빈 줄 1건이 남는다.
- A를 retrospective confirmed-starter conditional로 구분하고 역사적 F_t와 혼용하지 않은 것은 타당하다.

기존 테스트가 녹색인 것과 아래 실제 데이터 반례를 통과하는 것은 별개다.

## 2. E2-R1 / P1: 합성 1마리 경주의 Elo 상대값이 결과 상태를 반영한다

위치: src/horse_racing/analysis/confirmed_starter_dataset.py:350~414, 특히 360~373 및 history_names 교체. 상대값의 계산 원천은 features/ability.py의 _pre_race_ratings다.

DNF/실격은 outcome_state에 따라 별도 경로로 들어가고 각 말에 서로 다른 음수 synthetic race ID를 부여한다. 이는 과거 Elo 상태 갱신을 피하려는 목적에는 맞지만, ability 모듈은 같은 race ID의 상대 말 평균으로 ability_elo_vs_field도 함께 계산한다. 혼자 있는 합성 경주에서는 이 값이 항상 0이다. 그 결과가 선택 predictor에 그대로 저장됐다.

실제 제출 파일에서 **DNF/실격 48행의 ability_elo_vs_field가 모두 0**이다. 해당 열은 136개 선택 feature에 포함된다. 정상완주 15,531행 중 0인 행은 109개다. 따라서 현재 생성 방식은 사후 DNF/실격 상태와 강하게 연결되는 인위적 패턴을 predictor에 만든다. 학습 전이므로 이미 모델 성능이 부풀었다고 주장하지는 않지만, 이 파일로 학습하면 안 된다.

개별 사전 Elo는 유지하고 실제 A의 상대 말 평균으로 독립 계산했다.

    expected_vs_A = Elo_i - (sum(Elo over A) - Elo_i) / (|A| - 1)

예시:

| race_entry_id | 저장값 | A 기준 값 |
|---|---:|---:|
| 19361 | 0 | +25.532652 |
| 19785 | 0 | -54.075440 |
| 19928 | 0 | -44.251892 |

절대 오차 1e-9 기준 전체 **448행**이 A 기준과 다르다: 정상완주 401행, DNF 46행, 실격 1행. 최대 오차는 약 62.086103이다. DNF 한 행은 A 기준도 0이라 수치상 일치하지만 합성 경주 계산 경로는 동일하다. 정상완주 행의 상대값도 기존 정상완주 집합 N의 평균을 유지하므로 A 계약에 맞지 않는다.

요구:

- 개별 사전 Elo/상태 계산과 현재 field 상대값을 분리한다. 모든 A 행의 개별 Elo를 모은 뒤 동일한 실제 race ID의 A를 기준으로 상대값을 계산한다.
- 합성 anchor에서 파생된 field 통계를 최종 predictor에 복사하지 않는다. 다른 history 모듈 안의 field 파생 열도 확인한다.
- 기존 _predictor_base 결과 열 제거 테스트와 form/style만 검사한 테스트로는 충분하지 않다. 고정 A·고정 사전 이력을 사용해 정상완주↔DNF/실격 경로를 바꿔도 실제 build_predictors의 선택 열이 불변인지 검사한다.
- 현재·이후 결과 변경은 해당 대상의 predictor를 바꾸지 않아야 한다. 이후 경주의 과거 이력 정책 변화와 대상 당일 검증을 구분한다.

## 3. E2-R2 / P2: null 변화 누락과 변경 원인 판정 부족

위치: 같은 파일 455~493행.

_value_equal은 float 차이에 fill_null(0)을 적용한다. 따라서 null과 2.0, 1.0과 null을 모두 같다고 반환한다. 직접 실행 결과 [null, 1.0, null] 대 [2.0, null, null]의 비교는 [True, True, True]였다.

실제 N 공통행에서 exact_distance_top3_rate_race_z의 4개 null→유한값 전환이 누락됐다. race_id=1849, race_entry_id=19362/19363/19366/19369이며, 기존 null에서 새 -0.447213595499958로 바뀌었다. 기존 1e-12 오차 허용을 유지하면서 null 상태를 별도로 대조하면 현재 제출본의 변경 수는 **9,274가 아니라 9,278셀**이다. pace_pressure의 null 전환 10개는 문자열 경로에서 이미 집계됐으므로 이 4개와 혼동하지 않는다.

또한 field-dependent 이름 목록에 있으면 원인을 검사하지 않고 전부 field_expansion으로 분류한다. 이는 feature 종류를 설명할 뿐, 변화가 오직 A 확대 때문에 발생했음을 증명하지 않는다. 특히 R1의 ability_elo_vs_field는 목록에도 없고 기존 N에서 값이 그대로여서 'unexplained=0'이 잘못된 A feature를 발견하지 못했다.

요구:

- 양쪽 null만 동등하게 처리하고 한쪽만 null이면 변경으로 센다. 유한 float에만 명시한 tolerance를 적용하고 NaN/Inf 정책도 고정한다.
- null→값, 값→null, 양쪽 null, float 오차, 문자열/정수 변화를 검사한다.
- feature 이름 whitelist를 인과 설명으로 사용하지 않는다. 동일한 개별 사전 feature를 둔 채 field N/A를 바꿔 field 파생 열을 재계산하는 통제 또는 동등한 독립 산식 검증을 추가한다.
- 변경 경주가 A/N 차이가 있는 경주인지 확인하고, 필드와 무관한 선택 열 및 영향 없는 경주에서 추가 변화가 없는지 대조한다. 의도된 경로 보완과 설명 불가 변화도 구분한다.
- R1 수정 이후 새 데이터셋으로 변경 수와 원인 근거를 다시 기록한다. 9,278은 수정 전 제출본의 독립 재집계이며 최종값을 미리 강제하는 숫자가 아니다.

## 4. E2-R3 / P2: 사전 명세의 calibration 설명이 현재 trainer와 다르다

위치: E2 보고서 97행 및 src/horse_racing/analysis/lightgbm_model.py:397~418.

보고서는 auto calibration이 같은 calibration split만 사용하며 validation으로 재선택하지 않는다고 명시한다. 현재 trainer는 calibration split에서 각 보정기를 적합한 뒤, valid에 모든 후보를 적용하고 valid log loss가 가장 낮은 후보를 선택한다. 보정기 적합과 후보 선택은 서로 다르다.

이번에 학습하지 않았으므로 현재 E2 predictor 결함의 원인은 아니다. 그러나 후속 실행을 승인하기 전 비교 명세를 실제 실행 규칙과 맞춰야 한다.

요구: 기존 auto를 그대로 사용할 경우 validation을 후보 선택에도 쓰는 개발 평가라고 정확히 명시한다. validation을 선택에서 분리하려면 고정 방식 또는 훈련 기간 내부의 선택 절차를 먼저 사전 명세하고 이후 연구용 실행 경로에서 구현해야 한다. 두 설명을 동시에 유지하지 않는다. 이번 보완에서 실제 모델 학습은 하지 않는다.

## 5. 다음 조치

기존 E2 제출본과 로그를 보존하고 E2-R1~R3만 보완한 새 버전 dataset/manifest/log를 제출한다. 운영 기본 경로는 바꾸지 않는다. 현재 데이터로 N-vs-A 학습을 시작하지 않는다. 구현 담당자용 지시서는 CONFIRMED_STARTER_CONDITIONAL_E2_REMEDIATION_AGENT_PROMPT_2026-09-11.md에 있다.
