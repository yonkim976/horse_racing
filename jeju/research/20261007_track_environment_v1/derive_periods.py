"""Derive modern-period and raw-grade diagnostics from the preserved race audit."""

import json
from collections import Counter, defaultdict
from pathlib import Path

from audit_support import BANDS, grouped, save

HERE=Path(__file__).resolve().parent
rows=json.loads((HERE/"race_support_rows.json").read_text())
bands=[]
for name,sample in (("modern_style_2019_plus",[r for r in rows if r["year"]>=2019]),
                    ("modern_complete_2019_2025",[r for r in rows if 2019<=r["year"]<=2025])):
    tab=grouped(sample,("distance_m","band"))
    dry={r["distance_m"]:r for r in tab if r["band"]=="건조"}
    for r in tab:
        r["period"]=name
        r["dry_reference_race_days"]=dry.get(r["distance_m"],{}).get("race_days",0)
        r["provisional_20_day_support"]=r["race_days"]>=20 and r["dry_reference_race_days"]>=20
    bands.extend(tab)
save("modern_period_support.json",bands)
by_grade=defaultdict(list)
for r in rows:by_grade[r["grade_raw"]].append(r)
grades=[{"grade_raw":grade,"races":len(sample),"first_date":min(r["race_date"] for r in sample),
         "last_date":max(r["race_date"] for r in sample)} for grade,sample in sorted(by_grade.items())]
fields={name:dict(sorted(Counter(r["field_n"] for r in sample).items())) for name,sample in (
    ("all_2017_plus",rows),("modern_2019_plus",[r for r in rows if r["year"]>=2019]),
    ("recent_2024_plus",[r for r in rows if r["year"]>=2024]))}
save("period_grade_diagnostics.json",{"grade_raw_periods":grades,"field_size_periods":fields,
                                      "grade_interpretation":"Observed spelling/period diagnostic only; no rule-change date or grade equivalence inferred"})
print(json.dumps({"grades":grades,"field_sizes":fields},ensure_ascii=False))
