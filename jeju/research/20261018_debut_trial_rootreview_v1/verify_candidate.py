"""Independent frozen-model replay and cold-start metrics; no fits or optimizers."""
from pathlib import Path
from itertools import combinations
import importlib.util, json, hashlib
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
MAIN=ROOT/'jeju/research/20261018_debut_trial_ablation_v1/outputs'
BASE=ROOT/'jeju/research/20261010_style_history_ablation_v1/outputs'
VARIANT='F1_STYLE6_DEBUT_TRIAL4'
HELPER=ROOT/'jeju/research/20261017_1000m_five_section_rootreview_v1/independent.py'
spec=importlib.util.spec_from_file_location('verified_old_root_helpers',HELPER)
helper=importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def calibration_gradient(frame,z,tau):
    objective=[];gradient=[]
    for _,ix in frame.groupby('race_id',sort=False).indices.items():
        f=frame.iloc[ix];v=z[ix];sets=np.array(list(combinations(range(len(f)),3)))
        e=np.array([sum(sorted(v[s].tolist())) for s in sets]);a=e/tau
        normalizer=a.max()+np.log(np.exp(a-a.max()).sum());q=np.exp(a-normalizer)
        truth=tuple(np.flatnonzero(f.finish_position.to_numpy()<=3))
        t=next(i for i,s in enumerate(sets) if tuple(s)==truth)
        objective.append(normalizer-e[t]/tau);gradient.append((e[t]-q@e)/tau**2)
    return float(np.mean(objective)),float(np.mean(gradient))

def cold_concordance(u,features):
    joined=u.merge(features[['api_record_id','observed_starts','finish_position']],on='api_record_id',validate='one_to_one')
    rows=[]
    for rid,g in joined[joined.observed_starts.eq(0)].groupby('race_id',sort=False):
        p=g[g.finish_position.le(3)].score.to_numpy();n=g[g.finish_position.gt(3)].score.to_numpy()
        if len(p) and len(n):
            d=p[:,None]-n[None,:]
            rows.append({'race_id':rid,'pairs':int(d.size),'concordance':float(np.where(d>0,1.,np.where(d==0,.5,0.)).mean())})
    return pd.DataFrame(rows)

def main():
    features=pd.read_parquet(MAIN/'features_f1_style6_debut_trial4.parquet')
    original=pd.read_parquet(BASE/'features.parquet')
    pd.testing.assert_frame_equal(features[original.columns],original,check_exact=True)
    source_lock=json.loads((HERE/'ROOT_SOURCE_LOCK.json').read_text())
    assert sha(HELPER)==source_lock['prior_root_evaluator_sha256']
    races=[];runners=[];tickets=[];folds={}
    for year in (2024,2025,2026):
        folder=MAIN/f'{VARIANT}_{year}';test=features[features.year.eq(year)].reset_index(drop=True)
        z,meta=helper.replay(test,folder);oldmeta=json.loads((BASE/f'F1_STYLE6_{year}'/'meta.json').read_text())
        assert meta['features'][:30]==oldmeta['features'] and len(meta['features'])==34
        assert meta['parameters']==oldmeta['parameters'] and meta['vocabulary']==oldmeta['vocabulary']
        assert features.loc[features.observed_starts.gt(0),meta['features'][30:]].isna().all().all()
        for key in ['training_min','initial_training_max','early_stopping_min','refit_max','calibration_min','calibration_max','evaluation_min','evaluation_max','calibration_rows','calibration_races','evaluation_rows','evaluation_races']:
            assert meta[key]==oldmeta[key],(year,key)
        assert meta.get('train_rows_refit',meta.get('train_rows'))==oldmeta['train_rows']
        assert meta.get('train_races_refit',meta.get('train_races'))==oldmeta['train_races']
        stored=pd.read_parquet(folder/'evaluation_scores.parquet').set_index('api_record_id').loc[test.api_record_id]
        error=float(abs(stored.score.to_numpy()-z).max());assert error<1e-12
        cal=features[features.year.eq(year-1)].reset_index(drop=True);cz,_=helper.replay(cal,folder)
        sc=pd.read_parquet(folder/'calibration_scores.parquet').set_index('api_record_id').loc[cal.api_record_id]
        assert np.allclose(sc.score,cz,atol=1e-12,rtol=0)
        tau=meta['tau'];objective,grad=calibration_gradient(cal,cz,tau)
        assert .35<=tau<=4
        projected=grad if .35001<tau<3.99999 else min(grad,0) if tau<=.35001 else max(grad,0)
        assert abs(projected)<1e-4,(year,tau,grad)
        r,u,t=helper.evaluate(test,z,tau,VARIANT);races.append(r);runners.append(u);tickets.append(t)
        folds[str(year)]={'score_error':error,'tau':tau,'calibration_trio_nll':objective,'tau_gradient':grad,'trees':meta['trees']}
    r=pd.concat(races,ignore_index=True);u=pd.concat(runners,ignore_index=True);t=pd.concat(tickets,ignore_index=True)
    r.to_parquet(HERE/'ROOT_CANDIDATE_RACE_METRICS.parquet',index=False)
    u.to_parquet(HERE/'ROOT_CANDIDATE_RUNNERS.parquet',index=False)
    t.to_parquet(HERE/'ROOT_CANDIDATE_TICKETS.parquet',index=False)
    old_u=pd.read_parquet(HERE/'ROOT_BASELINE_RUNNERS.parquet');old_r=pd.read_parquet(HERE/'ROOT_BASELINE_RACE_METRICS.parquet')
    context=features[['api_record_id','observed_starts','race_date','year','distance_m']]
    pairs=u.merge(old_u,on=['api_record_id','race_id'],validate='one_to_one',suffixes=('_candidate','_baseline')).merge(context,on='api_record_id',validate='one_to_one')
    all_dates=sorted(r.race_date.unique());assert len(all_dates)==269
    dmap={d:i for i,d in enumerate(all_dates)}
    schedule_path=ROOT/'jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy'
    assert sha(schedule_path)=='d141b0c3f9a463cbfc9d1f4c61228b58757c31aee4ec74b79f41c5baeadaccbd'
    assert hashlib.sha256('\n'.join(all_dates).encode()).hexdigest()=='e4aa73b866eac00b361d0354fdd62b7b2bd98915e003f250adc40a8df0a66b84'
    schedule=np.load(schedule_path,allow_pickle=False)
    assert schedule.shape==(2000,269)
    weights=np.stack([np.bincount(v,minlength=269) for v in schedule])
    summary=[]
    for scope,mask in [('cold',pairs.observed_starts.eq(0)),('all',pd.Series(True,index=pairs.index)),('experienced',pairs.observed_starts.gt(0))]:
        selected=pairs[mask]
        rg=selected.groupby(['race_id','race_date','year'],sort=False)[['log_loss_candidate','log_loss_baseline','brier_candidate','brier_baseline']].mean().reset_index()
        if scope=='cold':assert len(selected)==661 and len(rg)==252;rg.to_parquet(HERE/'ROOT_CANDIDATE_PAIRED_COLD_METRICS.parquet',index=False)
        ix=rg.race_date.map(dmap).to_numpy();den=weights@np.bincount(ix,minlength=269);assert (den>0).all()
        for metric in ['log_loss','brier']:
            diff=(rg[metric+'_candidate']-rg[metric+'_baseline']).to_numpy()
            draws=(weights@np.bincount(ix,weights=diff,minlength=269))/den
            lo,hi=np.quantile(draws,[.025,.975])
            summary.append({'scope':scope,'metric':metric,'runner_rows':len(selected),'races':len(rg),'baseline':rg[metric+'_baseline'].mean(),'candidate':rg[metric+'_candidate'].mean(),'delta':diff.mean(),'ci_low':lo,'ci_high':hi})
    race_pairs=r.merge(old_r,on=['race_id','race_date','year','distance_m'],validate='one_to_one',suffixes=('_candidate','_baseline'))
    for scope,g in [('all',race_pairs),('cold_containing_races',race_pairs[race_pairs.race_id.isin(features.loc[features.observed_starts.eq(0),'race_id'])])]:
        for metric in ['pick_hit','top5_capture','top5_all3','six_combo_hit','trio_nll']:
            summary.append({'scope':scope,'metric':metric,'runner_rows':np.nan,'races':len(g),'baseline':g[metric+'_baseline'].mean(),'candidate':g[metric+'_candidate'].mean(),'delta':(g[metric+'_candidate']-g[metric+'_baseline']).mean(),'ci_low':np.nan,'ci_high':np.nan})
    concord=cold_concordance(u,features);old_concord=pd.read_parquet(HERE/'ROOT_BASELINE_COLD_CONCORDANCE.parquet')
    c=concord.merge(old_concord,on=['race_id','pairs'],validate='one_to_one',suffixes=('_candidate','_baseline'))
    assert len(c)==118 and c.pairs.sum()==398
    ix=c.merge(r[['race_id','race_date']],on='race_id',validate='one_to_one').race_date.map(dmap).to_numpy()
    den=weights@np.bincount(ix,minlength=269);assert (den>0).all()
    cdiff=(c.concordance_candidate-c.concordance_baseline).to_numpy()
    draws=(weights@np.bincount(ix,weights=cdiff,minlength=269))/den;lo,hi=np.quantile(draws,[.025,.975])
    summary.append({'scope':'cold_concordance','metric':'within_race_pair_concordance','runner_rows':np.nan,'races':len(c),'baseline':c.concordance_baseline.mean(),'candidate':c.concordance_candidate.mean(),'delta':cdiff.mean(),'ci_low':lo,'ci_high':hi})
    concord.to_parquet(HERE/'ROOT_CANDIDATE_COLD_CONCORDANCE.parquet',index=False)
    summary=pd.DataFrame(summary);summary.to_csv(HERE/'ROOT_PAIRED_RESULTS.csv',index=False)
    primary=summary[summary.scope.eq('cold')&summary.metric.isin(['log_loss','brier'])]
    gate=bool(primary.delta.lt(0).all() and primary.ci_high.lt(0).any())
    proof={'status':'PASS','root_fit_or_optimizer_calls':0,'models_replayed':3,'primary_cold_rows':661,'primary_cold_races':252,'primary_gate_pass':gate,'folds':folds,'feature_sha256':sha(MAIN/'features_f1_style6_debut_trial4.parquet')}
    (HERE/'ROOT_CANDIDATE_REVIEW.json').write_text(json.dumps(proof,indent=2)+'\n')
    print(json.dumps(proof,indent=2));print(summary.to_string(index=False))

if __name__=='__main__':main()
