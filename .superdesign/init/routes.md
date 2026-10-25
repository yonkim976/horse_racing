# Routes (FastAPI, `src/horse_racing/web/app.py`)

All HTML routes render Jinja templates. Desktop layout `base.html`; mobile UA gets `mobile/base.html`.

| Path | Template (desktop / mobile) | Loader | Summary |
|---|---|---|---|
| `/` | `dashboard.html` / `mobile/home.html` | `dashboard.py` | Race calendar: date picker, meet select, summary cards, daily race list (left) + selected race runners/results table (right). Mobile: date bar, meet bar, round jump chips, per-race horizontal poster cards (silk color, number, name, win %, role label). |
| `/races/{id}` | `race_detail.html` / `mobile/analysis.html` | `race_page.py` | Race detail: results, section times, dividends, steward notes. Mobile renders analysis page. |
| `/analysis` | `analysis.html` / `mobile/analysis.html` | `race_analysis.py` | Core product. Desktop: date form, meet tabs, round chips, race title, section nav (예측/비교/기록/전개/메모), embedded forecast + track pace animation, runners model table, field comparison table with checkboxes, side-by-side compare, per-horse dossier (history/trials/training/jockey tabs, video links), pace workbench, local memo. Mobile: round chips, 전력 구도 summary groups, accordion runner cards with silk gradient, pace-tendency lanes, record tabs. |
| `/running-trials/{id}` | `running_trial_detail.html` | `trial_page.py` | Running trial detail |
| `/horses`, `/jockeys`, `/trainers`, `/owners` | `entity_list.html` | `entities.py` | Searchable list |
| `/{kind}/{id}` | `entity_detail.html` | `entities.py` | Entity profile + history |
| `/predictions` | `predictions.html` | `predictions.py` | Prediction ledger |
| `/data-status` | `data_status.html` | `data_status.py` | Ingestion status |
| `/forecast`, `/validation`, `/racecourses/{c}/distances` | — | — | SCHEDULED FOR REMOVAL; do not design. |
| `/api/predictions`, `/api/analysis/export.csv` | JSON / CSV | | |
