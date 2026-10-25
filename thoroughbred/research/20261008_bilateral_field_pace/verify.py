"""Independent SQL bilateral aggregation, interventions, tree evaluation and metrics."""
import json,hashlib,math,sys
import numpy as np,pandas as pd,duckdb,lightgbm as lgb
from scipy.stats import t,rankdata
import experiment as e
H=e.H;O=e.O;P=e.P;ROOT=e.ROOT;checks=0
def test(ok,label,n=1):
 global checks
 assert bool(ok),label
 checks+=n
def close(a,b,label):
 a=np.asarray(a,float);b=np.asarray(b,float);test(a.shape==b.shape,label+' shape');test(np.allclose(a,b,atol=1e-9,rtol=1e-9,equal_nan=True),label,a.size)
def ci(g,v):
 v=np.asarray(v);mean=float(v.mean());score=(v-mean)/len(v);vars=[];ns=[]
 for ids in [g.horse_id,g.date.dt.strftime('%Y-%m-%d'),g.horse_id+':'+g.date.dt.strftime('%Y-%m-%d')]:
  sums={}
  for k,s in zip(ids,score):sums[k]=sums.get(k,0)+s
  n=len(sums);ns.append(n);vars.append(sum(s*s for s in sums.values())*n/(n-1))
 se=math.sqrt(max(0,vars[0],vars[1],vars[0]+vars[1]-vars[2]));crit=t.ppf(.975,min(ns[:2])-1);return [mean,se,mean-crit*se,mean+crit*se]
def bh(p):
 p=np.asarray(p);order=np.argsort(p);q=np.minimum.accumulate((p[order]*len(p)/np.arange(1,len(p)+1))[::-1])[::-1];out=np.empty_like(q);out[order]=np.minimum(q,1);return out
def leaf(node,row):
 while 'leaf_value' not in node:
  test(node['decision_type']=='<=','numeric tree');v=row[node['split_feature']];missing=np.isnan(v) or (node['missing_type']=='Zero' and v==0);left=node['default_left'] if missing else v<=node['threshold'];node=node['left_child' if left else 'right_child']
 return node['leaf_value']
def main():
 q=pd.read_parquet(P/'outputs/feature_context.parquet');z=pd.read_parquet(O/'additional_features.parquet');base=pd.read_parquet(P/'outputs/feature_frame.parquet');contract=json.loads((O/'feature_contract.json').read_text());groups=contract['groups'];x=pd.concat([base[groups['N']],z],axis=1);test(len(q)==159014 and len(z)==len(q),'full roster');test(q.row_key.is_unique,'unique roster');test(len(q.groupby('source_key'))==14636,'all races')
 close(q.groupby('source_key').size(),q.groupby('source_key').field_size.first(),'field roster counts');close(z.all_n,q.field_size-1,'no opponents dropped');close(z.inner_n+z.outer_n,z.all_n,'gate partition');close(z.outer_lead_sum,q.field_lead_sum_other-q.field_inner_front_sum,'outer sum was derivable');close(z.inner_lead_sum,q.field_inner_front_sum,'old inner reference')
 test(not any('jockey' in c or 'trainer' in c for c in x),'all entity/change fields excluded');test(len(groups['N'])==157,'baseline contract');test(hashlib.sha256('\n'.join(q.row_key).encode()).hexdigest()==contract['row_keys_sha256'],'row ordering')
 for r in json.loads((O/'source_audit.json').read_text())['inputs']:test(e.sha(ROOT/r['path'])==r['sha256'],'immutable input')
 # Pair join aggregates independently, retaining directions with zero opponents.
 db=duckdb.connect();db.register('roster',q);sqlchecks=0
 for side,condition in [('all','TRUE'),('inner','h.gate<c.gate'),('outer','h.gate>c.gate')]:
  count=f'count(*) FILTER(WHERE {condition})';cols=['c.row_key',f'{count} n']
  for v in e.VALUES:
   cols +=[f'avg(h."{v}") FILTER(WHERE {condition}) "{v}_mean"',f'count(h."{v}") FILTER(WHERE {condition})*1.0/nullif({count},0) "{v}_coverage"']
  cols +=[f'coalesce(sum(h.lead_prior5) FILTER(WHERE {condition}),0) lead_sum',f'count(*) FILTER(WHERE {condition} AND h.count5_0>=3) strong_front_n',f'count(*) FILTER(WHERE {condition} AND h.count5_0+h.count5_1>=3) strong_ahead_n',f'max(h.early_adv_mean5) FILTER(WHERE {condition}) adv_best']
  for name,val,known in [('faster_adv_n','h.early_adv_mean5>c.early_adv_mean5','early_adv_mean5'),('faster_raw_n','h.early_mean5<c.early_mean5','early_mean5'),('faster_front_n','h.early_adv_mean5>c.early_adv_mean5 AND h.count5_0>=3','early_adv_mean5')]:cols.append(f'CASE WHEN max(c.{known}) IS NOT NULL THEN count(*) FILTER(WHERE {condition} AND {val}) ELSE NULL END {name}')
  cols +=[f'count(*) FILTER(WHERE {condition} AND h.early_adv_mean5 IS NOT NULL AND c.early_adv_mean5 IS NOT NULL) faster_pair_n',f'CASE WHEN max(c.early_adv_mean5) IS NOT NULL THEN coalesce(sum(h.lead_prior5) FILTER(WHERE {condition} AND h.early_adv_mean5>c.early_adv_mean5),0) ELSE NULL END faster_lead_sum',f'count(*) FILTER(WHERE {condition} AND h.supported5) supported5_n',f'count(*) FILTER(WHERE {condition} AND h.valid_position5=0) unknown_position_n',f'count(*) FILTER(WHERE {condition} AND h.late_cond_adv_mean5>0) late_fast_n']
  out=db.execute('SELECT '+','.join(cols)+' FROM roster c JOIN roster h ON c.source_key=h.source_key AND c.row_key<>h.row_key GROUP BY c.row_key').df().set_index('row_key').loc[q.row_key]
  for c in e.STATS:close(out[c],z[side+'_'+c],'SQL '+side+' '+c);sqlchecks+=len(q)
  print('verified SQL',side,flush=True)
 for c in e.SIDE_DIFF:close(z['inner_'+c]-z['outer_'+c],z['side_gap_'+c],'side contrast')
 # Mirror a fixed race sample: sides swap, whole-field summaries stay unchanged.
 keys=q.source_key.drop_duplicates().iloc[::29];sample=q[q.source_key.isin(keys)].copy().reset_index(drop=True);original=e.features(sample);mirror=sample.copy();mirror.gate=mirror.groupby('source_key').gate.transform('max')+1-mirror.gate;reverse=e.features(mirror)
 for c in e.STATS:close(original['all_'+c],reverse['all_'+c],'mirror all');close(original['inner_'+c],reverse['outer_'+c],'mirror inner/outer');close(original['outer_'+c],reverse['inner_'+c],'mirror outer/inner')
 for c in e.SIDE_DIFF:close(original['side_gap_'+c],-reverse['side_gap_'+c],'mirror sign')
 perturbed=sample.copy();rng=np.random.default_rng(81)
 for c in ['role4','role5','early','late','last600','rating','finish_p','recovery','fade']:perturbed[c]=rng.normal(size=len(sample))
 for c in [c for c in sample if 'jockey' in c or 'trainer' in c]:perturbed[c]='MUTATED'
 invariant=e.features(perturbed);close(original,invariant,'current target/entities irrelevant')
 if '--features-only' in sys.argv:
  e.dump(O/'feature_verification.json',dict(passed=True,checks=checks,independent_SQL_values=sqlchecks,mirror_races=len(keys),intervention_rows=len(sample),all_starters_retained=True,no_jockey_trainer_or_change=True));print('Feature verification passed',checks,flush=True);return
 # Full-field four-class outputs and scalar independent probability diagnostics.
 ep=pd.read_parquet(O/'early_predictions.parquet');lp=pd.read_parquet(O/'late_predictions.parquet');old=pd.read_parquet(P/'outputs/early_predictions.parquet').set_index('row_key');test(set(ep.row_key)==set(old.index),'same previous evaluation roster');test(ep.supported5.sum()==24613,'common 5 support');loss={}
 for name in ['oldF','N','A','B']:
  pr=ep[[name+'_p'+str(j) for j in range(4)]].to_numpy();close(pr.sum(axis=1),np.ones(len(ep)),'probability sums');test(((pr>=0)&(pr<=1)).all(),'probability bounds');loss[name]=((pr-np.eye(4)[ep.role4.to_numpy()])**2).sum(axis=1)
 for j in range(4):close(ep['oldF_p'+str(j)],old.loc[ep.row_key,'F_p'+str(j)],'old F probabilities unchanged')
 for r in pd.read_csv(O/'early_metrics.csv').itertuples():
  mask=np.ones(len(ep),bool) if r.window=='2024_2025' else ep.year.eq(int(r.window)).to_numpy()
  if r.scope=='supported5':mask=mask&ep.supported5
  g=ep.loc[mask];pr=g[[r.model+'_p'+str(j) for j in range(4)]].to_numpy();y=g.role4.to_numpy();close([loss[r.model][mask].mean(),(pr.argmax(axis=1)==y).mean(),-np.log(pr[np.arange(len(g)),y]).mean()],[r.brier,r.accuracy,r.logloss],'early metrics')
 co=pd.read_csv(O/'early_comparisons.csv')
 for r in co.itertuples():
  mask=np.ones(len(ep),bool) if r.window=='2024_2025' else ep.year.eq(int(r.window)).to_numpy()
  if r.scope=='supported5':mask=mask&ep.supported5
  a,b=r.comparison.split('-');close(ci(ep.loc[mask],(loss[a]-loss[b])[mask]),[r.estimate,r.se,r.lower,r.upper],'early independent clusters')
 pooled=co[co.window.eq('2024_2025')&co.scope.eq('all')];close(bh(2*t.sf(abs(pooled.estimate/pooled.se),pooled.dates-1)),pooled.bh_q_three,'early BH')
 for r in pd.read_csv(O/'late_metrics.csv').itertuples():
  g=lp[lp.task.eq(r.task)];g=g if r.window=='2024_2025' else g[g.year.eq(int(r.window))];y=g.target.to_numpy();pr=g['p_'+r.model].to_numpy();pos=y==1;n1=pos.sum();auc=(rankdata(pr)[pos].sum()-n1*(n1+1)/2)/(n1*(len(y)-n1));lo,hi=np.quantile(pr,[.2,.8]);close([((pr-y)**2).mean(),auc,y[pr<=lo].mean(),y[pr>=hi].mean(),y.mean()],[r.brier,r.auc,r.low20_rate,r.high20_rate,r.prevalence],'binary metrics')
 lc=pd.read_csv(O/'late_comparisons.csv')
 for r in lc.itertuples():
  g=lp[lp.task.eq(r.task)];g=g if r.window=='2024_2025' else g[g.year.eq(int(r.window))];close(ci(g,(g.p_B-g.target)**2-(g.p_N-g.target)**2),[r.estimate,r.se,r.lower,r.upper],'binary cluster')
 g=lc[lc.window.eq('2024_2025')];close(bh(2*t.sf(abs(g.estimate/g.se),g.dates-1)),g.bh_q_two,'binary BH')
 for filename,pp in [('early_calibration.csv',ep),('late_calibration.csv',lp)]:
  for r in pd.read_csv(O/filename).itertuples():
   if filename.startswith('early'):gg=pp;pr=gg[r.model+'_p'+str(r.class_id)];y=gg.role4.eq(r.class_id)
   else:gg=pp[pp.task.eq(r.task)];pr=gg['p_'+r.model];y=gg.target
   mask=np.minimum((pr*10).astype(int),9).eq(r.bin);test(mask.sum()==r.n,'calibration counts');close([pr[mask].mean(),y[mask].mean()],[r.predicted,r.actual],'calibration')
 cards=pd.read_csv(O/'example_cards.csv',dtype={'horse_id':str});pairs=pd.read_csv(O/'example_rival_pairs.csv');model_details=[]
 for path in sorted(e.M.glob('*.json')):
  m=json.loads(path.read_text());target=m['target'];year=m['year'];name=m['name'];cols=m['features'];train=q.year.lt(year)&(q.role4.ge(0) if target=='early' else q[target].notna());test(train.sum()==m['n'] and q.loc[train,'date'].max().year<year,'model cutoff');test(hashlib.sha256('\n'.join(q.loc[train,'row_key']).encode()).hexdigest()==m['training_keys_sha256'],'train keys');test(cols==groups[name],'model exact columns');test(not any('jockey' in c or 'trainer' in c for c in cols),'actual models exclude entities')
  b=lgb.Booster(model_file=str(path.with_suffix('.txt')));tm=b.dump_model();nclass=4 if target=='early' else 1;ix=np.flatnonzero(q.year.eq(year));ix=rng.choice(ix,16,replace=False);vals=x.iloc[ix][cols].to_numpy();raw=np.zeros((len(ix),nclass))
  for k,tree in enumerate(tm['tree_info']):
   for i,row in enumerate(vals):raw[i,k%nclass]+=leaf(tree['tree_structure'],row)
  if nclass==4:pr=np.exp(raw-raw.max(axis=1)[:,None]);pr/=pr.sum(axis=1)[:,None]
  else:pr=1/(1+np.exp(-raw[:,0]))
  close(pr,b.predict(vals,num_threads=1),'independent scalar trees')
  saved=(ep[ep.year.eq(year)] if target=='early' else lp[lp.year.eq(year)&lp.task.eq(target)]) if year<2026 else cards;ix=q.set_index('row_key').index.get_indexer(saved.row_key);actual=b.predict(x.iloc[ix][cols],num_threads=1);stored=saved[[name+'_p'+str(j) for j in range(4)]].to_numpy() if target=='early' else saved['p_'+name if year<2026 else target+'_p'].to_numpy();close(actual,stored,'all stored predictions replay');model_details.append(dict(model=path.stem,train_n=m['n'],scalar_rows=16))
 for key,g in q[q.source_key.isin(cards.source_key)].groupby('source_key'):
  card=cards[cards.source_key.eq(key)];test(set(card.row_key)==set(g.row_key),'complete case card');test(len(pairs[pairs.source_key.eq(key)])==len(g)*(len(g)-1),'all directed rival pairs')
  for row in card.itertuples():
   pp=pairs[pairs.own_row_key.eq(row.row_key)];test(set(pp.rival_row_key)==set(g.row_key)-{row.row_key},'all other starters');test((pp.side.eq('inner')==pp.rival_gate.lt(row.gate)).all(),'case side labels');close([row.inner_n,row.outer_n],[pp.side.eq('inner').sum(),pp.side.eq('outer').sum()],'case side count')
 diag=pd.read_parquet(O/'diagnostic_rows.parquet');summary=pd.read_csv(O/'strong_front_side_diagnostic.csv')
 for r in summary.itertuples():
  g=diag[diag.gate_band.eq(r.gate_band)&diag.inner_fast_front.eq(r.inner_fast_front)&diag.outer_fast_front.eq(r.outer_fast_front)];test(len(g)==r.n,'diagnostic count');close([g.role4.eq(0).mean()],[r.first_group_rate],'descriptive rate')
 shared={'thoroughbred/research/'+p for p in ['README.md','conclusions/README.md','conclusions/SOURCES.md','conclusions/source_manifest.json','ARTIFACT_SIZE_LOG.md']};preserved=0
 for r in json.loads((O/'baseline_inventory.json').read_text())['related_existing_files']:
  if r['path'] in shared:continue
  test(e.sha(ROOT/r['path'])==r['sha256'],'prior preserved '+r['path']);preserved+=1
 result=dict(passed=True,checks=checks,independent_SQL_values=sqlchecks,roster_n=len(q),early_evaluation_n=len(ep),supported5_n=int(ep.supported5.sum()),mirror_races=len(keys),current_outcome_and_entity_intervention_rows=len(sample),case_races=cards.source_key.nunique(),case_runners=len(cards),directed_case_rivals=len(pairs),prior_files_preserved=preserved,models=model_details,no_jockey_trainer_or_change_inputs=True,outer_sum_redundancy_verified=True,prerace_publication_timestamps_audited=False)
 e.dump(O/'verification.json',result);print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
