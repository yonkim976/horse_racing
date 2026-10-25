# Pages — dependency trees

## `/analysis` desktop (primary analysis workspace)
Entry: src/horse_racing/web/templates/analysis.html (extends base.html)
- templates/base.html
  - static/css/dashboard.css, static/css/insights.css, static/js/dashboard.js, static/js/insights.js
- templates/_forecast_embed.html
- templates/_analysis_pace.html
- static/css/race-analysis.css, static/css/analysis-pace.css
- static/js/race-analysis.js, static/js/analysis-pace.js

## `/analysis` + `/races/{id}` mobile
Entry: src/horse_racing/web/templates/mobile/analysis.html (extends mobile/base.html)
- templates/mobile/base.html
  - static/css/dashboard.css, static/css/insights.css, static/css/mobile.css
- static/js/mobile-analysis.js

## `/` desktop
Entry: src/horse_racing/web/templates/dashboard.html (extends base.html)
- templates/_macros.html (entry_table, silk)
- static/css/dashboard.css, static/js/dashboard.js

## `/` mobile
Entry: src/horse_racing/web/templates/mobile/home.html (extends mobile/base.html)
- static/css/mobile.css

## `/races/{id}` desktop
Entry: templates/race_detail.html
- templates/_macros.html, _section_time_tables.html, _course_records.html, _jeju_course_explorer.html, _seoul_course_explorer.html
- static/js/race-chart.js, course-explorer.js, seoul-map.js, race-video.js

## `/horses/{id}` etc.
Entry: templates/entity_detail.html, templates/entity_list.html (extend base.html)
