"""Read-only population audit. No fitting; exclusive output creation."""
import bisect, hashlib, json, math, re, sqlite3
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
import numpy as np
import pandas as pd
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
DB=ROOT/'jeju/data/jeju_native_core.sqlite3'
OLD=ROOT/'jeju/research/20261007_track_environment_v1'
BANDS=['건조','양호','다습','포화','불량']
COLS=['api_record_id','race_date','meet_code','race_number','horse_id','horse_number','race_distance_m','rank_class_raw','finish_position','finish_time_seconds','track_raw','carried_weight_kg','age_at_race_raw','sex_at_race_raw','api4_3_payload_sha256']
def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(8*1024**2),b''):h.update(b)
    return h.hexdigest()
def save(p,x):
    with Path(p).open('x',encoding='utf-8') as f:json.dump(x,f,ensure_ascii=False,indent=2,allow_nan=False,default=lambda v:v.item() if isinstance(v,np.generic) else str(v))
def csv(p,df):
    with Path(p).open('x',encoding='utf-8') as f:df.to_csv(f,index=False)
def track(v):
    m=re.fullmatch(r'\s*([^()]*)\s*\((\d+(?:\.\d+)?)%\)\s*',str(v or ''))
    if not m:return None,None,None
    n=float(m[2]); label=m[1].strip()
    if not 0<n<=100 or not n.is_integer():return label,None,None
    b=BANDS[0 if n<=5 else 1 if n<=9 else 2 if n<=14 else 3 if n<=19 else 4]
    return label,n,b

def main():
    out=HERE/'audit';out.mkdir(exist_ok=False)
    stat=DB.stat();digest=sha(DB)
    con=sqlite3.connect(DB.as_uri()+'?mode=ro',uri=True);con.execute('PRAGMA query_only=ON')
    d=pd.read_sql_query('SELECT '+','.join('"'+c+'"' for c in COLS)+' FROM jeju_race_postrace_sections_quality_2026',con)
    full=pd.read_sql_query('SELECT race_date,meet_code,race_number,COUNT(*) full_n FROM race_result_rows GROUP BY race_date,meet_code,race_number',con)
    con.close()
    d['horse_id']=d.horse_id.astype(str)
    forbidden=json.loads((ROOT/'jeju/data/horse_exclusions.json').read_text())['horses']
    assert not set(d.horse_id)&{k for k,v in forbidden.items() if not v['reimport_allowed']}
    assert not d.duplicated(['race_date','meet_code','race_number','horse_id']).any()
    assert d.race_date.max()=='2026-09-19'
    d['race_id']=d.race_date+'_'+d.meet_code.astype(str)+'_'+d.race_number.astype(str)
    d['year']=d.race_date.str[:4].astype(int);d['month']=d.race_date.str[5:7].astype(int)
    d['label'],d['moisture'],d['band']=zip(*d.track_raw.map(track))
    d['valid']=d.finish_position.between(1,89)&(d.finish_time_seconds>0)&(d.race_distance_m>0)
    full['race_id']=full.race_date+'_'+full.meet_code.astype(str)+'_'+full.race_number.astype(str)
    full_n=dict(zip(full.race_id,full.full_n));ledger=[];strict=[]
    for rid,g in d[d.year>=2017].groupby('race_id',sort=True):
        n=len(g);reasons=[]
        if n<6:reasons.append('fewer_than_6_candidates')
        if n!=full_n.get(rid):reasons.append('partial_vs_stored_result_rows')
        if not g.valid.all():reasons.append('non_normal_or_nonpositive_result')
        if sorted(g.finish_position.dropna().tolist())!=list(range(1,n+1)):reasons.append('ranks_not_unique_complete_1_through_N')
        if g.horse_id.nunique()!=n:reasons.append('duplicate_horse_id')
        if g.horse_number.isna().any() or (g.horse_number<=0).any() or g.horse_number.nunique()!=n:reasons.append('invalid_or_duplicate_start_number')
        if any(g[c].nunique(dropna=False)!=1 for c in ['race_distance_m','rank_class_raw','track_raw']):reasons.append('within_race_condition_conflict')
        r=g.iloc[0]
        ledger.append(dict(race_id=rid,race_date=r.race_date,year=int(r.year),distance=int(r.race_distance_m),band=r.band or 'unknown',field_n=n,included=not reasons,reasons='|'.join(reasons),result_codes='|'.join(map(str,sorted(g.finish_position.dropna().unique())))))
        if not reasons:strict.append(rid)
    d['strict']=d.race_id.isin(strict)
    # All available valid historical rows, including before 2017, remain warm-up.
    by_hd={k:g.sort_values(['race_date','race_number','api_record_id']) for k,g in d[d.valid].groupby(['horse_id','race_distance_m'])}
    by_h={k:g.sort_values(['race_date','race_number','api_record_id']) for k,g in d[d.finish_position.between(1,89)|d.finish_position.isin([91,92])].groupby('horse_id')}
    histories={}; meta=[]
    for r in d[d.year>=2017].itertuples():
        cut=(date.fromisoformat(r.race_date)-timedelta(days=2)).isoformat()
        past=by_hd.get((r.horse_id,r.race_distance_m)); starts=by_h.get(r.horse_id)
        end=0 if past is None else bisect.bisect_right(past.race_date.to_numpy(),cut)
        ns=0 if starts is None else bisect.bisect_right(starts.race_date.to_numpy(),cut)
        chosen=[] if past is None else past.iloc[max(0,end-5):end].api_record_id.astype(int).tolist()
        last_date=None if not chosen else past.iloc[end-1].race_date
        assert last_date is None or last_date<=cut
        histories[str(r.api_record_id)]=chosen
        meta.append(dict(api_record_id=r.api_record_id,same_count=end,observed_starts=ns,days_since_start=np.nan if ns==0 else (date.fromisoformat(r.race_date)-date.fromisoformat(starts.iloc[ns-1].race_date)).days,days_since_same=np.nan if end==0 else (date.fromisoformat(r.race_date)-date.fromisoformat(last_date)).days,last_history_date=last_date,history_cutoff=cut))
    m=pd.DataFrame(meta);d=d.merge(m,on='api_record_id',how='left',validate='one_to_one')
    l=pd.DataFrame(ledger);s=d[d.strict]
    old=json.loads((OLD/'race_support_rows.json').read_text())
    old_ids={int(x) for r in old for x in r['source_api_record_ids']}
    summary=dict(database_sha256=digest,bytes=stat.st_size,mtime_ns=stat.st_mtime_ns,all_rows=len(d),all_races=d.race_id.nunique(),max_date=d.race_date.max(),candidate_rows_2017_plus=int((d.year>=2017).sum()),candidate_races_2017_plus=len(l),complete_normal_races=s.race_id.nunique(),complete_normal_rows=len(s),race_days=s.race_date.nunique(),prior_at_least4_races=int((s.groupby('race_id').same_count.apply(lambda x:(x>0).sum())>=4).sum()),previous_support_identical=set(s.api_record_id.astype(int))==old_ids,excluded_races=int((~l.included).sum()),exclusion_reasons_overlapping=dict(Counter(x for r in ledger for x in r['reasons'].split('|') if x)),track_unknown_all_rows=int(d.band.isna().sum()),track_label_mismatch_all_rows=int(((d.band.notna())&(d.band!=d.label)).sum()))
    summary['pilot_counts']=[]
    for (y,dist),g in s[s.race_distance_m.isin([1000,1110])].groupby(['year','race_distance_m']):
        summary['pilot_counts'].append(dict(year=int(y),distance=int(dist),rows=len(g),races=g.race_id.nunique(),days=g.race_date.nunique(),history_available_rows=int((g.same_count>0).sum())))
    csv(out/'race_inclusion_ledger.csv',l)
    csv(out/'exclusions_by_year_distance_band.csv',l.groupby(['year','distance','band'],dropna=False).agg(candidate_races=('race_id','size'),included_races=('included','sum')).reset_index())
    csv(out/'exclusions_by_start_number.csv',d[d.year>=2017].groupby(['race_distance_m','horse_number'],dropna=False).agg(candidate_rows=('api_record_id','size'),included_rows=('strict','sum')).reset_index())
    csv(out/'result_codes.csv',d[d.year>=2017].groupby(['race_distance_m','finish_position'],dropna=False).size().reset_index(name='rows'))
    csv(out/'track_inventory.csv',d.groupby(['year','track_raw','label','moisture','band'],dropna=False).size().reset_index(name='rows'))
    csv(out/'distance_band_support.csv',s.groupby(['race_distance_m','band'],dropna=False).agg(races=('race_id','nunique'),days=('race_date','nunique'),rows=('api_record_id','size')).reset_index())
    csv(out/'source_rows.csv',d);save(out/'history_ids.json',histories)
    assert summary['previous_support_identical'];assert (summary['complete_normal_races'],summary['complete_normal_rows'],summary['prior_at_least4_races'])==(5332,53341,5193)
    assert (DB.stat().st_size,DB.stat().st_mtime_ns)==(stat.st_size,stat.st_mtime_ns) and sha(DB)==digest
    save(out/'summary.json',summary)
    refs=[ROOT/'jeju/AGENTS.md',ROOT/'jeju/docs/RESTART_PLAN_20260928.md',ROOT/'jeju/data/horse_exclusions.json']
    for folder in [ROOT/'jeju/research/20261007_foundation_v1',OLD]:refs.extend(p for p in folder.iterdir() if p.is_file())
    refs.extend(ROOT/'thoroughbred/research/conclusions'/n for n in ['01_TRACK_MOISTURE.md','03_GATE_POSITION.md','04_JOINT_CORRECTION.md','22_SEASONAL_SAME_MOISTURE.md','23_MONTHLY_SAME_MOISTURE.md','24_ERA_RECORD_TRENDS.md'])
    refs.extend(p for p in (ROOT/'jeju/models').rglob('*') if p.is_file())
    refs.append(HERE/'audit.py')
    save(out/'reference_manifest.json',[dict(path=str(p),sha256=sha(p),bytes=p.stat().st_size,access='read_only_reference' if not p.is_relative_to(HERE) else 'new_research_code') for p in refs])
    print(json.dumps(summary,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
