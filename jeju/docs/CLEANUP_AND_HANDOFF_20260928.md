# 제주 작업 공간 정리 및 인계 기록 — 2026-09-28

이 문서는 제주마 분석을 `jeju/`에서 시작하기 위한 결과 요약이다. 삭제·보존 파일별 근거와 무결성 증명은 별도 영수증을 기준으로 한다.

## 결과

- 새 제주 작업의 기본 위치는 `jeju/`이다. 지침, 데이터 우선 재시작 계획, 입력 감사, 사람 분석 문서, 공유 원천 카탈로그와 `status`/고정 카드 `replay` CLI가 준비됐다.
- 기준 모델은 승격 등록부의 `HY_R_FORM`이다. 정본은 일반 파일 [models/current/HY_R_FORM.pkl](../models/current/HY_R_FORM.pkl)이며 SHA-256은 `f1b9531e068cab51dff906961d56f51c7c4b0e5a86f378c9aa1f03f159ec9706`이다. 기존 등록 경로는 정본을 가리키는 상대 호환 심볼릭 링크로 남겼고 등록부 바이트는 그대로다.
- 상위 저장소의 모델 resolver, `.venv`, `src/horse_racing`, 공통 제주 데이터와 원천을 유지했다. 대용량 DB는 복사하지 않고 `jeju/data/raw/`에 읽기 전용 참조 링크를 두었다. 구간 점수의 판정 단계와 제주마 진료·체중·Text 자료의 출처 설명은 [공유 원천 목록](SOURCE_CATALOG.md)을 본다.
- 보존된 2026-09-18 입력 카드로 독립 재현을 확인했다. 7경주·67두의 저장 점수와 말·경주 예측이 모두 일치했고, 최대 부동소수 차이는 0.0이었다. 이는 과거 카드 재현 확인이며 새 성능 평가나 실전 예측은 아니다.
- root 검토에서 관련 테스트 16개가 통과했고, 제주 resolver가 기준 모델·해시를 확인했다. 운영 등록부 해시는 `944e4aad25c99d3d346dab23c7f7596c216d8722a548dea2c7c07abf9b10b70b`로 보존됐다.

## 정리 총계와 증빙

최종 승인 정리에서는 고유 파일 632개, 114,267,306바이트(약 114.3 MB)를 삭제했고, 이 중 87개는 구형 모델 가중치였다.

- [삭제 허용 목록과 사전 보호 기준](../maintenance/cleanup_20260928/cleanup_plan.json)
- [실행·사후 보호 검사 영수증](../maintenance/cleanup_20260928/execution_receipt.json)
- [2단계 실행 영수증](../maintenance/cleanup_20260928/phase2_execution_receipt.json)
- [기준 모델 물리 이동과 호환 링크 영수증](../maintenance/cleanup_20260928/model_move_receipt.json)
- [구형 자료 검토의 첫 삭제 영수증](../maintenance/legacy_review_20260928/deletion_receipt.json)
- [구형 자료 검토의 최종 삭제 영수증](../maintenance/legacy_review_20260928/deletion_receipt_v2.json)
- [최종 정리 후 모델 재현 확인](../predictions/final_cleanup_review_20260928/replay_verification.json)

공유 실행 이력 `data/experiments/model_runs.jsonl`은 변경하지 않았다. 제주 과거 실행 산출물 참조 13개는 승인된 정리로 삭제된 파일을 계속 가리키므로 대상이 없다고 표시될 수 있으며, 이는 예상된 처분 결과다. 원장 자체는 보존됐다.

## 실행 한계와 다음 작업

CLI는 등록 모델 `status` 확인과 SHA가 고정된 2026-09-18 제주 피처 카드 `replay`만 지원한다. 일반 피처 카드 생성, 새 날짜의 범용 `predict`, 네트워크 자료 수집, DB 기록은 아직 구현 범위가 아니다. 새 연구는 현재 계획에 따라 보유 자료와 2026-09-12 상한에서 데이터 정의·품질·가용 시점부터 검토한다.

이 구현과 문서 정리는 gpt-6-luna, xhigh로 수행했고 root가 작업 공간·resolver·재현 결과를 검토했다. 기준 모델 승격이나 운영 등록부 변경은 하지 않았다.
