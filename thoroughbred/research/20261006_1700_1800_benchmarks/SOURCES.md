# 1700m와1800m 원천 및 계산 방법

2026-10-06. 기존 고정 스냅샷을 사용했다.1700m 서울 종료일은2026-09-20,1800m 서울은2026-09-20·부산은2026-09-18이다. 실시간 이력의 현재 종료일과 구분한다.

- [원천 일치 검증](../20261002_track_source_reconciliation/README.md)의results/api_study_population.parquet에서 지역·거리를 선택했다. 함수율 숫자로 건조1~5%·양호6~9%·다습10~14%·포화15~19%·불량20% 이상을 구분했다.
- [정상 경주·과거 이력](../20261002_gate_lateral_bias/README.md)의outputs/runners.parquet와 지역·날짜·경주·마필 키로 일대일 연결했다.1700m9,077행 중 품질2행,1800m15,383행 중 품질6행을 제외했다. 과거 이력은 현재보다 이전 날짜의 최근5회만 사용한다.
- thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb의confirmed_runners와section_measurements_api를 읽기 전용으로 조회했다. 성별과 부산 직접 마지막400m를 연결했다. 입력DB·Parquet의 작업 전후 SHA-256이 동일하다.
- thoroughbred/research/20260929_calendar_api_v1/raw/race_execution_probe/{2018..2026}/meet_{1,3}.json.gz의source_item_index를 직접 읽었다. 서울seS1fAccTime·seG3fAccTime·seG1fAccTime의 개별 누적시간 차와 부산buS1fTime·bu_3fGTime·bu_1fGTime·bu_2fGTime의 개별 구간기록을 대조했다. 날짜·경주·마필·거리·착순·전체·구간 대조 결과는 [1700m 원천 검증](1700/outputs/raw_source_verification.json), [1800m 원천 검증](1800/outputs/raw_source_verification.json)에 있다.
- [마사회 서울 성적표 용어](https://race.kra.co.kr/raceScore/scoretableLayerExplanation.do?meet=1), [부산 용어](https://race.kra.co.kr/raceScore/scoretableLayerExplanation.do?meet=3): 이전 거리 연구에서2026-10-05 확인한 S1F 출발200m·G3F 결승전600m·G1F 결승전200m의 지점 정의를 사용했다. 선두 통과·펄롱기록을 개별 말 기록과 혼동하지 않았다.
- [Ridge 공식 문서](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.Ridge.html), [시간순 교차검증 설명](https://scikit-learn.org/stable/modules/cross_validation.html)은 이전 연구에서2026-10-05 확인한 방법 출처다. 실제 실행 sklearn1.9.0과 웹 문서 버전을 구분한다. 연도별 분리는 코드에서 직접 수행했다.
- [1600m 연구](../20261006_1600_benchmarks/README.md)의 분석·독립 검증 구조를 두 거리별 코드로 수정했다. 구간·모집단·효과·개발 선택·검증을 다시 계산했다. 이번에는 검증기간에 이전3년 같은 등급 참조가 없는 행을 모든 방법에서 공통 제외해 비교 집단을 맞췄다. 완료된1600m 자료는 수정하지 않았다.
- [서울1700m 출전 여부 사전 점검](../20261006_seoul1700_coverage/README.md)의 국5·국6 존재와 표본을 출발점으로 삼았다. 본 연구는 추가 구간 품질 범위를 적용하므로 국6의 기록 수가1개 줄었다.

빠른20% 경계와 동률 절반의 기록점수는 자체 연구 정의다. 마사회 공식평가·Timeform rating·최적 효율par나 우승확률이 아니다. 각 거리의 전체·구간 의미를 맞춘 연구용 시간 기준이며 실제 경로 길이를 측정한 결과는 아니다.
