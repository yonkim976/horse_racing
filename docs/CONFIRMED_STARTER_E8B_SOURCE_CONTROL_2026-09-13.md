# E8-B 후속: 서울 과거 양성 대조군의 공식 원천 동작 확인

## 결론

서울 **2026-05-17**의 기존 비어 있지 않은 원문으로 날짜를 HTTP 전에 고정한 후, 공식 API26_2 출전표와 API154 일정의 **첫 페이지만** 한 번씩 조회했다. 두 요청 모두 HTTP 200이고 출전표 **110행**, 일정 **10행**을 반환했다. 이번 신규 transport 요청은 **2/4회**, 앞선 E8-B 5회를 합친 누적은 **7/12회**다. 조회한 날짜·원천에서 현재 요청 경로가 동작한다는 양성 대조 결과다. 2026-09-19의 빈 응답이 “미공개” 때문이었다는 증거는 아니며, 미래 조회 지원·게시 주기·지원 기간은 **unknown**이다. 미래 날짜 재조회나 예약 수집은 하지 않았다.

상태는 `positive_control_observed`이고, `first_page_nonempty=true`다. **`complete_dataset`은 `not_assessed_first_page_only`**다. 원문 `totalCount`와 첫 페이지 item 수가 각 110/110, 10/10으로 같더라도 이번 프로토콜은 추가 페이지·날짜 전체의 독립 완전성 검증을 수행하지 않았다. 과거 재조회는 T−30 관측이 아니다. 운영·모델 `not_activated`, F_t `unverified`다.

## 사전 고정 근거와 관측

기존 원문 index 경로 `data/raw/kra/entry_sheet/2026/05/17/meet_1/run_608/`의 첫 페이지 SHA256은 `6c4735c8b8694cb4b521c93344c75362a8a44e4cb0c5303f6015659f44bfa716`이고 110행이었다. 같은 날짜의 `data/raw/kra/race_plan/2026/05/17/meet_1/run_607/` 첫 페이지 SHA256은 `6ef89900f4fd337e9618ff457b3fa550419fd0ba073b6e533ebb767fde7e533e`이고 10행이었다. 성적 테이블을 사용해 날짜를 고르지 않았다. `preflight_protocol.json`은 이 경로·해시, 서울 meet=1, API26_2의 `rc_date=20260517`, API154의 `race_dt=20260517`, 공통 `pageNo=1`, `numOfRows=1000`, `_type=json`, transport 예산 4회를 최초 HTTP 전에 기록한다.

새 출전표 원문 SHA256은 `78f94758b09488044c8eba0d8a3d382bf6b69b19b0cdc9ed16f78351b023340d`(93,271 bytes), 새 일정 원문 SHA256은 기존과 동일한 `6ef89900f4fd337e9618ff457b3fa550419fd0ba073b6e533ebb767fde7e533e`(5,356 bytes)이다. 두 응답 모두 명시적 성공 header, `pageNo=1`, `numOfRows=1000`, `totalCount`와 실제 item 수 일치, 서울·해당 날짜 식별을 확인했다. 마지막 commit 완료는 `2026-09-13 18:20:54.293 KST`다. 요청/수신/파싱/commit의 개별 시각, HTTP 상태와 실패 여부는 append 원장 및 비교 JSON에 있다.

기존·신규 출전표의 `(meet, rcDate, rcNo, chulNo, hrNo)` 식별키 **110개는 모두 동일**했고 추가·누락·중복 키는 0개였다. 일정 경주키 10개도 동일하다. 반면 출전표의 원문 값은 **77행**에서 달랐다. 차이는 `rcCnt*`, `ord*Cnt*`, `chaksun*` 같은 누적 필드에 있었으며 `semantic_diff_assessment.json`에 필드별 변화 건수를 남겼다. 이는 과거 API 응답의 값이 사후에 달라질 수 있다는 관측이다. 두 재조회 중 어느 것도 당시의 사전시점 스냅샷으로 해석하지 않는다.

## 보존·검증·한계

첫 시도는 **HTTP 0회**로, 실행 source의 절대 경로가 스냅샷 밖을 가리키는 `SameFileError`가 preflight에서 발생했다. 그 폴더와 실패 평가는 보존했다. 수정 후 새 `data/experiments/confirmed_starter_e8b_source_control_20260913_attempt2/`에 실행 **전** source 6개 파일의 정확한 복사본·SHA256, preflight 프로토콜, 2개 응답의 비공개 raw CAS, append 요청 원장, `control_comparison.json`, manifest와 추가 semantic diff를 저장했다. 원문 CAS는 `0700` 디렉터리의 `0600` 파일이고, credential 값·인증 포함 URL은 기록하지 않았다. 응답 credential 반사도 검출되지 않았다. 기존 E8-B 5회 원장과 빈 원문은 수정하지 않았다.

관련 Ruff `check`와 `format --check`가 통과했고, 전체 `pytest -q`는 **621 passed, 2 warnings**였다(기존 Starlette deprecation 및 Polars PIT 경고). 새 회귀 검사는 사전 선택한 기존 원문 해시·비어 있지 않음, source 스냅샷 경로, 첫 페이지만으로 `complete_dataset`을 참으로 만들지 않음을 확인한다.

공식 문서의 공개 주기/미래 지원 문구는 이번에 확인하지 않았다. 두 과거 대조 응답이 모두 비어 있지 않아 지시문의 조건부 문서 확인 분기는 발생하지 않았기 때문이다. 따라서 다음 미래 수집을 실행할 조건은 **공식적으로 해당 날짜 출전표가 게시됐다는 독립 근거를 확인하고, 그 근거·시점을 새 사전 프로토콜에 고정하는 것**이다. 근거 없는 특정 요일·시각을 게시 시점으로 확정하지 않는다. 그때도 취소/정정 완전성, 실제 F_t 출전집합, 사전시점 가용성은 별도로 검증해야 한다.
