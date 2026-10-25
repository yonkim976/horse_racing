"""Independent post-apply checks against the verified pre-apply research backup."""
import hashlib,json,re
from pathlib import Path
import duckdb
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
CORE=ROOT/'thoroughbred/data/core_api_2010_20260929_v1'
BACKUP=CORE/'backups/20261015_before_event_name_31'
EVIDENCE=ROOT/'thoroughbred/research/20261015_training_rider_roles_followup_v1/080626_exact_event_evidence.jsonl'
def sha(p):
 with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def qi(name):
 assert re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*',name)
 return '"'+name+'"'
def main():
 c=duckdb.connect(str(CORE/'thoroughbred_core.duckdb'),read_only=True)
 c.execute('SET threads=2')
 c.execute("SET memory_limit='2GB'")
 # ATTACH does not support placeholders; this is an escaped fixed repository path.
 backup_sql_path=str(BACKUP/'thoroughbred_core.duckdb').replace("'","''")
 c.execute("ATTACH '"+backup_sql_path+"' AS before_db (READ_ONLY)")
 checks={}
 def check(name,ok,details=None):
  checks[name]={'passed':bool(ok),'details':details}
  assert ok,(name,details)
 evidence=[json.loads(s) for s in EVIDENCE.read_text().splitlines()]
 approved={r['observation_id'] for r in evidence}
 check('approved31_unique',len(approved)==31)
 old_tables=c.execute("select table_name,sql from duckdb_tables() where database_name='before_db' and not internal order by table_name").fetchall()
 dbname=c.execute('select current_database()').fetchone()[0]
 new_tables=dict(c.execute('select table_name,sql from duckdb_tables() where database_name=? and not internal',[dbname]).fetchall())
 check('only_expected_table_added',set(new_tables)-{r[0] for r in old_tables}=={'daily_training_rider_event_name_links'})
 fingerprints={}
 for name,sql in old_tables:
  check('schema_'+name,new_tables.get(name)==sql)
  if name=='source_manifests':continue
  quoted=qi(name)
  query='SELECT count(*),sum(hash(t)::HUGEINT),bit_xor(hash(t)) FROM {} t'
  old=c.execute(query.format('before_db.main.'+quoted)).fetchone()
  new=c.execute(query.format('main.'+quoted)).fetchone()
  check('unchanged_'+name,new==old,{'count':new[0]})
  fingerprints[name]={'count':new[0],'sum_hash64':str(new[1]),'xor_hash64':str(new[2])}
  print('verified table',name,flush=True)
 old_views=dict(c.execute("select view_name,sql from duckdb_views() where database_name='before_db' and not internal").fetchall())
 new_views=dict(c.execute('select view_name,sql from duckdb_views() where database_name=? and not internal',[dbname]).fetchall())
 check('same_view_inventory',old_views.keys()==new_views.keys())
 check('other81_view_definitions_unchanged',all(new_views[k]==v for k,v in old_views.items() if k!='daily_training_rider_linked'))
 old_sources=c.execute('SELECT * FROM before_db.main.source_manifests').fetchall()
 new_sources=c.execute('SELECT * FROM main.source_manifests').fetchall()
 check('source_manifest_append_only',set(old_sources).issubset(set(new_sources)) and len(new_sources)==len(old_sources)+1)
 cols=[r[0] for r in c.execute('DESCRIBE before_db.main.daily_training_rider_linked').fetchall()]
 select=','.join(qi(k) for k in cols)
 # Full old-column row fingerprints for all unapproved events, evaluated as multisets.
 c.execute('CREATE TEMP TABLE approved(observation_id VARCHAR PRIMARY KEY)')
 c.executemany('INSERT INTO approved VALUES (?)',[(k,) for k in sorted(approved)])
 def outside_fingerprint(source):
  q=f'SELECT count(*),sum(hash(t)::HUGEINT),bit_xor(hash(t)) FROM (SELECT {select} FROM {source} WHERE observation_id NOT IN (SELECT observation_id FROM approved)) t'
  return c.execute(q).fetchone()
 old=outside_fingerprint('before_db.main.daily_training_rider_linked')
 new=outside_fingerprint('main.daily_training_rider_linked')
 check('all_old_columns_outside31_unchanged',old==new,{'rows':new[0]})
 current_cols=[r[0] for r in c.execute('DESCRIBE daily_training_rider_linked').fetchall()]
 check('existing_columns_retained_in_order',current_cols[:len(cols)]==cols)
 cursor=c.execute(f'SELECT {select} FROM daily_training_rider_linked WHERE observation_id IN (SELECT observation_id FROM approved)')
 actual={r[cols.index('observation_id')]:dict(zip(cols,r)) for r in cursor.fetchall()}
 cursor=c.execute(f'SELECT {select} FROM before_db.main.daily_training_rider_linked WHERE observation_id IN (SELECT observation_id FROM approved)')
 prior={r[cols.index('observation_id')]:dict(zip(cols,r)) for r in cursor.fetchall()}
 check('exact31_approved_rows_present',actual.keys()==approved)
 allowed={'rider_name_candidate','rider_name_linked','rider_identity_status','rider_name_basis','event_verification_status','event_verification_web_rider_display_raw'}
 for key,row in actual.items():
  check('event_'+key,row['rider_id_raw']=='080626' and row['rider_name_linked']=='다비드' and row['rider_official_id_linked'] is None and row['rider_official_id_candidate'] is None and all(row[k]==prior[key][k] for k in cols if k not in allowed))
 hold=c.execute("SELECT observation_id,rider_name_linked,rider_official_id_linked,rider_identity_status FROM daily_training_rider_linked WHERE rider_identity_status='source_conflict_hold'").fetchall()
 old_hold=c.execute("SELECT observation_id,rider_name_linked,rider_official_id_linked,rider_identity_status FROM before_db.main.daily_training_rider_linked WHERE rider_identity_status='source_conflict_hold'").fetchall()
 check('Songdang_Sky_hold_unchanged',len(hold)==1 and hold==old_hold)
 status=dict(c.execute('select rider_identity_status,count(*) from daily_training_rider_linked group by 1').fetchall())
 check('expected_partition',status=={'exact_official_profile_id_name_link':1599487,'source_conflict_hold':1,'pr_no_absent':3383170,'profile_id_unmatched':190344,'exact_event_web_name_link':31},status)
 c.close()
 manifest=json.loads((CORE/'manifest.json').read_text())
 check('manifest_DB_hash',manifest['database_sha256']==sha(CORE/'thoroughbred_core.duckdb'))
 check('manifest_new_table_count',manifest['table_and_view_counts']['daily_training_rider_event_name_links']==31)
 check('manifest_source_count',manifest['table_and_view_counts']['source_manifests']==29)
 report={'all_passed':True,'check_count':len(checks),'checks':checks,'physical_table_preservation_fingerprints':fingerprints,'fingerprint_limit':'count + sum and XOR of DuckDB 64-bit row hashes; noncryptographic regression checks. Backup and input file identity separately verified using SHA256.','DB_sha256':manifest['database_sha256']}
 (HERE/'root_verification.json').write_text(json.dumps(report,ensure_ascii=False,default=str,indent=2)+'\n')
 print(json.dumps({'all_passed':True,'checks':len(checks),'status':status},ensure_ascii=False))
if __name__=='__main__':main()
