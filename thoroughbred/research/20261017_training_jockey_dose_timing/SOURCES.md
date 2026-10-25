# 조교 기수 기승 횟수와 시점 연구의 출처

2026-10-17. 연구56의 후속 관측 분석이며 신규 인터넷 수집과 운영DB 조회는 하지 않았다.

- [기수 기승 확인과 성적 연구56](../20261017_training_jockey_performance/README.md): 원래 존재 여부 연구의 정의·원천·모형. 이번에는 횟수·마지막 기승을 정확히 비교하기 위해 과거 역할 미상 및 출전 기수ID 불명확 표본을 더 엄격히 제외했다.
- 연구DB `thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb`: `daily_training_rider_linked`와 `training_date_coverage`를 읽기 전용으로 사용했다. 날짜별 선택 캡처와 완전수집·수량 일치 조건을 그대로 유지했다.
- [159,014출전 신원 원장](../20261012_jockey_switch_trainer_intent/outputs/analysis_rows.parquet): 실제 출전 기수ID·말·경주일·착순·정제시간·과거 능력. 원문 파일·항목번호·행키가 있다. 기수 교체 연구의 전용 지원 조건은 쓰지 않았다.
- [기존318,028행 조교 특징](../20261017_training_jockey_performance/outputs/training_window_features.parquet): 전체 조교량·기수 횟수·기승일수·역할 미상과 수집 지원을 원천에서 재계산해 모든 공통 열의 정확한 일치를 확인했다. 마지막 기승일과 다른 기수의 확인된 기승량을 추가했다.
- [공식 기승자ID 연결](../20261015_daily_training_rider_links_v1/README.md), [080626 사건별 이름 연결](../20261015_daily_training_event_names_v1/README.md), [기승자 역할 검증](../20261015_training_rider_roles_followup_v1/README.md): 이름만 확인된 기록을 출전 기수로 매칭하지 않았다. 2026프로필로 과거 역할·자격을 소급하지 않았으며 기수트랙라이더 가능성과 최근 역할 미상을 유지했다.
- 수치 함수는 연구56 `analyze.py`의 공변량 구성과 연구50 `analyze.py`의 정확 sparse 고정효과 투영·군집분산·BH 함수를 재사용한다. 해당 연구의 입력 생성·모델 학습·main은 호출하지 않는다.

[입력 해시](outputs/source_audit.json)에 현재DB·출전 입력·이전 특징·분석 함수·SQL의 실제 SHA256와 크기를 남겼다. [기승일 중복 감사](outputs/same_day_multiple_audit.csv), [코호트 지원](outputs/cohort_coverage.csv), [검증](outputs/verification.json)이 이번 비교의 범위를 설명한다. API 기수 표기는 당일 역할의 완전한 현장 검증을 뜻하지 않는다. 실제 과거 공개시각·예측 시점의 출전 기수 이용 가능성은 추가 확인이 필요하다.
