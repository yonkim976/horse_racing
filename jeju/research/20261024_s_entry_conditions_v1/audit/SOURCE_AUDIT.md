# S 출전조건 원천 감사

이 감사는 frozen S40 키만 사용해 현재 출전선언 부담중량, T−2 이전 실제 부담중량, 출주번호 비율의 3개 입력과 계보를 만들었습니다. 학습·추론·성과 평가·시장 자료는 사용하지 않았습니다.

- 출력: `jeju/research/20261024_s_entry_conditions_v1/audit/entry_condition_inputs.parquet` (4,942,596 bytes, SHA-256 `a1bc9e6b07ab28f384b2c0c104222a5cb297235e4dda645b9c08a376d27e0f72`; ZSTD Parquet)
- Contract SHA-256: `a6404068bffa91b9c6f0ab680e1a5f44c09078f229e3d37a481326bf49e98ad4`
- 분모: 5,206 races / 52,155 rows; exact full-card roster confirmed 5,181 races.
- 현재 선언 부담: 51,917 rows; exact ★ supplement 135; missing 238.
- 출주번호 fraction available: 51,917; prior actual burden available: 50,203; burden delta available: 49,988.
- 2019의 이름 충돌 네 경주 40행과 2026-09-17..19의 source tail 198행은 현재 부담·번호·delta를 NULL로 유지합니다. 최신 관측 이전 부담이 존재할 수 있는 tail 행은 snapshot 불완전 상태를 lineage에 표시합니다.
- 135개의 raw `★` 접두행만 같은 date/event/horse number/distance와 공식 ID/name을 대조한 뒤 신규 입력에서 보완했습니다. 별표 의미는 추정하지 않았고 원래 H3 파일은 바꾸지 않았습니다.
- 직전 실제 부담은 API4 `source_row.normalized_json.$.wgBudam`; 정상완주 1..89를 쓰고 ord 91/92는 raw `rcTime`와 normalized finish time이 모두 양수인 18행만 `actual_positive_time_observation`으로 포함합니다. 24개의 nonpositive ord92는 unknown으로 보류하고 앞선 valid actual이 선택되면 fallback status를 남깁니다.
- DB read-only hash: `0f2871c2a8f931bb968d8bf7086c27f0644c0ef7332b41b7a1bd85ff637c638f` (1,535,651,840 bytes; mode=ro + `query_only=ON`; file copied 0).
- Native history query rows: 65,562; canonical row/weight/status JSONL aggregate SHA-256 `8cb0595213f5901a1a92f236789f3aab723d16d028965a5f261d46333c0164e7`.
- Dacom01 `file_date <= T−2`는 문서날짜 기반 가정이며 실제 최초 공개·정정 시각은 입증되지 않았습니다. `retrieved_at_ms`는 수집 시각입니다.
- 전체 출처 목록, schema, year counts, read-only SQL, special-code evidence 샘플은 `SOURCE_AUDIT.json`, `source_contract.json`, `special_prior_evidence.json`에 고정했습니다.

- Builder code SHA-256 after diagnostic-only correction: `4ae19e5d53230e70c8fabc37e922582cb7b95f26c1f90bb91100fce4ae3819c3` (63,219 bytes).

생성 시 모든 파일 작성은 완료됐고, 마지막 stdout 진단 JSON에서 tuple Counter key 직렬화 오류로 프로세스가 비정상 종료했습니다. Parquet는 그대로 보존했으며, 출력 serializer와 이 기록만 수정했습니다.
