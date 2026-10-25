"""Time-ordered retrospective next-record comparison using historical features."""
from pathlib import Path
import importlib.util
import json
import bisect
import sqlite3
import numpy as np
import pandas as pd
from scipy.stats import t
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler,OneHotEncoder
from sklearn.pipeline import Pipeline
from sklearn.linear_model import Ridge

H=Path(__file__).resolve().parent;ROOT=H.parents[2];PRE=H.parent/'20261008_weight_speed_v2'
sp=importlib.util.spec_from_file_location('form_prior',PRE/'analyze.py');a=importlib.util.module_from_spec(sp);sp.loader.exec_module(a)
sha=a.sha;PLAN=json.loads((H/'PLAN.json').read_text())
BASE=['old_median','old_mean','log_count','log_gap','last_burden','last_age','sin1','cos1','sin2','cos2'];RECENT=['last_time','mean2','mean5','slope5','sd5','best5','recent_vs_old'];BODY=['last_body','body_median6','body_sd6','body_deviation','body_delta','body_delta_pct','body_count','body_staleness'];CATS=['last_grade','last_sex']
def save(name,v):
    with (H/name).open('x',encoding='utf-8') as z:json.dump(v,z,ensure_ascii=False,indent=2,allow_nan=False)
def csv(name,df):
    with (H/name).open('x',encoding='utf-8') as z:df.to_csv(z,index=False)
def clean(v):
    if isinstance(v,dict):return {k:clean(z) for k,z in v.items()}
    if isinstance(v,list):return [clean(z) for z in v]
    if isinstance(v,np.generic):v=v.item()
    return None if isinstance(v,float) and not np.isfinite(v) else v
def bh(df,keys):
    for _,g in df.groupby(keys,dropna=False):df.loc[g.index,'q_BH']=a.old.bh(g.p.to_numpy())
    return df
def interval(values,g,weights=None):
    y=np.asarray(values,float);w=np.ones(len(g)) if weights is None else np.asarray(weights,float);w=w/w.sum();point=float(w@y);score=w*(y-point);variance=0
    for ids in [g.race_date,g.horse_id]:
        _,codes=np.unique(ids,return_inverse=True);sums=np.bincount(codes,weights=score);n=len(sums);variance+=n/max(n-1,1)*float(sums@sums)
    df=min(g.race_date.nunique(),g.horse_id.nunique())-1;se=np.sqrt(variance);critical=t.ppf(.975,df)
    return {'effect':point,'ci_lo':point-critical*se,'ci_hi':point+critical*se,'se':se,'p':float(2*t.sf(abs(point/se),df)) if se>0 else 1.,'critical_df':int(df)}
def contrast_group(g,col,groupcol,good,poor):
    z=g[g[groupcol].isin([good,poor])].copy();lo=z[groupcol].eq(good).to_numpy();hi=~lo
    if lo.sum()<30 or hi.sum()<30:return None
    # Influence-function covariance of difference between two group means.
    mu1=z.loc[lo,col].mean();mu2=z.loc[hi,col].mean();point=float(mu1-mu2);score=np.where(lo,(z[col]-mu1)/lo.sum(),-(z[col]-mu2)/hi.sum());variance=0
    for ids in [z.race_date,z.horse_id]:
        _,codes=np.unique(ids,return_inverse=True);sums=np.bincount(codes,weights=score);n=len(sums);variance+=n/(n-1)*float(sums@sums)
    df=min(z.race_date.nunique(),z.horse_id.nunique())-1;se=np.sqrt(variance);cr=t.ppf(.975,df)
    return {'effect':point,'ci_lo':point-cr*se,'ci_hi':point+cr*se,'p':float(2*t.sf(abs(point/se),df)) if se>0 else 1.,'good_rows':int(lo.sum()),'poor_rows':int(hi.sum()),'se':se}

def features():
    refs=[H/'PLAN.json',H/'analyze.py',PRE/'source_lineage.csv',PRE/'input_audit.json',a.old.OLD/'audit/source_rows.csv',a.old.OLD/'audit/history_ids.json',ROOT/'jeju/data/horse_exclusions.json',ROOT/'jeju/AGENTS.md',ROOT/'jeju/docs/JEJU_TRAINING_API_INPUT_CONTRACT_2026-10-01.md',H.parent/'20261001_daily_training_api_load/README.md',H.parent/'20261002_medical_db_load/README.md',H.parent/'20261008_body_change_optimum_sex_v2/decision.json']
    save('source_manifest.json',[{'path':str(p),'sha256':sha(p),'bytes':p.stat().st_size} for p in refs]);dbsha=sha(a.old.DB);assert dbsha==json.loads((PRE/'input_audit.json').read_text())['database_sha256']
    d,h=a.old.load();q=pd.read_csv(PRE/'source_lineage.csv',dtype={'horse_id':str},low_memory=False);q=q.merge(d[['api_record_id','field_n']].reset_index(drop=True).rename(columns={'field_n':'source_field_n'}),on='api_record_id',validate='one_to_one');assert q.field_n.eq(q.source_field_n).all()
    groups={k:g.sort_values(['race_date','api_record_id']) for k,g in q.groupby('horse_id')};features=[];trace=[];checked=0
    for row in q.itertuples():
        cutoff=(pd.Timestamp(row.race_date)-pd.Timedelta(days=2)).strftime('%Y-%m-%d');ids=h[str(row.api_record_id)][-10:]
        if len(ids)<5:continue
        z=d.loc[ids];assert z.horse_id.eq(row.horse_id).all() and z.race_distance_m.eq(row.race_distance_m).all() and z.race_date.le(cutoff).all();checked+=len(ids)
        times=z.finish_time_seconds.to_numpy(float);old=times[:-2];last=z.iloc[-1];gap=(pd.Timestamp(row.race_date)-pd.Timestamp(last.race_date)).days;dt=pd.Timestamp(row.race_date);ph=2*np.pi*(dt.dayofyear-1)/(366 if dt.is_leap_year else 365)
        r={'api_record_id':row.api_record_id,'horse_id':row.horse_id,'race_id':row.race_id,'race_date':row.race_date,'distance':int(row.race_distance_m),'year':row.year,'time':row.time,'history_cutoff':cutoff,'old_median':np.median(old),'old_mean':np.mean(old),'log_count':np.log1p(len(h[str(row.api_record_id)])),'gap':gap,'log_gap':np.log1p(gap),'last_burden':last.carried_weight_kg,'last_age':pd.to_numeric(last.age_at_race_raw,errors='coerce'),'last_grade':str(last.rank_class_raw),'last_sex':str(last.sex_at_race_raw),'sin1':np.sin(ph),'cos1':np.cos(ph),'sin2':np.sin(2*ph),'cos2':np.cos(2*ph),'last_time':times[-1],'mean2':np.mean(times[-2:]),'mean5':np.mean(times[-5:]),'slope5':float(np.polyfit(np.arange(5),times[-5:],1)[0]),'sd5':np.std(times[-5:]),'best5':np.min(times[-5:]),'recent_vs_old':times[-1]-np.median(old)}
        bg=groups[row.horse_id];end=bisect.bisect_right(bg.race_date.to_numpy(),cutoff);past=bg.iloc[max(0,end-6):end];mass=past.body_kg.to_numpy(float)
        assert past.race_date.le(cutoff).all();bids=past.api_record_id.astype(int).tolist()
        r.update({'last_body':mass[-1] if len(mass) else np.nan,'body_median6':np.median(mass) if len(mass) else np.nan,'body_sd6':np.std(mass) if len(mass)>1 else np.nan,'body_deviation':mass[-1]-np.median(mass[:-1]) if len(mass)>1 else np.nan,'body_delta':mass[-1]-mass[-2] if len(mass)>1 else np.nan,'body_delta_pct':100*(mass[-1]/mass[-2]-1) if len(mass)>1 else np.nan,'body_count':len(mass),'body_staleness':(dt-pd.Timestamp(past.race_date.iloc[-1])).days if len(mass) else np.nan})
        features.append(r);trace.append({'api_record_id':row.api_record_id,'horse_id':row.horse_id,'distance':int(row.race_distance_m),'race_date':row.race_date,'history_cutoff':cutoff,'time_history_ids':ids,'body_history_ids':bids})
    f=pd.DataFrame(features);f['eligible_in_race']=f.groupby('race_id').api_record_id.transform('size');f=f[f.eligible_in_race.ge(3)].copy();trace=[z for z in trace if z['api_record_id'] in set(f.api_record_id)]
    csv('features.csv',f);save('feature_lineage.json',trace)
    save('input_audit.json',{'target_source_rows':len(q),'eligible_rows':len(f),'eligible_races':f.race_id.nunique(),'eligible_horses':f.horse_id.nunique(),'history_endpoints_checked_before_race_filter':checked,'database_sha256':dbsha,'all_features_from_T_minus_2_event_history':True,'historical_publication_and_revisions_not_fully_verified':True,'current_race_body_weight_used':False,'full_career_body_baseline_used':False,'unknown_medical_absence_not_healthy':True})
    return f,q,dbsha

def make_model(nums):
    prep=ColumnTransformer([('numeric',Pipeline([('imputer',SimpleImputer(strategy='median',add_indicator=True,keep_empty_features=True)),('scale',StandardScaler())]),nums),('cat',OneHotEncoder(handle_unknown='ignore',sparse_output=False),CATS)],sparse_threshold=0)
    return Pipeline([('prep',prep),('ridge',Ridge(alpha=10))])
def record(m):
    pr=m.named_steps['prep'];nu=pr.named_transformers_['numeric'];rg=m.named_steps['ridge']
    return {'features':list(pr.get_feature_names_out()),'coefficient':rg.coef_.tolist(),'intercept':float(rg.intercept_),'imputer_median':nu.named_steps['imputer'].statistics_.tolist(),'missing_indicators':nu.named_steps['imputer'].indicator_.features_.tolist(),'scale_mean':nu.named_steps['scale'].mean_.tolist(),'scale_sd':nu.named_steps['scale'].scale_.tolist(),'categorical_levels':[z.tolist() for z in pr.named_transformers_['cat'].categories_]}
def coverage(q):
    con=sqlite3.connect(a.old.DB.as_uri()+'?mode=ro',uri=True);con.execute('PRAGMA query_only=ON')
    specs=[('training','SELECT horse_id,training_date event_date,daily_training_api_row_id source_id,duration_seconds FROM daily_training_api_rows WHERE training_date<=?'),('medical','SELECT horse_id,clinic_date event_date,medical_api_row_id source_id FROM medical_api_rows WHERE clinic_date<=?')]
    out=[];invent=[]
    for kind,sql in specs:
        raw=pd.read_sql_query(sql,con,params=('2026-09-19',));raw.horse_id=raw.horse_id.astype(str);raw=raw[raw.horse_id.isin(set(q.horse_id))];groups={k:np.sort(v.event_date.to_numpy()) for k,v in raw.groupby('horse_id')}
        invent.append({'kind':kind,'rows_in_study_horses':len(raw),'horses':raw.horse_id.nunique(),'first_date':raw.event_date.min(),'last_date':raw.event_date.max(),'duration_missing_rows':int(raw.duration_seconds.isna().sum()) if kind=='training' else None,'historical_publication_verified':False,'predictive_value_tested':False})
        for r in q.itertuples():
            events=groups.get(r.horse_id,np.array([],dtype=str));cut=(pd.Timestamp(r.race_date)-pd.Timedelta(days=2)).strftime('%Y-%m-%d');start=(pd.Timestamp(r.race_date)-pd.Timedelta(days=28)).strftime('%Y-%m-%d');n=bisect.bisect_right(events,cut)-bisect.bisect_left(events,start)
            out.append({'api_record_id':r.api_record_id,'horse_id':r.horse_id,'race_date':r.race_date,'year':r.year,'kind':kind,'observed_rows_last28days_through_Tminus2':n})
    con.close();cov=pd.DataFrame(out);csv('candidate_event_date_coverage_rows.csv',cov);summary=cov.assign(observed=lambda z:z.observed_rows_last28days_through_Tminus2.gt(0)).groupby(['kind','year']).agg(starts=('api_record_id','size'),starts_with_observed_rows=('observed','sum')).reset_index();summary['observed_fraction']=summary.starts_with_observed_rows/summary.starts;csv('candidate_event_date_coverage.csv',summary);save('candidate_inventory.json',clean(invent))

def main():
    f,q,dbsha=features();predictions=[];models=[];support=[];config={'A':BASE,'B':BASE+RECENT,'C':BASE+BODY,'D':BASE+RECENT+BODY}
    for year in [2024,2025,2026]:
        for dist in PLAN['distances']:
            train=f[f.year.lt(year)&f.distance.eq(dist)];test=f[f.year.eq(year)&f.distance.eq(dist)];can=len(train)>=500 and train.race_date.nunique()>=50 and train.horse_id.nunique()>=50 and len(test)>=100 and test.race_date.nunique()>=20 and test.horse_id.nunique()>=30
            support.append({'year':year,'distance':dist,'train_rows':len(train),'train_dates':train.race_date.nunique(),'train_horses':train.horse_id.nunique(),'eval_rows':len(test),'eval_races':test.race_id.nunique(),'eval_dates':test.race_date.nunique(),'eval_horses':test.horse_id.nunique(),'estimated':can})
            if not can:continue
            assert train.race_date.max()<test.history_cutoff.min();z=test[['api_record_id','horse_id','race_id','race_date','year','distance','time','recent_vs_old','gap','last_body','body_deviation','body_delta']].copy();w=1/train.eligible_in_race.to_numpy();w/=w.mean()
            for name,cols in config.items():
                m=make_model(cols);m.fit(train[cols+CATS],train.time, ridge__sample_weight=w);z['prediction_'+name]=m.predict(test[cols+CATS]);models.append({'year':year,'distance':dist,'model':name,'numeric_columns':cols,'training_max_date':train.race_date.max(),'training_max_year':year-1,**record(m)})
            predictions.append(z);print('fitted',year,dist,len(train),len(test),flush=True)
    p=pd.concat(predictions,ignore_index=True);p['race_weight']=1/p.groupby('race_id').api_record_id.transform('size');p['form_group']=np.where(p.recent_vs_old.le(-.5),'recent_fast',np.where(p.recent_vs_old.ge(.5),'recent_slow','middle'));p['rest_group']=pd.cut(p.gap,[0,30,60,120,np.inf],labels=['upTo30','31to60','61to120','over120'])
    for name in config:
        p['error_'+name]=p['time']-p['prediction_'+name];p['abs_error_'+name]=p['error_'+name].abs();p['sq_error_'+name]=p['error_'+name]**2;p['relative_error_'+name]=p['error_'+name]-p.groupby('race_id')['error_'+name].transform('mean');p['relative_abs_error_'+name]=p['relative_error_'+name].abs()
    csv('predictions.csv',p);save('models.json',models);csv('model_support.csv',pd.DataFrame(support));metrics=[];improvements=[];persistence=[];groups=[];rest=[]
    for period,years in [('2024',[2024]),('2025',[2025]),('2024_2025',[2024,2025]),('2026partial',[2026])]:
        for dist,g in p[p.year.isin(years)].groupby('distance'):
            common={'period':period,'distance':int(dist),'rows':len(g),'races':g.race_id.nunique(),'horses':g.horse_id.nunique(),'dates':g.race_date.nunique()};w=g.race_weight.to_numpy()
            for name in config:metrics.append(common|{'model':name,'mae_s':np.average(g['abs_error_'+name],weights=w),'rmse_s':np.sqrt(np.average(g['sq_error_'+name],weights=w)),'relative_mae_s':np.average(g['relative_abs_error_'+name],weights=w)})
            for left,right in [('A','B'),('A','C'),('B','D'),('A','D')]:
                for metric,col in [('mae','abs_error_'),('relative_mae','relative_abs_error_')]:improvements.append(common|{'contrast':right+'_vs_'+left,'metric':metric,**interval(g[col+left]-g[col+right],g,w)})
            for group,gg in g.groupby('form_group'):groups.append(common|{'group':group,'group_rows':len(gg),'mean_prior_signal_s':gg.recent_vs_old.mean(),'mean_next_relative_A_error_s':gg.relative_error_A.mean(),'mean_next_absolute_A_error_s':gg.error_A.mean()})
            contrast=contrast_group(g,'relative_error_A','form_group','recent_fast','recent_slow')
            if contrast:persistence.append(common|contrast)
            for group,gg in g.groupby('rest_group',observed=True):
                if len(gg)>=100 and gg.race_date.nunique()>=20 and gg.horse_id.nunique()>=20:rest.append(common|{'rest_group':str(group),'group_rows':len(gg),**interval(gg.abs_error_A-gg.abs_error_B,gg,gg.race_weight)})
    imp=bh(pd.DataFrame(improvements),['period','contrast','metric']);pers=bh(pd.DataFrame(persistence),['period']);csv('metrics.csv',pd.DataFrame(metrics));csv('paired_improvements.csv',imp);csv('persistence_groups.csv',pd.DataFrame(groups));csv('persistence_contrasts.csv',pers);csv('rest_interval_improvements.csv',pd.DataFrame(rest));coverage(q)
    assert sha(a.old.DB)==dbsha
    for z in json.loads((H/'source_manifest.json').read_text()):assert sha(Path(z['path']))==z['sha256']
    save('verification.json',{'status':'passed','all_history_dates_at_or_before_Tminus2':True,'all_models_train_before_evaluation_year':True,'same_population_for_four_models':True,'current_race_measured_features_used':False,'predicted_rows':len(p),'predicted_races':p.race_id.nunique(),'models':len(models),'source_hashes_unchanged':True,'database_unchanged':True,'database_sha256':dbsha,'independent_future_holdout':False})
    print(imp[(imp.period=='2024_2025')&imp.metric.eq('mae')][['distance','contrast','rows','effect','ci_lo','ci_hi','q_BH']].to_string(index=False),flush=True)
    print('PERSISTENCE',pers[['period','distance','effect','ci_lo','ci_hi','q_BH']].to_string(index=False),flush=True)
if __name__=='__main__':main()
