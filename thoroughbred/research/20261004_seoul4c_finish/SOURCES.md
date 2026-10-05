# 출처와 지점 정의

2026-10-04 확인. 연구 대상은 서울 실전1200m이며 주행심사1000m와 다른 거리는 포함하지 않는다.

1. [한국마사회 공식 경주성적표 용어 설명](https://race.kra.co.kr/raceScore/scoretableLayerExplanation.do?meet=1): 4C는 결승선 전530m, G1F는 결승선 전200m 지점의 누적시간·통과순위로 설명된다. 공식 설명 페이지를 확인했다. 현재 성적표 본문 페이지의 실시간 조회는 실패했으므로 원본 개별 기록 검증은 아래 보관 API를 이용했다.
2. 읽기 전용 DB: `thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb`, `section_measurements_api`. 서울4C `se_4cAccTime`은 출발 이후 누적시간, `sj_4cOrd`는 통과순위다. G1F 누적시간은 `seG1fAccTime`, 통과순위는 `sjG1fOrd`다.
3. 보관 API: `thoroughbred/research/20260929_calendar_api_v1/raw/race_execution_probe/2018`부터2026년의 `meet_1.json.gz`. 모집단 각 행의 `source_file`·`source_item_index`로 24,961행의 날짜·경주·마번 식별자·거리·착순·4C/G1F/G3F 시간·4C/G1F 순위를 대조했다. 원본 파일을 복제하지 않고 해시와 검증 건수를 `outputs/summary.json`에 보존했다.
4. 모집단: [앞선 구간·전개 연구](../20261003_sectional_pace_moisture/README.md)의 `outputs/population.parquet`. 기존 정상 경주 선정과 물리적 구간 검사를 유지했다. 서울1200m 24,961행, 최근 기준7,897행. 너무 느리다는 이유만으로 정상 기록을 일괄 제거하지 않는다.
5. 착순·출전두수·과거 이력: [게이트 연구](../20261002_gate_lateral_bias/README.md)의 `outputs/runners.parquet`. 순위군의 분모는 품질 검사 후 남은 행 수가 아니라 원경주의 정상 출전두수다.
6. 비교 및 모델 설정: [1200m 기록 기준 연구](../20261004_1200_benchmarks/README.md). Ridge alpha10, 함수율 상태의 서울 공통 효과, 등급별 상태 상호작용0 설정을 고정했다. 기존 기준표·운영 보정 결정은 덮어쓰지 않았다.

공식530m는 계측점의 설명이며 말이 실제 달린 경로 길이가 아니다. 역사자료의 G3F→4C 평균 간격은6.189초다. 일반 용어 설명의600m−530m를 정확한 실측70m로 간주해 속도·가속도를 계산하기에는 별도의 지점·계측 검증이 필요하다. 이 연구는 시각 차와 순위 변화만 사용한다.530m 기록을400m 기록으로 비례 환산하지 않는다.
