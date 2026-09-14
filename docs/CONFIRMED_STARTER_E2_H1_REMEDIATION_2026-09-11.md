# Confirmed-starter E2-H1 remediation

검증 기준일: 2026-09-11 KST

판정: **E2-H1 독립 재검증용 후보를 제출한다. 재검증 전 학습·다음 단계·운영 연결은 하지 않는다.**

## 범위와 보존

- H1의 `horse_jockey_starts`, `horse_jockey_wins`, `horse_jockey_first`만 보완했다.
- 운영 `features/people.py`의 기본 동작과 기존 dataset/model 코드는 변경하지 않았다.
- v2에서 통과한 Elo, 38개 field 산식, null 비교, calibration 명세와 정상완주 조건부 과거 이력 정책은 유지했다.
- 실제 결과 범위는 2025-01-04~2026-05-31이다. 이후 날짜는 회귀 테스트의 합성 미래행만 사용했다.
- 기존 v2와 이전 E2/E1/canonical dataset·manifest·report·log·run, production DB 및 dirty work를 보존했다.
- 모델 학습, 성능 비교, 배팅, 운영 연결, 실제 수집은 수행하지 않았다.

## 결함 재현과 수정

운영 people 모듈은 정상완주 `past_results`에서 조합 누적값을 만든 뒤 target
`race_entry_id`로 join한다. DNF/실격 target는 정상완주 이력에 없으므로 join이 실패하고,
실제 과거 조합 이력이 있어도 `0/0/1`로 채워졌다.

E2 연구 경로에만 조합 이력 adapter를 추가했다. 모든 A 행에 대해
`horse_id+jockey_id`별 정상완주 이력을 정렬하고 target date보다 엄격히 이전인 행만 세어
출주수와 승수를 만든 뒤 `first = starts == 0`을 파생한다. target `race_entry_id`나 target 결과행의
존재 여부는 사용하지 않는다. null jockey는 세 값 모두 null이며, 알려진 기수의 실제 과거 조합
0회는 `0/0/1`이다. 과거 DNF는 이력에 추가하지 않았다.

## 독립 전수 검증

수정 함수는 정렬된 이력과 `bisect_left`로 값을 만든다. 검증 기대값은 그 함수를 호출하지 않고,
별도의 relational join으로 `horse_id+jockey_id`를 연결한 뒤
`event_date < target_date`와 정상착순 1~89 조건을 적용해 집계했다.

| 검사 | 결과 |
|---|---:|
| 독립 A 검사 행 | 15,579 |
| 불일치 행 | 0 |
| 불일치 셀 | 0 |
| null jockey 계약 | 통과 |

사례 값은 상수로 생성하지 않고 실제 과거 이력에서 계산했다.

| entry | starts | wins | first |
|---:|---:|---:|---:|
| 19361 | 1 | 0 | 0 |
| 19785 | 3 | 0 | 0 |
| 20871 | 1 | 1 | 0 |

## 보존된 v2 대비 변화

비교는 양쪽 null만 동일, null 전환은 변경, 유한 숫자는 절대오차 `1e-10`, NaN/Inf는 무효라는
v2 계약을 그대로 사용했다.

| 구분 | 결과 |
|---|---:|
| 키가 동일한 행 | 15,579 |
| 실질 변경 행 | 30 |
| 선택 feature 변경 셀 | 71 |
| `horse_jockey_starts` | 30 |
| `horse_jockey_wins` | 11 |
| `horse_jockey_first` | 30 |
| 정상완주 변경 셀 | 0 |
| 다른 선택 feature 변경 | 0 |
| 비선택 열 변경 | 0 |

재생성 과정에서 네 비선택 gate 수치 열에 부동소수점 미세 차이가 있었지만 모두 허용오차 안이다.
최대 절대차는 `gate_early_speed_course` 8.88e-16,
`gate_early_speed_distance` 2.22e-15, `gate_early_speed_context` 4.58e-15,
`gate_early_speed_front_fit` 4.05e-15이다. 이 값들은 변경 셀로 집계하지 않았다.

정상완주 N 공통행의 기존 field 확대 변화는 9,668셀로 유지됐다. 38개 A-field 독립 산식은
모두 일치했고 설명 불가 변화와 확대 42경주 밖 변화는 0이다.

## 실제 모듈 회귀와 mocked test의 범위

기존 mocked test는 `_apply_modules`를 교체해 결과 상태 문자열이 경로를 직접 바꾸지 않는지만
검사한다. H1 승인은 이 테스트에 의존하지 않는다.

새 실제 모듈 테스트는 race 1849의 A 11행과 target 말들의 실제 과거 source로 축소 fixture를
만들고 `_apply_modules`를 mock하지 않은 채 전체 `build_predictors`를 실행한다. 다음 네 반례에서
136개 선택 predictor의 null 상태를 정확히 비교하고 유한값은 `1e-10`으로 대조했다.

- target 정상 결과행을 source에서 삭제
- 정상완주/DNF/실격 상태 교환
- target 결과·구간 값을 합성 변경
- 2026-06-01 합성 미래 결과·구간을 추가하고 값 변경

네 경우 모두 선택 predictor 변화가 0이다. 별도 회귀로 DNF null anchor가 미래 Elo state를
갱신하지 않는 것도 유지됨을 확인했다.

## dataset 계약 재검사

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

독립 E1 evidence와 키 집합이 일치하며 누락·추가·중복은 0이다. 특수 상태 48행의
win/top2/top3=0 및 순위·완주시간 auxiliary mask도 유지했다. 데이터 실제 값이 H1의 71셀에서
달라졌으나 지시 범위에 따라 재학습하지 않았다.

## 검사 결과

- 관련 pytest: `14 passed` (실제 모듈 fixture 1개와 mocked unit test를 구분).
- 전체 pytest: `450 passed, 2 warnings` (25.32초).
- 관련 Ruff check/format check: 통과.
- 전체 Ruff check: 기존 범위 밖 21건으로 실패.
- 전체 Ruff format check: 기존 범위 밖 96개 파일이 재포맷 대상으로 남아 실패.
- `git diff --check`: 기존 `src/horse_racing/web/racecourse.py:347` EOF 빈 줄 1건으로 실패.

전체 Ruff 문제는 `scripts/analysis_finish_time_quality.py`, `analysis/baselines.py`,
`features/ability.py`, `tests/test_segment_correction.py` 등에 있으며 H1 변경 파일과 무관하다.

## 산출물과 해시

- dataset: `data/datasets/confirmed_starter_e2_h1_remediation_retrospective/start_minus_30m/dataset.parquet`
  (`sha256:9d508bfdea325482461fa5d4e1b9a3ea8543bfe146a9b40b5400f4084064d6a7`)
- manifest: `data/datasets/confirmed_starter_e2_h1_remediation_retrospective/start_minus_30m/manifest.json`
  (`sha256:f36cc08930c4010cc3be230575289d06110add010d4c3ad368dbdad5f142d801`)
- audit log: `data/logs/confirmed_starter_e2_h1_remediation_20260911.json`
  (`sha256:028a14f2af70dd3fd72b034cbda3e952d0ce7692b02aeadfe51e6868475e57e3`)
- 본 보고서: `docs/CONFIRMED_STARTER_E2_H1_REMEDIATION_2026-09-11.md`

manifest의 구현·builder·E1 evidence·canonical N reference·v2 dataset·DB source hash는 현재 파일과
모두 일치한다. audit log에는 보존된 v2 dataset/manifest/log 해시를 별도로 기록했다.

## 남은 한계와 독립 검증 요청

- A는 retrospective actual-starter conditional이며 역사적 T-30 `F_t`가 아니다.
- 정상완주 조건부 history와 성별 snapshot PIT는 알려진 별도 한계로 남는다.
- 검증자는 독립 조합 집계를 다시 작성해 15,579행, 30행·71셀, null jockey 계약을 확인해야 한다.
- 실제 모듈 fixture가 target 결과행 존재 여부와 합성 미래행을 차단하는지 재실행해야 한다.
- 기존 38개 field 산식, N 공통행 9,668셀, source hash 보존도 재확인해야 한다.

독립 검증 통과 전에는 이 artifact로 학습하거나 다음 단계로 이동하지 않는다.
