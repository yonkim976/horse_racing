# 기록 보정량 연구의 출처

- [기존 성별 연구 모집단](../20261007_sex_ability_gap/outputs/population.parquet):151,074출전, 마필ID·등급·체중·성별 편성·과거 이력·전체시간.
- [게이트 모집단](../20261002_gate_lateral_bias/outputs/runners.parquet):151,115출전, 마번·취소 후 두수·게이트 그룹. 동일 출전151,074개와 완주시간을 대조했다.
- [기존 함수율 참고표](../20261002_moisture_strength_selection/outputs/reference_seconds.csv)와 [채택 결정](../conclusions/01_TRACK_MOISTURE.md):서울80%·부산90%, 건조 기준. 기존 채택거리·상태 지원을 유지한다.
- [통합 설계](../conclusions/04A_TRACK_TOTAL_CORRECTION.md) · [월별 연구](../conclusions/23_MONTHLY_SAME_MOISTURE.md) · [게이트 전용 후속](../conclusions/03C_GATE_ONLY_FOLLOWUP.md):배경이며 입상률%p를 시간으로 환산하지 않았다.
- [계획](PLAN.md), [계산](analyze.py), [독립 대조](verify.py), [입력SHA256](outputs/summary.json), [검증](outputs/verification.json).

새 DB 조회·외부 웹 수집은 없었다. 원천 종료일과 기존 품질 계약을 유지했다. 실제 경로 길이·풍향·풍속·주로빠르기는 보정 입력이 아니다. 알려진 과거자료를 설명하는 연구용 참고량이다.
