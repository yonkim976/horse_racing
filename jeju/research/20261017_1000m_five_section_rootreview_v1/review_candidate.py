"""Replay frozen candidate and independently evaluate/contrast without fitting."""
from pathlib import Path
from itertools import combinations
import json
import numpy as np
import pandas as pd
from independent import replay,evaluate,sha

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
BASE=ROOT/'jeju/research/20261010_style_history_ablation_v1/outputs'
MAIN=ROOT/'jeju/research/20261017_1000m_five_section_ablation_v1/outputs'

def temperature_gradient(frame,scores,tau):
    losses=[];gradients=[]
    for _,indices in frame.groupby('race_id',sort=False).indices.items():
        f=frame.iloc[indices];z=np.asarray(scores)[indices];sets=np.array(list(combinations(range(len(f)),3)),int)
        e=np.array([sum(sorted(z[s].tolist())) for s in sets]);a=e/tau;normalizer=float(a.max()+np.log(np.exp(a-a.max()).sum()));q=np.exp(a-normalizer)
        t=tuple(np.flatnonzero(f.finish_position.to_numpy()<=3));i=next(i for i,s in enumerate(sets) if tuple(s)==t)
        losses.append(normalizer-e[i]/tau);gradients.append((e[i]-q@e)/tau**2)
    return float(np.mean(losses)),float(np.mean(gradients))

def main():
    f=pd.read_parquet(MAIN/'features_f1_style6_5section.parquet');original=pd.read_parquet(BASE/'features.parquet')
    pd.testing.assert_frame_equal(f[original.columns],original,check_exact=True)
    metrics=[];runners=[];tickets=[];folds={}
    for year in (2024,2025,2026):
        folder=MAIN/f'F1_STYLE6_5SECTION_{year}';test=f[f.year.eq(year)].reset_index(drop=True);z,meta=replay(test,folder)
        baseline_meta=json.loads((BASE/f'F1_STYLE6_{year}'/'meta.json').read_text())
        assert meta['features'][:30]==baseline_meta['features'] and len(meta['features'])==40
        assert meta['parameters']==baseline_meta['parameters'] and meta['vocabulary']==baseline_meta['vocabulary']
        extra=meta['features'][30:];assert f.loc[f.distance_m.ne(1000),extra].isna().all().all()
        for item in ['training_min','initial_training_max','early_stopping_min','refit_max','calibration_min','calibration_max','evaluation_min','evaluation_max','calibration_rows','calibration_races','evaluation_rows','evaluation_races']:
            assert meta[item]==baseline_meta[item],(year,item,meta.get(item),baseline_meta.get(item))
        assert meta['train_rows_refit']==baseline_meta['train_rows']
        assert meta['train_races_refit']==baseline_meta['train_races']
        stored=pd.read_parquet(folder/'evaluation_scores.parquet').set_index('api_record_id').loc[test.api_record_id]
        err=float(abs(stored.score.to_numpy()-z).max());assert err<1e-12
        cal=f[f.year.eq(year-1)].reset_index(drop=True);cz,_=replay(cal,folder);sc=pd.read_parquet(folder/'calibration_scores.parquet').set_index('api_record_id').loc[cal.api_record_id]
        assert np.allclose(sc.score.to_numpy(),cz,atol=1e-12,rtol=0)
        tau=meta['tau'];value,grad=temperature_gradient(cal,cz,tau)
        assert .35<=tau<=4
        projected=grad if .35001<tau<3.99999 else min(grad,0) if tau<=.35001 else max(grad,0)
        assert abs(projected)<1e-4,(year,tau,grad)
        r,u,t=evaluate(test,z,tau,'F1_STYLE6_5SECTION');metrics.append(r);runners.append(u);tickets.append(t)
        folds[str(year)]={'score_error':err,'tau':tau,'calibration_nll':value,'tau_objective_gradient':grad,'tau_projected_gradient':projected,'trees':meta['trees']}
    results=pd.concat(metrics,ignore_index=True);results.to_csv(HERE/'ROOT_CANDIDATE_RACE_METRICS.csv',index=False)
    pd.concat(runners,ignore_index=True).to_parquet(HERE/'ROOT_CANDIDATE_RUNNERS.parquet',index=False)
    pd.concat(tickets,ignore_index=True).to_csv(HERE/'ROOT_CANDIDATE_TICKETS.csv',index=False)
    baseline=pd.read_csv(HERE/'ROOT_BASELINE_RACE_METRICS.csv');keys=['race_id','race_date','year','distance_m'];paired=results.merge(baseline,on=keys,validate='one_to_one',suffixes=('_candidate','_baseline'))
    dates=sorted(paired.race_date.unique());assert len(dates)==269;di={d:i for i,d in enumerate(dates)}
    schedule=np.load(ROOT/'jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy',allow_pickle=False);weights=np.stack([np.bincount(row,minlength=269) for row in schedule])
    rows=[]
    for scope,mask in [('1000m',paired.distance_m.eq(1000)),('all',pd.Series(True,index=paired.index)),('other_distances',paired.distance_m.ne(1000))]:
        p=paired[mask];ix=p.race_date.map(di).to_numpy(int);count=np.bincount(ix,minlength=269);den=weights@count
        for metric in ['log_loss','brier','trio_nll','pick_hit','top5_capture','top5_all3','six_combo_hit']:
            delta=(p[metric+'_candidate']-p[metric+'_baseline']).to_numpy();draws=(weights@np.bincount(ix,weights=delta,minlength=269))/den;lo,hi=np.quantile(draws,[.025,.975])
            rows.append({'scope':scope,'metric':metric,'races':len(p),'baseline':float(p[metric+'_baseline'].mean()),'candidate':float(p[metric+'_candidate'].mean()),'delta':float(delta.mean()),'ci_low':float(lo),'ci_high':float(hi)})
    summary=pd.DataFrame(rows);summary.to_csv(HERE/'ROOT_PAIRED_RESULTS.csv',index=False)
    primary=summary[summary.scope.eq('1000m')&summary.metric.isin(['log_loss','brier'])];gate=bool(primary.delta.lt(0).all() & primary.ci_high.lt(0).any())
    proof={'status':'PASS','source_feature_base_columns_unchanged':True,'models_reloaded':3,'root_fit_or_optimizer_calls':0,'folds':folds,'primary_races':508,'primary_gate_pass':gate,'feature_sha256':sha(MAIN/'features_f1_style6_5section.parquet')}
    (HERE/'ROOT_CANDIDATE_REVIEW.json').write_text(json.dumps(proof,indent=2)+'\n');print(json.dumps(proof,indent=2));print(summary.to_string(index=False))

if __name__=='__main__':main()
