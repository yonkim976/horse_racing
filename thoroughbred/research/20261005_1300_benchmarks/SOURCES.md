# 1300m 원천과 방법 출처

2026-10-05. 원 자료는기존 고정 스냅샷을 사용하며 새 경기결과를 수집하지 않았다. 지역별 종료일은서울2026-09-20·부산2026-09-18이다. 파일 SHA-256은[요약](outputs/summary.json), 원API18개 파일 해시는[원천 대조](outputs/raw_source_verification.json)에 있다.

- [원천 일치 검증](../20261002_track_source_reconciliation/README.md)의results/api_study_population.parquet에서1300m29,189행을 추출했다.
- [정상 경주·과거 이력 원장](../20261002_gate_lateral_bias/README.md)의outputs/runners.parquet에서1300m27,909행을 연결했다. 이 원장은[전개 연구](../20261002_moisture_position/README.md)의 엄격한 이전 날짜 이력을 포함하며 다른 거리의 직전 착순/위치도 이용한다.
- thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb의confirmed_runners와section_measurements_api를읽기 전용 조회하여 성별·부산 직접 마지막400m를 연결했다. DB 해시를작업 전후 확인했다. 삭제된 단계별/공유 DB를사용하지 않는다.
- thoroughbred/research/20260929_calendar_api_v1/raw/race_execution_probe/{2018..2026}/meet_{1,3}.json.gz의source_item_index 위치를직접 읽어 날짜·경주·말·1300m·착순·전체 및 개별 구간시간을27,897행 대조했다. 서울 seS1fAccTime·seG3fAccTime·seG1fAccTime은누적시간, 부산 buS1fTime·bu_3fGTime·bu_1fGTime·bu_2fGTime은개별 구간/마감시간이다.
- [마사회 서울 경주성적표 용어](https://race.kra.co.kr/raceScore/scoretableLayerExplanation.do?meet=1): S1F 출발200m·G3F결승전600m·G1F결승전200m의 지점 정의. 선두마의 경주 통과/펄롱표와 개별 말 계측 필드의 의미를구분했다. [부산 용어](https://race.kra.co.kr/raceScore/scoretableLayerExplanation.do?meet=3)는펄롱/선두 통과시간과마군 표기를설명하며 이 페이지에없는 상세 지점은원API필드/검증된 내부 의미를참조했다. 두 공식페이지는2026-10-05 확인했다.
- [Ridge 공식 문서](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.Ridge.html): L2 패널티 회귀. 실행한 sklearn/numpy/pandas버전은summary.json에 기록했다. [교차검증 공식 문서](https://scikit-learn.org/stable/modules/cross_validation.html)의 시간순 분리 원칙을사용하되 이번 코드는직접 연도별 분리를실행했다. 공식문서는2026-10-05 확인했다.
- [1200m 연구](../20261004_1200_benchmarks/README.md)의 분석/검증 틀을새1300m스크립트로 복제·수정했다. 거리 분할·선택 표본·상태효과·개발선택·시간순 검증은1300m로별도 계산했다. 기존 숫자와운영 계수는입력하지 않았다.

주로상태는원천 숫자 함수율을검증한 건조1~5%,양호6~9%,다습10~14%,포화15~19%,불량20%이상이다. 연구용20% 시간 경계와동률 절반의 점수는자체 정의이며 마사회 공식평가나Timeform rating이 아니다. 이전 논문을새1300mpar나효율의 직접근거로사용하지 않았다.
