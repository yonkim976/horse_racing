"""Annual time-ordered 2024/2025 refits; fixed feature candidates, no price input."""
import hashlib,json,pickle
from datetime import date,datetime,UTC
from pathlib import Path

import lightgbm as lgb
import numpy as np
import polars as pl
from scipy.optimize import minimize_scalar

from horse_racing.analysis.jeju_top3_preprocessing import FitPreprocessor
from horse_racing.analysis.jeju_joint_top3 import JointTop3MLP
from horse_racing.analysis.jeju_hybrid_evaluation import accepted_layout,conditional_calibration_loss,evaluate_hybrid_race
from scripts.run_jeju_transition_holdout import data_frame
from scripts.run_jeju_context_experiment import rank_scores,order_scores
from scripts.run_jeju_top3_experiment import race_groups,order_loss
from scripts.build_jeju_steward_pace_v2 import STEWARD,PACE_BURDEN

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data/research/jeju_annual_revalidation_20260918'
DATA=ROOT/'data/research/jeju_native_top3_dataset_v1_20260915_r2'
OLD=ROOT/'data/research/jeju_native_transition_holdout_v13_20260916'
FEAT=ROOT/'data/research/jeju_steward_pace_v2_20260918'

def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def save(name,obj):
    (OUT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2,default=str,allow_nan=False))

def annual_parts(frame,year):
    p=year-1
    intervals={'fit':(date(2018,8,31),date(p,6,30)),'tune':(date(p,7,1),date(p,9,30)),
        'calibration':(date(p,10,1),date(p,12,31)),'evaluation':(date(year,1,1),date(year,12,31))}
    parts={role:frame.filter(pl.col('event_date').is_between(lo,hi)).sort('race_id','horse_id') for role,(lo,hi) in intervals.items()}
    # Evaluation labels never reach fit, checkpoint selection, or temperature calibration.
    parts['evaluation']=parts['evaluation'].with_columns(pl.lit(None,dtype=pl.Float64).alias('finish_position'),pl.lit(None,dtype=pl.Int64).alias('label_top3'))
    return parts

def main():
    OUT.mkdir(exist_ok=False);(OUT/'bundles').mkdir()
    old=pickle.loads((OLD/'bundles/frozen_2026__HY_R_FORM.pkl').read_bytes())
    config=json.loads((OLD/'protocol.json').read_text())
    save('protocol.json',dict(created_at=datetime.now(UTC).isoformat(),years=[2024,2025],seeds=[17,43],
        plan_sha256=sha(ROOT/'docs/JEJU_MULTYEAR_RETURN_PROTOCOL_2026-09-18.md'),old_bundle_sha256=sha(OLD/'bundles/frozen_2026__HY_R_FORM.pkl'),
        feature_sha256=sha(FEAT/'features.parquet'),rank_features=old['rank_bundle']['features'],order_features=old['order_bundle']['features'],
        rank_params=config['rank_params'],order_params=config['order_params'],skipped='2024 STEWARD: no reports before evaluation year',
        status='retrospective development reuse',expected_fits=14))
    frame,truth,_=data_frame()
    eligible=pl.read_parquet(DATA/'races.parquet').filter(pl.col('target_eligible')).select('race_id')
    frame=frame.join(eligible,on='race_id',how='semi').join(pl.read_parquet(FEAT/'features.parquet'),on='entry_id',validate='1:1')
    ledger=[];scoreframes=[];coverage=[];boundaries=[]
    for year in [2024,2025]:
        parts=annual_parts(frame,year)
        for left,right in [('fit','tune'),('tune','calibration'),('calibration','evaluation')]:
            assert parts[left]['event_date'].max()<parts[right]['event_date'].min()
        for role,d in parts.items():
            boundaries.append(dict(year=year,role=role,first=d['event_date'].min(),last=d['event_date'].max(),races=d['race_id'].n_unique(),rows=len(d)))
            coverage.append(dict(year=year,role=role,rows=len(d),report_known=int(d['st2_report_known'].sum()),event_known=int(d['st2_event_any'].fill_null(0).sum()),pace_known=int((d['pb_valid_count_3']>0).sum())))
        groups={k:race_groups(v,truth) for k,v in parts.items() if k!='evaluation'}
        ranks={};rs={}
        candidates={'BASE':[], 'PACE_BURDEN':PACE_BURDEN}
        if year==2025:candidates['STEWARD']=STEWARD
        for name,extras in candidates.items():
            features=old['rank_bundle']['features']+extras
            pre=FitPreprocessor().fit(parts['fit'],features)
            xs={k:pre.transform(v) for k,v in parts.items()}
            ys={k:np.where(np.isfinite(v['finish_position'].to_numpy().astype(float))&(v['finish_position'].to_numpy()<=3),
                4-v['finish_position'].to_numpy(),0).astype(int) for k,v in parts.items() if k in ['fit','tune']}
            models=[]
            for seed in [17,43]:
                model=lgb.LGBMRanker(objective='lambdarank',label_gain=[0,1,3,7],random_state=seed,verbosity=-1,**config['rank_params'])
                model.fit(xs['fit'],ys['fit'],group=[hi-lo for lo,hi,_ in groups['fit']],eval_set=[(xs['tune'],ys['tune'])],
                    eval_group=[[hi-lo for lo,hi,_ in groups['tune']]],eval_at=[3],callbacks=[lgb.early_stopping(30,verbose=False)])
                models.append(model);ledger.append(dict(year=year,model=name,seed=seed,best_iteration=int(model.best_iteration_)))
                save('fit_ledger.json',ledger);print(year,name,seed,'done',flush=True)
            bundle=dict(kind='ranker',features=features,preprocessor=pre,models=models)
            rs[name]={k:rank_scores(bundle,parts[k]) for k in ['calibration','evaluation']}
            opt=minimize_scalar(lambda x:order_loss(rs[name]['calibration'],groups['calibration'],np.exp(x)),bounds=(-4,4),method='bounded',options={'xatol':1e-5})
            assert opt.success
            bundle['beta']=float(np.exp(opt.x));ranks[name]=bundle
            (OUT/'bundles'/f'{year}__{name}.pkl').write_bytes(pickle.dumps(bundle))
        pre=FitPreprocessor().fit(parts['fit'],old['order_bundle']['features'])
        xs={k:pre.transform(v) for k,v in parts.items()}
        sizes={k:[hi-lo for lo,hi,_ in g] for k,g in groups.items()}
        accepted={k:[o for _,_,o in g] for k,g in groups.items()}
        models=[]
        for seed in [17,43]:
            model=JointTop3MLP(**config['order_params'])
            model.fit(xs['fit'],sizes['fit'],accepted['fit'],tune=(xs['tune'],sizes['tune'],accepted['tune']),seed=seed,joint_weight=1.)
            models.append(model);ledger.append(dict(year=year,model='ORDER',seed=seed,diagnostics={k:v for k,v in vars(model).items() if k.endswith('_') and isinstance(v,(str,int,float,bool,type(None)))}))
            save('fit_ledger.json',ledger);print(year,'ORDER',seed,'done',flush=True)
        ob=dict(features=old['order_bundle']['features'],preprocessor=pre,models=models)
        os={k:order_scores(ob,parts[k]) for k in ['calibration','evaluation']}
        layouts=[]
        for lo,hi,_ in groups['calibration']:
            d=parts['calibration'][lo:hi];rid=d['race_id'][0]
            layouts.append(accepted_layout(d['horse_id'].to_list(),rs['BASE']['calibration'][lo:hi],os['calibration'][lo:hi],truth[rid],ranks['BASE']['beta']))
        opt=minimize_scalar(lambda x:conditional_calibration_loss(x,layouts),bounds=(-4,4),method='bounded',options={'xatol':1e-5})
        assert opt.success
        ob['beta_order']=float(np.exp(opt.x));(OUT/'bundles'/f'{year}__ORDER.pkl').write_bytes(pickle.dumps(ob))
        for name,b in ranks.items():
            scoreframes.append(parts['evaluation'].select('entry_id','race_id','horse_id','event_date').with_columns(
                pl.lit(year).alias('year'),pl.lit(name).alias('model'),pl.Series('score',rs[name]['evaluation']),pl.Series('order_score',os['evaluation']),
                pl.lit(b['beta']).alias('beta'),pl.lit(ob['beta_order']).alias('beta_order')))
    save('boundaries.json',boundaries);save('coverage.json',coverage)
    scores=pl.concat(scoreframes);scores.write_parquet(OUT/'frozen_scores.parquet')
    save('prediction_lock.json',dict(created_at=datetime.now(UTC).isoformat(),files={str(p.relative_to(OUT)):sha(p) for p in [OUT/'frozen_scores.parquet',OUT/'protocol.json',*sorted((OUT/'bundles').glob('*.pkl'))]}))
    labels=pl.read_parquet(DATA/'labels.parquet').filter(pl.col('event_date').dt.year().is_in([2024,2025]))
    official={}
    for r in labels.filter(pl.col('label_top3')==1).to_dicts():official.setdefault(r['race_id'],[]).append(r['horse_id'])
    races=[];horses=[]
    for (year,name,rid),part in scores.partition_by(['year','model','race_id'],as_dict=True).items():
        part=part.sort('horse_id');ids=part['horse_id'].to_list()
        met=evaluate_hybrid_race(ids,part['score'].to_numpy(),part['order_score'].to_numpy(),truth[rid],official[rid],beta_set=part['beta'][0],beta_order=part['beta_order'][0])
        p=met.pop('pl_marginals');y=met.pop('official_labels')
        races.append(dict(year=year,model=name,race_id=rid,event_date=part['event_date'][0],**met))
        horses.extend(dict(year=year,model=name,race_id=rid,horse_id=h,p=pp,y=yy) for h,pp,yy in zip(ids,p,y,strict=True))
    r=pl.from_dicts(races);r.write_parquet(OUT/'race_predictions.parquet');pl.from_dicts(horses).write_parquet(OUT/'horse_predictions.parquet')
    summary=r.group_by('year','model').agg(pl.len().alias('races'),*[pl.col(k).sum() for k in ['pick_hit','set_hit','order_hit']],pl.col('place_brier').mean()).sort('year','model')
    save('summary.json',summary.to_dicts());print(summary,flush=True)
    comp=[]
    for year,names in [(2024,['PACE_BURDEN']),(2025,['PACE_BURDEN','STEWARD'])]:
        ref=r.filter((pl.col('year')==year)&(pl.col('model')=='BASE')).sort('race_id');days=ref['event_date'].to_list();unique=sorted(set(days))
        count=np.array([days.count(day) for day in unique]);ix=np.random.default_rng(17).integers(0,len(unique),(5000,len(unique)))
        for name in names:
            cand=r.filter((pl.col('year')==year)&(pl.col('model')==name)).sort('race_id')
            assert cand['race_id'].to_list()==ref['race_id'].to_list()
            for metric in ['pick_hit','set_hit','order_hit']:
                delta=cand[metric].to_numpy().astype(float)-ref[metric].to_numpy().astype(float)
                totals=np.array([sum(delta[i] for i,d in enumerate(days) if d==day) for day in unique])
                boot=totals[ix].sum(axis=1)/count[ix].sum(axis=1)
                lo,hi=np.quantile(boot,[.025/9,1-.025/9])
                comp.append(dict(year=year,candidate=name,metric=metric,difference=float(delta.mean()),low=float(lo),high=float(hi),improvement_signal=bool(lo>0)))
    save('comparisons.json',comp)
    save('quarters.json',r.with_columns(pl.col('event_date').dt.quarter().alias('quarter')).group_by('year','quarter','model').agg(pl.len().alias('races'),*[pl.col(k).sum() for k in ['pick_hit','set_hit','order_hit']]).sort('year','quarter','model').to_dicts())
    save('manifest.json',dict(files={str(p.relative_to(OUT)):sha(p) for p in OUT.rglob('*') if p.is_file()}))

if __name__=='__main__':main()
