# 결론 모음의 원 보고서

2026년 10월 8일 갱신. 기존 주로환경 검증을 이어 진행한 주로·전개·게이트·주행심사·거리별 기준·성별·연령·말별 거리 적성41개 연구를 대상으로 한다. 분석 코드·계획·원천 해시·상세 결과는 각 원 보고서의 기존 위치에서 유지한다. 결론 모음의 최신 공동모형과 이전 단독모형은 추정 조건이 다르며 이전 수치가 단순 오류로 대체된 것은 아니다.

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

## 서울·부산1600m 기록 기준

- 21. [1600m 85조합·전체와 구간560행 및 서울15조합 참조 부재](../20261006_1600_benchmarks/README.md)
- 이 폴더의 결론: [1600m 기준과 서울 잠정 추정](14_BENCHMARK1600.md)
- [원천·방법](../20261006_1600_benchmarks/SOURCES.md), [검증](../20261006_1600_benchmarks/outputs/verification.json), [용량](../20261006_1600_benchmarks/outputs/artifact_inventory.json)

## 서울1700m 후속 표본 사전 점검

- [국5·국6 경주와 출전 여부](../20261006_seoul1700_coverage/README.md), [원천](../20261006_seoul1700_coverage/SOURCES.md), [검증](../20261006_seoul1700_coverage/outputs/verification.json), [용량](../20261006_seoul1700_coverage/outputs/artifact_inventory.json)
- 사전 점검 당시 완료된21개 연구와 구분한 출전 여부 확인이다. 이후 아래1700m·1800m 기준 연구를 완료했다.

## 서울1700m 기록 기준

- 22. [서울1700m 국5·국6 포함25조합·150구간행](../20261006_1700_1800_benchmarks/1700/README.md)
- 이 폴더의 결론: [1700m 기준과 미관측 추정 한계](15_BENCHMARK1700.md)
- [공통 원천](../20261006_1700_1800_benchmarks/SOURCES.md), [독립 검증](../20261006_1700_1800_benchmarks/1700/outputs/verification.json)

## 서울·부산1800m 기록 기준

- 23. [1800m 지역별9등급90조합·585구간행](../20261006_1700_1800_benchmarks/1800/README.md)
- 이 폴더의 결론: [1800m 기준과 서울 국5 검증 참조](16_BENCHMARK1800.md)
- [공통 원천](../20261006_1700_1800_benchmarks/SOURCES.md), [독립 검증](../20261006_1700_1800_benchmarks/1800/outputs/verification.json), [전체 작업 용량](../20261006_1700_1800_benchmarks/outputs/artifact_inventory.json)

## 이 모음의 검증 범위

01·02는 결정 원문 본문을 그대로 보존하고 링크 경로와 사본 안내를 추가했다. 03·04·05·06·07·08·09·10·11·12·13·14·15·16과 통합 목록은 위 보고서의 결론을 주제별로 요약했다. 결론 모음을 위한 기존11개 분석 재실행은 하지 않았다. 새 주행심사 기준점·구간 전개·1200m 등급별·추정 기록 기준·서울4C 이후·구간 상대속도·중량 비율·1300m·1400m·1600m·1700m·1800m 기준 연구는 별도로 계산·검증한 결과를 추가했다. 문서 링크·원본 해시·사본 내용 보존을 확인했다.

[source_manifest.json](source_manifest.json)은 27개 출처 문서와 이 폴더의18개 Markdown 파일의 SHA-256을 기록한다. 출처가 이후 개정되면 기존 결론에 자동 반영되는 구조가 아니므로 비교 후 결론 모음을 갱신해야 한다. 이 목록은 프로젝트 전체의 데이터 수집·모델·장구·진료·조교 연구까지 포함하는 전체 감사 목록이 아니다.

## 1000m 남은 거리 기록 기준

- 24. [실전1000m 20조합·130행과 주행심사 구분](../20261006_remaining_distance_benchmarks/1000/README.md)
- 이 폴더의 결론: [1000m 기준과 한계](17_BENCHMARK1000.md)
- [공통 원천](../20261006_remaining_distance_benchmarks/SOURCES.md), [독립 검증](../20261006_remaining_distance_benchmarks/1000/outputs/verification.json), [전체 작업 용량](../20261006_remaining_distance_benchmarks/outputs/artifact_inventory.json)

## 1900m 남은 거리 기록 기준

- 25. [1900m 서울 한 경주 잠정치·부산 최근 참조 없음](../20261006_remaining_distance_benchmarks/1900/README.md)
- 이 폴더의 결론: [1900m 기준과 한계](18_BENCHMARK1900.md)
- [공통 원천](../20261006_remaining_distance_benchmarks/SOURCES.md), [독립 검증](../20261006_remaining_distance_benchmarks/1900/outputs/verification.json), [전체 작업 용량](../20261006_remaining_distance_benchmarks/outputs/artifact_inventory.json)

## 2000m 남은 거리 기록 기준

- 26. [2000m 35조합·225행과 부산 국OPEN 한 날짜](../20261006_remaining_distance_benchmarks/2000/README.md)
- 이 폴더의 결론: [2000m 기준과 한계](19_BENCHMARK2000.md)
- [공통 원천](../20261006_remaining_distance_benchmarks/SOURCES.md), [독립 검증](../20261006_remaining_distance_benchmarks/2000/outputs/verification.json), [전체 작업 용량](../20261006_remaining_distance_benchmarks/outputs/artifact_inventory.json)

## 2200m 남은 거리 기록 기준

- 27. [부산2200m 두 경주 잠정치·시간순 검증 불가·포화 부재](../20261006_remaining_distance_benchmarks/2200/README.md)
- 이 폴더의 결론: [2200m 기준과 한계](20_BENCHMARK2200.md)
- [공통 원천](../20261006_remaining_distance_benchmarks/SOURCES.md), [독립 검증](../20261006_remaining_distance_benchmarks/2200/outputs/verification.json), [전체 작업 용량](../20261006_remaining_distance_benchmarks/outputs/artifact_inventory.json)

## 2300m 남은 거리 기록 기준

- 28. [서울2300m 6일 참조·불량 부재](../20261006_remaining_distance_benchmarks/2300/README.md)
- 이 폴더의 결론: [2300m 기준과 한계](21_BENCHMARK2300.md)
- [공통 원천](../20261006_remaining_distance_benchmarks/SOURCES.md), [독립 검증](../20261006_remaining_distance_benchmarks/2300/outputs/verification.json), [전체 작업 용량](../20261006_remaining_distance_benchmarks/outputs/artifact_inventory.json)

## 같은 함수율 숫자의 월별·계절별 기록 경향

- 29. [11거리의 같은 연도·등급·함수율 숫자 비교](../20261007_seasonal_same_moisture/README.md)
- 이 폴더의 결론: [계절 경향과 새 보정 미채택](22_SEASONAL_SAME_MOISTURE.md)
- [원천·방법](../20261007_seasonal_same_moisture/SOURCES.md), [독립 검증](../20261007_seasonal_same_moisture/outputs/verification.json), [게시 요약](../20261007_seasonal_same_moisture/PUBLICATION.md), [산출물 용량](../20261007_seasonal_same_moisture/outputs/artifact_inventory.json)

## 같은 함수율의 월별 세분화 후속 연구

- 30. [11거리 월별 기록 특성](../20261007_monthly_same_moisture/README.md)
- [중앙 결론](23_MONTHLY_SAME_MOISTURE.md) · [출처](../20261007_monthly_same_moisture/SOURCES.md) · [숫자 검증](../20261007_monthly_same_moisture/outputs/verification.json) · [게시 요약](../20261007_monthly_same_moisture/PUBLICATION.md) · [용량 명세](../20261007_monthly_same_moisture/outputs/artifact_inventory.json)
- 앞선 검증된 월별 회귀를 재사용하고 같은 날짜 재표집의 월간 차이·완결연도 직접 매칭을 새로 계산했다. 기존 계절 원본·기준표·운영은 변경하지 않았다.

## 2024년 전후 기록 수준과구간 배분 변화

- 31. [동일 등급·정확 함수율·월의 시대 비교](../20261007_era_record_trends/README.md)
- [중앙 결론](24_ERA_RECORD_TRENDS.md) · [원천](../20261007_era_record_trends/SOURCES.md) · [숫자 검증](../20261007_era_record_trends/outputs/verification.json) · [게시 요약](../20261007_era_record_trends/PUBLICATION.md) · [산출물 용량](../20261007_era_record_trends/outputs/artifact_inventory.json)
- 주 비교는2018~2023년 대2024~2026년의 각1~8월이며 완결연도·가까운기간·부분2026년 포함 여부를 별도 점검했다. 기존 기록 기준·함수율 보정·운영을 변경하지 않았다.


## 암말·수말·거세마의 기록과 경기력

- 32. [출전 당시 성별·조건부 기록·같은 경주 성과·최근 격차](../20261007_sex_ability_gap/README.md)
- [중앙 결론](25_SEX_ABILITY_GAP.md) · [원천/방법/해시](../20261007_sex_ability_gap/SOURCES.md) · [검증](../20261007_sex_ability_gap/outputs/verification.json) · [보조 검증](../20261007_sex_ability_gap/outputs/supplement_verification.json) · [게시 요약](../20261007_sex_ability_gap/PUBLICATION.md) · [파일별 용량](../20261007_sex_ability_gap/outputs/artifact_inventory.json)
- 기존11거리151,074행·13,928경주를 그대로 재사용했다. 원래 출전자159,014행으로 선택 민감도를 추가했다. 기존 연구·함수율 보정·거리 기준·운영은 변경하지 않았다. <!-- sex_ability_gap_v1 -->

## 평균 연령 곡선과 출전 중단

- 33. [출전 집단 연령 곡선·같은 말 변화·중단 전 기록](../20261007_age_curve_exit/README.md)
- [중앙 결론](26_AGE_CURVE_EXIT.md) · [출처](../20261007_age_curve_exit/SOURCES.md) · [계획](../20261007_age_curve_exit/PLAN.md) · [검증](../20261007_age_curve_exit/outputs/verification.json) · [게시 요약](../20261007_age_curve_exit/PUBLICATION.md) · [용량 명세](../20261007_age_curve_exit/outputs/artifact_inventory.json)
- 기존151,074행을 재사용하고 전체 실제 출발326,157행에서 이후 출전을 확인했다. 365일 무출전과 확정 퇴사를 구분하며, 새 연령 보정·운영 변경은 하지 않았다.


## 성별 평균 체중과 거리별 성과 후속

기존32번 성별 연구의 후속으로 [마체중과 거리 상호작용](../20261007_sex_weight_distance_followup/README.md)을 추가했다.151,074행을 읽기 전용 재사용하고 세 성별 쌍·공동모형 직접 대비·같은 경주·완결2024~2025년 민감도를 계산했다. [중앙 결론](25A_SEX_WEIGHT_DISTANCE.md) · [출처/해시](../20261007_sex_weight_distance_followup/SOURCES.md) · [독립 검증](../20261007_sex_weight_distance_followup/outputs/verification.json) · [게시 자료](../20261007_sex_weight_distance_followup/PUBLICATION.md) · [용량](../20261007_sex_weight_distance_followup/outputs/artifact_inventory.json). 기존 독립 연구 수·기준·운영은 변경하지 않았다. <!-- sex_weight_distance_followup_v1 -->


## 5위 이내 성별 기록과 성과 후속

기존32번 성별 연구의 추가 후속으로 [상위5위 기록/전체 출전자 진입 성과](../20261007_sex_top5_followup/README.md)를 추가했다. 원151,074행 중69,639행·입력5개 해시·432이전 결과 재현·252독립 모형행·1073수치 검사를 보존했다. [중앙25B](25B_SEX_TOP5.md) · [출처](../20261007_sex_top5_followup/SOURCES.md) · [검증](../20261007_sex_top5_followup/outputs/verification.json) · [게시 요약](../20261007_sex_top5_followup/PUBLICATION.md) · [용량](../20261007_sex_top5_followup/outputs/artifact_inventory.json). 이전 연구·독립 연구 수·기준·운영 변경 없음. <!-- sex_top5_followup_v1 -->


## 주로 보정 결과의 종합

[기존 연구의 종합 적용안](../20261007_track_correction_synthesis/README.md) · [중앙 요약](04A_TRACK_TOTAL_CORRECTION.md) · [출처 대조](../20261007_track_correction_synthesis/outputs/verification.json) · [용량](../20261007_track_correction_synthesis/outputs/artifact_inventory.json). 01·03·04·23번 결론을 대조한 설계이며 새 독립 연구나 수치 채택이 아니다.


## 서울1600m 게이트 거리 간 비교 후속

[원 연구와 상세표](../20261007_seoul1600_gate_comparison/README.md) · [중앙 결론](03A_SEOUL1600_GATE.md) · [계획](../20261007_seoul1600_gate_comparison/PLAN.md) · [별도 부분회귀 검증](../20261007_seoul1600_gate_comparison/outputs/independent_verification.json) · [용량](../20261007_seoul1600_gate_comparison/outputs/artifact_inventory.json). 기존 게이트 모집단 재사용, 거리 간 공분산·다중비교와 사후 10두 분석을 구분했다.


## 부산 게이트 거리 간 비교 후속

[원 연구와 상세표](../20261007_busan_gate_comparison/README.md) · [중앙 결론](03B_BUSAN_GATE.md) · [계획](../20261007_busan_gate_comparison/PLAN.md) · [별도 부분회귀 검증](../20261007_busan_gate_comparison/outputs/independent_verification.json) · [용량](../20261007_busan_gate_comparison/outputs/artifact_inventory.json). 기존 부산 모집단 재사용, 모든 거리 쌍의 공분산·다중비교·최근·12두 민감도를 대조했다.


## 게이트 전용 번호·기간·예측 후속

[원 보고서](../20261008_gate_only_followup/README.md) · [중앙 결론](03C_GATE_ONLY_FOLLOWUP.md) · [계획](../20261008_gate_only_followup/PLAN.md) · [출처](../20261008_gate_only_followup/SOURCES.md) · [게시 요약](../20261008_gate_only_followup/PUBLICATION.md) · [독립 대조](../20261008_gate_only_followup/outputs/verification.json) · [기간표 보존 검증](../20261008_gate_only_followup/outputs/period_table_verification.json) · [용량](../20261008_gate_only_followup/outputs/artifact_inventory.json). 기존 모집단151,115출전·13,928경주 재사용. 번호별386대비와 과거 자료만 쓰는 예측후보11개를 별도 검증했다. 새 초·확률 가산이나 운영 변경은 없다.


## 완주시간의 함수율 월 게이트 보정량 연구

34번째 연구 [원 보고서](../20261008_record_normalization_seconds/README.md) · [중앙 결론](04B_RECORD_NORMALIZATION_SECONDS.md) · [계획](../20261008_record_normalization_seconds/PLAN.md) · [출처](../20261008_record_normalization_seconds/SOURCES.md) · [게시 요약](../20261008_record_normalization_seconds/PUBLICATION.md) · [독립 검증](../20261008_record_normalization_seconds/outputs/verification.json) · [용량](../20261008_record_normalization_seconds/outputs/artifact_inventory.json). 기록 보정량 탐구이며 다음 경주 예측 검증과 새 보정 채택은 수행하지 않았다.


## 게이트와 상대 주행위치의 시간 차이 후속

35번째 연구 [원 보고서](../20261008_gate_lateral_seconds/README.md) · [중앙 결론](04C_GATE_LATERAL_SECONDS.md) · [계획](../20261008_gate_lateral_seconds/PLAN.md) · [출처](../20261008_gate_lateral_seconds/SOURCES.md) · [게시 요약](../20261008_gate_lateral_seconds/PUBLICATION.md) · [독립 검증](../20261008_gate_lateral_seconds/outputs/verification.json) · [용량](../20261008_gate_lateral_seconds/outputs/artifact_inventory.json). 같은 경주·마군 및마필 고정효과의 초 단위 후속. 남은 시간과 최종시간을 구분했다. 새 보정 채택·운영 변경·다음 경주 예측 검증은 없다.


## 마체중별 부담중량과 기록 차이 후속

기존11번의 [체중×중량 직접 대비](../20261008_body_load_time_loss/README.md)를 추가했다.151,074행 재사용·65모형/3705대비·23독립 모형/366대비·760수치검사를 보존했다. [중앙11A](11A_BODY_LOAD_TIME.md) · [출처](../20261008_body_load_time_loss/SOURCES.md) · [독립 검증](../20261008_body_load_time_loss/outputs/verification.json) · [게시요약](../20261008_body_load_time_loss/PUBLICATION.md) · [용량](../20261008_body_load_time_loss/outputs/artifact_inventory.json). 조건부 관찰 연구이며 기존 독립연구수·원 결과·운영은변경하지 않았다. <!-- body_load_time_followup_v1 -->


## 함수율 상태와 게이트의 시간 교차 연구

36번째 연구 [원 보고서](../20261008_moisture_gate_seconds/README.md) · [중앙 결론](04D_MOISTURE_GATE_SECONDS.md) · [고정 계획](../20261008_moisture_gate_seconds/PLAN.md) · [출처](../20261008_moisture_gate_seconds/SOURCES.md) · [게시 요약](../20261008_moisture_gate_seconds/PUBLICATION.md) · [검증](../20261008_moisture_gate_seconds/outputs/verification.json) · [용량](../20261008_moisture_gate_seconds/outputs/artifact_inventory.json). 같은 경주·마필 통제 후 상태×게이트 대비와 건조 대비 상호작용. 희소 장거리 효과 미생성, 새 보정 채택·운영 변경·다음 경주 검증 없음.


## 성별 구분 없는 부담중량 평균 보정 후속

기존11번의 [단일 kg 후속](../20261008_carried_weight_correction/README.md)을 추가했다.151,074행을읽기전용재사용해동일말/경주·이력을맞추고,최근완결연도와세연도의과거고정계수적용을진단했다. [중앙11B](11B_CARRIED_WEIGHT_CORRECTION.md) · [출처](../20261008_carried_weight_correction/SOURCES.md) · [독립검증](../20261008_carried_weight_correction/outputs/verification.json) · [게시요약](../20261008_carried_weight_correction/PUBLICATION.md) · [용량](../20261008_carried_weight_correction/outputs/artifact_inventory.json). 조건부관찰평균이며다음경주예측검증·고정보정채택·운영변경은아니다. 기존독립연구수와원결과를보존했다. <!-- carried_weight_correction_v1 -->


## 모델 입력을 위한 게이트 보정 v1 후속

36번 연구 적용 후속 [원 보고서](../20261008_gate_model_candidate_v1/README.md) · [중앙 결론](04E_GATE_MODEL_CANDIDATE_V1.md) · [계획](../20261008_gate_model_candidate_v1/PLAN.md) · [출처](../20261008_gate_model_candidate_v1/SOURCES.md) · [적용 함수](../20261008_gate_model_candidate_v1/apply.py) · [게시 요약](../20261008_gate_model_candidate_v1/PUBLICATION.md) · [검증](../20261008_gate_model_candidate_v1/outputs/verification.json) · [용량](../20261008_gate_model_candidate_v1/outputs/artifact_inventory.json). 규칙으로 수축한 시험 후보이며 실증 연구 수는 늘리지 않는다. 운영 변경·다음 경주 검증 없음.


## 구간별 함수율·월·게이트 시험값 연구

37번째 연구 [원 보고서](../20261008_section_normalization_candidate_v1/README.md) · [중앙 결론](02A_SECTION_NORMALIZATION_CANDIDATE_V1.md) · [계획](../20261008_section_normalization_candidate_v1/PLAN.md) · [출처](../20261008_section_normalization_candidate_v1/SOURCES.md) · [함수](../20261008_section_normalization_candidate_v1/apply.py) · [게시 요약](../20261008_section_normalization_candidate_v1/PUBLICATION.md) · [검증](../20261008_section_normalization_candidate_v1/outputs/verification.json) · [용량](../20261008_section_normalization_candidate_v1/outputs/artifact_inventory.json). 직접3목표·중간 잔여값·겹치는 구간을 구분했다. 다음 경주 검증과운영 변경 없음.


## 마체중 변화와 적정체중 후속

기존11번의 [마체중 변화·자기 기준 편차·절대 최소체중](../20261008_body_weight_change_optimum/README.md)을 연결했다. 원문18파일·151,074행과 확인된0변화 복원,과거5개 체중 참조,개인 곡선의 시간분할/BH를 보존했다. [중앙11C](11C_BODY_WEIGHT_CHANGE_OPTIMUM.md) · [출처](../20261008_body_weight_change_optimum/SOURCES.md) · [독립검증](../20261008_body_weight_change_optimum/outputs/verification.json) · [게시요약](../20261008_body_weight_change_optimum/PUBLICATION.md) · [용량](../20261008_body_weight_change_optimum/outputs/artifact_inventory.json). 공동 고정효과와개인 상대기록 탐색을 구분하며,인과손실·개별체중처방·미래예측검증·운영반영은아니다. 이전결과와독립연구수를유지했다. <!-- body_weight_change_optimum_v1 -->

## 체중과 거리별 기록·막판 가설 후속

기존11번의 [체중과 거리별 기록·막판 통념 검토](../20261008_body_mass_distance_finish/README.md)를 연결했다. 절대체중과 현재를 제외한 과거5개 기준 편차, 단거리/1600~1800m 직접 차이, 마지막200m·600m·직전 구간 대비 둔화, 사후 극단 범주를 구분한다. [중앙11D](11D_BODY_MASS_DISTANCE_FINISH.md) · [출처](../20261008_body_mass_distance_finish/SOURCES.md) · [검증](../20261008_body_mass_distance_finish/outputs/verification.json) · [게시요약](../20261008_body_mass_distance_finish/PUBLICATION.md) · [용량](../20261008_body_mass_distance_finish/outputs/artifact_inventory.json). 체중 인과효과·피로 기전·1900m 이상 장거리·운영 보정을 확정하지 않는다. 이전 결과와 독립 연구 수를 유지한다. <!-- body_mass_distance_finish_v1 -->


## 결승 이탈 후미를 제외한 기록 기준

38번째 연구 [원 보고서](../20261008_detached_tail_sensitivity/README.md) · [중앙 결론](02B_DETACHED_TAIL_BASELINE.md) · [계획](../20261008_detached_tail_sensitivity/PLAN.md) · [출처](../20261008_detached_tail_sensitivity/SOURCES.md) · [게시 요약](../20261008_detached_tail_sensitivity/PUBLICATION.md) · [검증](../20261008_detached_tail_sensitivity/outputs/verification.json) · [용량](../20261008_detached_tail_sensitivity/outputs/artifact_inventory.json). 결승 이탈 표식의 회고적 민감도이며 원본 기록·운영 보정·다음 경주 검증은 변경하지 않았다.

## 말별 거리 적성

- 39. [말별 적정거리 후보와 이후 검증](../20261008_horse_distance_aptitude/README.md): [중앙27](27_HORSE_DISTANCE_APTITUDE.md) · [출처](../20261008_horse_distance_aptitude/SOURCES.md) · [개인 후보표](../20261008_horse_distance_aptitude/outputs/horse_candidates.csv) · [검증](../20261008_horse_distance_aptitude/outputs/verification.json) · [게시요약](../20261008_horse_distance_aptitude/PUBLICATION.md) · [용량](../20261008_horse_distance_aptitude/outputs/artifact_inventory.json). 2,634두 후보와작은/불확실한 이후 예측 개선을 구분하며 개인 최적거리·인과 개선·운영 채택은 미확정이다. <!-- horse_distance_aptitude_v1 -->


## 함수율 월 게이트 합산과 내외측 별도 특성

40번째 연구 [원 보고서](../20261008_environment_correction_atlas/README.md) · [중앙 결론](04F_ENVIRONMENT_CORRECTION_ATLAS.md) · [계획](../20261008_environment_correction_atlas/PLAN.md) · [출처](../20261008_environment_correction_atlas/SOURCES.md) · [조회 함수](../20261008_environment_correction_atlas/apply.py) · [게시 요약](../20261008_environment_correction_atlas/PUBLICATION.md) · [검증](../20261008_environment_correction_atlas/outputs/verification.json) · [용량](../20261008_environment_correction_atlas/outputs/artifact_inventory.json). 합산값·관측방향·내외측설명을구분하고기존채택/운영/예측검증을유지한다.

## 각질의 관측 근거와 반복 성향

- 41. [각질의 분류 근거와 말별 반복 성향](../20261008_running_style_foundation/README.md): [중앙28](28_RUNNING_STYLE_FOUNDATION.md) · [출처](../20261008_running_style_foundation/SOURCES.md) · [프로필](../20261008_running_style_foundation/outputs/horse_style_profiles.csv) · [검증](../20261008_running_style_foundation/outputs/verification.json) · [게시요약](../20261008_running_style_foundation/PUBLICATION.md) · [용량](../20261008_running_style_foundation/outputs/artifact_inventory.json). 반복 성향과최적 각질을 구분하며 각질 변경·선행 실패 성적 손실은 후속 연구다. <!-- running_style_foundation_v1 -->

## 통과조 각질 후속28A

- [통과조 기준 각질 성향](../20261008_passing_group_style/README.md): 연구28의후속으로독립연구수를유지한다. [중앙28A](28A_PASSING_GROUP_STYLE.md) · [출처](../20261008_passing_group_style/SOURCES.md) · [프로필](../20261008_passing_group_style/outputs/horse_profiles.csv) · [검증](../20261008_passing_group_style/outputs/verification.json) · [게시요약](../20261008_passing_group_style/PUBLICATION.md) · [용량](../20261008_passing_group_style/outputs/artifact_inventory.json). 같은마군을함께분류하며단독선두·경합·최적각질을구분한다. <!-- passing_group_style_v1 -->

## 말별 각질과 경기력 후속28B

[원 보고서](../20261008_horse_style_performance/README.md) · [중앙28B](28B_HORSE_STYLE_PERFORMANCE.md) · [입력3개 해시](../20261008_horse_style_performance/SOURCES.md) · [독립 검증](../20261008_horse_style_performance/outputs/verification.json) · [게시요약](../20261008_horse_style_performance/PUBLICATION.md) · [용량](../20261008_horse_style_performance/outputs/artifact_inventory.json). 평소 각질·좋은 경기·최근 변화와 개인 최적각질/전술 변경 원인을 구분한다. 기존 연구 수와 원본을 유지한다. <!-- horse_style_performance_v1 -->

## 편성 안의 각질 예측 후속28C

[원 보고서](../20261008_field_pace_prediction/README.md) · [중앙28C](28C_FIELD_PACE_PREDICTION.md) · [입력21개 해시](../20261008_field_pace_prediction/SOURCES.md) · [독립 검증](../20261008_field_pace_prediction/outputs/verification.json) · [게시요약](../20261008_field_pace_prediction/PUBLICATION.md) · [용량](../20261008_field_pace_prediction/outputs/artifact_inventory.json). 초반 위치 확보 확률과 후반 회복/후퇴, 기수·조교사 관측 성향을 직접 전술 의도와 구분한다. 기존 연구 수와 운영 유지. <!-- field_pace_prediction_v1 -->

## 전원·게이트 안팎 후속28D

[보고서](../20261008_bilateral_field_pace/README.md) · [중앙28D](28D_BILATERAL_FIELD_PACE.md) · [직접7입력과 원문 전이 출처](../20261008_bilateral_field_pace/SOURCES.md) · [독립 검증](../20261008_bilateral_field_pace/outputs/verification.json) · [게시요약](../20261008_bilateral_field_pace/PUBLICATION.md) · [용량](../20261008_bilateral_field_pace/outputs/artifact_inventory.json). 자기 제외 전원과 게이트 방향별 상대 구성을 비교하며 기수·조교사·교체 입력은 모두 제외한다. 실제 경합·작전 의도·주행경로의 공동확률과 구분한다. 기존 연구 수와 운영 유지. <!-- bilateral_field_pace_v1 -->

## 거리·함수율별 전개 후속28E

[보고서](../20261008_pace_condition_validation/README.md) · [중앙28E](28E_PACE_CONDITION_VALIDATION.md) · [출처/해시](../20261008_pace_condition_validation/SOURCES.md) · [검증](../20261008_pace_condition_validation/outputs/verification.json) · [게시요약](../20261008_pace_condition_validation/PUBLICATION.md) · [용량](../20261008_pace_condition_validation/outputs/artifact_inventory.json). 기존28C/28D 시간순 확률과 API4_3 원문 함수율을 평가 전원에 연결했다. 실제 함수율 층화와 사전 입력을 구분하며 거리·주로 모형의 개선/입상 연결은 미확정이다. <!-- pace_condition_validation_v1 -->

## 중반·종반 추입과 앞선 실패 후속28F

[보고서](../20261008_middle_late_style_validation/README.md) · [중앙28F](28F_MIDDLE_LATE_STYLE_VALIDATION.md) · [원문/파생 해시](../20261008_middle_late_style_validation/SOURCES.md) · [검증](../20261008_middle_late_style_validation/outputs/verification.json) · [게시요약](../20261008_middle_late_style_validation/PUBLICATION.md) · [용량](../20261008_middle_late_style_validation/outputs/artifact_inventory.json). 기존159,014실전 명단의 공식S1F/G3F/G1F/결승과T−2 실제5슬롯을 재검증했다. 현재 결과를 과거 프로필에 넣지 않았다. 후미 성향/실제 추입/입상, 앞선 미확보/확보 후 후퇴, 같은 말 관측 차이/인과 손실을 구분한다. <!-- middle_late_style_validation_v1 -->

## 선행 밀집과 뒤쪽형 회복·입상 후속28G

[보고서](../20261009_front_density_closer_benefit/README.md) · [중앙28G](28G_FRONT_DENSITY_CLOSER_BENEFIT.md) · [입력 해시](../20261009_front_density_closer_benefit/SOURCES.md) · [검증](../20261009_front_density_closer_benefit/outputs/verification.json) · [보조검증](../20261009_front_density_closer_benefit/outputs/adjusted_verification.json) · [게시요약](../20261009_front_density_closer_benefit/PUBLICATION.md) · [용량](../20261009_front_density_closer_benefit/outputs/artifact_inventory.json). 원문159,014행S1F시간을 대조하고 전체명단 후보수·자기제외·과거연도 페이스참조를 검증했다. 회복과입상,사전성향과관측속도,주설계와탐색조정을구분한다. <!-- front_density_closer_benefit_v1 -->

## 막판 우수·비입상 이후 입상 후속28H

[보고서](../20261009_fast_late_nonpodium_future/README.md) · [중앙28H](28H_FAST_LATE_NONPODIUM_FUTURE.md) · [출처/해시](../20261009_fast_late_nonpodium_future/SOURCES.md) · [검증](../20261009_fast_late_nonpodium_future/outputs/verification.json) · [민감도검증](../20261009_fast_late_nonpodium_future/outputs/sensitivity_verification.json) · [게시요약](../20261009_fast_late_nonpodium_future/PUBLICATION.md) · [용량](../20261009_fast_late_nonpodium_future/outputs/artifact_inventory.json). 원문159,014행의막판/누적시간·독립SQL실제미래슬롯·180일성숙·문턱·후속입상·군집구간을검증했다. 부산600/400/200·서울600/200,중첩합산/서울400생성없음. <!-- fast_late_nonpodium_future_v1 -->


<!-- axis_companion_pairs_v1_20261009 -->
[축 고정·조건부 동반 두 마리](29_AXIS_COMPANION_PAIRS.md): 기존 축+상대4두6개 24.96% → 상대6두 점수합6개 27.01%, 조건부 구간/전개6개 26.69%다. 새 동반학습은 같은 확대 후보군의 기존 점수합을 넘지 못했고 조건부 확률 오차는 악화됐다. 후보 범위 확대가 이번 개선의 주된 관측 요인이며 동반학습 추가 가치는 확인하지 못했다. [원본](../20261009_axis_companion_pairs_v1/README.md). 운영 미반영.


<!-- axis_pool_validation_v1_20261009 -->
[축 고정 후보 범위 추가 검증](30_AXIS_POOL_VALIDATION.md): 현재 선택22개에서 축+상대4두6개 23.80% → 상대6두에서 점수합 최고6개 25.09%(+1.29%p, 날짜95% +0.57~+2.07%p). 53개 연구후보는 24.96%→27.01%다. 선택 규칙의 후향 개선 신호이며 새 학습·운영 승격은 없다. [원본](../20261009_axis_pool_validation_v1/README.md).


<!-- axis_collapse_v1_20261009 -->
[축 붕괴 사전 예측](31_AXIS_COLLAPSE.md): 현재22개 기준4,799경주에서 위험 학습과 고정 해제·원축 제외·공동확률 재배분을 비교했다. context 재배분은 축자유6개 대비 -0.10%p(95% -0.45~+0.25%p). 새 미사용 기간 검증 전, 선택/운영 유지.


<!-- axis_mix_budget_v1_20261009 -->
[축 포함·제외 조합과 예산](32_AXIS_MIX_BUDGET.md): 현재22입력4,799경주에서 포함6+제외6은12개로 35.01%, 전체확률12개는 39.05%. 총6개 혼합과 구분하며 추가비용을 모델 개선으로 해석하지 않는다. 선택/운영 유지.


<!-- pair_trio_budget_v1_20261009 -->
[복승·복연·삼복의 조합 수](33_PAIR_TRIO_BUDGET.md): 원축 포함3+제외3의 총6개에서 복승 39.61%, 복연 67.06%, 삼복 21.38%. 총3개 예산을 구분하며 수익률 비교/운영 승격이 아니다.


<!-- qpl_multiple_dividends_v1_20261009 -->
[복연 다중 적중과 실제 당첨 배당](34_QPL_MULTIPLE_DIVIDENDS.md):2026서울/부산 정상당첨 평균 11.06배,1~99백분위 범위 10.07배. 실제1288경주 포함3+제외3 다중당첨 합산 표시총환급 79.79%. 적중률/일반배당평균/모델당첨평균을 구분하고 운영은 유지한다.


<!-- failure_clusters_v1_20261009 -->
[실패 경주와 후순위 입상마 조건 군집](35_FAILURE_CLUSTERS.md):삼복6조합 실패87.68%에 예측5위밖 입상마. 후순위 종반600·200m 상대우수+회복 조건은2025~26년1,610출전 실제21.68% 대 예상17.88%. 군집전체보다 조건교집합 신호이며 후향진단/운영유지.


<!-- late_recovery_ablation_v1_20261009 -->
[종반·회복·선행경쟁 작은 입력 실험](36_LATE_RECOVERY_ABLATION.md):30/32/43입력18모형.삼복6조합25.59%→25.55%→25.55%→25.76%,43개전체+8/후속−9경주.후순위포착과기존입상손실이함께발생해운영/22개유지.


<!-- third_place_hypothesis_v1_20261010 -->
[3착 예측난도와 유력마 탈락 가설](37_THIRD_PLACE_HYPOTHESIS.md):22입력4,799경주 상위5두 실제1/2/3착포착78.39/68.41/62.22%.운영공통1,258경주 정확1/2/3착한마리적중30.68/20.91/14.39%.3착어려움은지지되지만어부지리인과설명은미확인.운영유지.


<!-- axis_probability_conditions_v1_20261010 -->
[축확률별 이탈과 사전 조건](38_AXIS_PROBABILITY_CONDITIONS.md):22입력4,799경주,이탈건수최대50~60%741건/45.21%,이탈률최대40%미만62.67%.2024상위5조건2025~26재현미확인.초반/거리연장/고확률5등급추가감사후보,운영유지.


<!-- axis_signal_calibration_v1_20261010 -->
[축위험 세조건 보정 시험](39_AXIS_SIGNAL_CALIBRATION.md):4,799경주Brier원0.230332→0.229885,단순보정대비차이CI0포함.위험경고없는축입상64.35→64.40%.운영유지,10/11이후새검증계약/계수보존,미래성과0.
