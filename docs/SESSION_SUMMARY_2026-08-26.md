# 2026-08-26 대시보드 디자인 개편

기준 시각: **2026-08-26 03:45 KST** (브라우저 시각 확인 완료)  
이 문서는 로컬 웹 대시보드의 **디자인·인터랙션 전면 개편**만 정리한다.
데이터 수집·백필·모델은 [SESSION_SUMMARY_2026-08-25](SESSION_SUMMARY_2026-08-25.md)와
[CURRENT_STATUS](CURRENT_STATUS.md)를 본다.

서버: `uv run --group web horse-racing serve-dashboard` → `http://127.0.0.1:8000`

---

## 1. 한줄 요약

기존 단색 테이블 UI를 **다크 퍼스트 데이터 보드**로 바꿨다. 에메랄드/라임 포인트,
다크·라이트 테마 토글, 테이블 컬럼 정렬, 구간 차트 곡선·호버, 경주 상세 목차
스크롤 스파이를 넣었다. 표시 데이터와 Python 로더는 바꾸지 않았다.

---

## 2. 목표와 제약

### 목표

- 많은 숫자(착순, 기록, 배당, 구간)를 한눈에 읽히게 한다.
- 현대적인 다크 대시보드 톤을 쓰되, 라이트 모드도 유지한다.
- 차트·테이블·목차로 경주 상세를 탐색하기 쉽게 한다.

### 제약 (다른 에이전트와 충돌 방지)

같은 워킹트리에서 데이터 파이프라인 작업이 진행 중이었으므로, 수정 범위를
`src/horse_racing/web/`의 **템플릿·CSS·JS**로 한정했다.

- 건드리지 않음: `models.py`, `cli.py`, `services/`, `migrations/`, `dashboard.py`,
  `race_page.py`, `entities.py`
- 테스트가 검증하는 문자열·URL·클래스(`silk-N`, `section-chart-data` 등)는 유지

---

## 3. 디자인 시스템

파일: `src/horse_racing/web/static/css/dashboard.css` (Design System v3, 전면 재작성)

| 항목 | 내용 |
|---|---|
| 기본 테마 | 다크 (`data-theme="dark"`, 배경 `#0a0f0d`) |
| 포인트 | 에메랄드 `#34d399`, 라임 `#bef264` |
| 입상 강조 | 금/은/동 행 하이라이트 + 착순 뱃지 |
| 타이포 | UI: Pretendard Variable / 숫자: JetBrains Mono |
| 서피스 | 라운드 카드, 글래스 헤더, 앰비언트 글로우 |
| 접근성 | `prefers-reduced-motion`이면 카운트업·차트 그리기 애니메이션 생략 |

라이트 모드는 `[data-theme="light"]` CSS 변수 세트로 전환한다. 선택은
`localStorage` 키 `hr-theme`에 저장되고, `base.html` 인라인 스크립트가 페인트
전에 적용해 FOUC를 막는다.

폰트는 CDN(jsDelivr, Google Fonts)에서 불러온다. 오프라인이면 시스템 폰트로
대체된다.

캐시 무효화: `base.html`의 CSS/JS URL에 `?v=3`을 붙였다.

---

## 4. 화면별 변화

화면 구성(경로·표시 데이터)은 2026-08-25와 같다. 바뀐 것은 레이아웃·시각·조작이다.

| 화면 | URL | 디자인·인터랙션 |
|---|---|---|
| 공통 셸 | 전 페이지 | sticky 글래스 헤더, 브랜드 마크 `HR`, 테마 토글, 로컬 데이터 상태 점 |
| 경주 목록 | `/` | 요약 카드 카운트업, 필터 select 변경 시 자동 제출, 클릭 가능한 경주 행 |
| 경주 상세 | `/races/{id}` | 히어로 + 목차 스크롤 스파이, 출전표 컬럼 정렬, 입상 행 강조, 구간 차트 |
| 엔티티 목록 | `/horses` 등 | 검색/정렬 필터, 목록 테이블 컬럼 정렬 |
| 엔티티 상세 | `/horses/{id}` 등 | 성적 요약 카드 카운트업, 말 이력 탭 유지 |

### 4.1 경주 상세 목차

데이터가 있는 섹션만 링크가 생긴다.

- 결과, 구간, 배당, 기수변경, 출전취소, 장구, 심판

현재 보이는 섹션은 `.page-toc a.is-current`로 표시한다.

### 4.2 출전표

매크로 `entry_table` (`_macros.html`)에 `data-sortable`을 붙였다.

- 헤더 클릭/Enter/Space로 오름·내림차순
- 기록 `1:13.5`는 초 단위로 변환해 정렬
- 결측(`—`, `-`, 빈값)은 항상 아래로
- 마번 실크(`silk-1` … `silk-18`) 색상은 그대로 유지

---

## 5. 인터랙션 (`dashboard.js`)

| 기능 | 동작 |
|---|---|
| 테마 토글 | 다크 ↔ 라이트, `hr-theme` 저장, `hr:themechange` 이벤트 |
| 필터 자동 제출 | `[data-filter-form]` 안의 select 변경 시 submit |
| 행 내비게이션 | `[data-href]` 행 클릭·키보드, modifier 키면 새 탭 |
| 말 이력 탭 | `[data-history-tabs]` (기존 유지) |
| 카운트업 | `[data-countup]` 정수, 650ms ease-out, 축소 모션이면 생략 |
| 테이블 정렬 | `table[data-sortable]` |
| 스크롤 스파이 | `.page-toc` + `IntersectionObserver` |

---

## 6. 구간 전개 차트 (`race-chart.js`)

기존 SVG 차트를 유지한 채 시각·조작만 강화했다.

- Catmull-Rom 곡선 (직선 경로 → 부드러운 곡선)
- 로드 시 스트로크 그리기 애니메이션 (`prefers-reduced-motion`이면 생략)
- 투명 히트영역으로 툴팁 접근성 개선
- 다크/라이트 팔레트 분리, 테마 전환 시 리드로우
- 착순 1~5위는 기본 핀, 범례 클릭으로 시리즈 on/off

데이터 페이로드 ID `section-chart-data`는 테스트 호환을 위해 유지했다.

---

## 7. 변경 파일

Python 백엔드·테스트 코드는 이 세션에서 수정하지 않았다.

| 파일 | 역할 |
|---|---|
| `src/horse_racing/web/static/css/dashboard.css` | 디자인 시스템 전면 재작성 |
| `src/horse_racing/web/static/js/dashboard.js` | 테마·정렬·카운트업·스파이 |
| `src/horse_racing/web/static/js/race-chart.js` | 곡선 차트·테마 연동 |
| `src/horse_racing/web/templates/base.html` | 폰트, FOUC 방지, 테마 토글 |
| `src/horse_racing/web/templates/_macros.html` | 정렬 가능한 출전표 |
| `src/horse_racing/web/templates/dashboard.html` | 목록 레이아웃 |
| `src/horse_racing/web/templates/race_detail.html` | 히어로·목차 |
| `src/horse_racing/web/templates/entity_list.html` | 목록 정렬 |
| `src/horse_racing/web/templates/entity_detail.html` | 요약 카드 |

---

## 8. 검증

- `tests/test_dashboard.py` 등 웹 테스트 **9개 통과** (개편 직후)
- 브라우저에서 경주 목록, 경주 상세(결과·차트), 라이트 모드를 시각 확인

확인 방법:

```bash
uv run pytest tests/test_dashboard.py tests/test_formatting.py -q
uv run --group web horse-racing serve-dashboard
```

---

## 9. 의도적으로 하지 않은 것

- 예측 페이지(`/predictions`) — 로드맵 Phase 7
- 실시간/확정배당 UI 고도화 — 08-25 세션에서 보류
- 차트 라이브러리(D3 등) 도입 — 기존 커스텀 SVG 유지
- 백엔드 필드 추가, 새 API 엔드포인트
- 폰트 로컬 번들 (CDN 의존)

---

## 10. 다음으로 손볼 수 있는 UI

기능이 아니라 디자인 후속이다. 데이터 작업과 겹치지 않게 `web/` 안에서만 진행한다.

- 모바일 뷰포트에서 출전표 가로 스크롤·컬럼 우선순위 재검토
- 구간 차트에 코너/거리 축 라벨 가독성
- 말 상세 이력 탭의 시계열 미니차트 (체중·레이팅)
- 다크 모드 실크 색상 대비 점검 (`silk-2` 등 어두운 마번)
