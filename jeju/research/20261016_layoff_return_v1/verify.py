"""Independent actual-start SQL sequence and full joint FE verification."""
import json,sqlite3
from datetime import date,timedelta
import numpy as np
import pandas as pd
from scipy.sparse import coo_matrix,csc_matrix,bmat,diags
from scipy.sparse.linalg import splu
from scipy.stats import t
from data import HERE,ROOT,OLD,NUM,HISTORY,IDS,END,CURRENT,CONFIG,sha,save
from analysis import bh
def fe_independent(g,unit):
 races=sorted(g.race_id.unique());horses=sorted(g[unit].unique());r=pd.Categorical(g.race_id,categories=races).codes;h=pd.Categorical(g[unit],categories=horses).codes;nr=len(races);parent=list(range(nr+len(horses)))
 def root(a):
  while parent[a]!=a:parent[a]=parent[parent[a]];a=parent[a]
  return a
 for ri,hi in zip(r,h):
  u,v=root(int(ri)),root(nr+int(hi))
  if u!=v:parent[v]=u
 anchors={}
 for i in range(len(horses)):anchors.setdefault(root(nr+i),i)
 held=set(anchors.values());keep=[i for i in range(len(horses)) if i not in held];mapping={i:nr+k for k,i in enumerate(keep)};rr=list(range(len(g)));cc=list(r);vv=[1.]*len(g)
 for k,i in enumerate(h):
  if i in mapping:rr.append(k);cc.append(mapping[i]);vv.append(1.)
 return coo_matrix((vv,(rr,cc)),shape=(len(g),nr+len(keep))).tocsc(),len(anchors)
def reconstruct(g,spec):
 raw=g[NUM].copy();n=raw.fillna(spec['medians'])
 for c in NUM:
  assert np.isclose(raw[c].median() if raw[c].notna().any() else 0,spec['medians'][c])
  if raw[c].isna().any():n[c+'_missing']=raw[c].isna().astype(float)
 cols=[]
 for c in spec['columns']:
  if c.startswith('phase='):v=g.phase.eq(int(c.split('=')[1])).to_numpy(float)
  else:
   if c.startswith('jockey_'):n[c]=g.jockey_id.eq(c[len('jockey_'):]).astype(float)
   elif c.startswith('trainer_'):n[c]=g.trainer_id.eq(c[len('trainer_'):]).astype(float)
   assert np.isclose(n[c].mean(),spec['means'][c]) and np.isclose(n[c].std(ddof=0),spec['sd'][c]);v=((n[c]-spec['means'][c])/spec['sd'][c]).to_numpy()
  cols.append(v)
 return np.column_stack(cols)
def main():
 out=HERE/'verification01';out.mkdir(exist_ok=False);m=json.loads((HERE/'input01/source_manifest.json').read_text())
 for r in m['files']:assert sha(ROOT/r['path'])==r['sha256'] and (ROOT/r['path']).stat().st_size==r['bytes'],r['path']
 a=pd.read_csv(HERE/'input01/starts.csv',dtype={c:str for c in IDS},low_memory=False);e=pd.read_csv(HERE/'input01/episodes.csv',dtype={'horse_id':str});links=pd.read_csv(HERE/'input01/phase_lineage.csv',dtype={'horse_id':str});h=pd.read_csv(OLD/'input01/ledger_rows.csv',dtype={'horse_id':str});h=h[h.observed_started];idx=a.set_index('api_record_id');ed=e.set_index('episode_id');linkdict=links.groupby('episode_id').api_record_id.apply(list).to_dict()
 con=sqlite3.connect(':memory:');con.execute('CREATE TABLE s(id INTEGER,horse TEXT,day TEXT,race INTEGER,distance REAL)');con.executemany('INSERT INTO s VALUES(?,?,?,?,?)',[(int(r.api_record_id),r.horse_id,r.race_date,int(r.race_number),float(r.race_distance_m)) for r in h.itertuples()]);window=con.execute('SELECT id,horse,day,distance,LAG(day) OVER w,LEAD(id,1) OVER w,LEAD(day,1) OVER w,LEAD(id,2) OVER w,LEAD(day,2) OVER w FROM s WINDOW w AS (PARTITION BY horse ORDER BY day,race,id)').fetchall();con.close();checked_events=0
 for mode,(threshold,step,horizon) in CONFIG.items():
  expected=set();cutoff=(date.fromisoformat(END)-timedelta(days=horizon)).isoformat()
  for rid,horse,day,distance,prev,n1,d1,n2,d2 in window:
   if prev is None or day<'2017-01-01' or distance not in CURRENT:continue
   gap=(date.fromisoformat(day)-date.fromisoformat(prev)).days
   if gap<threshold:continue
   key=f'{mode}:{horse}:{rid}';expected.add(key);r=ed.loc[key];ids=[rid];dates=[day];reason='three_observed'
   for ni,di in [(n1,d1),(n2,d2)]:
    if ni is None:reason='no_next_observed_start';break
    delta=(date.fromisoformat(di)-date.fromisoformat(dates[-1])).days
    if delta>=91:reason='new_long_gap';break
    if delta>step:reason='followup_gap_exceeded';break
    if (date.fromisoformat(di)-date.fromisoformat(day)).days>horizon:reason='horizon_exceeded';break
    ids.append(ni);dates.append(di)
   chosen=[i in idx.index for i in ids];complete=len(ids)==3 and all(chosen);same=complete and len({idx.loc[i,'race_distance_m'] for i in ids})==1
   assert r.anchor_id==rid and r.anchor_date==day and r.rest_days==gap and r.mature==(day<=cutoff) and r.observed_phases==len(ids) and r.stop_reason==reason and r.complete_selected_triplet==complete and r.same_distance_triplet==same and linkdict[key]==ids
   assert r.first_selected==chosen[0] and r.second_selected==(len(ids)>=2 and chosen[1]) and r.third_selected==(len(ids)>=3 and chosen[2]);checked_events+=1
  assert expected==set(e[e['mode'].eq(mode)].episode_id)
 raw=pd.read_csv(HERE/'report01/raw_phase_results.csv',dtype={'period':str});rawchecks=0
 for r in raw.itertuples():
  q=e[e['mode'].eq(r.mode)&e.mature];q=q if r.period=='all' else q[q.anchor_year.between(2024,2025)] if r.period=='2024_2025' else q[q.anchor_year.eq(2026)]
  q=q[q.first_selected] if r.scope=='first_selected_all_available' else q[q.complete_selected_triplet] if r.scope=='balanced_all_distances' else q[q.same_distance_triplet];l=links[links.episode_id.isin(q.episode_id)&links.phase.eq(r.phase)&links.selected_outcome];g=idx.loc[l.api_record_id]
  assert len(g)==r.starts and int(g.top3.sum())==r.top3_count and np.allclose([g.finish_position.mean(),g.top3_pp.mean(),g.relative_time.mean()],[r.mean_rank,r.top3_pct,r.mean_relative_time]);rawchecks+=1
  for target in ['finish_position','top3_pp','relative_time','rank10_quality']:
   y=g[target];point=y.mean()
   for label,key in [('date','race_date'),('horse','horse_id')]:
    score=(y-point).groupby(g[key]).sum();G=len(score)
    if G>1:
     half=t.ppf(.975,G-1)*np.sqrt((score**2).sum()/len(g)**2*G/(G-1));assert np.allclose([point-half,point+half],[getattr(r,target+'_'+label+'_low'),getattr(r,target+'_'+label+'_high')])
 ef=pd.read_csv(HERE/'analysis01/effects.csv',dtype={'period':str});aux=pd.read_csv(HERE/'analysis01/third_minus_second.csv',dtype={'period':str});models=json.loads((HERE/'analysis01/models.json').read_text());checked=0;held=0;maxbeta=0.;maxcov=0.
 for group in models:
  if group['status']!='fitted':held+=1;continue
  variant=group['variant'];ep=e[e.episode_id.isin(group['episode_ids'])];assert ep.mature.all() and len(ep)>=30 and ep.horse_id.nunique()>=30 and ep.anchor_date.nunique()>=20
  phases=[1,2] if variant=='pair12' else [1,3] if variant=='pair13' else [1,2,3];l=links[links.episode_id.isin(ep.episode_id)&links.phase.isin(phases)].set_index('api_record_id');races=set(idx.loc[l.index,'race_id']);mask=np.ones(len(a),bool) if group['period']=='all' else a.year.between(2024,2025) if group['period']=='2024_2025' else a.year.eq(2026);g=a[mask|a.race_id.isin(races)].copy()
  if variant=='H1_residual':g=g[g.H1_time_adv.notna()]
  assert g.api_record_id.astype(int).tolist()==group['row_ids'];g['phase']=g.api_record_id.map(l.phase).fillna(0).astype(int);g['episode_id']=g.api_record_id.map(l.episode_id);g['anchor_id']=g.api_record_id.map(l.anchor_id);g['analysis_unit']='H:'+g.horse_distance;tr=g.phase.gt(0);g.loc[tr,'analysis_unit']='E:'+g.loc[tr,'episode_id']
  if variant=='all_distances':g.loc[tr,'analysis_unit']=g.loc[tr,'analysis_unit']+':'+g.loc[tr,'race_distance_m'].astype(str)
  if variant!='with_recent_form':
   for c in HISTORY:g.loc[tr,c]=g.loc[tr,'anchor_id'].map(idx[c]).to_numpy()
  X=reconstruct(g,group['spec']);Z,C=fe_independent(g,'analysis_unit');assert Z.shape[1]==group['FE']['rank'] and C==group['FE']['components'];K=len(group['spec']['phases']);pen=np.r_[np.zeros(K),np.ones(X.shape[1]-K)];xs=csc_matrix(X);ZZ=(Z.T@Z).tocsc();zlu=splu(ZZ);joint=splu(bmat([[ZZ,Z.T@xs],[xs.T@Z,xs.T@xs+diags(pen)]],format='csc'));xr=X-Z@zlu.solve(np.asarray(Z.T@X));bread=np.linalg.inv(X.T@X-np.asarray(X.T@Z)@zlu.solve(np.asarray(Z.T@X))+np.diag(pen))
  for model in group['models']:
   y=g[model['target']].to_numpy();coef=joint.solve(np.r_[np.asarray(Z.T@y).ravel(),X.T@y]);beta=coef[Z.shape[1]:];err=float(np.abs(beta-model['beta']).max());assert err<1e-5;maxbeta=max(maxbeta,err);res=y-Z@coef[:Z.shape[1]]-X@beta;covs={}
   for label,key in [('date','race_date'),('horse','horse_id')]:
    score=pd.DataFrame(xr*res[:,None]);score['key']=g[key].to_numpy();s=score.groupby('key').sum().to_numpy();G=len(s);cov=bread@s.T@s@bread*(G/(G-1)*(len(g)-1)/group['residual_df']);err=float(np.abs(cov-np.array(model[label+'_cov'])).max());assert err<1e-5;maxcov=max(maxcov,err);covs[label]=cov
   sign=-1 if model['target']=='relative_time' else 1
   for i,phase in enumerate(group['spec']['phases']):
    r=ef[(ef.period==group['period'])&(ef.variant==variant)&(ef.target==model['target'])&ef.comparison.eq(str(phase)+'_minus_1')];assert len(r)==1;r=r.iloc[0];point=sign*beta[i];sd=np.sqrt(max(0,covs['date'][i,i]));sh=np.sqrt(max(0,covs['horse'][i,i]));assert np.allclose([r.effect,r.date_low,r.date_high,r.horse_low,r.horse_high],[point,point-model['crit']*sd,point+model['crit']*sd,point-model['crit']*sh,point+model['crit']*sh])
   if group['spec']['phases']==[2,3]:
    vec=np.zeros(X.shape[1]);vec[0]=-sign;vec[1]=sign;point=vec@beta;r=aux[(aux.period==group['period'])&(aux.variant==variant)&(aux.target==model['target'])].iloc[0];sd=np.sqrt(max(0,vec@covs['date']@vec));assert np.allclose([r.effect,r.date_low,r.date_high],[point,point-model['crit']*sd,point+model['crit']*sd])
   checked+=1
  print('Return FE independently verified',group['period'],variant,flush=True)
 for variant in ['primary','H1_residual']:
  q=ef[ef.variant.eq(variant)];assert np.allclose(q.BH_q,bh(q.date_p))
 expected=ef.variant.isin(['primary','H1_residual'])&ef.BH_q.lt(.05)&((ef.date_low.gt(0)&ef.horse_low.gt(0))|(ef.date_high.lt(0)&ef.horse_high.lt(0)));assert np.array_equal(expected,ef.direction_supported);rep=pd.read_csv(HERE/'analysis01/repeat_checks.csv');assert not rep.repeated_supported.any()
 audit=json.loads((ROOT/'jeju/research/20261009_jockey_effects_v1/forecast01/fit_audit.json').read_text())
 for r in audit:assert r['train_last']<=r['cutoff']<str(r['year'])+'-01-01'
 H=a[a.H1_time.notna()];assert np.allclose(H.H1_time_adv,H.H1_time-H.relative_time)
 save(out/'verification.json',{'status':'passed','actual_start_SQL_window_rows':len(window),'episode_sequences_and_maturity_independently_rebuilt':checked_events,'phase_lineage_rows':len(links),'raw_scope_phase_cells_and_cluster_intervals_recomputed':rawchecks,'model_outcomes_joint_FE_reestimated':checked,'held_model_groups':held,'maximum_beta_difference':maxbeta,'maximum_covariance_difference':maxcov,'primary_tests_BH_recomputed':len(ef[ef.variant.eq('primary')]),'H1_tests_BH_recomputed':len(ef[ef.variant.eq('H1_residual')]),'recent_repeated_supported':0,'same_sample_phase_order_and_no_skipping_verified':True,'source_hashes_bytes_unchanged':True,'frozen_H1_cutoffs_and_sign_checked':True,'database_opened':False,'operational_change':False});print('Layoff-return verification passed',checked,flush=True)
if __name__=='__main__':main()
