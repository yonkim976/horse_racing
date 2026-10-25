# 심사 데뷔 기수 일치 연구의 출처

2026-10-25. 연구59의 입력·기준·예측을 고정한 후속이며 신규 외부 수집과 운영DB 접근은 없다.

- [원 연구59](../20261025_debut_trial_prediction/README.md), [코호트](../20261025_debut_trial_prediction/outputs/debut_cohort.parquet), [동결 예측](../20261025_debut_trial_prediction/outputs/predictions.parquet), [모형 원장](../20261025_debut_trial_prediction/outputs/model_manifest.json): 국내산 첫 실제출발·심사 지원·T-2 조건·연도 분리의 근거. 기존 파일과 중앙59는 수정하지 않았다.
- 연구DB `thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb`: `trial_participants_entity_reviewed.jockey_id_for_completed_trial`과선택 사건 ID를 연결했다. `confirmed_runners`의실제 기수ID·기수 과거 경주를 읽기 전용으로 사용했다.
- [주행심사 기수 결측 감사](../20260930_trial_jockey_gap_audit_v1/README.md): 원문 기수 필드 생략과 공식 성적표 보완의 근거. 양수시간의 실제 완료 기수와0초 편성 기수를 분리하므로 이름·편성만으로 기승을 확인하지 않았다.
- [심사 기수 관련 원천 검토](../20261001_trial_22_profile_absence_review_v1/README.md): 프로필 미확인과 개별 사건의 기승 사실을 구분한 배경. 현재 프로필에서 과거 자격을 소급하지 않았다.
- [연구 게시 정책](../RESEARCH_PUBLICATION_POLICY.md), [산출물 용량 정책](../SESSION_ARTIFACT_POLICY.md)에 따라 중앙59A·원 결과·모델·검증·용량을 보존했다.

[원천 감사](outputs/source_audit.json)는DB해시·공식ID 연결 범위를 기록하고, [이전 파일 보호](outputs/protected_inputs.json)는연구59의 원장·코드·모델·예측·문서와중앙59의 SHA256를 남겼다. 선택 사건·API 직접/보완 상태는[신원 지원](outputs/identity_coverage.csv), 과거 기수의 날짜 경계와 신규 특징은[기수 원장](outputs/rider_features.parquet), 독립 검산은[검증](outputs/verification.json)에 있다.

현재 출전 기수는 최종 결과에서확인한 실제 기수다. 과거 출전표의확정·변경 시각과그때 이용 가능했던 정보는미인증이며 전향 예측을발행한 결과가 아니다. ‘다름’은마지막 합격 심사와의관계이고 일반조교·다른연습에서기승한적이없다는뜻은아니다.
