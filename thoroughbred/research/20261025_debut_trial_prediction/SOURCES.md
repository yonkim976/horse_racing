# 신마 데뷔전 예측의 출처

2026-10-25. 로컬 보존 자료를 읽기 전용으로 사용했다. 인터넷 신규 수집이나 운영DB 접근은 하지 않았다.

- 연구DB: `thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb`. 확인된 경주 결과와 `trial_participants_entity_reviewed`·`trial_participants_venue_reviewed`를 연결했다. 실제 입력 파일 크기·SHA256는[원천 감사](outputs/source_audit.json)에 남겼다. DB를 새 산출물로 복사하지 않았다.
- [API 주행심사 결과 정규화](../20260929_trial_results_api_v1/README.md): 61,777원문 참가자 행·파일/항목번호·원문 JSON의 근거.
- [주행심사 말 신원 연결](../20260930_trial_horse_identity_v1/README.md): 원문ID 미기재104행의 검토 연결. 이름만으로 경주와 연결하지 않았다.
- [영남 심사 장소 재검토](../20261001_yeongnam_trial_venue_recheck_v2/README.md): 별도 검토된2026-09-17의부산1000m48행과 원문 보존.
- [서울·부산 주행심사 기준](../20261003_trial_time_baselines/README.md), [구간 전개 연구](../20261003_sectional_pace_moisture/README.md): 독립 구간 정의와 물리적 품질 범위. 이전의 중앙값이나 실전 함수율 보정률을 신규 예측 계수로 복제하지 않았다.
- [API78 독립 검증](../../../docs/API78_EQUIPMENT_HISTORY_INDEPENDENT_VALIDATION_2026-09-30.md): 공식 경주결과의91~95 특수착순과0 취소/제외 검증.91/92를 실제 출발 뒤 실패로 남기고93~95·0은첫 실제 출발로 세지 않았다.
- [연구 게시 정책](../RESEARCH_PUBLICATION_POLICY.md), [산출물 용량 정책](../SESSION_ARTIFACT_POLICY.md)에 따라 중앙 결론과 원천·예측·검증·모델을 보존했다.

[코호트](outputs/debut_cohort.parquet)는 각 데뷔 경주 및 선택 심사의 원문 파일·항목번호와 말ID를 담는다. 학습/교정/평가 경계·모델 해시는[모형 원장](outputs/model_manifest.json), 사용 특징은[특징 계약](outputs/feature_contract.json), 원시 예측과 독립 재현은[검증](outputs/verification.json)에 남겼다.

원천은2026년에 소급 수집한 보존 자료다. 사건 날짜가 경주 전이라는 사실과 당시 실제 공개시각·최종 출전표가 확인됐다는 것은 다르다. 이번 모델 입력의 출전 명단·거리·게이트·현재 기수 등은 최종 결과 메타데이터를 대용하므로 전향 운영 성능을 인증하지 않는다.
