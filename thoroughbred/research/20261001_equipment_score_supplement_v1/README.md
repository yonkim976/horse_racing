# 성적표 장구 보완 적재기

API78에서 출전행이 제공되지 않은 **8마리·104출전행**의 장구 원문을 공식 성적표 출처로 연구 DB에 보완했습니다. 모든 값은 `retrospective_score_observation_not_verified_pre_race`로 표시하며, API78 상태도 `row_not_provided_in_requeried_api`로 유지합니다.

## 실제 반영 및 검증 결과

- 2026-10-01 연구 코어 `thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb`에 적재 완료. [적재 기록](load_manifest.json).
- 성적표 관측 104행, 장구 토큰 170개: 변경 표시 없음 163개·신규 3개·해제 4개. 사용 선언 뷰 166개.
- 주 에이전트 독립 검증 13개 통과. 기존 77개 테이블·뷰의 전체 행과 스키마가 백업과 같고, 기존 출처 원장 20행은 보존하면서 새 출처 1행만 추가했습니다. [검증 결과](root_verification.json).
- 재실행은 기존 적재값을 읽기 전용으로 확인했으며 중복 적재나 DB 해시 변경이 없었습니다. [재실행 검증](replay_verification.json).
- 적재 전 DB와 매니페스트는 코어 폴더의 `backups/20261001_before_equipment_score_supplement/`에 보존했습니다.
- 앞서 후보 파일에 남긴 `candidate_only_not_loaded=True`는 후보 작성 당시 상태입니다. 해시 고정한 후보 원문을 수정하지 않았고, 실제 적재 상태는 이번 적재 기록에서 관리합니다.
- 이번 범위는 누락 104행의 성적표 보완입니다. API78 장구 전체 본 적재 완료를 뜻하지 않습니다.

## 장구 공백의 해석

앞서 비교한 수치는 **1,384행**입니다. API78 출전표가 공백이고 API156 결과가 단독 `-`인 행은 **장구란에 장구명 기재 없음**으로 해석합니다. 마사회 FAQ는 가슴걸이를 자유사용장구로 설명하며 장구사용현황에 표시하지 않는다고 안내하므로, 모든 실제 장구를 사용하지 않았다고 확정할 수 없습니다. 단독 `-`를 해제 이벤트로 만들지 않습니다. [해석과 공식 근거](empty_equipment_interpretation.md).

## 스키마와 적재기

적재기는 후보·토큰 CSV와 공식 성적표 HTML 103개를 해시로 고정합니다. 공식 경주 헤더, 말 ID, 정규화 마명, 착순, 장구 원문을 다시 파싱하고 `confirmed_runners`의 5개 키와 정상 착순을 확인합니다. 이전 검토에서 확인한 성적표 파서와 마명 정규화 함수를 재사용합니다.

적재 스키마는 [schema.sql](schema.sql)에 있습니다.

- `equipment_score_supplement`: 104행의 출전 사건 키, 말 신원, 착순, 장구 원문, 출처 URL, 조회 시각·기준, 원문 경로·SHA-256, 두 상태를 보존합니다.
- `equipment_score_supplement_tokens`: 170개 장구 항목의 순서와 부호를 보존합니다. 원문 토큰도 별도 컬럼에 유지합니다.
- `equipment_score_supplement_active_declared`: `unmarked`와 `new` 표식이 있는 성적표 장구 선언만 보여주는 뷰입니다. 해제(`removed`) 표시는 토큰 테이블에 남기고 뷰에서는 제외합니다.

뷰는 성적표에 적힌 장구 선언을 뜻합니다. 실제 착용 여부를 증명하지 않으며, 장구 표시가 비어 있다는 이유만으로 장구를 사용하지 않았다고 판단하지 않습니다. 식별자와 착순은 앞자리 0과 원문을 보존하도록 문자열로 저장합니다.

저장소 루트에서 읽기 전용 드라이런을 실행합니다.

```bash
.venv/bin/python thoroughbred/research/20261001_equipment_score_supplement_v1/load_equipment_score_supplement.py
```

실제 코어 DB 쓰기는 `--apply --confirm-core-append` 두 옵션을 모두 요구합니다. 쓰기 전에 DB와 코어 매니페스트를 함께 백업하고, 단일 DuckDB 트랜잭션으로 세 객체와 `source_manifests` 항목을 추가한 뒤 기존 코어 매니페스트에 입력·적재 정보를 덧붙였습니다. 적재 완료 후에는 위 명령이나 적재 옵션을 다시 실행해도 동일 입력·현재 DB·보완 레코드를 읽기 전용으로 검증한 뒤 `already_applied_verified`로 종료합니다.
