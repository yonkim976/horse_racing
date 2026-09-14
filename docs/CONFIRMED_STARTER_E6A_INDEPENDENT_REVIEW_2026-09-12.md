# E6-A 독립 검증

검증일: 2026-09-12 KST

**판정: 부분 통과. E6-B 실제 학습은 보류한다. 현재 중량·A 상대중량과 원천 일치는 재현했지만, 직전 출발 feature에 실제 데이터 오류가 있으며 평가 gate와 후속 명세도 보완이 필요하다.**

## R1 — P1: 직전 실제 출발을 직전 서울 출발로 제한

`scripts/audit_confirmed_starter_e6a.py:141`은 전체 과거 이력을 서울로 제한한다. 목표 경주가 서울이라는 조건과 그 말의 과거 출발이 서울이어야 한다는 조건은 다르다. 현재 산출물은 `직전 실제 출발`이라는 feature 정의를 충족하지 않는다.

검증자는 DB를 읽기 전용으로 열어 2026-05-31 이전의 경마장 전체 이력을 같은 horse_id와 엄격한 이전 날짜로 대조했다. E1 결과 분류를 적용한 DB 기준 결과는 다음과 같다.

- H1 167행에서 더 최근 부경 실제 출발이 존재한다. 이전 출발 키가 모두 달라진다.
- 변화량이 119행에서 달라진다: 유한값 변경 78행, null→값 41행.
- 나머지 48행은 중량이 우연히 같지만 직전 출발 키는 잘못됐다.
- 영향 167행은 2026-03-01 이전 127행, 3~5월 40행이다. 성능은 계산하지 않았다.
- 제출본의 `history_left_truncated_or_unobserved` 41행 전부에 DB상 부경 이전 출발이 있다. 이를 현재 DB 전체의 이력 부재로 설명할 수 없다.

| target entry | 현재 중량 | 제출 직전 출발 | DB상 더 최근 실제 출발 | 제출 delta | 재계산 delta |
|---|---:|---|---|---:|---:|
| 18703 | 56.5 | 서울 2024-10-06, entry 151579, 53.5kg | 부경 2024-11-24, entry 303213, 55.0kg | +3.0 | +1.5 |
| 23224 | 56.0 | 없음 | 부경 2025-02-07, entry 19712, 52.0kg | null | +4.0 |

이는 DB에 근거한 오류 재현이다. 새로 사용할 부경 과거 중량의 원천·정정 이력·가용성까지 이번 검증에서 승인한 것은 아니다. 구현 담당자는 해당 이전 출발의 출처도 감사한 뒤 새 버전을 생성해야 한다. 원천을 확인할 수 없으면 명시적으로 격리하고, 오래된 서울 출발로 되돌아가 값을 채우지 않는다.

## R2 — P2: 최근 미확정 출발을 건너뛰는 계약

`src/horse_racing/analysis/confirmed_starter_e6a.py:207`은 확정 출발이 하나라도 있으면 그 뒤의 `unresolved` 행을 검사하지 않는다.

실제 helper 합성 반례: 3월 1일 확정 출발 52kg, 4월 1일 출발 여부 미확정 54kg, 5월 1일 target 55kg를 넣으면 `previous_actual_start_weight_observed`, delta **+3kg**를 반환한다. 4월 출발 여부가 불명확하므로 3월이 직전 실제 출발이라고 확정할 수 없다. delta는 null과 미확정 상태여야 한다. 확정 출발보다 오래된 미확정 행까지 무조건 차단할 필요는 없다.

현재 서울 과거 126,191행에는 unresolved가 없고 E1 분류와의 불일치도 0이어서, 이 반례에 의한 현재 표본 변경은 입증되지 않았다. 다만 auditor는 rank_remark/disqualified를 읽지 않고 숫자와 scratched만 사용한다. 상충 상태를 미확정으로 남기는 E1 계약을 재사용하거나 동등한 검증을 적용해 재사용 시의 결함을 막아야 한다.

## R3 — P2: gate가 승인된 temperature 계약을 충분히 검사하지 않음

`src/horse_racing/analysis/confirmed_starter_e6a.py:69` 이후 검사는 상태 문자열과 유한 양수만 확인한다. 실제 helper에서 다음 두 잘못된 입력 모두 승인되어 validation이 두 번 실행됐다.

- `flat_use_T1`, **T=1.1**: flat 정책의 T=1과 불일치.
- `interior_optimum`, **T=1e10**: 승인된 log(T) 범위 [-4,4] 밖.

기존 성공 테스트도 flat 후보에 T=1.1을 넣어 이 오류를 정상으로 인정하고 있다. gate가 수학을 재학습할 필요는 없지만, 승인된 진단 상태·T·범위의 최소 일관성을 강제해야 한다. structural-flat 판정 자체는 기존 검증된 temperature 진단에 연결하고 임의 문자열만으로 생성하지 않는다.

## R4 — P2: 후속 후보·예산·gate 식별자 불일치

승인 지시서는 기존 136개 vs 감사 통과 부담조건 추가의 두 후보를 요구했다. E6-B 초안은 세 arm·18 fit으로 확대했다. 아직 초안이고 학습하지 않았으므로 실행 범위 위반은 없지만, 이 초안을 그대로 실행 승인하지 않는다.

또한 gate는 `BINARY/RACE_SOFTMAX`에 고정돼 있어 실제 부담조건 후보를 준비하면 거부한다. `BASE_136/CURRENT_WEIGHT_A_PREV` 두 정상 후보도 실제 helper에서 candidate_set_invalid로 거부됨을 재현했다.

최초 실험은 `BASE_136`과 `CURRENT_WEIGHT_A_PREV` 두 arm, 3 folds × 2 arms × selector/refit = **12 fit**으로 정리한다. 세 feature를 묶어 추가하는 최초 증분 정보 검사이며 각 feature의 개별 효과를 분리했다는 주장은 하지 않는다. 중간 arm은 향후 별도 가설로 남긴다. gate의 기대 후보 집합은 봉인 protocol에서 받아야 하고, prepare 전 요청 집합 및 prepare 후 반환 식별자까지 대조한다.

## 통과한 부분과 재현 범위

- H1/feature/evidence 15,579개 키 일치. 현재 중량과 A 상대값의 전수 산식 오차 0.
- 기존 서울 이력이라는 조건에서는 저장 delta/직전 키 15,579행 전수 재현. 이것이 R1의 원천 범위 적합성을 증명하지는 않는다.
- 세 원천을 다시 parser로 읽어 H1 15,579행과 각각 전수 일치 확인. 원문 파일 hash도 직접 대조해 불일치 0. 출전표 143문서/141고유 payload, 결과 각 141문서/141고유 payload.
- 모든 대상 원천의 가장 이른 수집도 마지막 target 경주 이후다. `retrospective_only / availability_unverified` 판정에 동의한다. 실시간 T-30 사용 승인 아님.
- 3-fold의 12개 partition 행·경주·경주일 수가 문서와 일치. 평가 합계 4,218행·407경주, 평가 경주 중복 0. 시간 순서와 확장창은 적합하다. 기존에 연구한 개발 데이터이므로 독립 test가 아니다.
- 최종 manifest 15항목 및 preservation에 기재된 현재 파일 hash 일치. 기재된 before/after도 동일. 과거 원장의 모든 하위 파일을 새로 전수 감사했다는 뜻은 아니다.
- 전체 pytest 직접 실행: **520 passed, 2 warnings**, 27.00초.
- 관련 Ruff/format 통과. 전체 Ruff 기존 21건, format 기존 98파일, diff-check 기존 racecourse.py:347 EOF 빈 줄 1건.

검증자는 실제 모델 학습·성능 평가·운영 변경을 수행하지 않았다. 2026-06-01 이후 실제 결과를 읽지 않았다. R1 감사에 필요한 서울·부경 등 이전 출발 이력만 읽기 전용으로 확인했다.

보완 지시: `docs/CONFIRMED_STARTER_E6A_REMEDIATION_AGENT_PROMPT_2026-09-12.md`.
기계 판독 로그: `data/logs/confirmed_starter_e6a_independent_review_20260912.json`.
