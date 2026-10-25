"""Read-only, every-column comparison of all pre-refresh SQLite rows."""
from pathlib import Path
import sqlite3,json,time
ROOT=Path(__file__).resolve().parents[4]
BASE=ROOT/'jeju/research/20261017_core_refresh/baseline/jeju_native_core.sqlite3'
DB=ROOT/'jeju/data/jeju_native_core.sqlite3'
def q(n):return '"'+n.replace('"','""')+'"'
c=sqlite3.connect(DB.as_uri()+'?mode=ro',uri=True);c.execute('pragma cache_size=-65536');c.execute('ATTACH DATABASE ? AS frozen',(BASE.as_uri()+'?mode=ro',));c.execute('pragma query_only=ON')
r={};t=time.monotonic()
for (name,) in c.execute("select name from frozen.sqlite_master where type='table' and name not like 'sqlite_%'").fetchall():
 cols=[v[1] for v in c.execute('pragma frozen.table_info('+q(name)+')')]
 diff=' OR '.join('b.'+q(k)+' IS NOT m.'+q(k) for k in cols)
 n=c.execute('select count(*) from frozen.'+q(name)).fetchone()[0]
 bad=c.execute('select count(*) from frozen.'+q(name)+' b left join main.'+q(name)+' m on m.rowid=b.rowid where m.rowid IS NULL OR '+diff).fetchone()[0]
 assert bad==0,(name,bad)
 r[name]={'baseline_rows':n,'changed_or_missing_rows':bad}
 print(name,n,'preserved',flush=True)
result={'status':'passed','baseline_rows_checked':sum(x['baseline_rows'] for x in r.values()),'tables_checked':len(r),'changed_or_missing_rows':0,'seconds':round(time.monotonic()-t,3),'read_only':True,'tables':r}
Path(__file__).with_name('preserved_rows.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
print(json.dumps({k:v for k,v in result.items() if k!='tables'}))
