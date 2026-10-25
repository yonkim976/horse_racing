"""Fixed, annual out-of-time classifiers and held-out probability evaluation."""

import time
import warnings

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.special import logit
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression,Ridge
from sklearn.metrics import average_precision_score,brier_score_loss,log_loss,roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder,StandardScaler

from prepare import HERE,OUT,dump,sha

MODELS=HERE/'models'
CONTEXT_NUM=['age','distance','gate','gate_relative','field_size','debut_count','field_experienced_other',
    'other_prior_top3_mean5','other_prior_finish_p5','other_best_top3',
    'jockey_history_n','jockey_prior_win','jockey_prior_top3','trainer_history_n','trainer_prior_win','trainer_prior_top3']
CONTEXT_CAT=['meet','month','sex','origin','grade']
ADMIN_NUM=['trial_gap_days','trial_attempts','trial_failures','trial_practices','new_passes','trial_passes',
    'trial_age','trial_weight','trial_body_weight','trial_moisture','valid_sections','cross_venue_trial','trial_session_n']
ADMIN_CAT=['trial_meet','trial_month','trial_moisture_band']
TOTAL=['finish','best_finish','trial_finish_change','trial_gap_to_fastest','trial_time_pct','trial_rank_relative','finish_resid']
SECTIONS=['early','middle1','middle2','late','last600','last400','fs200','fs600','trial_position_gain',
          'early_resid','middle1_resid','middle2_resid','late_resid']
GROUPS={
    'context':(CONTEXT_NUM,CONTEXT_CAT),
    'trial_admin':(CONTEXT_NUM+ADMIN_NUM,CONTEXT_CAT+ADMIN_CAT),
    'total':(CONTEXT_NUM+ADMIN_NUM+TOTAL,CONTEXT_CAT+ADMIN_CAT),
    'sections':(CONTEXT_NUM+ADMIN_NUM+TOTAL+SECTIONS,CONTEXT_CAT+ADMIN_CAT),
    'trial_focused':(['age']+ADMIN_NUM+TOTAL+SECTIONS,['meet','sex']+ADMIN_CAT),
}


def reference_features(cohort,year):
    trials=pd.read_parquet(OUT/'trial_reference_inputs.parquet')
    trials=trials[trials.date.lt(f'{year-1}-01-01')&trials.new_reason&trials.passed].copy()
    num=['trial_age','trial_weight'];cat=['trial_meet','trial_month','trial_sex','trial_moisture_band']
    metadata={}
    out=cohort.copy()
    for target in ['finish','early','middle1','middle2','late']:
        z=trials[trials[target].notna()].copy()
        pre=ColumnTransformer([('num',Pipeline([('impute',SimpleImputer(strategy='median')),('scale',StandardScaler())]),num),
            ('cat',OneHotEncoder(handle_unknown='ignore',sparse_output=False),cat)],sparse_threshold=0)
        reg=Pipeline([('pre',pre),('ridge',Ridge(alpha=10))])
        for frame in [z,out]:
            for col in cat:frame[col]=frame[col].fillna('미상').astype(str)
        reg.fit(z[num+cat],z[target])
        expected=reg.predict(out[num+cat])
        out[target+'_resid']=out[target].to_numpy(float)-expected
        ridge=reg.named_steps['ridge'];enc=reg.named_steps['pre']
        metadata[target]=dict(n=len(z),last_trial=str(z.date.max().date()),coef=ridge.coef_.tolist(),intercept=float(ridge.intercept_),
            numeric=num,categorical=cat,
            imputer=enc.named_transformers_['num'].named_steps['impute'].statistics_.tolist(),
            mean=enc.named_transformers_['num'].named_steps['scale'].mean_.tolist(),
            scale=enc.named_transformers_['num'].named_steps['scale'].scale_.tolist(),
            categories=[list(x) for x in enc.named_transformers_['cat'].categories_])
        assert z.date.max()<pd.Timestamp(f'{year-1}-01-01')
    dump(OUT/f'reference_{year}.json',metadata)
    out[['row_key','finish_resid','early_resid','middle1_resid','middle2_resid','late_resid']].to_parquet(OUT/f'reference_features_{year}.parquet',index=False)
    return out


def fit_schema(frame,num,cat):
    with warnings.catch_warnings():
        warnings.simplefilter('ignore',RuntimeWarning)
        values=frame[num].apply(pd.to_numeric,errors='coerce').to_numpy(float)
        med=np.nanmedian(values,axis=0);med=np.where(np.isfinite(med),med,0)
    filled=np.where(np.isfinite(values),values,med)
    scale=filled.std(axis=0);scale=np.where(scale>1e-10,scale,1.)
    categories={col:sorted(frame[col].fillna('미상').astype(str).unique()) for col in cat}
    return dict(numeric=num,categorical=cat,medians=med.tolist(),scales=scale.tolist(),categories=categories)


def encode(frame,schema):
    v=frame[schema['numeric']].apply(pd.to_numeric,errors='coerce').to_numpy(float)
    missing=~np.isfinite(v);v=np.where(missing,schema['medians'],v)
    pieces=[(v-np.array(schema['medians']))/np.array(schema['scales']),missing.astype(float)]
    for col in schema['categorical']:
        values=frame[col].fillna('미상').astype(str).to_numpy()
        pieces.append(np.column_stack([values==x for x in schema['categories'][col]]).astype(float))
    return np.column_stack(pieces)


def run():
    MODELS.mkdir(exist_ok=True)
    all_rows=pd.read_parquet(OUT/'debut_cohort.parquet')
    d=all_rows[all_rows.primary_eligible].reset_index(drop=True)
    assert d.horse_id.is_unique
    predictions=[];metadata=[]
    for year in [2024,2025,2026]:
        z=reference_features(d,year)
        train=z[z.year<=year-2];cal=z[z.year.eq(year-1)];test=z[z.year.eq(year)]
        assert train.date.max()<cal.date.min() and cal.date.max()<test.date.min()
        assert set(train.horse_id).isdisjoint(cal.horse_id) and set(cal.horse_id).isdisjoint(test.horse_id)
        for algorithm in ['lightgbm','logistic']:
            for group,(num,cat) in GROUPS.items():
                if algorithm=='logistic' and group not in ['context','sections']:continue
                print('FIT',year,algorithm,group,'train/cal/test',len(train),len(cal),len(test),flush=True)
                schema=fit_schema(train,num,cat);name=f'{algorithm}_{group}_{year}'
                dump(MODELS/f'{name}_schema.json',schema)
                xtr,xca,xte=[encode(s,schema) for s in [train,cal,test]]
                for target in ['top3','win']:
                    if algorithm=='lightgbm':
                        clf=lgb.LGBMClassifier(n_estimators=200,learning_rate=.04,num_leaves=7,min_child_samples=80,
                            reg_lambda=10,n_jobs=1,random_state=20261025,verbosity=-1)
                    else:clf=LogisticRegression(C=.3,max_iter=3000,solver='lbfgs')
                    clf.fit(xtr,train[target])
                    # Both stages use only the prior calibration year, never the evaluation year.
                    raw_cal=np.clip(clf.predict_proba(xca)[:,1],1e-6,1-1e-6)
                    raw_test=np.clip(clf.predict_proba(xte)[:,1],1e-6,1-1e-6)
                    platt=LogisticRegression(C=100,max_iter=2000)
                    platt.fit(logit(raw_cal).reshape(-1,1),cal[target])
                    calibrated_cal=platt.predict_proba(logit(raw_cal).reshape(-1,1))[:,1]
                    probability=platt.predict_proba(logit(raw_test).reshape(-1,1))[:,1]
                    threshold=float(np.quantile(calibrated_cal,.8))
                    output=test[['row_key','horse_id','meet','date','year','race_key','top3','win','field_size','trial_gap_days','finish','valid_sections']].copy()
                    output['algorithm']=algorithm;output['model']=group;output['target']=target
                    output['p_raw']=raw_test;output['p']=probability;output['high_threshold']=threshold
                    output['high_group']=probability>=threshold
                    predictions.append(output)
                    model_file=MODELS/f'{name}_{target}.txt'
                    if algorithm=='lightgbm':clf.booster_.save_model(str(model_file))
                    else:
                        model_file=MODELS/f'{name}_{target}_coef.json'
                        dump(model_file,dict(coef=clf.coef_[0].tolist(),intercept=float(clf.intercept_[0])))
                    info=dict(year=year,algorithm=algorithm,model=group,target=target,train_n=len(train),cal_n=len(cal),test_n=len(test),
                        train_end=str(train.date.max().date()),cal_start=str(cal.date.min().date()),cal_end=str(cal.date.max().date()),
                        test_start=str(test.date.min().date()),test_end=str(test.date.max().date()),
                        train_keys_sha256=__import__('hashlib').sha256('\n'.join(train.row_key).encode()).hexdigest(),
                        platt_coef=float(platt.coef_[0,0]),platt_intercept=float(platt.intercept_[0]),high_threshold=threshold,
                        schema_file=str((MODELS/f'{name}_schema.json').relative_to(HERE)),model_file=str(model_file.relative_to(HERE)),model_sha256=sha(model_file))
                    metadata.append(info)
    p=pd.concat(predictions,ignore_index=True)
    p.to_parquet(OUT/'predictions.parquet',index=False)
    dump(OUT/'model_manifest.json',metadata)
    return p


def score(g):
    y=g[g.target.iloc[0]].to_numpy();p=g.p.to_numpy()
    return dict(n=len(g),events=int(y.sum()),event_rate=float(y.mean()),mean_p=float(p.mean()),
        auc=float(roc_auc_score(y,p)) if len(np.unique(y))>1 else None,
        ap=float(average_precision_score(y,p)),brier=float(brier_score_loss(y,p)),logloss=float(log_loss(y,p,labels=[0,1])))


def evaluate(p):
    metrics=[];high=[];calibration=[];selection=[];intervals=[];single=[]
    for algorithm,pp in p.groupby('algorithm'):
        subsets=[('all',pp)]+[(str(year),pp[pp.year.eq(year)]) for year in [2024,2025,2026]]+[(meet,pp[pp.meet.eq(meet)]) for meet in ['서울','부산']]
        for subset,z in subsets:
            for (model,target),g in z.groupby(['model','target']):
                tags=dict(algorithm=algorithm,subset=subset,model=model,target=target)
                metrics.append(dict(**tags,**score(g)))
                s=g[g.high_group]
                high.append(dict(**tags,n=len(g),selected_n=len(s),selected_share=len(s)/len(g),selected_events=int(s[target].sum()),
                    selected_event_rate=float(s[target].mean()) if len(s) else None,selected_mean_p=float(s.p.mean()) if len(s) else None,
                    selected_wins=int(s.win.sum()),selected_top3=int(s.top3.sum()),
                    selected_win_rate=float(s.win.mean()) if len(s) else None,selected_top3_rate=float(s.top3.mean()) if len(s) else None))
                for band,s in g.groupby(pd.cut(g.p,[0,.05,.1,.2,.3,.4,.5,.7,1.],include_lowest=True),observed=True):
                    calibration.append(dict(**tags,probability_band=str(band),n=len(s),events=int(s[target].sum()),actual_rate=float(s[target].mean()),mean_p=float(s.p.mean())))
                # Compare only linked debutants, not all runners in a race.
                races=g.groupby('race_key').filter(lambda f:len(f)>=2)
                if len(races):
                    best=races.sort_values(['race_key','p','horse_id'],ascending=[True,False,True]).groupby('race_key').head(1)
                    baseline=races.groupby('race_key')[target].mean().mean()
                    selection.append(dict(**tags,races=len(best),selected_events=int(best[target].sum()),
                        selected_rate=float(best[target].mean()),random_debutant_rate=float(baseline)))
            for target in ['top3','win']:
                zz=z[z.target.eq(target)]
                ref=zz[zz.model.eq('context')][['row_key','date',target]].copy()
                wide=zz.pivot(index='row_key',columns='model',values='p')
                ref=ref.merge(wide,on='row_key',validate='one_to_one')
                y=ref[target].to_numpy(float)
                models=list(wide.columns)
                contrasts=[('total','context'),('sections','context'),('sections','total'),('total','trial_admin')] if algorithm=='lightgbm' else [('sections','context')]
                counts=ref.groupby('date').size().to_numpy()
                rng=np.random.default_rng(20261025)
                weights=rng.multinomial(len(counts),np.full(len(counts),1/len(counts)),size=2000)
                denom=weights@counts
                for loss in ['brier','logloss']:
                    losses={}
                    for model in models:
                        prob=np.clip(ref[model].to_numpy(float),1e-12,1-1e-12)
                        losses[model]=(prob-y)**2 if loss=='brier' else -y*np.log(prob)-(1-y)*np.log1p(-prob)
                    for extended,baseline in contrasts:
                        delta=losses[extended]-losses[baseline]
                        daily=pd.Series(delta,index=ref.index).groupby(ref.date).sum().to_numpy()
                        boot=weights@daily/denom
                        intervals.append(dict(algorithm=algorithm,subset=subset,target=target,loss=loss,extended=extended,baseline=baseline,
                            estimate=float(delta.mean()),ci_low=float(np.quantile(boot,.025)),ci_high=float(np.quantile(boot,.975)),
                            n=len(ref),dates=len(counts),bootstrap_repetitions=2000))
    # Time directions are fixed before seeing outcomes; core support is identical for all scores.
    d=pd.read_parquet(OUT/'debut_cohort.parquet');pieces=[]
    for year in [2024,2025,2026]:
        f=pd.read_parquet(OUT/f'reference_features_{year}.parquet')
        pieces.append(d[d.year.eq(year)&d.primary_eligible].merge(f,on='row_key',validate='one_to_one'))
    q=pd.concat(pieces,ignore_index=True);q=q[q.valid_sections.eq(True)]
    for subset,z in [('all',q)]+[(meet,q[q.meet.eq(meet)]) for meet in ['서울','부산']]:
        for target in ['top3','win']:
            for feature in ['finish','early','late','finish_resid','early_resid','late_resid']:
                single.append(dict(subset=subset,target=target,feature=feature,n=len(z),auc=float(roc_auc_score(z[target],-z[feature]))))
    pd.DataFrame(metrics).to_csv(OUT/'metrics.csv',index=False)
    pd.DataFrame(high).to_csv(OUT/'high_group.csv',index=False)
    pd.DataFrame(calibration).to_csv(OUT/'calibration.csv',index=False)
    pd.DataFrame(selection).to_csv(OUT/'debutant_selection.csv',index=False)
    pd.DataFrame(intervals).to_csv(OUT/'paired_loss_intervals.csv',index=False)
    pd.DataFrame(single).to_csv(OUT/'single_time_auc.csv',index=False)
    q['time_band']=pd.cut(q.finish,[0,62,63,64,65,100],labels=['<=62','62~63','63~64','64~65','>65'])
    q.groupby(['meet','time_band'],observed=True).agg(n=('row_key','size'),wins=('win','sum'),top3=('top3','sum'),win_rate=('win','mean'),top3_rate=('top3','mean')).reset_index().to_csv(OUT/'heldout_time_bands.csv',index=False)
    print('EVALUATED',p.row_key.nunique(),'test debutants',flush=True)


if __name__=='__main__':
    start=time.time();predictions=run();evaluate(predictions)
    print('COMPLETE seconds',round(time.time()-start,1),flush=True)
