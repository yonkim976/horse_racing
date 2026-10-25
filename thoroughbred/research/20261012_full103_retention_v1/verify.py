"""Replay merged model candidates and audit deduplication and probability swaps."""
import json
import itertools
import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.special import logsumexp
import run as e


def main():
    e.check()
    a=pd.read_parquet(e.OLD/'outputs/features.parquet')
    b=pd.read_parquet(e.NEW/'outputs/features.parquet')
    f=pd.read_parquet(e.OUT/'features.parquet')
    pd.testing.assert_frame_equal(f[e.BASE],a[e.BASE])
    for c in e.GAPS+e.KEEP:
        pd.testing.assert_series_equal(f[c],b[c])
    assert json.loads((e.NEW/'outputs/verification.json').read_text())['passed']
    h=pd.read_parquet(e.NEW/'outputs/history_events.parquet')
    slots=np.load(e.S.HERE/'outputs/history_slots.npy',allow_pickle=False)
    for lag in range(5):
        ok=slots[:,lag]>=0;src=h.iloc[slots[ok,lag]];dst=f[ok]
        assert np.array_equal(src.horse_id.to_numpy(),dst.horse_id.to_numpy())
        assert (src.race_date.to_numpy()<=dst.cutoff_date.to_numpy()).all()
        assert ((dst.race_date.to_numpy()-src.race_date.to_numpy())/np.timedelta64(1,'D')<=730).all()
    ids=f.sample(200,random_state=20261012).index
    for j in ids:
        prior=h.iloc[slots[j][slots[j]>=0]];own=f.iloc[j]
        for kind in ['front','fast','outerfast']:
            v=prior['event_'+kind+'_g3'].dropna();n=len(v)
            assert n==own['keep_'+kind+'_n']
            for part in ['g3','g1']:
                v=prior['event_'+kind+'_'+part].dropna()
                expected=v.mean()*n/(n+3) if n else np.nan
                np.testing.assert_allclose(own['keep_'+kind+'_'+part],expected,equal_nan=True,atol=1e-12)
        peers=f[(f.race_key==own.race_key)&(f.program_no<own.program_no)]
        v=peers.section_early_mean3.dropna()
        for suffix,expected in [('fastest',v.min()-own.section_early_mean3),('mean',v.mean()-own.section_early_mean3)]:
            np.testing.assert_allclose(own['inner_inner_'+suffix+'_gap'],expected,equal_nan=True,atol=1e-12)
    keys=f.race_key.drop_duplicates().sample(60,random_state=42)
    mask=f.race_key.isin(keys)
    aa=a[mask].reset_index(drop=True);bb=b[mask].reset_index(drop=True)
    for frame in [aa,bb]:
        for c in frame:
            if c.startswith('aux_') or c in ['outcome','front_label']:frame[c]=-9999
    poisoned,_=e.build(aa,bb)
    cols=list(dict.fromkeys(sum(e.CONTRACTS.values(),[])))
    pd.testing.assert_frame_equal(poisoned[cols],f.loc[mask,cols].reset_index(drop=True))
    # Counterfactual: replacing original probability cannot affect the swapped inputs.
    swapcols=e.CONTRACTS['swapped122']
    assert not any(c in swapcols for c in ['front_gate_probability']+e.RELATIONS+e.INTER)
    temp=f[mask].reset_index(drop=True).copy()
    expected=e.swapped_features(temp)
    temp['front_gate_probability']=.987654
    pd.testing.assert_frame_equal(expected,e.swapped_features(temp))
    aux=0
    for folder,source,column,isold in [(e.OLD/'outputs/front_models',a,'front_gate_probability',True),
                                       (e.NEW/'outputs/front_models',b,'front_probability',False)]:
        paths=sorted(folder.glob('gate_*')) if isold else sorted(folder.iterdir())
        for path in paths:
            m=json.loads((path/'metadata.json').read_text());year=m['year']
            assert m['train_end']<f'{year}-01-01' and e.sha(path/'model.txt')==m['model_sha256']
            train=source.year.between(2017,year-1)&source.front_label.notna()
            x,vocab=e.S.encode(source,m['features'],train);assert vocab==m['category_vocabulary']
            model=lgb.Booster(model_file=str(path/'model.txt'));test=source.year==year
            p=model.predict(x[test],num_threads=4)
            np.testing.assert_allclose(p,source.loc[test,column],atol=1e-12,rtol=0)
            aux+=1
    diagnostics=pd.read_csv(e.OUT/'race_diagnostics.csv').set_index(['variant','race_key'])
    models=0;maximum=0.;metric_checks=0
    for folder in sorted((e.OUT/'models').iterdir()):
        m=json.loads((folder/'metadata.json').read_text());p=pd.read_parquet(folder/'runners.parquet')
        assert m['train_end']<f"{m['calibration_year']}-01-01"
        assert e.sha(folder/'model.txt')==m['model_sha256']
        one=f[f.meet==p.meet.iloc[0]].reset_index(drop=True)
        train=one.year.between(2017,m['evaluation_year']-3);test=one.year==m['evaluation_year']
        x,vocab=e.S.encode(one,m['features'],train);assert vocab==m['category_vocabulary']
        model=lgb.Booster(model_file=str(folder/'model.txt'))
        z=one[test][e.S.KEY].copy();z['score']=model.predict(x[test],raw_score=True,num_threads=4)
        joined=z.merge(p,on=e.S.KEY,validate='one_to_one')
        error=float(np.max(np.abs(joined.score-joined.raw_score)));assert error<=1e-12;maximum=max(maximum,error)
        for rid,g in joined.groupby('race_key'):
            r=diagnostics.loc[(m['variant'],rid)]
            ranked=g.sort_values(['raw_score','program_no'],ascending=[False,True]);outcome=ranked.outcome.to_numpy()
            two=set(np.flatnonzero((outcome>=1)&(outcome<=2)))
            assert r.axis_top3==int(1<=outcome[0]<=3)
            assert r.axis_top2==int(0 in two)
            assert r.quinella_one==int(two=={0,1})
            assert r.axis_next3==int(0 in two and two<=set(range(4)))
            pos=np.flatnonzero((outcome>=1)&(outcome<=3))+1
            for k in [3,5,6]:assert r[f'top{k}_all']==int((pos<=k).all())
            sets=np.array(list(itertools.combinations(range(len(g)),3)))
            energy=g.raw_score.to_numpy()[sets].sum(axis=1)/m['temperature']
            q=np.exp(energy-logsumexp(energy));marginal=np.zeros(len(g))
            for ix,prob in zip(sets,q):marginal[ix]+=prob
            np.testing.assert_allclose(marginal,g.target_probability,atol=1e-12,rtol=0)
            assert abs(marginal.sum()-3)<1e-10
            truth=tuple(np.flatnonzero(g.outcome.between(1,3)))
            idx=next(j for j,combo in enumerate(sets) if tuple(combo)==truth)
            np.testing.assert_allclose(r.set_logloss,-np.log(q[idx]),atol=1e-12)
            np.testing.assert_allclose(r.target_brier,np.mean((marginal-g.outcome.between(1,3))**2),atol=1e-12)
            card=g.sort_values('program_no');triples=np.array(list(itertools.combinations(range(len(card)),3)))
            energy=card.raw_score.to_numpy()[triples].sum(axis=1);best=np.argsort(-energy,kind='stable')[:6]
            truth=tuple(np.flatnonzero(card.outcome.between(1,3)))
            assert r.trio6==int(any(tuple(triples[j])==truth for j in best))
            metric_checks+=1
        models+=1
    pred=pd.read_parquet(e.OUT/'runner_predictions.parquet')
    for variant,g in pred.groupby('variant'):
        assert len(g)==50754 and g.race_key.nunique()==4799
    old=pd.read_parquet(e.OLD/'outputs/runner_predictions.parquet')
    old=old[(old.variant=='full103')&(old.target==3)].reset_index(drop=True)
    old['variant']='baseline103'
    pd.testing.assert_frame_equal(old,pred[pred.variant=='baseline103'].reset_index(drop=True))
    assert models==18 and aux==14
    e.check()
    e.save(e.OUT/'verification.json',dict(passed=True,new_ability_models_replayed=models,frozen_front_models_replayed=aux,
          max_score_error=maximum,model_race_metrics_checked=metric_checks,history_rows_checked=200,
          whole_fields_poisoned=60,original103_inputs_and_predictions_unchanged=True,
          swapped_probability_no_original_dependency=True,same_4799_races=True,
          production_selected22_future_contract_hashes_unchanged=True))
    print('Verified',models,'new models,',aux,'frozen auxiliary models,',metric_checks,'race metrics')


if __name__=='__main__':main()
