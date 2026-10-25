"""Read-only burden deterioration and daily-training associations."""
from pathlib import Path
import importlib.util
import json
import sqlite3
import bisect
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

H=Path(__file__).resolve().parent;ROOT=H.parents[2];PRE=H.parent/'20261008_weight_speed_v2';FORM=H.parent/'20261008_recent_form_persistence_v1'
sp=importlib.util.spec_from_file_location('weight_source',PRE/'analyze.py');a=importlib.util.module_from_spec(sp);sp.loader.exec_module(a)
sp=importlib.util.spec_from_file_location('form_source',FORM/'analyze.py');b=importlib.util.module_from_spec(sp);sp.loader.exec_module(b)
PLAN=json.loads((H/'PLAN.json').read_text());sha=a.sha
def save(name,v):
    with (H/name).open('x',encoding='utf-8') as z:json.dump(b.clean(v),z,ensure_ascii=False,indent=2,allow_nan=False)
def csv(name,df):
    with (H/name).open('x',encoding='utf-8') as z:df.to_csv(z,index=False)
def bh(df,keys):
    for _,g in df.groupby(keys,dropna=False):df.loc[g.index,'q_BH']=a.old.bh(g.p.to_numpy())
    return df
def infer(m,v):
    z=a.infer(m,v)
    if 'speed_change_pct_per_kg' in z:z['speed_change_pct_for_contrast']=z.pop('speed_change_pct_per_kg')
    return z
def v(m,name,k=1):return a.get_vector(m,name,k)
def infog(g):return {'rows':len(g),'races':g.race_id.nunique(),'dates':g.race_date.nunique(),'horses':g.horse_id.nunique()}
def burden_group(x):return np.select([x.le(-1),x.lt(1),x.lt(3)],['down1plus','stableUnder1','up1toUnder3'],default='up3plus')
PAIRBASE=['body_change10','previous_burden_kg','log_gap','age','previous_relative_time','previous_finish_fraction','previous_hist_mean','field_change']

def load():
    refs=[H/'PLAN.json',H/'analyze.py',PRE/'analyze.py',PRE/'source_lineage.csv',PRE/'pair_lineage.csv',PRE/'input_audit.json',FORM/'analyze.py',FORM/'features.csv',FORM/'predictions.csv',FORM/'models.json',a.old.OLD/'audit/source_rows.csv',a.old.OLD/'audit/history_ids.json',ROOT/'jeju/docs/JEJU_TRAINING_API_INPUT_CONTRACT_2026-10-01.md',H.parent/'20261001_daily_training_api_load/README.md',H.parent/'20261001_training_audit/README.md',ROOT/'jeju/data/horse_exclusions.json']
    save('source_manifest.json',[{'path':str(p),'sha256':sha(p),'bytes':p.stat().st_size} for p in refs]);dbsha=sha(a.old.DB);assert dbsha==json.loads((PRE/'input_audit.json').read_text())['database_sha256']
    d,h=a.old.load();q=a.old.all_features(d,h).reset_index(drop=True);raw=pd.read_csv(PRE/'source_lineage.csv',dtype={'horse_id':str},low_memory=False);q=q.merge(raw[['api_record_id','body_kg']],on='api_record_id',validate='one_to_one');q['time']=q.finish_time_seconds;q['log_time100']=100*np.log(q.time);q['body10']=(q.body_kg-278)/10;q['body2']=q.body10**2;q['burden']=q.carried_weight_kg-55;q['prior_finish_fraction']=[(d.loc[h[str(rid)][-1],'finish_position']-1)/(d.loc[h[str(rid)][-1],'field_n']-1) if h[str(rid)] else np.nan for rid in q.api_record_id]
    pairs=pd.read_csv(PRE/'pair_lineage.csv',dtype={'horse_id':str},low_memory=False);pairs['burden_group']=burden_group(pairs.burden_change);pairs['raw_slow2']=pairs.time_delta.ge(2).astype(float);pairs['relative_slow1']=pairs.relative_time_delta.ge(1).astype(float);pairs['raw_slow3']=pairs.time_delta.ge(3).astype(float);pairs['relative_slow2']=pairs.relative_time_delta.ge(2).astype(float);pairs['hinge3']=(pairs.burden_change-3).clip(lower=0)
    con=sqlite3.connect(a.old.DB.as_uri()+'?mode=ro',uri=True);con.execute('PRAGMA query_only=ON');tr=pd.read_sql_query('SELECT daily_training_api_row_id,horse_id,training_date,duration_seconds,duration_status,daily_training_api_artifact_id,source_row_index FROM daily_training_api_rows WHERE training_date<=?',con,params=('2026-09-19',));con.close();tr.horse_id=tr.horse_id.astype(str);tr=tr[tr.horse_id.isin(set(q.horse_id))].sort_values(['horse_id','training_date','daily_training_api_row_id']);assert not tr.duplicated(['horse_id','training_date']).any();assert tr.daily_training_api_row_id.is_unique;csv('training_source_lineage.csv',tr)
    groups={hid:g for hid,g in tr.groupby('horse_id')};rows=[];lineage=[]
    for r in q.itertuples():
        dt=pd.Timestamp(r.race_date);g=groups.get(r.horse_id);dates=g.training_date.to_numpy() if g is not None else np.array([],dtype=str);rec={'api_record_id':r.api_record_id};trace={'api_record_id':r.api_record_id,'horse_id':r.horse_id,'race_date':r.race_date,'cutoff':(dt-pd.Timedelta(days=2)).strftime('%Y-%m-%d')}
        for label,start,end in [('7',8,2),('14',15,2),('28',29,2),('previous28',57,30)]:
            lo=(dt-pd.Timedelta(days=start)).strftime('%Y-%m-%d');hi=(dt-pd.Timedelta(days=end)).strftime('%Y-%m-%d');left=bisect.bisect_left(dates,lo);right=bisect.bisect_right(dates,hi);z=g.iloc[left:right] if g is not None else pd.DataFrame(columns=tr.columns);valid=z.duration_seconds.dropna();rec['days'+label]=len(z) if len(z) else np.nan;rec['meanmin'+label]=valid.mean()/60 if len(valid) else np.nan;rec['valid_fraction'+label]=len(valid)/len(z) if len(z) else np.nan;trace[label]=z.daily_training_api_row_id.astype(int).tolist();assert z.training_date.between(lo,hi).all()
        last=bisect.bisect_right(dates,trace['cutoff'])-1;rec['last_training_gap']=(dt-pd.Timestamp(dates[last])).days if last>=0 else np.nan;rec['days_change28']=rec['days28']-rec['daysprevious28'];rec['meanmin_change28']=rec['meanmin28']-rec['meanminprevious28'];rec['training_days5']=rec['days28']/5;rec['training_mean5']=rec['meanmin28']/5;rows.append(rec);lineage.append(trace)
    ft=pd.DataFrame(rows);csv('training_features.csv',ft);save('training_window_lineage.json',lineage);q=q.merge(ft,on='api_record_id',validate='one_to_one');ix=ft.set_index('api_record_id')
    for key in ['days28','meanmin28','daysprevious28','meanminprevious28']:
        pairs[key]=ix.loc[pairs.pair_id,key].to_numpy();pairs['previous_'+key]=ix.loc[pairs.previous_api_record_id,key].to_numpy()
    pairs['training_days5']=(pairs.days28-pairs.previous_days28)/5;pairs['training_mean5']=(pairs.meanmin28-pairs.previous_meanmin28)/5;pairs['gap_squared']=pairs.gap**2
    save('input_audit.json',{'source_rows':len(q),'races':q.race_id.nunique(),'pairs':len(pairs),'training_rows':len(tr),'training_horses':tr.horse_id.nunique(),'training_missing_duration_rows':tr.duration_seconds.isna().sum(),'horse_date_unique':True,'current28_observation_missing_rows':q.days28.isna().sum(),'current28_duration_missing_rows':q.meanmin28.isna().sum(),'previous28_observation_missing_rows':q.daysprevious28.isna().sum(),'previous28_duration_missing_rows':q.meanminprevious28.isna().sum(),'last_date':q.race_date.max(),'database_sha256':dbsha,'training_event_dates_not_publication_proof':True,'run_counts_and_intensity_not_used':True})
    return q,pairs,ft,dbsha

def pair_controls(g,variant='primary',training=False):
    numeric=list(PAIRBASE)
    if variant=='no_previous_performance':numeric=[c for c in numeric if c not in ['previous_relative_time','previous_finish_fraction','previous_hist_mean']]
    if training:numeric+=['increase_kg','decrease_kg','gap_squared','previous_days28','previous_meanmin28']
    numeric += [c for c in g if c.startswith(('band=','gate='))]+['sin1','cos1','sin2','cos2'];return a.standardized_nuisance(g,numeric,['year_grade'])
def fit_pair(g,family,variant):
    nx,design=pair_controls(g,variant,training=family=='training_pair')
    if family=='burden_risk':
        targets=['down1plus','up1toUnder3','up3plus'];tv=np.column_stack([g.burden_group.eq(c).astype(float) for c in targets]);y=g[['raw_slow2','relative_slow1']].to_numpy();labels=['raw_slow2','relative_slow1']
    elif family=='burden_spline':
        targets=['increase_kg','hinge3'];tv=g[targets].to_numpy();extra,extra_design=a.standardized_nuisance(g,['decrease_kg']);nx=np.column_stack([nx,extra]);design['nuisance_columns']+=extra_design['nuisance_columns'];design['nuisance_means']+=extra_design['nuisance_means'];design['nuisance_sd']+=extra_design['nuisance_sd'];design['nuisance_medians'].update(extra_design['nuisance_medians']);y=g[['time_delta','log_time_delta100']].to_numpy();labels=['time_s','log_time100']
    else:targets=['training_days5','training_mean5'];tv=g[targets].to_numpy();y=g[['time_delta','log_time_delta100']].to_numpy();labels=['time_s','log_time100']
    cols=targets+['intercept']+design['nuisance_columns'];x=np.column_stack([tv,np.ones(len(g)),nx]);fits=a.core_fit(x,y,g,cols,len(targets),fe=False)
    for m,label in zip(fits,labels):m['design']=design;m['target']=label
    return fits
def fit_training_row(g):
    numeric=['daysprevious28','meanminprevious28','burden','body10','body2','event_age','age_squared','hist_mean','hist_last','prior_finish_fraction','log_same_count','log_starts','log_gap','log_same_gap'];nx,design=a.standardized_nuisance(g,numeric,['sex','horse_number']);targets=['training_days5','training_mean5'];x=np.column_stack([g[targets].to_numpy(),nx]);fits=a.core_fit(x,g[['time','log_time100']].to_numpy(),g,targets+design['nuisance_columns'],2)
    for m in fits:m['design']=design
    return fits

def burden(pairs,models):
    descriptive=[];effects=[];support=[]
    for period,(lo,hi) in PLAN['burden_periods'].items():
        for dist,g in pairs[pairs.year.between(lo,hi)].groupby('distance'):
            for group,z in g.groupby('burden_group'):
                r={'period':period,'distance':int(dist),'burden_group':group,**infog(z),'mean_burden_change':z.burden_change.mean(),'mean_time_delta':z.time_delta.mean(),'median_time_delta':z.time_delta.median(),'mean_relative_time_delta':z.relative_time_delta.mean(),'previous_finish_fraction':z.previous_finish_fraction.mean()}
                for outcome in ['raw_slow2','relative_slow1','raw_slow3','relative_slow2']:r[outcome+'_count']=int(z[outcome].sum());r[outcome+'_rate']=z[outcome].mean()
                descriptive.append(r)
    csv('burden_raw_risks.csv',pd.DataFrame(descriptive))
    for period,(lo,hi) in PLAN['burden_periods'].items():
        for variant in (['primary','stable_conditions','no_previous_performance'] if period=='full' else ['primary']):
            for dist,g in pairs[pairs.year.between(lo,hi)].groupby('distance'):
                if variant=='stable_conditions':g=g[g.month.eq(g.previous_month)&g.band.eq(g.previous_band)&g.body_change_kg.abs().le(5)]
                counts=g.burden_group.value_counts();can=a.support(g,True)['supported'] and counts.get('stableUnder1',0)>=100 and counts.get('up3plus',0)>=30 and all(counts.get(c,0)>=20 for c in ['down1plus','up1toUnder3']);support.append({'family':'burden','period':period,'variant':variant,'distance':int(dist),**infog(g),'estimated':can})
                if not can:continue
                for family in ['burden_risk','burden_spline']:
                    for m in fit_pair(g,family,variant):
                        models.append({'family':family,'period':period,'variant':variant,'distance':int(dist),'model':m});contrasts={'up3_vs_stable':v(m,'up3plus')} if family=='burden_risk' else {'slope_up_to3kg':v(m,'increase_kg'),'extra_slope_above3kg':v(m,'hinge3'),'fivekg_change':v(m,'increase_kg',5)+v(m,'hinge3',2)}
                        for name,vector in contrasts.items():
                            r=infer(m,vector)
                            if family=='burden_risk':r={key:val*100 if key in ['effect','ci_lo','ci_hi','se'] else val for key,val in r.items()}
                            effects.append({'family':family,'period':period,'variant':variant,'distance':int(dist),'target':m['target'],'exposure':name,**infog(g),**r})
                print('burden',period,variant,int(dist),len(g),flush=True)
    csv('burden_effects.csv',bh(pd.DataFrame(effects),['family','period','variant','target','exposure']));csv('burden_support.csv',pd.DataFrame(support))
    cases=pairs[pairs.year.ge(2024)&pairs.burden_change.between(3,5)&pairs.time_delta.between(2,5)&pairs.relative_time_delta.ge(1)&pairs.month.eq(pairs.previous_month)&pairs.band.eq(pairs.previous_band)&pairs.body_change_kg.abs().le(5)].sort_values(['race_date','pair_id'],ascending=False).head(5).copy();con=sqlite3.connect(a.old.DB.as_uri()+'?mode=ro',uri=True);con.execute('PRAGMA query_only=ON');checks=[];names={}
    for r in cases.itertuples():
        names[r.horse_id]=con.execute('SELECT horse_name_raw FROM horse_profile_latest WHERE horse_id=?',(r.horse_id,)).fetchone()[0]
        for rid,weight,time in [(r.pair_id,r.burden_kg,r.time),(r.previous_api_record_id,r.previous_burden_kg,r.previous_time)]:
            actual=con.execute('SELECT r.horse_id,r.carried_weight_kg,r.finish_time_seconds,a.payload_json,a.payload_sha256 FROM race_result_rows r JOIN api_records a ON a.api_record_id=r.api_record_id WHERE r.api_record_id=?',(int(rid),)).fetchone();assert actual[0]==r.horse_id and actual[1]==weight and actual[2]==time and float(json.loads(actual[3])['wgBudam'])==weight;checks.append({'api_record_id':int(rid),'horse_id':r.horse_id,'burden_kg':weight,'time_s':time,'payload_sha256':actual[4]})
    con.close();cases['current_horse_name']=cases.horse_id.map(names);csv('burden_case_examples.csv',cases);save('case_api_verification.json',checks)

def training(q,pairs,models):
    effects=[];support=[];rawcorr=[]
    complete=q.dropna(subset=['training_days5','training_mean5','daysprevious28','meanminprevious28']);pp=pairs.dropna(subset=['training_days5','training_mean5','previous_days28','previous_meanmin28'])
    for dist,g in pp.groupby('distance'):
        for col in ['training_days5','training_mean5']:rawcorr.append({'distance':int(dist),'exposure':col,'pairs':len(g),'spearman_with_positive_time_improvement':float(spearmanr(g[col],-g.time_delta).statistic),'spearman_with_positive_relative_improvement':float(spearmanr(g[col],-g.relative_time_delta).statistic)})
    csv('training_raw_correlations.csv',pd.DataFrame(rawcorr))
    for family,data,distcol in [('training_row',complete,'race_distance_m'),('training_pair',pp,'distance')]:
        for period,(lo,hi) in PLAN['burden_periods'].items():
            for dist,g in data[data.year.between(lo,hi)].groupby(distcol):
                can=a.support(g,family=='training_pair')['supported'];support.append({'family':family,'period':period,'distance':int(dist),**infog(g),'estimated':can})
                if not can:continue
                fits=fit_training_row(g) if family=='training_row' else fit_pair(g,'training_pair','primary')
                for m in fits:
                    models.append({'family':family,'period':period,'variant':'primary','distance':int(dist),'model':m})
                    for col in ['training_days5','training_mean5']:effects.append({'family':family,'period':period,'variant':'primary','distance':int(dist),'target':m['target'],'exposure':col,**infog(g),**infer(m,v(m,col))})
                print(family,period,int(dist),len(g),flush=True)
    csv('training_effects.csv',bh(pd.DataFrame(effects),['family','period','exposure']));csv('training_support.csv',pd.DataFrame(support))

def prediction(ft):
    f=pd.read_csv(FORM/'features.csv',dtype={'horse_id':str},low_memory=False).merge(ft,on='api_record_id',validate='one_to_one');oldpred=pd.read_csv(FORM/'predictions.csv',dtype={'horse_id':str});oldmodels=json.loads((FORM/'models.json').read_text());newcols=['days7','days14','days28','meanmin7','meanmin14','meanmin28','days_change28','meanmin_change28','last_training_gap','valid_fraction28'];nums=b.BASE+b.RECENT;models=[];pred=[];baseline_errors=[]
    for saved in oldmodels:
        if saved['model']!='B':continue
        year,dist=saved['year'],saved['distance'];train=f[f.year.lt(year)&f.distance.eq(dist)];test=f[f.year.eq(year)&f.distance.eq(dist)];w=1/train.eligible_in_race.to_numpy();w/=w.mean();base=b.make_model(nums);base.fit(train[nums+b.CATS],train.time,ridge__sample_weight=w);bp=base.predict(test[nums+b.CATS]);ref=oldpred.set_index('api_record_id').loc[test.api_record_id,'prediction_B'].to_numpy();err=float(np.max(np.abs(bp-ref)));assert err<1e-8;baseline_errors.append(err)
        model=b.make_model(nums+newcols);model.fit(train[nums+newcols+b.CATS],train.time,ridge__sample_weight=w);z=oldpred.set_index('api_record_id').loc[test.api_record_id].reset_index();z['prediction_E']=model.predict(test[nums+newcols+b.CATS]);z['error_E']=z.time-z.prediction_E;z['abs_error_E']=z.error_E.abs();z['relative_error_E']=z.error_E-z.groupby('race_id').error_E.transform('mean');z['relative_abs_error_E']=z.relative_error_E.abs();pred.append(z);models.append({'year':year,'distance':dist,'model':'E','numeric_columns':nums+newcols,'training_max_date':train.race_date.max(),**b.record(model)});print('predict',year,dist,len(test),flush=True)
    p=pd.concat(pred,ignore_index=True);csv('training_predictions.csv',p);save('training_prediction_models.json',models);rows=[];metrics=[]
    for period,years in [('2024',[2024]),('2025',[2025]),('2024_2025',[2024,2025]),('2026partial',[2026])]:
        for dist,g in p[p.year.isin(years)].groupby('distance'):
            common={'period':period,'distance':int(dist),**infog(g)}
            for name in ['B','E']:metrics.append(common|{'model':name,'mae_s':np.average(g['abs_error_'+name],weights=g.race_weight),'rmse_s':np.sqrt(np.average(g['error_'+name]**2,weights=g.race_weight)),'relative_mae_s':np.average(g['relative_abs_error_'+name],weights=g.race_weight)})
            for metric,col in [('mae','abs_error_'),('relative_mae','relative_abs_error_')]:rows.append(common|{'metric':metric,**b.interval(g[col+'B']-g[col+'E'],g,g.race_weight)})
    csv('training_prediction_improvements.csv',bh(pd.DataFrame(rows),['period','metric']));csv('training_prediction_metrics.csv',pd.DataFrame(metrics));save('training_baseline_reproduction.json',{'all_frozen_B_predictions_reproduced':True,'models':len(models),'maximum_prediction_error':max(baseline_errors),'same_eval_rows':len(p),'training_publication_time_unverified':True})

def main():
    q,pairs,ft,dbsha=load();models=[];burden(pairs,models);training(q,pairs,models);save('association_models.json',models);prediction(ft)
    for r in json.loads((H/'source_manifest.json').read_text()):assert sha(Path(r['path']))==r['sha256']
    assert sha(a.old.DB)==dbsha
    save('verification.json',{'status':'passed','database_sha256':dbsha,'database_and_prior_sources_unchanged':True,'association_models':len(models),'maximum_FE_projection_error':max(z['model']['orthogonality'] for z in models),'maximum_FE_joint_coefficient_error':max(z['model']['joint_beta_error'] for z in models),'all_training_windows_end_at_Tminus2':True,'training_rows_are_observed_days_not_intensity':True,'burden_binary_targets_relabelled_as_risk_before_inference':True,'no_operational_updates':True})
    for name in ['burden_effects.csv','training_effects.csv','training_prediction_improvements.csv']:
        z=pd.read_csv(H/name);print(name,flush=True);print(z[(z.period.isin(['full','2024_2025','2026partial']))&(z.target.eq('time_s') if 'target' in z else z.metric.eq('mae'))].to_string(index=False),flush=True)
if __name__=='__main__':main()
