# Theme

## Part 1 — Token summary

Fonts: `--font-sans` "Pretendard Variable", Pretendard, "Noto Sans KR"; `--font-mono` "JetBrains Mono" (all numbers, times, odds, eyebrows).
Base size 14px, line-height 1.5. Eyebrows: mono, uppercase, letter-spaced, accent color (e.g. "RACE CALENDAR").
Headings heavy (800), tight tracking (-0.03em).

Radius: `--radius-lg` 18px (panels/cards), `--radius` 12px, `--radius-sm` 9px, pills 999px.

| token | dark (default) | light |
|---|---|---|
| --bg | #0a0f0d | #f2f5f2 |
| --surface-1/2/3 | #101714 / #151e1a / #1a2621 | #ffffff / #fbfdfb / #f0f5f1 |
| --border | rgb(155 190 170/13%) | rgb(21 45 33/11%) |
| --ink / --ink-strong | #e7efe9 / #fff | #17241d / #060c09 |
| --muted / --faint | #93a79b / #5f7268 | #5d7066 / #93a49a |
| --accent | #34d399 | #059669 |
| --accent-strong | #6ee7b7 | #047857 |
| --accent-deep | #0b5a3c | #065f46 |
| --lime | #bef264 | #65a30d |
| --gold / silver / bronze | #fbbf24 / #cbd5e1 / #d69b6b | #b45309 / #64748b / #9a5b2d |
| --red / --blue | #f87171 / #7dd3fc | #dc2626 / #0369a1 |
| --hero-bg | 135deg #0d2b1f→#123c2c | 135deg #06392a→#0e6a47 |
| --shadow | 0 16px 40px rgb(0 0 0/35%) | 0 16px 40px rgb(20 40 30/10%) |
| --shadow-soft | 0 6px 20px rgb(0 0 0/25%) | 0 6px 18px rgb(20 40 30/7%) |

Background: flat `--bg` plus two soft radial glows (green top-left, lime top-right).
Header: translucent + `backdrop-filter: blur(14px)`. Active nav pill: green→lime gradient.
Mobile extras: `--upcoming` #3b9eff (next race), role colors (축마 #4ade80, 대항 #d6d96b, 입상후보 #f2c14e, 후순위 #87928e).
Silk colors `.silk-1`..`.silk-16` follow KRA saddle-cloth colors (1 white, 2 yellow, 3 sky, 4 black, 5 blue, 6 green, 7 red/brown, 8 pink, 9 purple ...).
Breakpoint: desktop page width `min(1520px, 100% - 48px)`; mobile served by UA.

## Part 2 — Raw token source

### `src/horse_racing/web/static/css/dashboard.css (lines 1-136)`

```css
/* ==========================================================================
   한국 경마 데이터 보드 — Design System v3
   Dark-first / light-toggle, Pretendard + JetBrains Mono
   ========================================================================== */

:root {
  /* palette — dark (default) */
  --bg: #0a0f0d;
  --bg-glow-1: rgb(52 211 153 / 7%);
  --bg-glow-2: rgb(190 242 100 / 4%);
  --surface-1: #101714;
  --surface-2: #151e1a;
  --surface-3: #1a2621;
  --border: rgb(155 190 170 / 13%);
  --border-strong: rgb(155 190 170 / 26%);
  --ink: #e7efe9;
  --ink-strong: #ffffff;
  --muted: #93a79b;
  --faint: #5f7268;
  --accent: #34d399;
  --accent-strong: #6ee7b7;
  --accent-deep: #0b5a3c;
  --accent-soft: rgb(52 211 153 / 11%);
  --accent-line: rgb(52 211 153 / 32%);
  --lime: #bef264;
  --gold: #fbbf24;
  --gold-soft: rgb(251 191 36 / 10%);
  --silver: #cbd5e1;
  --silver-soft: rgb(203 213 225 / 8%);
  --bronze: #d69b6b;
  --bronze-soft: rgb(214 155 107 / 8%);
  --red: #f87171;
  --red-soft: rgb(248 113 113 / 12%);
  --blue: #7dd3fc;
  --blue-soft: rgb(125 211 252 / 11%);
  --hero-bg: linear-gradient(135deg, #0d2b1f 0%, #0f382a 55%, #123c2c 100%);
  --header-bg: rgb(10 15 13 / 78%);
  --tooltip-bg: rgb(13 33 24 / 94%);
  --track-field: #173322;
  --track-surface: #9d8c62;
  --track-edge: #d3c28d;
  --track-route: #bef264;
  --thead-bg: rgb(255 255 255 / 2.5%);
  --row-hover: rgb(52 211 153 / 5%);
  --row-selected: rgb(52 211 153 / 9%);
  --shadow: 0 16px 40px rgb(0 0 0 / 35%);
  --shadow-soft: 0 6px 20px rgb(0 0 0 / 25%);
  --glow-accent: 0 0 22px rgb(52 211 153 / 16%);
  --radius-lg: 18px;
  --radius: 12px;
  --radius-sm: 9px;
  --font-sans: "Pretendard Variable", Pretendard, "Noto Sans KR", -apple-system, sans-serif;
  --font-mono: "JetBrains Mono", "Roboto Mono", ui-monospace, monospace;
  color-scheme: dark;
}

[data-theme="light"] {
  --bg: #f2f5f2;
  --bg-glow-1: rgb(5 150 105 / 6%);
  --bg-glow-2: rgb(132 204 22 / 5%);
  --surface-1: #ffffff;
  --surface-2: #fbfdfb;
  --surface-3: #f0f5f1;
  --border: rgb(21 45 33 / 11%);
  --border-strong: rgb(21 45 33 / 22%);
  --ink: #17241d;
  --ink-strong: #060c09;
  --muted: #5d7066;
  --faint: #93a49a;
  --accent: #059669;
  --accent-strong: #047857;
  --accent-deep: #065f46;
  --accent-soft: rgb(5 150 105 / 9%);
  --accent-line: rgb(5 150 105 / 35%);
  --lime: #65a30d;
  --gold: #b45309;
  --gold-soft: rgb(217 164 34 / 14%);
  --silver: #64748b;
  --silver-soft: rgb(100 116 139 / 9%);
  --bronze: #9a5b2d;
  --bronze-soft: rgb(154 91 45 / 9%);
  --red: #dc2626;
  --red-soft: rgb(220 38 38 / 9%);
  --blue: #0369a1;
  --track-field: #dce9c0;
  --track-surface: #d8c89b;
  --track-edge: #8e7b50;
  --track-route: #047857;
  --blue-soft: rgb(3 105 161 / 9%);
  --hero-bg: linear-gradient(135deg, #06392a 0%, #0b5a3c 60%, #0e6a47 100%);
  --header-bg: rgb(255 255 255 / 82%);
  --tooltip-bg: rgb(6 45 31 / 94%);
  --thead-bg: rgb(21 45 33 / 3%);
  --row-hover: rgb(5 150 105 / 5%);
  --row-selected: rgb(5 150 105 / 8%);
  --shadow: 0 16px 40px rgb(20 40 30 / 10%);
  --shadow-soft: 0 6px 18px rgb(20 40 30 / 7%);
  --glow-accent: 0 0 22px rgb(5 150 105 / 10%);
  color-scheme: light;
}

/* --------------------------------------------------------------------------
   Base
   -------------------------------------------------------------------------- */

* {
  box-sizing: border-box;
}

html {
  scroll-behavior: smooth;
  scroll-padding-top: 90px;
}

body {
  margin: 0;
  color: var(--ink);
  background: var(--bg);
  font-family: var(--font-sans);
  font-size: 14px;
  line-height: 1.5;
  -webkit-font-smoothing: antialiased;
  transition: background 240ms ease, color 240ms ease;
}

body::before {
  position: fixed;
  inset: 0;
  z-index: -1;
  content: "";
  background:
    radial-gradient(800px 420px at 12% -8%, var(--bg-glow-1), transparent 66%),
    radial-gradient(720px 400px at 88% -4%, var(--bg-glow-2), transparent 62%);
  pointer-events: none;
}

```
### `src/horse_racing/web/static/css/mobile.css (lines 1-40)`

```css
/* 모바일 전용 레이아웃. /m 페이지에서만 로드한다. */

html {
  --mobile-topbar-height: calc(56px + env(safe-area-inset-top));
  --mobile-sticky-clearance: calc(var(--mobile-topbar-height) + 132px);
  --upcoming: #3b9eff;
  --upcoming-strong: #7ec4ff;
  --upcoming-soft: rgb(59 158 255 / 14%);
  --upcoming-line: rgb(59 158 255 / 42%);
  --role-strong-axis: #4ade80;
  --role-axis: #86df6c;
  --role-axis-candidate: #bddc63;
  --role-opponent: #d6d96b;
  --role-place-candidate: #f2c14e;
  --role-joint-axis: #4fd1c5;
  --role-mixed: #73a7ff;
  --role-candidate: #f59e42;
  --role-lower: #87928e;
  --role-missing: #66736e;
  scroll-behavior: auto;
}

[data-theme="light"] {
  --upcoming: #1570c7;
  --upcoming-strong: #0b5cad;
  --upcoming-soft: rgb(21 112 199 / 10%);
  --upcoming-line: rgb(21 112 199 / 38%);
  --role-strong-axis: #168a42;
  --role-axis: #3e7b22;
  --role-axis-candidate: #667a0a;
  --role-opponent: #756900;
  --role-place-candidate: #9a6500;
  --role-joint-axis: #087f78;
  --role-mixed: #2f66c8;
  --role-candidate: #b85d00;
  --role-lower: #58635f;
  --role-missing: #58635f;
}

body.mobile-app {
```
