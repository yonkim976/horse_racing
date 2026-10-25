# 출처와 분석 범위

2026-10-08. 입력은 [기존 성별 연구 모집단](../20261007_sex_ability_gap/outputs/population.parquet) 151,074행이다. 원천18파일·정상 완주·품질 선택·마필ID·공식 부담중량의 정의는 [원연구 출처](../20261007_sex_ability_gap/SOURCES.md)를 계승한다. 이번 분석은 성별 열을 모형에 쓰지 않는다. 입력 SHA-256·기간·행/말/경주 수는 [source_and_method.json](outputs/source_and_method.json)에 있다. 새 API·공식 규정 조회는 필요하지 않았다.

기존 [비율 연구](../20261005_relative_load1200/README.md)의 예측오차 감소를 kg 손실로 바꾸지 않고, [체중 상호작용 연구](../20261008_body_load_time_loss/README.md)의 480kg 점추정을 평균효과로 재사용하지 않았다. 새 단일 선형 중량 모형을 적합했다. 부담중량은 공식 기록값이며 기수 체중을 중복 합산하지 않는다.

모형·변수·SVD 허용오차·군집 분산·기간 보류 진단은 [보고서](README.md)와 [계획/실행 보충](PLAN.md)에 있다. 모든 성별을 합치며 성별별 기준·체중 상호작용을 사용하지 않는다. 주 모형에는 체중항이 없고 체중 직접항은 민감도만이다. 성별에 영향받는 중량 배정 자체를 제거한 무작위 시험은 아니다. 미관측 컨디션과 배정의 내생성이 남는다.

검증은 본 분석의 반복 잔차화를 가져오지 않고 희소 설계행렬에서 연결요소당 말 한 열을 제거해 LU 투영과 QR을 계산했다. 동일 마필·날짜의 거리 간 상관을 유지한 공통 SE와 과거 고정계수의 보류 잔차 오차를 검증했다. 실행 중에 전체 공통값을 추가한 점과 CI 양수 조건의 엄격한 해석은 계획 보충에 명시했다. 별도 미래 예측 검증은 아니다.

code-security의 고정 경로·읽기 전용 입력 원칙과 pages:write-page의 수치/주장 검토 기준을 적용했다. 기존 관련104파일의 목록·해시는 [baseline_inventory.json](outputs/baseline_inventory.json), 공유 파일 수정 직전과 자체 변경량은 shared_edits_baseline.json/shared_own_edits.json, 자기포함 용량은 [artifact_inventory.json](outputs/artifact_inventory.json)에 있다. 원본·입력·다른 채팅 작업을 보존한다.
