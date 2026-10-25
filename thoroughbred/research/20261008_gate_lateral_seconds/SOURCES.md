# 게이트와 상대 주행위치 시간 연구의 출처

- [기존151,074출전](../20261007_sex_ability_gap/outputs/population.parquet):마필·등급·중량·체중·과거 이력·전체와구간시간.
- [151,115출전 게이트](../20261002_gate_lateral_bias/outputs/runners.parquet):마번·취소 후두수·게이트그룹. 전체시간 일치를 대조했다.
- [2두 이상 상대위치](../20261003_joint_gate_lateral_smoothing/outputs/observations.parquet):435,537출전마×지점. 상대위치의 기존 파싱·마군 정의를 유지했다.
- [직전 시간 연구 원장](../20261008_record_normalization_seconds/outputs/runner_normalization_candidates.parquet) · [프로필](../20261008_record_normalization_seconds/outputs/joint_seconds_profiles.csv) · [코드](../20261008_record_normalization_seconds/analyze.py):149,624출전의이상치 기준과 마필모형 민감도. 원 기준을 바꾸지 않았다.
- [서울1200m4C계측](../20261004_seoul4c_finish/outputs/runner_4c_analysis.parquet):2024년이후7,897행의실제4C 이후시간을 해당 표본에만 연결했다.
- [계획](PLAN.md) · [계산](analyze.py) · [독립대조](verify.py) · [입력해시](outputs/summary.json) · [검증](outputs/verification.json).

새DB조회·외부자료 수집·풍향·풍속·주로빠르기 추가는 없다. 미계측 경로 길이·잔여거리 시간을 생성하지 않았다. 원 연구와운영모형·보정 채택은 변경하지 않았다.
