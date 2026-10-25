# 2026-10-17 제주 구간상세·통과조 홈페이지 대조

후속 사용자 승인으로 API6·API303 각 7행과 5R 홈페이지 거리 검토 6칸을 [실제 DB에 반영했다](../20261018_oct17_section_load/README.md). 아래와 이 폴더의 기존 원장은 적재 전 원문 대조 단계의 상태이며 원문·해시·검토 결과를 그대로 보존한다.

검토일: **2026-10-18 KST**. 조사 범위는 2026-10-17 제주 1~7경주의 KRA 성적 홈페이지, 기존 API4 결과 69행, API6 경주별 구간기록, API303 통과조다. DB는 SQLite `mode=ro`와 `query_only`로 읽었고 수정·갱신하지 않았다.

## 확인 결과

KRA 공식 성적 페이지 7개에서 날짜·제주·경주번호를 각각 확인했다. 공식 말 링크의 말 ID, 마번, 착순을 기존 API4 자료와 대조해 **69두 모두 일치**했다. 독립 파서도 같은 7개 원문을 검사해 69두의 ID·마번·착순 일치를 확인했다.

페이지의 세 자료 유형은 서로 다른 단위다.

| 홈페이지 항목 | 단위와 내용 | 대조 원천 |
|---|---|---|
| `펄롱타임`·`통과거리`·`통과타임` | 경주 전체의 구간시간·거리·누적 통과시간. 1~7R 합계 39개 지점 | API6, 경주당 1행 |
| `통과순위` | S-1F·코너·G-1F별 마번 그룹 문자열 | API303 및 API6, 경주당 1행씩 |
| 말별 `S1F-1C-2C-3C-4C-G1F` 및 지점별 시간 | 출전마 한 마리씩의 지점 순위·기록 | API4, 출전마당 1행 |

API4 69행의 말별 6개 지점 시간·순위, G-3F 시간, 완주시간은 홈페이지 행과 일치했다. 경주 전체 표에서는 API6의 **39개 구간시간과 39개 누적시간**이 홈페이지와 일치했다. API6·API303은 각각 29개의 실제 통과조 문자열을 제공했고, 두 원천 모두 홈페이지의 괄호·기호를 포함한 그룹 문자열과 29/29 일치했다. 괄호 안 말들의 개별 순서는 추정하지 않았다.

### API6·API303 재조회

기존 갱신 실행 `20261017T220226_4747d5bd`는 2026-10-17 22:02 KST 무렵 API6 구간기록과 API303 통과조에서 각각 **0행**을 받았다. 2026-10-18 04:02:34 KST의 제한된 재조회에서는 두 API가 각각 **7행**을 반환했다. 따라서 이전의 0행 상태는 재조회 시점에 해소되어 해당 응답에서 확인 가능했다. 실제 게시 시각이나 당시 0행의 내부 원인은 이 자료만으로 특정하지 않는다.

재조회는 날짜 `20261017`, 제주(`meet=2`)만 요청했다. API6와 API303 각 한 번, 총 2회 요청했고, 최대 동시 요청 2개·요청별 20초 제한·응답 4 MiB 상한·TLS 검증·리다이렉트 비활성 조건을 적용했다. 인증값은 기존 설정 도우미로 메모리에만 읽었고 출력·저장하지 않았다.

| 원천 | 오늘 행 수 | 보관 원문 SHA-256 |
|---|---:|---|
| API6 `/API6/raceDetailSectionRecord_1` | 7 | `80de7db02fe04b7eb0431fb18b312fb92d121a538cf677f87d928b5ab86ce640` |
| API303 `/API303/corner_rank` | 7 | `2c49575bf06a95844134574b64f17fe98ae55fb31519f3734190946ef23d9215` |

이전 원천 매니페스트 SHA-256은 `9dc27d3d21f4dc993cd276879f1b0b83d89927b2b2a57429efd358ea601f5f72`다. 이전 API4 결과 원문에는 69행이 있으며 페이지 SHA-256은 `bd320b9c59967df87ccb136cd2915abbe1ea4098991472a884e368b2bedbc23d`다.

### 5경주 거리 6칸 원문 불일치

5경주 전체 거리는 1110m다. 홈페이지의 `통과거리`는 `110, 310, 510, 710, 910, 1110`m이고, API6 원문 `dist_1f`~`dist_6f`는 `100, 300, 500, 700, 900, 1100`m다. API6의 `rcDist`는 1110m다. 39개 거리 지점 중 나머지 33개는 일치한다. 시간값 39개 구간·39개 누적값은 모두 일치한다. 여섯 값은 **출처 불일치 후보**로 보존하며 어느 쪽도 수정하거나 보정하지 않았다.

### 비어 있는 통과 지점

홈페이지 코너 표에서 1코너 통과조는 7개 경주 모두 비어 있다. 2코너 그룹은 7경주에만 있으며, 1~6경주에서는 비어 있다. S-1F·3코너·4코너·G-1F 그룹은 7경주 모두 값이 있다. API6/API303의 `-`와 홈페이지의 빈 칸은 해당 지점에 그룹 값이 없다는 뜻으로 대조했다. 홈페이지 말별 표에서도 해당 지점의 적용 불가 기록 칸은 빈 값으로 남아 있다.

예를 들어 1경주 S-1F 원문은 `5-(10,3,7),(2,4),8-1,(6,9)`이고, 7경주 2코너 원문은 `(5,9)-(10,3,4),(2,1,8),6,7`이다. 괄호 묶음과 기호를 그대로 보존했다.

## 경주별 홈페이지 원문

각 페이지는 아래 KRA 공식 URL에서 GET으로 가져왔다. 응답은 최대 4 MiB, 시간 제한 20초, TLS 인증서 검증, 리다이렉트 비활성 조건으로 보관했다. EUC-KR 페이지를 HTMLParser로 추출하고, 별도로 BeautifulSoup 파서가 원문을 독립 확인했다.

| 경주 | 출전마 | 구간 지점 수 | 홈페이지 원문 ID | 원문 SHA-256 |
|---:|---:|---:|---|---|
| 1R | 10 | 5 | `kra-scoretable-jeju-20261017-r01` | `b609c7e3e107a611282f11a5d32a5255070b02e66ed92a881be454a6e03e839f` |
| 2R | 10 | 5 | `kra-scoretable-jeju-20261017-r02` | `e95be063b7f3b89fb76bff01195cff53e89885c88fcdb417b3e7e91e138f45bd` |
| 3R | 10 | 5 | `kra-scoretable-jeju-20261017-r03` | `1c863aee859a9ff15c47023ca979ab3f2a55ad7c8c8342d7be93ae3edab2c3ee` |
| 4R | 9 | 5 | `kra-scoretable-jeju-20261017-r04` | `9355de27247f64c714dad10e7729e78666718107d8fd70801b95505bf28a5bdd` |
| 5R | 10 | 6 | `kra-scoretable-jeju-20261017-r05` | `c1e52a671ec2eca41b5190e937959825502c9c8e2a32ea8598da1bec814edf92` |
| 6R | 10 | 6 | `kra-scoretable-jeju-20261017-r06` | `71cdf5e00002c5aa3d43967af486fbc9e7947b93dd65b9915e9696c427a26698` |
| 7R | 10 | 7 | `kra-scoretable-jeju-20261017-r07` | `5841cbcb1b99fef4a585e9bd34c31745a36bdce8ffc4b9be6f4977a037dece67` |

공식 페이지 링크: [1R](https://race.kra.co.kr/raceScore/ScoretableDetailList.do?Act=04&Sub=1&meet=2&realRcDate=20261017&realRcNo=1), [2R](https://race.kra.co.kr/raceScore/ScoretableDetailList.do?Act=04&Sub=1&meet=2&realRcDate=20261017&realRcNo=2), [3R](https://race.kra.co.kr/raceScore/ScoretableDetailList.do?Act=04&Sub=1&meet=2&realRcDate=20261017&realRcNo=3), [4R](https://race.kra.co.kr/raceScore/ScoretableDetailList.do?Act=04&Sub=1&meet=2&realRcDate=20261017&realRcNo=4), [5R](https://race.kra.co.kr/raceScore/ScoretableDetailList.do?Act=04&Sub=1&meet=2&realRcDate=20261017&realRcNo=5), [6R](https://race.kra.co.kr/raceScore/ScoretableDetailList.do?Act=04&Sub=1&meet=2&realRcDate=20261017&realRcNo=6), [7R](https://race.kra.co.kr/raceScore/ScoretableDetailList.do?Act=04&Sub=1&meet=2&realRcDate=20261017&realRcNo=7).

## 보관 자료

- [경주별 홈페이지 출처·SHA·말 ID 대조](website_page_evidence.json)
- [API6/API303 재조회 요약과 시각·행 수](api_recheck_summary.json)
- [API6/API303 원문 대 홈페이지 비교 및 5R 불일치 목록](root_api_website_comparison.json)
- [독립 파서 검증 결과](root_independent_verification.json)
- [초기 홈페이지/API 비교 요약](comparison_summary.json)
- 원문 HTML: `raw/20261017_01.html`~`raw/20261017_07.html`
- 재조회 API JSON: `api_recheck/raw/section_records/20261017/page_0001.json`, `api_recheck/raw/corner_rank/20261017/page_0001.json`

이 자료는 홈페이지 표시와 보관 API 원문을 대조한 결과다. 5R 거리 차이의 원인을 확정하지 않으며 DB 반영·자동 갱신을 수행하지 않았다.
