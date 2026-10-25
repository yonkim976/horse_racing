"""Exploratory personal curves and chronological repetition, distinct from main FE model."""
from pathlib import Path
import json,math
import numpy as np,pandas as pd
from scipy.stats import t,false_discovery_control
H=Path(__file__).resolve().parent;O=H/'outputs';d=pd.read_parquet(H.parent/'20261007_sex_ability_gap/outputs/population.parquet').sort_values(['horse_id','date'])
e=pd.read_csv(O/'eligibility.csv');d=d.merge(e[e.eligible][['meet','distance_m']],on=['meet','distance_m'],validate='many_to_one')
race=d.groupby('source_key').finish.agg(['mean','size']);d=d.join(race,on='source_key');d=d[d['size'].gt(1)].copy();d['relative_time']=(d.finish-d['mean'])*d['size']/(d['size']-1)*1000/d.distance_m
rows=[];ledger=[]
def fit(g):
 n=len(g);center=g.body_weight.mean();b=(g.body_weight.to_numpy()-center)/10;cols=[np.ones(n),b,b*b];names=['intercept','body','body_squared']
 vals={'elapsed_years':(g.date-g.date.min()).dt.days.to_numpy()/365.25,'carried':g.weight.to_numpy()-54,'rating':g.rating.to_numpy()/10,'prior_finish':g.prior_finish.to_numpy()}
 for name,v in vals.items():
  miss=~np.isfinite(v)
  if miss.all():continue
  v=np.where(miss,np.median(v[~miss]),v)
  if v.std()>1e-10:cols.append((v-v.mean())/v.std());names.append(name)
  if miss.any():cols.append(miss.astype(float));names.append(name+'_missing')
 x=np.column_stack(cols);s=np.linalg.svd(x,compute_uv=False);rank=int((s>s[0]*1e-10).sum());df=n-rank
 if rank!=x.shape[1] or df<4:return dict(n=n,estimable=False,reason='rank deficient or fewer than4 residual degrees')
 pseudo=np.linalg.pinv(x,rcond=1e-10);beta=pseudo@g.relative_time.to_numpy();res=g.relative_time.to_numpy()-x@beta;leverage=np.sum(x*pseudo.T,axis=1)
 if np.max(leverage)>.999999:return dict(n=n,estimable=False,reason='near-perfect leverage')
 hc=pseudo*(res/(1-leverage))[None,:];cov=hc@hc.T;err=math.sqrt(max(cov[2,2],0));crit=t.ppf(.975,df);p=2*t.sf(abs(beta[2]/err),df) if err>0 else 1
 vertex=center-10*beta[1]/(2*beta[2]) if beta[2]>0 else np.nan;lower=beta[2]-crit*err
 inside=bool(np.isfinite(vertex) and g.body_weight.quantile(.1)<=vertex<=g.body_weight.quantile(.9));left=int((g.body_weight<vertex).sum());right=int((g.body_weight>vertex).sum());candidate=bool(inside and lower>0 and min(left,right)>=3)
 return dict(n=n,estimable=True,rank=rank,df=df,condition_number=float(s[0]/s[-1]),beta_linear=float(beta[1]),beta_quadratic=float(beta[2]),quadratic_se=err,quadratic_lower=float(lower),quadratic_upper=float(beta[2]+crit*err),curvature_p=float(p),vertex_kg=float(vertex),vertex_inside=inside,rows_below=left,rows_above=right,candidate=candidate,body_min=float(g.body_weight.min()),body_max=float(g.body_weight.max()),body_mean=float(center),body_unique=g.body_weight.nunique(),date_min=str(g.date.min()),date_max=str(g.date.max()),nuisance_names='|'.join(names[3:]))
for (meet,dist,hid),g in d.groupby(['meet','distance_m','horse_id']):
 meta=dict(meet=meet,distance_m=dist,horse_id=hid);g=g.sort_values('date');n=len(g);span=g.body_weight.max()-g.body_weight.min();unique=g.body_weight.nunique()
 ok=n>=24 and span>=20 and unique>=8;ledger.append(meta|dict(n=n,body_span=span,body_unique=unique,eligible=ok))
 if not ok:continue
 full=fit(g);cut=int(n*.6);tr=g.iloc[:cut];te=g.iloc[cut:];split_ok=len(tr)>=14 and len(te)>=10 and tr.body_weight.nunique()>=6 and te.body_weight.nunique()>=5 and tr.body_weight.max()-tr.body_weight.min()>=15 and te.body_weight.max()-te.body_weight.min()>=10
 a=fit(tr) if split_ok else dict(estimable=False,reason='split support insufficient');b=fit(te) if split_ok else dict(estimable=False,reason='split support insufficient')
 repeat=None
 if a.get('candidate',False) and b.get('estimable',False):repeat=bool(b.get('vertex_inside',False) and b['beta_quadratic']>0 and abs(a['vertex_kg']-b['vertex_kg'])<=10)
 row=meta|dict(split_supported=split_ok,repeat_within10kg=repeat)
 for prefix,ss in [('full',full),('train',a),('test',b)]:row.update({prefix+'_'+k:v for k,v in ss.items()})
 if a.get('estimable',False):assert tr.date.max()<te.date.min()
 rows.append(row)
r=pd.DataFrame(rows)
for prefix in ['full','train']:
 r[prefix+'_bh_q']=np.nan;ix=r.index[r[prefix+'_estimable'].eq(True)];r.loc[ix,prefix+'_bh_q']=false_discovery_control(r.loc[ix,prefix+'_curvature_p'].to_numpy())
r.to_csv(O/'individual_curves.csv',index=False);pd.DataFrame(ledger).to_csv(O/'individual_eligibility.csv',index=False)
full=r.full_candidate.fillna(False);train=r.train_candidate.fillna(False);rep=r.repeat_within10kg.eq(True);full_bh=full&r.full_bh_q.lt(.05);train_bh=train&r.train_bh_q.lt(.05)
summary=dict(exploratory_model='leave-one-out same-race relative seconds per1000m ~ personal body + body^2 + elapsed years + carried load + rating + prior_finish; HC3; distinct from joint horse/race FE model',same_venue_distance_horse_groups=len(ledger),eligible_groups=len(r),eligible_horses=r.horse_id.nunique(),estimable_full=int(r.full_estimable.sum()),full_candidate_groups=int(full.sum()),full_candidate_bh05_groups=int(full_bh.sum()),split_support_groups=int(r.split_supported.sum()),train_candidate_groups=int(train.sum()),train_candidate_bh05_groups=int(train_bh.sum()),train_candidates_with_test_curve=int((train&r.test_estimable.eq(True)).sum()),repeat_groups=int(rep.sum()),repeat_after_train_bh_groups=int((rep&train_bh).sum()),repeat_fraction_if_train_candidate=float(rep.sum()/train.sum()) if train.sum() else None,full_candidate_vertex_median=float(r.loc[full,'full_vertex_kg'].median()) if full.any() else None,forecast_validation=False,validated_personal_prescriptions=False,limits=['normal finisher selection','same-race relative outcome changes with field composition','personal curves differ from joint FE model','full eligibility uses observed body ranges, not a prospective screening rule','small samples and multiple comparisons','chronological repetition is conditional outcome analysis, not future record forecasting'])
(O/'individual_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n');print(json.dumps(summary,ensure_ascii=False,indent=2),flush=True)
