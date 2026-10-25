"""Retrospective conditional Top3 rates; style labels use T-minus-two history only."""
from pathlib import Path
import json, hashlib
import numpy as np
import pandas as pd
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
FEATURES=ROOT/'jeju/research/20261008_gate_region_pace_prediction_v2/features01'
OUTCOMES=ROOT/'jeju/research/20261008_running_style_outcomes_v1/run01/runner_types_and_evidence.csv'
SEED=20261009
B=4000
DEFS={'same60':('same',.6),'any60':('any',.6),'same80':('same',.8)}
GROUPS={'first':0,'second':1,'farther':2,'nonfirst':-1}
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for x in iter(lambda:f.read(1048576),b''):h.update(x)
    return h.hexdigest()
def save(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def style(a,scope,threshold):
    p='h_'+scope+'_'
    return (a[p+'s1f_n'].ge(5)&a[p+'s1f_n'].ge(.6*a[p+'n'])&
            a[p+'s1f_first_mean'].ge(threshold-1e-12)&a[p+'s1f_front_mean'].ge(threshold-1e-12))
def boot(a,key,labels):
    """Cluster resample whole days or horses; all position groups share each draw."""
    if a.empty:return np.full((B,len(labels)),np.nan)
    keys=pd.Index(a[key].unique());counts=np.zeros((len(keys),len(labels)));wins=counts.copy()
    for j,mask in enumerate(labels):
        g=a.loc[mask].groupby(key).top3.agg(['count','sum']).reindex(keys,fill_value=0)
        counts[:,j]=g['count'];wins[:,j]=g['sum']
    rng=np.random.default_rng(SEED)
    results=[]
    for start in range(0,B,200):
        weights=rng.multinomial(len(keys),np.full(len(keys),1/len(keys)),size=min(200,B-start))
        den=weights@counts;num=weights@wins
        results.append(np.divide(num,den,out=np.full_like(num,np.nan),where=den>0))
    return np.concatenate(results)
def ci(values):
    valid=values[np.isfinite(values)]
    return [float(x) for x in np.quantile(valid,[.025,.975])] if len(valid) else [None,None]
def views(a):
    yield 'all','all',a
    yield 'period','2024_2025',a[a.year.isin([2024,2025])]
    yield 'period','2026',a[a.year.eq(2026)]
    for year,g in a.groupby('year'):yield 'year',str(year),g
    for dist,g in a.groupby('race_distance_m'):yield 'distance',str(dist),g
    for (dist,year),g in a[a.year.ge(2024)].groupby(['race_distance_m','year']):
        yield 'distance_year',f'{dist}_{year}',g

def main():
    out=HERE/'run01';out.mkdir(exist_ok=False)
    sources=[HERE/'PLAN.md',FEATURES/'features_and_targets.csv',FEATURES/'history_lineage.csv',FEATURES/'source_manifest.json',OUTCOMES,
             ROOT/'jeju/data/horse_exclusions.json',ROOT/'jeju/research/20261008_passing_group_running_style_v1/README.md']
    manifest={'files':[{'path':str(p.relative_to(ROOT)),'sha256':sha(p),'bytes':p.stat().st_size} for p in sources],
              'database_opened':False,'source_database_sha256':'a878a40fd5dc28e1385801c40136e506d9e3bc406e357e4158e5eb6883f5f21e'}
    save(out/'source_manifest.json',manifest)
    a=pd.read_csv(FEATURES/'features_and_targets.csv',dtype={'horse_id':str},low_memory=False)
    b=pd.read_csv(OUTCOMES,dtype={'horse_id':str},usecols=['api_record_id','horse_id','race_id','race_date','finish_position','top3'])
    assert len(a)==52155 and not a.api_record_id.duplicated().any() and not b.api_record_id.duplicated().any()
    a=a.merge(b,on=['api_record_id','horse_id','race_id','race_date'],validate='one_to_one',how='left')
    assert a.top3.notna().all() and (a.top3.astype(int)==a.finish_position.le(3)).all()
    exclusions=json.loads((ROOT/'jeju/data/horse_exclusions.json').read_text())['horses']
    assert not set(a.horse_id)&{k for k,v in exclusions.items() if not v['reimport_allowed']}
    for name,(scope,threshold) in DEFS.items():a['style_'+name]=style(a,scope,threshold)
    keep=['api_record_id','horse_id','race_id','race_date','year','race_distance_m','field_n','horse_number','s1f_pack_index','s1f_pack_size','s1f_zone','y_s1f_pack3','y_s1f_position4','finish_position','top3']
    keep += [c for c in a if c.startswith('style_')]+[f'h_{scope}_{name}' for scope in ['same','any'] for name in ['n','s1f_n','s1f_first_mean','s1f_front_mean']]
    a[keep].to_csv(out/'start_labels_and_outcomes.csv',index=False,encoding='utf-8-sig')
    rows=[];diffs=[];strict=[];coverage=[];within=[]
    for name in DEFS:
        selected=a[a['style_'+name]]
        for view,key,g in views(a):
            s=g[g['style_'+name]]
            coverage.append({'definition':name,'view':view,'key':key,'source_starts':len(g),'style_starts':len(s),'style_horses':s.horse_id.nunique(),'unknown_actual':int(s.y_s1f_pack3.isna().sum())})
        for view,key,g0 in views(selected):
            g=g0[g0.y_s1f_pack3.notna()]
            if g.empty:continue
            masks=[g.y_s1f_pack3.eq(v) if v>=0 else g.y_s1f_pack3.gt(0) for v in GROUPS.values()]
            bd=boot(g,'race_date',masks);bh=boot(g,'horse_id',masks)
            for j,(group,mask) in enumerate(zip(GROUPS,masks)):
                h=g.loc[mask];n=len(h);wins=int(h.top3.sum())
                rows.append({'definition':name,'view':view,'key':key,'actual_group':group,'starts':n,'top3':wins,'rate':wins/n if n else None,
                             'date_ci_low':ci(bd[:,j])[0],'date_ci_high':ci(bd[:,j])[1],'horse_ci_low':ci(bh[:,j])[0],'horse_ci_high':ci(bh[:,j])[1],
                             'horses':h.horse_id.nunique(),'races':h.race_id.nunique(),'days':h.race_date.nunique(),
                             'first_date':h.race_date.min() if n else None,'last_date':h.race_date.max() if n else None,
                             'field_min':int(h.field_n.min()) if n else None,'field_max':int(h.field_n.max()) if n else None,
                             'low_support':bool(n<100 or h.race_date.nunique()<20)})
            for j,other in [(1,'second'),(2,'farther'),(3,'nonfirst')]:
                first=g.loc[masks[0]];rest=g.loc[masks[j]]
                diffs.append({'definition':name,'view':view,'key':key,'contrast':'first_minus_'+other,
                              'difference_pp':100*(first.top3.mean()-rest.top3.mean()) if len(first) and len(rest) else None,
                              'date_ci_low_pp':ci(100*(bd[:,0]-bd[:,j]))[0],'date_ci_high_pp':ci(100*(bd[:,0]-bd[:,j]))[1],
                              'horse_ci_low_pp':ci(100*(bh[:,0]-bh[:,j]))[0],'horse_ci_high_pp':ci(100*(bh[:,0]-bh[:,j]))[1]})
            if view in ['all','period','distance']:
                # Overlap horse x distance strata, weights fixed at min(group sample sizes).
                gg=g.assign(nonfirst=g.y_s1f_pack3.gt(0).astype(int))
                ag=gg.groupby(['horse_id','race_distance_m','nonfirst']).top3.agg(['count','sum']).unstack('nonfirst')
                if 0 in ag['count'] and 1 in ag['count']:
                    ag=ag.dropna();w=ag['count'].min(axis=1);r0=ag['sum'][0]/ag['count'][0];r1=ag['sum'][1]/ag['count'][1]
                    if len(ag):
                        pairs=pd.DataFrame({'horse_id':ag.index.get_level_values('horse_id'),'weight':w.to_numpy(),'d':(r0-r1).to_numpy()})
                        hp=pairs.assign(wd=pairs.weight*pairs.d).groupby('horse_id')[['weight','wd']].sum()
                        rng=np.random.default_rng(SEED); draws=rng.multinomial(len(hp),np.full(len(hp),1/len(hp)),size=B)
                        bootdiff=100*(draws@hp.wd.to_numpy())/(draws@hp.weight.to_numpy())
                        within.append({'definition':name,'view':view,'key':key,'strata':len(ag),'horses':len(hp),'first_starts':int(ag['count'][0].sum()),'nonfirst_starts':int(ag['count'][1].sum()),
                                       'first_standardized_rate':float(np.average(r0,weights=w)),'nonfirst_standardized_rate':float(np.average(r1,weights=w)),
                                       'difference_pp':float(100*np.average(r0-r1,weights=w)),'horse_ci_low_pp':ci(bootdiff)[0],'horse_ci_high_pp':ci(bootdiff)[1]})
                for label,value in [('definite_lead',0),('definite_front_nonlead',1),('middle',2),('rear',3),('ambiguous',None)]:
                    h=g0[g0.y_s1f_position4.isna() if value is None else g0.y_s1f_position4.eq(value)]
                    strict.append({'definition':name,'view':view,'key':key,'position':label,'starts':len(h),'top3':int(h.top3.sum()),'rate':float(h.top3.mean()) if len(h) else None})
        print(name,'classified starts',len(selected),'horses',selected.horse_id.nunique(),flush=True)
    for file,data in [('rates',rows),('contrasts',diffs),('coverage',coverage),('strict_positions',strict),('within_horse_distance',within)]:
        pd.DataFrame(data).to_csv(out/(file+'.csv'),index=False,encoding='utf-8-sig')
    assert all(sha(ROOT/r['path'])==r['sha256'] for r in manifest['files'])
    save(out/'analysis_receipt.json',{'status':'completed_pending_independent_verification','source_starts':len(a),'source_races':a.race_id.nunique(),'source_horses':a.horse_id.nunique(),
                                    'source_first_date':a.race_date.min(),'source_last_date':a.race_date.max(),'bootstrap_draws':B,'seed':SEED,'operational_change':False})
    print(pd.DataFrame(rows).query("definition=='same60' and view in ['all','period']").to_string(index=False),flush=True)
if __name__=='__main__':main()
