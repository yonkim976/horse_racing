# 후속 연구 산출물과 검증

현재 연구 선택은 A=v3 `top3_allcore`, B/C=v4 `top3_growth_strength`입니다. 운영 모델과 DB를 변경하지 않았습니다.

- `REPORT.md`: 선택 근거, 이미 확인한 과거 자료의 성능, 정리 내용.
- `UPCOMING_PREDICTIONS.md`: 선택된 모델로 계산한 9월 19·20일 예상표. 9월 17일 저장 출마표 기준.
- `upcoming_context/PRIOR_EVENTS.md`: 직전 3회 실제 출전의 원문 사건 참고. 확률 조정에 사용하지 않았습니다.
- `model/USAGE.md`: 학습 재현과 새 출력 폴더로의 고정 출마표 추론 재현 명령.
- `cleanup/README.md`: 제거한 중간 CSV의 검증·복원 방법.

저장된 이번 연구 전체를 읽기 전용으로 검증합니다.

```bash
.venv/bin/python data/research/thoroughbred_followup_20260918_v4/integrity.py verify
```

기존 v1/v2/v3 자료는 원래 manifest를 그대로 보존했습니다. v2의 중간 CSV 하나는 압축 보관 대응 목록으로 확인합니다. 아래 검증은 결과 JSON을 새 연구 폴더의 동일 경로에 갱신할 수 있습니다.

```bash
.venv/bin/python data/research/thoroughbred_followup_20260918_v4/review_blend/verify_prior_manifests.py
```

원래 v2 검증기를 그대로 사용하려면 `cleanup/restore_features_v2_rows.py --restore`로 CSV를 먼저 복원해야 합니다. 기존 파일이 있으면 복원 도구는 덮어쓰지 않습니다.

`model/invalid_attempt_01`, `model/invalid_future_export_attempt_*`, `upcoming_context_superseded_entries`는 무효·대체된 시도의 감사 자료입니다. 현재 예상에는 사용하지 않습니다. 보존된 실행 기록과 원천 해시로 원인을 추적할 수 있도록 남겼습니다.

새 비교 연구는 새 폴더에서 실행합니다. 원본 코드의 덮어쓰기 방지 조건을 제거하거나, 이미 본 2025~2026년 성능으로 현재 선택 기준을 바꾸지 않습니다. 출전표·체중·날씨를 새로 수집하는 도구는 이번 고정 출마표 재현 명령에 포함되지 않습니다.
