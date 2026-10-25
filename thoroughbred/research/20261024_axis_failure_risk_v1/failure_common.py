"""Fixed paths, selected-axis risk features, and coherent event reweighting."""
from pathlib import Path
from datetime import datetime,timezone
import sys,json
import torch
import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import expit,logit
from scipy.stats import rankdata

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2];R=HERE.parent;OUT=HERE/'outputs'
PREV=R/'20261022_dynamic_race_model_v1'
sys.path.insert(0,str(PREV))
import common as old

PREVIOUS_BYTES=148_849_873
LAMBDAS=[0.,.25,.5,1.]
AXIS=['history_count','days_since_last','previous_age',
    'moist_last_record_index','moist_last3_record_index_mean','moist_last5_record_index_best','moist_last5_record_index_count',
    'profile_trend','profile_std5','profile_count3','section_same_distance_n5','section_previous_distance',
    'section_early_mean3','section_last600_mean3','section_late_mean3','section_early_n5','section_last600_n5','section_late_n5',
    'front_gate_probability','dirgate_inner_faster_n','dirgate_outer_faster_n',
    'style_fade_mean5','rolelate_front_fade_mean5','style_gain200_mean5',
    'state_rank_current','state_rank_current_sd','state_form_mean','state_form_trend','state_form_sd',
    'state_early_mean','state_early_sd','state_close_mean','state_close_sd','state_risk_rate','state_observed_n','state_days',
    'current_vs_previous_carried_weight','current_carried_weight']
CONTEXT=['distance_m','grade','field_size','base_failure_logit','probability_gap12','probability_gap13',
    'field_top3_entropy','diff_rank_current','diff_form_mean','diff_close_mean',
    'field_short_history_fraction','field_rank_uncertainty_mean']
FEATURES=['axis_'+x for x in AXIS]+CONTEXT
assert len(AXIS)==38 and len(FEATURES)==50
KEY=old.KEY

def sha(p):return old.sha(p)
def save(path,value):
    path=Path(path);assert path.resolve().is_relative_to(HERE)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n')

def safe_logit(p):return logit(np.clip(p,1e-7,1-1e-7))
def order(score):return old.scorer.probability_order(score)

def base_folder(meet,year):
    return (OUT/'history_models'/f'state_gbm_{meet}_{year}') if year<2024 else (PREV/'outputs/models'/f'state_gbm_{meet}_{year}')

def race_example(g,score,temperature):
    assert g.program_no.is_monotonic_increasing
    sets=old.base.triples(len(g));q=old.prob.trio_distribution(score,temperature)
    p=np.bincount(sets.ravel(),weights=np.repeat(q,3),minlength=len(g))
    idx=order(p);a,b,d=idx[:3];axis=g.iloc[a];alt=g.iloc[b]
    event=(sets==a).any(axis=1)
    pi=p[a];assert 0<pi<1 and abs(q[event].sum()-pi)<1e-12
    joint=np.bincount(sets[event].ravel(),weights=np.repeat(q[event],3),minlength=len(g))
    given_in=joint/pi;given_out=(p-joint)/(1-pi)
    assert abs(given_in.sum()-3)<1e-10 and abs(given_out.sum()-3)<1e-10
    record={'race_key':axis.race_key,'race_date':axis.race_date,'meet':int(axis.meet),'year':int(axis.year),
        'grade_raw':axis.grade_raw,'axis_program_no':int(axis.program_no),'axis_horse_id':axis.horse_id,
        'axis_row_number':int(axis.row_number),'axis_outcome':int(axis.outcome),
        'axis_hit':int(1<=axis.outcome<=3),'failure':int(not 1<=axis.outcome<=3),
        'base_risk':float(1-pi),'base_axis_probability':float(pi),
        'distance_m':float(axis.distance_m),'grade':float(axis.grade),'field_size':len(g),
        'base_failure_logit':float(safe_logit(1-pi)),
        'probability_gap12':float(pi-p[b]),'probability_gap13':float(pi-p[d]),
        'field_top3_entropy':float(-np.sum((p/3)*np.log(p/3))/np.log(len(g))),
        'diff_rank_current':float(axis.state_rank_current-alt.state_rank_current),
        'diff_form_mean':float(axis.state_form_mean-alt.state_form_mean),
        'diff_close_mean':float(axis.state_close_mean-alt.state_close_mean),
        'field_short_history_fraction':float(g.history_count.le(3).mean()),
        'field_rank_uncertainty_mean':float(g.state_rank_current_sd.mean())}
    record.update({'axis_'+name:float(axis[name]) for name in AXIS})
    runners=g[['row_number',*KEY,'outcome']].copy()
    runners['base_top3']=p;runners['given_axis_in']=given_in;runners['given_axis_out']=given_out
    runners['is_axis']=np.arange(len(g))==a
    return record,runners

def adjusted_top3(runners,new_axis_probability):
    p=runners.given_axis_in.to_numpy(float)*new_axis_probability+runners.given_axis_out.to_numpy(float)*(1-new_axis_probability)
    assert abs(p.sum()-3)<1e-9 and p.min()>-1e-9 and p.max()<1+1e-9
    assert abs(p[runners.is_axis.to_numpy(bool)][0]-new_axis_probability)<1e-10
    return p

def pick(runners,risk,lam):
    axis_probability=float(runners.loc[runners.is_axis,'base_top3'].iloc[0])
    newp=(1-lam)*axis_probability+lam*(1-risk)
    p=adjusted_top3(runners,newp);ix=int(order(p)[0]);a=runners.iloc[ix]
    return int(a.program_no),int(1<=a.outcome<=3),float(p[ix])

def fit_calibration(score,y):
    score=np.asarray(score,float);y=np.asarray(y,float)
    def objective(v):
        z=v[0]+v[1]*score;r=expit(z)-y
        loss=float(np.mean(np.logaddexp(0,z)-y*z)+.005*(v[0]**2+(v[1]-1)**2))
        grad=np.array([r.mean()+.01*v[0],np.mean(r*score)+.01*(v[1]-1)])
        return loss,grad
    fit=minimize(objective,[0.,1.],jac=True,method='L-BFGS-B',bounds=[(-2,2),(.25,4)],options={'maxiter':300,'ftol':1e-12,'gtol':1e-9})
    assert fit.success,fit.message
    return {'intercept':float(fit.x[0]),'slope':float(fit.x[1]),'objective':float(fit.fun),'iterations':int(fit.nit)}

def calibrated(score,m):return expit(m['intercept']+m['slope']*np.asarray(score,float))

def probability_metrics(y,p):
    y=np.asarray(y,int);p=np.clip(np.asarray(p,float),1e-12,1-1e-12)
    positive=int(y.sum());negative=len(y)-positive
    auc=float((rankdata(p)[y==1].sum()-positive*(positive+1)/2)/(positive*negative)) if positive and negative else None
    ix=np.argsort(-p,kind='stable');ys=y[ix];ps=p[ix];ends=np.r_[np.flatnonzero(ps[:-1]!=ps[1:]),len(ps)-1]
    tp=ys.cumsum()[ends];recall=tp/positive if positive else np.zeros(len(tp))
    ap=float(np.sum(np.diff(np.r_[0.,recall])*tp/(ends+1))) if positive else None
    return {'races':len(y),'failures':positive,'mean_prediction':float(p.mean()),'actual_failure_rate':float(y.mean()),
        'brier':float(np.mean((p-y)**2)),'logloss':float(np.mean(-y*np.log(p)-(1-y)*np.log1p(-p))),
        'auc':auc,'average_precision':ap}

def paired(f,before,after):
    b=f[before].to_numpy(float);a=f[after].to_numpy(float)
    dates,ix=np.unique(f.race_date,return_inverse=True);n=np.bincount(ix)
    sums=np.bincount(ix,weights=a-b)
    draws=np.random.default_rng(20261027).integers(0,len(dates),size=(2000,len(dates)))
    boot=sums[draws].sum(1)/n[draws].sum(1)
    return {'races':len(f),'dates':len(dates),'baseline_total':float(b.sum()),'candidate_total':float(a.sum()),
        'baseline_mean':float(b.mean()),'candidate_mean':float(a.mean()),'difference':float((a-b).mean()),
        'difference_ci95':np.quantile(boot,[.025,.975]).tolist(),
        'gained_races':int((a>b).sum()),'lost_races':int((a<b).sum())}

def storage():
    total=sum(p.stat().st_size for p in HERE.rglob('*') if p.is_file())
    assert total+PREVIOUS_BYTES<300_000_000
    return total

def freeze():
    f=old.frame();assert set(AXIS).issubset(f.columns)
    paths=[HERE/'PLAN.md',*sorted(HERE.glob('*.py')),old.DB,old.HISTORY,
        old.base.SOURCE/'features.parquet',old.base.SOURCE/'feature_contract.json',
        old.base.ABILITY/'research_baseline_selection.json',old.BASE/'config.json',old.BASE/'run.py',old.BASE/'probability.py',old.BASE/'evaluate.py',
        PREV/'common.py',PREV/'state.py',PREV/'outputs/state_features.parquet',PREV/'outputs/state_contract.json',
        PREV/'outputs/race_metrics.parquet',PREV/'outputs/runner_probabilities.parquet',PREV/'outputs/tickets.parquet',
        ROOT/'config/prediction_model_registry.json']
    for meet in [1,3]:
        for year in [2024,2025,2026]:
            folder=base_folder(meet,year);paths += [folder/'metadata.json',folder/'model.txt',folder/'scores.parquet']
    assert not (OUT/'input_manifest.json').exists()
    save(OUT/'input_manifest.json',{str(p.relative_to(ROOT)):{'sha256':sha(p),'bytes':p.stat().st_size} for p in paths})
    save(OUT/'protocol_frozen.json',{'frozen_at_utc':datetime.now(timezone.utc).isoformat(),'evaluation_started':False,
        'risk_features':FEATURES,'history_final_models':8,'risk_final_models':6,'lambdas':LAMBDAS,
        'same_development_period':True,'future_independent_validation':False})
    names=['README.md','conclusions/README.md','conclusions/SOURCES.md','conclusions/source_manifest.json','ARTIFACT_SIZE_LOG.md']
    save(OUT/'preexisting_files.json',{str((R/n).relative_to(ROOT)):{'sha256':sha(R/n),'bytes':(R/n).stat().st_size} for n in names})
    print('Frozen',len(FEATURES),'features',flush=True)

def check():
    for name,v in json.loads((OUT/'input_manifest.json').read_text()).items():assert sha(ROOT/name)==v['sha256'],name

if __name__=='__main__':freeze()
