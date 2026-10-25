# 원천과 재사용 범위

2026-10-08. 외부 홈페이지 새 조회 없이 동결 DB와 완료 연구 산출물을 사용했다.

- DB: `thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb`의`confirmed_runners`. 읽기 전용 연결에서 경주키/마번/말ID/날짜/지역/부담중량만 추출했다. 이번 중량이 사전 출마표의 동일 값이었는지와 실제 공개시각은 검증하지 않았다.
- [기본19 모델](../20261008_horse_profile_model_v1/README.md)의 입력178,497행과6개기본19head·예측·조합·지표를 그대로 재사용했다. 학습/보정/평가 함수와 설정도 재사용하고 신규 후보만 학습했다.
- [월·게이트 비교](../20261008_profile_environment_ablation_v1/README.md)의 월게이트19 입력과6개head·예측·조합·지표를 재사용했다. 과거 시점 보정계수는 이 연구에서 다시 선택하지 않았다.
- [전체시간 함수율 연구](../20261003_pace_gate_moisture_v2/README.md)의`adjusted_records.parquet`에 있는 실전 이력326,327행의 키·날짜로 이전 출전을 제한했다. 기존 보정초와 지수는 변경하지 않았다.
- [후순위 연구](../20261004_outsider_joint_v1/README.md)의 동결 입력에서`previous_carried_weight`만 읽어 새로 계산한 직전 중량을 전체행 대조했다. 기존`carried_weight_change`나 그 외258개 입력을 추가하지 않았다.

실제로 읽은 파일·코드·기존 모델·운영 registry는[SHA256 명세](outputs/input_manifest.json)에 고정했다. 원천DB와 완료된 기존 연구 산출물·운영 registry·웹 평가표를 변경하지 않았다. 신규 연구 산출물과 연구 목록 소개만 추가한다.
