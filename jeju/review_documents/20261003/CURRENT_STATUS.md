# 제주마 DB 최신 적재·검증 상태 — 2026-10-03

기존 실제 적용·독립 검증 원장을 취합한 상태표다. 이번 문서 취합에서는 API 재수집이나 DB 수정을 수행하지 않았다. 원장 DB는 [jeju_native_core.sqlite3](</Users/kimyongjin/Desktop/horse_racing/jeju/data/jeju_native_core.sqlite3>)이며 제주 전용 로컬 SQLite다. 공유 운영 DB나 모델 피처 저장소와 구분한다.

## 현재 적재 범위

| 자료 | 확인한 적재·조회 상태 | 기준 보고서 |
|---|---|---|
| 제주마 경주 후보 | 2002-07-28~2026-09-19, 9,494경주·92,513출전행. 유효 착순·양수 완주시간 경주 9,347개, 취소·불성립 147개 별도 | [수집·연결 계획 및 후속 기록](<documents/jeju/docs/JEJU_NATIVE_DB_COLLECTION_PLAN_2026-09-29.md>) / [구간기록 전체 후속 점검](<documents/jeju/research/20261002_section_remaining_review/README.md>) |
| 최신 말 프로필 | 진료 후속 81두 반영 후 4,718두. 공식 말 ID로 과거 기록 연결 | [진료 적재·검증](<documents/jeju/research/20261002_medical_db_load/README.md>) |
| API20 주행심사 분석 | 기존 명시 제주 심사 15,738행 분석 정책 적용. 최초 TXT 후보 15,688행과 다른 모집단이며 단순 합산하지 않음 | [말 이름·성별·2026년 나이 계약](<documents/jeju/research/20261001_horse_analysis_2026/README.md>) |
| 일별조교 API18 | 908,316행·4,545두. 분석 상한 9월 19일까지 907,389행 | [일별조교 적재·검증](<documents/jeju/research/20261001_daily_training_api_load/README.md>) |
| 홈페이지 출발조교 | 전체 제주 관측 295,470행, 검증 명단 연결 190,842행·4,476두. 분석 190,790행 | [출발조교 홈페이지 적재·검증](<documents/jeju/research/20261001_starting_training_website_load/README.md>) |
| 출발심사 API21 | 10,664행·4,636두. 분석 상한까지 10,620행. 기승자 키 미제공 5,795행 | [출발심사 적재·검증](<documents/jeju/research/20261002_starting_exam_db_load/README.md>) |
| 진료 API16 | 12,030행·944두. 분석 상한까지 11,991행·939두. API33 기반 공유 사전은 별도 해석 자료 | [진료 적재·검증](<documents/jeju/research/20261002_medical_db_load/README.md>) |
| 구간 정정·보류 조회 | `jeju_race_postrace_sections_quality_2026`, 92,513행·고유 출전키 92,513개 | [19경주 재검토·DB 보류 반영](<documents/jeju/research/20261003_unresolved_section_review/README.md>) |

조교·심사·진료 수량은 각 적용 때 검증한 연결 모집단이다. 현재 프로필이 늘었다는 이유만으로 이전 모집단 밖 원문이 자동으로 새 적재된 것은 아니다. 원장 전체에는 제주 경마장 다른 품종의 API 관측도 있으므로 모든 원행을 확정 제주마 사건으로 계산하지 않는다. 현재 프로필의 제주마 표기는 과거 사건일 품종까지 증명하지 않는다.

## 최신 구간기록 처리

미해결 19경주·184출전행을 최신 API4와 홈페이지로 다시 확인했다. 개별 통과착순 70개·통과조 20지점의 충돌은 그대로이며, 실제 대체 순위는 확보하지 못했다.

- `section_internal_conflict_reviews`에 순위 70행·통과조 20행, 총 90검토행을 실제 적재했다.
- 품질 조회에서 충돌 순위 70필드·통과조 20지점을 NULL·`unresolved_official_internal_conflict`로 제공한다. 통과조는 출전행별 194개 말·지점 관측에 해당한다.
- 원 API값·최종 착순·완주시간은 유지했다. 홈페이지 순위 정정 14개, 시간 정정 3개와 광해청명 G1F 시간 NULL도 유지했다.
- 검토행이 없거나 원천 SHA가 달라지면 NULL 보류한다. 이전 조회나 `_raw` 값을 사용해 보류를 우회하지 않는다.
- 실제 DB 전체 92,513행 대조와 메모리 DB 차단 규칙 검증을 완료했다. [실제 적용 기록](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261003_unresolved_section_review/application_receipt.json>), [독립 검증 기록](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261003_unresolved_section_review/root_independent_verification.json>)을 따른다.

이 단계는 **보류 처리 완료·실제 정답 미확정**이다. 경주 전체를 삭제하거나 추정 순위를 넣지 않았다. 홈페이지와 API가 일치하는 나머지 양수 원값도 모든 값의 정확성 확정은 아니다.

## 분석 계약

- 현재 이름은 API42 최신 프로필명, 과거 연결키는 공식 말 ID다. 과거 이름·성별·나이는 원문으로 보존한다.
- 기본 분석 나이는 **2026 − 출생연도**이며 2026년으로 고정한다. 사건 당시 나이나 만 나이로 설명하지 않는다. 토종등극 성별은 사용자 결정에 따라 현행 원문과 충돌 메모를 유지한다.
- 원천 우선순위는 API 수집 후 검증·부족 자료의 홈페이지/TXT 보완이다. 출발조교는 사용자 지시로 홈페이지 정규 자료를 사용하며, 구간 정정은 경주·말·필드별 근거를 기록한다.
- 같은 내용·말·날짜의 복수행은 실제 중복 사건으로 확정하지 않는다. 재적재 중복은 원문 artifact와 item 위치로 막는다.
- 분석 사건 상한은 2026-09-19다. 이후 수집 원문은 별도 보존한다. 기존 모델 재현 자료 상한 2026-09-12와 혼동하지 않는다.
- 적재 자료를 기존 모델에 자동 채택하거나 재학습하지 않았다. 사건 날짜는 과거 공개시각 증명이 아니며 사후 구간기록을 같은 경주의 사전 입력으로 연결하지 않는다.

남은 실제 진실·측정 정의·입력 허용 판단은 [재점검 목록](RECHECK_CHECKLIST.md)을 따른다.
