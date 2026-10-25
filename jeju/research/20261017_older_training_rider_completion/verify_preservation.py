"""Read-only every-column preservation and reviewed-plan verification."""
from pathlib import Path
import argparse, importlib.util, json, sqlite3, time
HERE=Path(__file__).resolve().parent
s=importlib.util.spec_from_file_location('loader',HERE/'apply_older_types.py')
l=importlib.util.module_from_spec(s);s.loader.exec_module(l)
q=lambda x:'"'+x.replace('"','""')+'"'
a=argparse.ArgumentParser();a.add_argument('--phase',choices=['initial609','full'],required=True);args=a.parse_args()
phases=['initial609'] if args.phase=='initial609' else ['initial609','full']
out=HERE/'verification'/(args.phase+'_preservation.json');l.require(not out.exists(),'Report exists')
plans=[l.paths(p)[0] for p in phases];ids=set()
for p in plans:
    for r in l.records(p):
        rid=r['daily_training_api_row_id'];l.require(rid not in ids,'Plans overlap');ids.add(rid)
c=l.connect();c.execute('ATTACH DATABASE ? AS frozen',((HERE/'before_older_completion.sqlite3').as_uri()+'?mode=ro',));c.execute('PRAGMA query_only=ON');started=time.monotonic()
schema=lambda name:[tuple(r) for r in c.execute('SELECT type,name,tbl_name,sql FROM '+name+'.sqlite_master ORDER BY type,name')]
l.require(schema('main')==schema('frozen'),'Schema changed');tables={}
for (name,) in c.execute("SELECT name FROM frozen.sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall():
    cols=[r[1] for r in c.execute('PRAGMA frozen.table_info('+q(name)+')')]
    before=c.execute('SELECT count(*) FROM frozen.'+q(name)).fetchone()[0];after=c.execute('SELECT count(*) FROM main.'+q(name)).fetchone()[0]
    l.require(before==after,'Row count changed:'+name)
    checked=[k for k in cols if name!='daily_training_rider_type_assignments' or k not in l.CHANGED]
    diff=' OR '.join('b.'+q(k)+' IS NOT m.'+q(k) for k in checked)
    bad=c.execute('SELECT count(*) FROM frozen.'+q(name)+' b LEFT JOIN main.'+q(name)+' m ON m.rowid=b.rowid WHERE m.rowid IS NULL OR '+diff).fetchone()[0]
    l.require(bad==0,'Unexpected column changes:'+name);tables[name]={'rows':before,'columns_checked':checked};print(name,before,'preserved',flush=True)
cols=[r[1] for r in c.execute('PRAGMA main.table_info(daily_training_rider_type_assignments)')]
diff=' OR '.join('b.'+q(k)+' IS NOT m.'+q(k) for k in cols)
changed={r[0] for r in c.execute('SELECT m.daily_training_api_row_id FROM frozen.daily_training_rider_type_assignments b JOIN main.daily_training_rider_type_assignments m USING(daily_training_api_row_id) WHERE '+diff)}
l.require(changed==ids,'Changed IDs differ from plans')
for p in plans:
    for r in l.records(p):
        key=(r['daily_training_api_row_id'],)
        l.require(dict(c.execute('SELECT * FROM frozen.daily_training_rider_type_assignments WHERE daily_training_api_row_id=?',key).fetchone())==r['old'],'Old plan mismatch')
        l.require(dict(c.execute('SELECT * FROM main.daily_training_rider_type_assignments WHERE daily_training_api_row_id=?',key).fetchone())==r['new'],'New plan mismatch')
        v=c.execute('SELECT rider_type,rider_type_status,website_jockey_name FROM daily_training_rider_type_values WHERE daily_training_api_row_id=?',key).fetchone()
        l.require(tuple(v)==(r['new_type'],r['new_status'],r['new']['website_jockey_name']),'Guarded values mismatch')
counts=dict(c.execute('SELECT rider_type,count(*) FROM daily_training_rider_type_assignments GROUP BY rider_type'))
older=c.execute("SELECT count(*) FROM daily_training_rider_type_assignments WHERE rider_type='미분류' AND training_date<'2026-04-17'").fetchone()[0]
recent=c.execute("SELECT count(*) FROM daily_training_rider_type_assignments WHERE rider_type='미분류' AND training_date>='2026-04-17'").fetchone()[0]
l.require(c.execute('PRAGMA integrity_check').fetchone()[0]=='ok','Integrity failure');l.require(not c.execute('PRAGMA foreign_key_check').fetchall(),'FK failure');c.close()
receipt=json.loads(l.paths(args.phase)[1].read_text());actual=l.sha(l.DB);l.require(actual==receipt['database_sha256_after'],'Receipt DB SHA mismatch')
report={'passed':True,'read_only':True,'phase':args.phase,'database_sha256':actual,'schema_unchanged':True,'tables_checked':len(tables),'rows_checked':sum(v['rows'] for v in tables.values()),'tables':tables,'changed_assignment_rows':len(ids),'unexpected_changes':0,'all_planned_old_new_values_exact':True,'guarded_values_checked':len(ids),'type_counts':counts,'remaining_older_unknown':older,'remaining_recent_unknown':recent,'integrity_check':'ok','foreign_key_violations':0,'seconds':round(time.monotonic()-started,2)}
l.write(out,report);print(json.dumps({k:v for k,v in report.items() if k!='tables'},ensure_ascii=False))
