# E2 보완 v2 독립 검증

판정: **Elo·값 비교·calibration 명세 보완은 통과. 말×기수 이력의 실제 결함 E2-H1이 남아 학습 승인은 보류.** 검증일은 2026-09-11 KST다. 검증자는 운영 코드·DB·기존 산출물을 변경하거나 모델을 학습하지 않았다. 실제 결과 조회는 2026-05-31 이하로 제한했다.

## 통과한 항목

- 전체 pytest: 448 passed, 2 warnings, 12.83초. 관련 Ruff/format 통과. 기존 UI EOF 공백은 별도 실패로 남음.
- 제출 dataset·source·DB 해시 일치. A 15,579행 및 독립 키·분할·라벨 계약 유지.
- 구현의 검증 함수를 호출하는 대신 Python statistics, 직접 상대 순위 계산, 상대 말 평균으로 38개 field 산식을 전수 대조했다. 불일치 0, 최대 수치 차이 4.610134496374485e-11.
- A에서 저장한 개별 사전 입력을 N으로 제한해 동일 산식을 다시 계산한 뒤 기존 N과 대조했다. 불일치 0, 최대 수치 차이 6.135980612498315e-12. field 확대 효과를 독립적으로 확인했다.
- 1e-10 절대 허용오차에서 N 공통행의 변경은 9,668셀, null→값 4개, 값→null 10개, 확대 42경주 밖 변경 0이다.
- 1e-12로 낮추면 경주 3858의 ability_elo_context_race_z에서 11개 추가 차이가 발생하며 최대 약 4.229e-11이다. 제출된 오차 설명과 일치한다. 결측과 비유한값에 이 tolerance를 적용하지 않은 정책은 적절하다.
- 현행 auto calibration이 development validation을 후보 선택과 지표 산출에 함께 사용한다는 정정도 실제 trainer와 맞는다.

## E2-H1 / P1: DNF/실격의 말×기수 이력이 사라진다

영향 열은 모두 선택된 136개 predictor에 포함된다.

- horse_jockey_starts
- horse_jockey_wins
- horse_jockey_first

제출된 DNF/실격 48행은 세 값이 전부 (0, 0, 1)이다. 그러나 target 날짜보다 엄격히 이전인 정상완주 이력만 사용해 DB를 별도로 집계하면 아래와 같다.

| 검증 | 결과 |
|---|---:|
| 전체 A 검사 | 15,579행 |
| 실제 값이 잘못된 출전행 | 30행 |
| 잘못된 선택 feature 셀 | 71셀 |
| horse_jockey_starts 오류 | 30셀 |
| horse_jockey_wins 오류 | 11셀 |
| horse_jockey_first 오류 | 30셀 |
| 정상완주 행 오류 | 0 |

예시:

| entry | 저장 starts/wins/first | 과거 정상완주 이력 기대값 |
|---|---|---|
| 19361 | 0 / 0 / 1 | 1 / 0 / 0 |
| 19785 | 0 / 0 / 1 | 3 / 0 / 0 |
| 20871 | 0 / 0 / 1 | 1 / 1 / 0 |
| 21023 | 0 / 0 / 1 | 4 / 1 / 0 |

이 검증은 과거 DNF를 이력에 새로 포함한 것이 아니다. 기존 정책 그대로 completed, 정상착순 1~89, 같은 horse_id/jockey_id, race_date < target date로 세었다.

### 원인

features/people.py:217~245의 _add_combo_features는 정상완주 past_results에서 각 행의 shift/cumulative 조합 이력을 만든 다음, 현재 race_entry_id로 다시 join한다. DNF/실격 target는 정상완주 past_results에 없으므로 join이 실패하고 0으로 채워진다. 실제 과거 조합이 없어서 나온 0이 아니다.

confirmed_starter_dataset.py:423은 people을 포함한 _FIELD_MODULES에 원래 sources를 그대로 전달한다. 기존 anchor 보완은 _HISTORY_MODULES에만 적용되어 이 세 열까지 복원하지 못했다. Elo 상대값 결함과 별도로 남아 있던 anchor 의존 경로다.

### 실제 모듈 재생

기존 상태 교환 테스트는 tests/test_confirmed_starter_dataset.py:220에서 _apply_modules를 fake 함수로 교체한다. 호출 경로가 outcome_state 문자열에 직접 분기하지 않는지는 검사하지만, 실제 people feature 계산의 결과행 의존성은 검사하지 못한다.

검증자는 fake 없이 race_id=1849의 실제 11행을 build_predictors에 넣었다.

1. 2025-01-26까지의 source를 사용한 baseline의 선택 predictor는 저장 dataset과 일치했다.
2. A와 과거 이력은 유지하고 대상 당일 result/section을 source에서 제거하면 정상완주 5행의 horse_jockey_starts/first가 바뀌었다. 이는 target 결과행의 존재가 feature lookup에 필요하다는 증거다.
3. 대상 말들의 과거 경주와 상대 말들로 줄인 실제 source fixture에서도 같은 두 열의 변화가 재현됐다. 이 fixture에서는 결과 상태/값만 바꾸는 검사에 선택 feature 변화가 없었다. 문제는 문자열 분기만이 아니라 source에서 target 결과행이 있느냐는 점이다.

전체 DataFrame의 byte/bit 동일성까지 승인하는 검증은 아니다. 재계산에는 기존 비선택 열 및 미세한 수치 비결정성이 남을 수 있으며, 선택 predictor는 명시된 null 정책과 1e-10 허용오차로 검사한다.

## 요구하는 한정 보완

E2 연구 경로에서 세 조합 feature를 모든 A 행에 대해 같은 사전 이력 질의로 계산한다. target의 race_entry_id가 정상완주 이력에 존재해야 한다는 조건을 없앤다. 과거 DNF 제외 정책은 유지하고, target 날짜 당일·이후 이력은 제외한다. jockey_id 결측과 실제 첫 조합은 구분한다.

실제 feature 모듈을 사용하는 회귀를 추가한다. 고정 A·같은 과거 이력에서 target 결과행의 추가/삭제, 결과 상태 교환, 현재/합성 미래 결과 변경이 대상 predictor에 영향을 주지 않아야 한다. _apply_modules를 대체한 테스트만으로 완료 판정하지 않는다.

기존 v2를 보존하고 새 버전 dataset/manifest/log를 제출한다. 15,579행에 대한 독립 말×기수 집계와 38개 field 산식·9,668셀 설명을 다시 확인한다. 현재 정상완주 0오류라는 결과를 감안하면 이번 결함의 직접 수정은 특수 상태의 71셀에 해당한다. 다른 변화가 발생하면 이유를 별도로 규명한다.

이번에는 위 E2-H1을 보완하고 재검증에 제출한다. 통제 학습은 아직 실행하지 않는다. 담당자 지시서는 CONFIRMED_STARTER_E2_H1_AGENT_PROMPT_2026-09-11.md에 있다.
