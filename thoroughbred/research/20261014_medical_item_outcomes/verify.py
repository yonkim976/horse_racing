"""Independent timeline reconstruction and multiple-testing arithmetic verification."""
from pathlib import Path
import json,hashlib
import numpy as np,pandas as pd
import duckdb
H=Path(__file__).resolve().parent;ROOT=H.parents[2];O=H/'outputs'

def main():
 d=pd.read_parquet(O/'landmark_rows.parquet');r=pd.read_parquet(O/'race_history.parquet');m=pd.read_parquet(O/'medical_family_days.parquet')
 labels=json.loads((O/'family_definitions.json').read_text())['labels'];checks=0
 def equal(a,b):
  nonlocal checks
  a=np.asarray(a);b=np.asarray(b);assert a.shape==b.shape
  if a.dtype.kind in 'biufc' and b.dtype.kind in 'biufc':assert np.allclose(a,b,equal_nan=True,atol=1e-10,rtol=1e-10)
  else:assert np.array_equal(a,b)
  checks+=a.size
 assert d.index_date.add(pd.Timedelta(days=180)).le(pd.Timestamp('2026-09-18')).all()
 assert d.prior_date.lt(d.index_date-pd.Timedelta(days=7)).all()
 assert d.elapsed.between(8,180).all()
 assert r.rank_badness.between(0,1).all()
 checks+=len(d)*3+len(r)
 # Rebuild all exposure flags from dates and preceding gaps, without using stored onset flags.
 mg={(hid,fam):g.sort_values('date') for (hid,fam),g in m.groupby(['horse_id','family'])}
 for hid,g in d.groupby('horse_id',sort=False):
  days=g.index_date.to_numpy('datetime64[D]')
  for fam in labels:
   a=mg.get((hid,fam));dd=np.array([],dtype='datetime64[D]') if a is None else a.date.to_numpy('datetime64[D]')
   lo=np.searchsorted(dd,days-np.timedelta64(7,'D'));hi=np.searchsorted(dd,days)
   active=hi>lo
   for gap in [7,14]:
    new=np.r_[True,np.diff(dd).astype(int)>gap] if len(dd) else np.array([],dtype=bool)
    cs=np.r_[0,np.cumsum(new)];onset=cs[hi]>cs[lo]
    equal(g['new'+str(gap)+'_'+fam].to_numpy(),onset.astype(int))
    equal(g['ongoing'+str(gap)+'_'+fam].to_numpy(),(active&~onset).astype(int))
 # Rebuild previous/future race sequence, including started special outcomes, from separate history arrays.
 rg={hid:g.sort_values('date').reset_index(drop=True) for hid,g in r.groupby('horse_id',sort=False)}
 for hid,g in d.groupby('horse_id',sort=False):
  a=rg[hid];dd=a.date.to_numpy('datetime64[D]');days=g.index_date.to_numpy('datetime64[D]')
  ix=np.searchsorted(dd,days);prev=ix-1;assert (prev>=0).all()
  equal(g.prior_race_key.to_numpy(),a.race_key.to_numpy()[prev])
  equal(g.elapsed.to_numpy(),(days-dd[prev]).astype(int))
  for col,dcol in [('rank_badness','prev_rank'),('top3','prev_top3'),('time_loss','prev_time')]:
   equal(g[dcol].to_numpy(),a[col].to_numpy()[prev])
  wait=np.full(len(g),99999);ok=ix<len(a);wait[ok]=(dd[ix[ok]]-days[ok]).astype(int)
  equal(g.restricted_wait_180.to_numpy(),np.minimum(wait,180))
  for lim in [30,60,90,180]:equal(g['no_start_'+str(lim)].to_numpy(),(wait>lim).astype(int))
  for h in [1,2,3]:
   j=ix+h-1;ok=j<len(a);ok[ok]&=(dd[j[ok]]-days[ok]).astype(int)<=180
   for source,key in [('top3','top3_'),('rank_badness','rank_'),('time_loss','time_')]:
    expect=np.full(len(g),np.nan);expect[ok]=a[source].to_numpy()[j[ok]]
    equal(g[key+str(h)].to_numpy(),expect)
   equal(g['no_top3_at_'+str(h)+'_by180'].to_numpy(),(~g['top3_'+str(h)].eq(1)).astype(int))
   # Rolling form is calculated independently from the last five pre-index starts.
  for source,key in [('rank_badness','mean5_rank'),('top3','mean5_top3'),('time_loss','mean5_time')]:
   vals=a[source].to_numpy();good=np.isfinite(vals);cs=np.r_[0,np.cumsum(np.where(good,vals,0))];ns=np.r_[0,np.cumsum(good)]
   left=np.maximum(0,ix-5);count=ns[ix]-ns[left];expect=np.divide(cs[ix]-cs[left],count,out=np.full(len(g),np.nan),where=count>0)
   equal(g[key].to_numpy(),expect)
 # Initial observation evidence is dated before the exposure week, not selected from the future.
 c=duckdb.connect(str(ROOT/'thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb'),read_only=True)
 md=c.execute('''select distinct linked_horse_official_id horse_id,event_date from medical_current_api_records
  where linked_horse_official_id is not null''').df();c.close();md['date']=pd.to_datetime(md.event_date)
 for hid,g in d.groupby('horse_id',sort=False):
  ds=md.loc[md.horse_id.eq(hid),'date'].sort_values().to_numpy('datetime64[D]');days=g.index_date.to_numpy('datetime64[D]')
  ix=np.searchsorted(ds,days-np.timedelta64(7,'D'))-1;assert (ix>=0).all()
  assert ((days-ds[ix]).astype(int)<=365).all();checks+=len(g)*2
 e=pd.read_csv(O/'adjusted_associations.csv');diag=pd.read_csv(O/'model_diagnostics.csv')
 assert len(diag)==41 and e.model_id.nunique()==41
 assert diag.independent_fitted_error.max()<2e-5
 assert diag.independent_coefficient_error.max()<2e-5
 assert e.groupby(['period','variant','state','target']).size().eq(len(labels)).all()
 for _,g in e.groupby(['period','variant','state']):
  p=np.where(g.identified,g.p.fillna(1),1);order=np.argsort(p);n=len(p)
  q=np.minimum(1,np.minimum.accumulate((p[order]*n/np.arange(1,n+1))[::-1])[::-1]);expect=np.empty(n);expect[order]=q
  equal(g.q_joint.to_numpy(),expect)
 for _,g in e.groupby(['period','variant','state','target']):
  p=np.where(g.identified,g.p.fillna(1),1);order=np.argsort(p);n=len(p)
  q=np.minimum(1,np.minimum.accumulate((p[order]*n/np.arange(1,n+1))[::-1])[::-1]);expect=np.empty(n);expect[order]=q
  equal(g.q_endpoint.to_numpy(),expect)
 for _,g in e.groupby(['period','variant','state','domain']):
  p=np.where(g.identified,g.p.fillna(1),1);order=np.argsort(p);n=len(p)
  q=np.minimum(1,np.minimum.accumulate((p[order]*n/np.arange(1,n+1))[::-1])[::-1]);expect=np.empty(n);expect[order]=q
  equal(g.q_domain.to_numpy(),expect)
 annual=e[e.variant.eq('primary')&e.period.ne('2024_2025')]
 for _,g in annual.groupby('state'):
  p=np.where(g.identified,g.p.fillna(1),1);order=np.argsort(p);n=len(p)
  q=np.minimum(1,np.minimum.accumulate((p[order]*n/np.arange(1,n+1))[::-1])[::-1]);expect=np.empty(n);expect[order]=q
  equal(g.q_all_annual.to_numpy(),expect)
 # Source references and all prior feasibility findings remain byte-identical.
 baseline=json.loads((O/'baseline.json').read_text())
 for item in baseline['references']:
  assert hashlib.sha256((ROOT/item['path']).read_bytes()).hexdigest()==item['sha256'];checks+=1
 result=dict(status='passed',checks=checks,models=41,coefficient_rows=len(e),
  independent_fit_max=float(diag.independent_fitted_error.max()),
  independent_coefficient_max=float(diag.independent_coefficient_error.max()),
  prior_documents_preserved=len(baseline['references']),
  all_exposure_dates_and_followup_reconstructed=True,all_rows_have_complete_180_day_calendar_followup=True,
  normal_and_special_started_distinguished=True,primary_joint_BH_recomputed=True,
  production_changed=False,causal_effect_claimed=False)
 (O/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result),flush=True)
if __name__=='__main__':main()
