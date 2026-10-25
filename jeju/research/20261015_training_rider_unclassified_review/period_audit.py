"""Read-only time distribution of guarded rider types; no DB mutation."""
from pathlib import Path
from collections import Counter
import csv, json, sqlite3
from datetime import date
ROOT=Path(__file__).resolve().parent
DB=ROOT.parents[1]/'data/jeju_native_core.sqlite3'
c=sqlite3.connect(DB.as_uri()+'?mode=ro',uri=True)
c.execute('PRAGMA query_only=ON')
year=Counter(); month=Counter(); unknown_year=Counter(); unknown_month=Counter(); reasons=Counter(); raw=Counter(); dates=Counter(); periods={}; duration=Counter(); staff=Counter(); horses=set()
q='''SELECT d.training_date,v.rider_type,v.rider_type_status,d.prGubun_raw,d.prNo_raw,d.duration_seconds,d.horse_id FROM daily_training_api_rows d JOIN daily_training_rider_type_values v USING(daily_training_api_row_id)'''
for day,role,status,rawrole,staffid,seconds,horse in c.execute(q):
    year[day[:4]]+=1; month[day[:7]]+=1
    if role=='미분류':
        unknown_year[day[:4]]+=1; unknown_month[day[:7]]+=1; reasons[status]+=1; raw[str(rawrole)]+=1; dates[day]+=1; duration['valid_duration' if seconds is not None else 'missing_duration']+=1; staff[str(staffid)]+=1; horses.add(horse)
for name,start,end in [('before_2017','0001-01-01','2016-12-31'),('2017_through_analysis','2017-01-01','2026-09-19'),('after_analysis','2026-09-20','9999-12-31'),('website_current_six_month_candidate','2026-04-15','2026-09-28'),('before_current_website_window','0001-01-01','2026-04-14')]:
    t=c.execute('''SELECT count(*),sum(v.rider_type='미분류'),sum(v.rider_type='미분류' AND d.duration_seconds IS NOT NULL),count(DISTINCT CASE WHEN v.rider_type='미분류' THEN d.horse_id END) FROM daily_training_api_rows d JOIN daily_training_rider_type_values v USING(daily_training_api_row_id) WHERE d.training_date BETWEEN ? AND ?''',(start,end)).fetchone()
    periods[name]=dict(zip(('total','unclassified','unclassified_with_valid_duration','unclassified_horses'),t))
def tab(total,unknown):
    return [dict(period=k,total=total[k],unclassified=unknown[k],unclassified_rate_pct=round(100*unknown[k]/total[k],3),share_of_all_unclassified_pct=round(100*unknown[k]/sum(unknown.values()),3)) for k in sorted(total)]
ys=tab(year,unknown_year); ms=tab(month,unknown_month)
for filename,rows in [('year_counts.csv',ys),('month_counts.csv',ms)]:
    with (ROOT/filename).open('x',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
result={'db':str(DB),'as_of_kst':'2026-10-15','total':sum(year.values()),'unclassified':sum(unknown_year.values()),'unclassified_pct':round(100*sum(unknown_year.values())/sum(year.values()),3),'years':ys,'top_months_by_unclassified_count':sorted(ms,key=lambda r:r['unclassified'],reverse=True)[:20],'periods':periods,'statuses':dict(reasons),'raw_roles':dict(raw),'duration':dict(duration),'unclassified_horses':len(horses),'unclassified_employee_values':len(staff),'first_unclassified_date':min(dates),'last_unclassified_date':max(dates),'monthly_data': 'month_counts.csv','boundary_days':dict(sorted(dates.items())[-15:])}
with (ROOT/'period_summary.json').open('x',encoding='utf-8') as f:json.dump(result,f,ensure_ascii=False,indent=2)
print(json.dumps(result,ensure_ascii=False,indent=2))
