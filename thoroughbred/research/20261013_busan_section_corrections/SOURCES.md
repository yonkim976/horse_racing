# 부산 구간 보정과 서울 비교 출처

2026-10-13.기존검증원천을읽기전용으로사용했다.

1.20261007_sex_ability_gap/outputs/population.parquet:2018년이후서울/부산고정모집단.
2.20261002_gate_lateral_bias/outputs/runners.parquet:원출전명단·번호·게이트순번.
3.20261008_record_normalization_seconds와20261008_detached_tail_sensitivity:고정이상치/이탈후미표식.
4.thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb의section_measurements_api:누적시간과API원본경로/행번호.
5.20260929_calendar_api_v1/raw/race_execution_probe의2018~2026meet_3.json.gz:62,831행전수대조.원천별SHA-256은outputs/summary.json.
6.20261011_seoul_section_corrections:서울계측연결·계수·모형·후보·고정보정정책.이전서울파일은변경하지않았다.
7.20261008_environment_correction_atlas및선행모형코드:지원기준·통제변수·군집분산.
8.docs/SECTION_POINT_LOAD_PLAN_2026-09-24.md:부산펄롱/누적/막판구분.공식참조는https://race.kra.co.kr/raceScore/cornerRecordDesc.do 및https://race.kra.co.kr/chulmainfo/RacingcourseStructure.do?Act=02&Sub=10&meet=3.

이번새웹수집은없다.원천은숫자크기추정이아닌cumulative_time과bu*AccTime필드로구분했다.입력파일및재사용서울파일해시를summary.json에보존했다.
