# 각질 연구의 출처와 범위

2026-10-08. [한국마사회 경주기록 정보의 공식 제공기관 안내](https://data.mafra.go.kr/opendata/data/indexOpenDataDetail.do?data_id=20220715000000002224)는 기관과 경주기록 서비스의 확인용이다. 이번 수치는 아래 보존 원문을 직접 계산했으며, 공식 기관이 이번 연구의 각질 경계나 성향 판정 기준을 정했다는 뜻이 아니다. 온라인 검색의 게임 각질·민간 예상지 분류는 분석 근거로 사용하지 않았다.

- 원문: `20260929_calendar_api_v1/raw/race_execution_probe/{2018..2026}/meet_{1,3}.json.gz`, API4_3/raceResult_3의18개 보존 응답. 신규 API 수집 없음.
- 검증된 실전 경주 키: [기존 선택 원장](../20261007_sex_ability_gap/outputs/selection_ledger.parquet),158,528완주자행·14,636경주. 원래 명단의 비정상486행을 복원해159,014행을 보존했다. 기존 정상151,074출전으로 한정하지 않았다.
- 공식 통과순위: 서울 `sjS1fOrd/sjG3fOrd/sjG1fOrd`,부산 `buS1fOrd/buG3fOrd/buG1fOrd`. 0을 후미로 대체하지 않았다. 반올림된 구간시간으로 공식 순위를 재구성하지 않았다.
- 출주두수: 검증 경주 키의 원문 전체명단 중 착순93/94/95를 제외한 기존 명단 계약. 비정상91/92·0을 완주착순으로 쓰지 않는다. 코드0인2행의 실제 주행을 확정하지 않고 결측 관측으로 보존했다.
- 이전 분류 확인: [기존 feature 코드](../../../src/horse_racing/analysis/features/style.py),[거리·등급 진단](../20261004_pace_distance_grade_diagnostic/README.md). feature의 최근5전 평균 rank/N 규칙과 웹의 다른 경계를 확인했으나 운영 코드를 수정하지 않았다.
- 기존 게이트·마군 연구의 실제 위치와 선행 실패의 인과효과를 혼동하지 않는다. 이번에는 실제 주행 경로·선두 착차·마군·영상·기수 의도·심판 사유를 추정하거나 새로 수집하지 않았다.

원문 파일별 SHA-256·기간·표본은 [source_audit.json](outputs/source_audit.json),시작 시 관련364개 파일은 [baseline_inventory.json](outputs/baseline_inventory.json),독립 재계산은 [verification.json](outputs/verification.json)에 있다. 보완 명단159,014행과 분류155,349행을 구분한다. 단계별 판단과 계산 전 경계는 [계획](PLAN.md)을 따른다.

서울2018-01-06~2026-09-20,부산2018-01-05~2026-09-18. 제주·영천·주행심사·주로빠르기 제외. 2024/2025년 이전 이력만 사용하는 시간순 검증이며 2026년은 관측 프로필에 사용한다. 운영 모델·DB·배포 변경 없음.
