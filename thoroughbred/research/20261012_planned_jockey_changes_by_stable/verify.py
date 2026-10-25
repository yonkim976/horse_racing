"""Independent token parser, source crosscheck, table reaggregation, full sparse LSQR audit."""
from pathlib import Path
import json,re,hashlib,math
import pandas as pd,numpy as np,duckdb
from scipy import sparse,stats
from scipy.sparse.linalg import lsqr
from scipy.stats import false_discovery_control
H=Path(__file__).resolve().parent;R=H.parent;ROOT=H.parents[2];O=H/'outputs';checks=0
def eq(a,b,tol=1e-9):
 global checks
 a=np.asarray(a);b=np.asarray(b);assert a.shape==b.shape,(a.shape,b.shape)
 if a.dtype.kind in 'biufc' and b.dtype.kind in 'biufc':assert np.allclose(a,b,atol=tol,rtol=tol,equal_nan=True),np.nanmax(np.abs(a-b))
 else:assert np.array_equal(pd.Series(a.ravel()).fillna('MISSING').astype(str),pd.Series(b.ravel()).fillna('MISSING').astype(str)),(a,b)
 checks+=a.size
def horse(x):return re.sub(r'^\[(서|서울|부|부산경남)\]','',str(x)).replace(' ','')
def audit():
 d=pd.read_parquet(O/'classified_starts.parquet');base=pd.read_parquet(R/'20261012_jockey_switch_trainer_intent/outputs/analysis_rows.parquet');
 for col in base.columns:eq(d[col],base[col])
 c=pd.read_parquet(O/'card_rows.parquet');n=pd.read_parquet(O/'notice_rows.parquet');api_cross=[]
 for file,g in c.groupby('source_path'):
  lines=(ROOT/file).read_bytes().decode('cp949').splitlines()
  for row in g.itertuples():
   line=lines[row.line_no-1];eq([line],[row.source_line]);parts=line.split();wi=next(i for i,v in enumerate(parts) if re.fullmatch(r'\d+\.\d+',v));eq([int(parts[0]),float(parts[wi])],[row.gate,row.card_weight]);eq([parts[1],re.sub(r'^\(-\d+\)','',parts[wi+1]),parts[wi+2]],[row.card_horse,row.scheduled_name,row.card_trainer])
   title=next(v for v in reversed(lines[:row.line_no]) if v.lstrip().startswith('제목'))
   date=re.search(r'(\d\d)\.(\d\d)\.(\d\d)',title);no=re.search(r'(\d+)경주',title);eq([row.source_key],[f'{row.meet}:20'+''.join(date.groups())+':'+str(int(no[1]))]);assert row.card_nominal_date<row.card_date
 for file,g in n.groupby('source_path'):
  if file.endswith('.rpt'):
   lines=(ROOT/file).read_bytes().decode('cp949').splitlines()
   for row in g.itertuples():
    parts=lines[row.line_no-1].split();eq([row.source_line],[lines[row.line_no-1]]);eq([row.gate],[int(parts[2])]);eq([row.notice_horse,row.before_name,row.after_name],[parts[3],parts[4],parts[5]]);eq([' '.join(row.reason.split())],[' '.join(parts[7:])]);eq([row.source_key],[row.source_key.split(':')[0]+':'+parts[0].replace('/','')+':'+str(int(parts[1][:-1]))])
  else:
   items=json.loads((ROOT/file).read_text())['response']['body']['items']['item'];items=items if isinstance(items,list) else [items]
   for row in g.itertuples():
    a=items[row.line_no];eq([row.before_id,row.after_id,row.reason,row.notice_horse],[str(a['jkBef']),str(a['jkAft']),a['reason'],a['hrName']])
 # Independent SQL planned necessary and sufficient source linkage, with horse prefix canonicalization.
 con=duckdb.connect();con.register('starts',d);con.register('cards',c);con.register('notices',n)
 s=con.sql("SELECT row_key,lag(classification) OVER(PARTITION BY horse_id ORDER BY date) previous_status FROM starts ORDER BY row_key").df();eq(d.sort_values('row_key').previous_classification,s.previous_status)
 cardmap={};edges={}
 for row in c.itertuples():cardmap.setdefault((row.source_key,row.gate),[]).append(row)
 for row in n.itertuples():edges.setdefault((row.source_key,row.gate),[]).append(row)
 days=pd.read_csv(O/'daily_bulletin_support.csv');receipts=pd.read_csv(O/'api_receipt_support.csv');support=set(zip(days.loc[days.supported,'meet'],days.loc[days.supported,'date']))|set(zip(receipts.loc[receipts.supported,'meet'],receipts.loc[receipts.supported,'date']))
 for row in d.itertuples():
  cards=cardmap.get((row.source_key,row.gate),[]);notices=edges.get((row.source_key,row.gate),[])
  validcards=[v for v in cards if v.card_pre_race];unique={(v.scheduled_id,v.card_trainer_id,horse(v.card_horse)) for v in validcards};supported=(row.meet,row.date.strftime('%Y-%m-%d')) in support
  expected=False
  if len(unique)==1:
   jid,tid,name=next(iter(unique));expected=bool(jid and tid and name==horse(row.horse_name) and tid==row.trainer_id and jid==row.jockey_id and not notices and supported)
  eq([row.classification=='planned_as_card'],[expected]);eq([row.change_source_supported],[supported])
  if row.classification=='post_card_change':
   assert notices and all(horse(v.notice_horse)==horse(row.horse_name) for v in notices)
   arcs={(v.before_id,v.after_id) for v in notices};assert all(a and b for a,b in arcs)
   roots=[row.scheduled_id] if row.scheduled_id else list({a for a,b in arcs}-{b for a,b in arcs});valid=False
   for root in roots:
    reach={root}
    for _ in range(len(arcs)+1):reach.update(b for a,b in arcs if a in reach)
    if row.jockey_id in reach and row.jockey_id!=root and all(a in reach for a,b in arcs):valid=True
   assert valid;checks_add=1
 # All overlapping API10/text events: compare ID edges; disagreements retained in classification as conflicts.
 for (key,gate),g in n.groupby(['source_key','gate']):
  txt=g[g.notice_type.eq('dacom13')];api=g[g.notice_type.eq('api10_1')]
  if len(txt) and len(api):
   a=set(zip(txt.before_id,txt.after_id));b=set(zip(api.before_id,api.after_id));api_cross.append(dict(source_key=key,gate=gate,edges_agree=a==b,text_edges=json.dumps(sorted(a)),api_edges=json.dumps(sorted(b))))
 pd.DataFrame(api_cross).to_csv(O/'api_text_crosscheck.csv',index=False)
 # Reaggregate every displayed population, stable and stable-rider pair; include both periods.
 for file,kind in [('category_metrics.csv','cat'),('stable_metrics.csv','stable'),('stable_destination_jockey_metrics.csv','pair'),('late_change_metrics.csv','late')]:
  table=pd.read_csv(O/file,dtype={'trainer_id':str,'jockey_id':str})
  for row in table.itertuples():
   g=d[d.year.between(2024,2025)] if row.window=='2024_2025' else d[d.year.eq(2026)]
   if kind=='late':g=g[g.normal_outcome] if row.population=='all_normal' else g[g.main_eligible];g=g[g.classification.eq('post_card_change')]
   elif kind=='stable' and row.category=='post_card_all_normal':g=g[g.normal_outcome&g.classification.eq('post_card_change')]
   else:g=g[g.main_eligible&g.classification.eq('planned_as_card')]
   if row.meet!='전체':g=g[g.meet.eq(row.meet)]
   if kind in ['stable','pair']:g=g[g.trainer_id.eq(row.trainer_id)]
   if kind=='pair':g=g[g.changed&g.jockey_id.eq(row.jockey_id)]
   if kind in ['cat','stable'] and row.category not in ['all','post_card_all_normal']:g=g[g.category.eq(row.category)]
   if kind=='late' and row.reason_class!='all':g=g[g.reason_class.eq(row.reason_class)]
   paired=g[g.previous_top3.notna()];eq([row.n,row.horses,row.races,row.top3_events],[len(g),g.horse_id.nunique(),g.source_key.nunique(),g.top3.sum()]);eq([row.top3_rate,row.previous_top3_rate,row.paired_top3_change,row.rank_improvement_mean,row.time_gap_mean,row.same_condition_time_change],[g.top3.mean(),paired.previous_top3.mean(),(paired.top3-paired.previous_top3).mean(),g.rank_improvement.mean(),g.time_gap.mean(),g.raw_time_change_same.mean()])
 eff=pd.read_csv(O/'adjusted_associations.csv');diag=pd.read_csv(O/'model_diagnostics.csv')
 for _,g in eff.groupby(['window','family','target']):eq(g.q,false_discovery_control(g.p.to_numpy(),method='bh'))
 assert diag.max_fe_mean.max()<1e-7 and diag.normal_equation_max.max()<1e-5
 # Full sparse solve independently from the production exact-FE projection; primary upgrade coefficient and cluster CI.
 reg=[]
 for target in ['top3','finish_p','time_gap']:
  g=d[d.main_eligible&d.year.between(2024,2025)&d.classification.eq('planned_as_card')&d[target].notna()].copy();count=len(g);cats=['retained_top','ordinary_to_top','top_to_top','top_to_ordinary','ordinary_to_ordinary'];x=np.column_stack([g.category.eq(cat).to_numpy(float) for cat in cats]);controls=[]
  for name in ['finish_p_mean5','finish_p_n5','previous_finish_p','previous_top3','gap_days','distance_change','grade_change','rating','age_current','weight','body_weight','gate_relative','previous_score']:
   v=g[name].to_numpy(float);bad=~np.isfinite(v);v=np.where(bad,0,v);controls.append(bad.astype(float));v=np.log1p(v) if name=='gap_days' else v;controls.append(v)
   if name in ['rating','age_current','weight','body_weight','finish_p_mean5','previous_finish_p','gap_days','gate_relative']:controls.append(v*v)
  ctrl=np.column_stack(controls);sd=ctrl.std(axis=0);x=np.column_stack([x,ctrl[:,sd>1e-12]/sd[sd>1e-12]]);race=pd.factorize(g.source_key)[0];horseid=pd.factorize(g.horse_id)[0];nr=race.max()+1;nh=horseid.max()+1
  fe=sparse.coo_matrix((np.ones(2*count),(np.r_[np.arange(count),np.arange(count)],np.r_[race,horseid+nr])),shape=(count,nr+nh)).tocsr();full=sparse.hstack([sparse.csr_matrix(x),fe]).tocsr();fit=lsqr(full,g[target].to_numpy(float),atol=1e-12,btol=1e-12,iter_lim=30000);coef=fit[0][:5]
  expected=eff[eff.window.eq('2024_2025')&eff.model.eq('primary')&eff.target.eq(target)].set_index('term').loc[cats];eq(coef,expected.estimate,tol=2e-6)
  unit=np.zeros(full.shape[1]);unit[1]=1;weights=lsqr(full.T,unit,atol=1e-12,btol=1e-12,iter_lim=30000)[0];df=diag[diag.window.eq('2024_2025')&diag.model.eq('primary')&diag.target.eq(target)].residual_df.iloc[0];score=weights*(g[target].to_numpy(float)-full@fit[0])*np.sqrt(count/df);variances=[];counts=[]
  for fields in [['horse_id'],['date'],['horse_id','date']]:
   t=g[fields].copy();t['score']=score;sums=t.groupby(fields).score.sum();k=len(sums);counts.append(k);variances.append(np.sum(sums.to_numpy()**2)*k/(k-1))
  se=np.sqrt(max(0,variances[0],variances[1],variances[0]+variances[1]-variances[2]));crit=stats.t.ppf(.975,min(counts[:2])-1);row=expected.loc['ordinary_to_top'];eq([se,coef[1]-crit*se,coef[1]+crit*se],[row.se,row.ci_low,row.ci_high],tol=2e-6);reg.append(dict(target=target,iterations=int(fit[2]),stop_code=int(fit[1]),max_coefficient_error=float(np.max(np.abs(coef-expected.estimate))),upgrade_ci_error=float(abs(se-row.se))))
 stable_reg=[];supported=pd.read_csv(O/'stable_model_support.csv',dtype={'trainer_id':str})
 for target in ['top3','finish_p','time_gap']:
  g=d[d.main_eligible&d.year.between(2024,2025)&d.classification.eq('planned_as_card')&d[target].notna()].copy();count=len(g);keys=g.meet+':'+g.trainer_id;terms=['retained_top','top_to_top','top_to_ordinary','ordinary_to_ordinary'];columns=[g.category.eq(v).to_numpy(float) for v in terms]
  for key in sorted(set(keys)):terms.append('stable_'+key);columns.append(keys.eq(key).to_numpy(float))
  qkeys=supported.meet+':'+supported.trainer_id;up=g.category.eq('ordinary_to_top');terms.append('upgrade_other');columns.append((up&~keys.isin(qkeys)).to_numpy(float))
  for key in qkeys:terms.append('upgrade_'+key);columns.append((up&keys.eq(key)).to_numpy(float))
  ctrl=[]
  for name in ['finish_p_mean5','finish_p_n5','previous_finish_p','previous_top3','gap_days','distance_change','grade_change','rating','age_current','weight','body_weight','gate_relative','previous_score']:
   v=g[name].to_numpy(float);bad=~np.isfinite(v);v=np.where(bad,0,v);ctrl.append(bad.astype(float));v=np.log1p(v) if name=='gap_days' else v;ctrl.append(v)
   if name in ['rating','age_current','weight','body_weight','finish_p_mean5','previous_finish_p','gap_days','gate_relative']:ctrl.append(v*v)
  ctrl=np.column_stack(ctrl);sd=ctrl.std(axis=0);x=np.column_stack(columns+[v for v in (ctrl[:,sd>1e-12]/sd[sd>1e-12]).T]);race=pd.factorize(g.source_key)[0];horseid=pd.factorize(g.horse_id)[0];nr=race.max()+1;nh=horseid.max()+1
  fe=sparse.coo_matrix((np.ones(2*count),(np.r_[np.arange(count),np.arange(count)],np.r_[race,horseid+nr])),shape=(count,nr+nh)).tocsr();full=sparse.hstack([sparse.csr_matrix(x),fe]).tocsr();sol=lsqr(full,g[target].to_numpy(float),atol=1e-12,btol=1e-12,iter_lim=30000);expected=eff[eff.model.eq('stable_joint')&eff.target.eq(target)].set_index('term');ix=[terms.index(v) for v in expected.index];eq(sol[0][ix],expected.estimate,tol=3e-6)
  significant=expected[expected.q.lt(.05)]
  for term,row in significant.iterrows():
   if term=='upgrade_other':continue
   unit=np.zeros(full.shape[1]);unit[terms.index(term)]=1;weights=lsqr(full.T,unit,atol=1e-12,btol=1e-12,iter_lim=30000)[0];df=diag[diag.model.eq('stable_joint')&diag.target.eq(target)].residual_df.iloc[0];score=weights*(g[target].to_numpy(float)-full@sol[0])*np.sqrt(count/df);vars_=[];counts=[]
   for fields in [['horse_id'],['date'],['horse_id','date']]:
    t=g[fields].copy();t['score']=score;sums=t.groupby(fields).score.sum();k=len(sums);counts.append(k);vars_.append(np.sum(sums.to_numpy()**2)*k/(k-1))
   se=np.sqrt(max(0,vars_[0],vars_[1],vars_[0]+vars_[1]-vars_[2]));eq([se],[row.se],tol=3e-6)
  stable_reg.append(dict(target=target,stop_code=int(sol[1]),iterations=int(sol[2]),stable_terms=len(ix),max_coefficient_error=float(np.max(np.abs(sol[0][ix]-expected.estimate)))))
 for row in json.loads((O/'source_audit.json').read_text())['source_inputs']:eq([hashlib.sha256((ROOT/row['path']).read_bytes()).hexdigest()],[row['sha256']])
 result=dict(passed=True,checks=checks,base_rows_preserved=len(d),card_rows_independently_token_parsed=len(c),notice_rows_independently_reparsed=len(n),planned_classification_independently_checked=len(d),explicit_replacement_chains_checked=int(d.classification.eq('post_card_change').sum()),api_text_overlaps=len(api_cross),api_text_edge_disagreements=sum(not x['edges_agree'] for x in api_cross),all_tables_reaggregated=True,independent_full_sparse_primary_models=reg,independent_full_sparse_stable_models=stable_reg,source_hashes_unchanged=True)
 (O/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':audit()
