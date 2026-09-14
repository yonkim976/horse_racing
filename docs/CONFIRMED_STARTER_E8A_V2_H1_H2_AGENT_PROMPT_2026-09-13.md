# E8-A v2 잔여 H1/H2 보완 — 시간 검사만 수정

작업 경로: `/Users/kimyongjin/Desktop/horse_racing`.

기존 R1–R4 네 반례는 독립 재검증에서도 차단됐다. 새 기능을 추가하지 말고 현재 시간 계약의 H1/H2만 보완한다. 먼저 `docs/CONFIRMED_STARTER_E8A_V2_INDEPENDENT_REVIEW_2026-09-13.md`와 `data/logs/confirmed_starter_e8a_v2_independent_review_20260913.json`의 재현 소스를 읽는다.

## H1: 모든 ack의 시간 하한·상한

field clock 순서 `[cutoff, cutoff+1, cutoff, cutoff+2]`에서 늦은 pending이 `accepted`가 되는 반례를 차단한다. 이벤트 append 시각만 단조 증가하는지 검사해서는 payload의 역행 ack를 검출할 수 없다.

- observation, field, snapshot, prediction 각각의 단계별 시간 관계를 명시적으로 검사한다. 관측에서는 수신≤파싱≤insert≤commit ack, field/snapshot/prediction에서는 관련 선행 완료≤계산/transaction 진입≤insert≤commit ack 등의 실제 실행 순서에 맞는 조건을 강제한다. admission 시각과 payload ack의 관계도 확인한다.
- 유효 commit ack가 해당 단계 deadline을 만족할 때만 승인한다. clock 역행을 clamp하거나 이전/다음 시각으로 교체하여 승인하지 않는다.
- 역행 후 clock이 다시 전진하는 경우에도 거부한다. admission marker를 만들 수 없으면 pending/ineligible로 남겨도 되며 재시작 후 승인된 것으로 읽지 않는다.
- 기존 정상 경로, 늦은 완료, marker 실패, 적시에 승인된 prediction의 늦은 동일 payload 재시도는 유지한다. 기존 승인을 반환하는 재시도와 신규 승인을 만드는 행위를 구분한다.
- observation/field/snapshot/prediction에서 각각 ack가 insert보다 작아지는 변형을 검사한다. 새 라이브러리나 외부 공인시각 시스템을 만들지 않는다.

## H2: feature declared availability의 cutoff 상한

정상 source·값·dependency로 `available_at_ms=cutoff+1` 또는 예정 출발+1ms를 전달해도 snapshot/prediction이 승인되는 반례를 차단한다.

- 현재 선언의 의미를 유지하며 `max(source_ack, calculation_completed) <= declared_available_at_ms <= cutoff`를 검사한다.
- snapshot transaction·commit ack에 대한 H1 및 deadline 검사도 함께 만족해야 한다.
- 미래 declared 값을 수정하거나 cutoff로 잘라 넣지 않는다. 부적격 입력으로 거부한다.
- 하한이 유효한 정상 equal 경계, cutoff+1 및 큰 미래 값, source/계산 완료보다 빠른 값을 각각 검증한다. 정상 동작에 필요한 값을 임의로 미래로 선언하게 만드는 계약이 남지 않도록 한다.

## 보존·산출물·종료

현재 v2 attempt2, 봉인된 v2 코드·runner·테스트·계약 및 이전 모든 연구/운영 산출물을 보존하고 별도 보완 버전으로 제출한다. 실제 수집·학습·모델 발행·성능 평가·운영 연결·DB 변경은 0회이며 `not_activated`를 유지한다. 실제 원천/holdout 조회, 스케줄러 및 새 feature 작업은 이번 범위에 없다.

구현, H1/H2 수정 전·후 재현, 원래 R1–R4 및 정상 경로 회귀, 보존/신규 source/출력 hash manifest, 간결한 보완 보고서를 제출한다. 재현 source는 저장소 경로만으로 실행 가능해야 한다. 관련 Ruff check/format과 전체 pytest를 수행하고 범위 밖 dirty 파일은 건드리지 않는다.

H1/H2가 모두 차단되고 기존 계약이 유지되면 독립 재검증에 제출하고 종료한다. 이번 작업을 추가 기능 개발로 확대하지 않는다.
