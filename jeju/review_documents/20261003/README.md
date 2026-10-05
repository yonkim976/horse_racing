# 제주마 DB 수집·검증 통합 문서함 — 2026-10-03

이번 대화에서 축적한 활성 제주 수집·적재·검증 문서와 작업 계획, 삭제·제외 근거, 공통 API 관리 문서 **78개**를 한 폴더에 모았다. 최신 미해결 구간 처리도 포함한다. 현재 상태는 아래 최신 상태표와 실제 적용 원장을 기준으로 판단한다.

## 읽는 순서

1. [최신 적재 상태와 구간 처리](CURRENT_STATUS.md)
2. [다시 점검할 항목과 완료 기준](RECHECK_CHECKLIST.md)
3. [전체 문서 목록·원본 위치](DOCUMENT_REGISTER.md)
4. [19경주 재검토·DB 보류 반영](<documents/jeju/research/20261003_unresolved_section_review/README.md>)

## 주제별 시작 문서

| 주제 | 시작 문서 |
|---|---|
| API 우선 수집과 경주 후보·취소 분류 | [수집·연결 계획 및 후속 기록](<documents/jeju/docs/JEJU_NATIVE_DB_COLLECTION_PLAN_2026-09-29.md>) |
| 말 ID·현재 이름·2026년 고정 나이 | [말 이름·성별·2026년 나이 계약](<documents/jeju/research/20261001_horse_analysis_2026/README.md>) |
| 일별조교 | [일별조교 적재·검증](<documents/jeju/research/20261001_daily_training_api_load/README.md>) |
| 출발조교·중복 보존 | [출발조교 홈페이지 적재·검증](<documents/jeju/research/20261001_starting_training_website_load/README.md>) |
| 출발심사·기승자 미제공 | [출발심사 적재·검증](<documents/jeju/research/20261002_starting_exam_db_load/README.md>) |
| 진료·질병 사전·과거 공백 | [진료 적재·검증](<documents/jeju/research/20261002_medical_db_load/README.md>) |
| 구간시간·통과착순·통과조 | [구간기록 전체 후속 점검](<documents/jeju/research/20261002_section_remaining_review/README.md>) |
| 미해결 19경주의 NULL 보류 | [19경주 재검토·DB 보류 반영](<documents/jeju/research/20261003_unresolved_section_review/README.md>) |
| 공통 API 관리 | [공통 API 사용 인벤토리](<documents/docs/KRA_API_USAGE_INVENTORY_2026-09-30.md>) / [승인 API 목록](<documents/docs/KRA_APPROVED_42_API_CATALOG_2026-09-30.md>) |

## 보관 범위와 해석

- `documents/`에는 `jeju/docs/`, `jeju/research/`, `jeju/maintenance/`의 모든 Markdown, 제주 README·AGENTS 및 공통 API 관리 문서 두 개를 원본 경로 구조에 맞춰 모았다. 예전 모델 보관소 전체를 추가로 복제한 것은 아니다.
- 원본 문서는 원래 위치에 유지한다. 문서 사이 링크는 가능한 한 이 폴더의 사본으로 연결했다. 원문 JSON·HTML·TXT·CSV, 코드·DB·백업은 기존 위치에 연결한다. **이 폴더는 문서 점검용 사본이며 단독 실행 패키지나 전체 근거 백업이 아니다.**
- 과거 보고서의 숫자와 ‘미완료’는 작성 당시의 상태다. 4,617→4,637→4,718두 같은 단계별 집계를 서로 덮어쓰지 않는다. 현재 상태표와 후속 적용·독립 검증 기록을 함께 읽는다.
- API 원문 보존, 제주마 후보 연결, 공식 정정·품질 보류, 모델 입력 채택은 서로 다른 완료 단계다. 적재 완료를 모든 필드의 진실 확정이나 새 모델 적용으로 해석하지 않는다.
- [manifest.json](manifest.json)은 원본·사본 SHA-256과 링크 변환 목록이다. 사본은 링크만 변환했으므로 두 해시가 다를 수 있다. [보관 검증](verification.json)에는 문서 누락·내용·원본 변경 여부 점검 결과를 기록한다.
- [기존 원문 링크 점검](SOURCE_LINK_CHECK.md)은 원본에 이미 있던 누락 링크를 별도로 기록한다. 미존재 파일을 새 근거로 만들어 채우지 않는다.

새 결과가 생기면 원본 보고서를 작성하고 새로운 날짜·버전의 문서함을 만든 뒤 상위 README의 최신 포인터를 갱신한다. 이번 날짜 사본의 역사적 내용을 최신 상태로 덮어쓰지 않는다.
