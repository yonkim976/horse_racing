# Components

Stack: Python FastAPI server-rendered Jinja2 templates (no React/Vue, no Tailwind).
Vanilla CSS with CSS custom properties (dark default, `[data-theme="light"]` override) and vanilla JS
progressive enhancement via `data-*` hooks. Fonts: Pretendard Variable (Korean UI) + JetBrains Mono (numbers).
Mobile vs desktop is decided server-side by User-Agent: mobile uses `templates/mobile/*` + `static/css/mobile.css`.

No component library. Shared UI = Jinja macros + CSS classes.

## Jinja macros (`entry_table`, `silk`)

### `src/horse_racing/web/templates/_macros.html`

```html
{% macro silk(number) -%}
  <span class="silk-number silk-{{ number }}">{{ number }}</span>
{%- endmacro %}

{% macro entry_table(entries) %}
  <div class="table-scroll">
    <table class="entry-table" data-sortable>
      <thead>
        <tr>
          <th>순위</th>
          <th>마번 / 마명</th>
          <th>기수</th>
          <th>조교사</th>
          <th>마주</th>
          <th>부담중량</th>
          <th>마체중</th>
          <th>레이팅</th>
          <th>기록</th>
          <th>착차</th>
          <th>단승</th>
          <th>연승</th>
        </tr>
      </thead>
      <tbody>
        {% for entry in entries %}
          <tr class="{{ entry.row_class }}">
            <td>
              <strong class="placing {% if entry.special_outcome %}special{% endif %}">
                {{ entry.finish_position }}
              </strong>
            </td>
            <td>
              <div class="horse-cell">
                {{ silk(entry.horse_number) }}
                <span>
                  <a class="entity-link" href="/horses/{{ entry.horse_id }}">
                    <strong>{{ entry.horse_name }}</strong>
                  </a>
                  <small>{{ entry.horse_meta }}</small>
                </span>
              </div>
            </td>
            <td>
              {% if entry.jockey_id %}
                <a class="entity-link" href="/jockeys/{{ entry.jockey_id }}">{{ entry.jockey_name }}</a>
              {% else %}
                {{ entry.jockey_name }}
              {% endif %}
            </td>
            <td>
              {% if entry.trainer_id %}
                <a class="entity-link" href="/trainers/{{ entry.trainer_id }}">{{ entry.trainer_name }}</a>
              {% else %}
                {{ entry.trainer_name }}
              {% endif %}
            </td>
            <td>
              {% if entry.owner_id %}
                <a class="entity-link" href="/owners/{{ entry.owner_id }}">{{ entry.owner_name }}</a>
              {% else %}
                {{ entry.owner_name }}
              {% endif %}
            </td>
            <td class="numeric">{{ entry.carried_weight }}</td>
            <td class="numeric {% if entry.weight_delta and entry.weight_delta > 0 %}delta-up{% elif entry.weight_delta and entry.weight_delta < 0 %}delta-down{% endif %}">
              {{ entry.body_weight }}
            </td>
            <td class="numeric">{{ entry.rating }}</td>
            <td class="numeric result-time">{{ entry.finish_time }}</td>
            <td class="numeric margin">{{ entry.margin }}</td>
            <td class="numeric odds">{{ entry.win_odds }}</td>
            <td class="numeric odds">{{ entry.place_odds }}</td>
          </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
{% endmacro %}
```

## Shared card / panel / chip / table styles

### `src/horse_racing/web/static/css/dashboard.css (lines 756-1010)`

```css
.chip-link,
.back-link {
  display: inline-flex;
  align-items: center;
  color: var(--ink);
  background: var(--surface-2);
  border: 1px solid var(--border);
  font-weight: 700;
  transition: border-color 140ms ease, background 140ms ease, transform 140ms ease;
}

.chip-link {
  min-height: 34px;
  padding: 0 13px;
  border-radius: 999px;
  font-size: 12px;
}

.back-link {
  min-height: 40px;
  padding: 0 16px;
  border-radius: 999px;
}

.chip-link:hover,
.back-link:hover {
  border-color: var(--accent-line);
  background: var(--surface-3);
  transform: translateY(-1px);
}

.chip-link.disabled {
  color: var(--faint);
  pointer-events: none;
  opacity: 0.6;
}

/* --------------------------------------------------------------------------
   Summary cards
   -------------------------------------------------------------------------- */

.summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
  margin-bottom: 20px;
}

.summary-grid-3 {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.summary-card {
  position: relative;
  min-height: 96px;
  padding: 18px 22px;
  overflow: hidden;
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-soft);
  transition: border-color 180ms ease, transform 180ms ease, box-shadow 180ms ease;
  animation: rise 480ms cubic-bezier(0.22, 1, 0.36, 1) both;
}

.summary-card:nth-child(1) { animation-delay: 0ms; }
.summary-card:nth-child(2) { animation-delay: 60ms; }
.summary-card:nth-child(3) { animation-delay: 120ms; }
.summary-card:nth-child(4) { animation-delay: 180ms; }

.summary-card:hover {
  border-color: var(--border-strong);
  transform: translateY(-2px);
}

.summary-card::after {
  position: absolute;
  right: -30px;
  bottom: -46px;
  width: 110px;
  height: 110px;
  content: "";
  background: radial-gradient(closest-side, var(--accent-soft), transparent);
  border-radius: 50%;
}

.summary-card.primary {
  color: #eafff5;
  background: var(--hero-bg);
  border-color: rgb(110 231 183 / 25%);
  box-shadow: var(--shadow-soft), var(--glow-accent);
}

.summary-card.primary::after {
  background: radial-gradient(closest-side, rgb(190 242 100 / 18%), transparent);
}

.summary-card span,
.summary-card small {
  display: block;
}

.summary-card span {
  color: var(--muted);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.01em;
}

.summary-card.primary span {
  color: rgb(209 250 229 / 75%);
}

.summary-card strong {
  display: inline-block;
  margin-top: 6px;
  color: var(--ink-strong);
  font: 700 32px/1 var(--font-mono);
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.05em;
}

.summary-card.primary strong {
  color: #ffffff;
  text-shadow: 0 0 24px rgb(190 242 100 / 25%);
}

.summary-card strong.rate {
  font-size: 27px;
}

.summary-card small {
  position: absolute;
  top: 20px;
  right: 20px;
  color: var(--faint);
  font: 600 9px var(--font-mono);
  letter-spacing: 0.15em;
}

.summary-card.primary small {
  color: rgb(190 242 100 / 55%);
}

/* --------------------------------------------------------------------------
   Panels
   -------------------------------------------------------------------------- */

.panel {
  overflow: hidden;
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-soft);
  animation: rise 520ms cubic-bezier(0.22, 1, 0.36, 1) both;
}

@keyframes rise {
  from {
    opacity: 0;
    transform: translateY(14px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.panel-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 74px;
  padding: 18px 22px;
  border-bottom: 1px solid var(--border);
}

.panel-heading h2 {
  margin: 0;
  color: var(--ink-strong);
  font-size: 18px;
  font-weight: 800;
  letter-spacing: -0.03em;
}

.panel-heading time,
.panel-heading > span {
  color: var(--muted);
  font: 600 12px var(--font-mono);
}

.entries-heading {
  min-height: 70px;
}

.panel-note {
  margin: 0;
  padding: 12px 22px 18px;
  color: var(--muted);
  font: 400 12px/1.5 var(--font-sans);
  border-top: 1px solid var(--border);
}

.coverage-line {
  margin: 0;
  padding: 12px 22px;
  color: var(--muted);
  background: var(--thead-bg);
  border-bottom: 1px solid var(--border);
  font-size: 12px;
}

.board-layout {
  display: grid;
  gap: 18px;
}

.race-board {
  grid-template-columns: minmax(380px, 0.42fr) minmax(0, 1fr);
  align-items: start;
}

.schedule-panel {
  position: sticky;
  top: 84px;
  max-height: calc(100vh - 104px);
  overflow: auto;
}

.schedule-panel th {
  position: sticky;
  top: 0;
  z-index: 1;
}

.entity-detail-layout {
  grid-template-columns: minmax(260px, 320px) minmax(0, 1fr);
  align-items: start;
}

.entity-history-layout {
  margin-top: 28px;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  align-items: start;
}

/* --------------------------------------------------------------------------
   Tables
   -------------------------------------------------------------------------- */

.table-scroll {
  overflow-x: auto;
}

table {
```
### `src/horse_racing/web/static/css/dashboard.css (lines 1100-1175)`

```css
  outline: none;
}

.clickable-row.selected {
  background: var(--row-selected);
}

.clickable-row.selected td:first-child {
  box-shadow: inset 3px 0 var(--accent);
}

.group-row th {
  height: 36px;
  color: var(--accent);
  background: var(--accent-soft);
  font-size: 11.5px;
  letter-spacing: 0.06em;
}

.race-number {
  color: var(--ink-strong);
  font-size: 14px;
  font-weight: 700;
  transition: color 120ms ease;
}

.race-number:hover {
  color: var(--accent);
}

.entry-table td {
  height: 56px;
}

.entry-table td.margin {
  min-width: 58px;
  color: var(--ink-strong);
  font-family: var(--font-sans);
  font-size: 16px;
  font-weight: 750;
  letter-spacing: 0.02em;
  white-space: nowrap;
}

.entry-table tbody tr {
  transition: background 130ms ease;
}

.entry-table tbody tr:hover {
  background: var(--row-hover);
}

.entry-table tr.placed-1 {
  background: var(--gold-soft);
  box-shadow: inset 3px 0 var(--gold);
}

.entry-table tr.placed-2 {
  background: var(--silver-soft);
  box-shadow: inset 3px 0 var(--silver);
}

.entry-table tr.placed-3 {
  background: var(--bronze-soft);
  box-shadow: inset 3px 0 var(--bronze);
}

.non-finisher {
  opacity: 0.55;
}

.placing {
  display: inline-grid;
  min-width: 27px;
  height: 27px;
  padding: 0 4px;
```

## Silk (saddle-cloth number) chips

### `src/horse_racing/web/static/css/dashboard.css (lines 1329-1400)`

```css
.silk-number {
  display: grid;
  width: 29px;
  height: 29px;
  flex: 0 0 auto;
  color: #fff;
  background: var(--accent-deep);
  border-radius: var(--radius-sm);
  font: 700 12px/1 var(--font-mono);
  place-items: center;
  box-shadow: 0 2px 8px rgb(0 0 0 / 25%);
}

.silk-1 { background: #f4f4f4; color: #222; border: 1px solid #c5c5c5; }
.silk-2 { background: #f4c430; color: #1a1a1a; border: 1px solid #d5a600; }
.silk-3 { background: #c0392b; color: #fff; }
.silk-4 { background: #1a1a1a; color: #fff; border: 1px solid #4b5563; }
.silk-5 { background: #1f5fbf; color: #fff; }
.silk-6 { background: #1f7a3a; color: #fff; }
.silk-7 { background: #7c2d26; color: #fff; }
.silk-8 { background: #ef7eb2; color: #30101f; }
.silk-9 { background: #6d28d9; color: #fff; }
.silk-10 { background: #38bdf8; color: #0b3b4d; }
.silk-11 {
  color: #17212b;
  background: repeating-linear-gradient(90deg, #38bdf8 0 6px, #f4f4f4 6px 10px);
  border: 1px solid #8fcde8;
}
.silk-12 {
  color: #1a1a1a;
  background: repeating-linear-gradient(90deg, #38bdf8 0 6px, #f4c430 6px 10px);
  border: 1px solid #caac36;
}
.silk-13 {
  color: #fff;
  background: repeating-linear-gradient(90deg, #38bdf8 0 6px, #c0392b 6px 10px);
  text-shadow: 0 1px 2px rgb(0 0 0 / 65%);
}
.silk-14 {
  color: #fff;
  background: repeating-linear-gradient(90deg, #38bdf8 0 6px, #1a1a1a 6px 10px);
  text-shadow: 0 1px 2px rgb(0 0 0 / 65%);
}
.silk-15 { background: #be123c; color: #fff; }
.silk-16 { background: #0f766e; color: #fff; }
.silk-17 { background: #a16207; color: #fff; }
.silk-18 { background: #334155; color: #fff; }

/* --------------------------------------------------------------------------
   Race hero
   -------------------------------------------------------------------------- */

.race-hero {
  display: flex;
  position: relative;
  overflow: hidden;
  color: #eafff5;
  background: var(--hero-bg);
}

.race-hero::after {
  position: absolute;
  top: -70px;
  right: -50px;
  width: 260px;
  height: 260px;
  content: "";
  background: radial-gradient(closest-side, rgb(190 242 100 / 12%), transparent);
  border-radius: 50%;
  pointer-events: none;
}

```
