# Thoroughbred 백업 DB 정리와 향후 재검증

2026-10-03 사용자 지시에 따라 연구 코어의 과거 백업 DB 5개를 삭제했다. 과거 검증을 다시 실행하기 위해 대용량 단계별 DB를 계속 보관하지 않고, 필요할 때 별도 경로에서 재구축·재검증하기로 했다. 현재 코어 DB, 예측모델·등록부·추론 코드·모델 입력·보존 카드·실험 산출물, API/JSON/TXT/RPT 원문과 검증 문서는 삭제하지 않았다.

## 실제 삭제와 보존

삭제한 파일은 `thoroughbred/data/core_api_2010_20260929_v1/backups/`의 아래 폴더에 있던 `thoroughbred_core.duckdb`다. 각 폴더의 `manifest.json`과 기존 `backup_pair_attestation.json`은 원래 경로와 내용으로 보존했다. 이제 이 폴더들에는 복구 가능한 DB 파일이 없다.

| 폴더 | DB 용량 | 과거 역할 |
|---|---:|---|
| `20261002_current_verified_061544` | 1.64GiB | 출발심사 적재 후 검증본. 진료 적재 전본과 DB·manifest 동일 |
| `20261002_before_starting_exam` | 1.64GiB | 출발심사 적재 전 복구 지점 |
| `20261002_before_medical` | 1.64GiB | 진료 적재 전후 보존 비교의 기준 |
| `20261002_before_passing_groups` | 2.23GiB | 통과조 적재 전후 보존 비교의 기준 |
| `20261002_before_steward_reports` | 2.23GiB | 심판리포트 적재 전본, 종합 DB 검증·통과조 재점검의 기준 |

정확한 경로·파일 크기·삭제 전 해시·현재 DB의 삭제 전후 해시·관측 여유 공간 변화는 [삭제 기록](deletion_receipt.json)에 있다. APFS clone은 데이터 블록을 공유하므로 삭제 파일의 논리 용량 합계 9.39GiB가 실제 회수 공간과 같지 않다.

현재 최종 DB는 `thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb`다. SHA-256 `c46286df4773a7ffcea4c7bc431e2cd2a8fc03a4c38fdaa4403bd8f39c2a1668`, 127테이블·81뷰의 내용과 manifest는 삭제 전후 동일했다. 등록된 예측모델 관련 파일 10개의 해시 확인도 통과했다([모델 상태 확인](model_status_after.json)).

## 삭제로 바로 재실행할 수 없게 된 검증

다음 코드는 삭제된 백업 DB 경로 또는 당시 해시를 기준으로 고정한다. 코드와 완료 보고서는 과거 검증 근거로 보존했지만, 현재 경로에서 그대로 실행하면 백업 부재로 실패한다.

- 진료·통과조·심판리포트 각각의 `research/20261002_*_v1/root_preservation_verify.py`: 해당 단계의 적재 전후 내용·스키마 보존 비교.
- `research/20261002_core_validation_before_reports_v1/`: `race_core/validate_core.py`, `training_equipment/validate_prior_research.py`, `medical_passing/verify_medical_passing_snapshot.py`, `root_manifest_verify.py`, `consolidate_verification.py`. 심판리포트 직전의 180객체를 고정 기준으로 사용하는 종합 검증.
- `research/20261002_passing_groups_v1/local_audit/recheck_unmapped.py`: 같은 심판리포트 직전 DB·확인서 해시를 사용하는 통과조 재점검.

당시 완료 결과·원천 명세·검증 코드·검증 보고서 해시는 남아 있다. 이번 삭제는 검증을 새로 수행하거나 당시 결과를 취소한 것이 아니다. 현재 208객체 DB의 전체 검증을 과거 180객체 검증 완료로 대체하지 않는다.

## 나중에 다시 적재·검증하는 순서

1. 현재 최종 DB를 변경하지 않고 새로운 작업 폴더와 DB 출력 경로를 준비한다. 기존 `build_core_db.py`와 분야별 로더는 출력 경로·기준 DB 해시·기대 행 수가 고정된 부분이 있으므로, 현재 코어에 그대로 실행하지 않는다. 새 실행용 사본에서 입력·출력 경로와 검증 계약을 먼저 고정한다.
2. 먼저 보존한 API 응답·JSON/TXT/RPT 원문, 파생 입력과 manifest를 사용한다. 필요한 자료가 없는 경우 해당 분야의 수집 코드를 검토한 뒤 API 또는 공식 홈페이지·Text 자료를 새 경로에 다시 수집하고 수집 시각·해시·커버리지를 기록한다.
3. 출발심사, 진료, 통과조, 심판리포트의 적재 명세와 보존 검증 원장을 따라 필요한 단계까지 별도 DB를 재구축한다. 과거 값의 수동 정정·보류·ID 연결·제외 근거도 함께 반영한다. 최종 DB를 과거 백업 경로에 복사해 당시 기준본으로 취급하지 않는다.
4. 새 DB와 입력의 해시·행 수·뷰 정의·기간·장소·말 식별자·제외/미연결/반복/결측을 확인하고, 분야별 검증 및 적재 전후 보존 비교를 새로운 결과 폴더에서 실행한다. 현재 DB를 대상으로 검증한다면 검증 범위를 208객체 상태에 맞게 별도로 정의한다.
5. 새 검증을 마치면 결과·사용한 원천·DB 해시·과거 검증과의 차이를 새 문서에 남긴다. 일시적인 단계별 DB는 검증 종료 후 필요한 보관 범위를 결정한다. 운영 DB나 예측모델 반영은 별도 작업이다.

API 재조회로 새 연구 DB를 만들 수는 있지만, 예전 API 응답이나 DB 바이트·해시를 동일하게 복원할 수 있다는 보장은 없다. 진료 적재에는 최신 API가 제공하지 않았던 과거 API 수집본과 Text 기록도 포함된다. 통과조에는 공식 성적표 보완과 API/성적표 차이·지점 대응 판정이 있다. 따라서 API만 다시 받는 것은 보존 원문과 검토 근거를 이용한 재구축과 같지 않다. 기존 검증의 해시 고정 조건을 임의로 해제하지 않고, 변경된 원천은 새 수집·검증 결과로 관리한다.

## 근거 문서

- [삭제 전 후보 점검](../backup_review_20261003/backup_review.json)
- [출발심사 적재](../../research/20261002_starting_exam_v1/README.md)
- [진료 적재·검증](../../research/20261002_medical_v1/README.md)
- [통과조 적재·검증](../../research/20261002_passing_groups_v1/README.md)
- [심판리포트 적재·검증](../../research/20261002_steward_reports_v1/README.md)
- [심판리포트 직전본의 종합 검증](../../research/20261002_core_validation_before_reports_v1/README.md)
