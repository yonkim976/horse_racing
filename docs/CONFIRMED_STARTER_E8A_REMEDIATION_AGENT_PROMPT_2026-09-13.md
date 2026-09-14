# E8-A R1–R4 보완 지시문

작업 디렉터리: `/Users/kimyongjin/Desktop/horse_racing`.

독립 검증에서 제출 8개 이벤트의 hash와 보존 경로는 통과했지만, 네 가지 합성 반례가 재현됐다. `docs/CONFIRMED_STARTER_E8A_INDEPENDENT_REVIEW_2026-09-13.md`와 `data/logs/confirmed_starter_e8a_independent_review_20260913.json`의 결과·재현 소스를 먼저 읽는다. 이번 목표는 이 네 계약을 보완하는 것이며 실제 수집 활성화나 다음 연구 실행이 아니다.

## 작업 경계

- attempt4의 SQLite/raw/replay/manifest와 기존 E8-A 보고서·runner·모듈·테스트를 보존하고 v2 모듈·runner·테스트·산출물로 분리한다. E1 등 기존 승인 계약을 재사용한다.
- H1/E3–E7, 운영 registry/DB/schema/발행/UI/scheduler는 변경하지 않는다. 실제 수집·tree fit·확률 발행·성능 계산은 0회, 상태는 `not_activated`다.
- 네트워크, 실제 결과 조회, 자동화 등록을 하지 않는다. 합성 데이터와 임시/격리 저장소만 사용한다.
- 136개 실제 feature 재구현, 실제 KRA pagination, DNS 정산 정의, 배당 수집으로 범위를 확대하지 않는다.

## R1: 기록 시각과 완료 시각

독립 반례는 seal 사전 clock 검사=cutoff, `_append` clock=cutoff+1인데 `sealed_at_ms=cutoff`인 field가 성공하는 경우다. 정책 cutoff를 실제 완료 시각인 것처럼 기록하지 않는다.

1. requested/received/parsed, observation commit 확인, field 생성/완료, 승인 여부를 명확히 구분한다. `persisted_at_ms`처럼 완료로 읽히는 이름에 provisional 시각을 넣지 않는다.
2. 승인 기준이 되는 transaction/완료 ack를 명세한다. commit 전에 측정한 값을 완료시각으로 주장하지 않는다. 승인 대기 기록은 남길 수 있으나 늦게 완료된 것을 사전 성공으로 승격하지 않는다.
3. clock을 시간 검사와 transaction 사이, transaction 진입과 실제 commit 사이에 전진시키는 반례 및 commit 실패·재시작을 검증한다. 같은 고정 clock만 반복하는 테스트로 대체하지 않는다.
4. 정확시각 seal만 허용하는 기존 정책을 바꾸려면 허용 지연·적격 사건 정의를 문서로 명시한다. 단순히 검사식을 느슨하게 하여 통과시키지 않는다. 정보 cutoff와 실제 봉인 완료를 구분하면 late replay를 별도 부적격으로 저장할 수 있다.

완료 marker를 무한히 추가하는 설계는 필요 없다. 영속화·승인을 구분하는 작은 상태 기계와 복구 규칙을 구현하고, 공인시각·악의적 전체 재작성 방지까지 주장하지 않는다.

## R2: cutoff 상태의 결정적 선택

현재는 같은 source/race에서 cutoff−5에 유효한 정정이 존재해도 cutoff−10의 observation hash를 지정해 옛 field를 만들 수 있다.

- caller가 임의의 옛 observation을 골라도 승인할 수 없도록 source/race 관측 계열, 알려진 시각, effective 시각과 정정 우선순위를 명세한다.
- 유효 최신 complete 정정은 반영하고, 최신 partial/ambiguous 또는 원천 충돌은 보수적으로 실패시킨다. 늦게 관측된 과거 effective 정정은 이미 봉인된 field를 바꾸지 않는다. 미래 effective 이벤트의 처리도 별도 명시한다.
- 출전마 감소/추가, 일정 변경, 동일시각 상충, 관측 입력 순서 변화, 선택과 봉인 사이 신규 관측 반례를 검사한다. 전체 과거 상태를 DB 현재값으로 대체하지 않는다.
- 봉인에 사용한 선택 정책 버전과 근거 이벤트를 남긴다. 실제 source 완전성이 검증됐다는 주장은 하지 않는다.

## R3: 새 사후 snapshot·prediction의 적격 거부

field를 cutoff에 만든 뒤 예정 출발+1ms에 새 snapshot/prediction을 만드는 독립 반례를 먼저 회귀 테스트로 추가한다.

- 정보 cutoff, feature 계산 완료, prediction 완료 deadline과 admission 상태를 일관되게 정의한다.
- 늦은 신규 snapshot·prediction은 사전 예측 적격을 받지 못한다. 별도 replay 기록을 허용하면 `late/ineligible` 및 사유를 명시하고, 정상 합성 적격 이벤트와 기계적으로 구별한다.
- 이미 적시에 승인된 동일 payload의 늦은 재시도는 같은 승인 객체를 반환할 수 있다. 늦은 새 모델/실험 식별자로 신규 prediction을 만드는 것은 이 예외가 아니다.
- 사후 결과의 내용이 실제로 새 값 생성에 사용됐는지를 추측할 필요 없이, 시간·증거 gate만으로 재현 가능한 거부 규칙을 만든다.

## R4: 합성 feature의 최소 계산 증거

현재는 무관한 race의 원문, 가짜 계산 버전, source보다 빠른 available 시각, 임의 값으로 snapshot을 승인할 수 있다.

- 등록된 합성 feature 한 개를 정하고 원문에서 값과 대상 키를 실제로 계산한다. 값은 caller가 선언한 것을 무조건 신뢰하지 않는다.
- 계산 버전, dependency observation/ready 목록, 결과 hash, 실제 계산 완료시각을 묶는다. available은 모든 필요한 source 완료보다 빠를 수 없다.
- 미등록 계산 버전, 변조된 값/키, 빠진 dependency, source보다 빠른 선언시각, 무관한 원문을 거부한다.
- 다른 경주 source를 무조건 금지하지 않는다. feature의 선언된 의존 관계에서 허용되는지를 검증한다. 합성 원문에 없는 임의 feature 저장은 가능하더라도 `availability_unverified`로 격리하고 예측 적격을 주지 않는다.
- 기존 실제 136개 feature의 적격성을 이번 합성 구현으로 인정하지 않는다.

## 제출

새 보완 보고서, v2 구현/runner/테스트, 네 독립 반례의 수정 전·후 결과, 합성 replay, hash manifest를 제출한다. 기존 E8-A 코드·문서·산출물의 보존 hash와 신규 코드/테스트/runner/계약 문서 hash도 manifest에 포함한다. JSON 재현 소스가 저장소의 새 경로만으로 다시 실행되도록 한다.

관련 Ruff check/format, 기존 테스트와 새 회귀 테스트, 전체 pytest를 실행한다. 전체 정적 검사 범위 밖 문제는 파일·실제 개수를 따로 보고하며 수정하지 않는다. 검사 개수 증가 자체를 계약 통과의 근거로 삼지 말고 네 반례가 거부 또는 명시적인 부적격 기록으로 바뀌었음을 보여준다.

보완 완료 뒤 독립 재검증에 제출하고 종료한다. 실제 수집·모델 학습·운영 연결은 수행하지 않는다.
