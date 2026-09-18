"""Six binary fits and twelve past-only calibrations for the one-horse Top3 target."""
import json,pickle
from collections import defaultdict
from datetime import UTC,datetime
from pathlib import Path
import lightgbm as lgb
import numpy as np
import polars as pl
from scipy.special import logit
from horse_racing.analysis.jeju_top3_preprocessing import FitPreprocessor
from horse_racing.analysis.jeju_place_probability import pl_top3_marginals
from horse_racing.analysis.jeju_place_calibration import PositivePlattCalibrator
from horse_racing.analysis.jeju_zero_history_calibration import ZeroHistoryCalibrator
from scripts.run_jeju_transition_holdout import data_frame
from scripts.run_jeju_annual_revalidation import annual_parts,sha
from scripts.run_jeju_context_experiment import rank_scores

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data/research/jeju_place_objective_20260919'
DATA=ROOT/'data/research/jeju_native_top3_dataset_v1_20260915_r2'
OLD=ROOT/'data/research/jeju_native_transition_holdout_v13_20260916'
ANN=ROOT/'data/research/jeju_annual_revalidation_20260918'
REF=ROOT/'data/research/jeju_accuracy_candidates_20260919'
PLAN=ROOT/'docs/JEJU_PLACE_OBJECTIVE_PROTOCOL_2026-09-19.md'
ARMS=['BASE','BASE_GLOBAL','BASE_ZERO','P_FORM','P_FORM_ZERO']
def save(name,obj):(OUT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2,default=str,allow_nan=False))
def load_frame():
    f,_,_=data_frame()
    return f.join(pl.read_parquet(DATA/'races.parquet').filter(pl.col('target_eligible')).select('race_id'),on='race_id',how='semi')
def base_prob(bundle,frame):
    score=rank_scores(bundle,frame);p=np.empty(len(frame))
    start=0
    for part in frame.partition_by('race_id',maintain_order=True):
        end=start+len(part);p[start:end]=pl_top3_marginals(score[start:end],bundle['beta']);start=end
    return p
def main():
    OUT.mkdir(exist_ok=False);(OUT/'bundles').mkdir()
    old=pickle.loads((OLD/'bundles/frozen_2026__HY_R_FORM.pkl').read_bytes());features=old['rank_bundle']['features']
    params=json.loads((OLD/'protocol.json').read_text())['rank_params']
    save('protocol.json',dict(created_at=datetime.now(UTC).isoformat(),plan_sha256=sha(PLAN),script_sha256=sha(Path(__file__)),features=features,params=params,seeds=[17,43],arms=ARMS,max_fits=6,calibrations=12,
        reference_sha256=sha(OLD/'bundles/frozen_2026__HY_R_FORM.pkl'),zero_penalty=.01,probability_contract='A only; no enforced sum3 or joint set/order probabilities'))
    frame=load_frame();meta={r['race_id']:r for r in pl.read_parquet(DATA/'races.parquet').to_dicts()}
    boundary=[rid for rid,r in meta.items() if r['boundary_tie']]
    ledger=[];cal_ledger=[];bounds=[];frames=[]
    for year in [2024,2025,2026]:
        parts=annual_parts(frame,year)
        for a,b in [('fit','tune'),('tune','calibration'),('calibration','evaluation')]:assert parts[a]['event_date'].max()<parts[b]['event_date'].min()
        for role,f in parts.items():bounds.append(dict(year=year,role=role,first=f['event_date'].min(),last=f['event_date'].max(),races=f['race_id'].n_unique(),rows=len(f)))
        parts['calibration']=parts['calibration'].filter(~pl.col('race_id').is_in(boundary))
        base=old['rank_bundle'] if year==2026 else pickle.loads((ANN/f'bundles/{year}__BASE.pkl').read_bytes())
        pre=FitPreprocessor().fit(parts['fit'],features);xs={k:pre.transform(v) for k,v in parts.items()}
        weights={k:1/v['field_size'].to_numpy().astype(float) for k,v in parts.items()}
        models=[]
        for seed in [17,43]:
            m=lgb.LGBMClassifier(objective='binary',random_state=seed,verbosity=-1,**params)
            m.fit(xs['fit'],parts['fit']['label_top3'].to_numpy(),sample_weight=weights['fit']/weights['fit'].mean(),
              eval_set=[(xs['tune'],parts['tune']['label_top3'].to_numpy())],eval_sample_weight=[weights['tune']/weights['tune'].mean()],
              eval_metric='binary_logloss',callbacks=[lgb.early_stopping(30,verbose=False)])
            models.append(m);ledger.append(dict(year=year,seed=seed,best_iteration=int(m.best_iteration_)));save('fit_ledger.json',ledger)
            print(year,'P_FORM',seed,'done',flush=True)
        binary={k:np.mean([m.predict(xs[k],raw_score=True) for m in models],axis=0) for k in ['calibration','evaluation']}
        bp={k:base_prob(base,parts[k]) for k in ['calibration','evaluation']}
        zero={k:(parts[k]['starts_pre'].to_numpy()==0).astype(int) for k in ['calibration','evaluation']}
        inputs={'BASE':{k:logit(np.clip(p,1e-8,1-1e-8)) for k,p in bp.items()},'P_FORM':binary}
        cal={};pred={'BASE':bp['evaluation']};y=parts['calibration']['label_top3'].to_numpy();w=weights['calibration']
        for family,x in inputs.items():
            global_cal=PositivePlattCalibrator().fit(x['calibration'],y,w)
            local=ZeroHistoryCalibrator().fit(x['calibration'],zero['calibration'],y,w)
            assert global_cal.success and local.success_
            cal[family]=dict(global_cal=global_cal,zero_cal=local)
            pred['BASE_GLOBAL' if family=='BASE' else 'P_FORM']=global_cal.predict(x['evaluation'])
            pred[family+'_ZERO']=local.predict(x['evaluation'],zero['evaluation'])
            for kind,c in [('global',global_cal),('zero',local)]:
                cal_ledger.append(dict(year=year,family=family,kind=kind,cal_races=parts['calibration']['race_id'].n_unique(),cal_entries=len(y),zero_entries=int(zero['calibration'].sum()),
                    params=c.params_.tolist() if kind=='zero' else [c.log_scale_,c.intercept_],iterations=c.n_iter_,success=c.success_,fallback=getattr(c,'fallback_',False)))
        bundle=dict(features=features,preprocessor=pre,models=models,calibrators=cal)
        (OUT/f'bundles/{year}__P_FORM_CAL.pkl').write_bytes(pickle.dumps(bundle))
        frames.append(parts['evaluation'].select('entry_id','race_id','horse_id','event_date','starts_pre','field_size').with_columns(pl.lit(year).alias('year'),
            pl.Series('binary_score',binary['evaluation']),*[pl.Series('p_'+name,p) for name,p in pred.items()]))
    save('boundaries.json',bounds);save('calibration_ledger.json',cal_ledger)
    scores=pl.concat(frames);scores.write_parquet(OUT/'frozen_probabilities.parquet')
    save('prediction_lock.json',dict(created_at=datetime.now(UTC).isoformat(),files={str(p.relative_to(OUT)):sha(p) for p in [OUT/'protocol.json',OUT/'frozen_probabilities.parquet',*sorted((OUT/'bundles').glob('*.pkl'))]}))
    # Evaluation labels first enter this run's scoring here, after models and probabilities are locked.
    labels={(r['race_id'],r['horse_id']):int(r['label_top3']) for r in pl.read_parquet(DATA/'labels.parquet').to_dicts()}
    ref={r['race_id']:r for r in pl.read_parquet(REF/'race_predictions.parquet').filter(pl.col('model')=='BASE').to_dicts()}
    races=[];horses=[]
    for (rid,),part in scores.partition_by('race_id',as_dict=True).items():
        part=part.sort('horse_id');ids=part['horse_id'].to_list();year=part['year'][0];date=part['event_date'][0]
        z=part['starts_pre'].to_numpy()==0;y=np.array([labels[(rid,h)] for h in ids]);haszero=bool(z.any())
        base_pick=None
        for name in ARMS:
            p=part['p_'+name].to_numpy();idx=int(np.argmax(p));chosen=ids[idx]
            if name=='BASE':base_pick=chosen;assert chosen==ref[rid]['pick_horse_id']
            if name=='BASE_GLOBAL':assert chosen==base_pick
            loss=-(y*np.log(np.clip(p,1e-15,1))+(1-y)*np.log(np.clip(1-p,1e-15,1)))
            races.append(dict(year=year,model=name,race_id=rid,event_date=date,pick_horse_id=chosen,pick_hit=bool(y[idx]),pick_probability=float(p[idx]),pick_zero=bool(z[idx]),has_zero_history=haszero,
                changed_from_BASE=chosen!=base_pick,outside_BASE_set=chosen not in ref[rid]['predicted_set'],boundary_tie=meta[rid]['boundary_tie'],
                brier=float(np.mean((p-y)**2)),logloss=float(np.mean(loss))))
            horses.extend(dict(year=year,model=name,race_id=rid,event_date=date,horse_id=h,p=float(pp),y=int(yy),zero=bool(zz),boundary_tie=meta[rid]['boundary_tie']) for h,pp,yy,zz in zip(ids,p,y,z,strict=True))
    r=pl.from_dicts(races);h=pl.from_dicts(horses);r.write_parquet(OUT/'race_predictions.parquet');h.write_parquet(OUT/'horse_predictions.parquet')
    summary=[];subgroup=[]
    for year in [2024,2025,2026,'ALL']:
        for name in ARMS:
            rr=[x for x in races if x['model']==name and (year=='ALL' or x['year']==year)];valid=[x for x in rr if not x['boundary_tie']]
            wins=sum(x['pick_hit'] for x in rr)
            changed=[x for x in rr if x['changed_from_BASE']]
            summary.append(dict(year=year,model=name,races=len(rr),hits=wins,accuracy=wins/len(rr),brier=float(np.mean([x['brier'] for x in valid])),logloss=float(np.mean([x['logloss'] for x in valid])),changed=len(changed),
               changed_wins=sum(x['pick_hit'] and not ref[x['race_id']]['pick_hit'] for x in changed),changed_losses=sum(not x['pick_hit'] and ref[x['race_id']]['pick_hit'] for x in changed),
               outside_BASE_set=sum(x['outside_BASE_set'] for x in rr)))
            for axis in ['has_zero_history','pick_zero']:
                for flag in [False,True]:
                    g=[x for x in rr if x[axis]==flag]
                    if g:subgroup.append(dict(year=year,model=name,axis=axis,flag=flag,races=len(g),hits=sum(x['pick_hit'] for x in g)))
    save('summary.json',summary);save('subgroups.json',subgroup)
    save('quarters.json',r.with_columns(pl.col('event_date').dt.quarter().alias('quarter')).group_by('year','quarter','model').agg(pl.len().alias('races'),pl.col('pick_hit').sum()).sort('year','quarter','model').to_dicts())
    hs=[]
    for year in [2024,2025,2026,'ALL']:
        for name in ARMS:
            for zero in [False,True]:
                g=[x for x in horses if x['model']==name and (year=='ALL' or x['year']==year) and x['zero']==zero and not x['boundary_tie']]
                if g:hs.append(dict(year=year,model=name,zero=zero,entries=len(g),predicted=float(np.mean([x['p'] for x in g])),actual=float(np.mean([x['y'] for x in g])),brier=float(np.mean([(x['p']-x['y'])**2 for x in g]))))
    save('horse_experience.json',hs)
    comparisons=[]
    for name in ['BASE_ZERO','P_FORM','P_FORM_ZERO']:
        rng=np.random.default_rng(17);pooled=np.zeros(5000);n=0;diff=0;year_results=[]
        for year in [2024,2025,2026]:
            g=sorted([x for x in races if x['model']==name and x['year']==year],key=lambda x:x['race_id']);days=sorted({x['event_date'] for x in g})
            d=np.array([int(x['pick_hit'])-int(ref[x['race_id']]['pick_hit']) for x in g]);count=np.array([sum(x['event_date']==day for x in g) for day in days])
            total=np.array([sum(d[i] for i,x in enumerate(g) if x['event_date']==day) for day in days]);ix=rng.integers(0,len(days),(5000,len(days)))
            boot=total[ix].sum(axis=1)/count[ix].sum(axis=1);pooled+=boot*len(g);n+=len(g);diff+=d.sum()
            year_results.append(dict(year=year,delta_hits=int(d.sum()),difference=float(d.mean()),ci95=np.quantile(boot,[.025,.975]).tolist()))
        lo,hi=np.quantile(pooled/n,[.025/3,1-.025/3]);comparisons.append(dict(candidate=name,difference=diff/n,delta_hits=int(diff),simultaneous95=[float(lo),float(hi)],years=year_results,
            promote_development=bool(lo>0 and sum(x['delta_hits']>0 for x in year_results)>=2 and year_results[-1]['delta_hits']>0)))
    save('primary_comparisons.json',comparisons)
    save('manifest.json',dict(files={str(p.relative_to(OUT)):sha(p) for p in OUT.rglob('*') if p.is_file()}))
    print(json.dumps(summary,ensure_ascii=False),flush=True);print(json.dumps(comparisons,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
