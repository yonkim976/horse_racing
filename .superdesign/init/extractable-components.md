# Extractable components

## SiteHeader
- Source: `src/horse_racing/web/templates/base.html`
- Category: layout
- Description: Sticky blurred desktop header with Mapilog symbol+wordmark logo, centered pill nav, "로컬 데이터" live dot, theme toggle
- Extractable props: activeItem (string, default: "races")
- Hardcoded: logo SVGs, nav labels (경주, 경주 분석, 예측 원장, 말, 기수, 조교사, 마주, 데이터), CSS

## MobileTopbar
- Source: `src/horse_racing/web/templates/mobile/base.html`
- Category: layout
- Description: Mobile sticky topbar with wordmark + BETA badge and theme toggle
- Extractable props: none
- Hardcoded: wordmark, badge

## MobileTabbar
- Source: `src/horse_racing/web/templates/mobile/base.html`
- Category: layout
- Description: Bottom tab bar 경주 / 경주 분석 / 더비온
- Extractable props: activeItem (string, default: "races")

## SiteFooter
- Source: `src/horse_racing/web/templates/base.html`
- Category: layout
- Description: Thin footer "HORSE RACING DATA PLATFORM · 한국마사회 공공데이터 기반"

## SilkChip (basic)
- Source: `templates/_macros.html` `silk()` + `.silk-number` CSS
- Description: Rounded number chip colored by KRA saddle-cloth color

## SummaryCard / Panel (basic)
- Source: `.summary-card`, `.panel` in dashboard.css
