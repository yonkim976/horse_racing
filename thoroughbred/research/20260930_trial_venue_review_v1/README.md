# 2026-09-17 영남 주행심사 장소 검토

> 2026-10-01 후속 정정: 2026-09-17 영남 주행심사 4회차·48행은 [공식 계획 및 사용자 설명 재검토](../20261001_yeongnam_trial_venue_recheck_v2/README.md)를 거쳐 코어 DB의 별도 검토 뷰에서 부산경남·1,000m로 보완했다. 아래는 최초 원천 검토 기록이며, API·RPT 원문과 이전 CSV는 변경하지 않았다.

마사회 주행심사 API의 `meet=3` 2026-09-17 기록은 4경주·48두이며 원문 표기는 `영남`이다. 이 4경주는 이미 `trial_sessions`와 `trial_participants`에 적재되어 있다. 이 원장은 **실제 시행 장소**만 별도로 검토하며 API 표기를 수정하거나 심사 행을 중복 적재하지 않는다.

[마사회 API20_1 명세](https://www.data.go.kr/data/15056974/openapi.do)는 영천 시행 이후 부산경남·영천을 합쳐 `영남경마`로 표출한다고 설명한다. 공식 [주행심사 결과 화면](https://race.kra.co.kr/referee/RacingTrainCheckList.do?Act=07&Sub=8&meet=3)과 [성적표 RPT](https://race.kra.co.kr/dbdata/fileDownLoad.do?fn=chollian%2Fbusan%2Fjungbo%2Fap-check-rslt%2F20260917dacom23.rpt&meet=3)는 회차와 결과를 확인시켜 준다. 그러나 자료 본문은 장소를 `부산경남` 또는 `영천`으로 명시하지 않는다. RPT URL의 `busan`은 파일 저장 경로이며 실제 시행 장소의 직접 증거로 쓰지 않는다. 같은 `meet=3` 경로의 2026-09-13 경마 성적표 본문에는 영천 경주가 들어 있다.

따라서 [검토 원장](venue_review.csv)의 `physical_venue`는 공란, `venue_review_status`는 `physical_venue_unresolved`이다. 코어 DB의 `trial_venue_review`에는 이 날짜를 한 행으로, `trial_sessions_venue_reviewed`에는 기존 4개 심사에 결합해 보존한다. 장소를 확정하려면 해당 날짜·회차를 특정하는 공식 공지, 장소가 적힌 성적표, 또는 공식 영상의 장소 표기가 추가로 필요하다.
