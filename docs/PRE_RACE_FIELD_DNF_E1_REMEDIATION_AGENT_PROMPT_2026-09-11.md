# E1 계약 보완 담당자 지시서

작업 경로는 /Users/kimyongjin/Desktop/horse_racing이다. E1 감사의 실제 집계와 역사적 F_t 복원 불가 결론은 독립 재현됐다. 하지만 격리 계약 함수에서 네 결함이 확인됐다. PRE_RACE_FIELD_DNF_E1_INDEPENDENT_REVIEW_2026-09-11.md의 구체 반례를 먼저 읽고 아래 보완만 수행하라.

현재 dirty 작업을 보존한다. 기존 감사 JSON·parquet·보고서·dataset·run을 덮어쓰지 않는다. 실제 결과 조회는 2026-05-31 이하로 제한한다. 연구 계약 함수·새 테스트·감사기의 범위 방어는 수정할 수 있다. 운영 연결, DB 변경, 모델 학습, 성능 비교, 과거 F_t 추정 대체, live 수집 실행은 하지 않는다.

## E1-R1: 알려진 시점과 발생시점을 분리

- cutoff=1000, entry observation=900, withdrawal observation=1100, effective=950에서 자동 사전 제외가 일어나지 않게 한다.
- effective time만으로 정보가 cutoff 전에 공개됐다고 가정하지 않는다. 관측/공개 근거와 사후 사건 태그를 분리한다.
- snapshot의 cutoff membership은 사후 취소 정보를 추가해도 변하지 않게 한다. 복원 근거가 불충분하면 unknown/오류를 반환한다.
- effective만 있는 입력, late observation+past effective, 정당한 pre-cutoff observation, 이후 취소, 모순 시각을 각각 검사한다. 불필요한 재확인 요청 없이 근거가 명확한 계약부터 완성한다.

## E1-R2: 독립된 sealed field를 기준으로 검증

- immutable snapshot/field manifest에 race ID, cutoff, snapshot/source 식별자, 예상 race/entry 키와 완전성 근거를 묶는다. 예상 키는 예측 또는 결과에서 재생성하지 않는다.
- 선택 단계의 실제 행을 snapshot 예상 키와 검증한다. 입력이 자기 자신과 같은지만 검사하지 않는다.
- winner/TopK 평가 진입점에 sealed F_t를 받아 예측과 결과 양쪽을 각각 검증한다. 결과 누락은 unknown으로 보존하거나 실패해야 한다.
- 3마리 중 같은 한 마리를 예측·결과에서 동시에 제거한 경우, 양쪽에 같은 잘못된 키를 추가한 경우, snapshot에서 행을 삭제한 경우, 중복·다른 경주 혼입을 거부하는 통합 반례를 추가한다.

## E1-R3: 상충하는 상태는 확정 라벨로 만들지 않기

- 코드·비고·scratched·disqualified의 호환 조합과 충돌 정책을 명시한다. 신뢰 우선순위가 없다면 unknown/mask로 처리한다.
- 95/출전취소/scratched=True/disqualified=True를 확정 비입상 0으로 만들지 않는다.
- 92/주행중지/scratched=True, 1/주행중지도 모순을 검출한다.
- 현재 실측 정상완주 15,531·DNF 47·실격 1·미출주 267의 분류는 그대로 재현한다. DNF에 가짜 순위나 완주시간을 넣지 않는다.

## E1-R4: 유효한 순위와 TopK 사건 검증

- 단일 경주, 고유 키, sealed F_t 완전성, 결과 확정과 사건의 평가 가능성을 먼저 확인한다.
- [2,2,3], [1,3,3], 같은 결과 3회 중복, 서로 다른 경주 순위 혼합을 거부한다.
- 유효한 공식 동착 [1,1,3], [1,2,2]를 구분하고, 동착군 크기와 다음 공식 순위의 관계를 검사한다.
- 관측된 동착 순위와 유일한 exact ordered TopK는 다르다. 함수 이름·반환형·문서에서 의미를 고정하고, 필요한 경우 ordered loss를 mask한다. 이번에 새 순위 모델을 만들지 않는다.
- E1에서 미출주 사건은 아직 미정이다. winner NLL과 TopK에 같은 경주 평가 가능성 제한을 적용한다.

## 감사기 범위와 제출

현재 E1 표본 전용으로 고정할지, 다른 scope에서도 올바르게 계산할지 명확히 선택하라. 다른 기간/meet CLI를 유지한다면 고정 manifest·하드코딩 복원 결론을 제거하고, live COUNT(DISTINCT run) 및 meet 범위, 최초 취소 관측을 올바르게 처리한다. 합성 fixture로 검증하고 실제 미래 결과는 읽지 않는다. 현재 scope 전용으로 제한한다면 데이터 전제 변화도 검출해 오해를 낳는 성공 보고를 막는다.

제출물:

1. docs/PRE_RACE_FIELD_DNF_E1_REMEDIATION_2026-09-11.md: 네 결함의 수정 전/후 반례, 함수 사건 정의, 잔여 한계.
2. data/logs/pre_race_field_dnf_e1_remediation_20260911.json: 코드 해시·검증 결과·현재 표본 분류 재현·미변경 산출물 근거.
3. 보완한 연구 계약 함수, 실제 진입점을 검증하는 테스트, 필요하면 새 버전 감사 산출물.

관련 테스트와 전체 pytest/Ruff/diff-check를 실행하고 동시 UI 오류는 별도로 보고한다. 기존 E1 결론을 지우거나 미래 데이터가 없는 문제를 추정으로 메우지 않는다. 이 보완 결과를 독립 검증에 제출한 뒤 멈춘다.
