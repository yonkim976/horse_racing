"""All-runner and symmetric gate-side features with strictly chronological experiments."""
from pathlib import Path
import json,hashlib,math
import numpy as np,pandas as pd,lightgbm as lgb
from scipy.stats import t,false_discovery_control
from sklearn.metrics import roc_auc_score
H=Path(__file__).resolve().parent;R=H.parent;ROOT=H.parents[2];P=R/'20261008_field_pace_prediction';O=H/'outputs';M=H/'models'
VALUES=[f'rate{w}_{j}' for w in [5,10] for j in range(4)]+['early_mean5','early_adv_mean5','last600_mean5','last600_adv_mean5','late_mean5','late_adv_mean5','late_cond_adv_mean5','solo_rate_mean5']
STATS=['n']+[f'{v}_{s}' for v in VALUES for s in ['mean','coverage']]+['lead_sum','strong_front_n','strong_ahead_n','adv_best','faster_adv_n','faster_raw_n','faster_pair_n','faster_front_n','faster_lead_sum','supported5_n','unknown_position_n','late_fast_n']
SIDE_DIFF=['lead_sum','strong_front_n','faster_front_n','early_adv_mean5_mean','late_cond_adv_mean5_mean']
PARAMS=dict(learning_rate=.04,num_leaves=15,min_data_in_leaf=150,lambda_l2=10.,verbosity=-1,num_threads=1,seed=42,deterministic=True,force_col_wise=True)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def dump(p,obj):p.write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def features(q):
 out={f'{side}_{stat}':np.full(len(q),np.nan) for side in ['all','inner','outer'] for stat in STATS}
 for key,ix in q.groupby('source_key',sort=False).groups.items():
  ix=np.asarray(ix);g=q.loc[ix];gate=g.gate.to_numpy();n=len(g);nonself=~np.eye(n,dtype=bool);inside=gate[:,None]>gate[None,:];outside=gate[:,None]<gate[None,:];adv=g.early_adv_mean5.to_numpy();raw=g.early_mean5.to_numpy();lead=g.lead_prior5.to_numpy();strong=g.count5_0.ge(3).to_numpy();ahead=(g.count5_0+g.count5_1).ge(3).to_numpy();faster=adv[None,:]>adv[:,None];rawfast=raw[None,:]<raw[:,None];pair=np.isfinite(adv[:,None])&np.isfinite(adv[None,:]);validown=np.isfinite(adv);rawown=np.isfinite(raw)
  for side,w in [('all',nonself),('inner',inside),('outer',outside)]:
   cnt=w.sum(axis=1);out[side+'_n'][ix]=cnt
   for col in VALUES:
    v=g[col].to_numpy();finite=np.isfinite(v);known=w@finite.astype(int);total=w@np.nan_to_num(v);mean=np.divide(total,known,out=np.full(n,np.nan),where=known>0);coverage=np.divide(known,cnt,out=np.full(n,np.nan),where=cnt>0);out[side+'_'+col+'_mean'][ix]=mean;out[side+'_'+col+'_coverage'][ix]=coverage
   out[side+'_lead_sum'][ix]=w@lead;out[side+'_strong_front_n'][ix]=w@strong.astype(int);out[side+'_strong_ahead_n'][ix]=w@ahead.astype(int)
   matrix=np.where(w&np.isfinite(adv)[None,:],adv[None,:],-np.inf);best=matrix.max(axis=1);best[~np.isfinite(best)]=np.nan;out[side+'_adv_best'][ix]=best
   for suffix,vec in [('faster_adv_n',np.where(validown,(w&faster).sum(axis=1),np.nan)),('faster_raw_n',np.where(rawown,(w&rawfast).sum(axis=1),np.nan)),('faster_pair_n',(w&pair).sum(axis=1)),('faster_front_n',np.where(validown,(w&faster&strong[None,:]).sum(axis=1),np.nan)),('faster_lead_sum',np.where(validown,(w&faster)@lead,np.nan)),('supported5_n',w@g.supported5.to_numpy(int)),('unknown_position_n',w@g.valid_position5.eq(0).to_numpy(int)),('late_fast_n',w@g.late_cond_adv_mean5.gt(0).to_numpy(int))]:out[side+'_'+suffix][ix]=vec
 z=pd.DataFrame(out)
 for stat in SIDE_DIFF:z['side_gap_'+stat]=z['inner_'+stat]-z['outer_'+stat]
 return z
def ci(q,values):
 values=np.asarray(values,float);mean=values.mean();score=(values-mean)/len(values);vars=[];ns=[]
 for ids in [q.horse_id,q.date.dt.strftime('%Y-%m-%d'),q.horse_id+':'+q.date.dt.strftime('%Y-%m-%d')]:
  codes=pd.factorize(ids)[0];n=codes.max()+1;s=np.bincount(codes,weights=score);vars.append(float(s@s)*n/(n-1));ns.append(n)
 se=math.sqrt(max(0,vars[0],vars[1],vars[0]+vars[1]-vars[2]));crit=t.ppf(.975,min(ns[:2])-1)
 return dict(n=len(q),horses=q.horse_id.nunique(),dates=q.date.nunique(),estimate=float(mean),se=se,lower=float(mean-crit*se),upper=float(mean+crit*se))
def fit(q,x,cols,target,year,name):
 path=M/f'{year}_{target}_{name}.txt';assert not path.exists(),'Refusing completed model overwrite';mask=q.year.lt(year)&(q.role4.ge(0) if target=='early' else q[target].notna());y=q.loc[mask,'role4' if target=='early' else target];params=PARAMS|dict(objective='multiclass' if target=='early' else 'binary');params.update(num_class=4) if target=='early' else None
 b=lgb.train(params,lgb.Dataset(x.loc[mask,cols],label=y),num_boost_round=180);b.save_model(str(path));dump(path.with_suffix('.json'),dict(features=cols,target=target,year=year,name=name,n=int(mask.sum()),train_end=str(q.loc[mask,'date'].max().date()),training_keys_sha256=hashlib.sha256('\n'.join(q.loc[mask,'row_key']).encode()).hexdigest(),params=params,iterations=180));print('fit',path.stem,int(mask.sum()),len(cols),flush=True);return b
def prepare():
 q=pd.read_parquet(P/'outputs/feature_context.parquet');x=pd.read_parquet(P/'outputs/feature_frame.parquet');assert len(q)==159014 and q.row_key.is_unique;z=features(q);z.to_parquet(O/'additional_features.parquet',index=False);base=json.loads((P/'outputs/feature_groups.json').read_text())['F'];base=[c for c in base if c!='jockey_changed'];groups=dict(N=base,A=base+[c for c in z if c.startswith('all_')],B=base+list(z));x=pd.concat([x[base],z],axis=1)
 assert all(not any(s in c for s in ['jockey','trainer']) for c in x);dump(O/'feature_contract.json',dict(groups=groups,values=VALUES,stats=STATS,side_differences=SIDE_DIFF,base_count=len(base),additional_count=len(z.columns),row_keys_sha256=hashlib.sha256('\n'.join(q.row_key).encode()).hexdigest(),prerace_publication_timestamps_audited=False,excluded_jockey_trainer_and_change=True))
 inputs=[P/'outputs'/s for s in ['feature_context.parquet','feature_frame.parquet','feature_groups.json','early_predictions.parquet','example_cards.csv','source_audit.json','verification.json']];dump(O/'source_audit.json',dict(inputs=[dict(path=str(p.relative_to(ROOT)),bytes=p.stat().st_size,sha256=sha(p)) for p in inputs],roster_n=len(q),races=q.source_key.nunique(),horses=q.horse_id.nunique(),observed_early=int(q.role4.ge(0).sum()),data_end_by_meet=q.groupby('meet').date.max().astype(str).to_dict(),operational=False,direct_intention=False));return q,x,z,groups
def main():
 assert not (O/'additional_features.parquet').exists(),'Refusing finished study overwrite';q,x,z,groups=prepare();ep=[];lp=[];old=pd.read_parquet(P/'outputs/early_predictions.parquet').set_index('row_key');casekeys=pd.read_csv(P/'outputs/example_cards.csv').source_key.unique();cases=[]
 meta=['row_key','source_key','horse_id','horse_name','date','year','meet','distance_m','grade_bucket','gate','field_size','role4','supported5']
 for year in [2024,2025,2026]:
  te=q.year.eq(year) if year<2026 else q.source_key.isin(casekeys);r=q.loc[te,meta].copy()
  for name in (['N','A','B'] if year<2026 else ['B']):
   b=fit(q,x,groups[name],'early',year,name);pr=b.predict(x.loc[te,groups[name]],num_threads=1)
   for j in range(4):r[name+'_p'+str(j)]=pr[:,j]
  for target in ['recovery','fade']:
   rr=q.loc[te,meta].copy();rr['target']=q.loc[te,target];rr['task']=target
   for name in (['N','B'] if year<2026 else ['B']):
    b=fit(q,x,groups[name],target,year,name);rr['p_'+name]=b.predict(x.loc[te,groups[name]],num_threads=1)
   if year<2026:lp.append(rr[rr.target.notna()])
   else:r[target+'_p']=rr.p_B;r[target+'_actual']=rr.target
  if year<2026:
   r=r[r.role4.ge(0)].copy()
   for j in range(4):r['oldF_p'+str(j)]=r.row_key.map(old['F_p'+str(j)])
   ep.append(r)
  else:cases.append(r)
 ep=pd.concat(ep,ignore_index=True);lp=pd.concat(lp,ignore_index=True);ep.to_parquet(O/'early_predictions.parquet',index=False);lp.to_parquet(O/'late_predictions.parquet',index=False)
 card=pd.concat(cases,ignore_index=True).sort_values(['source_key','gate']);extra=pd.concat([q[['row_key','early_adv_mean5','early_mean5','late_cond_adv_mean5','valid_position5']+[f'count5_{j}' for j in range(4)]],z],axis=1);card=card.merge(extra,on='row_key',validate='one_to_one');card.to_csv(O/'example_cards.csv',index=False)
 pairs=[]
 for key,g in q[q.source_key.isin(casekeys)].groupby('source_key'):
  for own in g.itertuples():
   for other in g.itertuples():
    if own.row_key==other.row_key:continue
    d=dict(source_key=key,own_row_key=own.row_key,own_horse=own.horse_name,own_gate=own.gate,rival_row_key=other.row_key,rival_horse=other.horse_name,rival_gate=other.gate,side='inner' if other.gate<own.gate else 'outer',gate_difference=other.gate-own.gate)
    for col in VALUES+['lead_prior5','count5_0','valid_position5']:d[col]=getattr(other,col)
    d['rival_adv_minus_own']=other.early_adv_mean5-own.early_adv_mean5;pairs.append(d)
 pd.DataFrame(pairs).to_csv(O/'example_rival_pairs.csv',index=False);metrics(q,ep,lp,z);print('Completed bilateral field experiments',flush=True)
def metrics(q,ep,lp,z):
 rows=[];comparisons=[];cal=[];race=[]
 for window in ['2024','2025','2024_2025']:
  pp=ep if window=='2024_2025' else ep[ep.year.eq(int(window))]
  for scope in ['all','supported5']:
   g=pp[pp.supported5] if scope=='supported5' else pp;y=np.eye(4)[g.role4.to_numpy()];loss={}
   for name in ['oldF','N','A','B']:
    probs=g[[name+'_p'+str(j) for j in range(4)]].to_numpy();loss[name]=((probs-y)**2).sum(axis=1);rows.append(dict(window=window,scope=scope,model=name,n=len(g),accuracy=float((probs.argmax(axis=1)==g.role4).mean()),brier=float(loss[name].mean()),logloss=float(-np.log(probs[np.arange(len(g)),g.role4]).mean())))
   for ext,base in [('B','A'),('A','N'),('N','oldF')]:comparisons.append(dict(window=window,scope=scope,comparison=ext+'-'+base)|ci(g,loss[ext]-loss[base]))
 co=pd.DataFrame(comparisons);main=co.window.eq('2024_2025')&co.scope.eq('all');co.loc[main,'bh_q_three']=false_discovery_control(2*t.sf(abs(co.loc[main,'estimate']/co.loc[main,'se']),co.loc[main,'dates']-1));pd.DataFrame(rows).to_csv(O/'early_metrics.csv',index=False);co.to_csv(O/'early_comparisons.csv',index=False)
 for name in ['N','A','B']:
  for j in range(4):
   bins=np.minimum((ep[name+'_p'+str(j)]*10).astype(int),9)
   for bn,g in ep.groupby(bins):cal.append(dict(model=name,class_id=j,bin=int(bn),n=len(g),predicted=float(g[name+'_p'+str(j)].mean()),actual=float(g.role4.eq(j).mean())))
  for key,g in ep.groupby('source_key'):
   if len(g)!=g.field_size.iloc[0]:continue
   best=g.sort_values([name+'_p0','gate'],ascending=[False,True]).iloc[0];race.append(dict(model=name,source_key=key,n=len(g),top_first_group=bool(best.role4==0),lead_count_pred=float(g[name+'_p0'].sum()),lead_count_actual=int(g.role4.eq(0).sum())))
 pd.DataFrame(cal).to_csv(O/'early_calibration.csv',index=False);r=pd.DataFrame(race);r.to_parquet(O/'race_predictions.parquet',index=False);r['count_error']=abs(r.lead_count_pred-r.lead_count_actual);r.groupby('model').agg(races=('source_key','size'),top_first_group=('top_first_group','mean'),leader_count_mae=('count_error','mean')).reset_index().to_csv(O/'race_metrics.csv',index=False)
 zz=ep.copy();zz['distance_band']=np.where(zz.distance_m.le(1300),'<=1300',np.where(zz.distance_m.le(1600),'1400_1600','>=1700'));maxgate=q.groupby('source_key').gate.max();zz['gate_band']=pd.cut((zz.gate-1)/(zz.source_key.map(maxgate)-1),[-.001,1/3,2/3,1.001],labels=['inner','middle','outer']);sub=[]
 for col in ['meet','distance_band','gate_band','grade_bucket']:
  for label,g in zz.groupby(col,observed=True):
   y=np.eye(4)[g.role4.to_numpy()];loss={}
   for name in ['N','A','B']:
    pr=g[[name+'_p'+str(j) for j in range(4)]].to_numpy();loss[name]=((pr-y)**2).sum(axis=1);sub.append(dict(group=col,label=label,model=name,n=len(g),accuracy=float((pr.argmax(axis=1)==g.role4).mean()),brier=float(loss[name].mean())))
   sub.append(dict(group=col,label=label,model='B-A')|ci(g,loss['B']-loss['A']))
 pd.DataFrame(sub).to_csv(O/'subgroup_metrics.csv',index=False)
 late=[];diff=[];cal=[]
 for task,pp in lp.groupby('task'):
  for window in ['2024','2025','2024_2025']:
   g=pp if window=='2024_2025' else pp[pp.year.eq(int(window))];y=g.target.to_numpy()
   for name in ['N','B']:
    pr=g['p_'+name].to_numpy();lo,hi=np.quantile(pr,[.2,.8]);late.append(dict(task=task,window=window,model=name,n=len(g),prevalence=float(y.mean()),brier=float(((pr-y)**2).mean()),auc=float(roc_auc_score(y,pr)),low20_rate=float(y[pr<=lo].mean()),high20_rate=float(y[pr>=hi].mean())))
    if window=='2024_2025':
     for bn,gg in g.groupby(np.minimum((g['p_'+name]*10).astype(int),9)):cal.append(dict(task=task,model=name,bin=int(bn),n=len(gg),predicted=float(gg['p_'+name].mean()),actual=float(gg.target.mean())))
   diff.append(dict(task=task,window=window)|ci(g,(g.p_B-y)**2-(g.p_N-y)**2))
 lc=pd.DataFrame(diff);mask=lc.window.eq('2024_2025');lc.loc[mask,'bh_q_two']=false_discovery_control(2*t.sf(abs(lc.loc[mask,'estimate']/lc.loc[mask,'se']),lc.loc[mask,'dates']-1));pd.DataFrame(late).to_csv(O/'late_metrics.csv',index=False);lc.to_csv(O/'late_comparisons.csv',index=False);pd.DataFrame(cal).to_csv(O/'late_calibration.csv',index=False)
 d=q[q.row_key.isin(ep.row_key)].copy();d=d.join(z);d=d[d.count5_0.ge(3)&d.early_adv_n5.ge(3)&d.early_adv_mean5.notna()].copy();d['inner_fast_front']=d.inner_faster_front_n.gt(0);d['outer_fast_front']=d.outer_faster_front_n.gt(0);d['actual_first']=d.role4.eq(0);d['gate_band']=pd.cut((d.gate-1)/(d.source_key.map(maxgate)-1),[-.001,1/3,2/3,1.001],labels=['inner','middle','outer']);d.groupby(['gate_band','inner_fast_front','outer_fast_front'],observed=True).agg(n=('row_key','size'),horses=('horse_id','nunique'),first_group_rate=('actual_first','mean'),inner_speed_coverage=('inner_early_adv_mean5_coverage','mean'),outer_speed_coverage=('outer_early_adv_mean5_coverage','mean')).reset_index().to_csv(O/'strong_front_side_diagnostic.csv',index=False);d.to_parquet(O/'diagnostic_rows.parquet',index=False)
if __name__=='__main__':main()
