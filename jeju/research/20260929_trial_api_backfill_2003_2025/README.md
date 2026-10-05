# 제주 주행심사 API 원천 백필

수집일: 2026-09-29  
주요 범위: 2003~2025, `meet=2`  
보충 관측: 2000~2002  
출처: [공공데이터포털 15056974 한국마사회 주행심사 상세결과](https://www.data.go.kr/data/15056974/openapi.do)

## 수집 방식

공식 API `GET /API20_1/ridingTestResult_1`를 연도별 `meet=2`, `tr_year=YYYY`, `_type=json`으로 호출했다. 페이지당 요청 수는 1,000행이다. 성공한 응답 본문은 원래 HTTP body 바이트 그대로 페이지 파일에 저장하고, 시도별 manifest에 SHA-256, 상태코드, 바이트 길이, 키가 제거된 URL, 페이지 건수와 전체 `totalCount`를 기록한다. 인증키 값은 파일과 manifest에 기록하지 않는다.

2003~2025 주 범위의 연도별 원문은 `raw/trials/YYYY/attempts/<attempt_id>/source_pages/`에 있다. 2000~2002 조회는 시작 연도를 확인하기 위한 별도 보충 시도다. 각 연도는 성공된 시도가 있으면 재호출을 건너뛰고, 실패 연도는 새 attempt로 재개한다. 부분 응답과 실패 시도는 지우거나 성공으로 표시하지 않는다.

원문은 제주 경마장(`meet=2`)의 API 반환 전체다. `majong` 값이 제주가 아닌 한라·한라(래) 행도 source layer에 그대로 포함된다. 공식 포털은 응답 필드 `majong`을 마종으로 설명하지만 공개 문서 화면에서 값의 enum/code 표는 확인되지 않았다. 따라서 `majong=제주` 건수는 원문 라벨 건수로 표기하고 별도의 코드 변환이나 품종 효력일 추정을 하지 않는다. 공식 KRA의 마종 필드는 품종 근거로 쓸 수 있지만, 역사적 효력시점은 별도 검토 대상이다.

## Coverage 결과

- 2003~2025: 23/23년 완료, 전체 API 29,557행, exact `majong=제주` 원문 라벨 14,746행.
- 2000~2002 보충: 전체 API 3,848행. 2000·2001 exact `majong=제주`는 0행, 2002는 20행이며 라벨 첫 날짜는 2002-06-12다.
- 2000~2025 합계: 전체 API 33,405행, exact `majong=제주` 14,766행.
- 별도 보존된 2026년 동료 수집 응답은 972행이며 exact `majong=제주`가 972행이다. 2026년 응답을 이 작업에서 다시 요청하거나 복제하지 않았다. 2000~2026 합계 coverage 계산은 비교 JSON에만 참조로 기록했다.
- 시도별 최초·최종 날짜, 정확한 마종 라벨 빈도, 말 ID·행 coverage와 응답 페이지 SHA는 [`collection_inventory.json`](collection_inventory.json) 및 각 `attempt_manifest.json`에 있다.

## phase2 비교

[`API_VS_PHASE2_COMPARISON.md`](API_VS_PHASE2_COMPARISON.md)와 [`api_vs_phase2_comparison.json`](api_vs_phase2_comparison.json)은 phase2 연구 DB를 SQLite read-only/query-only로 열어 날짜·심사번호·출주번호 기준 비교했다. 공식 API의 `majong=제주`와 phase2의 기존 제주 후보 상태 사이에 2003~2025년 14,735개 출주키가 겹치고, 52개 겹친 키는 phase2에서 말 ID가 연결되지 않았다.

- API에만 있는 제주 라벨 행 11개 중 9개는 phase2 첫 관측일 2003-07-11 전이다. 나머지 2개는 2003-09-05 심사 1의 출주 1·2이고, 해당 날짜 심사 자체가 phase2에 없어 시작일 공백만으로 설명되지 않는다.
- phase2 제주 후보 중 2021-10-21 심사 1 출주 1 `자수정`(말 ID `1019026`)은 공식 API의 동일 출주키에서 `majong=한라`다. 새 제주마 원장에 자동 확정하지 말고 품종 충돌로 격리해야 한다.
- 합계는 API 14,746 제주 라벨 행과 phase2 제주 후보 14,736행이다. 차이 +10은 API 전용 11행에서 phase2 전용 한라마 표기 1행을 빼면 설명된다.

2026년 API 972행을 기존 별도 attempt에서 참조하면, 2002~2026-09-16 exact 제주 라벨은 15,738행·1,967개 날짜/심사/심사일련번호 이벤트다. phase2의 15,688행·1,945 이벤트보다 각각 50행·22 이벤트 많다. 공식 `majong` 코드표 및 과거 효력시점이 확인될 때까지 이 합계는 원천 라벨 coverage로만 취급한다.

phase2 DB, 운영 DB, 기존 RPT/TXT 파일, 정규화/운영 원장은 수정하지 않았다. RPT/TXT는 이번 수집의 원천이나 대체 입력으로 사용하지 않았다.
