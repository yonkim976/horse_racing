# 입력 고정 보고

입력 준비는 supervisor/DESIGN_CONTRACT.md에 따라 완료했다. 원천 복사·DB 접근·모델 학습·예측·성능 평가는 없었다. 자체 합성검사와 라벨 재구성이 통과했고, 독립 검증 영수증 supervisor/INPUT_VERIFICATION.json도 PASS다. 독립 검증은 전체 52,155개 대상 키·phase label과 208,620개 lineage cutoff를 확인하고, 연도 층화 1,280개 runner의 30,720개 특징 셀을 원천에서 다시 계산했다. 최대 절대 오차는 5.33e-15다.

10/08 snapshot은 92,513행·9,494경주다. frozen inclusion ledger의 2017년 이후 후보 5,901경주·59,042행 가운데 strict 정상완전 코호트는 5,206경주·52,155두이며, ledger상 695경주가 제외된다. 제외 사유는 중복 집계다: 비정상/비양수 시간 510, 거리 제외 135, 불완전 순위 569. partial_vs_stored_result는 원래 저장 결과 비교를 포함한 frozen ledger 값을 참조했으며, 이번에는 DB를 열어 다시 확인하지 않았다. 2017년 이전 3,593경주는 9,494−5,901 산술 차이로 추론한 값이다.

10/21의 56,618행·5,693경주 observation roster는 10/08 frozen started roster와 ID·말·마번·날짜·거리·착순 키가 일치했다. 전체 roster에서 early 56,392행, recovery 56,381행, early-pack Z 5,671경주가 알려져 있고, 세 라벨 모두 label-only reference와 재구성 값·결측 상태가 일치했다. 10/21의 strict 밖 4,463행은 과거 이력 원천으로만 사용한다. 새 phase 목표는 strict 5,206경주 안에서 early 52,095/52,155 runner, recovery 52,116/52,155 runner, Z 5,200/5,206 race가 알려져 있다. 각각 60, 39, 6개는 unknown으로 유지했다.

모든 phase head의 2019–2026 학습 및 직전연도 보정 지원이 계약 최소치(학습 양·음 각 50, 보정 양·음 각 10)를 통과했다. 전체 fold별 수는 phase_fold_support.json에 있다. 입력은 A 27개, runner phase 35개, race Z 8개 특징의 고정 순서와 label-only 열로 구성했다. 역사 상태는 같은 말·2017-01-01 이후·730일 이내·T−2 inclusive 이벤트만 사용한다. 원천 공개 timestamp는 확인할 수 없어 이는 event-date 경계이며 실제 발행 시점 가용성은 보증하지 않는다. 대상 편성은 사후 확정 roster에 조건부다.

평가 키는 1,779경주·17,412두·269일(2024/2025/2026 = 637/654/488)로 고정됐다. PLC는 미확인 개장 편성수 36경주를 제외한 1,743경주다. canonical runner/race key hash는 inputs/input_manifest.json에 기록했다.

새 입력·감사 산출물 합계는 약 10.8 MB다. 핵심 파일은 model_inputs.parquet 9,853,758 B, race_inputs.parquet 223,513 B, history_lineage.parquet 612,842 B, race_census.parquet 34,119 B다. 각 SHA-256, source hashes, 열 순서, label 지원, 시간 경계는 inputs/input_manifest.json에 잠겼다. 생성은 43.1초였다.
