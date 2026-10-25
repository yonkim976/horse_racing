"""Precommitted development selection and subsequent retrospective evaluation."""
import argparse,json
from pathlib import Path
import numpy as np
import pandas as pd
from audit import HERE,DB,sha,save,csv
from modeling import load,features,fit,model_record,probabilities,losses,paired_ci,SEED

def metrics(q,p,ptime,sets):
    ll,br=losses(q,p)
    runners=q[['api_record_id','race_id','race_date','horse_id','year','race_distance_m','grade','same_count','observed_starts','horse_number','finish_position','finish_time_seconds']].copy()
    runners['p_top3']=p;runners['log_loss']=ll;runners['brier']=br;runners['predicted_time_s']=ptime;runners['absolute_error_s']=np.abs(q.finish_time_seconds.to_numpy()-ptime)
    runners['history_group']=pd.cut(runners.observed_starts,[-1,0,4,np.inf],labels=['observed_0','observed_1_4','observed_5_plus']).astype(str)
    races=runners.groupby(['race_id','race_date','year','race_distance_m']).agg(log_loss=('log_loss','mean'),brier=('brier','mean'),mae_s=('absolute_error_s','mean'),rows=('api_record_id','size')).reset_index().merge(sets,on='race_id',validate='one_to_one')
    contain=[]
    for rid,g in runners.groupby('race_id',sort=False):
        truth=set(g[g.finish_position<=3].api_record_id)
        ordered=g.sort_values(['p_top3','horse_number'],ascending=[False,True]);entry={'race_id':rid}
        for k in [3,4,5,6]:
            found=len(truth&set(ordered.head(k).api_record_id));entry[f'coverage{k}']=found/3;entry[f'all3_in_top{k}']=int(found==3)
        contain.append(entry)
    races=races.merge(pd.DataFrame(contain),on='race_id',validate='one_to_one')
    races['week']=pd.to_datetime(races.race_date).dt.to_period('W').astype(str)
    return runners,races

def summary(runners,races,name):
    result=[]
    slices=[('all','all',runners,races)]
    for c in ['year','race_distance_m','grade','history_group']:
        for val,g in runners.groupby(c):
            if c=='history_group':
                rr=g.groupby(['race_id','race_date']).agg(log_loss=('log_loss','mean'),brier=('brier','mean'),mae_s=('absolute_error_s','mean')).reset_index()
            else:rr=races[races.race_id.isin(g.race_id)]
            slices.append((c,str(val),g,rr))
    for axis,val,g,rr in slices:
        row={'model':name,'axis':axis,'value':val,'rows':len(g),'races':rr.race_id.nunique(),'days':rr.race_date.nunique(),'runner_log_loss':g.log_loss.mean(),'runner_brier':g.brier.mean(),'runner_mae_s':g.absolute_error_s.mean(),'race_log_loss':rr.log_loss.mean(),'race_brier':rr.brier.mean(),'race_mae_s':rr.mae_s.mean(),'same_distance_history_rows':int((g.same_count>0).sum()),'history_available_mae_s':g[g.same_count>0].absolute_error_s.mean()}
        for c in ['six_combo_hit','six_predicted_mass']+[f'{m}{k}' for k in [3,4,5,6] for m in ['coverage','all3_in_top']]:row[c]=rr[c].mean() if c in rr else np.nan
        result.append(row)
    return pd.DataFrame(result)

def calibration(runners,name):
    g=runners.copy();g['bin']=np.minimum(9,(g.p_top3*10).astype(int));g['y']=(g.finish_position<=3).astype(float);g['w']=1/g.groupby('race_id').api_record_id.transform('size')
    result=[]
    for (dist,bin_),a in g.groupby(['race_distance_m','bin']):
        result.append({'model':name,'distance':dist,'bin':bin_,'rows':len(a),'races':a.race_id.nunique(),'predicted':np.average(a.p_top3,weights=a.w),'observed':np.average(a.y,weights=a.w),'weight':a.w.sum()})
    return pd.DataFrame(result)

def main(analysis,output):
    assert sha(HERE/'RESEARCH_CONTRACT.md')==json.loads((HERE/'contract_lock.json').read_text())['sha256']
    out=HERE/output;assert out.parent==HERE and out.name.startswith('comparison_');out.mkdir(exist_ok=False)
    src=HERE/analysis;d,h=load();e=pd.read_csv(src/'record_effects.csv').set_index('api_record_id')
    cache={};models=[];calfits=[];candidate_metrics=[]
    def run(rates,years):
        key=tuple(rates),tuple(years)
        if key in cache:return cache[key]
        correction=sum((e[c+'_effect_s'].fillna(0)*a for c,a in zip(['moisture','month','number'],rates)),start=pd.Series(0.,index=e.index))
        q=features(d,h,correction=correction);q=q[q.strict].sort_values(['race_date','race_number','horse_number'])
        runnerparts=[];raceparts=[]
        for year in years:
            qp=[];tp=[];zp=[]
            for dist in [1000,1110]:
                train=q[(q.year<=year-2)&(q.race_distance_m==dist)];cal=q[(q.year==year-1)&(q.race_distance_m==dist)];target=q[(q.year==year)&(q.race_distance_m==dist)]
                assert train.race_date.max()<cal.race_date.min() and cal.race_date.max()<target.race_date.min()
                tm=fit(train,'time');pm=fit(train,'top3');cl=pm.decision_function(cal);opts=[]
                for tau in [.5,.75,1.,1.5,2.,3.]:
                    pp,_=probabilities(cal,cl,tau);ll,_=losses(cal,pp)
                    score=pd.Series(ll,index=cal.index).groupby(cal.race_id).mean().mean();opts.append((float(score),tau))
                tau=min(opts)[1];p,sets=probabilities(target,pm.decision_function(target),tau)
                ru,ra=metrics(target,p,tm.predict(target),sets);runnerparts.append(ru);raceparts.append(ra)
                models.append({'rates':list(rates),'year':year,'distance':dist,'train_start':train.race_date.min(),'train_end':train.race_date.max(),'cal_start':cal.race_date.min(),'cal_end':cal.race_date.max(),'train_rows':len(train),'cal_rows':len(cal),'eval_rows':len(target),'tau':tau,'time_model':model_record(tm),'top3_model':model_record(pm)})
                calfits.append({'rates':list(rates),'year':year,'distance':dist,'candidate_scores':[{'tau':t,'log_loss':s} for s,t in opts],'selected_tau':tau})
            print('Forecast comparison',rates,year,flush=True)
        result=(pd.concat(runnerparts,ignore_index=True),pd.concat(raceparts,ignore_index=True));cache[key]=result
        return result
    base_dev=run((0,0,0),(2022,2023));decisions=[]
    def select(stage,options,reference):
        entries=[]
        for rates in options:
            ru,ra=run(rates,(2022,2023));entries.append((tuple(rates),float(ra.log_loss.mean()),ra))
            tab=summary(ru,ra,f'{stage}_{rates}');tab['stage']=stage;candidate_metrics.append(tab)
        best=min(entries,key=lambda x:(x[1],x[0]));near=[]
        for rates,score,ra in entries:
            diff=paired_ci(ra,best[2]);
            if diff['delta']<=diff['se']+1e-15:near.append((rates,ra))
        chosen=min(near,key=lambda x:x[0]);zero=run(reference,(2022,2023))[1];ci=paired_ci(chosen[1],zero);brier=paired_ci(chosen[1],zero,col='brier')
        passed=chosen[0]!=tuple(reference) and ci['hi']<0 and brier['delta']<=0
        final=chosen[0] if passed else tuple(reference)
        decisions.append({'stage':stage,'options':[list(r) for r in options],'best_rates':list(best[0]),'one_se_smallest_rates':list(chosen[0]),'chosen_delta_log_loss':ci,'chosen_delta_brier':brier,'nonzero_passed':passed,'selected_rates':list(final),'reason':'passed_precommitted_development_rule' if passed else 'zero_retained_no_sufficient_development_gain'})
        return final
    r1=select('R1',[(a,0,0) for a in [0,.25,.5,.75,1]],(0,0,0))
    r2=select('R2',[(r1[0],a,0) for a in [0,.25,.5]],r1)
    r3=select('R3',[(r2[0],r2[1],a) for a in [0,.25,.5]],r2)
    save(out/'selection_locked_before_evaluation.json',{'contract_sha256':sha(HERE/'RESEARCH_CONTRACT.md'),'selection_years':[2022,2023],'decisions':decisions,'fixed_evaluation_rates':{'R0':[0,0,0],'R1':list(r1),'R2':list(r2),'R3':list(r3)}})
    print('Selection frozen',r1,r2,r3,flush=True)
    csv(out/'development_candidate_metrics.csv',pd.concat(candidate_metrics,ignore_index=True))
    evals={};tables=[];caltables=[];cirows=[];corrected=[]
    fixed={'R0':(0,0,0),'R1':r1,'R2':r2,'R3':r3}
    for name,rates in fixed.items():
        ru,ra=run(rates,(2024,2025,2026));evals[name]=(ru,ra)
        csv(out/f'{name}_runner_predictions.csv',ru);csv(out/f'{name}_race_metrics.csv',ra)
        tables.append(summary(ru,ra,name));caltables.append(calibration(ru,name))
        records=e.copy()
        for c,a in zip(['moisture','month','number'],rates):
            records[c+'_rate']=a;records[c+'_applied_s']=records[c+'_effect_s'].fillna(0)*a
            records[c+'_application_status']=np.where(records[c+'_effect_s'].isna(),records[c+'_status'],np.where(a==0,'raw_retained_zero_rate',records[c+'_status']))
        records['corrected_time_s']=records.original_time_s-records[[c+'_applied_s' for c in ['moisture','month','number']]].sum(axis=1)
        csv(out/f'{name}_corrected_records.csv',records.reset_index())
    br,ba=evals['R0']
    for name,(ru,ra) in evals.items():
        for period,mask in [('2024_2025',ra.year<=2025),('2026_partial',ra.year==2026),('all_2024_2026',ra.year>=2024)]:
            x=ra[mask];b=ba[ba.race_id.isin(x.race_id)]
            for dist in [None,1000,1110]:
                xx=x if dist is None else x[x.race_distance_m==dist];bb=b[b.race_id.isin(xx.race_id)]
                for col in ['log_loss','brier','mae_s','six_combo_hit','all3_in_top5']:
                    cirows.append({'model':name,'period':period,'distance':dist or 'all','metric':col,'cluster':'race_day',**paired_ci(xx,bb,col)})
                cirows.append({'model':name,'period':period,'distance':dist or 'all','metric':'log_loss','cluster':'week',**paired_ci(xx,bb,'log_loss',cluster='week')})
        # Repeated-horse sensitivity is runner-average, distinct from primary race-average.
        for col in ['log_loss','brier','absolute_error_s']:
            a=ru.rename(columns={'race_id':'original_race_id','api_record_id':'race_id'});b=br.rename(columns={'race_id':'original_race_id','api_record_id':'race_id'})
            cirows.append({'model':name,'period':'all_2024_2026','distance':'all','metric':col,'cluster':'horse_runner_mean',**paired_ci(a,b,col,cluster='horse_id')})
    # Uniform reference uses identical evaluation rows and deterministic start-number tie policy.
    q=features(d,h);q=q.loc[br.api_record_id.to_numpy()].copy();p=3/q.field_n.to_numpy()
    _,sets=probabilities(q,np.zeros(len(q)),1)
    ur,ua=metrics(q,p,br.predicted_time_s.to_numpy(),sets);tables.append(summary(ur,ua,'UNIFORM'));caltables.append(calibration(ur,'UNIFORM'))
    csv(out/'evaluation_metrics.csv',pd.concat(tables,ignore_index=True));csv(out/'calibration_bins.csv',pd.concat(caltables,ignore_index=True));csv(out/'paired_uncertainty.csv',pd.DataFrame(cirows))
    save(out/'forecast_models.json',models);save(out/'temperature_calibration.json',calfits)
    # Preserve development predictions, including zero and all fixed candidates.
    for (rates,years),(ru,ra) in cache.items():
        if years==(2022,2023):
            tag='_'.join(str(int(a*100)) for a in rates);csv(out/f'dev_{tag}_runner_predictions.csv',ru);csv(out/f'dev_{tag}_race_metrics.csv',ra)
    ci=pd.DataFrame(cirows);ll=ci[(ci.model=='R3')&(ci.period=='2024_2025')&(ci.metric=='log_loss')&(ci.cluster=='race_day')];combined=ll[ll.distance=='all'].iloc[0]
    bb=ci[(ci.model=='R3')&(ci.period=='2024_2025')&(ci.metric=='brier')&(ci.distance=='all')&(ci.cluster=='race_day')].iloc[0]
    partial=ci[(ci.model=='R3')&(ci.period=='2026_partial')&(ci.metric=='log_loss')&(ci.distance=='all')&(ci.cluster=='race_day')].iloc[0]
    passed=any(a>0 for a in r3) and combined.hi<0 and bb.delta<=0 and (ll[ll.distance!='all'].delta<=0).all() and partial.delta<=0
    save(out/'decision.json',{'status':'research_candidate_passed_retrospective_rule' if passed else 'R0_retained','selected_rates':list(r3),'retrospective_rule_passed':bool(passed),'operational_change':False,'independent_future_validation':False,'db_sha256':sha(DB),'contract_sha256':sha(HERE/'RESEARCH_CONTRACT.md'),'code_sha256':{n:sha(HERE/n) for n in ['modeling.py','compare.py']},'conditional_confidence_intervals':'models_and_selection_frozen_not_full_retraining_bootstrap'})
    print('Comparison complete',out,flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--analysis',default='analysis_02');p.add_argument('--output',default='comparison_01');a=p.parse_args();main(a.analysis,a.output)
