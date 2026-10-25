"""Frozen annual retrospective comparisons; no database or network access."""
from pathlib import Path
from datetime import date, timedelta
import json
import math
import warnings
import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.exceptions import ConvergenceWarning
from features import HERE, ROOT, TASKS, DISTANCES, sha, save


def row_scores(y,p):
    one=np.eye(p.shape[1])[y]
    return {'logloss':-np.log(np.maximum(p[np.arange(len(y)),y],1e-15)),
            'brier':np.square(p-one).sum(axis=1), 'accuracy':(p.argmax(axis=1)==y).astype(float),
            'first_brier':np.square(p[:,0]-(y==0)),
            'second_brier':np.square(p[:,1]-(y==1))}


def interval(d,cluster,rng):
    # Equal-race estimand, with row contributions allocated to each cluster.
    weights=1/d.groupby('race_id').api_record_id.transform('size')
    z=pd.DataFrame({'cluster':d[cluster], 'num':d.delta*weights,'den':weights}).groupby('cluster')[['num','den']].sum()
    num,den=z.num.to_numpy(),z.den.to_numpy()
    mean=num.sum()/den.sum()
    n=len(z)
    se=math.sqrt(n/(n-1)*np.square(num-mean*den).sum())/den.sum() if n>1 else np.nan
    vals=[]
    for _ in range(2000):
        ix=rng.integers(n,size=n)
        vals.append(num[ix].sum()/den[ix].sum())
    lo,hi=np.quantile(vals,[.025,.975])
    p=math.erfc(abs(mean/se)/math.sqrt(2)) if se>0 else (0. if mean else 1.)
    return float(mean),float(lo),float(hi),float(p),n


def main():
    out=HERE/'run02';out.mkdir(exist_ok=False)
    source=HERE/'features01/features_and_targets.csv'
    frozen=[source,HERE/'features01/history_lineage.csv',HERE/'features01/feature_columns.json',HERE/'PLAN.md',Path(__file__)]
    manifest=[{'path':str(p.relative_to(ROOT)),'sha256':sha(p),'bytes':p.stat().st_size} for p in frozen]
    save(out/'input_manifest.json',{'files':manifest})
    a=pd.read_csv(source,dtype={'horse_id':str},low_memory=False)
    a=a[a.race_distance_m.isin(DISTANCES)].copy()
    groups=json.loads((HERE/'features01/feature_columns.json').read_text())
    models={f'M{i}':sum([groups[k] for k in ['common','history','gate','opponents'][:i+1]],[]) for i in range(4)}
    ev=a[a.year.ge(2024)].copy()
    meta=['api_record_id','race_id','race_date','year','horse_id','horse_name','horse_number','race_distance_m','field_n','h_any_s1f_n']
    preds=[]; fits=[]; coef=[]; support=[]
    for year in [2024,2025,2026]:
        cut=(date(year,1,1)-timedelta(days=2)).isoformat()
        test=ev[ev.year.eq(year)].copy()
        train=a[a.race_date.le(cut)].copy()
        for dist in DISTANCES:
            tr=train[train.race_distance_m.eq(dist)];te=test[test.race_distance_m.eq(dist)]
            support.append({'year':year,'distance':dist,'train_races':tr.race_id.nunique(),'eval_races':te.race_id.nunique(),
                'eval_days':te.race_date.nunique(),'supported':tr.race_id.nunique()>=50 and te.race_id.nunique()>=30 and te.race_date.nunique()>=15})
        for task,labels in TASKS.items():
            tr=train[train['y_'+task].notna()].copy();y=tr['y_'+task].to_numpy(dtype=int)
            assert set(y)==set(range(len(labels)))
            w=(1/tr.groupby('race_id').api_record_id.transform('size')).to_numpy(copy=True);w/=w.mean()
            for name,cols in models.items():
                imp=SimpleImputer(strategy='median',add_indicator=True,keep_empty_features=True)
                sc=StandardScaler()
                x=sc.fit_transform(imp.fit_transform(tr[cols]))
                lr=LogisticRegression(C=.3,solver='lbfgs',max_iter=2000,tol=1e-5)
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter('always',ConvergenceWarning)
                    lr.fit(x,y,sample_weight=w)
                assert not any(issubclass(v.category,ConvergenceWarning) for v in caught)
                p=lr.predict_proba(sc.transform(imp.transform(test[cols])))
                assert np.isfinite(p).all() and (p>0).all() and np.allclose(p.sum(axis=1),1,atol=1e-12)
                z=test[meta].copy();z['task']=task;z['model']=name;z['y']=test['y_'+task]
                for j in range(len(labels)):z['p'+str(j)]=p[:,j]
                preds.append(z)
                fits.append({'year':year,'task':task,'model':name,'cutoff':cut,'train_last_date':tr.race_date.max(),
                    'train_rows':len(tr),'train_races':tr.race_id.nunique(),'eval_rows_all':len(test),
                    'eval_rows_known':test['y_'+task].notna().sum().item(),'max_iterations':int(lr.n_iter_.max()),
                    'converged':True,'input_columns':cols})
                coef.append({'year':year,'task':task,'model':name,'classes':lr.classes_.tolist(),
                    'feature_names':imp.get_feature_names_out(cols).tolist(),'impute_statistics':imp.statistics_.tolist(),
                    'indicator_columns':imp.indicator_.features_.tolist(),'scale_mean':sc.mean_.tolist(),
                    'scale_scale':sc.scale_.tolist(),'coef':lr.coef_.tolist(),'intercept':lr.intercept_.tolist()})
        print('Completed annual fit',year,len(test),'evaluation runners',flush=True)
    pr=pd.concat(preds,ignore_index=True)
    pr.to_csv(out/'predictions.csv',index=False,encoding='utf-8-sig')
    save(out/'fit_audit.json',fits);save(out/'model_parameters.json',coef)
    pd.DataFrame(support).to_csv(out/'distance_support.csv',index=False)
    scored=[];race_scores=[];cal=[]
    for (task,model),g in pr.groupby(['task','model']):
        g=g[g.y.notna()].copy();p=g[['p'+str(j) for j in range(len(TASKS[task]))]].to_numpy();y=g.y.to_numpy(dtype=int)
        for k,v in row_scores(y,p).items():g[k]=v
        scored.append(g)
        r=g.groupby(['race_id','race_date','year','race_distance_m'],as_index=False)[['logloss','brier','accuracy','first_brier','second_brier']].mean()
        r['task']=task;r['model']=model;r['known_rows']=g.groupby('race_id').size().reindex(r.race_id).to_numpy()
        race_scores.append(r)
        for period,mask in [('2024_2025',g.year.le(2025)),('2026_partial',g.year.eq(2026))]:
            sub=g[mask]
            for c in range(len(TASKS[task])):
                bins=np.minimum((sub['p'+str(c)]*10).astype(int),9)
                t=sub.assign(bin=bins,prob=sub['p'+str(c)],event=sub.y.eq(c).astype(float))
                for b,z in t.groupby('bin'):
                    cal.append({'task':task,'model':model,'period':period,'class':c,'bin':b,'rows':len(z),
                        'mean_probability':z.prob.mean(),'observed_rate':z.event.mean()})
    sc=pd.concat(scored,ignore_index=True);rs=pd.concat(race_scores,ignore_index=True)
    rs.to_csv(out/'race_metrics.csv',index=False)
    pd.DataFrame(cal).to_csv(out/'calibration.csv',index=False)
    # Aggregates always average each race, including selected-history subgroups.
    metrics=[]
    periods={'2024':lambda g:g.year.eq(2024),'2025':lambda g:g.year.eq(2025),'2026_partial':lambda g:g.year.eq(2026),
             '2024_2025':lambda g:g.year.le(2025)}
    for (task,model),g in sc.groupby(['task','model']):
        for period,masker in periods.items():
            z=g[masker(g)]
            for subset,ss in [('all',z),('history3plus',z[z.h_any_s1f_n.ge(3)]),('history0to2',z[z.h_any_s1f_n.lt(3)])]:
                for dist in ['all']+DISTANCES:
                    v=ss if dist=='all' else ss[ss.race_distance_m.eq(dist)]
                    if v.empty:continue
                    values=v.groupby('race_id')[['logloss','brier','accuracy','first_brier','second_brier']].mean().mean().to_dict()
                    metrics.append(dict(task=task,model=model,period=period,subset=subset,distance=dist,rows=len(v),races=v.race_id.nunique(),**values))
    pd.DataFrame(metrics).to_csv(out/'metrics.csv',index=False)
    top=[]
    for (model,rid),g in pr[pr.task.eq('s1f_pack3')].groupby(['model','race_id']):
        if g.y.isna().any():continue
        best=g.sort_values(['p0','horse_id'],ascending=[False,True]).iloc[0]
        top.append({'race_id':rid,'model':model,'year':int(best.year),'distance':int(best.race_distance_m),
            'selected_horse_id':best.horse_id,'selected_name':best.horse_name,'selected_probability':best.p0,
            'hit':int(best.y==0),'random_baseline':g.y.eq(0).mean(),'field_n':len(g)})
    pd.DataFrame(top).to_csv(out/'top_first_pack.csv',index=False,encoding='utf-8-sig')
    rng=np.random.default_rng(20261008);comparisons=[]
    for task in TASKS:
        for period,masker in [('2024_2025',lambda g:g.year.le(2025)),('2026_partial',lambda g:g.year.eq(2026))]:
            g=sc[sc.task.eq(task)];g=g[masker(g)]
            for old,new in [('M0','M1'),('M1','M2'),('M2','M3'),('M1','M3')]:
                l=g[g.model.eq(old)][meta+['logloss']]
                n=g[g.model.eq(new)][['api_record_id','logloss']]
                d=l.merge(n,on='api_record_id',validate='one_to_one',suffixes=('_old','_new'))
                d['delta']=d.logloss_new-d.logloss_old
                mean,lo,hi,p,days=interval(d,'race_date',rng)
                _,hl,hh,_,horses=interval(d,'horse_id',rng)
                comparisons.append({'task':task,'period':period,'comparison':new+'-'+old,'rows':len(d),'races':d.race_id.nunique(),
                    'date_clusters':days,'horse_clusters':horses,'delta_logloss':mean,'date_lo':lo,'date_hi':hi,
                    'horse_lo':hl,'horse_hi':hh,'p_date_normal':p,'confirmatory_family':new+'-'+old!='M3-M1'})
    cmp=pd.DataFrame(comparisons);family=cmp[cmp.confirmatory_family].sort_values('p_date_normal')
    q=np.minimum.accumulate((family.p_date_normal.to_numpy()*len(family)/np.arange(1,len(family)+1))[::-1])[::-1]
    cmp.loc[family.index,'BH_q']=np.minimum(q,1)
    cmp['supported_improvement']=cmp.confirmatory_family&cmp.date_hi.lt(0)&cmp.horse_hi.lt(0)&cmp.BH_q.lt(.05)
    cmp.to_csv(out/'paired_comparisons.csv',index=False)
    # Fixed descriptive gate / speed cells; no causal adjustment.
    v=ev.copy();exact=v.groupby('race_id').horse_number.agg(lambda x:len(x)==10 and set(x)==set(range(1,11)))
    v=v[v.race_id.isin(exact[exact].index)&v.speed_prior_known_field_n.ge(8)&v.h_any_s1ftime_n.ge(3)]
    v['gate_band']=pd.cut(v.horse_number,[0,3,7,10],labels=['inner1to3','middle4to7','outer8to10'])
    p3=pr[(pr.task=='s1f_pack3')&(pr.model=='M3')][['api_record_id','p0','p1']]
    pi=pr[(pr.task=='s1f_second_inside')&(pr.model=='M3')][['api_record_id','p1']].rename(columns={'p1':'inside_probability'})
    v=v.merge(p3,on='api_record_id',validate='one_to_one').merge(pi,on='api_record_id',validate='one_to_one')
    cells=[]
    for period,masker in [('2024_2025',lambda g:g.year.le(2025)),('2026_partial',lambda g:g.year.eq(2026))]:
        for (band,fast),g in v[masker(v)].groupby(['gate_band','speed_prior_fast_third'],observed=True):
            g=g[g.y_s1f_pack3.notna()]
            cells.append({'period':period,'gate_band':str(band),'fast_third':bool(fast),'rows':len(g),'races':g.race_id.nunique(),
                'first_observed':g.y_s1f_pack3.eq(0).mean(),'second_observed':g.y_s1f_pack3.eq(1).mean(),
                'inside_observed':g.y_s1f_second_inside.mean(),'first_predicted':g.p0.mean(),'second_predicted':g.p1.mean(),
                'inside_predicted':g.inside_probability.mean()})
    pd.DataFrame(cells).to_csv(out/'gate_speed_cells.csv',index=False)
    coverage=[]
    for period,masker in periods.items():
        g=ev[masker(ev)]
        for task in TASKS:coverage.append({'period':period,'task':task,'all_rows':len(g),'known_rows':int(g['y_'+task].notna().sum()),
            'coverage':g['y_'+task].notna().mean(),'all_races':g.race_id.nunique()})
    pd.DataFrame(coverage).to_csv(out/'target_coverage.csv',index=False)
    assert all(sha(ROOT[r['path']])==r['sha256'] for r in manifest)
    save(out/'verification.json',{'status':'passed','models':len(fits),'all_converged':True,'all_probabilities_positive_sum1':True,
        'all_train_cutoffs_precede_eval_year':True,'source_hashes_unchanged':True,'prediction_rows':len(pr),
        'evaluation_rows':len(ev),'evaluation_races':ev.race_id.nunique(),'BH_family_size':int(cmp.confirmatory_family.sum()),
        'no_hyperparameter_search':True,'retrospective_not_independent_holdout':True})
    print('Completed scoring',len(ev),ev.race_id.nunique(),flush=True)


if __name__=='__main__':main()
