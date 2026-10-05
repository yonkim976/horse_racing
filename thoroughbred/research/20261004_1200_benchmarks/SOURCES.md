# 서울 부산1200m 기록 기준의 출처

2026년 10월 4일. 원천의 해시·지역·기간은outputs/summary.json에 기록한다. 새 웹 경주 결과나 영천을 수집하지 않았다.

- [검증된 실전 구간 모집단](../20261003_sectional_pace_moisture/README.md)과 해당outputs/population.parquet: 서울·부산2018년 이후41,623행.
- [등급별 구간 연구](../20261004_grade1200_sectional/README.md):2024년 이후13,313행의 원시 기준. 원시 평균은 추정 표와 함께 보존한다.
- [정상 경주 원장](../20261002_gate_lateral_bias/README.md)과 해당outputs/runners.parquet: 등급·함수율과 말별 정식 착순·출전두수 연결에 사용.
- [Ridge 공식 문서](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.Ridge.html): L2 정규화의 목적과 구현. 실행 환경의 실제 버전은summary.json에 기록하며 최신 웹 문서의 버전을 실행 버전으로 혼동하지 않는다.
- [시간순 교차검증 공식 설명](https://scikit-learn.org/stable/modules/cross_validation.html): 미래 자료로 과거를 평가하지 않는 분리 원칙. 이번 코드는 고정 연도 구분을 직접 사용한다.
- [Stan 부분 통합 설명](https://mc-stan.org/learn-stan/case-studies/tutorial_rstanarm.html): 작은 집단이 공통 효과를 더 활용하는 개념적 근거. 이번 Ridge 구현을Stan 모형이나 베이지안 사후분포라고 부르지 않는다.
- [Timeform 구간 분석](https://www.timeform.com/horse-racing/features/rowley/the-timeform-knowledge-sectional-analysis-872015): 사용자가 제시한 향후 연구 방향. 이번 백분위 점수는 자체 상대 기록 척도이고Timeform 공식 rating·finishing speed par를 구현한 결과가 아니다.

주로상태는 건조1–5%, 양호6–9%, 다습10–14%, 포화15–19%, 불량20% 이상이다. 상태 효과는 관측 연관이며 인과효과가 아니다. 기록 점수의20% 경계는 연구에서 선택한 정의이며 마사회의 공식 평가선이 아니다.
