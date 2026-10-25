# 서울1700m 표본 확인 출처

2026-10-06. 기존 거리 연구와 같은 고정 스냅샷을 읽기 전용으로 확인했다. 웹사이트의 최신 전체 이력이나 현재 모든 경주를 빠짐없이 집계한 결과로 표현하지 않는다.

- [원천 감사 모집단](../20261002_track_source_reconciliation/README.md)의results/api_study_population.parquet에서 서울1700m를 선택했다.2018년 이후9,480행이다.
- [정상 경주 모집단](../20261002_gate_lateral_bias/README.md)의outputs/runners.parquet와 지역·날짜·경주·마필 키로 일대일 연결했다. 서울1700m9,077행, 최근2024년 이후2,311행이다. 추가 구간 품질 제외는 수행하지 않았다.
- thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb의confirmed_runners와confirmed_races를 읽기 전용으로 조회했다. 국5·국6 출전행의 등급·전체기록, 경주의 등급·거리를 직접 대조했다.
- thoroughbred/research/20260929_calendar_api_v1/raw/race_execution_probe/{2018..2026}/meet_1.json.gz의source_item_index를 직접 읽어 국5·국6의4,246행을 재확인했다. rcDate·rcNo·hrNo·rcDist·rank·rcTime을 대조했다. rank는 이 원API의 경주 등급 필드이며 착순과 구분한다.

[검증](outputs/verification.json)에 입력과 원API 해시를 보존한다. 낮은 등급의 말이 다른 등급의 경주에 출전한 모든 사례는 마필별 당시 등급 이력을 별도로 확인해야 한다. 이번에는 국5·국6 경주 자체의 존재를 확인했다. 거리별 평균·구간·보정 기준을 만든 결과는 아니다.
