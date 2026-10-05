# 제주 출발심사 API 수집 및 홈페이지 교차확인

기준일: 2026-10-02 (Asia/Seoul)  
요청 범위: `meet=2`, 2000-01-01부터 2026-10-02까지  
현재 상태: API21 연도별 27개 파티션 수집 및 독립 검증 완료

2000년은 요청한 시작 연도다. 공식 API의 최초 제공 연도는 별도로 확인하지 않았다. 수집 원문에서 관측된 날짜는 2000-01-07부터 2026-09-30까지다. 2026년은 연간 파티션을 원문 그대로 보존했으며 요청 종료일 이후 행은 0개였다.

## 공식 API와 수집 결과

공공데이터포털의 [한국마사회 출발심사 결과 API](https://www.data.go.kr/data/15057405/openapi.do)를 사용했다. 공식 경로는 `https://apis.data.go.kr/B551015/API21_1/startingTestResult_1`, operation은 `startingTestResult_1`, 인증 파라미터는 `ServiceKey`다. 공식 HTML과 Swagger JSON은 [official_metadata/](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261001_starting_exam_api_collection/official_metadata>)에 저장했고 SHA-256은 [metadata manifest](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261001_starting_exam_api_collection/official_metadata/metadata_manifest.json>)에 기록했다.

API21은 `meet`, `tr_year`, `tr_month`, `tr_date`로 조회한다. `meet=2`는 제주 경마장 구분이며 품종 필터가 아니다. 응답의 `passFlag`와 사유 필드는 원문 그대로 유지한다. `합격`, `불합격`, `1차합격` 외의 취소·제외·기타 라벨과 `-`도 각각 보존하며 하나의 결과로 합치지 않았다.

2000~2026년 연간 파티션 27개, 응답 페이지 37개, 원문 행 25,614개를 수집했다. 2026년은 807행이다. 페이지 SHA-256, 응답 행 수, `pageNo`, `totalCount` 검증이 모두 통과했다. 같은 내용 행을 삭제하지 않았다. 전체 연도·페이지별 원장과 해시는 [api21_successful_collection_report.json](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261001_starting_exam_api_collection/api21_successful_collection_report.json>), 독립 검증 결과는 [api21_independent_verification.json](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261001_starting_exam_api_collection/api21_independent_verification.json>)에 있다.

API21 응답은 [raw/api21_1/partitions/](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261001_starting_exam_api_collection/raw/api21_1/partitions>) 아래 연도별 immutable attempt에 보존했다. 인증 복구 전 `independent_final_verification.json`과 [aggregate_report.json](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261001_starting_exam_api_collection/aggregate_report.json>)은 당시의 차단 상태를 기록한 과거 스냅샷이다. 현재 상태는 위의 성공 수집 보고서와 `api21_independent_verification.json`을 기준으로 한다.

## 마필 연결 및 홈페이지 대조

공식 말 ID와 현재 API42 프로필을 연결하고 사용자 제외를 적용한 활성 API21 후보는 10,664행·4,636두다. 작은곰(3005648) 2행은 2026-10-02 사용자 지시에 따라 후보에서 삭제했다. 나머지 14,948행(고유 말 ID 10,769개)은 현행 프로필 품종을 확인하지 못해 미분류로 남겼다. “제주 경마장에서 심사됨”만으로 제주마나 한라마를 단정하지 않았다. 연결 후보는 [api21_verified_native_candidate_rows.jsonl](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261001_starting_exam_api_collection/api21_verified_native_candidate_rows.jsonl>), 후속 확인 대상은 [api21_unlinked_horse_inventory.jsonl](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261001_starting_exam_api_collection/api21_unlinked_horse_inventory.jsonl>)이다. API42 품종은 현재 프로필 기준이며 과거 심사일에 유효했던 품종을 뜻하지 않는다.

2026년 API 원문 807행과 공식 홈페이지 검증 관측 66행을 비교했다. 독립 검증에서 9개 신원·결과 필드는 기록된 정규화 기준으로 모두 일치했다. 홈페이지 원문과 별도 후보 파일은 [website_validation/](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261001_starting_exam_api_collection/website_validation>) 및 [website_native_candidate_rows.jsonl](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261001_starting_exam_api_collection/website_native_candidate_rows.jsonl>)에 있다. 홈페이지 최신 확인일은 2026-09-30이며 10월 1일과 2일 홈페이지 자료는 수집하지 않았다.

## 접근 이력과 안전 기준

초기 API21 요청은 HTTP 403, `SERVICE_KEY_IS_NOT_REGISTERED_ERROR`(사유 코드 30)로 실패했다. 서비스키 재활용 신청 완료 안내 후 API21 재호출에서 HTTP 200과 `resultCode=00`을 확인했고, 이후 전체 연도 수집이 완료됐다. 첫 성공 호출은 원문 페이지 1을 쓴 뒤 수집기 변수명 오류로 중단되어 `aborted_code_error`로 남겼다. 해당 원문은 변경하지 않았고, 수집기를 수정한 새 attempt에서 807행을 정상 완료했다. 실패·중단 attempt도 덮어쓰지 않았다.

초기 진단 예외 한 건의 도구 출력에 설정된 인증값이 포함된 URL이 나타났다. 저장 파일 138개에서 현재 설정값 원문 및 URL 인코딩값과 일치하는 내용은 없었다. 인증값은 저장소에 기록하지 않으며 작업 대화 기록에는 노출 흔적이 남아 있을 수 있다.

최초 원문 수집 단계에서는 DB에 쓰지 않았다. 이후 2026-10-02 사용자 승인으로 활성 제주마 후보 10,664행·4,636두와 API42 추가 프로필 21두의 제주 DB 적재·독립 검증을 완료했다. 현재 조회는 `starting_exam_api_rows` 및 `starting_exam_api_rows_analysis_2026`이며 상세 계약·출처·백업은 [적재 보고서](<../20261002_starting_exam_db_load/README.md>)를 따른다. 최초 수집기는 인증값을 URL·예외 문자열에 출력하지 않고 각 실행 결과를 새 attempt에 보존했다.

API21 수집기를 다시 실행하려면 다음 명령을 사용한다. 완료된 파티션은 기본적으로 재수집하지 않으며, 강제 재시도는 별도의 새 immutable attempt를 만든다.

```bash
.venv/bin/python jeju/research/20261001_starting_exam_api_collection/collect_starting_exam_api.py \
  --year 2026 --end-date 20261002
```

## 2026-10-02 추가 데이터 감사

전체 응답 25,614행과 제주마 후보 10,666행의 중복·식별키·날짜·프로필·판정·결측을 재검사했다. 원문 구조와 후보 연결은 통과했고, 판정 미제공 4행·불합격 사유 미제공 3행·외부마 조교사 코드 1행·과거 고령 나이 11행 및 알려진 성별 충돌은 보존할 검토 항목으로 문서화했다. 같은 날 다른 회차의 제주마 기록 779그룹은 유일화하지 않는다. [데이터 감사 및 홈페이지 추가 대조](<../20261002_starting_exam_data_audit/README.md>)를 따른다. 이번 감사에서도 DB 적재·원문 수정·삭제는 하지 않았다.

## 2026-10-02 작은곰 삭제 후 현행 후보

사용자 요청에 따라 작은곰은 활성 후보와 기존 제주 DB의 프로필·주행심사에서 삭제했다. 원문·기존 감사는 과거 스냅샷으로 보관한다. 현재 후보 10,664행·4,636두, 품종 미분류 14,948행, 사용자 제외 2행으로 구분한다. 기승자 미제공은 5,795행이며 2021-10-24까지의 후보에만 있다. 후보 생성 검증기는 `data/horse_exclusions.json`을 적용한다. [삭제·재검증 보고서](<../../maintenance/small_bear_removal_20261002/README.md>)에 이력과 백업이 있다.
