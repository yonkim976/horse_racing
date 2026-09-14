# Confirmed-starter E6-A 평가 경계 및 부담조건 감사

작성일: 2026-09-12 KST

**다음 연구용 평가 실행 경계를 fail-closed 구조로 분리했고, 부담중량 세 후보의 후향 원천·산식을
15,579행 전체에서 검증했다. 세 feature는 T-30 가용성이 확인되지 않아 격리 산출물로만 저장했다.
실제 tree 학습과 성능 평가는 수행하지 않았다.**

## 1. 양 후보 공통 평가 경계

새 `execute_two_candidate_gate`는 각 후보의 selector→refit→calibration 준비가 끝난 후 정확한
`BINARY`, `RACE_SOFTMAX` 집합과 temperature 상태를 공통 검사한다. 두 후보가 모두
`interior_optimum` 또는 `flat_use_T1`이고 T가 유한한 양수일 때만 validation 함수를 후보당 한 번
호출한다.

실제 helper를 stub/spies로 실행해 다음을 확인했다.

- 두 번째 후보 boundary, 첫 후보 예외, 후보 누락·중복, NaN/Inf/0/음수 T: validation 호출 0,
  산출물 0, 실패 사유 보존.
- 두 후보 정상 또는 structural-flat: 공통 승인 후 양쪽 validation 정확히 한 번.
- 후보 순서 역전: 같은 계약 유지, 첫 validation 전에 두 prepare 모두 완료.

기존 E5-B runner와 산출물은 수정하지 않았고 과거 실행 순서를 사후 변경된 것처럼 기술하지 않는다.
이 보완을 위해 Booster를 다시 학습하지 않았다.

## 2. 부담중량 원천과 시간 판정

H1 비선택 열 `carried_weight_kg`를 이름만 신뢰하지 않고 세 원문 경로와 독립 대조했다.

| 원천 | 원문 필드 | parser | 문서/고유 payload | 공통 H1 키 | mismatch | 추가 미출주 키 |
|---|---|---|---:|---:|---:|---:|
| 출전표 | `wgBudam` | `EntrySheetItem.parse_float` | 143/141 | 15,579 | 0 | 267 |
| AI 결과 | `burdWgt` | `AiRaceResultItem.parse_float` | 141/141 | 15,579 | 0 | 267 |
| 상세 결과 | `pthrBurdWgt` | `DetailedRaceResultItem.parse_float` | 141/141 | 15,579 | 0 | 267 |

DB `race_entries.carried_weight_kg`와 H1도 15,579행 모두 일치한다. 단위는 kg이며 실제 범위는
50.0~59.5kg, 결측과 45~80kg 연구 유효범위 위반은 0이다. parser는 문자열을 float로 바꾸고
공백·대시·해석 불가값을 null로 만든다. feature helper는 비결측 target 및 시간상 관련 있는 과거
이력 값이 유한한 45~80kg 폐구간인지 검사하며 위반 시 fail closed한다. 값을 clip하거나 임의
대치하지 않았다.

그러나 대상 141경주일의 세 원천은 모두 경주 후인 2026-08-21 22:26~23:29 KST에 수집됐다.
`requested_at/retrieved_at`은 수집 관측시각이지 최초 공개시각이 아니다. 부담중량의 published/effective
시각, 변경·override·정정 revision은 DB에 저장되지 않는다. 따라서 세 원천의 일치는 후향 최종값을
지지하지만 출전 시점 또는 T-30 상태를 증명하지 않는다. 판정은
`retrospective_only / availability_unverified`이다.

## 3. 세 후보 산식과 실측

| feature | non-null | null | 계약 |
|---|---:|---:|---|
| `condition_carried_weight_kg` | 15,579 | 0 | H1 target 부담중량 |
| `condition_carried_weight_rel_A` | 15,579 | 0 | 자기 중량−동일 경주 A 유효중량 평균 |
| `condition_carried_weight_delta_prev_start` | 14,712 | 867 | 자기 중량−날짜가 엄격히 이전인 직전 실제 출발 중량 |

상대중량 분모는 A의 유한·유효 중량만 사용하고 최소 관측수는 2다. target 중량 결측, 유효값 2개
미만 또는 전부 결측이면 상태를 구분해 null을 유지한다. 정상완주 N 평균은 사용하지 않는다.

직전 출발은 정상완주, started DNF, 실격만 포함한다. 미출주는 제외하고 미확정은 과거 출발로
소급하지 않는다. 직전 실제 출발 중량이 결측이면 더 오래된 비결측 경주로 건너뛰지 않는다.
관측 이력은 서울 DB의 2015-01-03부터이며 상태는 다음과 같다.

- 직전 실제 출발 중량 관측: 14,712행.
- 관측 범위 내 후향 첫 실제 출발: 826행.
- left truncation 또는 관측되지 않은 이력: 41행.

변화량 범위는 -8.0~+7.5kg다. 독립 race 집계와 독립 직전 출발 join에서 상대값·변화량·직전 키
mismatch는 모두 0이었다.

## 4. 불변성·coverage·보존

H1 A 키 15,579개를 분모로 보조 feature와 행별 세 원천 evidence parquet을 만들었다. inner join으로
행을 줄이지 않았고 원본 H1·136개 predictor·label은 변경하지 않았다.

실제 모듈에 고정 A 모집단과 `history date <= 2026-05-31`, `prior date < target date`를 적용했다.
target 결과 변경·삭제, 당일 결과 배제, 합성 미래행 추가, 입력 역순에서 feature hash는 모두
기준값 `648a5ff86afbb22e7550c1b72779c4c363208b6629eeb76a20d6b47ffce802fc`와 같았다.

기존 H1/E3/E4/E5-A/E5-B/기본 registry manifest의 실행 전후 hash는 동일하다. 실제
2026-06-01 이후 행은 읽지 않았고,
DB는 read-only URI로만 열었다. 첫 두 감사 시도의 타입·보조 표현 오류는 각 실패 경로에 보존했고
attempt3도 덮어쓰지 않았다. 문서화된 값 범위를 코드에서 강제하고 전체 frozen manifest 범위를
확장한 attempt4를 최종 제출본으로 확정했다.

## 5. E6-B 초안과 한계

E6-B는 동일 BINARY 절차의 `BASE_136`, `CURRENT_WEIGHT_A`, `CURRENT_WEIGHT_A_PREV` 세 arm만
제안한다. 2026-02-28 이전에서 확장 fit 창과 서로 겹치지 않는 evaluation을 가진 3개 fold를
숫자로 고정했다. 실제 학습은 하지 않았다.

부담중량은 능력 배정과 연관되므로 이 feature와 결과의 관계는 인과효과가 아니다. A 자체가 사후
실제 출발집합이고 기존 136개에도 알려진 snapshot PIT/source 한계가 있다. T-30 가용성이 확인되지
않았으므로 후속 결과도 historical live 성능이나 독립 미래 성능으로 해석할 수 없다. 2026년 3~5월
개발 validation, 6월 이후 결과, 운영 registry/champion은 이번 단계에서 사용하거나 변경하지 않았다.

## 6. 검증 결과

- 관련 Ruff check와 format check: 3개 E6-A Python 파일 모두 통과.
- 관련 pytest: 18 passed. 공통 gate spy, 후보 순서, 온도 경계, 결과·미래·순서 불변성,
  중복 키와 target/관련 history의 비유한·범위 밖 중량을 포함한다.
- 전체 pytest: 520 passed, 기존 dependency/PIT sortedness warning 2건.
- 저장소 전체 Ruff: E6-A 밖 기존 21건으로 실패.
- 저장소 전체 format check: E6-A 파일은 통과했으나 기존 98개 파일이 미정렬 상태라 실패
  (200개 파일은 통과).
- `git diff --check`: 기존 `src/horse_racing/web/racecourse.py:347` EOF 공백 1건으로 실패.

## 7. 제출 파일

- 최종 감사 경로: `data/experiments/confirmed_starter_e6a_20260912_attempt4/`
- 감사 JSON: `confirmed_starter_e6a_carried_weight_audit.json`
- keyed feature: `confirmed_starter_e6a_carried_weight_features.parquet`
- keyed source evidence: `confirmed_starter_e6a_carried_weight_evidence.parquet`
- feature 계약: `feature_contract.json`
- 평가 경계 증거: `evaluation_gate_evidence.json`
- 보존 및 검증: `preservation.json`, `verification.json`, `artifact_manifest.json`
- 시도 원장: `attempts.json`, 앞선 두 실패 폴더의 `failure.json`, 덮어쓰지 않은 attempt3
- E6-B 초안: `docs/CONFIRMED_STARTER_E6B_PROTOCOL_DRAFT_2026-09-12.md`
