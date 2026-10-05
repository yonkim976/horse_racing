# 주행심사 시간 기준점의 공식 자료와 방법 출처

연구 작성·웹 확인일2026-10-03. 통계 자료의 종료일은2026-09-17이다. 공식 규정·공식 결과 데이터·외부 분석 방법을 구분해 사용했다.

## 마사회 공식 규정

- [2026년 경마시행계획 2026년 5월 개정본](https://race.kra.co.kr/down/raceplan2026_20260516.pdf): 인쇄65~66쪽(PDF69~70쪽) 서울·부경1000m 심사 거리와 연령별66.0/65.0초 기준. 2026하반기부터3세7월 이상 단계에65.0초를 적용한다. 두 장소의 시간 상한은 같다. [로컬 보존본](outputs/official_plan_2026.pdf)은 이전 장소 검토 연구가 공식 URL에서 확보한 파일을 복사했으며 해시는 분석 입력 목록에 있다.
- [서울경마 2026 주요변경사항](https://race.kra.co.kr/raceoper/RaceoperView.do?Sub=2&meet=1): 심사일을 기준으로 하는 연령별 합격 기록 차등화의 보조 대조.
- [경주마 조교심사 시행기준집 2026년 5월](https://race.kra.co.kr/down/trngImplementGuide_20260626130700.pdf): PDF6~7쪽의 심사내용과 주행상태 평가. 이번에는 웹 열람으로만 확인했고 이 파일 자체의 로컬 사본은 새로 확보하지 않았다.

## 마사회 공식 결과 원천

- [공공데이터포털 주행심사 상세결과 API20_1](https://www.data.go.kr/data/15056974/openapi.do): 공식 판정·사유·전체기록·개별 구간기록의 출처. 영천 시행 이후 영남 통합 표기라는 현재 원천 안내도 확인했다.
- 사용한 원천은 기존 보관 응답34개와 읽기 전용 코어DB의 `trial_participants_venue_reviewed`다. 참가 원문61,777행을 보관API 응답·행JSON과 재대조했다. 새 API 호출·원천DB 수정은 하지 않았다. [입력 경로와 해시](outputs/summary.json), [독립 대조 결과](outputs/verification.json)에 남겼다.
- [2026-09-17 영남 주행심사 장소·거리 검토](../20261001_yeongnam_trial_venue_recheck_v2/README.md): 그 날짜의48행을 부산경남1000m로 구분한 기존 공식계획 기반 판정을 유지했다.
- 전체기간/최근 전체시간 최단 관측행은 공식 성적표 보관 RPT4개와 말·시간을 추가 대조했다. 원 파일 경로·해시·기록행은 `verification.json`에 있다.

`rcTime`은 전체시간, `rcTimeS1f`·`rcTimeG3f`·`rcTimeG1f`는 개별 말의 출발200m·마지막600m·마지막200m 시간으로 사용했다. 부산의 `rcTimeG400`은 RPT 구간표의G400 표기와 대조했다. `passtime_3f/4f`나 통과순위 열은 개별 말 구간시간에 사용하지 않았다. 서울의G400 미제공을 다른 코너 누적시간으로 임의 대체하지 않았다.

## Timeform의 방법 참고

- [The Timeform Knowledge Sectional Analysis](https://www.timeform.com/horse-racing/features/rowley/the-timeform-knowledge-sectional-analysis-872015), Simon Rowlands, 게시2015-07-12. 사용자가 지정한 방법 참고 자료다.
- 마지막 구간의 속도를 같은 말의 전체 평균속도와 비교하는FS% 산식, 코스·거리·조건에 맞는 효율적par와 비교해야 한다는 설명을 참고했다. 글 전체나 이미지·Timeform의 유료 기록은 복제하지 않았다.
- 이번에 계산한 국내 주행심사FS200/600 및 부산FS400의 평균·중앙값은 기술 통계다. 효율적par·시간 보정량·예측 우위로 검증하거나 채택한 것이 아니다.

웹 출처는 위 링크를 직접 확인했다. 외부 사이트 규정은 이후 개정될 수 있고 이번 기록은2026-10-03 확인 범위다. 각 과거 연도의 실제 결과 판정은 API 원문을 유지하고 현재 시간 규정으로 다시 판정하지 않았다.
