# E8-A 독립 검증 — 보완 후 재검증 필요

검증일: 2026-09-13. **제출 replay의 무결성은 확인했으나, 시간·상태 선택·feature 증거 계약에 반례가 있어 E8-A 승인은 보류한다.** 실제 수집 또는 운영 연결을 시작할 단계가 아니다. 아래 문제는 격리된 합성 데이터에서 재현했다. 실제 예측 누수·운영 변경이 발생했다고 주장하지 않는다.

## 통과한 범위

- attempt4 보존 경로 12개 전후 hash, 출력 5개 hash 일치.
- 상위 E7-B의 보존 112개·출력 68개 경로도 현재 hash와 일치.
- 제출 SQLite는 read-only로 열어 8개 이벤트의 payload hash, 이전 이벤트 chain, raw 바이트 hash, 상위 이벤트 참조·순서를 별도 산식으로 검사했다. 모두 통과.
- 전체 `.venv/bin/python -m pytest -q`: **594 passed, 2 warnings**, 29.80초. 이번 검증에서는 console pytest를 별도로 재실행하지 않았다.
- E8-A Python 3개 파일 Ruff check/format 통과.
- 전체 Ruff는 범위 밖 6개 파일 26건. 전체 diff-check는 기존 `src/horse_racing/web/racecourse.py:347` EOF 빈 줄 1건.
- 실제 수집·학습·예측 발행·성능 계산은 이번 검증에서도 0회. 원 운영 DB와 실제 결과를 조회하지 않았다.

독립 반례는 `/tmp/review_e8a_probes.py`로 실행했다. 실행 소스와 결과를 저장소 JSON에도 보존했다. 기존 제출 테스트를 수정하지 않았고, 반례용 SQLite는 시스템 임시 디렉터리에만 만들었다.

## R1 — 봉인시각 검사를 통과한 뒤의 시간 경과를 반영하지 않는다 [P1]

근거: `confirmed_starter_e8a.py:347`의 `_now() == cutoff` 검사, 368/386행의 `sealed_at_ms=cutoff`, 374행 이후 `_append` 호출.

합성 cutoff `2000000000000`에서 첫 clock 호출은 cutoff, 실제 field append의 clock 호출은 cutoff+1로 진행시켰다. 호출은 성공했고 field의 `sealed_at_ms`는 cutoff지만 journal `created_ms`는 `2000000000001`이었다. `verify_chain()`도 통과했다. 이미 append 시작 시점부터 늦었는데도 정확시각에 봉인됐다는 payload가 남는다. 이는 문서가 인정한 scheduler 정밀도 한계와 별개로, 현재 offline 계약 자체의 검사·기록 불일치다.

관측의 `persisted_at_ms` 역시 commit 이전 값이며 `observation_ready.available_at_ms`는 ready transaction 이전 값이다. 관측 commit 이후에 ready timestamp를 구하는 개선은 확인했다. 다만 이 timestamp가 무엇의 완료를 증명하는지, ready 이벤트 자체의 완료까지 뜻하는지 구분해야 한다.

보완: cutoff 정책시각, 실제 생성시각, commit 후 확인시각을 구분한다. 승인 전에 쓰기 지연을 검증하고 늦은 완료를 사전 봉인 성공으로 표시하지 않는다. 모든 transaction에 계속 완료 이벤트를 붙이는 식으로 확장할 필요는 없다. 어느 commit/ack가 승인 기준인지 명확히 정하고 pending/late/accepted 상태를 최소 구현으로 검증한다.

## R2 — cutoff 전에 알려진 정정을 무시하고 옛 출전표를 선택할 수 있다 [P1]

근거: `confirmed_starter_e8a.py:340–355`. `seal_field`는 호출자가 지정한 `observation_hash` 한 개만 검사하고 그 경주의 다른 관측을 검토하지 않는다.

같은 source·race에서 cutoff−10에는 entry 11/12의 완전한 출전표를, cutoff−5에는 entry 11만 있는 완전한 정정 출전표를 저장했다. 정정의 effective 시각도 cutoff−5로 명시했다. cutoff에서 옛 observation을 전달하자 두 마리 field가 성공적으로 봉인됐다. 새 정정은 이미 ready였다. 원문·hash·시각이 모두 정상이어도 cutoff 당시 알려진 출전 상태와 다른 집합을 승인할 수 있다.

보완: 출처·경주·관측 계열별로 cutoff에서 유효한 상태를 결정하는 정책을 구현한다. 최신 유효 정정과 상충하거나 최신 관측이 부분/모호한 상태인 경우 임의로 예전 complete 자료로 되돌아가지 않는다. 여러 원천의 충돌·미래 effective 이벤트는 정책으로 분리하고, 확정 불가능하면 봉인 실패를 기록한다. 신규 관측과 선택/봉인 사이 동시성도 검사한다. 이미 봉인된 field를 사후 변경하라는 요구가 아니다.

## R3 — 새 snapshot·예측의 사후 생성에 대한 적격 gate가 없다 [P1]

근거: `confirmed_starter_e8a.py:397–459`, `461–535`. source와 호출자가 제공한 feature available 시각은 검사하지만, 새 snapshot·prediction 생성시각에 대한 마감 검사가 없다.

field만 cutoff에 봉인한 뒤 clock을 예정 출발시각+1ms, 즉 `2000001800001`로 이동했다. 그때 새 snapshot과 새 prediction을 만들었으며 모두 성공했다. 승인 경로는 cutoff에 생성한 정상 합성 prediction과 동일하고, 별도 late/ineligible 사유가 없다. 사전 원문 hash가 있다는 사실만으로 사후에 계산·선택한 값이 사전 예측이 되는 것은 아니다.

보완: 정보 cutoff, feature 계산 완료, prediction 완료 마감의 관계를 명세하고 신규 승인에 강제한다. T−30 이후 replay를 보존하려면 별도 historical/synthetic-replay 부적격 상태로 기록한다. 이미 적시에 봉인된 동일 payload를 나중에 재시도하는 idempotency와, 늦게 만드는 새 예측은 구별해야 한다.

## R4 — feature 계약이 값의 증거가 아니라 호출자 선언에 머문다 [P2]

근거: `confirmed_starter_e8a.py:439–451`. `calculation_version`은 비어 있지 않은지만 검사하고, feature available 시각이 source available보다 빠른지도 검사하지 않는다. 해당 원문에서 해당 말의 feature 값이 도출되는 연결도 없다.

target race 7의 entry 11/12에 값 `999/-999`를 넣고, 관계없는 race 999의 말 두 마리 출전표를 source로 연결했다. 존재하지 않는 계산 버전 문자열을 입력하고 feature available은 cutoff−10000, source available은 cutoff−5로 선언했다. snapshot이 성공했으며 chain 검증도 통과했다. 다른 경주 원문을 feature에 사용하는 행위 자체가 문제라는 뜻은 아니다. 과거 이력·경주 공통 변수에는 다른 경주 자료도 정당하다. 문제는 계산 의존성과 값·시각을 확인할 계약이 없어 무관한 자료도 같은 방식으로 승인된다는 점이다.

보완: 이번 범위에서는 136열 전체 대신 **등록된 합성 feature 계산 한 개**만 구현해 원문에서 값·키를 재현하고, 계산 버전과 의존 source 목록·실제 계산 완료를 묶는다. 선언시각이 source 완료보다 빠르거나 미등록 계산·무관한 의존성·수정된 값이면 적격을 거부한다. 임의 feature payload 저장 기능을 남기려면 availability_unverified로 표시하고 예측 적격 경로에서 차단한다.

## 판정과 후속

`not_activated` 표기, 실제 원천 완전성 미확인, 실제 clock/수집주기 미확인, F_t 모델·feature 미검증이라는 보고서의 한계 표시는 적절하다. 이것을 더 많은 경마 원천을 수집하라는 요구로 확대하지 않는다. 현재 승인 보류 사유는 합성 최소 경로 안에서 재현된 네 가지다.

기존 594개 테스트를 유지하고 위 반례를 회귀 테스트로 추가한 새 보완본을 제출한다. attempt4와 기존 보고서·출력은 보존한다. 실제 수집·학습·운영 연결 없이 재검증한다.

- [기계 판독 검증·재현 소스](../data/logs/confirmed_starter_e8a_independent_review_20260913.json)
- [다음 에이전트 보완 지시문](CONFIRMED_STARTER_E8A_REMEDIATION_AGENT_PROMPT_2026-09-13.md)
