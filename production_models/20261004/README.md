# 운영 모델 보관본 — 2026-10-04

공통 운영 등록부가 선택한 서울·부산 모델과 제주 HY_R_FORM의 가중치, 메타데이터, 기준 추론 코드, 선택·검증 기록을 실제 파일로 복사했다. 외부 심볼릭 링크는 없다.

- `thoroughbred/models/A/`: 현행 A 모델과 입력·보정 메타데이터
- `thoroughbred/models/BC/`: 현행 B/C 점수 모델과 메타데이터
- `thoroughbred/models/order/`: 현행 순서 모델과 메타데이터
- `jeju/models/`: HY_R_FORM 가중치와 정본 메타데이터
- 각 도메인의 `reference/`, `verification/`: 등록된 추론 코드와 검증 근거
- `config/source_registry.json`: 변경하지 않은 원래 운영 등록부 사본
- `config/prediction_model_registry.json`: 보관본 내부 경로로만 수정한 검증용 등록부
- `manifest.json`: 원본 위치, 크기, SHA-256 및 복사 검증 결과

기존 운영 등록부와 모델 경로는 유지했다. 이 보관본은 모델 자산을 분리한 저장 폴더다. 기준 추론 코드와 메타데이터에는 기존 프로젝트의 모듈·데이터·경로 의존성이 남아 있다. DB, 원본 수집 자료, 학습 데이터, 피처 생성 파이프라인, 실행 환경은 포함하지 않아 이 폴더만으로 새 경주의 독립 예측을 실행할 수는 없다.

이 폴더에서 모델 파일과 선택 조건을 검증할 수 있다:

```bash
python3 tools/resolve_main_model.py --repo-root . --domain thoroughbred
python3 tools/resolve_main_model.py --repo-root . --domain jeju
```

가중치·모델 메타데이터는 이 폴더의 `.gitignore`로 Git에서 제외했다. 보관본의 해시·출처·검증 기록으로 원본과의 동일성을 확인한다.
