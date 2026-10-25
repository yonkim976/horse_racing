"""Replay saved models and independently audit history and evaluation contracts."""
import json
import itertools
import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.special import logsumexp
import run as e


def main():
    e.check();f=pd.read_parquet(e.OUT/'features.parquet');h=pd.read_parquet(e.OUT/'history_events.parquet')
    slots=np.load(e.OLD/'outputs/history_slots.npy',allow_pickle=False)
    base=pd.read_parquet(e.OLD/'outputs/features.parquet')
    assert f[e.BASE].equals(base[e.BASE])
    for lag in range(5):
        known=slots[:,lag]>=0;src=h.iloc[slots[known,lag]];dst=f[known]
        assert np.array_equal(src.horse_id.to_numpy(),dst.horse_id.to_numpy())
        assert (src.race_date.to_numpy()<=dst.cutoff_date.to_numpy()).all()
        assert ((dst.race_date.to_numpy()-src.race_date.to_numpy())/np.timedelta64(1,'D')<=730).all()
    rng=np.random.default_rng(20261012)
    keys=f.race_key.drop_duplicates().sample(80,random_state=42)
    mask=f.race_key.isin(keys);sub=f[mask].copy().reset_index(drop=True)
    six=slots[mask]
    for c in sub:
        if c.startswith('aux_') or c in ['outcome','front_label']: sub[c]=-9999
    pd.testing.assert_frame_equal(e.early_features(sub,h,six),f.loc[mask,e.EARLY].reset_index(drop=True))
    pd.testing.assert_frame_equal(e.keep_features(h,six),f.loc[mask,e.KEEP].reset_index(drop=True))
    pd.testing.assert_frame_equal(e.interactions(sub),f.loc[mask,e.INTER].reset_index(drop=True))
    for j in rng.choice(len(f),250,replace=False):
        own=f.iloc[j];prior=h.iloc[slots[j][slots[j]>=0]]
        # Independently reconstruct actual five starts, not five valid sections.
        allprior=h[(h.horse_id==own.horse_id)&(h.race_date<=own.cutoff_date)].sort_values('race_date',ascending=False).head(5)
        allprior=allprior[(own.race_date-allprior.race_date).dt.days<=730]
        np.testing.assert_array_equal(prior.index.to_numpy(),allprior.index.to_numpy())
        for kind in ['front','fast','outerfast']:
            v=prior['event_'+kind+'_g3'].dropna();n=len(v)
            assert n==own['keep_'+kind+'_n']
            for part in ['g3','g1']:
                q=prior['event_'+kind+'_'+part].dropna()
                expected=q.mean()*n/(n+3) if n else np.nan
                np.testing.assert_allclose(own['keep_'+kind+'_'+part],expected,equal_nan=True,atol=1e-12)
            if kind!='outerfast':
                v=prior['event_'+kind+'_keep'].dropna()
                expected=(v.sum()+1)/(n+2) if n else np.nan
                np.testing.assert_allclose(own['keep_'+kind+'_keep'],expected,equal_nan=True,atol=1e-12)
        peers=f[(f.race_key==own.race_key)&(f.program_no<own.program_no)]
        v=peers.inner_early_mean3.dropna()
        assert len(peers)==own.inner_inner_n and len(v)==own.inner_inner_early_n
        expected=v.min()-own.inner_early_mean3 if len(v) and pd.notna(own.inner_early_mean3) else np.nan
        np.testing.assert_allclose(own.inner_inner_fastest_gap,expected,equal_nan=True,atol=1e-12)
    # Reconstruct source events directly from the complete section observation table.
    obs=pd.read_parquet(e.S.P/'observations.parquet')
    obs['race_key']=obs.source_key.str.replace('서울:','1:',regex=False).str.replace('부산:','3:',regex=False)
    obs['program_no']=obs.gate
    cor=pd.read_parquet(e.OLD/'outputs/section_corrections.parquet')
    obs=obs.merge(cor.drop(columns='year'),on='row_key',how='left',validate='one_to_one')
    candidates=h[h.event_valid==1].sample(180,random_state=20261012)
    for _,r in candidates.iterrows():
        g=obs[obs.race_key==r.race_key]
        own=g[(g.horse_id==r.horse_id)&(g.program_no==r.program_no)].iloc[0]
        valid=True
        adv={}
        for part in e.S.PARTS:
            times=g[part+'_adjusted'].where(g[part+'_adjusted'].notna(),g[part]).where(g.normal_outcome)
            peers=times.drop(index=own.name).dropna()
            valid &= len(peers)>=5 and times.notna().sum()/own.field_size>=.8 and pd.notna(times.loc[own.name])
            expected=round(peers.mean()-times.loc[own.name],10)
            np.testing.assert_allclose(r[part+'_peer_adv'],expected,atol=1e-9)
            adv[part]=expected
        assert valid
        front=own.group_observed and not own.leader_conflict_race and own.role4==0
        fast=adv['early']>0
        frac=(g.gate<own.gate).sum()/(len(g)-1)
        for kind,eligible in [('front',front),('fast',fast),('outerfast',fast and frac>=2/3)]:
            assert pd.notna(r['event_'+kind+'_g3'])==eligible
            if kind!='outerfast' and eligible:
                assert r['event_'+kind+'_keep']==float(adv['last600']>=0 and adv['late']>=0)
    aux=0;maximum=0.
    for folder in sorted((e.OUT/'front_models').iterdir()):
        m=json.loads((folder/'metadata.json').read_text());year=m['year']
        assert m['train_end']<f'{year}-01-01' and m['model_sha256']==e.sha(folder/'model.txt')
        train=f.year.between(2017,year-1)&f.front_label.notna();x,vocab=e.S.encode(f,m['features'],train)
        assert vocab==m['category_vocabulary']
        model=lgb.Booster(model_file=str(folder/'model.txt'));test=f.year==year
        pred=model.predict(x[test],num_threads=4)
        np.testing.assert_allclose(pred,f.loc[test,'front_probability'],atol=1e-12,rtol=0)
        aux+=1
    diag=pd.read_csv(e.OUT/'race_diagnostics.csv').set_index(['variant','race_key'])
    models=0;metric_checks=0
    for folder in sorted((e.OUT/'models').iterdir()):
        m=json.loads((folder/'metadata.json').read_text());pred=pd.read_parquet(folder/'runners.parquet')
        assert m['train_end']<f"{m['calibration_year']}-01-01"
        assert m['model_sha256']==e.sha(folder/'model.txt')
        one=f[f.meet==pred.meet.iloc[0]].reset_index(drop=True)
        train=one.year.between(2017,m['evaluation_year']-3)
        x,vocab=e.S.encode(one,m['features'],train);assert vocab==m['category_vocabulary']
        test=one.year==m['evaluation_year'];model=lgb.Booster(model_file=str(folder/'model.txt'))
        score=model.predict(x[test],raw_score=True,num_threads=4)
        q=one[test][e.S.KEY].copy();q['score']=score
        joined=q.merge(pred,on=e.S.KEY,validate='one_to_one');err=np.max(np.abs(joined.score-joined.raw_score));maximum=max(maximum,float(err));assert err<=1e-12
        for rid,g in joined.groupby('race_key'):
            row=diag.loc[(m['variant'],rid)]
            ordered=g.sort_values(['raw_score','program_no'],ascending=[False,True]);outcomes=ordered.outcome.to_numpy()
            top2=set(np.flatnonzero((outcomes>=1)&(outcomes<=2)))
            assert row.axis_top2==int(0 in top2)
            assert row.axis_top3==int(1<=outcomes[0]<=3)
            assert row.quinella_one==int(top2=={0,1})
            assert row.axis_next3==int(0 in top2 and top2<=set(range(4)))
            positions=np.flatnonzero((outcomes>=1)&(outcomes<=3))+1
            for k in [3,5,6]: assert row[f'top{k}_all']==int((positions<=k).all())
            card=g.sort_values('program_no')
            triples=np.array(list(itertools.combinations(range(len(card)),3)))
            score3=card.raw_score.to_numpy()[triples].sum(axis=1)
            selected=np.argsort(-score3,kind='stable')[:6]
            truth=tuple(np.flatnonzero(card.outcome.between(1,3)))
            assert row.trio6==int(any(tuple(triples[j])==truth for j in selected))
            sets=np.array(list(itertools.combinations(range(len(g)),m['target'])))
            energy=g.raw_score.to_numpy()[sets].sum(axis=1)/m['temperature']
            p=np.exp(energy-logsumexp(energy));marginal=np.zeros(len(g))
            for combination,prob in zip(sets,p): marginal[combination]+=prob
            np.testing.assert_allclose(marginal,g.target_probability,atol=1e-12,rtol=0)
            y=g.outcome.between(1,m['target']).to_numpy(float)
            np.testing.assert_allclose(row.target_brier,np.mean((marginal-y)**2),atol=1e-12)
            assert abs(marginal.sum()-m['target'])<1e-10
            metric_checks+=1
        models+=1
    p=pd.read_parquet(e.OUT/'runner_predictions.parquet')
    for variant,g in p.groupby('variant'):
        assert len(g)==50754 and g.race_key.nunique()==4799
    old=pd.read_parquet(e.OLD/'outputs/runner_predictions.parquet')
    old=old[(old.variant=='baseline22')&(old.target==3)].reset_index(drop=True)
    new=p[p.variant=='baseline22'].reset_index(drop=True)
    pd.testing.assert_frame_equal(old,new)
    assert aux==7 and models==24
    e.check()
    e.save(e.OUT/'verification.json',dict(passed=True,front_models_replayed=aux,ability_models_replayed=models,
         max_score_error=maximum,model_race_metrics_checked=metric_checks,history_rows_checked=250,
         historical_events_independently_checked=180,whole_fields_poisoned=80,baseline22_unchanged=True,
         same_4799_races=True,production_and_future_contract_hashes_unchanged=True))
    print('Verified',models,'ability models',aux,'front models',metric_checks,'model/race metrics')


if __name__=='__main__':
    main()
