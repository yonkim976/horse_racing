# E8-A v2 H1/H2 시간 계약 보완

적용 범위는 합성 offline shadow v2의 새 격리 저장소뿐이다. 기존 E8-A/v2 산출물·코드는 수정하지 않으며 실제 수집·모델·운영은 `not_activated`이다. cutoff 허용 지연은 기존과 같이 **0ms**다.

## H1 — 완료 ack의 실행 순서

모든 clock 샘플은 직전 샘플 이상이어야 한다. 역행을 cutoff 또는 이전 값으로 clamp하지 않는다. 한 단계에서 역행이 검출되면 예외로 중단하고 그 단계의 `accepted` admission을 남기지 않는다. pending만 commit된 상태에서 중단되면 재시작 후에도 미승인이다.

- 관측: `requested ≤ received ≤ parsed ≤ observation insert ≤ observation COMMIT 반환 뒤 ack ≤ ack marker insert`. 원문 `requested`는 호출 입력이고 다른 시각은 저장기에서 측정한다. ack payload는 원 observation의 insert·parsed보다 빠를 수 없다.
- field: 선택된 observation 완료 ack ≤ transaction 진입 ≤ pending insert ≤ field COMMIT 반환 뒤 ack ≤ admission insert. 실제 승인에는 `ack ≤ policy cutoff`도 필요하다. cutoff는 정보 정책시각이지 insert/완료시각이 아니다.
- snapshot: field admission 이후 계산 완료 ≤ transaction 진입 ≤ pending insert ≤ snapshot COMMIT 반환 뒤 ack ≤ admission insert. admission ack는 source ack·계산 완료·pending insert 이상이고 cutoff 이하여야 승인한다.
- prediction: snapshot admission 이후 transaction 진입 ≤ pending insert ≤ prediction COMMIT 반환 뒤 ack ≤ admission insert. ack는 snapshot 완료·pending insert 이상이고 cutoff 이하여야 승인한다.

append 이벤트의 `created_ms`만 단조인지 검사하지 않고, admission payload의 ack 하한도 해당 pending 및 선행 완료 event에서 대조한다. 동일 store를 재개할 때 마지막 기록 시각보다 빠른 clock도 거부한다. 이미 적시에 승인한 동일 prediction payload의 늦은 재시도는 신규 clock gate 없이 원래 승인 hash를 반환한다. 다른 model/experiment/payload로 신규 승인을 생성하는 예외는 없다. 로컬 clock/SQLite ack는 공인시각 또는 악의적 전체 기록 재작성 방지 수단이 아니다.

## H2 — 선언 feature availability

등록된 합성 feature의 `declared_available_at_ms`는 선언값 그대로 보존하며, `max(source_ack_ms, calculation_completed_ms) ≤ declared_available_at_ms ≤ policy cutoff`일 때만 적격이다. 상한을 넘으면 snapshot pending을 만들기 전에 거부한다. 하한은 기존 등록 calculator 검사를 그대로 사용한다. cutoff로 자르거나 이전 값으로 보정하지 않는다. 이후 snapshot transaction 진입·COMMIT ack도 H1과 cutoff gate를 통과해야 한다.

현재 정확시각 field 정책에서는 field 완료 뒤 계산하는 등록 합성 feature의 정상 equal 경계가 cutoff다. `cutoff−1`은 계산 완료보다 빠르므로 정상 사례가 아니며 하한 위반으로 거부한다. `cutoff+1`과 예정 출발 이후 값은 상한 위반으로 거부한다. 실제 136개 feature·KRA 원천·DNS/배당은 이 계약의 승인 대상이 아니다.
