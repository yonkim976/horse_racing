# 경기장 거리별 환경 보정과 내외측 분석의 자료

2026-10-08. 이 연구는 고정된 로컬 자료를 읽기 전용으로 사용한다. 외부 데이터·풍향·풍속·주로빠르기를 추가하지 않았다.

- [구간 시험표](../20261008_section_normalization_candidate_v1/README.md):출발200m·마지막600m·마지막200m의 함수율·전체/최근 월·게이트 후보. [게이트](../20261008_section_normalization_candidate_v1/outputs/section_gate_lookup.csv), [월](../20261008_section_normalization_candidate_v1/outputs/section_month_lookup.csv), [함수율](../20261008_section_normalization_candidate_v1/outputs/section_moisture_reference.csv)를 보존했다.
- [전체 시험표](../20261008_gate_model_candidate_v1/README.md):전체시간 게이트·함수율·월 기준. 함수율 채택 여부와 원 참조의 지원 여부를 구분했다. 전체 월의 최근·누락 거리 보충만 새 민감도 모형에서 계산했다.
- [이탈 후미 연구](../20261008_detached_tail_sensitivity/README.md):완전한 명단의 선두·중위·MAD 표식. 실제 느린 경기 기록을 삭제하지 않는다.
- [원 출전 자료](../20261007_sex_ability_gap/outputs/population.parquet), [게이트 완전 명단](../20261002_gate_lateral_bias/outputs/runners.parquet), [기존4MAD 원장](../20261008_record_normalization_seconds/outputs/runner_normalization_candidates.parquet):말·등급·날짜·함수율·기록·원래 두수 및 명단.
- [마군 상대 위치](../20261003_joint_gate_lateral_smoothing/outputs/observations.parquet), [위치 시간 모형](../20261008_gate_lateral_seconds/analyze.py):같은 마군과 같은 말×거리 통제·가중치·지원 기준을 재사용했다. 마군 상대 위치이며 레일 거리나 실제 주행 경로가 아니다.
- [서울1200m4C 잔여 계측](../20261004_seoul4c_finish/outputs/runner_4c_analysis.parquet):2024년 이후 실제 관측에만 연결했다. 미계측 지점 이후 시간을 생성하지 않았다.
- [분석 입력 SHA256](outputs/analysis_summary.json) · [합산 입력 SHA256](outputs/build_summary.json) · [검증](outputs/verification.json) · [계획](PLAN.md).

전체·최근 기간은 겹친다. 전체거리·정확거리 및 겹치는 구간은 독립 증거가 아니다. 연도/분기 노출 평균은 해당 시기의 새 환경 편향을 추정한 값이 아니고, 내외측 연도/분기 단순 표는 같은 마군 차이의 기술통계다. 양수 보정과 양수 외측−내측 시간차는 해석이 다르므로 별도 표로 보존했다. 연구용 합산 후보·기존 채택·운영 모델 반영을 구분한다.
