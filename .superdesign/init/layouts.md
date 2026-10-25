# Layouts

Stack: Python FastAPI server-rendered Jinja2 templates (no React/Vue, no Tailwind).
Vanilla CSS with CSS custom properties (dark default, `[data-theme="light"]` override) and vanilla JS
progressive enhancement via `data-*` hooks. Fonts: Pretendard Variable (Korean UI) + JetBrains Mono (numbers).
Mobile vs desktop is decided server-side by User-Agent: mobile uses `templates/mobile/*` + `static/css/mobile.css`.

## Desktop shell — sticky blurred header, pill nav, theme toggle, footer

### `src/horse_racing/web/templates/base.html`

```html
<!doctype html>
<html lang="ko" data-theme="dark">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
    <meta name="naver-site-verification" content="a71202c329d9767a2c3589e8637e278720be227f">
    <meta name="description" content="{% block meta_description %}한국 경마 일정과 결과, 출전마 기록과 예측 확률을 확인하는 마필로그 Mapilog{% endblock %}">
    <meta name="robots" content="{{ 'noindex,follow' if request.url.query else 'index,follow' }}">
    <link rel="canonical" href="https://mapilog.xyz{{ request.url.path }}">
    <meta property="og:type" content="website">
    <meta property="og:locale" content="ko_KR">
    <meta property="og:site_name" content="마필로그 Mapilog">
    <meta property="og:title" content="{{ self.title()|striptags }}">
    <meta property="og:description" content="{{ self.meta_description()|striptags }}">
    <meta name="twitter:card" content="summary">
    <meta name="twitter:title" content="{{ self.title()|striptags }}">
    <meta name="twitter:description" content="{{ self.meta_description()|striptags }}">
    <meta name="theme-color" content="#0a0f0d">
    <title>{% block title %}마필로그 | Mapilog 경마 분석 및 예측{% endblock %}</title>
    <link rel="icon" href="{{ url_for('static', path='/images/brand/mapilog-favicon-final.svg') }}" type="image/svg+xml">
    <link rel="icon" href="{{ url_for('static', path='/images/brand/mapilog-favicon.png') }}" type="image/png" sizes="224x224">
    <script>
      (function () {
        try {
          var theme = localStorage.getItem("hr-theme");
          if (theme === "light" || theme === "dark") {
            document.documentElement.dataset.theme = theme;
          }
        } catch (error) { /* private mode 등에서 무시 */ }
      })();
    </script>
    <link rel="preconnect" href="https://cdn.jsdelivr.net" crossorigin>
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css">
    <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@500;600;700&display=swap">
    <link rel="stylesheet" href="{{ url_for('static', path='/css/dashboard.css') }}?v=15">
    <link rel="stylesheet" href="{{ url_for('static', path='/css/insights.css') }}?v=2">
    <script src="{{ url_for('static', path='/js/dashboard.js') }}?v=15" defer></script>
    <script src="{{ url_for('static', path='/js/insights.js') }}?v=1" defer></script>
    {% block extra_head %}{% endblock %}
  </head>
  <body class="{% block body_class %}{% endblock %}">
    <header class="site-header">
      <div class="header-inner">
        <a class="brand" href="/" aria-label="마필로그 홈">
          <img class="brand-symbol brand-logo-color" src="{{ url_for('static', path='/images/brand/mapilog-symbol-color.svg') }}" alt="" aria-hidden="true">
          <img class="brand-symbol brand-logo-white" src="{{ url_for('static', path='/images/brand/mapilog-symbol-white.svg') }}" alt="" aria-hidden="true">
          <img class="brand-wordmark brand-logo-color" src="{{ url_for('static', path='/images/brand/mapilog-wordmark-color.svg') }}" alt="" aria-hidden="true">
          <img class="brand-wordmark brand-logo-white" src="{{ url_for('static', path='/images/brand/mapilog-wordmark-white.svg') }}" alt="" aria-hidden="true">
        </a>
        <nav class="site-nav" aria-label="주요 메뉴">
          <a href="/" class="{% if active_nav == 'races' %}active{% endif %}">경주</a>
          <a href="/forecast" class="{% if active_nav == 'forecast' %}active{% endif %}">미래 예측</a>
          <a href="/validation" class="{% if active_nav == 'validation' %}active{% endif %}">예측 검증</a>
          <a href="/analysis" class="{% if active_nav == 'analysis' %}active{% endif %}">경주 분석</a>
          <a href="/racecourses/jeju/distances" class="{% if active_nav == 'distances' %}active{% endif %}">거리별 분석</a>
          <a href="/predictions" class="{% if active_nav == 'predictions' %}active{% endif %}">예측 원장</a>
          <a href="/horses" class="{% if active_nav == 'horses' %}active{% endif %}">말</a>
          <a href="/jockeys" class="{% if active_nav == 'jockeys' %}active{% endif %}">기수</a>
          <a href="/trainers" class="{% if active_nav == 'trainers' %}active{% endif %}">조교사</a>
          <a href="/owners" class="{% if active_nav == 'owners' %}active{% endif %}">마주</a>
          <a href="/data-status" class="{% if active_nav == 'data-status' %}active{% endif %}">데이터</a>
        </nav>
        <div class="header-actions">
          <div class="data-state">
            <span class="live-dot" aria-hidden="true"></span>
            로컬 데이터
          </div>
          <button type="button" class="theme-toggle" data-theme-toggle aria-label="라이트 모드로 전환">
            <svg class="icon-moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
            </svg>
            <svg class="icon-sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <circle cx="12" cy="12" r="4"/>
              <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/>
            </svg>
          </button>
        </div>
      </div>
    </header>

    <main class="page-shell">
      {% block content %}{% endblock %}
    </main>

    <footer>
      <span>HORSE RACING DATA PLATFORM</span>
      <span>한국마사회 공공데이터 기반 · 로컬 분석용</span>
    </footer>
  </body>
</html>
```
### `src/horse_racing/web/static/css/dashboard.css (lines 175-357)`

```css
   Header / Nav / Footer
   -------------------------------------------------------------------------- */

.site-header {
  position: sticky;
  top: 0;
  z-index: 40;
  background: var(--header-bg);
  border-bottom: 1px solid var(--border);
  backdrop-filter: blur(14px) saturate(150%);
  -webkit-backdrop-filter: blur(14px) saturate(150%);
}

.header-inner,
.page-shell,
footer {
  width: min(1520px, calc(100% - 48px));
  margin: 0 auto;
}

.header-inner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  min-height: 68px;
}

.brand {
  display: inline-flex;
  flex-shrink: 0;
  align-items: center;
  gap: 8px;
}

.brand:focus-visible {
  outline: 2px solid var(--accent-strong);
  outline-offset: 4px;
  border-radius: 4px;
}

.brand-symbol,
.brand-wordmark {
  display: block;
  flex-shrink: 0;
  object-fit: contain;
}

.brand-symbol {
  width: 70px;
  height: 38px;
}

.brand-wordmark {
  width: 112px;
  height: 38px;
}

.brand-logo-color {
  display: none;
}

[data-theme="light"] .brand-logo-color {
  display: block;
}

[data-theme="light"] .brand-logo-white {
  display: none;
}

.site-nav {
  display: flex;
  flex: 1;
  align-items: center;
  justify-content: center;
  gap: 4px;
}

.site-nav a {
  flex-shrink: 0;
  white-space: nowrap;
  padding: 8px 15px;
  color: var(--muted);
  border-radius: 999px;
  font-size: 13px;
  font-weight: 700;
  letter-spacing: -0.02em;
  transition: color 140ms ease, background 140ms ease, box-shadow 140ms ease;
}

.site-nav a:hover {
  color: var(--ink-strong);
  background: var(--surface-3);
}

.site-nav a.active {
  color: #06251a;
  background: linear-gradient(120deg, var(--lime), #4ade80);
  box-shadow: var(--glow-accent);
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.data-state {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  color: var(--muted);
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
}

.live-dot {
  width: 7px;
  height: 7px;
  background: var(--accent);
  border-radius: 50%;
  box-shadow: 0 0 0 4px var(--accent-soft);
  animation: pulse 2.4s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% { box-shadow: 0 0 0 3px var(--accent-soft); }
  50% { box-shadow: 0 0 0 6px transparent; }
}

.theme-toggle {
  display: grid;
  width: 38px;
  height: 38px;
  padding: 0;
  color: var(--muted);
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: 999px;
  cursor: pointer;
  place-items: center;
  transition: color 140ms ease, border-color 140ms ease, transform 140ms ease;
}

.theme-toggle:hover {
  color: var(--ink-strong);
  border-color: var(--border-strong);
  transform: rotate(12deg);
}

.theme-toggle svg {
  width: 17px;
  height: 17px;
}

.theme-toggle .icon-sun { display: none; }
.theme-toggle .icon-moon { display: block; }

[data-theme="light"] .theme-toggle .icon-sun { display: block; }
[data-theme="light"] .theme-toggle .icon-moon { display: none; }

footer {
  display: flex;
  justify-content: space-between;
  padding: 26px 0 38px;
  color: var(--faint);
  border-top: 1px solid var(--border);
  font: 500 10px var(--font-mono);
  letter-spacing: 0.08em;
}

/* --------------------------------------------------------------------------
   Page shell / intro
   -------------------------------------------------------------------------- */

.page-shell {
  padding: 40px 0 64px;
}

```

## Mobile shell — sticky topbar with wordmark + BETA badge, bottom tab bar (경주 / 경주 분석 / 더비온)

### `src/horse_racing/web/templates/mobile/base.html`

```html
<!doctype html>
<html lang="ko" data-theme="dark">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
    <meta name="naver-site-verification" content="a71202c329d9767a2c3589e8637e278720be227f">
    <meta name="description" content="{% block meta_description %}한국 경마 일정과 결과, 출전마 기록과 예측 확률을 확인하는 마필로그 Mapilog{% endblock %}">
    <meta name="robots" content="{{ 'noindex,follow' if request.url.query else 'index,follow' }}">
    <link rel="canonical" href="https://mapilog.xyz{{ request.url.path }}">
    <meta property="og:type" content="website">
    <meta property="og:locale" content="ko_KR">
    <meta property="og:site_name" content="마필로그 Mapilog">
    <meta property="og:title" content="{{ self.title()|striptags }}">
    <meta property="og:description" content="{{ self.meta_description()|striptags }}">
    <meta name="twitter:card" content="summary">
    <meta name="twitter:title" content="{{ self.title()|striptags }}">
    <meta name="twitter:description" content="{{ self.meta_description()|striptags }}">
    <meta name="theme-color" content="#0a0f0d">
    <title>{% block title %}마필로그 | Mapilog 경마 분석 및 예측{% endblock %}</title>
    <script>
      (function () {
        try {
          var theme = localStorage.getItem("hr-theme");
          if (theme === "light" || theme === "dark") {
            document.documentElement.dataset.theme = theme;
          }
        } catch (error) { /* private mode 등에서 무시 */ }
      })();
    </script>
    <link rel="preconnect" href="https://cdn.jsdelivr.net" crossorigin>
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link rel="icon" href="{{ url_for('static', path='/images/brand/mapilog-favicon-final.svg') }}" type="image/svg+xml">
    <link rel="icon" href="{{ url_for('static', path='/images/brand/mapilog-favicon.png') }}" type="image/png" sizes="224x224">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css">
    <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@500;600;700&display=swap">
    <link rel="stylesheet" href="{{ url_for('static', path='/css/dashboard.css') }}?v=15">
    <link rel="stylesheet" href="{{ url_for('static', path='/css/insights.css') }}?v=2">
    <link rel="stylesheet" href="{{ url_for('static', path='/css/mobile.css') }}?v=75">
    <script src="{{ url_for('static', path='/js/dashboard.js') }}?v=15" defer></script>
    <script src="{{ url_for('static', path='/js/insights.js') }}?v=1" defer></script>
    {% block extra_head %}{% endblock %}
  </head>
  <body class="mobile-app {% block body_class %}{% endblock %}">
    <header class="mobile-topbar">
      <a class="mobile-brand" href="/" aria-label="Mapilog 경주 목록 홈">
        <img class="mobile-brand-logo mobile-brand-logo-color" src="{{ url_for('static', path='/images/brand/mapilog-wordmark-color.svg') }}" alt="Mapilog">
        <img class="mobile-brand-logo mobile-brand-logo-white" src="{{ url_for('static', path='/images/brand/mapilog-wordmark-white.svg') }}" alt="" aria-hidden="true">
        <span class="mobile-beta-badge">BETA</span>
      </a>
      <div class="mobile-topbar-actions">
        <button type="button" class="theme-toggle" data-theme-toggle aria-label="라이트 모드로 전환">
          <svg class="icon-moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
          </svg>
          <svg class="icon-sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <circle cx="12" cy="12" r="4"/>
            <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/>
          </svg>
        </button>
      </div>
    </header>
    <main class="page-shell">
      {% block content %}{% endblock %}
    </main>
    <nav class="mobile-tabbar" aria-label="모바일 주요 메뉴">
      <a href="/" {% if active_nav == 'races' %}aria-current="page"{% endif %}>경주</a>
      <a href="/analysis" {% if active_nav == 'analysis' %}aria-current="page"{% endif %}>경주 분석</a>
      <a href="https://m.kra.co.kr/comp/view/kraAppList.do" data-open-derbyon rel="noopener noreferrer" aria-label="더비온 앱 열기">더비온</a>
    </nav>
  </body>
</html>
```
### `src/horse_racing/web/static/css/mobile.css (lines 1-200)`

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
  overflow-x: clip;
}

.mobile-topbar {
  display: flex;
  position: sticky;
  top: 0;
  z-index: 50;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-height: var(--mobile-topbar-height);
  height: var(--mobile-topbar-height);
  padding: env(safe-area-inset-top) 16px 0;
  border-bottom: 1px solid var(--border);
  background: var(--header-bg);
  backdrop-filter: blur(14px) saturate(150%);
  -webkit-backdrop-filter: blur(14px) saturate(150%);
}

.mobile-brand {
  display: inline-flex;
  min-width: 0;
  height: 36px;
  align-items: center;
  border-radius: 8px;
}

.mobile-brand:focus-visible {
  outline: 2px solid var(--accent-strong);
  outline-offset: 3px;
}

.mobile-brand-logo {
  display: block;
  width: 112px;
  height: auto;
}

.mobile-beta-badge {
  align-self: flex-start;
  margin: 2px 0 0 6px;
  padding: 2px 5px;
  border: 1px solid color-mix(in srgb, var(--accent) 50%, transparent);
  border-radius: 999px;
  color: var(--accent-strong);
  background: var(--accent-soft);
  font: 800 8px/1.2 var(--font-mono);
  letter-spacing: 0.06em;
}

.mobile-brand-logo-color {
  display: none;
}

[data-theme="light"] .mobile-brand-logo-color {
  display: block;
}

[data-theme="light"] .mobile-brand-logo-white {
  display: none;
}

.mobile-topbar strong {
  min-width: 0;
  overflow: hidden;
  color: var(--ink-strong);
  font-size: 15px;
  font-weight: 800;
  letter-spacing: -0.03em;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mobile-topbar-actions {
  display: flex;
  flex-shrink: 0;
  align-items: center;
  gap: 8px;
}

.mobile-tabbar {
  display: flex;
  position: fixed;
  right: 0;
  bottom: 0;
  left: 0;
  z-index: 50;
  gap: 4px;
  padding: 8px 10px calc(8px + env(safe-area-inset-bottom));
  border-top: 1px solid var(--border);
  background: var(--header-bg);
  backdrop-filter: blur(14px) saturate(150%);
  -webkit-backdrop-filter: blur(14px) saturate(150%);
}

.mobile-tabbar a {
  flex: 1;
  display: grid;
  min-height: 40px;
  place-items: center;
  padding: 0 4px;
  color: var(--muted);
  background: transparent;
  border: 0;
  border-radius: 999px;
  font-size: 13px;
  font-weight: 700;
  white-space: nowrap;
}

.mobile-tabbar a[aria-current="page"] {
  color: var(--ink-strong);
  background: var(--accent-soft);
}

.mobile-app .page-shell {
  width: auto;
  max-width: none;
  margin: 0;
  padding: 12px 0 calc(80px + env(safe-area-inset-bottom));
  overflow-x: clip;
  overflow-y: visible;
}

.mobile-day-chrome {
  display: grid;
  position: sticky;
  top: var(--mobile-topbar-height);
  z-index: 45;
  gap: 6px;
  margin: -12px 0 16px;
  padding: 8px 16px 12px;
  border-bottom: 1px solid var(--border);
  background: var(--header-bg);
  backdrop-filter: blur(14px) saturate(150%);
  -webkit-backdrop-filter: blur(14px) saturate(150%);
}

.mobile-day-chrome .mobile-round-jump {
  margin: 0 -16px;
  padding: 2px 16px 0;
}

.mobile-weekend-bar,
.mobile-meet-bar {
  display: grid;
  gap: 6px;
}

.mobile-weekend-bar {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.mobile-meet-bar {
  position: relative;
  z-index: 2;
  grid-template-columns: repeat(auto-fit, minmax(0, 1fr));
}

```
