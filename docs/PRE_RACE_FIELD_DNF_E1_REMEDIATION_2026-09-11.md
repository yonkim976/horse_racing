# Pre-race field / DNF E1 보완 보고서

작성일: 2026-09-11<br>
범위: 서울(meet=1), 2025-01-04~2026-05-31, 예정 출발 30분 전 계약<br>
상태: 독립 검증 제출용. 운영 연결·학습·성능 비교는 수행하지 않음.

## 결론

독립 검증에서 지적한 네 계약 결함을 연구 전용 모듈과 실제 평가 진입점에서 보완했다. 현재 표본의 집계와 "역사적 T-30 `F_t`는 정확히 복원할 수 없다"는 기존 결론은 유지된다. 보완 auditor는 이 결론의 전제가 확인된 고정 E1 범위에서만 실행되며, 표본이나 키 집합이 달라지면 성공 산출물을 쓰기 전에 중단한다.

새 계약은 다음 순서를 강제한다.

1. 예측·결과와 독립적으로 생성된 완전한 sealed field manifest를 검증한다.
2. snapshot 실제 행, 예측 행, 결과 행을 각각 manifest의 정확한 `(race_id, race_entry_id)` 집합과 대조한다.
3. 결과 상태의 코드·비고·flag 호환성을 확인한다.
4. 공식 순위 진행과 해당 사건의 평가 가능성을 확인한 뒤에만 TopK 또는 winner NLL을 계산한다.

## E1-R1: 알려진 시점과 발생시점 분리

### 수정 전 반례

`cutoff=1000`, entry 관측=900, 취소 관측=1100, 취소 effective=950이면, 사후에 알려진 취소를 effective 시각만 보고 cutoff 전 제외로 소급할 수 있었다. 이는 당시 알 수 있었던 정보와 사건 발생 태그를 혼동한다.

### 수정 후

`FieldEvidence`에 entry 관측, withdrawal 관측, 공개, effective 시각을 별도 필드로 두었다. `resolve_field_membership`은 관측/공개 근거 없이 effective 시각만 있는 경우 `UNKNOWN`을 반환한다. cutoff 뒤에 관측됐으나 effective가 cutoff 전인 취소는 sealed snapshot을 바꾸지 않고 `INCLUDED`로 유지한다. 공개 또는 관측이 cutoff 전에 확인된 취소만 사전 제외할 수 있다. 시각 관계가 모순되면 `UNKNOWN`이다.

회귀 테스트는 다음을 포함한다.

- effective-only → `UNKNOWN`
- late observation + past effective → `INCLUDED`
- 정당한 pre-cutoff observation/publication → 사전 제외
- post-cutoff withdrawal → 예측 당시 포함
- observation/publication 모순 → `UNKNOWN`
- 사후 취소 정보를 추가해도 기존 sealed snapshot과 field feature가 변하지 않음

## E1-R2: 독립 sealed field 기준 검증

### 수정 전 반례

선택 입력에서 만든 키를 같은 입력과 비교하거나, 결과 키를 예상 집합으로 사용하면 다음 오류를 놓칠 수 있었다.

- 예측과 결과에서 같은 한 마리를 동시에 삭제
- 예측과 결과 양쪽에 같은 잘못된 키를 추가
- snapshot 실제 행 삭제
- 중복 행 또는 다른 경주 행 혼입

### 수정 후

`SealedFieldManifest`가 `snapshot_id`, `source_id`, `race_id`, cutoff/sealed 시각, 독립 expected key set, 완전성 여부와 근거를 불변 객체로 묶는다. expected key set은 예측이나 결과에서 재생성하지 않는다.

`select_pre_race_field`는 snapshot 행을 manifest와 대조한다. `race_winner_nll`과 `official_topk_event`는 동일 sealed field를 받고 결과를 먼저 독립 검증하며, winner NLL은 예측 키도 별도로 검증한다. `validate_exact_keyset`은 누락·추가뿐 아니라 expected/observed 양쪽의 중복도 거부하고, 조용한 inner join을 하지 않는다.

통합 회귀 테스트에서 대칭 삭제, 같은 오키 추가, snapshot 삭제, 중복, 다른 경주 혼입이 모두 실패한다.

## E1-R3: 상충 결과 상태의 unknown/mask 처리

### 수정 전 반례

특수코드, 비고, `scratched`, `disqualified`가 충돌해도 단순 우선순위로 확정 0 라벨이 될 수 있었다. 특히 다음은 확정 DNS/DNF/정상완주가 아니다.

- `95/출전취소`, `scratched=True`, `disqualified=True`
- `92/주행중지`, `scratched=True`
- 정상 순위 `1`, 비고 `주행중지`

### 수정 후

`classify_outcome`은 호환 조합만 확정한다.

| 상태 | 허용되는 핵심 조합 | 라벨 정책 |
|---|---|---|
| normal finish | 순위 1~89, 비고/모든 특수 flag 없음 | win/Top2/Top3 및 관측 순위 사용 |
| started DNF | `92/주행중지`, scratch/DQ/void 아님 | 분류 라벨은 0, 보조 순위는 mask |
| disqualified | `91/실격`, scratch/void 아님 | 분류 라벨은 0, 보조 순위는 mask |
| did not start | `93/출발제외`, `94/경주제외`, `95/출전취소`와 scratch=True | E1 평가 전체 mask |
| race void | `99/경주취소`와 호환 flag | 평가 전체 mask |
| missing/conflict | 결과 누락 또는 위 조합 충돌 | unknown, 평가 전체 mask |

명시적 신뢰 우선순위가 없으므로 상충 조합은 모두 `UNKNOWN_SPECIAL`로 둔다. 현재 데이터에서 확정 조합은 기존 집계를 그대로 재현했다.

- 정상완주 15,531
- started DNF 47
- 실격 1
- 미출주 267

확정 실제 출주자는 15,579행이며, 전체 post-event entry는 15,846행이다.

## E1-R4: 공식 순위와 TopK 사건

### 수정 전 반례

결과 키와 공식 순위 진행을 먼저 검증하지 않으면 `[2,2,3]`, `[1,3,3]`, 동일 결과 3회 중복, 서로 다른 경주 혼합이 TopK 입력으로 통과할 수 있었다. 또한 공식 동착 TopK membership과 유일한 ordered TopK를 같은 사건으로 취급할 위험이 있었다.

### 수정 후 사건 정의

`official_topk_event(field, outcomes, k)`의 `official_entry_ids`는 공식 착순 값이 `<= k`인 모든 말의 membership이다. 따라서 경계 동착이면 원소 수가 k보다 많을 수 있다. `unique_ordered_entry_ids`는 1..k가 각각 한 마리로 유일할 때만 존재한다. k 이내에 동착이 있거나 완주자가 부족하면 ordered loss는 mask한다.

공식 순위는 Olympic ranking 규칙을 따른다. 앞 순위 동착군의 크기만큼 다음 순위를 건너뛴다.

- `[1,1,3]` 허용, official membership 3마리, ordered loss mask
- `[1,2,2]` 허용, official membership 3마리, ordered loss mask
- `[2,2,3]` 거부: 순위가 1에서 시작하지 않음
- `[1,3,3]` 거부: 1위가 한 마리인데 2위가 누락됨

동일한 전체 순위 검증은 winner NLL에도 적용한다. 공동 1위의 winner 확률은 공식 공동 우승자 확률의 합으로 정의한다. DNS, 결과 누락, void, 상충 상태가 하나라도 있으면 winner NLL과 TopK 모두 평가하지 않는다. E1의 DNS 사건 정의가 미정이기 때문이다.

실측 데이터에는 동착군 19개(19경주, 38행), 그중 공동 1위군 3개가 있다.

## Auditor 범위 방어와 재현

다른 scope를 일반화하는 대신 현재 E1 표본 전용 auditor로 명시적으로 고정했다. `meet=1`, 시작일 `2025-01-04`, 종료일 `2026-05-31` 중 하나라도 다르면 DB를 열기 전에 실패한다. 따라서 미래 실제 결과를 합성 fixture 또는 실행 편의 때문에 읽지 않는다.

고정 범위에서도 다음 전제가 달라지면 v2 산출물을 쓰기 전에 실패한다.

- 1,488경주, 15,846 entry 및 상태별 고정 집계
- `(race_id, race_entry_id)` 중복 0
- T-30까지 수집된 entry sheet 경주 0
- T-30까지 최초 관측된 scratch 0
- 사후 raw entry sheet와 DB entry의 정확한 키 일치
- 기존 dataset key와 현재 normal-finish key의 정확한 일치

취소 관측은 `MAX`가 아니라 최초 관측 `MIN(observed_at_ms)`를 사용한다. live ledger는 `COUNT(DISTINCT prediction_run.id)`로 run을 세며 racecourse meet 조건을 적용한다. 현 범위 live run/race/entry는 모두 0이다.

v2 evidence parquet은 새 경로에 썼다. 내용 hash가 기존 evidence와 같은 것은 동일한 15,846개 감사 행과 분류가 재현됐기 때문이며, 기존 파일을 덮어쓴 것이 아니다.

## 검증 결과

| 검증 | 결과 |
|---|---|
| 관련 pytest | 24 passed |
| 관련 Ruff check | 통과 |
| 관련 Ruff format check | 3 files 통과 |
| 전체 pytest | 434 passed, 2 warnings |
| 전체 Ruff check | 실패: 범위 밖 기존 오류 21개 |
| 전체 Ruff format check | 실패: 범위 밖 기존 파일 96개 |
| `git diff --check` | 실패: 동시 UI 파일 `src/horse_racing/web/racecourse.py:347`의 EOF blank line |

전체 Ruff 21개는 `scripts/analysis_finish_time_quality.py`의 line length/미사용 loop 변수, `src/horse_racing/analysis/baselines.py` 및 `tests/test_segment_correction.py`의 import 정렬, `src/horse_racing/analysis/features/ability.py`의 미사용 import이다. 이번 제출 파일 세 개에 대한 Ruff는 통과했다. 전체 format 오류와 UI diff 오류는 dirty work 보존 원칙에 따라 수정하지 않았다.

## 산출물과 보존 근거

새 산출물:

- `src/horse_racing/analysis/pre_race_field_contract.py`
- `tests/test_pre_race_field_contract.py`
- `scripts/audit_pre_race_field_dnf_e1.py`
- `data/logs/pre_race_field_dnf_audit_e1_v2_20260911.json`
- `data/logs/pre_race_field_dnf_evidence_e1_v2_20260911.parquet`
- `data/logs/pre_race_field_dnf_e1_remediation_20260911.json`
- 본 보고서

기존 보고서, E1 JSON, E1 parquet, dataset 및 manifest의 hash는 보완 로그에 기록했다. 기존 E1 세 산출물의 SHA-256은 각각 `a63d6061...`, `f5ed2707...`, `abe6415d...`로 유지됐다. dataset 또는 run을 새로 만들거나 수정하지 않았다.

## 잔여 한계와 독립 검증 체크포인트

- 1,488경주 모두 T-30 entry sheet와 scratch 공개/effective 이력이 없으므로, v2도 역사적 `F_t` 복원 자료가 아니다. 사후 current-state evidence라는 한계를 유지한다.
- DNS를 loss로 셀지, field에서 제외할지, 별도 사건으로 둘지는 아직 정하지 않았다. 현재 계약은 DNS가 있으면 경주 평가를 mask한다.
- 연구 계약은 운영 dataset/prediction 경로에 연결하지 않았다. 운영 승격 검토는 별도 단계다.
- 독립 검증자는 late-observed/past-effective 반례가 membership을 소급 변경하지 않는지, prediction/outcome 대칭 누락이 sealed manifest에서 실패하는지, 세 충돌 상태가 unscored인지, Olympic rank skip과 ordered-loss mask가 의도대로인지 재확인해야 한다.
- auditor의 비기본 날짜/meet가 DB 접근 전에 실패하고, 고정 집계 또는 독립 키 비교가 달라질 때 v2 파일 쓰기 전에 실패하는지 확인해야 한다.

이 제출은 E1 보완 결과까지만 포함한다. 운영 승격, 다음 연구 단계, 모델 학습 또는 성능 비교는 진행하지 않았다.
