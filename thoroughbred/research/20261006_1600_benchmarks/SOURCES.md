# 1600m 원천과 방법 출처

2026-10-06. 기존 고정 스냅샷을 사용했다. 실제 선택 표본의 종료일은 서울2026-09-19·부산2026-09-18이다. 입력 SHA-256과 실행 버전은 [요약](outputs/summary.json), 원API16개 파일 해시와 직접 대조 결과는 [원천 검증](outputs/raw_source_verification.json)에 기록한다.

- [원천 일치 검증](../20261002_track_source_reconciliation/README.md)의results/api_study_population.parquet에서1600m13,158행을 추출했다. 함수율은 숫자 기반 상태와 원문 충돌을 이전 연구에서 검증했다.
- [정상 경주·과거 이력](../20261002_gate_lateral_bias/README.md)의outputs/runners.parquet에서 정상·완전 착순1600m12,639행을 연결했다. 추가 구간 품질 제외1행 이후12,638행을 분석했다. 과거 이력은 다른 거리도 포함하되 현재보다 이전 날짜만 사용한다.
- thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb의confirmed_runners와section_measurements_api를 읽기 전용 조회해 성별·부산 직접 마지막400m를 연결했다. 작업 전후 입력 해시는 동일했다.
- thoroughbred/research/20260929_calendar_api_v1/raw/race_execution_probe/{2018..2026}/meet_{1,3}.json.gz의source_item_index를 직접 대조했다. 서울seS1fAccTime·seG3fAccTime·seG1fAccTime의 개별 누적시간 차, 부산buS1fTime·bu_3fGTime·bu_1fGTime·bu_2fGTime의 개별 구간시간을 사용했다. 최종12,638행의 기록 불일치는0이다. 선택된 서울1600m 표본에2021년 자료는 없으며, 이를 서울 전체 경주가 없었다는 뜻으로 해석하지 않는다.
- [마사회 서울 성적표 용어](https://race.kra.co.kr/raceScore/scoretableLayerExplanation.do?meet=1), [부산 용어](https://race.kra.co.kr/raceScore/scoretableLayerExplanation.do?meet=3): S1F 출발200m·G3F 결승전600m·G1F 결승전200m의 지점 정의를 사용한다. 공식 페이지는 직전 거리 연구에서2026-10-05 확인했다. 선두 통과·펄롱시간과 개별 말 기록을 구분했다.
- [Ridge 공식 문서](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.Ridge.html), [시간순 교차검증 설명](https://scikit-learn.org/stable/modules/cross_validation.html): 직전 연구에서2026-10-05 확인한 방법 출처다. 실제 실행 sklearn1.9.0과 웹 문서 버전을 구분한다. 이번 코드는 직접 연도별 분리를 실행했다.
- [1400m 기준 연구](../20261005_1400_benchmarks/README.md)의 분석·검증 구조를 새1600m 스크립트로 수정했다. 구간분할·모집단·품질범위·상태효과·검증은1600m로 다시 계산했고 기존 거리의 숫자나 운영 계수를 입력하지 않았다.

빠른20% 경계와 동률 절반의 기록점수는 자체 연구 정의다. 마사회 공식평가·Timeform rating 또는 최적 효율par를 계산한 작업은 아니다. 서울 직접 마지막400m 자료는 없어 추정으로 만들어 넣지 않았다. 부산 직접 마지막400m의 추가 품질 미달은0행이다.
