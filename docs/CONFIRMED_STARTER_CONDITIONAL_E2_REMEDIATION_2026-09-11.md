# Confirmed-starter conditional E2 remediation

검증 기준일: 2026-09-11 KST

범위: E2-R1~R3만 보완

판정: **독립 재검증용 보완 후보 제출. 재검증 전 학습 입력 승인·다음 단계·운영 승격은 하지 않는다.**

## 범위와 보존

- 실제 결과와 개발 평가 범위는 2025-01-04~2026-05-31로 고정했다. 2026-06-01 이후 실제 행은 조회·탐색·평가하지 않았다.
- A는 계속 사후 확인된 actual-starter conditional 집합이며 역사적 T-30 출전집합 `F_t`가 아니다.
- 기존 E2 dataset/manifest/report/log, E1·canonical·run, production DB는 수정하지 않았다.
- 새 모델 학습, 성능 비교, calibration 후보 탐색, 운영 연결은 수행하지 않았다.
- 정상완주 조건부 과거 이력 정책과 성별 snapshot PIT 문제는 이번 범위 밖으로 유지했다.

## R1. 실제 A 전체를 사용한 Elo 상대값

수정 전에는 DNF/실격용 null anchor를 각 1마리 synthetic race로 격리하면서 그 경주의
`ability_elo_vs_field=0`까지 최종 predictor에 복사했다. 이 때문에 특수 상태 48행이 전부 0이었고,
정상완주 401행도 A가 아닌 N 평균을 사용했다.

개별 사전 Elo/state 계산과 현재 field 파생을 분리했다. null anchor 격리는 Elo 상태 갱신 방지에만
사용하고, 모든 A 행의 `ability_elo_global`이 완성된 뒤 실제 `race_id`별로 다음 식을 다시 계산한다.

```text
ability_elo_vs_field_i
  = Elo_i - (sum(Elo over actual A) - Elo_i) / (A_count - 1)
```

전수 결과:

| 검사 | 결과 |
|---|---:|
| A 공식 대조 행 | 15,579 |
| 절대오차 1e-12 초과 | 0 |
| 기존 E2 대비 수정 행 | 448 |
| 기존 특수 상태 0 | 48/48 |
| 수정 후 특수 상태 0 | 1/48 (A 공식상 실제 0) |
| entry 19361 수정 전 | 0 |
| entry 19361 수정 후 | +25.532651761296847 |

entry 19361의 값은 구현에 상수로 넣지 않았으며, artifact 테스트도 각 경주의 저장 Elo에서 독립
산식으로 기대값을 만든다. `build_predictors`의 특수 경로 판정은 결과 상태가 아니라 사전 이력
원천에 해당 entry anchor가 있는지로 정했다. 실제 진입점 회귀에서는 같은 A와 같은 사전 이력에서
정상완주/DNF/실격 상태와 결과 열을 서로 바꿔도 predictor frame 전체가 동일함을 확인했다.
대상 및 이후 경주의 결과·구간 값을 합성 변경해도 대상 form/style predictor는 동일했다.

다른 history module도 점검했다. 현재 history 단계에서 실제 field를 직접 사용하는 선택 열은
`ability_elo_vs_field`이며, 나머지 37개 선택 field 파생 열은 field module 이후 실제 A에서 계산된다.

## R2. 결측 보존 비교와 변화 원인 검증

`_value_equal`을 값 쌍별 계약으로 교체했다.

- 양쪽 null만 동일하다.
- null→값과 값→null은 변경이다.
- 유한 실수에만 절대 허용오차 `1e-10`을 적용한다.
- NaN/Inf는 같은 비유한값끼리도 유효한 동일값으로 인정하지 않는다.
- 문자열·정수 등 비실수 값은 정확히 비교한다.

독립 검토의 수정 전 재집계 9,278셀에는 종전 비교가 놓친
`exact_distance_top3_rate_race_z` 4건(entry 19362/19363/19366/19369)의
null→-0.447213595499958 전환이 포함된다. R1을 반영한 최종 v2 비교 결과는 다음과 같다.

| 분류 | 셀 수 |
|---|---:|
| 최종 변경 | 9,668 |
| null→값 | 4 |
| 값→null | 10 |
| 유한값 변경 | 9,574 |
| 비실수 값 변경 | 80 |
| 허용오차 내 유한값 | 134,238 |
| 양쪽 null | 85,030 |
| 정확히 동일 | 1,883,280 |
| NaN/Inf | 0 |

처음에는 `1e-12`로 비교했으나 A/N 차이가 없는 race 3858의
`ability_elo_context_race_z` 11셀에서 near-zero 표준편차 연산 순서로 생긴
4.2e-12~4.2e-11 차이가 검출됐다. 이를 숨기지 않고 유한 실수 계약을 `1e-10`으로 명시했다.
null 전환과 비유한값에는 이 tolerance를 적용하지 않는다.

feature 이름 whitelist만으로 원인을 인정하지 않도록 바꿨다. 저장된 개별 사전 입력을 사용해 실제
A의 field 파생식을 별도로 다시 계산하고 38개 선택 field feature를 전수 대조했다. 산식 mismatch와
비유한값은 모두 0이다. A/N이 다른 42경주 밖의 변경은 0이고, 최종 9,668셀 모두 독립 산식으로
field 확대 효과가 확인됐다. 의도된 별도 생성 경로 변경은 0, 설명 불가 변경도 0이다.

## R3. 실행 코드와 일치하는 calibration 명세

후속 N 모델과 A 모델에 동일한 현행 `auto` 규칙을 적용한다고 명세한다.

1. 시간순 train 내부의 fit/tune/calibration 분할을 사용한다.
2. `raw`, `sigmoid`, `isotonic` 후보 중 sigmoid와 isotonic 보정기는 calibration 구간에서 적합하고,
   raw는 무보정 후보다.
3. 각 후보를 development validation에 적용하고 경주별 목표 확률합으로 정규화한다.
4. 같은 development validation의 log loss가 가장 낮은 후보를 각 target별로 선택한다.
5. 따라서 development validation은 후보 선택과 보고 지표 산출에 함께 사용되는 개발 평가이며,
   선택과 독립된 test·미래 holdout이 아니다.

이번 보완에서는 trainer를 변경하거나 위 절차를 실행하지 않았다. 기존 보고서의
"validation으로 재선택하지 않는다"는 설명만 위 명세로 정정한다.

## 새 dataset 계약

| 항목 | 결과 |
|---|---:|
| A 경주 | 1,488 |
| A 행 | 15,579 |
| 정상완주 | 15,531 |
| started DNF | 47 |
| 실격 | 1 |
| train | 12,528 |
| development validation | 3,051 |
| 선택 feature | 136 |

E1 v2 evidence와 `(race_id, race_entry_id)` 키를 독립 집합 비교했고 누락·추가·중복은 0이다.
특수 상태 48행의 win/top2/top3는 0이고 순위·완주시간 auxiliary target은 모두 mask됐다.
선택 feature 이름·순서·hash 계약은 유지했다. 입력 값은 R1의
`ability_elo_vs_field` 448행에서 실제로 달라졌으나, 지시 범위에 따라 재학습하지 않았다.

## 재현 검사

- 관련 pytest: `12 passed`.
- 전체 pytest: `448 passed, 2 warnings` (11.46초).
- 관련 Ruff check 및 format check: 통과.
- 전체 Ruff check: 이번 변경 밖의 기존 21건으로 실패
  (`scripts/analysis_finish_time_quality.py`, `analysis/baselines.py`,
  `features/ability.py`, `tests/test_segment_correction.py`).
- 전체 Ruff format check: 이번 변경 밖의 기존 96개 파일이 재포맷 대상으로 남아 실패.
- `git diff --check`: 기존 `src/horse_racing/web/racecourse.py:347` EOF 빈 줄 1건으로 실패.
- 보완 관련 세 파일만 대상으로 한 Ruff check/format은 모두 통과하며 전체 pytest는 녹색이다.

추가된 회귀 검사는 null 전환·tolerance·NaN/Inf, 실제 A Elo 공식 전수 대조,
`build_predictors` 결과 상태 교환 불변성, 대상/미래 결과·구간 불변성, A 키·분할·라벨·mask를 다룬다.

## 산출물과 해시

- dataset: `data/datasets/confirmed_starter_conditional_e2_remediation_v2_retrospective/start_minus_30m/dataset.parquet`
  (`sha256:7e91eb16bbdb56102ee8ef3b5f785b2c4515dd4fcb75f98193c411f586f342de`)
- manifest: `data/datasets/confirmed_starter_conditional_e2_remediation_v2_retrospective/start_minus_30m/manifest.json`
  (`sha256:9d98db01802686b256394f4748a1e2c190e3ae1c549c863033342661dc87e5d0`)
- audit log: `data/logs/confirmed_starter_conditional_e2_remediation_v2_20260911.json`
  (`sha256:da3162f83110276ae46bf4b3b671724d78ccac7bbf0683db24547bdb6b00924c`)
- 본 보고서: `docs/CONFIRMED_STARTER_CONDITIONAL_E2_REMEDIATION_2026-09-11.md`

manifest에 기록된 builder/module/E1 evidence/reference dataset/DB 해시는 현재 파일과 모두 일치한다.
로그에는 기존 E2 네 산출물의 보존 해시도 기록했다.

## 남은 한계와 독립 검증 요청

- 이 데이터는 retrospective A 조건부 연구 입력이며 실제 당시 출전집합을 증명하지 않는다.
- 정상완주 조건부 history와 성별 snapshot PIT는 알려진 별도 한계로 남긴다.
- `1e-10` tolerance와 near-zero z-score 사례가 적절한지 독립적으로 재확인해야 한다.
- 검증자는 15,579행 A Elo 공식, 38개 field 산식, 42개 확대 경주 밖 변경 0,
  결과 상태/미래 합성 반례, manifest source hash를 다시 확인해야 한다.
- calibration validation의 이중 역할을 인지한 상태에서만 후속 비교 명세를 승인해야 한다.

독립 검증 통과 전에는 이 산출물로 학습하거나 다음 연구 단계로 이동하지 않는다.
