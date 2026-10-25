# 통과조 연구의 출처

2026-10-08. [마사회 공식 경주성적표 용어해설](https://race.kra.co.kr/raceScore/scoretableLayerExplanation.do?meet=1)을 직접 확인했다. S1F의 지점,괄호의1마신 미만 마군,내측부터의 내부 번호 순서와간격 구분이 공식 근거다. 연구의5/4구분 경계·최근5전3/5와4/5 기준은 공식 각질 분류가 아니다.

- [이전 각질 연구의 명단·순위](../20261008_running_style_foundation/outputs/observed_styles.parquet):159,014명단행·14,636검증 경주,원 출전번호·공식 통과순위·말 식별·날짜. 원문18파일 대조와비정상486행 복원·결측 보존은 [이전 연구](../20261008_running_style_foundation/README.md)를 따른다.
- [공식 통과조 선택 스냅샷](../20261002_moisture_position/outputs/passing_snapshot.parquet):28,781지점 원문,S1F14,636·서울3C8,583·부산G4F5,562지점. API303 기본·공식 성적표 보완 선택 문자열과선택 상태를 포함한다.
- [스냅샷 매니페스트](../20261002_moisture_position/outputs/snapshot_manifest.json):기존 연구 코어DB의읽기 전용 단일 트랜잭션에서 보존한 자료. 통과조 SHA-256 `a843cd4535aeb1d4758a46169b5798a6b801064ffd8f7e1b22ca75507fa83555`와이번 입력이 일치했다. 이번에는 DB를조회하거나 원천을재선택하지 않았다.
- [기존 마군 정의와관찰 연구](../20261002_moisture_position/README.md):첫 마군1두/여러 두와나머지마군 평균 위치 구분을 이어 사용한다. 기존 정상 완주 제한은 이번에 복제하지 않고 원 명단에 전체 통과조 일치를 요구했다.
- [이전 시간순 통계 도우미](../20261008_running_style_foundation/run.py):지역·거리·두수 기준 빈도와말/날짜 군집 함수를 재사용했다. 별도 문자 스캐너·빈도표·실제 이력 순서와스칼라 군집 통계로 독립 검증한다.

입력 해시·범위·공통/단독 관측·모순은 [source_audit.json](outputs/source_audit.json),보류 원문은 [notation_issues.csv](outputs/notation_issues.csv),기존 파일 목록·크기는 [baseline_inventory.json](outputs/baseline_inventory.json)에 있다. 같은 마군 내부 순서를 앞뒤 순위로 바꾸지 않으며 경합·기수 의도·실제 경로·절대 레일 거리·최적 각질을 확정하지 않는다. 새 API 수집·모델/DB/배포 변경 없음.
