# 원천·구간 정의·추정 방법

2026-10-06. 동결 모집단의 남은5거리 실전 기록 연구다. 거리·지역별 실제 종료일은 각 outputs/summary.json의input_end에 있다.1900m 부산은2020-07-19까지여서 최근 기준을 만들지 않았다.1900/2200/2300은2026년 봄까지의 희소 자료이며 실시간 현재 자료와 구분한다.

- [원천 일치 검증](../20261002_track_source_reconciliation/README.md)의results/api_study_population.parquet에서 지역/거리를 선택하고 함수율 건조1~5·양호6~9·다습10~14·포화15~19·불량20% 이상을 사용했다.
- [정상 경주/과거 이력](../20261002_gate_lateral_bias/README.md)의outputs/runners.parquet와 지역·날짜·경주·마필 키로 일대일 연결했다. 이전 날짜의 최근5회만 이력으로 사용하고 다른 거리도 포함한다.
- thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb를 읽기 전용으로 조회해 성별과 부산 직접 마지막400m를 연결했다. 입력DB·Parquet SHA-256은 각 summary.json에 기록했으며 작업 전후 동일하다.
- thoroughbred/research/20260929_calendar_api_v1/raw/race_execution_probe/{year}/meet_{1,3}.json.gz의source_item_index에서 식별·거리·착순·전체 및 개별 구간을 대조했다. 서울seS1fAccTime·seG3fAccTime·seG1fAccTime의 누적시간 차, 부산buS1fTime·bu_3fGTime·bu_1fGTime·bu_2fGTime을 사용했다. 경로가 원천 폴더 안에 있는지 확인하며 원API 파일 해시와 대조 결과는 거리별 raw_source_verification.json에 있다.
- [서울 성적표 용어](https://race.kra.co.kr/raceScore/scoretableLayerExplanation.do?meet=1), [부산 용어](https://race.kra.co.kr/raceScore/scoretableLayerExplanation.do?meet=3)는 앞선 거리 연구에서2026-10-05 확인한 S1F 출발200·G3F 마지막600·G1F 마지막200 지점 정의다. 선두 통과시간을 개별 말 시간으로 대체하지 않았다.
- [Ridge 문서](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.Ridge.html), [시간순 교차검증 설명](https://scikit-learn.org/stable/modules/cross_validation.html)도 이전 연구2026-10-05 확인한 방법 출처다. 실제 실행 버전은 거리별 summary.json의software에 있다. 연도별 분리는 직접 구현했다.
- [1700/1800m 연구](../20261006_1700_1800_benchmarks/README.md)의 분석·독립 검증 구조를 공동 코드로 확장했다. 거리·지역 선택, 구간길이, 넓은 품질 범위, 개발 선택, 효과, 분포, 검증을5거리별로 각각 새로 계산했다. 이번에는 과거에 미관측인 함수율 상태도 개발/시간순 평가에서 제외하며 최종 전기간 지원 없는 상태는 추정하지 않는다. 이전 완료 표는 수정하지 않았다.

이 기준은 최근 같은 등급 분포를 상태 효과의 위치 이동으로 맞춘 연구용 참조다. 상태별 분산/꼬리 모양, 최적 효율par, Timeform rating, 인과 함수율 효과, 공식 능력평가·우승확률을 추정한 결과가 아니다. 개발의 최적 후보 선택과 검증된 보정 효과를 구분한다. 한 날짜의 참조·희소 시간순 검증은 잠정으로 보존한다.
