# 제주마 예측·연구 작업 폴더

2026-09-28부터 제주마의 새 분석과 연구를 여기서 시작한다. 프로젝트의 공통 DB·수집 코드·파이썬 환경은 상위 `horse_racing` 저장소에 있다. 이 폴더만 복사해서는 독립 실행 패키지가 되지 않는다.

2026-10-04 사용자 승인으로 공통 `scripts/`의 이전 DB 구축·검증과 사용성이 낮은 수동 연구 도구를 정리했다. 전체 삭제는 스크립트 92개와 종료된 공유 구간 경로 전용 테스트 2개다. 날짜가 고정된 제주 자료표·폐기된 중간 원천의 검증·이전 심판/정체성 실험 도구 등이 포함된다. 현재 `HY_R_FORM` 추론·피처 재현 코드, 제주 전용 DB 구축·검토 적용 코드, 원문·연구 결과와 운영 DB는 유지했다. 과거 문서는 당시의 근거로 보존하며 삭제된 도구의 실행 안내로 사용하지 않는다. 상세: [스크립트 정리 기록](</Users/kimyongjin/Desktop/horse_racing/reports/script_cleanup_20261004/deletion_receipt.json>).

## 먼저 읽을 문서

새 분석의 핵심 결과와 최신 버전은 [제주마 연구 결과 모음](</Users/kimyongjin/Desktop/horse_racing/jeju/research/conclusions/README.md>)에서 확인한다. 앞으로 완료한 연구는 [연구 결과 관리 기준](</Users/kimyongjin/Desktop/horse_racing/jeju/research/RESEARCH_PUBLICATION_POLICY.md>)에 따라 날짜별 원본과 주제별 결론을 함께 관리한다.

현재 수집·적재·보류 상태와 과거 검증 문서는 [통합 점검 문서함](</Users/kimyongjin/Desktop/horse_racing/jeju/review_documents/README.md>)에서 확인한다. 과거 보고서의 미완료 표시는 작성 당시의 상태이며 최신 상태표와 적용 원장을 우선한다.

1. [작업 규칙](<AGENTS.md>)
2. [데이터 분석부터 다시 시작하는 계획](</Users/kimyongjin/Desktop/horse_racing/jeju/docs/RESTART_PLAN_20260928.md>)
3. [우승축·착순·동반 후보 예측 목표](</Users/kimyongjin/Desktop/horse_racing/jeju/docs/JEJU_PREDICTION_OBJECTIVES_2026-09-28.md>)
4. [기준 모델 입력 감사와 분석 계획](</Users/kimyongjin/Desktop/horse_racing/jeju/docs/JEJU_FINAL_MODEL_INPUT_AUDIT_AND_REBUILD_PLAN_2026-09-28.md>)
5. [사람의 분석 방식과 모델 반영 방향](</Users/kimyongjin/Desktop/horse_racing/jeju/docs/JEJU_HUMAN_ANALYSIS_FRAMEWORK_2026-09-28.md>)
6. [공유 자료 원천 목록](</Users/kimyongjin/Desktop/horse_racing/jeju/docs/SOURCE_CATALOG.md>)
7. [정리와 인계 기록](</Users/kimyongjin/Desktop/horse_racing/jeju/docs/CLEANUP_AND_HANDOFF_20260928.md>)
8. [조교 API 자료와 모델 입력 기준](<docs/JEJU_TRAINING_API_INPUT_CONTRACT_2026-10-01.md>)

기준 모델은 등록부가 명시적으로 선택한 `HY_R_FORM`이다. 실험 후보 `HY_R_TRANSITION` 등은 승격된 모델이 아니다. 기준 모델 가중치 파일의 정본은 [models/current/HY_R_FORM.pkl](</Users/kimyongjin/Desktop/horse_racing/jeju/models/current/HY_R_FORM.pkl>)이다. 등록부에 남은 기존 모델 경로는 이 정본을 가리키는 호환 링크로 유지한다. 운영 모델 등록부는 변경하지 않는다.

## 폴더 구성

| 경로 | 목적 |
|---|---|
| `cli.py` | 등록 모델 상태 확인, 보존 예측 카드 재현 |
| `config/production_registry.json` | 상위 프로젝트 운영 등록부에 대한 읽기 전용 링크 |
| `models/current/` | 기준 모델 정본 가중치와 메타데이터 |
| `data/raw/` | 상위 프로젝트의 공유 원천에 대한 읽기 전용 참조 링크 |
| `data/snapshots/`, `data/features/` | 이후 감사된 데이터 스냅샷·분석 피처 카드 |
| `data/fixtures/` | 해시가 고정된 재현 입력 카드 링크 |
| `predictions/` | 매 실행별 새 재현 결과 |
| `research/` | 앞으로 시작할 새 분석 질문·코드·결과 |
| `research/conclusions/` | 주제별 연구 결론, 최신 버전 목록과 원 보고서 연결 |
| `docs/` | 제주 목표, 데이터 계획, 입력 감사와 원천 안내 |
| `review_documents/` | 수집·적재·검증 문서 사본, 최신 상태표와 재점검 목록 |
| `maintenance/cleanup_20260928/` | 이번 별도 정리 작업의 삭제·보존 근거 |

DB를 새 경로로 복사하지 않는다. `data/raw/`의 심볼릭 링크와 자료 목록은 탐색을 돕는 읽기 전용 참조이며, 원천을 바꾸거나 재수집하는 실행 경로가 아니다. 이번 승인된 정리에서 더는 필요하지 않은 연구 산출물은 별도 보존 기록에 따라 제거한다. 실제 프로젝트 환경과 등록부를 사용하므로 가상환경은 상위의 `.venv`이다.

## 사용

저장소 루트에서 실행한다.

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python jeju/cli.py status
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python jeju/cli.py replay --output jeju/predictions/replay_20260928_01
```

`status`는 공통 등록부와 공식 모델 resolver를 읽고 해시·승격 상태를 확인한다. `replay`는 해시가 고정된 2026-09-18 제주 카드의 저장 피처로 기존 `HY_R_FORM` 점수와 A/B/C 확률을 다시 계산하고, 함께 보존된 점수·예측과 비교한다. 출력 경로가 이미 있으면 실패한다. 이 재현은 기능 확인이며 새 성능 평가나 실전 예측이 아니다. CLI는 네트워크나 DB를 호출하지 않는다. 새 목표의 범용 예측·조합 출력 파이프라인은 아직 구현되지 않았다.

아직 새 경주의 출마표에서 피처를 만드는 완전한 오프라인 파이프라인은 이 작업 폴더에 없다. 새 예측은 검증된 완전 피처 카드 입력과 공개 시점 근거가 마련된 뒤 추가한다.

## 새 연구 규칙

### 조교 자료 사용 기준

일별조교의 기승자 이름은 [사번·실명 연결과 미연결 검토](<research/20261015_training_rider_identity/README.md>) 및 `daily_training_riders_analysis_2026`에서 조회한다. 사번 기준 참조명과 홈페이지 동일 조교행에서 직접 확인한 이름을 구분하고, 미연결은 NULL로 유지한다.

일별조교는 [API18 적재·전수 검증](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261001_daily_training_api_load/README.md>), 출발조교는 [홈페이지 기준 적재·전수 검증](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261001_starting_training_website_load/README.md>)을 완료했다. 분석 조회는 각각 `daily_training_api_rows_analysis_2026`, `starting_training_website_rows_analysis_2026`이다. 새 모델 입력에는 자동 반영하지 않았다. 사용 전 [조교 API 입력 기준](<docs/JEJU_TRAINING_API_INPUT_CONTRACT_2026-10-01.md>)을 따른다. 횟수 항목의 전 기간 0값과 초기 시간값 공백을 실제 미조교로 입력하지 않고, 말 ID·날짜만으로 출발조교를 중복 제거하지 않는다. 원문과 감사 산출물은 보존한다.

### 이름·나이의 기본 조회 기준 (2026-10-01 사용자 지정)

로컬 `data/jeju_native_core.sqlite3`의 `horse_analysis_2026`(말), `jeju_race_analysis_2026`(경주 후보·통과착순), `jeju_trial_analysis_2026`(API에 제주로 명시된 심사)을 사용한다. `horse_name`은 최신 프로필명이고 `age`와 `age_2026`는 **2026 − 출생연도**다. 공식 `horse_id`로 과거 경주·심사를 연결한다.

`historical_horse_name_raw`, `age_at_race_raw`/`age_at_trial_raw`, 이벤트 `sex`, `sex_current_profile`로 원래 관측과 현재 프로필을 함께 조회할 수 있다. 토종등극 성별 원천은 사용자 승인에 따라 유지한다. 상세·검증·예제는 [2026년 분석 조회 기준](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261001_horse_analysis_2026/README.md>)을 본다.

구간기록의 새 사후 분석은 `jeju_race_postrace_sections_quality_2026`를 사용한다. 홈페이지 기준 시간·순위 정정과 미해결 19경주의 순위 70개·통과조 20지점 NULL 보류를 포함한다. [현재 보류 반영·검증](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261003_unresolved_section_review/README.md>)의 출처·품질 상태를 함께 확인한다. 이 조회를 같은 경주의 사전 예측 입력으로 사용하지 않는다.

- 새 연구는 `research/YYYYMMDD_주제/`에 질문·가설·분석 시점·표본·코드·결과를 함께 둔다.
- 보유 자료만으로 시작한다. 기존 모델 재현 자료 상한은 2026-09-12이고, 사용자 승인으로 확장한 제주 전용 DB 경주결과 상한은 2026-09-19다. 수집 시점과 분석 조회 상한을 구분한다. 시장 배당·인기 입력과 영상 수집은 현재 범위 밖이다. 새 목표의 말별·공동 착순 확률은 평가와 조합 사건 계산에 사용한다.
- 새 데이터셋은 `data/snapshots/` 또는 `data/features/` 아래 새 버전으로 만든다. 원천 경로, SHA-256, 범위, 단위, 연결키, 공개 시점, 결측·제외 규칙을 기록한다.
- 관측 사실, 추정, 가설, 확인할 수 없는 내용을 표와 보고서에서 분리한다.
- 새 연구는 우승축·말별 우승/Top2/Top3·정확한 2/3착·조건부 동반 후보·승식 조합 확률을 목표 문서에 따라 정의하고 평가한다. 기존 A/B/C는 HY_R_FORM 비교 지표로 보존한다.
- 과거 2024~2026 기간을 반복해서 사용한 결과는 후향 개발 분석으로 표시한다. 날짜나 분할을 바꿔도 새 독립 검증이 되지 않는다.
- 새 피처나 모델은 감사·시간 검증을 거쳐 연구 후보로 보고한다. 운영 모델 승격은 명시적 등록 절차를 따른다.


<!-- axis_companion_pairs_v1_20261009 -->
[축 고정·동반 두 마리 연구](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261009_axis_companion_pairs_v1/README.md>): R1의 기존 축+상대4두6개 17.88% → 상대6두 점수합6개 19.39% → 조건부 구간/전개6개 21.59%다. 조건부 학습+구간/전개 입력 묶음의 개선 신호가 있다. 같은467경주의 새 방식 22.70%는 운영 HY_R_FORM 30.84%보다 낮아 운영 교체 근거는 아니다. 운영 미반영.
