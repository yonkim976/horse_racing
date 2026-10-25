"""Independent read-only full-roster check against the local Jeju DB.

No source imports, copies, exports or mutations. A single consistent read
transaction checks complete rows for eligible races in parameterized batches.
"""
import hashlib
import json
import sqlite3
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
STUDY = HERE.parent
DB = ROOT/'jeju/data/jeju_native_core.sqlite3'
RAW = ROOT/'jeju/research/20261008_horse_profile_baseline_v1/outputs_v2/source_snapshot.parquet'
LEDGER = STUDY/'audit/history_eligibility.parquet'


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(4*1024*1024),b''):h.update(block)
    return h.hexdigest()


def metadata(path):
    s=path.stat()
    return [s.st_size,s.st_mtime_ns,s.st_ino]


def main():
    before=metadata(DB)
    db_hash=sha(DB)
    source=pd.read_parquet(RAW)
    ledger=pd.read_parquet(LEDGER)
    eligible=ledger.loc[ledger.history_update_eligible.eq('True')].copy()
    assert len(eligible)==7066 and eligible.race_id.is_unique
    keys=[tuple(rid.rsplit('_',2)) for rid in eligible.race_id]
    keys=[(day,int(meet),int(race)) for day,meet,race in keys]
    fields=['api_record_id','horse_id','horse_number','race_distance_m','finish_position','finish_time_seconds']
    def canonical(rows):
        return sorted((int(a),str(h),int(n),int(d),int(r),float(t)) for a,h,n,d,r,t in rows)
    expected={rid:canonical(g[fields].itertuples(index=False,name=None))
              for rid,g in source.loc[source.race_id.isin(eligible.race_id)].groupby('race_id')}
    connection=sqlite3.connect(DB.as_uri()+'?mode=ro',uri=True)
    connection.execute('PRAGMA query_only=ON')
    connection.execute('BEGIN')
    actual={};batches=0
    try:
        for start in range(0,len(keys),200):
            part=keys[start:start+200]
            conditions=' OR '.join(['(race_date=? AND meet_code=? AND race_number=?)']*len(part))
            query=('SELECT race_date,meet_code,race_number,'+','.join(fields)+
                   ' FROM race_result_rows WHERE '+conditions)
            rows=connection.execute(query,[v for key in part for v in key]).fetchall()
            for day,meet,race,*values in rows:
                rid=f'{day}_{meet}_{race}'
                actual.setdefault(rid,[]).append(values)
            batches+=1
        connection.rollback()
    finally:connection.close()
    assert set(actual)==set(expected)
    for rid,rows in actual.items():assert canonical(rows)==expected[rid],rid
    assert sum(map(len,actual.values()))==69752
    assert metadata(DB)==before,'DB changed during read-only audit'
    assert sha(DB)==db_hash,'DB byte content changed during audit'
    result={'passed':True,'races':len(actual),'rows':sum(map(len,actual.values())),
            'parameterized_batches':batches,'full_roster_exact':True,
            'query_policy':'mode=ro; query_only=ON; single BEGIN read transaction; no exports',
            'compared_fields':fields,'db_path':str(DB.relative_to(ROOT)),
            'db_bytes':before[0],'db_sha256':db_hash,'db_metadata_before_after_equal':True,
            'db_sidecars':{suffix:{'exists':Path(str(DB)+suffix).exists(),
                           'bytes':Path(str(DB)+suffix).stat().st_size if Path(str(DB)+suffix).exists() else 0}
                           for suffix in ('-wal','-shm')},
            'source_sha256':sha(RAW),'ledger_sha256':sha(LEDGER),
            'verification_code_sha256':sha(Path(__file__))}
    with (HERE/'ROSTER_VERIFICATION.json').open('x') as stream:
        json.dump(result,stream,indent=2);stream.write('\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
