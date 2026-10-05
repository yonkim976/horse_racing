# 1200m 등급별 연구의 출처와 지역 구분

확인일2026-10-04. 원천 관측의 마지막 날짜와 확인일은 다르다. DB의 정식 경주 확정 원장만 분석하며 현재 웹에 게시된 출전예정 경주를 기록으로 넣지 않는다.

## 저장 원천

- 이전 [독립 구간 연구](../20261003_sectional_pace_moisture/README.md)의 `outputs/population.parquet`: 서울·부산 정상완주1200m41,623행,2018년 이후. 원천충돌 제외와 시간 검증을 승계했다.
- [게이트 연구](../20261002_gate_lateral_bias/README.md)의 `outputs/runners.parquet`: 완전 착순·6두 이상·취소/비정상 완주 구분 및 당일보다 앞선 과거 이력. 이번 연구에서 순위를 연결해 우승·3위 이내 표를 구분했다.
- `thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb`: 읽기 전용. `confirmed_races`, `confirmed_runners`의 실제 개최지 영천 및source_meet4로 구분했다. 심사·진료 등 통합영남 코드3과 실제 정식 경주 코드4를 혼동하지 않는다.
- `../20260929_calendar_api_v1/raw/race_execution_probe/2026/meet_4.json.gz`: 전체 응답291행 중 확정 정식 경주119행만 DB의source_item_index로 대조했다. 그중1200m50행을 선택했다. 응답 전체의 시험/미확정 항목을 정식 기록에 재포함하지 않는다.
- 영천 API 직접 구간은 `buS1fAccTime`, `bu_1fGTime`, `bu_2fGTime`, `bu_3fGTime`. 마지막600 직접값이0인11행은 유효한 `rcTime−buG3fAccTime`를 사용했다.39행의 직접값과 같은 누적 계산을 대조했다. 이 계산은 실제600m 남은 통과 지점을 이용하며 코너 이름으로 임의 거리를 부여한 것이 아니다.

입력별 SHA-256은 [summary.json](outputs/summary.json), 원천·독립 집계 검증 결과는 [verification.json](outputs/verification.json)에 기록한다.

## 공식 지역과 시행계획 확인

- [한국마사회 영남경마 시행개요](https://race.kra.co.kr/raceoper/RaceoperView.do?Act=13&Sub=1&meet=3):2026년 계획에서 영남권역 안의 부산경남과 영천을 구분한다. 영천 계획 개최기간9월13일~12월6일. 계획은 실제 개별 경주 결과의 증거를 대신하지 않는다.
- [한국마사회2026년 주요변경사항](https://race.kra.co.kr/raceoper/RaceoperView.do?Act=13&Sub=2&meet=3): 영천 개장 및 순회경마, 계획72경주를 안내한다. 본 연구의 실제 영천 표본은9월13일·20일 확정 결과다.
- [한국마사회 전체 출전정보](https://race.kra.co.kr/thisweekrace/ThisWeekDetailInfoList.do?Act=01&Sub=2&meet=): 실제 출전정보 화면에서도 영천과 부경을 별도 지역으로 표시한다.2026-10-04 확인 화면의10월4일·5일 출전예정은 이번 저장본 분석에 포함하지 않았다.

## 이번 연구가 확정하지 않는 것

평균·중앙값·P10–P90는 해당 등급과 모집단의 경험적 분포다. 등급 사이 초 차이는 승급 때 자동으로 빼줄 보정값이 아니며, 영천 두 날짜의 차이는 고유한 주로속도의 인과효과가 아니다. 최적 Timeform par와 새로운 구간 보정계수는 확정하지 않았다.
