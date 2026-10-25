# 서울 구간 환경 보정 출처

2026-10-11.새 웹 수집 없이 기존 검증 원자료를 읽기 전용으로 사용했다.

1.20261007_sex_ability_gap/outputs/population.parquet:2018년 이후 고정 모집단과 기본 구간.
2.20261002_gate_lateral_bias/outputs/runners.parquet:원 출전명단·게이트 번호/순번.
3.20261008_record_normalization_seconds의 원장:기존4MAD/trim5 표식.
4.20261008_detached_tail_sensitivity/outputs/runner_tail_flags.parquet:원 출전명단에서 만든 이탈후미 표식.
5.thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb의section_measurements_api:서울 지점 누적시간.원 응답 파일/행으로88,243출전 전수 대조.
6.20260929_calendar_api_v1/raw/race_execution_probe의2018~2026서울 보관 응답.파일 해시와 검사 건수는outputs/summary.json.
7.20261008_environment_correction_atlas와선행모형 코드:설계·군집 분산·지원 기준 및 비교 후보.
8.docs/SECTION_POINT_LOAD_PLAN_2026-09-24.md,docs/SEOUL_SECTION_REPAIR_2026-09-08.md,20261004_seoul4c_finish/SOURCES.md:계측 종류와코너 좌표 한계.
9.마사회 공식 지점 설명:https://race.kra.co.kr/raceScore/scoretableLayerExplanation.do?meet=1.앞선 대화에서 확인.일반530m 설명을 거리별 실제 경로 길이나200m 실측으로 바꾸지 않는다.

입력 DB·원장·실행 모듈의SHA-256은summary.json.시간종류를 수치 크기로 추정하지 않고원천 cumulative_time만 사용했다.
