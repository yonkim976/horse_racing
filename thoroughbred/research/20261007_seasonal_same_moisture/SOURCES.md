# 자료와 계산 출처

2026-10-07. 외부 날씨 자료를 결합하지 않은 동일 함수율 조건의 후향 계절 연구다. 기존 최종 품질 모집단의11거리151,074출전기록·13,928경주를 사용했다. 실제 종료일은 서울2026-09-20·부산2026-09-18이다.

- [1200m 기준](../20261004_1200_benchmarks/README.md)의 기초 [구간·함수율 모집단](../20261003_sectional_pace_moisture/README.md)에서 실전1200만 선택했다. rating0이하는 기존1200 분석과 같이 결측 처리했다. 주행심사1000m는 제외했다.
- [1300m](../20261005_1300_benchmarks/README.md), [1400m](../20261005_1400_benchmarks/README.md), [1600m](../20261006_1600_benchmarks/README.md), [1700/1800m](../20261006_1700_1800_benchmarks/README.md), [나머지1000/1900/2000/2200/2300m](../20261006_remaining_distance_benchmarks/README.md)의 outputs/population.parquet를 그대로 읽었다. 새 비율 절사나 거리별 품질 기준 변경은 하지 않았다.
- 개별 전체·구간 기록 및 과거 이력은 각 원 연구의 원API 대조를 거친 자료다. 이번에는 모든 선택 행의 전체·구간·함수율·통제변수를 원 입력과 다시 대조하고,11개 입력 파일의 SHA-256을 전후 확인했다. DB를 새로 조회하거나 변경하지 않았다. [입력 해시·모형 정의](outputs/summary.json), [독립 검증](outputs/verification.json).
- 월효과는 정확 함수율×연도×경주등급 안의 고정효과를 제거한 최소제곱으로 직접 계산했다. [NumPy pinv](https://numpy.org/doc/stable/reference/generated/numpy.linalg.pinv.html), [statsmodels OLS](https://www.statsmodels.org/stable/generated/statsmodels.regression.linear_model.OLS.html)는 계산 방법의 공식 설명이다. 본 구현은 자체 NumPy 코드이고 별도 SciPy 희소 더미 회귀로 대조했다.
- [statsmodels 날짜 등 집단의 공분산](https://www.statsmodels.org/stable/generated/statsmodels.stats.sandwich_covariance.cov_cluster.html), [가중 회귀](https://www.statsmodels.org/stable/generated/statsmodels.regression.linear_model.WLS.html)는2026-10-07 확인한 방법 참고다. 실제 주 보고서의95% 구간은 자체 날짜 군집 재표집200회의 분위수다. 분석 CSV에는 별도 날짜 집단 샌드위치 구간도 보존했다. 웹 문서의 버전과 실제 자체 구현을 구분한다.

겨울/봄/여름/가을의3개월 정의, 경주평균의 동일 가중치, 조화 매칭 가중치, 표본100경주·각10일/3년과 재표집180/200 기준은 이 연구의 사전 정의다. 공식 경마 보정 기준이 아니다. 많은 월·거리·상태·구간의 점별 구간을 동시에 보면 우연히 큰 차이가 나타날 수 있다. 실제 기온·바람·관리 변화나 당일 능력을 모두 통제한 인과효과, 사전 예측·수익 개선을 입증한 결과로 표현하지 않는다.
