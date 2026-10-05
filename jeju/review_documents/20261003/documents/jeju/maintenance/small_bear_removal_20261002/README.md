# 작은곰 사용자 요청 삭제

결정일: 2026-10-02. 사용자 지시: “작은곰은 데이터 삭제해줘 어차피 뭐가 없어서..”

말 이름이 아닌 공식 말 ID **3005648**로 로컬 제주 DB와 활성 출발심사 후보에서 삭제했다.

| 삭제 대상 | 행 수 |
|---|---:|
| 마필 프로필 | 1 |
| 주행심사 | 2 |
| 위 자료의 품종 근거 | 3 |
| DB 원천 item `api_records` | 3 |
| 활성 API21 출발심사 후보 | 2 |

보유 경주결과·일별조교·출발조교는 해당 말 기록이 각각 0행이었다. 삭제 후 다른 말의 행 수는 변하지 않았으며 FK 위반 0, SQLite `quick_check=ok`, 말 분석 뷰에서도 해당 ID 0행을 확인했다. 현재 API21 후보는 **10,664행·4,636두**, 기승자 필드 미제공은 **5,795행**이다. 제주 DB 재수집·재구축 시 `data/horse_exclusions.json`의 사용자 제외 ID를 적용한다. API21 후보 검증기에도 이 제외를 반영했고 원문 25,614행 = 활성 후보 10,664행 + 품종 미분류 14,948행 + 사용자 제외 2행으로 재검산했다.

원문 응답 파일·과거 감사는 증거 보관으로 유지하며 활성 DB 입력이 아니다. 삭제 전 DB는 `before_deletion.sqlite3`, 삭제 DB 행은 `deleted_database_rows.json`, 출발심사 삭제 2행은 `deleted_api21_candidate_rows.jsonl`에 보관했다. 삭제 전 후보 및 보고서도 이 폴더에 보관했다. 백업·변경 후 DB·활성 후보의 해시와 실제 삭제 수는 [deletion_receipt.json](</Users/kimyongjin/Desktop/horse_racing/jeju/maintenance/small_bear_removal_20261002/deletion_receipt.json>)에 있다.

## 기승자 누락 조사

삭제 후 후보의 `rider` 키 미제공은 2002-06-07~2021-10-24에만 있고, 2021-10-27~2026-09-30 후보는 모두 값이 있다. 저장된 API JSON 자체가 옛 기간의 키를 생략하므로 파서 손실이 아니다. 과거 홈페이지에는 같은 말·날짜의 기승자명이 존재하는 사례가 있다. 공식 문서에서 해당 필드의 변경 이력이나 이전 값 미제공 사유는 확인되지 않아 API 내부 원인은 확정하지 않았다. 전환일은 수집 원문에서 관측된 제공 시작일이다. [기간별 재계산](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261002_starting_exam_data_audit/rider_absence_periods_20261002.json>)을 참조한다.
