# 더러브렛 작업 폴더 통합·미사용 자료 정리 완료

2026-09-28. 사용자 요청에 따라 세 서브에이전트가 삭제 후보, 폴더/추론 구현, 독립 검토를 나누어 수행했다. 주 에이전트가 검토 결과를 확인하고 허용 목록만 삭제했다.

## 실제 삭제

11개 파일, **2,183,019,154 bytes (2.033 GiB)**를 삭제했다. 휴지통 이동이나 대용량 복제 백업은 만들지 않았다. 상세 SHA-256은 `deletion_plan.json`과 `deletion_receipt.json`, 실행 기록은 `deletion_events.jsonl`에 있다. `deletion_plan_initial_not_executed.json`은 처음 검토한 후보 목록이며 실행 목록이 아니다.

| 삭제 경로 | bytes |
|---|---:|
| `data/research/section_point_db_20260925/section_points_ext.sqlite3` | 1,091,465,216 |
| `data/research/section_point_db_20260925/section_points_repaired.sqlite3` | 1,091,465,216 |
| `data/research/thoroughbred_boundary_20260918_v6/.DS_Store` | 6,148 |
| `data/research/thoroughbred_followup_20260918_v4/.DS_Store` | 8,196 |
| `data/research/thoroughbred_model_20260918_v1/.DS_Store` | 6,148 |
| `data/research/thoroughbred_offline_20260918_v5/.DS_Store` | 6,148 |
| `data/research/thoroughbred_three_targets_20260918_v3/.DS_Store` | 10,244 |
| `data/research/thoroughbred_three_targets_20260918_v3/code/__pycache__/targets_core.cpython-312.pyc` | 33,394 |
| `data/research/thoroughbred_unified_20260918/.DS_Store` | 6,148 |
| `data/research/thoroughbred_weight_20260919_v8/.DS_Store` | 6,148 |
| `data/research/thoroughbred_win_research_20260918_v2/.DS_Store` | 6,148 |

두 구간 DB는 과거 확장본·수정본이다. 기존 인수인계 문서에서 사용 금지로 지정되어 있었고, 최신 판정 DB와 비교한 경마장·날짜·경주·거리·고유 말 ID·마번·지점·시간값·원천·원천 필드의 고유 튜플 누락이 0이었다. 완주기록 575,708행, 거리별 주로표 19행, S1F 차이표 18행도 누락이 0이었다. 내부 행 ID와 잘못된 과거 파생 분류의 동일성을 요구한 비교는 아니다. 강한 식별 키의 `section_comparison.json`을 근거로 사용했고, `section_comparison_weaker_not_for_delete.json`은 삭제 근거가 아니다.

## 보존·보류

- `section_points.sqlite3`: 강한 원천 키 기준 756,700개 튜플의 대응이 확인되지 않았다. 모두 마번이 비어 있으므로 연결 방식 차이일 수 있으나 완전 대체를 입증하지 못해 보존했다. 그 개수를 원자료 손실 건수라고 단정하지 않는다. 새 분석용 DB로 사용하지 않는다.
- `section_points_verified.sqlite3`: 판정 전 근거이자 판정 스크립트의 직접 입력이므로 보존했다.
- `section_points_adjudicated.sqlite3`: 현재 판정 DB로 보존했다.
- 통합 더러브렛 DuckDB·학습 피처·원천 이력·재현 입력·연구 보고서·현재 모델 의존성은 보존했다.
- 5개 연구의 동일 평가 파일은 수 MB 절약을 위해 공유 쓰기 위험을 만들지 않도록 유지했다.
- 운영 DB·제주 모델·운영 등록부를 변경하지 않았다. 공통 구간 자료에서는 위 두 개의 폐기된 중간 파일만 제거했다.

과거 문서의 ‘당시 보존했다’는 문구는 당시 상태를 설명한다. 이번 삭제 후 ext/repaired를 읽는 과거 중간 단계 재실행은 해당 파일 재생성 없이는 불가능하다. 현재 `build-verified`는 운영 DB와 통합 더러브렛 DB에서 재구축하며, adjudication은 보존한 verified와 원문 근거를 사용하므로 두 삭제 파일을 입력으로 요구하지 않는다. 삭제 후 같은 비교 스크립트를 처음부터 다시 돌리려면 삭제된 중간 DB를 재생성해야 하며, 이번 전체 비교 결과는 JSON으로 보존했다.

## 통합 작업 폴더

작업 진입점은 `thoroughbred/README.md`, 실행기는 `thoroughbred/cli.py`다. 새 연구는 `thoroughbred/research/`, 새 데이터 스냅샷은 `thoroughbred/data/`, 예측 출력은 `thoroughbred/predictions/`에서 진행한다. 모델·문서·과거 연구·공통 데이터 30개 연결을 제공한다. 과거 코드의 위치 의존성을 깨지 않도록 기존 파일을 물리적으로 옮기지 않았고, 새 폴더는 독립 배포 패키지가 아니다.

CLI는 준비된 완전한 피처 카드의 읽기 전용 추론과 보존 카드 재현을 지원한다. 새 출마표 피처를 자동 생성하는 실전 파이프라인, 축마 조건부 추천, 다섯 승식 전체 출력은 이번 작업의 구현 범위가 아니다. 기존 A/B/C 모델의 의미를 유지한다.

## 검증

- 삭제 대상 외 스냅샷 1107개 파일의 SHA-256 일치.
- 더러브렛·제주 운영 모델 resolver 모두 통과, 운영 등록부 변경 없음.
- 삭제 후 보존 27경주·294두의 말별 A확률, B/C 상위 조합 540행, 원점수가 보존 결과와 정확히 일치.
- CLI 테스트 6개와 Ruff 검사 통과. 부분 출전표·누락 피처·미지원 경마장·덮어쓰기·검증 후 등록부 변경을 검사했다.
- 예측 결과는 기존 파일을 덮어쓰지 않고 새 디렉터리에 저장했다. DB 행 쓰기와 학습은 수행하지 않았다.

삭제 후 재현: `thoroughbred/predictions/20260928_after_cleanup/`. 새 폴더의 사용법은 `thoroughbred/README.md`를 따른다.
