# 확인된 일별조교 31행의 기승자 이름 보완

완료일: 2026-10-15 (한국시간). 연구 DB: `thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb`.

## 적용 결과

- 원문 기승자 번호 **080626 유지**.
- 2026-09-04·05·06·09·10의 **확인된 31개 observation_id에만 다비드 이름 연결**.
- 공식 기수 번호는 배정하지 않음: `rider_official_id_candidate`, `rider_official_id_linked` 모두 NULL. 080584로 병합하지 않음.
- 조교보 계열 등 나머지 69개 미연결 번호·190,344행은 미확정 유지.
- 송당스카이의 기존 충돌 보류 1행 유지. 이름 연결값과 공식 ID 연결값은 NULL.

## 저장 방식

`daily_training_rider_event_name_links`에 31행을 추가했다. 각 행은 공식 화면의 원문 파일·SHA256, 해당 화면의 행 번호, 확인된 마번·날짜·입퇴장 시각, 사건별 이름 확인 근거를 보존한다.

기존 `daily_training_rider_linked` 조회에서 해당 31행만 다음 값으로 표시한다.

| 필드 | 값 |
|---|---|
| rider_id_raw | 080626 |
| rider_name_candidate / rider_name_linked | 다비드 |
| rider_identity_status | exact_event_web_name_link |
| event_verification_status | exact_event_web_name_verified_profile_id_unmatched |
| event_verification_web_rider_display_raw | 다비드 |
| rider_official_id_candidate / rider_official_id_linked | NULL |

공식 프로필과 번호를 연결하는 전역 `rider_name_links`는 수정하지 않았다. `rider_unmatched_ids` 역시 원래 70개 번호를 보존한다. 그 안의 080626은 **프로필 ID 미연결 이력**이며, 이번에 이름이 보완된 31행의 상태는 위 조회에서 별도로 구분한다.

원문 조교 기록과 다른 경주·심사·엔티티·장구·진료·통과조 등 기존 테이블은 수정하지 않았다. 운영 DB 조회·변경도 없다.

## 검증

- 공식 화면 5일분에서 마번·날짜·입퇴장 시각으로 유일 대응한 31행 전부 다비드 표시 확인.
- 적용 전 읽기 전용 검증 통과, 적용 트랜잭션 검사 통과.
- 별도 root 검증 **305개 통과**.
- 기존 물리 테이블 130개의 행 수·행 해시 집계가 백업과 일치. 원천 목록 테이블은 기존 28행을 보존하며 1행만 추가.
- 다른 81개 조회 정의 보존. 이름 조회의 기존 열을 기준으로 승인된 31행 외 **5,173,002행**의 행 해시 집계가 백업과 일치.
- 승인된 31행도 원문 번호·말·시간과 공식 ID/프로필 출처 필드 보존 확인.
- 원천 목록의 기존 파일 항목 보존, 신규 입력 파일 **12개 SHA256** 확인.
- DB/manifest 해시 일치. 등록 객체 214개, 전체 일별조교 조회 5,173,033행 유지.

행 보존 회귀 검사는 행 수와 DuckDB 64비트 행 해시의 합·XOR 비교이며 암호학적 동일성 증명은 아니다. 백업 및 입력 파일은 별도로 SHA256을 확인했다.

## 산출물

- [적용 보고서](reports/apply_report.json)
- [별도 검증 보고서](root_verification.json)
- [원천 목록 검증 및 31행 조회 결과](root_manifest_and_31_rows.json)
- [원래 공식 화면 조사](../20261015_training_rider_roles_followup_v1/README.md)
- 변경 전 백업: `thoroughbred/data/core_api_2010_20260929_v1/backups/20261015_before_event_name_31/`

적용 후 DB SHA256: `44924894b418979f45091e948a73dc50a55f7dc6897af35e42d65e6a3d776816`.
