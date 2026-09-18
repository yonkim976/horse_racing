"""Fixed retrospective pilot; fit through 2025, eight outputs on known 2026 data."""
import hashlib
import json
import pickle
from datetime import datetime,UTC
from pathlib import Path

import lightgbm as lgb
import numpy as np
import polars as pl
from scipy.optimize import minimize_scalar

from horse_racing.analysis.jeju_tempo_pace import PAR,PACE
from horse_racing.analysis.jeju_top3_preprocessing import FitPreprocessor
from horse_racing.analysis.jeju_joint_top3 import JointTop3MLP
from horse_racing.analysis.jeju_hybrid_evaluation import accepted_layout,conditional_calibration_loss,evaluate_hybrid_race
from scripts.run_jeju_transition_holdout import data_frame
from scripts.run_jeju_context_experiment import rank_scores,order_scores
from scripts.run_jeju_top3_experiment import race_groups,order_loss

ROOT=Path(__file__).resolve().parents[1]
OLD=ROOT/'data/research/jeju_native_transition_holdout_v13_20260916'
DATA=ROOT/'data/research/jeju_native_top3_dataset_v1_20260915_r2'
FEAT=ROOT/'data/research/jeju_tempo_pace_features_20260917'
OUT=ROOT/'data/research/jeju_tempo_pace_pilot_20260917'

def sha(p):return hashlib.file_digest(p.open('rb'),'sha256').hexdigest()
def save(name,obj):
    (OUT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2,default=str,allow_nan=False))

def main():
    OUT.mkdir(exist_ok=False);(OUT/'bundles').mkdir()
    old=pickle.loads((OLD/'bundles/frozen_2026__HY_R_FORM.pkl').read_bytes())
    config=json.loads((OLD/'protocol.json').read_text())
    candidates={'PAR':PAR,'PACE':PACE,'BOTH':PAR+PACE}
    save('protocol.json',dict(created_at=datetime.now(UTC).isoformat(),evaluation_status='previously_seen_retrospective_development',
        old_model_sha256=sha(OLD/'bundles/frozen_2026__HY_R_FORM.pkl'),features_sha256=sha(FEAT/'features.parquet'),
        plan_sha256=sha(ROOT/'docs/JEJU_NATIVE_TEMPO_PACE_PILOT_PLAN_2026-09-17.md'),
        candidates=candidates,seeds=[17,43],rank_params=config['rank_params'],order_params=config['order_params'],
        main_contrasts='A3+B3+C1, day bootstrap5000 Bonferroni7; no automatic deployment'))
    frame,truth,folds=data_frame()
    frame=frame.join(pl.read_parquet(FEAT/'features.parquet'),on='entry_id',validate='1:1')
    parts={role:frame.join(folds.filter(pl.col('role')==role).select('race_id'),on='race_id',how='semi').sort('race_id','horse_id')
           for role in ['fit','tune','calibration','evaluation']}
    assert parts['evaluation']['finish_position'].null_count()==len(parts['evaluation'])==4852
    groups={k:race_groups(v,truth) for k,v in parts.items() if k!='evaluation'}
    ledger=[]
    base=old['rank_bundle'];obase=old['order_bundle']
    ranks={'BASE':base};orders={'BASE':obase}
    rs={'BASE':{k:rank_scores(base,v) for k,v in parts.items() if k in ('calibration','evaluation')}}
    os={'BASE':{k:order_scores(obase,v) for k,v in parts.items() if k in ('calibration','evaluation')}}
    for name,extras in candidates.items():
        features=base['features']+extras
        pre=FitPreprocessor().fit(parts['fit'],features)
        xs={k:pre.transform(v) for k,v in parts.items()}
        ys={k:np.where(np.isfinite(v['finish_position'].to_numpy().astype(float))&(v['finish_position'].to_numpy()<=3),
                       4-v['finish_position'].to_numpy(),0).astype(int) for k,v in parts.items() if k in ('fit','tune')}
        models=[]
        for seed in [17,43]:
            model=lgb.LGBMRanker(objective='lambdarank',label_gain=[0,1,3,7],random_state=seed,verbosity=-1,**config['rank_params'])
            model.fit(xs['fit'],ys['fit'],group=[hi-lo for lo,hi,_ in groups['fit']],
                eval_set=[(xs['tune'],ys['tune'])],eval_group=[[hi-lo for lo,hi,_ in groups['tune']]],
                eval_at=[3],callbacks=[lgb.early_stopping(30,verbose=False)])
            models.append(model);ledger.append(dict(model=name,seed=seed,best_iteration=int(model.best_iteration_)))
            save('fit_ledger.json',ledger);print(name,seed,'done',flush=True)
        bundle=dict(kind='ranker',features=features,preprocessor=pre,models=models)
        rs[name]={k:rank_scores(bundle,parts[k]) for k in ['calibration','evaluation']}
        opt=minimize_scalar(lambda x:order_loss(rs[name]['calibration'],groups['calibration'],np.exp(x)),
                            bounds=(-4,4),method='bounded',options={'xatol':1e-5})
        assert opt.success
        bundle['beta']=float(np.exp(opt.x));ranks[name]=bundle
        (OUT/'bundles'/f'{name}.pkl').write_bytes(pickle.dumps(bundle))
    features=obase['features']+PAR+PACE
    pre=FitPreprocessor().fit(parts['fit'],features)
    xs={k:pre.transform(v) for k,v in parts.items()}
    sizes={k:[hi-lo for lo,hi,_ in g] for k,g in groups.items()}
    accepted={k:[o for _,_,o in g] for k,g in groups.items()}
    models=[]
    for seed in [17,43]:
        model=JointTop3MLP(**config['order_params'])
        model.fit(xs['fit'],sizes['fit'],accepted['fit'],tune=(xs['tune'],sizes['tune'],accepted['tune']),seed=seed,joint_weight=1.)
        models.append(model)
        ledger.append(dict(model='ORDER_BOTH',seed=seed,diagnostics={k:v for k,v in vars(model).items()
                      if k.endswith('_') and isinstance(v,(str,int,float,bool,type(None)))}))
        save('fit_ledger.json',ledger);print('ORDER_BOTH',seed,'done',flush=True)
    orders['NEW']=dict(features=features,preprocessor=pre,models=models)
    os['NEW']={k:order_scores(orders['NEW'],parts[k]) for k in ['calibration','evaluation']}
    layout=[]
    for lo,hi,_ in groups['calibration']:
        r=parts['calibration'][lo:hi];rid=r['race_id'][0]
        layout.append(accepted_layout(r['horse_id'].to_list(),rs['BASE']['calibration'][lo:hi],
                      os['NEW']['calibration'][lo:hi],truth[rid],base['beta']))
    opt=minimize_scalar(lambda x:conditional_calibration_loss(x,layout),bounds=(-4,4),method='bounded',options={'xatol':1e-5})
    assert opt.success
    betas={'BASE':old['beta_order'],'NEW':float(np.exp(opt.x))}
    orders['NEW']['beta_order']=betas['NEW']
    (OUT/'bundles/ORDER_BOTH.pkl').write_bytes(pickle.dumps(orders['NEW']))
    allscores=[]
    for rankname in ranks:
        for ordername in orders:
            name=rankname+'__'+ordername
            allscores.append(parts['evaluation'].select('entry_id','race_id','horse_id','event_date').with_columns(
                pl.lit(name).alias('model'),pl.Series('score',rs[rankname]['evaluation']),
                pl.Series('order_score',os[ordername]['evaluation']),
                pl.lit(ranks[rankname]['beta']).alias('beta'),pl.lit(betas[ordername]).alias('beta_order')))
    scores=pl.concat(allscores);scores.write_parquet(OUT/'frozen_scores.parquet')
    save('prediction_lock.json',dict(created_at=datetime.now(UTC).isoformat(),files={str(p.relative_to(OUT)):sha(p)
       for p in [OUT/'protocol.json',OUT/'frozen_scores.parquet',*sorted((OUT/'bundles').glob('*.pkl'))]}))
    # First label join for this new pilot; this period is already known from earlier work.
    labels=pl.read_parquet(DATA/'labels.parquet').filter(pl.col('event_date').dt.year()==2026)
    official={}
    for r in labels.filter(pl.col('label_top3')==1).to_dicts():official.setdefault(r['race_id'],[]).append(r['horse_id'])
    truths={}
    for r in pl.read_parquet(DATA/'accepted_orders.parquet').filter(pl.col('event_date').dt.year()==2026).to_dicts():
        truths.setdefault(r['race_id'],[]).append((r['first_horse_id'],r['second_horse_id'],r['third_horse_id']))
    races=[];horses=[]
    for (name,rid),part in scores.partition_by(['model','race_id'],as_dict=True).items():
        part=part.sort('horse_id');ids=part['horse_id'].to_list()
        met=evaluate_hybrid_race(ids,part['score'].to_numpy(),part['order_score'].to_numpy(),truths[rid],official[rid],
             beta_set=part['beta'][0],beta_order=part['beta_order'][0])
        probs=met.pop('pl_marginals');ys=met.pop('official_labels')
        races.append(dict(model=name,race_id=rid,event_date=part['event_date'][0],**met))
        horses.extend(dict(model=name,race_id=rid,horse_id=h,p=pr,y=y) for h,pr,y in zip(ids,probs,ys,strict=True))
    r=pl.from_dicts(races);r.write_parquet(OUT/'race_predictions.parquet')
    pl.from_dicts(horses).write_parquet(OUT/'horse_predictions.parquet')
    summary=r.group_by('model').agg(pl.len().alias('races'),*[pl.col(k).sum() for k in ['pick_hit','set_hit','order_hit']],
                                  pl.col('place_brier').mean()).sort('model')
    save('summary.json',summary.to_dicts());print(summary,flush=True)
    assert r.filter(pl.col('model')=='BASE__BASE')['pick_hit'].sum()==317
    assert r.filter(pl.col('model')=='BASE__BASE')['set_hit'].sum()==32
    assert r.filter(pl.col('model')=='BASE__BASE')['order_hit'].sum()==7
    ref=r.filter(pl.col('model')=='BASE__BASE').sort('race_id')
    primary=[(name+'__BASE',metric) for name in ['PAR','PACE','BOTH'] for metric in ['pick_hit','set_hit']]+[('BASE__NEW','order_hit')]
    comparisons=[]
    for name,metric in primary:
        cand=r.filter(pl.col('model')==name).sort('race_id')
        assert cand['race_id'].to_list()==ref['race_id'].to_list()
        delta=cand[metric].to_numpy().astype(float)-ref[metric].to_numpy().astype(float)
        days=ref['event_date'].to_list();unique=sorted(set(days))
        count=np.array([days.count(day) for day in unique]);total=np.array([sum(delta[i] for i,d in enumerate(days) if d==day) for day in unique])
        ix=np.random.default_rng(17).integers(0,len(unique),size=(5000,len(unique)))
        boot=total[ix].sum(axis=1)/count[ix].sum(axis=1)
        low,high=np.quantile(boot,[.025/7,1-.025/7])
        comparisons.append(dict(candidate=name,metric=metric,difference=float(delta.mean()),low=float(low),high=float(high),
                                improvement_signal=bool(low>0)))
    save('primary_comparisons.json',comparisons)
    quarters=r.with_columns(pl.col('event_date').dt.quarter().alias('quarter')).group_by('model','quarter').agg(
       pl.len().alias('races'),*[pl.col(k).mean() for k in ['pick_hit','set_hit','order_hit']]).sort('model','quarter')
    save('quarter_summary.json',quarters.to_dicts())
    save('manifest.json',dict(files={str(p.relative_to(OUT)):sha(p) for p in OUT.rglob('*') if p.is_file() and p.name!='manifest.json'},
          baseline_unchanged=sha(OLD/'bundles/frozen_2026__HY_R_FORM.pkl')==json.loads((OUT/'protocol.json').read_text())['old_model_sha256']))

if __name__=='__main__':main()
