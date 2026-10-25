"""Shared, deterministic, research-only feature and model calculations."""
import itertools, json
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.special import logsumexp
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge, LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler, OneHotEncoder
from audit import HERE, ROOT, DB, BANDS, sha, save, csv
NUM=['hist_mean','hist_last','log_same_count','log_starts','log_gap','log_same_gap','event_age','age_squared','weight','field_n','relative_mean','relative_last','relative_rank']
CAT=['grade','sex','era']
SEED=20261007

def load():
    d=pd.read_csv(HERE/'audit/source_rows.csv',dtype={'horse_id':str},low_memory=False).set_index('api_record_id',drop=False)
    d.index=d.index.astype(int);d['api_record_id']=d.index
    d['field_n']=d.groupby('race_id').api_record_id.transform('size')
    histories=json.loads((HERE/'audit/history_ids.json').read_text())
    return d,histories

def features(d,histories,correction=None,n_recent=5):
    q=d[(d.year>=2017)&d.race_distance_m.isin([1000,1110])].copy()
    time=d.finish_time_seconds.copy()
    if correction is not None:time=time-correction.reindex(d.index).fillna(0)
    hmean=[];hlast=[]
    for rid in q.index:
        ids=histories[str(rid)][-n_recent:]
        values=time.loc[ids].to_numpy() if ids else []
        hmean.append(float(np.mean(values)) if len(values) else np.nan)
        hlast.append(float(values[-1]) if len(values) else np.nan)
    q['hist_mean']=hmean;q['hist_last']=hlast
    for dest,src in [('log_same_count','same_count'),('log_starts','observed_starts'),('log_gap','days_since_start'),('log_same_gap','days_since_same')]:q[dest]=np.log1p(q[src])
    age=pd.to_numeric(q.age_at_race_raw,errors='coerce');q['event_age']=age.where(age>0);q['age_squared']=q.event_age**2
    q['weight']=q.carried_weight_kg.where(q.carried_weight_kg>0)
    q['grade']=q.rank_class_raw.fillna('unknown');q['sex']=q.sex_at_race_raw.fillna('unknown');q['era']=np.where(q.year<=2018,'2017_2018','2019_plus')
    for col in ['mean','last']:q['relative_'+col]=q['hist_'+col]-q.groupby('race_id')['hist_'+col].transform('median')
    q['relative_rank']=(q.groupby('race_id').hist_mean.rank(method='average')-1)/(q.field_n-1)
    return q

def pipe(kind):
    prep=ColumnTransformer([('numeric',Pipeline([('impute',SimpleImputer(strategy='median',add_indicator=True,keep_empty_features=True)),('scale',StandardScaler())]),NUM),('category',OneHotEncoder(handle_unknown='ignore',sparse_output=False),CAT)],remainder='drop',sparse_threshold=0)
    estimator=Ridge(alpha=10) if kind=='time' else LogisticRegression(C=1,max_iter=2000,solver='lbfgs',random_state=SEED)
    return Pipeline([('prep',prep),('model',estimator)])

def fit(q,kind):
    model=pipe(kind); w=(1/q.field_n).to_numpy(copy=True);w/=w.mean()
    y=q.finish_time_seconds if kind=='time' else (q.finish_position<=3).astype(int)
    model.fit(q[NUM+CAT],y,model__sample_weight=w)
    return model

def model_record(model):
    prep=model.named_steps['prep'];m=model.named_steps['model'];numeric=prep.named_transformers_['numeric']
    return {'features':list(prep.get_feature_names_out()),'coef':m.coef_.tolist(),'intercept':np.asarray(m.intercept_).tolist(),'numeric_imputer_statistics':numeric.named_steps['impute'].statistics_.tolist(),'numeric_indicator_indices':numeric.named_steps['impute'].indicator_.features_.tolist(),'scale_mean':numeric.named_steps['scale'].mean_.tolist(),'scale_std':numeric.named_steps['scale'].scale_.tolist(),'category_levels':[x.tolist() for x in prep.named_transformers_['category'].categories_]}

def phase(ds):
    dates=pd.to_datetime(ds)
    # Exact continuous calendar phase, with leap-year denominator.
    return 2*np.pi*(dates.dt.dayofyear.to_numpy()-1)/np.where(dates.dt.is_leap_year,366,365)

def design(g,mode='environment',spec=None):
    if mode=='environment':
        numeric=['race_number','field_n','event_age','weight','log_starts','hist_mean','missing_fraction']
        cats=['year','grade'];z=pd.DataFrame(index=g.index)
        for c in numeric:z[c]=g[c].astype(float)
        p=phase(g.race_date)
        for k in [1,2]:z[f'sin{k}']=np.sin(k*p);z[f'cos{k}']=np.cos(k*p)
        for band in BANDS[1:]:z['band_'+band]=(g.band==band).astype(float)
        catg=g.copy()
    else:
        numeric=['hist_mean','hist_last','log_same_count','log_starts','log_gap','event_age','age_squared','weight']
        cats=['sex'];z=g[numeric].astype(float).copy();catg=g
        for k in range(1,10):z[f'number_{k}']=(g.horse_number==k).astype(float)
    if spec is None:
        spec={'mode':mode,'numeric':numeric,'medians':{},'levels':{c:sorted(catg[c].astype(str).unique()) for c in cats}}
        for c in numeric:spec['medians'][c]=float(z[c].median()) if z[c].notna().any() else 0.
    for c in numeric:
        z[c+'_missing']=z[c].isna().astype(float);z[c]=z[c].fillna(spec['medians'][c])
    for c,levels in spec['levels'].items():
        for level in levels[1:]:z[f'{c}={level}']=(catg[c].astype(str)==level).astype(float)
    if 'columns' not in spec:
        spec['columns']=list(z.columns);spec['means']=z.mean().tolist();sd=z.std(ddof=0).replace(0,1);spec['sd']=sd.tolist()
    z=z.reindex(columns=spec['columns'],fill_value=0)
    arr=(z.to_numpy()-np.array(spec['means']))/np.array(spec['sd'])
    if mode=='environment':arr=np.column_stack([np.ones(len(g)),arr])
    else:
        frame=pd.DataFrame(arr,index=g.index);arr=(frame-frame.groupby(g.race_id).transform('mean')).to_numpy()
    return arr,spec

def ridge_solve(X,y,lam=1,weights=None,intercept=True):
    w=np.ones(len(y)) if weights is None else np.asarray(weights)
    penalty=np.eye(X.shape[1])*lam
    if intercept:penalty[0,0]=0
    bread=np.linalg.pinv(X.T@(w[:,None]*X)+penalty)
    beta=bread@(X.T@(w*y))
    return beta,bread

def cluster_cov(X,resid,bread,cluster,weights=None):
    w=np.ones(len(resid)) if weights is None else np.asarray(weights)
    scores=X*(resid*w)[:,None]
    sums=pd.DataFrame(scores).groupby(np.asarray(cluster)).sum().to_numpy()
    ng=len(sums);n,p=X.shape
    factor=ng/max(1,ng-1)*(n-1)/max(1,n-p)
    return bread@(sums.T@sums)@bread*factor

def contrast(spec,which):
    v=np.zeros(len(spec['columns'])+(spec['mode']=='environment'))
    offset=int(spec['mode']=='environment')
    if isinstance(which,str):v[spec['columns'].index(which)+offset]=1/np.array(spec['sd'])[spec['columns'].index(which)]
    else:
        for c,val in which.items():v[spec['columns'].index(c)+offset]=val/np.array(spec['sd'])[spec['columns'].index(c)]
    return v

def interval(v,beta,cov):
    point=float(v@beta);se=float(np.sqrt(max(0,v@cov@v)))
    return point,point-1.96*se,point+1.96*se

COMBOS={}
def combos(n):
    if n not in COMBOS:COMBOS[n]=np.array(list(itertools.combinations(range(n),3)),dtype=int)
    return COMBOS[n]

def probabilities(q,logits,tau):
    pred=np.zeros(len(q));records=[]
    for rid,indices in q.groupby('race_id',sort=False).indices.items():
        idx=np.asarray(indices);z=np.asarray(logits)[idx]/tau;c=combos(len(idx));s=z[c].sum(axis=1);joint=np.exp(s-logsumexp(s))
        p=np.bincount(c.ravel(),weights=np.repeat(joint,3),minlength=len(idx));pred[idx]=p
        assert np.isclose(p.sum(),3,atol=1e-10) and np.isclose(joint.sum(),1)
        truth=set(np.flatnonzero(q.iloc[idx].finish_position.to_numpy()<=3))
        # Stable ties by source input ordering, itself explicitly sorted by start number.
        top=np.argsort(-joint,kind='stable')[:6]
        hit=any(set(c[j])==truth for j in top)
        records.append({'race_id':rid,'six_combo_hit':int(hit),'six_predicted_mass':float(joint[top].sum()),'six_combos':'|'.join(','.join(map(str,q.iloc[idx].horse_number.to_numpy()[c[j]].astype(int))) for j in top)})
    return np.clip(pred,1e-12,1-1e-12),pd.DataFrame(records)

def losses(q,p):
    y=(q.finish_position.to_numpy()<=3).astype(float)
    return -y*np.log(p)-(1-y)*np.log1p(-p),(y-p)**2

def paired_ci(frame,base,col='log_loss',reps=1000,cluster='race_date'):
    # Metrics are race-equal within each period; date resampling preserves races/day.
    a=frame[['race_id',cluster,col]].merge(base[['race_id',col]],on='race_id',suffixes=('','_base'),validate='one_to_one')
    a['delta']=a[col]-a[col+'_base']; grouped=a.groupby(cluster).delta.agg(['sum','size'])
    rng=np.random.default_rng(SEED);n=len(grouped);ix=rng.integers(0,n,size=(reps,n))
    sums=grouped['sum'].to_numpy();counts=grouped['size'].to_numpy();boot=sums[ix].sum(axis=1)/counts[ix].sum(axis=1)
    return dict(delta=float(a.delta.mean()),lo=float(np.quantile(boot,.025)),hi=float(np.quantile(boot,.975)),se=float(boot.std(ddof=1)),clusters=n,races=len(a))
