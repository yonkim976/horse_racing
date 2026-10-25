# 게이트 전용 후속 연구의 출처

- [게이트 모집단](../20261002_gate_lateral_bias/outputs/runners.parquet):151,115행. 기존 정상 순위 완결·6두 이상 품질 계약과 과거 이력을 유지한다. 원시 DB를 새로 읽거나 다른 모집단을 합치지 않았다.
- [기존 게이트 연구](../20261002_gate_lateral_bias/README.md)와 [번호별 원 결과](../20261002_gate_lateral_bias/outputs/number_results.json):같은12두·거리·기간의1번 대비198개 계수를 재현했다. 이번 평균 게이트 대비 BH와 검정 가족은 다르다.
- [기간별 연구](../20261003_gate_lateral_time_windows/README.md)와 [고정 연도별 기준](../20261003_gate_lateral_time_windows/outputs/baseline_models.json):현재 실제 주행위치를 쓰지 않는게이트14모형만 사용했다. 마군 위치 모형56개는 사용하지 않았다.
- [세 위치 기간표](../20261003_three_lateral_positions/README.md)의 게이트 행만 날짜·주말·연월별로 추출했다. [원천 해시와 보존 대조](outputs/period_table_verification.json)에 기록했다. 재적합·q 재계산 없이 원래의 세 대비 검정 가족을 유지한다.
- [서울1600m 직접 비교](../20261007_seoul1600_gate_comparison/README.md) · [부산 거리별 비교](../20261007_busan_gate_comparison/README.md):이번 번호별 질문의 배경이며 미래 자료가 아니다.
- [계획](PLAN.md), [입력SHA-256](outputs/summary.json), [계산](analyze.py), [독립 대조](verify.py), [검증](outputs/verification.json)에 입력 경로·기간·선택 규칙·지원·누수 방지와 검증 범위를 보존했다.

실제 물리적 게이트 이동·레일 거리·추가 주행거리·현재 당일 관리 상태는 원천에서 확인한 변수가 아니다. 번호별 조건부 차이와 실제 위치의 인과효과를 구분한다. 최신 당일 자료를 수집한 연구가 아니며 기준 종료일을 유지한다. 외부 효과 크기를 새로운 보정 계수로 가져오지 않았다.
