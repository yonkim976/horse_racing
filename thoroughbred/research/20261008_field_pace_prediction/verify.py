"""Independent SQL, scalar, coefficient and tree-path verification; no refitting predictions."""
from pathlib import Path
import json,hashlib,gzip,math,warnings
import numpy as np,pandas as pd,duckdb,lightgbm as lgb
from scipy.stats import t,rankdata
import data
warnings.filterwarnings('ignore',category=pd.errors.PerformanceWarning)
H=data.H;O=data.O;ROOT=data.ROOT;checks=0;details={}
def check(ok,label,n=1):
 global checks
 assert bool(ok),label
 checks+=n
def close(a,b,label,tol=1e-9):
 a=np.asarray(a,float);b=np.asarray(b,float)
 check(a.shape==b.shape,label+' shape');check(np.allclose(a,b,atol=tol,rtol=tol,equal_nan=True),label,a.size)
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def cluster(q,v):
 v=np.asarray(v);est=v.mean();score=(v-est)/len(v);variances=[];ns=[]
 for ids in [q.horse_id,q.date.dt.strftime('%Y-%m-%d'),q.horse_id+':'+q.date.dt.strftime('%Y-%m-%d')]:
  sums={}
  for k,s in zip(ids,score):sums[k]=sums.get(k,0)+s
  n=len(sums);ns.append(n);variances.append(sum(s*s for s in sums.values())*n/(n-1))
 se=math.sqrt(max(0,variances[0],variances[1],variances[0]+variances[1]-variances[2]));crit=t.ppf(.975,min(ns[:2])-1)
 return np.array([est,se,est-crit*se,est+crit*se])
def bh(p):
 p=np.asarray(p);order=np.argsort(p);a=p[order]*len(p)/np.arange(1,len(p)+1);a=np.minimum.accumulate(a[::-1])[::-1];out=np.empty_like(a);out[order]=np.minimum(a,1);return out
def tree_value(tree,row):
 while 'leaf_value' not in tree:
  v=row[tree['split_feature']];check(tree['decision_type']=='<=','numeric tree split')
  missing=np.isnan(v) or (tree.get('missing_type')=='Zero' and v==0)
  left=tree['default_left'] if missing else v<=tree['threshold'];tree=tree['left_child'] if left else tree['right_child']
 return tree['leaf_value']
def main():
 a=pd.read_parquet(O/'observations.parquet');q=pd.read_parquet(O/'feature_context.parquet');x=pd.read_parquet(O/'feature_frame.parquet');audit=json.loads((O/'source_audit.json').read_text());groups=json.loads((O/'feature_groups.json').read_text())
 for r in audit['inputs']:check(digest(ROOT/r['path'])==r['sha256'],'source hash '+r['path'])
 check(len(q)==len(a)==159014 and q.row_key.is_unique,'full roster');check(q.source_key.nunique()==14636,'race count');check(q.horse_id.nunique()==12516,'horse count')
 close(q.groupby('source_key').size().to_numpy(),q.groupby('source_key').field_size.first().to_numpy(),'all actual runners retained')
 check(q.row_key.equals(a.row_key),'stable row order');check((q.history_last.isna()|(q.history_last<=q.date-pd.Timedelta(days=2))).all(),'horse cutoff',len(q))
 for filename,g in a.groupby('source_file'):
  with gzip.open(ROOT/filename,'rt') as f:raw=json.load(f)['response']['body']['items']['item']
  for z in g.itertuples():
   r=raw[z.source_item_index]
   check(str(r['hrNo']).zfill(7)==z.horse_id and int(r['chulNo'])==z.gate and str(r['rcDate'])==z.date.strftime('%Y%m%d'),'raw row identity')
   for kind,key in [('jockey','jkNo'),('trainer','trNo')]:
    s=str(r.get(key,'')).strip();ident=s if s.isdigit() and int(s)>0 else '';check(getattr(z,kind+'_id')==ident,'raw entity')
   close([z.age_current],[float(r['age']) if float(r.get('age',0))>0 else np.nan],'raw age')
 rec=np.where(a.g3f_complete&a.normal_outcome,((a.g3f_p>=.5)&((a.g3f_p-a.finish_p)>=.25)).astype(float),np.nan);fade=np.where(a.group_observed&a.normal_outcome,((a.role4<=1)&((a.finish_p-a.group_mean_relative)>=.30)).astype(float),np.nan)
 close(a.recovery,rec,'recovery definition');close(a.fade,fade,'fade definition')
 s=pd.read_parquet(O/'section_observations.parquet');close(s.early+s.middle1+s.middle2+s.late,s.finish,'four segment sum',1e-8)
 env=np.load(H/'models/environment_models.npz');meta=json.loads((H/'models/environment_models.json').read_text());p=pd.read_parquet(data.INPUTS[2]);check(s.row_key.equals(p.row_key),'section order')
 matrices=[]
 for conditional in [False,True]:
  cols=[((p.meet==v)&(p.distance_m==d)).astype(float).to_numpy() for v in ['서울','부산'] for d in data.DIST]+[(p.date.dt.month==m).astype(float).to_numpy() for m in range(1,13)]+[p.moisture.to_numpy(),p.moisture.to_numpy()**2]
  if conditional:cols +=[(p.grade==g).astype(float).to_numpy() for g in data.GRADES]+[p[c].to_numpy() for c in ['early','rating','age','weight']]+[p.middle1.to_numpy()*1000/(p.distance_m.to_numpy()-800)]
  matrices.append(np.column_stack(cols))
 for year in range(2019,2027):
  tr=p.year.to_numpy()<year;te=p.year.to_numpy()==year;check(p.loc[tr,'date'].max().year<year,'annual environment cutoff')
  for k,kind in enumerate(['base','conditional']):
   sp={v:env[f'{year}_{kind}_{v}'] for v in ['medians','means','sds','beta','intercept']};xx=matrices[k];filled=np.where(np.isfinite(xx[tr]),xx[tr],sp['medians']);z=(filled-sp['means'])/sp['sds'];yy=p.loc[tr,['early','last600','late']].to_numpy() if k==0 else p.loc[tr,'late'].to_numpy()[:,None];coef=sp['beta'] if k==0 else sp['beta'][None,:]
   close(z.T@(z@coef.T+sp['intercept']-yy)+10*coef.T,np.zeros_like(coef.T),'ridge normal equations',1e-5)
   zt=(np.where(np.isfinite(xx[te]),xx[te],sp['medians'])-sp['means'])/sp['sds'];pred=zt@coef.T+sp['intercept'];res=pred-(p.loc[te,['early','last600','late']].to_numpy() if k==0 else p.loc[te,'late'].to_numpy()[:,None]);actual=s.loc[te,['early_adv','last600_adv','late_adv']].to_numpy() if k==0 else s.loc[te,['late_cond_adv']].to_numpy();close(res,actual,'annual residuals')
 check(s.loc[s.year.eq(2018),['early_adv','last600_adv','late_adv','late_cond_adv']].isna().all().all(),'first year residuals missing')
 # SQL uses actual roster row numbers and conditional validity, never a valid-record-only window.
 db=duckdb.connect();aa=a.copy();aa['solo_rate']=np.where(aa.group_observed,aa.role5.eq(0).astype(float),np.nan);db.register('a',aa)
 db.execute('CREATE TEMP TABLE roster AS SELECT *, row_number() OVER(PARTITION BY horse_id ORDER BY date) rn FROM a')
 for window in [5,10]:
  select=['c.row_key','max(c.rn)-1 past_total','count(h.row_key) slots','sum(CASE WHEN date_diff(\'day\',h.date,c.date) BETWEEN 2 AND 730 THEN 1 ELSE 0 END) fresh']
  for name in data.HISTORY_VALUES:
   val=f'CASE WHEN date_diff(\'day\',h.date,c.date) BETWEEN 2 AND 730 THEN h."{name}" ELSE NULL END';select +=[f'count({val}) "{name}_n{window}"',f'avg({val}) "{name}_mean{window}"']
  for j in range(4):select.append(f'sum(CASE WHEN date_diff(\'day\',h.date,c.date) BETWEEN 2 AND 730 AND h.role4={j} THEN 1 ELSE 0 END) "count{window}_{j}"')
  sql='SELECT '+','.join(select)+f' FROM roster c LEFT JOIN roster h ON c.horse_id=h.horse_id AND h.rn BETWEEN c.rn-{window} AND c.rn-1 GROUP BY c.row_key';out=db.execute(sql).df().set_index('row_key').loc[q.row_key]
  for col in ['past_total']+[f'{v}_{metric}{window}' for v in data.HISTORY_VALUES for metric in ['n','mean']]+[f'count{window}_{j}' for j in range(4)]:close(out[col],q[col],'SQL history '+col)
  close(out.slots,q[f'slots{window}'],'SQL actual slots');close(out.fresh,q[f'fresh_slots{window}'],'SQL fresh slots')
  counts=out[[f'count{window}_{j}' for j in range(4)]].to_numpy();valid=counts.sum(axis=1);close(valid,q[f'valid_position{window}'],'SQL valid position');close((counts[:,0]+1)/(valid+4),q[f'lead_prior{window}'],'SQL lead prior')
  for j in range(4):close(np.divide(counts[:,j],valid,out=np.full(len(q),np.nan),where=valid>0),q[f'rate{window}_{j}'],'SQL position rate')
 # Scalar independent date-range/entity lookups, including multiple same-day races.
 rng=np.random.default_rng(728);sample=np.unique(np.r_[rng.choice(len(q),512,replace=False),np.flatnonzero(q.past_total.eq(0))[:10]])
 for kind in ['jockey','trainer']:
  check((q[kind+'_history_last'].isna()|(q[kind+'_history_last']<=q.date-pd.Timedelta(days=2))).all(),'entity cutoff',len(q))
  for ix in sample:
   row=q.iloc[ix];ident=row[kind+'_id'];actual=row[[kind+'_'+v for v in ['history_n','lead_rate','conditional_front','roster_n']]].to_numpy(float)
   if ident=='':close(actual,[np.nan]*4,'unknown entity');continue
   g=q[(q[kind+'_id']==ident)&q.date.between(row.date-pd.Timedelta(days=365),row.date-pd.Timedelta(days=2))];seen=g[g.group_observed];n=len(seen);lead=seen.role4.eq(0).astype(float);close(actual,[n,(lead.sum()+5)/(n+20),(lead-seen.lead_prior5).sum()/(n+20),len(g)],'scalar entity')
 for key,g in q.groupby('source_key'):
  for col in data.FIELD_BASE:
   val=g[col].to_numpy();known=np.isfinite(val);count=known.sum()-known;total=np.nansum(val)-np.nan_to_num(val);mean=np.divide(total,count,out=np.full(len(g),np.nan),where=count>0)
   close(mean,g['field_other_'+col],'field leave self out');close(val-mean,g['field_gap_'+col],'field gap');close(count/(len(g)-1),g['field_coverage_'+col],'field coverage')
  gate=g.gate.to_numpy();prior=g.lead_prior5.to_numpy();close([sum(prior[gate<v]) for v in gate],g.field_inner_front_sum,'inner rivals');close(prior.sum()-prior,g.field_lead_sum_other,'other lead sums');strong=(g.count5_0>=3).astype(int);close(strong.sum()-strong,g.field_strong_front_other,'other strong counts')
  for col,ascending in [('early_mean5',True),('early_adv_mean5',False)]:
   val=g[col].to_numpy();mask=np.isfinite(val);rank=np.full(len(g),np.nan)
   if mask.sum()>1:rank[mask]=(rankdata(val[mask] if ascending else -val[mask])-1)/(mask.sum()-1)
   close(rank,g['field_rank_'+col],'opponent tied ranks')
 for small,big in [('P','S'),('S','F'),('F','J')]:check(set(groups[small])<set(groups[big]),'nested features')
 forbidden={'role4','role5','finish_p','early','last600','late','rating','recovery','fade','horse_id','jockey_id','trainer_id','moisture','body_weight','weight'};check(not forbidden.intersection(x.columns),'no current target/result predictors')
 # Metamorphic future/current result intervention: cutoff features must stay identical.
 for day in [pd.Timestamp('2024-01-06'),pd.Timestamp('2025-06-01')]:
  z=a.copy();mask=z.date.ge(day);z.loc[mask,'role4']=3-z.loc[mask,'role4'];z.loc[mask,'role5']=0
  for c in data.HISTORY_VALUES:
   if c!='solo_rate':z.loc[mask,c]=rng.normal(size=mask.sum())
  z['group_observed']=z.role4.ge(0);fresh=data.field_features(data.entities(data.histories(z)));xx,_=data.features(fresh);before=q.date.le(day);close(xx.loc[before,x.columns],x.loc[before],'future/current outcome intervention')
 ep=pd.read_parquet(O/'early_predictions.parquet');lp=pd.read_parquet(O/'late_predictions.parquet');cards=pd.read_csv(O/'example_cards.csv',dtype={'horse_id':str});loss={}
 for name in ['B','H','P','S','F','J']:
  probs=ep[[name+'_p'+str(j) for j in range(4)]].to_numpy();close(probs.sum(axis=1),np.ones(len(ep)),'probability sum');check((probs>=0).all() and (probs<=1).all(),'probability range');loss[name]=((probs-np.eye(4)[ep.role4.to_numpy()])**2).sum(axis=1)
 metrics=pd.read_csv(O/'early_metrics.csv')
 for z in metrics.itertuples():
  mask=ep.grade_bucket.eq(z.window.split(':')[1]) if z.window.startswith('grade:') else (np.ones(len(ep),bool) if z.window=='2024_2025' else ep.year.eq(int(z.window)))
  if z.scope=='supported5':mask=mask&ep.supported5
  g=ep.loc[mask];pr=g[[z.model+'_p'+str(j) for j in range(4)]].to_numpy();y=g.role4.to_numpy();close([z.brier,z.accuracy,z.logloss],[np.mean(loss[z.model][mask]),np.mean(pr.argmax(axis=1)==y),-np.mean(np.log(pr[np.arange(len(g)),y]))],'independent early metrics');check(len(g)==z.n,'metric count')
 comps=pd.read_csv(O/'early_comparisons.csv')
 for z in comps.itertuples():
  mask=ep.grade_bucket.eq(z.window.split(':')[1]) if z.window.startswith('grade:') else (np.ones(len(ep),bool) if z.window=='2024_2025' else ep.year.eq(int(z.window)))
  if z.scope=='supported5':mask=mask&ep.supported5
  ext,base=z.comparison.split('-');close(cluster(ep.loc[mask],(loss[ext]-loss[base])[mask]),[z.estimate,z.se,z.lower,z.upper],'independent cluster CI')
 zz=comps[comps.window.eq('2024_2025')&comps.scope.eq('all')];close(bh(2*t.sf(abs(zz.estimate/zz.se),zz.dates-1)),zz.bh_q_four_comparisons,'BH four')
 old=pd.read_parquet(data.R/'20261008_passing_group_style/outputs/temporal_predictions.parquet') if (data.R/'20261008_passing_group_style/outputs/temporal_predictions.parquet').exists() else None
 check(ep.supported5.sum()==24613,'28A common support')
 for z in pd.read_csv(O/'late_metrics.csv').itertuples():
  g=lp[lp.task.eq(z.task)];g=g if z.window=='2024_2025' else g[g.year.eq(int(z.window))];pr=g['p_'+z.model].to_numpy();y=g.target.to_numpy();pos=y==1;n1=pos.sum();n0=len(y)-n1;auc=(rankdata(pr)[pos].sum()-n1*(n1+1)/2)/(n1*n0);lo,hi=np.quantile(pr,[.2,.8]);close([z.brier,z.auc,z.prevalence,z.low20_rate,z.high20_rate],[np.mean((pr-y)**2),auc,y.mean(),y[pr<=lo].mean(),y[pr>=hi].mean()],'binary independent metrics')
 for z in pd.read_csv(O/'late_comparisons.csv').itertuples():
  g=lp[lp.task.eq(z.task)];g=g if z.window=='2024_2025' else g[g.year.eq(int(z.window))];close(cluster(g,(g.p_J-g.target)**2-(g.p_P-g.target)**2),[z.estimate,z.se,z.lower,z.upper],'binary cluster CI')
 # Saved LightGBM models are evaluated with an independent scalar tree interpreter.
 model_details=[]
 for path in sorted((H/'models').glob('20*.json')):
  m=json.loads(path.read_text());year=m['year'];target=m['target'];name=m['feature_group'];cols=m['features'];tr=(q.year<year)&(q.role4.ge(0) if target=='early' else q[target].notna());check(tr.sum()==m['n'] and q.loc[tr,'date'].max().year<year,'model train cutoff');check(hashlib.sha256('\n'.join(q.loc[tr,'row_key']).encode()).hexdigest()==m['training_row_keys_sha256'],'training keys');check(cols==groups[name],'model feature order')
  booster=lgb.Booster(model_file=str(path.with_suffix('.txt')));tm=booster.dump_model();nclass=4 if target=='early' else 1;te=np.flatnonzero(q.year.eq(year));idx=rng.choice(te,min(32,len(te)),replace=False);vals=x.iloc[idx][cols].to_numpy();raw=np.zeros((len(idx),nclass))
  for k,tree in enumerate(tm['tree_info']):
   for j,row in enumerate(vals):raw[j,k%nclass]+=tree_value(tree['tree_structure'],row)
  if nclass==4:pr=np.exp(raw-raw.max(axis=1)[:,None]);pr/=pr.sum(axis=1)[:,None]
  else:pr=1/(1+np.exp(-raw[:,0]))
  close(pr,booster.predict(vals,num_threads=1),'scalar model trees',1e-10)
  if year<2026:
   pp=ep[ep.year.eq(year)] if target=='early' else lp[(lp.year==year)&(lp.task==target)];ix=q.set_index('row_key').index.get_indexer(pp.row_key);native=booster.predict(x.iloc[ix][cols],num_threads=1);saved=pp[[name+'_p'+str(j) for j in range(4)]].to_numpy() if target=='early' else pp['p_'+name].to_numpy();close(native,saved,'saved model predictions',1e-11)
  model_details.append(dict(model=path.stem,scalar_rows=len(idx),trees=len(tm['tree_info'])))
 matched=pd.read_parquet(O/'grade_matched_rows.parquet');cells=pd.read_csv(O/'grade_matched_cells.csv');cols=['meet','distance_m','year','experience_bin','age_bin'];check((cells[['False','True']]>=20).all().all(),'matched cell support')
 check(matched.groupby(cols+['high']).size().min()>=20,'matched rows support');check(matched.groupby('high').contrast_weight.sum().abs().sub(1).abs().max()<1e-12,'matched signed weights')
 gm=pd.read_csv(O/'grade_matched_comparisons.csv')
 for z in gm.itertuples():
  val=(matched.strong5 if z.target=='strong5' else matched['repeat']).astype(float);w=matched.contrast_weight;hi=(w[matched.high]*val[matched.high]).sum();lo=-(w[~matched.high]*val[~matched.high]).sum();close([z.high_mean,z.low_mean,z.estimate],[hi,lo,float(w@val)],'matched contrast')
  # Weighted clustered influence, separate high/low centering.
  influence=w*(val-np.where(matched.high,hi,lo));sums=[];ns=[]
  for ids in [matched.horse_id,matched.date.dt.strftime('%Y-%m-%d'),matched.horse_id+':'+matched.date.dt.strftime('%Y-%m-%d')]:
   a1=pd.DataFrame(dict(ids=ids,v=influence)).groupby('ids').v.sum();ns.append(len(a1));sums.append(float((a1*a1).sum())*len(a1)/(len(a1)-1))
  se=math.sqrt(max(0,sums[0],sums[1],sums[0]+sums[1]-sums[2]));crit=t.ppf(.975,min(ns[:2])-1);close([z.se,z.lower,z.upper],[se,z.estimate-crit*se,z.estimate+crit*se],'matched cluster')
 close(bh(2*t.sf(abs(gm.estimate/gm.se),gm.dates-1)),gm.bh_q_two_comparisons,'matched BH')
 for meet,g in q.groupby('meet'):
  day=g.date.max();key=max(g[g.date.eq(day)].source_key.unique(),key=lambda s:int(s.rsplit(':',1)[1]));card=cards[cards.source_key.eq(key)];check(set(card.row_key)==set(g[g.source_key.eq(key)].row_key),'unselected full example card')
 baseline=json.loads((O/'baseline_inventory.json').read_text())['related_existing_files'];shared={'thoroughbred/research/'+p for p in ['README.md','conclusions/README.md','conclusions/SOURCES.md','conclusions/source_manifest.json','ARTIFACT_SIZE_LOG.md']};preserved=0
 for r in baseline:
  if r['path'] in shared:continue
  check(digest(ROOT/r['path'])==r['sha256'],'preserved '+r['path']);preserved+=1
 result=dict(passed=True,checks=checks,inputs_hashed=len(audit['inputs']),full_roster_n=len(q),evaluation_n=len(ep),supported5_n=int(ep.supported5.sum()),preserved_prior_files=preserved,independent_methods=['SQL actual roster 5/10-slot windows','raw API identity and entity metadata','annual ridge normal equations and residual reconstruction','scalar entity cutoff lookups','leave-self-out full roster field features and tied ranks','future/current outcome intervention','scalar LightGBM tree-path interpreter','saved model full prediction replay','independent probability metrics/BH/cluster intervals','grade overlap weights and contrasts'],model_checks=model_details,intention_labels_available=False,publication_timestamps_audited=False)
 (O/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
