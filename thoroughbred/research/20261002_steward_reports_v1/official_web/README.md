# 공식 웹 과거 리포트 원천 확인

주 에이전트가 2026-10-02에 공식 페이지 3개를 읽고 원문과 수집 시각·해시를 보존했다. 운영 DB는 조회하지 않았다.

1. [현행 심판위원 Report](https://race.kra.co.kr/referee/StewardsReport.do?Act=06&Sub=12&meet=1)의 `goReport2()`는 `/referee/RefereeReport.do`로 조회 양식을 제출한다. 현행 서울 날짜 선택에는 2017-10-14가 있다.
2. [이전 Report 페이지](https://race.kra.co.kr/referee/RefereeReport.do?Act=06&Sub=12&meet=1)는 `board.kra.co.kr/board/viewBoard.do?boardNo=69`를 iframe으로 연다.
3. [서울 과거 게시판](https://board.kra.co.kr/board/viewBoard.do?boardNo=69) 첫 페이지에는 2017년 12월 일별 리포트 첨부 게시물과 2017-12-27 ‘심판위원 리포트 공개방식 개선에 따른 안내’가 있다. 페이지 코드의 목록은 142페이지다.

이번 확인은 과거 게시판 경로의 존재를 입증한다. 첨부파일의 내용·최초 보유일·2010년부터의 경주별 완전성은 아직 검증하지 않았다. API의 정상 빈 응답을 과거 심판사항 부재로 해석하지 않는다. 위 세 HTML은 API 수집 원문과 별도 보조 근거이며, 이 목록만으로 경주 본문을 적재하지 않는다.

HTML 문자 인코딩: `race.kra.co.kr` 두 페이지는 EUC-KR, 게시판은 UTF-8로 읽었다. 각 `.metadata.json`은 응답 상태·원문 SHA-256·UTC 수집 시각을 포함한다. 당시 게시 시각은 본문으로 확인되는 게시물에만 적용하며 API 본문의 역사적 이용 가능 시각을 대신하지 않는다.
