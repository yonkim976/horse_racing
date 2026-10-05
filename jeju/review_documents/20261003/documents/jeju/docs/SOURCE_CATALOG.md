# 제주마 자료 원천 목록

상위 프로젝트의 공유 자료를 제주 작업에서 찾기 쉽게 정리한 읽기 전용 카탈로그다. DB 파일은 `jeju/data/raw/` 아래에서 상대 심볼릭 링크로 참조하며 복제하지 않는다. 분석 코드는 입력 DB를 읽기 전용으로 연다. 내용 수정, 마이그레이션, 재수집, Supabase 접근은 이 카탈로그가 허용하지 않는다.

## 핵심 제주 경주·말 이력

| 원천 | 범위·역할 | 주의 |
|---|---|---|
| [제주 텍스트 통합 분석 DB](</Users/kimyongjin/Desktop/horse_racing/data/research/jeju_native_text_phase2_db_20260915/jeju_native_text_phase2.sqlite3>) | 명시적으로 확인한 제주마 경주·주행심사, 조교·출발조교·진료·체중, 제주 관련 Text 구조화 기록 | 약 15억 바이트 공유 스냅샷. ID가 모호한 후보는 격리되어 있고 자료 전체가 완전하다는 뜻은 아니다. |
| [제주 원시 건강·체중 응답](</Users/kimyongjin/Desktop/horse_racing/data/raw/jeju_native_health_weight>) | 공식 말 ID로 분리한 연도별 진료·체중 원문과 수집 manifest | 행 단위 시점·중복·coverage를 먼저 확인한다. 원문과 현재 프로필을 이름만으로 연결하지 않는다. |
| [제주 기본 Top3 데이터셋](</Users/kimyongjin/Desktop/horse_racing/data/research/jeju_native_top3_dataset_v1_20260915_r2>) | 출전·레이블·과거 결과·말 상태·동착 정답·시간 분할 | 결과 표시는 사후 확인 출발집합과 공개 시점 가정을 포함한다. 미래 정보 입력은 금지한다. |
| [최종 HY_R_FORM 번들](</Users/kimyongjin/Desktop/horse_racing/jeju/models/current/HY_R_FORM.pkl>) | 등록부가 지목한 기준 점수 모델 | SHA-256 `f1b9531e068cab51dff906961d56f51c7c4b0e5a86f378c9aa1f03f159ec9706`. 모델·피처 생성·학습을 재현하는 일반 원천 DB와 구분한다. |

## 연도별 제주 점수 DB

2026-09-25 생성된 로컬 SQLite 자료다. 실제 제주마 범위, 공식 연결, 이벤트 날짜, 결과 상태, 구간 컬럼을 확인한 후에만 사용한다.

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

`section_point_db_20260925`에는 서로 다른 검토 단계의 DB가 있다. `section_points_adjudicated.sqlite3`는 현재 판정·조정 이력이 반영된 최신 단계이며, verified 또는 원본 DB를 최신 권위 자료라고 부르지 않는다.

| 단계 | 읽기 전용 참조 | 용도 |
|---|---|---|
| 원본 | [section_points.sqlite3](</Users/kimyongjin/Desktop/horse_racing/data/research/section_point_db_20260925/section_points.sqlite3>) | 초기 적재 스냅샷 |
| 검증 | [section_points_verified.sqlite3](</Users/kimyongjin/Desktop/horse_racing/data/research/section_point_db_20260925/section_points_verified.sqlite3>) | 원천 확인을 거친 중간 검증 단계 |
| 판정 반영 | [section_points_adjudicated.sqlite3](</Users/kimyongjin/Desktop/horse_racing/data/research/section_point_db_20260925/section_points_adjudicated.sqlite3>) | 최신 판정·조정 단계. 각 행의 판정과 제외 근거를 확인한다. |

단계별 내용과 출처 판정은 [구간 원천 판정 보고](</Users/kimyongjin/Desktop/horse_racing/docs/SECTION_POINT_DB_SOURCE_ADJUDICATION_2026-09-25.md>)와 [운영 마이그레이션 기록](</Users/kimyongjin/Desktop/horse_racing/docs/PASSING_SECTION_OPERATIONAL_MIGRATION_2026-09-28.md>)를 읽는다. 모델의 기존 S1F/G1F 값이 이 DB와 동일한 정의라고 가정하지 않는다.

## 진료 용어·사건 연구 자료

[의료·부상 사건 영향 연구](</Users/kimyongjin/Desktop/horse_racing/research/medical_injury_race_impact_20260925>)는 용어 분리·판정 자료와 분석 초안을 포함한다. 의미 카탈로그는 진단이나 부상 심각도를 자동 확정하지 않는다. 현재 기준 모델의 진료 입력은 제한된 집계 변수뿐이다. 이를 모델 채택 피처로 간주하지 말고, 원문·사건 일자·게시 시점·말 ID 연결을 검토한다.

## 해시 고정 재현 입력

[2026-09-18 보존 카드](</Users/kimyongjin/Desktop/horse_racing/data/predictions/jeju_live_20260918_hy_r_form_verified_20260917>)는 기준 모델을 다시 계산하는 기능 점검용이다. 전체 카드 7경주·67두이고, 고정 피처의 SHA-256은 `4bd409321d3d25fbbba0d6845fa4d61219b2dfd8cc02a1af9c79ada6797e2a56`이다. 저장 결과를 다시 만들 수 있는지 확인하며 실전 누수 검증이나 새 성능 평가로 쓰지 않는다.

분석 자료 상한은 현재 2026-09-12다. `2026-09-12` 이후의 응답을 상한 이전 원천의 누락 보완 근거로 역사용하지 않는다.
