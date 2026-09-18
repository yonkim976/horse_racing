"""Twelve fixed annual ranking fits; frozen order heads; no odds or subgroup selection."""
import hashlib,json,pickle
from datetime import datetime,UTC
from pathlib import Path
import lightgbm as lgb
import numpy as np
import polars as pl
from scipy.optimize import minimize_scalar
from horse_racing.analysis.jeju_top3_preprocessing import FitPreprocessor
from horse_racing.analysis.jeju_tempo_pace import PACE
from horse_racing.analysis.jeju_hybrid_evaluation import evaluate_hybrid_race
from scripts.run_jeju_transition_holdout import data_frame
from scripts.run_jeju_context_experiment import rank_scores,order_scores
from scripts.run_jeju_top3_experiment import race_groups,order_loss
from scripts.run_jeju_annual_revalidation import annual_parts

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data/research/jeju_accuracy_candidates_20260919'
DATA=ROOT/'data/research/jeju_native_top3_dataset_v1_20260915_r2'
ANN=ROOT/'data/research/jeju_annual_revalidation_20260918'
OLD=ROOT/'data/research/jeju_native_transition_holdout_v13_20260916'
FEAT=ROOT/'data/research/jeju_tempo_pace_features_20260917'
PLAN=ROOT/'docs/JEJU_ACCURACY_CANDIDATES_PROTOCOL_2026-09-19.md'
GROWTH=['current_minus_previous_elo','progression_last3_vs_prev3','best_last5_performance','poor_last_but_good_late']
def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def save(name,obj):
    (OUT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2,default=str,allow_nan=False))
def main():
    OUT.mkdir(exist_ok=False);(OUT/'bundles').mkdir()
    old=pickle.loads((OLD/'bundles/frozen_2026__HY_R_FORM.pkl').read_bytes())
    params=json.loads((OLD/'protocol.json').read_text())['rank_params']
    features={'PACE':old['rank_bundle']['features']+PACE,'NO_GROWTH':[f for f in old['rank_bundle']['features'] if f not in GROWTH]}
    assert len(features['PACE'])==121 and len(features['NO_GROWTH'])==104
    save('protocol.json',dict(created_at=datetime.now(UTC).isoformat(),plan_sha256=sha(PLAN),script_sha256=sha(Path(__file__)),
        features=features,rank_params=params,seeds=[17,43],years=[2024,2025,2026],max_new_fits=12,
        feature_sha256=sha(FEAT/'features.parquet'),reference_sha256=sha(OLD/'bundles/frozen_2026__HY_R_FORM.pkl'),
        order_model='existing annual BASE order unchanged',status='previously seen retrospective development'))
    frame,truth,_=data_frame()
    frame=frame.join(pl.read_parquet(DATA/'races.parquet').filter(pl.col('target_eligible')).select('race_id'),on='race_id',how='semi')
    frame=frame.join(pl.read_parquet(FEAT/'features.parquet'),on='entry_id',validate='1:1')
    ledger=[];boundaries=[];all_scores=[]
    for year in [2024,2025,2026]:
        parts=annual_parts(frame,year)
        for a,b in [('fit','tune'),('tune','calibration'),('calibration','evaluation')]:assert parts[a]['event_date'].max()<parts[b]['event_date'].min()
        for role,d in parts.items():boundaries.append(dict(year=year,role=role,first=d['event_date'].min(),last=d['event_date'].max(),races=d['race_id'].n_unique(),rows=len(d)))
        groups={k:race_groups(v,truth) for k,v in parts.items() if k!='evaluation'}
        if year==2026:
            base=old['rank_bundle'];ob=old['order_bundle'];beta_order=old['beta_order']
        else:
            base=pickle.loads((ANN/f'bundles/{year}__BASE.pkl').read_bytes())
            ob=pickle.loads((ANN/f'bundles/{year}__ORDER.pkl').read_bytes());beta_order=ob['beta_order']
        order=order_scores(ob,parts['evaluation'])
        bundles={'BASE':base}
        for name,cols in features.items():
            pre=FitPreprocessor().fit(parts['fit'],cols);xs={k:pre.transform(v) for k,v in parts.items()}
            ys={k:np.where(np.isfinite(v['finish_position'].to_numpy().astype(float))&(v['finish_position'].to_numpy()<=3),4-v['finish_position'].to_numpy(),0).astype(int) for k,v in parts.items() if k in ['fit','tune']}
            models=[]
            for seed in [17,43]:
                model=lgb.LGBMRanker(objective='lambdarank',label_gain=[0,1,3,7],random_state=seed,verbosity=-1,**params)
                model.fit(xs['fit'],ys['fit'],group=[hi-lo for lo,hi,_ in groups['fit']],eval_set=[(xs['tune'],ys['tune'])],eval_group=[[hi-lo for lo,hi,_ in groups['tune']]],eval_at=[3],callbacks=[lgb.early_stopping(30,verbose=False)])
                models.append(model);ledger.append(dict(year=year,model=name,seed=seed,best_iteration=int(model.best_iteration_)))
                save('fit_ledger.json',ledger);print(year,name,seed,'done',flush=True)
            bundle=dict(kind='ranker',features=cols,preprocessor=pre,models=models)
            cal=rank_scores(bundle,parts['calibration'])
            opt=minimize_scalar(lambda x:order_loss(cal,groups['calibration'],np.exp(x)),bounds=(-4,4),method='bounded',options={'xatol':1e-5})
            assert opt.success
            bundle['beta']=float(np.exp(opt.x));bundles[name]=bundle
            (OUT/f'bundles/{year}__{name}.pkl').write_bytes(pickle.dumps(bundle))
        for name,b in bundles.items():
            x=b['preprocessor'].transform(parts['evaluation']);seed_scores=[m.predict(x,raw_score=True) for m in b['models']]
            all_scores.append(parts['evaluation'].select('entry_id','race_id','horse_id','event_date').with_columns(pl.lit(year).alias('year'),pl.lit(name).alias('model'),
                pl.Series('score',np.mean(seed_scores,axis=0)),pl.Series('seed17',seed_scores[0]),pl.Series('seed43',seed_scores[1]),
                pl.Series('order_score',order),pl.lit(b['beta']).alias('beta'),pl.lit(beta_order).alias('beta_order')))
    save('boundaries.json',boundaries)
    scores=pl.concat(all_scores);scores.write_parquet(OUT/'frozen_scores.parquet')
    save('prediction_lock.json',dict(created_at=datetime.now(UTC).isoformat(),files={str(p.relative_to(OUT)):sha(p) for p in [OUT/'protocol.json',OUT/'frozen_scores.parquet',*sorted((OUT/'bundles').glob('*.pkl'))]}))
    accepted={};official={}
    for r in pl.read_parquet(DATA/'accepted_orders.parquet').to_dicts():accepted.setdefault(r['race_id'],[]).append((r['first_horse_id'],r['second_horse_id'],r['third_horse_id']))
    for r in pl.read_parquet(DATA/'labels.parquet').filter(pl.col('label_top3')==1).to_dicts():official.setdefault(r['race_id'],[]).append(r['horse_id'])
    races=[];horses=[];seeds=[]
    for (year,name,rid),part in scores.partition_by(['year','model','race_id'],as_dict=True).items():
        part=part.sort('horse_id');ids=part['horse_id'].to_list()
        met=evaluate_hybrid_race(ids,part['score'].to_numpy(),part['order_score'].to_numpy(),accepted[rid],official[rid],beta_set=part['beta'][0],beta_order=part['beta_order'][0])
        p=met.pop('pl_marginals');y=met.pop('official_labels')
        races.append(dict(year=year,model=name,race_id=rid,event_date=part['event_date'][0],**met))
        horses.extend(dict(year=year,model=name,race_id=rid,horse_id=h,p=pp,y=yy) for h,pp,yy in zip(ids,p,y,strict=True))
        # PL top set and top marginal are score-ordered; audit this against full evaluator.
        ranking=sorted(range(len(ids)),key=lambda i:(-part['score'][i],ids[i]))
        assert set(ids[i] for i in ranking[:3])==set(met['predicted_set'])
        for seed in [17,43]:
            rank=sorted(range(len(ids)),key=lambda i:(-part[f'seed{seed}'][i],ids[i]));selection={ids[i] for i in rank[:3]}
            seeds.append(dict(year=year,model=name,seed=seed,race_id=rid,pick_hit=ids[rank[0]] in official[rid],set_hit=any(selection==set(a) for a in accepted[rid])))
    r=pl.from_dicts(races);r.write_parquet(OUT/'race_predictions.parquet');pl.from_dicts(horses).write_parquet(OUT/'horse_predictions.parquet')
    pl.from_dicts(seeds).write_parquet(OUT/'seed_race_predictions.parquet')
    agg=[pl.len().alias('races'),*[pl.col(k).sum() for k in ['pick_hit','set_hit','order_hit']],pl.col('place_brier').mean()]
    summary=r.group_by('year','model').agg(*agg).sort('year','model');save('summary.json',summary.to_dicts());print(summary,flush=True)
    save('quarters.json',r.with_columns(pl.col('event_date').dt.quarter().alias('quarter')).group_by('year','quarter','model').agg(*agg).sort('year','quarter','model').to_dicts())
    save('seed_summary.json',pl.from_dicts(seeds).group_by('year','model','seed').agg(pl.len().alias('races'),pl.col('pick_hit').sum(),pl.col('set_hit').sum()).sort('year','model','seed').to_dicts())
    comparisons=[]
    for name in features:
        boot_total=np.zeros(5000);weighted_diff=0;count_total=0;year_diffs=[]
        rng=np.random.default_rng(17)
        for year in [2024,2025,2026]:
            ref=r.filter((pl.col('year')==year)&(pl.col('model')=='BASE')).sort('race_id');cand=r.filter((pl.col('year')==year)&(pl.col('model')==name)).sort('race_id')
            assert ref['race_id'].to_list()==cand['race_id'].to_list()
            delta=cand['set_hit'].to_numpy().astype(float)-ref['set_hit'].to_numpy().astype(float)
            days=ref['event_date'].to_list();unique=sorted(set(days));count=np.array([days.count(d) for d in unique])
            totals=np.array([sum(delta[i] for i,d in enumerate(days) if d==day) for day in unique])
            ix=rng.integers(0,len(unique),(5000,len(unique)));boot=totals[ix].sum(axis=1)/count[ix].sum(axis=1)
            boot_total+=boot*len(ref);weighted_diff+=delta.sum();count_total+=len(ref);year_diffs.append(dict(year=year,delta_hits=int(delta.sum()),difference=float(delta.mean()),ci95=np.quantile(boot,[.025,.975]).tolist()))
        lo,hi=np.quantile(boot_total/count_total,[.0125,.9875])
        comparisons.append(dict(candidate=name,metric='B',races=count_total,difference=weighted_diff/count_total,simultaneous95=[float(lo),float(hi)],years=year_diffs,
            promote_development=bool(lo>0 and sum(x['delta_hits']>0 for x in year_diffs)>=2 and year_diffs[-1]['delta_hits']>0)))
    save('primary_comparisons.json',comparisons)
    save('manifest.json',dict(files={str(p.relative_to(OUT)):sha(p) for p in OUT.rglob('*') if p.is_file()}))
    print(json.dumps(comparisons,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
