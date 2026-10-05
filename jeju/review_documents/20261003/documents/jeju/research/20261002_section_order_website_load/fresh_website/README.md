# 제주 홈페이지 새 조회: API6 구간표 공란 6경주와 순위 정정 후보 14건

2026-10-02에 KRA 제주 성적 페이지 8개를 각각 새 HTTP GET으로 다시 받았다. 요청은 고정된 `race.kra.co.kr` 성적표 URL과 아래 8개 경주 키만 사용했다. 캐시 파일은 재사용하지 않았다. DB에는 접속하거나 쓰지 않았다.

## 6개 상세 구간표 공란 재확인

각 페이지는 HTTP 200이며 페이지 표제에서 날짜·경주번호·제주를 확인했다. 표의 해당 세 행은 모두 빈 셀로 내려왔다.

| 날짜 | 경주 | 펄롱타임 | 통과거리 | 통과타임 |
|---|---:|---|---|---|
| 2025-01-10 | 1R | 공란 | 공란 | 공란 |
| 2025-05-16 | 8R | 공란 | 공란 | 공란 |
| 2025-05-23 | 3R | 공란 | 공란 | 공란 |
| 2025-06-27 | 4R | 공란 | 공란 | 공란 |
| 2025-07-04 | 5R | 공란 | 공란 | 공란 |
| 2026-09-11 | 5R | 공란 | 공란 | 공란 |

이 판정은 홈페이지의 **경주 전체 상세 구간표**에 한정된다. 말별 구간시간·통과착순 표의 결측 여부는 여기서 판정하지 않는다.

## 홈페이지 순위 후보 대조

2025-10-17 7R 10건, 2026-03-06 8R 4건의 후보 14건 모두 홈페이지 마명 링크의 `goHorseID`가 후보의 `horse_id`와 일치했다. 홈페이지의 6개 지점 경로(S1F, 1C, 2C, 3C, 4C, G1F)를 출전번호별로 추출했고, 후보 14건의 해당 홈페이지 순위가 각각 일치했다. 비교에 사용한 순위는 결승 착순 열이 아니라 `S1F-1C-2C-3C-4C-G1F` 경로의 지점별 값이다.

| 날짜 | 경주 | 대조 건수 | 말 ID 일치 | 후보 홈페이지 순위 일치 |
|---|---:|---:|---:|---:|
| 2025-10-17 | 7R | 10 | 10/10 | 10/10 |
| 2026-03-06 | 8R | 4 | 4/4 | 4/4 |

이는 홈페이지 관측값 재확인이다. DB 정정 적용은 이 작업에서 하지 않았다.

## 보존 파일과 인코딩

- [evidence.json](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261002_section_order_website_load/fresh_website/evidence.json>): 8페이지별 URL, 조회 UTC 시각, HTTP 상태, 날짜·경주·제주 표제 확인, raw 경로, SHA-256, 바이트 수, 제목, 표 헤더 및 행을 보존한다.
- [candidate_crosscheck.json](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261002_section_order_website_load/fresh_website/candidate_crosscheck.json>): 후보별 `goHorseID`, 마명, 선택 지점 순위 및 6개 지점 순위 경로 대조 결과를 보존한다.
- [section_gap_blank_summary.json](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261002_section_order_website_load/fresh_website/section_gap_blank_summary.json>): 6개 경주에서 세 상세 구간 행의 공란을 요약한다.
- `YYYYMMDD_R.html`: 각 GET 응답의 HTML 바이트를 그대로 저장했다.
- [collect_fresh_website.py](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261002_section_order_website_load/fresh_website/collect_fresh_website.py>): 지정된 8개 키만 새로 요청하고 위 증거를 생성한 수집기다.

KRA HTTP 응답은 `text/html; charset=EUC-KR`로 선언되어 있었다. 원응답 바이트를 변환하지 않고 보존했으며, BeautifulSoup가 선언된 인코딩으로 디코딩해 표 내용을 추출했다. 따라서 원 HTML 파일은 UTF-8 재인코딩본이 아니다. 파일별 인코딩 선언과 UTF-8 유효성 표시는 `evidence.json`에 포함했다.

## 범위

이번 확인은 홈페이지 원문 수집과 비교 자료 작성만 수행했다. DB 변경, 파서 변경, 말별 기록 전체의 누락 판정, 모델 입력 반영은 하지 않았다.
