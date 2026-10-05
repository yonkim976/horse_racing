# 제주마 자료 원천 목록

상위 프로젝트의 공유 자료를 제주 작업에서 찾기 쉽게 정리한 읽기 전용 카탈로그다. DB 파일은 `jeju/data/raw/` 아래에서 상대 심볼릭 링크로 참조하며 복제하지 않는다. 분석 코드는 입력 DB를 읽기 전용으로 연다. 내용 수정, 마이그레이션, 재수집, Supabase 접근은 이 카탈로그가 허용하지 않는다.

2026-10-03 사용자 승인 정리로 제주 백업 DB 7개와 아래 연도별 점수 DB 10개 및 해당 링크를 삭제했다. 현재 제주 최종 DB는 `jeju/data/jeju_native_core.sqlite3`이며 내용은 변경하지 않았다. 제주 텍스트 통합 DB는 기존 HY_R_FORM 피처 생성과 선택적 웹 과거 이력 보완에 사용되므로 사용자 결정에 따라 유지했다. 당시 공유 구간 DB 3개와 API/JSON/TXT 원문·검증 문서는 보존했다. 삭제 경로·해시는 [백업 삭제 기록](../maintenance/db_cleanup_20261003/backup_deletion_receipt.json)과 [원문 DB 삭제 기록](../maintenance/db_cleanup_20261003/source_db_deletion_receipt.json)을 따른다.

2026-10-04 사용자 승인으로 공유 구간 원본·검증·판정 DB 3개와 제주 참조 링크 3개를 삭제했다. 새 제주 연구는 [제주 전용 DB](../data/jeju_native_core.sqlite3)를 사용하며, 구간 사후 분석은 `jeju_race_postrace_sections_quality_2026` 뷰와 해당 검토 상태를 따른다. 기존 HY_R_FORM 모델·저장 피처·텍스트 통합 DB는 유지했다. 전체 삭제 경로·해시와 보존 파일 및 모델 검증은 [구간 DB 삭제 기록](../../reports/data_deletion_audit_20261004/section_db_deletion_receipt.json)에 있다.

## 핵심 제주 경주·말 이력

| 원천 | 범위·역할 | 주의 |
|---|---|---|
| [제주 텍스트 통합 분석 DB](../data/raw/jeju_native_text_phase2.sqlite3) | 명시적으로 확인한 제주마 경주·주행심사, 조교·출발조교·진료·체중, 제주 관련 Text 구조화 기록 | 약 15억 바이트 공유 스냅샷. ID가 모호한 후보는 격리되어 있고 자료 전체가 완전하다는 뜻은 아니다. |
| [제주 원시 건강·체중 응답](../data/raw/jeju_native_health_weight) | 공식 말 ID로 분리한 연도별 진료·체중 원문과 수집 manifest | 행 단위 시점·중복·coverage를 먼저 확인한다. 원문과 현재 프로필을 이름만으로 연결하지 않는다. |
| [제주 기본 Top3 데이터셋](../../data/research/jeju_native_top3_dataset_v1_20260915_r2) | 출전·레이블·과거 결과·말 상태·동착 정답·시간 분할 | 결과 표시는 사후 확인 출발집합과 공개 시점 가정을 포함한다. 미래 정보 입력은 금지한다. |
| [최종 HY_R_FORM 번들](../models/current/HY_R_FORM.pkl) | 등록부가 지목한 기준 점수 모델 | SHA-256 `f1b9531e068cab51dff906961d56f51c7c4b0e5a86f378c9aa1f03f159ec9706`. 모델·피처 생성·학습을 재현하는 일반 원천 DB와 구분한다. |

## 연도별 제주 점수 DB

2026-09-25 생성된 로컬 SQLite 자료다. 실제 제주마 범위, 공식 연결, 이벤트 날짜, 결과 상태, 구간 컬럼을 확인한 후에만 사용한다.

아래 목록은 과거 보유 자료의 경로 기록이다. DB 10개와 링크 10개는 2026-10-03 삭제되어 현재 입력으로 사용할 수 없다.

| 연도 | 자료 |
|---:|---|
| 2017 | `../data/raw/jeju_2017_score.sqlite3` |
| 2018 | `../data/raw/jeju_2018_score.sqlite3` |
| 2019 | `../data/raw/jeju_2019_score.sqlite3` |
| 2020 | `../data/raw/jeju_2020_score.sqlite3` |
| 2021 | `../data/raw/jeju_2021_score.sqlite3` |
| 2022 | `../data/raw/jeju_2022_score.sqlite3` |
| 2023 | `../data/raw/jeju_2023_score.sqlite3` |
| 2024 | `../data/raw/jeju_2024_score.sqlite3` |
| 2025 | `../data/raw/jeju_2025_score.sqlite3` |
| 2026 | `../data/raw/jeju_2026_score.sqlite3` |

## 구간 원천과 판정 이력

`section_point_db_20260925`에 있던 아래 DB 3개는 2026-10-04 삭제했다. 종별 DB가 과거 원천의 모든 행·판정 이력을 완전히 복제했다는 의미가 아니라, 기존 공유 구간 재구축·판정 경로를 종료한 사용자 결정이다. 삭제된 DB를 입력으로 삼는 과거 스크립트는 그대로 재실행할 수 없다.

| 단계 | 삭제된 파일 | 과거 용도 |
|---|---|---|
| 원본 | `section_points.sqlite3` | 초기 적재 스냅샷 |
| 검증 | `section_points_verified.sqlite3` | 원천 확인을 거친 중간 검증 단계 |
| 판정 반영 | `section_points_adjudicated.sqlite3` | 당시 판정·조정 단계 |

과거 공유 구간 DB 적재·인수인계·검증·판정 보고 4개와 연도별 성적표·주행심사 DB 안내 1개는 2026-10-04 사용자 승인으로 삭제했다. 파일별 경로·해시는 [문서 삭제 기록](../../reports/document_cleanup_20261004/deletion_receipt.json)에 있으며, [운영 마이그레이션 기록](../../docs/PASSING_SECTION_OPERATIONAL_MIGRATION_2026-09-28.md)은 유지했다. 현재 제주 구간 조회 기준은 `jeju_native_core.sqlite3`의 `jeju_race_postrace_sections_quality_2026`이며, 기존 모델의 S1F/G1F 입력과 같은 정의라고 가정하지 않는다.

## 진료 용어·사건 연구 자료

[의료·부상 사건 영향 연구](../data/raw/medical_injury_race_impact_20260925)는 용어 분리·판정 자료와 분석 초안을 포함한다. 의미 카탈로그는 진단이나 부상 심각도를 자동 확정하지 않는다. 현재 기준 모델의 진료 입력은 제한된 집계 변수뿐이다. 이를 모델 채택 피처로 간주하지 말고, 원문·사건 일자·게시 시점·말 ID 연결을 검토한다.

## 해시 고정 재현 입력

[2026-09-18 보존 카드](../data/fixtures/jeju_live_20260918_hy_r_form_verified_20260917)는 기준 모델을 다시 계산하는 기능 점검용이다. 전체 카드 7경주·67두이고, 고정 피처의 SHA-256은 `4bd409321d3d25fbbba0d6845fa4d61219b2dfd8cc02a1af9c79ada6797e2a56`이다. 저장 결과를 다시 만들 수 있는지 확인하며 실전 누수 검증이나 새 성능 평가로 쓰지 않는다.

분석 자료 상한은 현재 2026-09-12다. `2026-09-12` 이후의 응답을 상한 이전 원천의 누락 보완 근거로 역사용하지 않는다.
