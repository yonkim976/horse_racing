"""Fixed evaluation with equal-race scoring and date-cluster uncertainty."""
import json,math
import numpy as np
import pandas as pd
from scipy.stats import norm
from sklearn.metrics import roc_auc_score
from common import *
from experiment import META

def periods(a):
    return {'all_eval':a,'2024':a[a.year.eq(2024)],'2025':a[a.year.eq(2025)],
            '2024_2025':a[a.year.between(2024,2025)],'2026':a[a.year.eq(2026)]}

def interval(values,dates,seed=20261021):
    z=pd.DataFrame({'value':np.asarray(values,float),'date':np.asarray(dates)})
    z=z.groupby('date').value.agg(['sum','count']);n=len(z)
    if n<2:return float(z['sum'].sum()/z['count'].sum()),None,None,1.
    num=z['sum'].to_numpy();den=z['count'].to_numpy();mean=num.sum()/den.sum()
    se=np.sqrt(n/(n-1)*np.square(num-mean*den).sum())/den.sum()
    rng=np.random.default_rng(seed);boots=[]
    for _ in range(2000):
        ix=rng.integers(n,size=n);boots.append(num[ix].sum()/den[ix].sum())
    low,high=np.quantile(boots,[.025,.975])
    p=float(2*norm.sf(abs(mean/se))) if se else (1. if mean==0 else 0.)
    return float(mean),float(low),float(high),p

def bh(p):
    p=np.asarray(p);order=np.argsort(p);v=np.minimum.accumulate((p[order]*len(p)/np.arange(1,len(p)+1))[::-1])[::-1]
    r=np.empty(len(p));r[order]=np.minimum(v,1);return r

def scores(g,k):
    p=g[['p'+str(c) for c in range(k)]].to_numpy();y=g.y.to_numpy(int)
    return pd.DataFrame({'api_record_id':g.api_record_id.to_numpy(),'race_id':g.race_id.to_numpy(),
        'race_date':g.race_date.to_numpy(),'year':g.year.to_numpy(),'distance':g.race_distance_m.to_numpy(),
        'task':g.task.to_numpy(),'model':g.model.to_numpy(),'brier':np.square(p-np.eye(k)[y]).sum(axis=1),
        'nll':-np.log(np.maximum(p[np.arange(len(p)),y],1e-15)),
        'accuracy':(p.argmax(axis=1)==y).astype(float),
        'first_brier':np.square(p[:,0]-(y==0)) if k==3 else np.square(p[:,1]-y)})

def main():
    pr=pd.read_parquet(OUT/'predictions.parquet');a=pd.read_parquet(OUT/'features_and_targets.parquet')
    scored=[];metrics=[];binary=[];calibration=[];confusion=[];candidates=[];coverage=[];support=[]
    for task in TASKS:
        raw=pr[(pr.task==task)&(pr.model=='F')]
        for period,g in periods(raw).items():
            coverage.append({'task':task,'period':period,'roster_rows':len(g),'known_rows':int(g.y.notna().sum()),
                             'roster_races':g.race_id.nunique(),'known_races':g.loc[g.y.notna(),'race_id'].nunique()})
    for (task,name),g in pr.groupby(['task','model']):
        known=g[g.y.notna()].copy();k=3 if task in POINTS else 2
        s=scores(known,k);scored.append(s)
        rs=s.groupby(['race_id','race_date','year','distance'],as_index=False)[['brier','nll','accuracy','first_brier']].mean()
        for period,z in periods(rs).items():
            for distance in ['all']+DISTANCES:
                d=z if distance=='all' else z[z.distance.eq(distance)]
                if d.empty:continue
                runners=known[known.race_id.isin(d.race_id)]
                metrics.append({'task':task,'model':name,'period':period,'distance':str(distance),'races':len(d),
                    'rows':len(runners),'days':d.race_date.nunique(),**{c:float(d[c].mean()) for c in ['brier','nll','accuracy','first_brier']}})
            zrunner=known[known.race_id.isin(z.race_id)]
            if zrunner.empty:continue
            if k==2:
                binary.append({'task':task,'model':name,'period':period,'rows':len(zrunner),'races':len(z),
                    'prevalence':zrunner.y.mean(),'probability_mean':zrunner.p1.mean(),
                    'binary_brier':float(np.square(zrunner.p1-zrunner.y).mean()),
                    'auc':float(roc_auc_score(zrunner.y,zrunner.p1)) if zrunner.y.nunique()==2 else np.nan,
                    'low20_rate':zrunner.sort_values(['p1','api_record_id']).head(max(1,int(.2*len(zrunner)))).y.mean(),
                    'high20_rate':zrunner.sort_values(['p1','api_record_id']).tail(max(1,int(.2*len(zrunner)))).y.mean()})
            for c in range(k):
                prob=zrunner['p'+str(c)];binid=np.minimum((prob*10).astype(int),9)
                for b,t in zrunner.assign(bin=binid).groupby('bin'):
                    calibration.append({'task':task,'model':name,'period':period,'class':c,'bin':b,'rows':len(t),
                         'probability':t['p'+str(c)].mean(),'observed':t.y.eq(c).mean()})
        if task in POINTS:
            pcols=['p0','p1','p2'];known['guess']=known[pcols].to_numpy().argmax(axis=1)
            for period,z in periods(known).items():
                for actual in range(3):
                    for guessed in range(3):confusion.append({'task':task,'model':name,'period':period,'actual':actual,'predicted':guessed,
                        'count':int((z.y.eq(actual)&z.guess.eq(guessed)).sum()),'actual_count':int(z.y.eq(actual).sum())})
            # Candidate is selected before checking whether its label is observed.
            top=g.sort_values(['race_id','p0','horse_id'],ascending=[True,False,True]).drop_duplicates('race_id')
            top=top.copy();top['hit']=top.y.eq(0).astype(float).where(top.y.notna())
            top['miss_second']=top.y.eq(1);top['miss_behind']=top.y.eq(2)
            candidates.append(top)
    sc=pd.concat(scored,ignore_index=True);sc.to_parquet(OUT/'row_scores.parquet',index=False)
    met=pd.DataFrame(metrics);met.to_csv(OUT/'metrics.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(binary).to_csv(OUT/'binary_metrics.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(calibration).to_csv(OUT/'calibration.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(confusion).to_csv(OUT/'confusion.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(coverage).to_csv(OUT/'target_coverage.csv',index=False,encoding='utf-8-sig')
    cand=pd.concat(candidates,ignore_index=True);cand.to_parquet(OUT/'first_pack_candidates.parquet',index=False)
    crows=[]
    for (task,name),g in cand.groupby(['task','model']):
        g=g[g.y.notna()]
        for period,z in periods(g).items():
            for distance in ['all']+DISTANCES:
                d=z if distance=='all' else z[z.race_distance_m.eq(distance)]
                if d.empty:continue
                m,lo,hi,_=interval(d.hit,d.race_date);miss=d[d.hit.eq(0)]
                crows.append({'task':task,'model':name,'period':period,'distance':str(distance),'races':len(d),
                    'hits':int(d.hit.sum()),'hit_rate':m,'date_low':lo,'date_high':hi,'misses':len(miss),
                    'miss_second':int(miss.y.eq(1).sum()),'miss_behind':int(miss.y.eq(2).sum()),
                    'miss_second_rate':float(miss.y.eq(1).mean()) if len(miss) else np.nan})
    pd.DataFrame(crows).to_csv(OUT/'candidate_metrics.csv',index=False,encoding='utf-8-sig')
    # Eight prespecified primary contrasts, with each race weighted equally.
    rs=sc.groupby(['race_id','race_date','year','distance','task','model'],as_index=False)[['brier','nll','accuracy']].mean()
    rs.to_parquet(OUT/'race_scores.parquet',index=False)
    contrasts=[]
    for task in TASKS:
        t=rs[rs.task==task]
        for ref in ['H','P']:
            d=t[t.model.eq('F')].merge(t[t.model.eq(ref)],on=['race_id','race_date','year','distance','task'],suffixes=('_F','_ref'),validate='one_to_one')
            for period,z in periods(d).items():
                if z.empty:continue
                m,lo,hi,p=interval(z.brier_F-z.brier_ref,z.race_date)
                contrasts.append({'task':task,'comparison':'F-'+ref,'period':period,'races':len(z),'estimate':m,'low':lo,'high':hi,'p':p,
                                  'primary':task in POINTS and period=='all_eval'})
    contrasts=pd.DataFrame(contrasts);mask=contrasts.primary
    contrasts['bh_q_primary8']=np.nan;contrasts.loc[mask,'bh_q_primary8']=bh(contrasts.loc[mask,'p'])
    contrasts.to_csv(OUT/'paired_comparisons.csv',index=False,encoding='utf-8-sig')
    # Distances have a per-task and per-year support gate, not just a pooled N.
    for year in [2024,2025,2026]:
        cut=f'{year-1}-12-30'
        for task in POINTS:
            for dist in DISTANCES:
                tr=a[a.race_date.le(cut)&a.race_distance_m.eq(dist)&a['y_'+task].notna()]
                te=a[a.year.eq(year)&a.race_distance_m.eq(dist)&a['y_'+task].notna()]
                support.append({'year':year,'task':task,'distance':dist,'train_races':tr.race_id.nunique(),'eval_races':te.race_id.nunique(),
                    'eval_days':te.race_date.nunique(),'supported':tr.race_id.nunique()>=50 and te.race_id.nunique()>=30 and te.race_date.nunique()>=15,
                    'alias':task=='c3' and dist==800})
    pd.DataFrame(support).to_csv(OUT/'distance_support.csv',index=False,encoding='utf-8-sig')
    # First-pack count and coherent subset diagnostics.
    cp=pd.read_parquet(OUT/'count_predictions.parquet')
    joint=pd.read_parquet(OUT/'joint_early_predictions.parquet')
    jc=joint.drop_duplicates(['race_id','model']).merge(cp[cp.model.eq('F')][['race_id','y_count']],on='race_id',validate='many_to_one')
    jc=jc.rename(columns={'count_p1':'p0','count_p2':'p1','count_p3plus':'p2'})
    cp['expected_leaders']=np.nan
    for year in [2024,2025,2026]:
        tr=a[a.race_date.le(f'{year-1}-12-30')&a.y_s1f.notna()]
        count=tr.assign(first=tr.y_s1f.eq(0)).groupby('race_id')['first'].sum()
        cp.loc[cp.year.eq(year)&cp.model.eq('H'),'expected_leaders']=count.mean()
    allcount=pd.concat([cp,jc],ignore_index=True)
    actual=a[a.y_s1f.notna()].assign(first=a.loc[a.y_s1f.notna(),'y_s1f'].eq(0)).groupby('race_id')['first'].sum()
    cm=[]
    for model,g in allcount.groupby('model'):
        for period,z in periods(g[g.y_count.notna()]).items():
            if z.empty:continue
            p=z[['p0','p1','p2']].to_numpy();y=z.y_count.to_numpy(int)
            expected=z.expected_leaders;truth=actual.reindex(z.race_id).to_numpy()
            cm.append({'model':model,'period':period,'races':len(z),'accuracy':float(np.mean(p.argmax(axis=1)==y)),
                'brier':float(np.square(p-np.eye(3)[y]).sum(axis=1).mean()),'nll':float(-np.log(np.maximum(p[np.arange(len(y)),y],1e-15)).mean()),
                'count_mae':float(np.abs(expected-truth).mean()) if expected.notna().all() else np.nan})
    pd.DataFrame(cm).to_csv(OUT/'count_metrics.csv',index=False,encoding='utf-8-sig')
    # A mechanically selected retrospective example, no best-case selection.
    race=a.sort_values(['race_date','race_number']).iloc[-1].race_id
    ex=a[a.race_id.eq(race)][META+['y_'+t for t in TASKS]].copy()
    for t in TASKS:
        z=pr[pr.race_id.eq(race)&pr.task.eq(t)&pr.model.eq('F')]
        k=3 if t in POINTS else 2
        for c in range(k):ex[t+'_p'+str(c)]=ex.api_record_id.map(z.set_index('api_record_id')['p'+str(c)])
    for col in ['p_first','p_solo','count_p1','count_p2','count_p3plus','expected_leaders']:
        z=joint[joint.race_id.eq(race)&joint.model.eq('J')].set_index('api_record_id')
        ex['joint_'+col]=ex.api_record_id.map(z[col])
    ex.to_csv(OUT/'example_last_race.csv',index=False,encoding='utf-8-sig')
    latest=a.sort_values(['race_date','race_number']).drop_duplicates('horse_id',keep='last')
    latest[['horse_id','horse_name','race_date','race_distance_m']+[c for c in latest if c.startswith(('h10_','same10_'))]].to_parquet(OUT/'latest_prestart_profiles.parquet',index=False)
    save(OUT/'diagnostics_receipt.json',{'status':'computed_pending_independent_verification','primary_contrasts':int(mask.sum()),
         'example_race':race,'profile_note':'latest retained pre-start history per horse; different as-of dates, not one current card'})
    print(met[(met.distance=='all')&met.period.eq('all_eval')&met.task.isin(POINTS)][['task','model','rows','races','accuracy','brier','nll']].to_string(index=False),flush=True)
    print(pd.DataFrame(cm).query("period=='2026'").to_string(index=False),flush=True)

if __name__=='__main__':main()
