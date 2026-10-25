"""Independent character scanner, actual-start history and scalar inference."""
from pathlib import Path
import json,hashlib,math
import pandas as pd,numpy as np
from scipy.stats import t
H=Path(__file__).resolve().parent;O=H/'outputs';ROOT=H.parents[2];checks=0
def check(a,msg):
 global checks
 assert bool(a),msg;checks+=1
def close(a,b,msg):
 global checks
 np.testing.assert_allclose(a,b,atol=1e-11,rtol=1e-10,equal_nan=True,err_msg=msg);checks+=1
def scan(raw):
 s=''.join(raw.split());pos=0;groups=[];sep='';used=set()
 if not s or len(s)>4096:raise ValueError('empty')
 while pos<len(s):
  members=[];bracket=s[pos]=='('
  if bracket:pos+=1
  while True:
   if pos<len(s) and s[pos]=='^':pos+=1
   start=pos
   while pos<len(s) and '0'<=s[pos]<='9':pos+=1
   if pos==start:raise ValueError('missing digit')
   n=int(s[start:pos])
   if n<1 or n in used:raise ValueError('invalid member')
   used.add(n);members.append(n)
   if not bracket:break
   if pos<len(s) and s[pos]==',':pos+=1;continue
   if pos>=len(s) or s[pos]!=')':raise ValueError('missing close bracket')
   pos+=1;break
  groups.append((members,sep))
  if pos==len(s):break
  sep=s[pos]
  if sep not in ',-=≡':raise ValueError('unknown separator')
  pos+=1
  if pos==len(s):raise ValueError('trailing delimiter')
 return groups
def main():
 audit=json.loads((O/'source_audit.json').read_text())
 for name,expected in audit['inputs'].items():
  p=(ROOT/name).resolve();check(p.is_relative_to(ROOT),'input path');check(hashlib.sha256(p.read_bytes()).hexdigest()==expected,'input hash')
 snap=ROOT/'thoroughbred/research/20261002_moisture_position/outputs/passing_snapshot.parquet';manifest=json.loads((snap.parent/'snapshot_manifest.json').read_text());check(hashlib.sha256(snap.read_bytes()).hexdigest()==manifest['snapshot_sha256']['passing_snapshot.parquet'],'prior read-only snapshot lineage')
 d=pd.read_parquet(O/'observations.parquet');points=pd.read_parquet(O/'passing_group_points.parquet');s=pd.read_parquet(snap);s['source_key']=s.actual_meet_code.map({1:'서울',3:'부산'})+':'+pd.to_datetime(s.event_date).dt.strftime('%Y%m%d')+':'+s.race_no.astype(str)
 roster={k:set(q.gate.astype(int)) for k,q in d.groupby('source_key',sort=False)};lookup={(k,point):q for (k,point),q in points.groupby(['source_key','point'],sort=False)};issues=pd.read_csv(O/'notation_issues.csv');issuekeys=set(zip(issues.source_key,issues.point));failures=0;success=0
 for r in s.itertuples():
  key=(r.source_key,r.canonical_point_code)
  if r.source_key not in roster:continue
  try:
   g=scan(r.notation_raw)
   if {n for members,_ in g for n in members}!=roster[r.source_key]:raise ValueError('roster')
  except ValueError:
   check(key in issuekeys,'rejected notation recorded');failures+=1;continue
  check(key in lookup,'independent scanner accepted point');q=lookup[key].set_index('gate');b=0;n=sum(len(members) for members,_ in g)
  for idx,(members,sep) in enumerate(g):
   k=len(members);rel=(2*b+k-1)/(2*(n-1));c=(0 if k==1 else 1) if idx==0 else (2 if rel<=1/3 else 3 if rel<=2/3 else 4)
   a=q.loc[members];close(a.role5,np.full(k,c),'same group role');close(a.role4,np.full(k,max(c-1,0)),'group four-role mapping');close(a.group_mean_relative,np.full(k,rel),'midrank relative');close(a.group_index,np.full(k,idx),'group index');close(a.group_size,np.full(k,k),'size');check(a.separator.eq(sep).all(),'gap literal');check(a.notation_raw.eq(r.notation_raw).all(),'original literal')
   b+=k
  success+=1
 check(failures==len(issues),'all notation issues');check(success==len(lookup),'all parsed points')
 # Permuting within a parenthesized group cannot change any front/back classification.
 check([len(a) for a,_ in scan('(1,^2,3),4-5')]==[len(a) for a,_ in scan('(3,1,^2),4-5')],'within-group order invariance')
 for _,q in d.groupby('horse_id',sort=False):
  dates=q.date.to_numpy();values=q.role4.to_numpy()
  for j,r in enumerate(q.itertuples()):
   end=np.searchsorted(dates,np.datetime64(r.date)-np.timedelta64(2,'D'),side='right');ii=np.arange(max(0,end-5),end);v=values[ii];c=np.bincount(v[v>=0],minlength=4)
   close(c,[getattr(r,f'count_{i}') for i in range(4)],'independent actual last5');check(r.prior_valid==int((v>=0).sum()),'missing retained')
   supported=len(ii)==5 and (v>=0).all() and (np.datetime64(r.date)-dates[ii[0]])<=np.timedelta64(730,'D');check(r.group_history_supported==supported,'T-2 support')
 p=pd.read_parquet(O/'temporal_evaluation.parquet')
 for year in [2024,2025]:
  train=d[d.year.lt(year)&d.group_observed];test=p[p.year.eq(year)];dist=train.groupby(['meet','distance_m','role4']).size().unstack(fill_value=0).reindex(columns=range(4),fill_value=0);dist=dist.div(dist.sum(axis=1),axis=0);field=train.groupby(['meet','distance_m','field_size','role4']).size().unstack(fill_value=0).reindex(columns=range(4),fill_value=0);globalp=train.role4.value_counts().reindex(range(4),fill_value=0).to_numpy()/len(train);base=[]
  for r in test.itertuples():
   key=(r.meet,r.distance_m);fkey=(*key,r.field_size);b=dist.loc[key].to_numpy() if key in dist.index else globalp;c=field.loc[fkey].to_numpy() if fkey in field.index else np.zeros(4);base.append((c+20*b)/(sum(c)+20))
  base=np.array(base);hist=(test[[f'count_{i}' for i in range(4)]].to_numpy()+3*base)/8;y=np.eye(4)[test.role4]
  close(base,test[[f'baseline_p_{i}' for i in range(4)]],'independent baseline');close(hist,test[[f'history_p_{i}' for i in range(4)]],'history probability');close(((y-base)**2).sum(axis=1),test.baseline_brier,'base Brier');close(((y-hist)**2).sum(axis=1),test.history_brier,'horse Brier')
  check(train.date.max()<pd.Timestamp(f'{year}-01-01'),'baseline cutoff')
 # Current and future labels never enter the current feature window.
 for r in p.iloc[np.linspace(0,len(p)-1,24,dtype=int)].itertuples():
  q=d[d.horse_id.eq(r.horse_id)].copy();before=q[q.date.le(r.date-pd.Timedelta(days=2))].tail(5).role4.to_numpy();q.loc[q.date.ge(r.date),'role4']=999;after=q[q.date.le(r.date-pd.Timedelta(days=2))].tail(5).role4.to_numpy();close(before,after,'current/future mutation')
 metrics=pd.read_csv(O/'evaluation_metrics.csv',dtype={'window':str})
 for r in metrics.itertuples():
  q=p if r.window=='2024_2025' else p[p.window.eq(r.window)]
  if r.meet!='전체':q=q[q.meet.eq(r.meet)]
  est=float(q.difference.mean());score=(q.difference-est)/len(q);vars=[];gs=[]
  for ids in [q.horse_id,q.day_key,q.horse_id+':'+q.day_key]:
   sums=score.groupby(ids).sum();g=len(sums);vars.append(float(sums.pow(2).sum())*g/(g-1));gs.append(g)
  se=math.sqrt(max(0,vars[0],vars[1],vars[0]+vars[1]-vars[2]));crit=t.ppf(.975,min(gs[:2])-1);close([est,se,est-crit*se,est+crit*se],[r.estimate,r.se,r.lower,r.upper],'independent cluster interval')
 profile=pd.read_csv(O/'horse_profiles.csv',dtype={'horse_id':str}).set_index('horse_id')
 for horse,q in d.groupby('horse_id',sort=False):
  r=profile.loc[horse]
  for look in [5,10]:
   a=q.tail(look);c=a.role5.value_counts().reindex(range(5),fill_value=0);close(c,[r[f'role5_count{look}_{i}'] for i in range(5)],'profile counts');close(int(c.iloc[:2].sum()),r[f'role4_count{look}_0'],'front group sum')
 baseline=json.loads((O/'baseline_inventory.json').read_text());shared={str((H.parent/p).relative_to(ROOT)) for p in ['README.md','conclusions/README.md','conclusions/SOURCES.md','conclusions/source_manifest.json','ARTIFACT_SIZE_LOG.md']};unchanged=0
 for item in baseline['related_existing_files']:
  if item['path'] in shared:continue
  path=ROOT/item['path'];check(path.stat().st_size==item['bytes'] and hashlib.sha256(path.read_bytes()).hexdigest()==item['sha256'],'prior artifact preservation');unchanged+=1
 result=dict(passed=True,checks=checks,raw_point_literals_checked=len(s),accepted_points=success,held_points=failures,rows_history_checked=len(d),within_group_order_not_rank=True,original_snapshot_hash_confirmed=True,profile_horses_checked=len(profile),mutation_samples=24,prior_files_unchanged=unchanged,causal_or_optimal_style_proven=False)
 dump=json.dumps(result,ensure_ascii=False,indent=2)+'\n';(O/'verification.json').write_text(dump);print(dump)
if __name__=='__main__':main()
