# Mapilog 디자인 시안 보관본 (2026-09-25)

Superdesign 캔버스의 시안을 저장소 안에 보관한 사본이다. Superdesign 계정 없이도 HTML을 브라우저로 열어
보고 구현 기준으로 쓸 수 있다. 평가와 단계별 계획은 [`../../MAPILOG_ANALYSIS_UX_PLAN_2026-09-25.md`](../../MAPILOG_ANALYSIS_UX_PLAN_2026-09-25.md)에 있다.

## 결정 사항

- 분석 화면(`/analysis`)은 **A안 분석 시트**로 간다.
- 모바일은 당분간 현재 버전을 유지한다.
- 첫 방문 기본 테마는 라이트다(코드 반영 완료).

## 시안 (`drafts/`)

| 파일 | 화면 | 상태 |
|---|---|---|
| `00-analysis-current-reproduction` | 현재 `/analysis` 재현본 | 기준점. 출전마 3두만 생성된 부분 재현 |
| `01-analysis-A-sheet-SELECTED` | 분석 시트 | **확정안** |
| `02-analysis-B-board` | 경주 보드 | 채택 안 함. 일부 카드가 빈 미완성본 |
| `03-race-tab-entry-card-pre` | 경주 탭 출마표 (경주 전) | 다듬은 안 |
| `04-race-tab-result-post` | 경주 탭 결과·기록표 (경주 후) | 다듬은 안 |

각 시안은 `.html`(열어서 보는 원본)과 `.png`(1440px 캡처)가 짝이다. HTML은 Tailwind·Pretendard·아이콘을
공개 CDN에서 불러오므로 열 때 인터넷 연결이 필요하다. 로고는 저장소의 `src/horse_racing/web/static/images/brand/`
파일을 상대 경로로 쓴다.

03·04번 시안은 2026-09-20 서울 8R 실제 데이터(기록, 구간 통과순위, 장구, 진료, 배당)로 만들었다.
최근 5전은 4번 라온포레스트만 실제 값이고 나머지는 예시다. 로컬 DB에 예정 경주가 없어 출마표는 같은 경주를
경주 전 상태로 꾸몄다.

## 현재 화면 캡처 (`current-ui/`)

평가에 쓴 개선 전 화면이다. `*-light-1440.png`는 라이트 테마 1440px 캡처이고, 나머지는 같은 날 먼저 찍은
데스크톱·모바일 캡처다.

## 기타

- `design-system.md`: 시안이 따르는 색, 글꼴, 간격, 컴포넌트 규칙.
- `source/gen_race_tab.py`: 03·04번 시안 생성 스크립트. `python3 source/gen_race_tab.py`로 `drafts/`에 다시 쓴다.

## Superdesign 원본

- 캔버스: https://superdesign.dev/teams/860f4440-c381-4e56-8b7f-1a499cd61c72/projects/54d3a0e7-1f39-40c6-a56a-5d1a86cd661d
- 시안 ID: 00 `f1988376-3d8f-46bf-b064-d6215c75b863`, 01 `1743d630-3532-4c2d-8635-34dcfed70fef`,
  02 `a1713323-82bb-4cf9-8650-a588d1ad92b9`, 03 `29f37626-7d5c-4bb5-a0e7-ed13ad9351c9`,
  04 `9a6bbd93-287d-4544-979d-4da39522862f`
