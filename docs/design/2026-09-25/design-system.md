# Mapilog (마필로그) Design System

## Product context

Mapilog is a Korean horse-racing analysis web app built on Korea Racing Authority (KRA, 한국마사회) public data.
Users today read race cards on the KRA site, jump across many pages (출마표, 과거 성적, 주행심사, 조교, 영상),
and copy everything into their own Excel sheets to mark candidates. Mapilog removes that work:
it pre-joins the data and gives a ready-made, spreadsheet-like analysis format, like "Tableau/Excel with the data
and templates already filled in". Later, users will save their own analysis views, marks, and memos.

Job to be done: "Before an upcoming race, let me see every runner's relevant history side by side in one screen,
mark my picks, and reason about pace, without opening ten KRA tabs."

Key pages
- 경주 (Race calendar, `/`): pick date + meet, see race list and runners.
- 경주 분석 (Race analysis workspace, `/analysis`): THE core page. Race selector, field overview grid,
  per-horse dossier (past races, running trials, training, jockey), pace/tendency board, compare, memo, video.
- Entity pages (말 / 기수 / 조교사 / 마주), 예측 원장, 데이터 상태.
- Removed soon (never design): 미래 예측, 예측 검증, 거리별 분석.

Audience: Korean racing fans and semi-pro analysts, many on mobile at the track, power users on desktop.
All UI copy in Korean. Numbers, times, odds in monospace.

## Visual direction (keep)

Clean, modern, soft. Not rigid or corporate. Rounded surfaces, gentle shadows, calm green palette,
generous spacing around dense data. Data density is welcome inside tables, but the chrome around it stays airy.
Design in LIGHT theme by default (dark theme exists with the same token names).

## Color tokens (light)

- Background `#f2f5f2` with two very soft radial glows (green `rgb(5 150 105 / 6%)` top-left, lime `rgb(132 204 22 / 5%)` top-right)
- Surfaces: `#ffffff` (cards), `#fbfdfb`, `#f0f5f1` (subtle fills, table headers)
- Border `rgb(21 45 33 / 11%)`, strong border `rgb(21 45 33 / 22%)`
- Ink `#17241d`, strong ink `#060c09`, muted `#5d7066`, faint `#93a49a`
- Accent green `#059669`, accent strong `#047857`, deep `#065f46`, accent soft fill `rgb(5 150 105 / 9%)`
- Lime `#65a30d` (used in gradient with accent for active pills: green→lime)
- Medal: gold `#b45309` / soft `rgb(217 164 34 / 14%)`, silver `#64748b`, bronze `#9a5b2d`
- Red `#dc2626` (weight up, warnings), blue `#0369a1` / upcoming race `#1570c7`
- Hero gradient: `linear-gradient(135deg, #06392a 0%, #0b5a3c 60%, #0e6a47 100%)` (primary summary card only)
- Prediction role colors: 축마 `#168a42`, 대항 `#756900`, 관심마 `#9a6500`, 후순위 `#58635f`
- Saddle-cloth (silk) number colors follow KRA: 1 white, 2 yellow, 3 sky blue, 4 black, 5 blue, 6 green,
  7 brown-red, 8 pink, 9 purple, 10 gray-blue ... Always render horse numbers as rounded silk chips.

Dark theme equivalents: bg `#0a0f0d`, surfaces `#101714/#151e1a/#1a2621`, ink `#e7efe9`, accent `#34d399`.

## Typography

- Sans: "Pretendard Variable", Pretendard, "Noto Sans KR", sans-serif (all Korean text)
- Mono: "JetBrains Mono" (times like 1:12.8, percentages, odds, weights, eyebrow labels)
- Base 14px / 1.5. Page title 32-40px weight 800, tracking -0.03em. Section title 18-20px weight 800.
- Eyebrow labels: mono 11px, uppercase, letter-spacing 0.14em, accent color (e.g. "RACE STUDY").
- Do NOT introduce serif or decorative fonts.

## Shape, spacing, elevation

- Radius: panels/cards 18px, controls 12px, small chips 9px, pills 999px
- Shadow soft: `0 6px 18px rgb(20 40 30 / 7%)`; raised: `0 16px 40px rgb(20 40 30 / 10%)`
- Page width `min(1520px, 100% - 48px)`; panel padding 20-24px; gaps 12-16px
- Header: sticky, translucent white `rgb(255 255 255 / 82%)` + backdrop blur 14px, logo left, pill nav center
- Tables: 13px, row height ~44px, sticky header on `#f0f5f1`, hover row `rgb(5 150 105 / 5%)`,
  selected row `rgb(5 150 105 / 8%)`, top-3 rows get soft medal tint with a colored left edge

## Components

- Pill tabs / segmented controls (meet, round R1..R11 chips with time underneath)
- Summary cards (one hero-gradient primary card, others white)
- Silk number chip, form chips (recent finishes, top-3 highlighted), status tags (종료 / 예정 / 출전취소)
- Data grid with column toggles, sort, sticky first columns (마번/마명)
- Horse dossier drawer with tabs (과거 경주 / 주행심사 / 조교 / 기수)
- Pace board: horizontal lanes 추입→중위→선입→선행 with silk chips
- Video link opens official KRA player in a docked panel
- Brand: use the real Mapilog logo (horse symbol + "mapilog" wordmark) in every logo position

## Motion

Short (160-240ms) ease transitions, cards fade/slide up 8px on load with small stagger, hover lifts 1-2px.
Respect reduced motion.

## Rules

Use ONLY these fonts, colors, spacing, and component styles. Do not introduce other fonts, neon, purple gradients,
or new brand colors. Keep Korean copy. Keep the soft, rounded, calm feel.
