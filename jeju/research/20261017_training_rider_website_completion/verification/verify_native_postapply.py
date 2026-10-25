"""Read-only native SQLite every-column comparison with the apply-time backup."""
from pathlib import Path
import hashlib
import json
import sqlite3
import time

HERE=Path(__file__).resolve().parent
TASK=HERE.parent
ROOT=TASK.parents[2]
DB=ROOT/'jeju/data/jeju_native_core.sqlite3'
BASE=TASK/'before_website_completion.sqlite3'
OUT=HERE/'native_postapply_verification.json'
ASSIGN='daily_training_rider_type_assignments'
ALLOWED={'rider_type','type_status','website_type','website_label_raw',
         'website_jockey_name','website_source_path','website_sha256'}

def q(value):
    return '"'+value.replace('"','""')+'"'

def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(4194304),b''):
            h.update(b)
    return h.hexdigest()

assert not OUT.exists()
plan=[json.loads(s) for s in (TASK/'plan.jsonl').read_text().splitlines()]
receipt=json.loads((TASK/'application_manifest.json').read_text())
ids={r['daily_training_api_row_id'] for r in plan}
assert len(ids)==len(plan)==19885
c=sqlite3.connect(DB.as_uri()+'?mode=ro',uri=True)
c.row_factory=sqlite3.Row
c.execute('PRAGMA cache_size=-65536')
c.execute('ATTACH DATABASE ? AS frozen',(BASE.as_uri()+'?mode=ro',))
c.execute('PRAGMA query_only=ON')
started=time.monotonic()
schema_sql="SELECT type,name,tbl_name,sql FROM {}.sqlite_master ORDER BY type,name"
assert [tuple(r) for r in c.execute(schema_sql.format('main'))]==[tuple(r) for r in c.execute(schema_sql.format('frozen'))]
names=[r[0] for r in c.execute("SELECT name FROM frozen.sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
tables={}
for name in names:
    cols=[r[1] for r in c.execute('PRAGMA frozen.table_info('+q(name)+')')]
    count_old=c.execute('SELECT count(*) FROM frozen.'+q(name)).fetchone()[0]
    count_new=c.execute('SELECT count(*) FROM main.'+q(name)).fetchone()[0]
    assert count_old==count_new,(name,'count')
    checked=cols if name!=ASSIGN else [k for k in cols if k not in ALLOWED]
    diff=' OR '.join('b.'+q(k)+' IS NOT m.'+q(k) for k in checked)
    bad=c.execute('SELECT count(*) FROM frozen.'+q(name)+' b LEFT JOIN main.'+q(name)+' m ON m.rowid=b.rowid WHERE m.rowid IS NULL OR '+diff).fetchone()[0]
    assert bad==0,(name,bad)
    tables[name]={'rows':count_old,'changed_or_missing_rows':bad,'columns_checked':checked,
                  'classification_columns_excluded':sorted(ALLOWED) if name==ASSIGN else []}
    print(name,count_old,'preserved',flush=True)
cols=[r[1] for r in c.execute('PRAGMA main.table_info('+q(ASSIGN)+')')]
diff=' OR '.join('b.'+q(k)+' IS NOT m.'+q(k) for k in cols)
changed={r[0] for r in c.execute('SELECT m.daily_training_api_row_id FROM frozen.'+q(ASSIGN)+' b JOIN main.'+q(ASSIGN)+' m USING(daily_training_api_row_id) WHERE '+diff)}
assert changed==ids
for row in plan:
    key=(row['daily_training_api_row_id'],)
    old=c.execute('SELECT * FROM frozen.daily_training_rider_type_assignments WHERE daily_training_api_row_id=?',key).fetchone()
    new=c.execute('SELECT * FROM main.daily_training_rider_type_assignments WHERE daily_training_api_row_id=?',key).fetchone()
    assert dict(old)==row['old'] and dict(new)==row['new']
    view=c.execute('SELECT rider_type,rider_type_status,website_jockey_name FROM daily_training_rider_type_values WHERE daily_training_api_row_id=?',key).fetchone()
    assert tuple(view)==('주로조교','website_same_event_type',None)
remaining=c.execute("SELECT count(*) FROM daily_training_rider_type_values v JOIN daily_training_api_rows d USING(daily_training_api_row_id) WHERE d.training_date BETWEEN '2026-04-17' AND '2026-10-17' AND v.rider_type='미분류'").fetchone()[0]
assert remaining==523
integrity=c.execute('PRAGMA integrity_check').fetchone()[0]
assert integrity=='ok'
fk=c.execute('PRAGMA foreign_key_check').fetchall()
assert not fk
c.close()
actual_sha=sha(DB)
assert actual_sha==receipt['database_sha256_after']
report={'passed':True,'read_only':True,'plan_sha256':sha(TASK/'plan.jsonl'),
        'database_sha256':actual_sha,'schema_unchanged':True,
        'tables_checked':len(tables),'rows_checked':sum(v['rows'] for v in tables.values()),
        'tables':tables,'assignment_changed_rows':len(changed),
        'unexpected_assignment_changes':0,'unchanged_source_snapshot_fields':True,
        'old_and_new_plan_snapshots_exact':True,'guarded_type_values_checked':len(ids),
        'remaining_recent_unclassified':remaining,'integrity_check':integrity,
        'foreign_key_violations':len(fk),'seconds':round(time.monotonic()-started,3)}
OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:v for k,v in report.items() if k!='tables'},ensure_ascii=False))
