# 1400m 원천과 방법 출처

2026-10-05. 기존 고정 스냅샷을 사용했다. 서울 종료일2026-09-20·부산2026-09-11은1400m 실제 선택 표본의 마지막 날짜다. 입력 SHA-256과 실행 버전은[요약](outputs/summary.json), 원API18개 해시는[원천 대조](outputs/raw_source_verification.json)에 기록한다.

- [원천 일치 검증](../20261002_track_source_reconciliation/README.md)의results/api_study_population.parquet에서1400m29,678행을 추출했다. 함수율은 숫자 기반 상태와 원문 충돌을 이전 연구에서 검증했다.
- [정상 경주·과거 이력](../20261002_gate_lateral_bias/README.md)의outputs/runners.parquet에서1400m28,262행을 연결했다.6두 이상 정상 완주·착순 완전 연결·함수율/통과원천 검증 모집단이다. 과거 이력은 다른 거리도 포함하며 현재 출전보다 이전 날짜만 쓴다.
- thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb의confirmed_runners와section_measurements_api를 읽기 전용 조회해 성별·부산 직접 마지막400m를 연결했다. DB해시를 작업 전후 확인했다.
- thoroughbred/research/20260929_calendar_api_v1/raw/race_execution_probe/{2018..2026}/meet_{1,3}.json.gz의source_item_index를 직접 대조했다. 서울seS1fAccTime·seG3fAccTime·seG1fAccTime의 개별 누적시간 차, 부산buS1fTime·bu_3fGTime·bu_1fGTime·bu_2fGTime의 개별 구간시간을 사용했다. 최종28,258행 불일치0이다.
- [마사회 서울 성적표 용어](https://race.kra.co.kr/raceScore/scoretableLayerExplanation.do?meet=1):S1F 출발200m·G3F결승전600m·G1F결승전200m의 지점 정의. [부산 용어](https://race.kra.co.kr/raceScore/scoretableLayerExplanation.do?meet=3)는선두 통과/펄롱시간과 마군 표기를 설명한다. 두 공식 페이지는직전1300m 작업에서2026-10-05 확인했으며 개별 말 원API 필드와 의미를 구분했다.
- [Ridge 공식 문서](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.Ridge.html),[시간순 교차검증 설명](https://scikit-learn.org/stable/modules/cross_validation.html): 직전1300m 작업에서2026-10-05 확인한 방법 출처다. 실제 실행 sklearn1.9.0과 최신 웹 문서 버전을 혼동하지 않는다. 이번 코드는직접 연도별 분리를 실행했다.
- [1300m 기준 연구](../20261005_1300_benchmarks/README.md)의 분석·검증 구조를새1400m스크립트로 복제·수정했다. 구간분할·모집단·품질범위·상태효과·검증은1400m로 다시 계산했다.1200/1300의 숫자나 운영 계수는입력하지 않았다.

빠른20% 경계와 동률 절반의 기록점수는 연구에서 선택한 자체 정의다. 마사회 공식평가·Timeform rating이나 최적 효율par를 계산한 작업이 아니다. 직접400m 자료에넓은 품질 범위 미달이 있으면 그 보조 구간만 결측으로 보존한다.
