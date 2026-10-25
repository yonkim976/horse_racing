"""Annual frozen phase models, simple historical controls, coherent early subsets."""
from datetime import date,timedelta
import json
import numpy as np
import pandas as pd
import lightgbm as lgb
from common import *

PARAMS=dict(n_estimators=180,learning_rate=.04,num_leaves=15,min_child_samples=100,
            reg_lambda=10,random_state=20261021,n_jobs=4,verbosity=-1,deterministic=True,force_col_wise=True)
META=['api_record_id','race_id','race_date','year','race_distance_m','field_n','horse_id','horse_name','horse_number',
      'h10_s1f_0_n','h10_slots','finish_position']

def historical_probabilities(train,test,task):
    k=3 if task in POINTS else 2
    good=train['y_'+task].notna();tr=train[good];y=tr['y_'+task].to_numpy(int)
    w=1/tr.groupby('race_id').api_record_id.transform('size')
    prior=np.bincount(y,weights=w,minlength=k);prior/=prior.sum()
    if task in POINTS:
        count=test['h10_'+task+'_0_n'].to_numpy(float)
        means=test[['h10_'+task+'_'+str(i)+'_mean' for i in range(3)]].fillna(0).to_numpy(float)
        return (means*count[:,None]+3*prior)/(count[:,None]+3)
    count=test['h10_'+task+'_n'].to_numpy(float)
    rate=(test['h10_'+task+'_mean'].fillna(0).to_numpy()*count+3*prior[1])/(count+3)
    return np.column_stack([1-rate,rate])

def race_features(a):
    cols=['prior_s1f','h10_s1f_0_n','h10_s1f_speedrank_mean','h10_s1f_0_mean','h5_s1f_0_mean',
          'same10_s1f_0_mean','h10_g1f_speedrank_mean','h10_finish_rank_mean','h10_slots','h10_gap']
    x=a.groupby('race_id')[cols].agg(['mean','std','max','min'])
    x.columns=['r_'+c+'_'+s for c,s in x.columns]
    meta=a.groupby('race_id',sort=True)[['race_date','year','race_distance_m','field_n','base_month','y_count']].first()
    x=x.join(meta)
    x['r_strong_count']=a.assign(strong=a.prior_s1f.ge(.5)&a.h10_s1f_0_n.ge(3)).groupby('race_id').strong.sum()
    x['r_early_sum']=a.groupby('race_id').prior_s1f.sum()
    return x.reset_index()

def subset_distribution(p,q=None):
    """All nonempty first-pack subsets; count categories are 1, 2, and 3+."""
    n=len(p);assert 2<=n<=16
    bits=((np.arange(1,2**n,dtype=np.uint32)[:,None]>>np.arange(n,dtype=np.uint32))&1).astype(float)
    p=np.clip(p,1e-8,1-1e-8)
    logw=bits@np.log(p)+(1-bits)@np.log1p(-p)
    w=np.exp(logw-logw.max());w/=w.sum()
    counts=bits.sum(axis=1).astype(int);buckets=np.minimum(counts,3)-1
    if q is not None:
        total=np.bincount(buckets,weights=w,minlength=3)
        w=w*np.asarray(q)[buckets]/total[buckets];w/=w.sum()
    marg=w@bits;solo=w[counts==1]@bits[counts==1]
    bucket=np.bincount(buckets,weights=w,minlength=3)
    return {'p':marg,'solo':solo,'bucket':bucket,'expected':float(w@counts)}

def main():
    a=pd.read_parquet(OUT/'features_and_targets.parquet')
    contract=json.loads((OUT/'feature_contract.json').read_text())
    models=OUT/'models';models.mkdir(exist_ok=False)
    save(OUT/'training_input_manifest.json',{'files':manifest([HERE/'PLAN.md',HERE/'experiment.py',OUT/'features_and_targets.parquet',OUT/'feature_contract.json',OUT/'build_verification.json']),
                                            'parameters':PARAMS})
    assert json.loads((OUT/'build_verification.json').read_text())['status']=='passed'
    assert not any(c.startswith(('obs_','y_')) for cols in [contract['P'],contract['F']] for c in cols)
    assert all(not any(t in c for t in ['horse_name','horse_id','jockey','trainer','age_2026']) for c in contract['F'])
    predicted=[];audit=[];count_pred=[];joint=[]
    races=race_features(a);races.to_parquet(OUT/'race_features.parquet',index=False)
    rcols=[c for c in races if c.startswith('r_')]+['race_distance_m','field_n','base_month']
    for year in [2024,2025,2026]:
        cutoff=(date(year,1,1)-timedelta(days=2)).isoformat()
        train=a[a.race_date.le(cutoff)];test=a[a.year.eq(year)].copy()
        for task in TASKS:
            tr=train[train['y_'+task].notna()];y=tr['y_'+task].to_numpy(int)
            w=(1/tr.groupby('race_id').api_record_id.transform('size')).to_numpy();w/=w.mean()
            for name in ['H','P','F']:
                if name=='H':p=historical_probabilities(train,test,task)
                else:
                    cols=contract[name];model=lgb.LGBMClassifier(**PARAMS)
                    model.fit(tr[cols],y,sample_weight=w)
                    assert np.array_equal(model.classes_,np.arange(3 if task in POINTS else 2))
                    p=model.predict_proba(test[cols])
                    path=models/f'{year}_{task}_{name}.txt';model.booster_.save_model(path)
                    audit.append({'year':year,'task':task,'model':name,'train_rows':len(tr),'train_races':tr.race_id.nunique(),
                        'train_last_date':tr.race_date.max(),'cutoff':cutoff,'test_rows':len(test),'columns':cols,
                        'path':str(path.relative_to(HERE)),'model_sha256':sha(path),'trees':model.booster_.num_trees()})
                assert np.isfinite(p).all() and np.allclose(p.sum(axis=1),1,atol=1e-10)
                z=test[META].copy();z['task']=task;z['model']=name;z['y']=test['y_'+task]
                if task=='c3':z['alias_s1f']=z.race_distance_m.eq(800)
                for j in range(p.shape[1]):z['p'+str(j)]=p[:,j]
                predicted.append(z)
        rt=races[races.race_date.le(cutoff)&races.y_count.notna()];re=races[races.year.eq(year)]
        cm=lgb.LGBMClassifier(**PARAMS);cm.fit(rt[rcols],rt.y_count.astype(int))
        cp=cm.predict_proba(re[rcols]);path=models/f'{year}_count_F.txt';cm.booster_.save_model(path)
        audit.append({'year':year,'task':'count','model':'F','train_rows':len(rt),'train_races':len(rt),'train_last_date':rt.race_date.max(),
            'cutoff':cutoff,'test_rows':len(re),'columns':rcols,'path':str(path.relative_to(HERE)),'model_sha256':sha(path),'trees':cm.booster_.num_trees()})
        prior=np.bincount(rt.y_count.astype(int),minlength=3)/len(rt)
        for name,probs in [('H',np.tile(prior,(len(re),1))),('F',cp)]:
            z=re[['race_id','race_date','year','race_distance_m','field_n','y_count']].copy();z['model']=name
            for j in range(3):z['p'+str(j)]=probs[:,j]
            count_pred.append(z)
        early=next(z for z in reversed(predicted) if z.year.iloc[0]==year and z.task.iloc[0]=='s1f' and z.model.iloc[0]=='F')
        qmap=dict(zip(re.race_id,cp))
        for race,g in early.groupby('race_id',sort=False):
            for name,q in [('I',None),('J',qmap[race])]:
                s=subset_distribution(g.p0.to_numpy(),q)
                for pos,r in enumerate(g.itertuples()):
                    joint.append({'api_record_id':r.api_record_id,'race_id':race,'race_date':r.race_date,'year':year,
                        'race_distance_m':r.race_distance_m,'field_n':r.field_n,'horse_id':r.horse_id,'horse_number':r.horse_number,
                        'model':name,'p_first':s['p'][pos],'p_solo':s['solo'][pos],
                        'count_p1':s['bucket'][0],'count_p2':s['bucket'][1],'count_p3plus':s['bucket'][2],
                        'expected_leaders':s['expected']})
        print('Annual frozen fits complete',year,len(test),'runners',flush=True)
    pr=pd.concat(predicted,ignore_index=True)
    # 800m S1F and 3C are the same measured point, not a new middle phase.
    for name in ['H','P','F']:
        src=pr[(pr.task=='s1f')&(pr.model==name)&pr.race_distance_m.eq(800)].set_index('api_record_id')
        mask=(pr.task=='c3')&(pr.model==name)&pr.race_distance_m.eq(800)
        pr.loc[mask,['p0','p1','p2']]=src.loc[pr.loc[mask,'api_record_id'],['p0','p1','p2']].to_numpy()
    pr.to_parquet(OUT/'predictions.parquet',index=False)
    pd.concat(count_pred,ignore_index=True).to_parquet(OUT/'count_predictions.parquet',index=False)
    pd.DataFrame(joint).to_parquet(OUT/'joint_early_predictions.parquet',index=False)
    save(OUT/'fit_audit.json',audit)
    save(OUT/'fit_receipt.json',{'status':'fitted_pending_independent_verification','fitted_models':len(audit),
         'prediction_rows':len(pr),'parameters':PARAMS,'production_changed':False})

if __name__=='__main__':main()
