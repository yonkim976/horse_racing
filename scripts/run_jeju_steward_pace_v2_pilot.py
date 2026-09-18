"""Two fixed feature additions, four rank fits, unchanged order model."""
import hashlib,json,pickle
from datetime import datetime,UTC
from pathlib import Path

import lightgbm as lgb
import numpy as np
import polars as pl
from scipy.optimize import minimize_scalar

from horse_racing.analysis.jeju_top3_preprocessing import FitPreprocessor
from horse_racing.analysis.jeju_hybrid_evaluation import evaluate_hybrid_race
from scripts.run_jeju_transition_holdout import data_frame
from scripts.run_jeju_context_experiment import rank_scores,order_scores
from scripts.run_jeju_top3_experiment import race_groups,order_loss
from scripts.build_jeju_steward_pace_v2 import STEWARD,PACE_BURDEN

ROOT=Path(__file__).resolve().parents[1]
OLD=ROOT/'data/research/jeju_native_transition_holdout_v13_20260916'
DATA=ROOT/'data/research/jeju_native_top3_dataset_v1_20260915_r2'
FEAT=ROOT/'data/research/jeju_steward_pace_v2_20260918'
OUT=ROOT/'data/research/jeju_steward_pace_v2_pilot_20260918'

def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def save(name,obj):
    (OUT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2,default=str,allow_nan=False))

def main():
    assert json.loads((FEAT/'audit_result.json').read_text())['accepted_for_research_pilot']
    OUT.mkdir(exist_ok=False);(OUT/'bundles').mkdir()
    old=pickle.loads((OLD/'bundles/frozen_2026__HY_R_FORM.pkl').read_bytes())
    config=json.loads((OLD/'protocol.json').read_text())
    save('protocol.json',dict(created_at=datetime.now(UTC).isoformat(),evaluation_status='previously_seen_retrospective_development',
        old_model_sha256=sha(OLD/'bundles/frozen_2026__HY_R_FORM.pkl'),features_sha256=sha(FEAT/'features.parquet'),
        audit_sha256=sha(FEAT/'audit_result.json'),plan_sha256=sha(ROOT/'docs/JEJU_STEWARD_MARKETS_PROTOCOL_2026-09-18.md'),
        candidates=dict(STEWARD=STEWARD,PACE_BURDEN=PACE_BURDEN),seeds=[17,43],rank_params=config['rank_params'],
        main_comparisons='A/B/C x2, day bootstrap5000 Bonferroni6',unchanged_order=True))
    frame,truth,folds=data_frame()
    frame=frame.join(pl.read_parquet(FEAT/'features.parquet'),on='entry_id',validate='1:1')
    parts={role:frame.join(folds.filter(pl.col('role')==role).select('race_id'),on='race_id',how='semi').sort('race_id','horse_id')
           for role in ['fit','tune','calibration','evaluation']}
    assert parts['evaluation']['finish_position'].null_count()==len(parts['evaluation'])==4852
    groups={k:race_groups(v,truth) for k,v in parts.items() if k!='evaluation'}
    ranks={'BASE':old['rank_bundle']};ledger=[]
    rs={'BASE':rank_scores(ranks['BASE'],parts['evaluation'])}
    order=order_scores(old['order_bundle'],parts['evaluation'])
    for name,extras in [('STEWARD',STEWARD),('PACE_BURDEN',PACE_BURDEN)]:
        features=ranks['BASE']['features']+extras
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
        cal=rank_scores(bundle,parts['calibration'])
        opt=minimize_scalar(lambda x:order_loss(cal,groups['calibration'],np.exp(x)),bounds=(-4,4),method='bounded',options={'xatol':1e-5})
        assert opt.success
        bundle['beta']=float(np.exp(opt.x));ranks[name]=bundle
        rs[name]=rank_scores(bundle,parts['evaluation'])
        (OUT/'bundles'/f'{name}.pkl').write_bytes(pickle.dumps(bundle))
    scoreframes=[]
    for name,bundle in ranks.items():
        scoreframes.append(parts['evaluation'].select('entry_id','race_id','horse_id','event_date').with_columns(
            pl.lit(name).alias('model'),pl.Series('score',rs[name]),pl.Series('order_score',order),
            pl.lit(bundle['beta']).alias('beta'),pl.lit(old['beta_order']).alias('beta_order')))
    scores=pl.concat(scoreframes);scores.write_parquet(OUT/'frozen_scores.parquet')
    save('prediction_lock.json',dict(created_at=datetime.now(UTC).isoformat(),files={str(p.relative_to(OUT)):sha(p)
        for p in [OUT/'protocol.json',OUT/'frozen_scores.parquet',*sorted((OUT/'bundles').glob('*.pkl'))]}))
    labels=pl.read_parquet(DATA/'labels.parquet').filter(pl.col('event_date').dt.year()==2026)
    official={};truths={}
    for r in labels.filter(pl.col('label_top3')==1).to_dicts():official.setdefault(r['race_id'],[]).append(r['horse_id'])
    for r in pl.read_parquet(DATA/'accepted_orders.parquet').filter(pl.col('event_date').dt.year()==2026).to_dicts():
        truths.setdefault(r['race_id'],[]).append((r['first_horse_id'],r['second_horse_id'],r['third_horse_id']))
    races=[];horses=[]
    for (name,rid),part in scores.partition_by(['model','race_id'],as_dict=True).items():
        part=part.sort('horse_id');ids=part['horse_id'].to_list()
        met=evaluate_hybrid_race(ids,part['score'].to_numpy(),part['order_score'].to_numpy(),truths[rid],official[rid],
            beta_set=part['beta'][0],beta_order=part['beta_order'][0])
        p=met.pop('pl_marginals');y=met.pop('official_labels')
        races.append(dict(model=name,race_id=rid,event_date=part['event_date'][0],**met))
        horses.extend(dict(model=name,race_id=rid,horse_id=h,p=pr,y=yy) for h,pr,yy in zip(ids,p,y,strict=True))
    r=pl.from_dicts(races);r.write_parquet(OUT/'race_predictions.parquet')
    pl.from_dicts(horses).write_parquet(OUT/'horse_predictions.parquet')
    summary=r.group_by('model').agg(pl.len().alias('races'),*[pl.col(k).sum() for k in ['pick_hit','set_hit','order_hit']],pl.col('place_brier').mean()).sort('model')
    save('summary.json',summary.to_dicts());print(summary,flush=True)
    ref=r.filter(pl.col('model')=='BASE').sort('race_id')
    assert [ref[k].sum() for k in ['pick_hit','set_hit','order_hit']]==[317,32,7]
    comparisons=[]
    for name in ['STEWARD','PACE_BURDEN']:
        cand=r.filter(pl.col('model')==name).sort('race_id')
        assert cand['race_id'].to_list()==ref['race_id'].to_list()
        for metric in ['pick_hit','set_hit','order_hit']:
            delta=cand[metric].to_numpy().astype(float)-ref[metric].to_numpy().astype(float)
            days=ref['event_date'].to_list();unique=sorted(set(days))
            count=np.array([days.count(day) for day in unique])
            total=np.array([sum(delta[i] for i,d in enumerate(days) if d==day) for day in unique])
            ix=np.random.default_rng(17).integers(0,len(unique),(5000,len(unique)))
            boot=total[ix].sum(axis=1)/count[ix].sum(axis=1)
            low,high=np.quantile(boot,[.025/6,1-.025/6])
            comparisons.append(dict(candidate=name,metric=metric,difference=float(delta.mean()),low=float(low),high=float(high),improvement_signal=bool(low>0)))
    save('primary_comparisons.json',comparisons)
    q=r.with_columns(pl.col('event_date').dt.quarter().alias('quarter')).group_by('model','quarter').agg(
        pl.len().alias('races'),*[pl.col(k).sum() for k in ['pick_hit','set_hit','order_hit']]).sort('model','quarter')
    save('quarter_summary.json',q.to_dicts())
    coverage=[]
    for role,part in parts.items():
        coverage.append(dict(role=role,rows=len(part),previous_report_known=int(part['st2_report_known'].sum()),
            previous_event=int(part['st2_event_any'].fill_null(0).sum()),previous_start_delay=int(part['st2_start_delay'].fill_null(0).sum()),
            pace_profile_known=int((part['pb_valid_count_3']>0).sum())))
    save('coverage.json',coverage)
    save('manifest.json',dict(files={str(p.relative_to(OUT)):sha(p) for p in OUT.rglob('*') if p.is_file()},
        baseline_unchanged=sha(OLD/'bundles/frozen_2026__HY_R_FORM.pkl')==json.loads((OUT/'protocol.json').read_text())['old_model_sha256']))

if __name__=='__main__':main()
