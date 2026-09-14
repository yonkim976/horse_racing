# E8-A v2 합성 shadow 계약

적용 범위는 합성 offline 저장기뿐이다. 실제 수집·모델·운영 경로는 `not_activated`이며, 이 문서는 실제 KRA 원천 완전성이나 외부 공인시각을 보증하지 않는다.

## 시간과 승인 상태

- 정책 정보 cutoff와 field/snapshot/prediction 완료 deadline은 모두 관측된 일정 버전의 `scheduled_at_ms − 1,800,000ms`이다. 허용 지연은 **0ms**다. 이 정책은 기존 정확시각 실험을 유지하기 위한 것으로 실제 scheduler에 그대로 적용할 준비가 되었다는 뜻이 아니다.
- 원문 `requested_at_ms`, `received_at_ms`, `parsed_at_ms`는 각각 구분한다. observation insert의 시각은 시작 시각이지 영속화 완료시각이 아니다. `v2_observation` COMMIT 반환 뒤에 측정한 `ack_ms`를 `v2_observation_ack`에 기록한다. ack marker가 없으면 재시작 후에도 관측은 `pending/ineligible`이며 사후 backfill로 과거 cutoff 적격을 만들지 않는다.
- field는 SQLite `BEGIN IMMEDIATE` 안에서 cutoff 상태를 선택하고 `v2_field_pending`을 기록해 COMMIT한다. 그 후의 `field_commit_ack_ms`가 cutoff 이하여야 `v2_field_admission.status=accepted`다. 넘으면 `late_ineligible`이다. pending event의 `policy_cutoff_at_ms`는 사건 기준시각이지 실제 완료시각이 아니다. 승인 marker가 없으면 미승인이다. commit 전 예외는 rollback된다. marker 전 중단은 pending으로 남고 승인되지 않는다.
- snapshot은 등록 계산 완료와 원천 ack 이후, cutoff 이내에 transaction 진입·commit ack가 끝나야 한다. prediction도 cutoff 이내에 commit ack가 끝나야 한다. 각 admission event가 `accepted`인 경우에만 다음 단계가 진행된다. 사후 신규 생성은 거부하고, 적시 승인된 동일 prediction payload의 늦은 재시도만 원래 hash를 반환한다. 늦은 commit은 pending과 `late_ineligible` 이유를 남긴다.
- 클록이 경계 안에서 이동하거나 역행하면 승인되지 않는다. millisecond wall-clock 및 로컬 SQLite ack는 외부 공인시각이 아니며 악의적 전체 기록 재작성을 막지 못한다.

## cutoff 상태 선택 (`e8a_v2_latest_known_per_source_v1`)

- 동일 race의 관측 계열은 `source_id`로 구분한다. cutoff까지 commit ack가 확인된 이벤트만 본다. 원문 `effective_at_ms`가 없으면 알려진 시점부터 유효하고, 명시된 미래 effective는 현재 선택에서 제외해 근거에 `deferred_future_effective`로 남긴다. cutoff 뒤 관측한 과거 effective 정정은 기존 field를 바꾸지 않는다.
- 각 source에서 `ack_ms`가 가장 늦은 관측을 선택한다. 동일 `ack_ms`에 서로 다른 파싱 상태/내용이 있으면 입력 행 순서로 고르지 않고 실패한다. 최신 partial·ambiguous·파싱 실패는 옛 complete로 되돌아가지 않고 실패한다. 여러 source의 최종 내용이 다르면 원천 충돌로 실패한다. 모든 source가 동의하면 정렬된 source/hash로 결정적 대표 이벤트를 택한다.
- caller가 지정한 observation은 최종 선택 근거에 포함돼야 한다. 선택과 pending insert는 한 SQLite 쓰기 transaction에서 이뤄지므로 그 사이 새 관측 commit이 끼지 못한다. 선택 정책 버전, 선택 관측 hash, 미래 effective 보류 hash, 일정 버전, 출전 키를 pending에 남긴다. `declared_count`만으로 실제 다중 페이지 수집 완전성을 입증하지 않는다.

## 합성 feature와 결과 모집단

- 승인된 계산은 `synthetic_horse_number_pct_v1` 한 개뿐이다. field가 참조하는 원문 바이트의 SHA256을 확인해 다시 파싱하고 각 키에 `horse_number / declared_count`를 계산한다. 사용자가 보낸 키·말 식별자·값과 결과 hash가 계산값과 일치해야 한다.
- 계약은 calculator version, 해당 field 원문의 observation/ack hash 목록, 계산 결과 hash, source ack 및 실제 계산 완료시각, 선언 available 시각을 함께 보존한다. 선언시각은 source ack와 계산 완료보다 빠를 수 없다. 무관한 race 원문은 이 **등록 calculator**의 의존성이 아니므로 거부한다. 다른 경주의 과거 이력을 쓰는 별도 calculator 자체를 금지하는 규칙은 아니다.
- 다른 feature/미등록 버전·임의 값은 `availability_unverified`로 거부하며 prospective snapshot/prediction으로 들어갈 수 없다. 결과 모집단은 합성 `F_t`만 허용한다. 실제 136열 또는 후향 A 모델의 F_t 적격은 승인하지 않는다. DNS·결과 정정은 append-only outcome 사건으로만 기록하고 평가를 `held_dns_policy_unconfirmed`로 보류한다.
