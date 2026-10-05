# 결론 모음의 원 보고서

2026년 10월 5일 갱신. 기존 주로환경 검증을 이어 진행한 주로·전개·게이트·주행심사20개 연구를 대상으로 한다. 분석 코드·계획·원천 해시·상세 결과는 각 원 보고서의 기존 위치에서 유지한다. 결론 모음의 최신 공동모형과 이전 단독모형은 추정 조건이 다르며 이전 수치가 단순 오류로 대체된 것은 아니다.

## 기존 연구와 일치 검증

- 이전 참조 연구: [주로 공통 잔차 최종 보고서](../../../research/track_common_residual_20260928/FINAL_REPORT_KO.md)
- 1. [주로환경 원천 일치 검증](../20261002_track_source_reconciliation/README.md)

## 함수율 전체시간 전개 이상치 등급

- 2. [함수율만 사용한 환경 재분석](../20261002_moisture_only/README.md)
- 3. [거리별 함수율 환산 후 재학습](../20261002_moisture_distance_retrain/README.md)
- 4. [함수율 거리 실제 앞뒤 주행위치](../20261002_moisture_position/README.md)
- 5. [이상치 보수적 환산 등급 검증](../20261002_moisture_robust_grade/README.md)
- 6. [전체시간 보정률 탐색](../20261002_moisture_strength_selection/README.md)
- 결정 원문: [전체시간 함수율 보정 결정](../../docs/TRACK_MOISTURE_CORRECTION_DECISION_2026-10-02.md)
- 이 폴더의 열람 사본: [전체시간 결정과 거리별 표](01_TRACK_MOISTURE.md)

25~50%라는 초기 부분 보정 후보는 이후 보정률 선택과 사용자 합의를 거쳐 서울80%·부산90% 연구 기준으로 갱신됐다. 초기 탐색 보고서의 후보를 현행 기준으로 읽지 않는다.

## 구간기록

- 7. [구간별 함수율 보정률 검증](../20261002_moisture_section_strength/README.md)
- 검토 원문: [구간기록 보정 상태](../../docs/TRACK_MOISTURE_SECTION_CORRECTION_STATUS_2026-10-02.md)
- 이 폴더의 열람 사본: [구간기록 후보와 보류 이유](02_SECTION_TIME.md)

## 게이트 주행위치 최근 보정

- 8. [거리별 게이트와 상대 내외측](../20261002_gate_lateral_bias/README.md)
- 9. [날짜 주말 월별 세부 변화](../20261003_gate_lateral_time_windows/README.md)
- 10. [내측 중간 외측 세 단계](../20261003_three_lateral_positions/README.md)
- 11. [2두 포함 공동 추정과 최근 완화](../20261003_joint_gate_lateral_smoothing/README.md)

## 주행심사 시간 기준점

- 12. [서울·부산1000m 주행심사 전체·구간시간 기초 기준점](../20261003_trial_time_baselines/README.md)
- 이 폴더의 결론: [공식 합격 규정과 실제 시간 분포](05_TRIAL_TIME_BASELINES.md)
- 새 연구의 [공식·방법 출처](../20261003_trial_time_baselines/SOURCES.md)에서 마사회 시행계획·API·Timeform 글을 구분한다.

## 함수율과 구간 전개

- 13. [신마1000m·실전1200m 함수율별 독립 구간과 초중반별 막판](../20261003_sectional_pace_moisture/README.md)
- 이 폴더의 결론: [조건부 막판 해석과 기존 보정 유지](06_SECTIONAL_PACE_MOISTURE.md)

## 서울 부산 영천1200m 등급별 구간

- 14. [지역·원천등급별1200m 구간·함수율·전개와 영천 소표본](../20261004_grade1200_sectional/README.md)
- 이 폴더의 결론: [등급별 기록과 영천 기준 미확정](07_GRADE1200_SECTIONS.md)
- [출처와 지역 구분](../20261004_grade1200_sectional/SOURCES.md), [새 산출물 용량](../20261004_grade1200_sectional/outputs/artifact_inventory.json)

## 서울 부산1200m 추정 기록과 거리별 평가 기준

- 15. [서울·부산1200m의100조합 추정 평균·상하위 기록·두 점수](../20261004_1200_benchmarks/README.md)
- 이 폴더의 결론: [거리별 기록 기준과1200m 추정](08_DISTANCE_RECORD_BENCHMARKS.md)
- [거리별 공통 연구 기준](../DISTANCE_RECORD_BENCHMARK_POLICY.md), [새 산출물 용량](../20261004_1200_benchmarks/outputs/artifact_inventory.json)

## 서울1200m 4C 이후 마무리

- 16. [4C 이후 기록·두 부분·통과순위·시간차 회복 연구](../20261004_seoul4c_finish/README.md)
- 이 폴더의 결론: [서울4C 이후 마무리와 추입 기준](09_SEOUL4C_FINISH.md)
- [공식 계측 설명과 원API 대조](../20261004_seoul4c_finish/SOURCES.md), [산출물 용량](../20261004_seoul4c_finish/outputs/artifact_inventory.json)

## 구간 상대속도와par 후보

- 17. [서울·부산1200m 비율 분포·좋은 기록 집단par 후보·과거 이력 예측 비교](../20261004_relative_speed_par_v1/README.md)
- 이 폴더의 결론: [구간 상대속도·par 후보와 한계](10_RELATIVE_SPEED_PAR.md)
- [공식·방법 출처](../20261004_relative_speed_par_v1/SOURCES.md),[독립 검증](../20261004_relative_speed_par_v1/outputs/verification.json),[산출물 용량](../20261004_relative_speed_par_v1/outputs/artifact_inventory.json)

## 총중량 대비 부담중량

- 18. [서울·부산1200m 체중 비율·동일 표본12모형·과거 구간이력 추가 비교](../20261005_relative_load1200/README.md)
- 이 폴더의 결론: [총중량 대비 부담중량의 추가 정보](11_RELATIVE_LOAD1200.md)
- [공식 정의·원자료·시점](../20261005_relative_load1200/SOURCES.md),[검증](../20261005_relative_load1200/outputs/verification.json),[용량](../20261005_relative_load1200/outputs/artifact_inventory.json)

## 서울·부산1300m 기록 기준

- 19. [1300m 등급·함수율40조합 추정과60조합 참조 부재](../20261005_1300_benchmarks/README.md)
- 이 폴더의 결론: [1300m 기록과구간 기준](12_BENCHMARK1300.md)
- [원천·방법](../20261005_1300_benchmarks/SOURCES.md),[검증](../20261005_1300_benchmarks/outputs/verification.json),[용량](../20261005_1300_benchmarks/outputs/artifact_inventory.json)

## 서울·부산1400m 기록 기준

- 20. [1400m 10등급·주로상태100조합 기준과구간](../20261005_1400_benchmarks/README.md)
- 이 폴더의 결론: [1400m 기준과소표본](13_BENCHMARK1400.md)
- [원천·방법](../20261005_1400_benchmarks/SOURCES.md),[검증](../20261005_1400_benchmarks/outputs/verification.json),[용량](../20261005_1400_benchmarks/outputs/artifact_inventory.json)

## 이 모음의 검증 범위

01·02는 결정 원문 본문을 그대로 보존하고 링크 경로와 사본 안내를 추가했다. 03·04·05·06·07·08·09·10·11·12·13과 통합 목록은 위 보고서의 결론을 주제별로 요약했다. 결론 모음을 위한 기존11개 분석 재실행은 하지 않았다. 새 주행심사 기준점·구간 전개·1200m 등급별·추정 기록 기준·서울4C 이후·구간 상대속도·중량 비율·1300m·1400m기준 연구는 별도로 계산·검증한 결과를 추가했다. 문서 링크·원본 해시·사본 내용 보존을 확인했다.

[source_manifest.json](source_manifest.json)은 23개 출처 문서와 이 폴더의15개 Markdown 파일의 SHA-256을 기록한다. 출처가 이후 개정되면 기존 결론에 자동 반영되는 구조가 아니므로 비교 후 결론 모음을 갱신해야 한다. 이 목록은 프로젝트 전체의 데이터 수집·모델·장구·진료·조교 연구까지 포함하는 전체 감사 목록이 아니다.
