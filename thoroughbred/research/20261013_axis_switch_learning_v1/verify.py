"""Audit chronological OOF lineage, learner replay, and independent race metrics."""
import ast
import json

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from threadpoolctl import threadpool_limits

import run as e


def main():
    e.check()
    for path in e.HERE.glob('*.py'):ast.parse(path.read_text(),filename=str(path))
    f=pd.read_parquet(e.P/'features.parquet');p=pd.read_parquet(e.OUT/'base_predictions.parquet')
    d=pd.read_parquet(e.OUT/'pair_frame.parquet');sp=pd.read_parquet(e.OUT/'selector_predictions.parquet')
    rr=pd.read_parquet(e.OUT/'race_metrics.parquet');rk=pd.read_parquet(e.OUT/'selection_rankings.parquet')
    contract=json.loads((e.OUT/'feature_contract.json').read_text());cols=contract['numeric']+contract['categorical']
    assert len(cols)==len(set(cols))==59
    assert not any('outcome'in col or col.startswith('actual_')for col in cols)
    assert len(d)==10770 and len(sp)==4799*2 and len(rr)==4799*4
    assert len(rk)==50754*4 and d[d.year.ge(2024)].switched.sum()==671
    assert not d.duplicated('race_key').any()
    # Rebuild each historical/evaluation anchor directly from frozen base scores.
    for variant,side in [('baseline103','old'),('combined122','new')]:
        a=p[p.variant.eq(variant)].sort_values(['race_key','raw_score','program_no'],ascending=[True,False,True]).groupby('race_key').head(1).set_index('race_key')
        z=d.set_index('race_key').loc[a.index]
        np.testing.assert_array_equal(a.program_no,z[side+'_program_no'])
        np.testing.assert_array_equal(a.horse_id,z[side+'_horse_id'])
        np.testing.assert_array_equal(a.outcome,z[side+'_outcome'])
    label=d.new_outcome.between(1,3).astype(int)-d.old_outcome.between(1,3).astype(int)
    np.testing.assert_array_equal(label,d.switch_outcome)
    assert d.loc[~d.switched,'switch_outcome'].eq(0).all()
    # Independently validate the pair features, with within-field PIT records only.
    f['gate_fraction']=f.dirgate_inner_n/(f.field_size-1)
    f['record_field_adv']=f.moist_last3_record_index_mean-f.groupby('race_key').moist_last3_record_index_mean.transform('mean')
    indexed=f.set_index(e.KEY)
    for side in ['old','new']:
        ix=pd.MultiIndex.from_arrays([d.race_key,d[side+'_program_no'],d[side+'_horse_id']])
        a=indexed.loc[ix]
        for col in e.HORSE:
            np.testing.assert_allclose(d[side+'_'+col],a[col],atol=1e-12,rtol=0,equal_nan=True)
    for col in e.HORSE:
        np.testing.assert_allclose(d['delta_'+col],d['new_'+col]-d['old_'+col],atol=1e-12,rtol=0,equal_nan=True)
    for section in ['g3','g1']:
        for context in ['support','recent']:
            name=section+'_x_'+context
            for side in ['old','new']:
                multiplier=d[side+'_keep_fast_n']/5 if context=='support'else d[side+'_record_field_adv']
                np.testing.assert_allclose(d[side+'_'+name],d[side+'_keep_fast_'+section]*multiplier,atol=1e-12,rtol=0,equal_nan=True)
            np.testing.assert_allclose(d['delta_'+name],d['new_'+name]-d['old_'+name],atol=1e-12,rtol=0,equal_nan=True)
    # Current outcomes cannot enter the pair/serving APIs; permutations don't alter features.
    blindf=f.drop(columns='outcome');blindp=p.drop(columns='outcome')
    rebuilt,_=e.build_pairs(blindf,blindp)
    dirty=p.copy();dirty['outcome']=np.random.default_rng(51).permutation(dirty.outcome.to_numpy())
    changed,_=e.build_pairs(blindf,dirty.drop(columns='outcome'))
    pd.testing.assert_frame_equal(rebuilt,changed)
    np.testing.assert_allclose(rebuilt[contract['numeric']],d[contract['numeric']],atol=1e-12,rtol=0,equal_nan=True)
    try:e.build_pairs(blindf,p)
    except AssertionError:pass
    else:raise AssertionError('labels accepted into pair feature API')
    replays=[]
    # Replay all 16 newly trained past models and all 12 frozen evaluation models.
    for variant,stem,parent in [('baseline103','full103',e.B),('combined122','combined122',e.P)]:
        for meet in [1,3]:
            for year in range(2020,2027):
                folder=(e.OUT/'past_models'/f'{variant}_{meet}_{year}'if year<2024 else parent/'models'/f'{stem}_{meet}_{year}')
                meta=json.loads((folder/'metadata.json').read_text());model=lgb.Booster(model_file=str(folder/'model.txt'))
                z=p[p.variant.eq(variant)&p.meet.eq(meet)&p.year.eq(year)]
                ix=pd.MultiIndex.from_frame(z[e.KEY]);a=indexed.loc[ix].reset_index()
                x=a[meta['features']].copy()
                for col,values in meta['category_vocabulary'].items():x[col]=pd.Categorical(x[col],categories=values)
                score=model.predict(x,raw_score=True,num_threads=1)
                err=float(np.abs(score-z.raw_score.to_numpy()).max());assert err<1e-10
                assert meta['features']==e.BASECOLS[variant]
                assert pd.Timestamp(meta['train_end'])<pd.Timestamp(year=year-1,month=1,day=1)
                assert meta['validation_year']==year-2 and meta['calibration_year']==year-1
                assert meta['evaluation_year']==year and meta['training_min']=='2017-01-01'
                assert e.sha(folder/'model.txt')==meta['model_sha256']
                replays.append(dict(kind='ability',variant=variant,meet=meet,year=year,runners=len(z),max_error=err))
    for variant in ['joint_logit','joint_tree']:
        for year in [2024,2025,2026]:
            folder=e.OUT/'selector_models'/f'{variant}_{year}'
            meta=json.loads((folder/'metadata.json').read_text());pre=json.loads((folder/'preprocess.json').read_text())
            train=d[d.switched&d.year.between(2020,year-1)];test=d[d.year.eq(year)]
            assert len(train)==meta['training_rows']==pre['training_rows']
            assert meta['training_years']==[2020,year-1]
            assert pd.Timestamp(pre['training_max'])<pd.Timestamp(year=year,month=1,day=1)
            assert pre==e.fit_preprocess(train,contract)
            assert e.sha(folder/'preprocess.json')==meta['preprocess_sha256']
            assert e.sha(folder/('model.json'if variant=='joint_logit'else'model.txt'))==meta['model_sha256']
            clean=test.drop(columns=['old_outcome','new_outcome','switch_outcome'])
            prob=e.selector_predict(clean,folder,variant)
            stored=sp[sp.variant.eq(variant)&sp.year.eq(year)].set_index('race_key').loc[test.race_key]
            np.testing.assert_allclose(prob,stored[['p_loss','p_neutral','p_gain']],atol=1e-12,rtol=0)
            np.testing.assert_allclose(prob.sum(axis=1),1,atol=1e-12,rtol=0)
            assert (prob>=0).all()and(prob<=1).all()
            choose=~test.switched.to_numpy()|((prob[:,2]-prob[:,0])>=0)
            np.testing.assert_array_equal(choose,stored.choose_new)
            np.testing.assert_array_equal(np.where(choose,test.new_program_no,test.old_program_no),stored.axis_program_no)
            try:e.selector_predict(test,folder,variant)
            except AssertionError:pass
            else:raise AssertionError('labels accepted into learner serving API')
            if variant=='joint_logit':
                w=json.loads((folder/'model.json').read_text());x,names=e.transform(clean,pre)
                native=LogisticRegression(C=.1,solver='lbfgs',max_iter=2000)
                native.classes_=np.array(w['classes']);native.coef_=np.array(w['coef'])
                native.intercept_=np.array(w['intercept']);native.n_features_in_=x.shape[1]
                np.testing.assert_allclose(native.predict_proba(x),prob,atol=1e-12,rtol=0)
                tx,_=e.transform(train,pre);native.fit(tx,train.switch_outcome)
                np.testing.assert_allclose(native.coef_,w['coef'],atol=1e-10,rtol=0)
            replays.append(dict(kind='selector',variant=variant,year=year,prior_cases=len(train),test_races=len(test),max_error=float(np.abs(prob-stored[['p_loss','p_neutral','p_gain']].to_numpy()).max())))
    # Reconstruct every selected axis and two-horse hit independently using stored ranking lists.
    truth=p[p.variant.eq('combined122')&p.year.ge(2024)].set_index(['race_key','program_no']).outcome
    independent=[]
    for (variant,rid),z in rk.groupby(['variant','race_key'],sort=False):
        seq=z.sort_values('selection_rank').program_no.tolist()
        assert len(seq)==len(set(seq))
        outcomes=np.array([truth.loc[(rid,k)]for k in seq]);win={seq[j]for j in np.flatnonzero((outcomes>=1)&(outcomes<=2))}
        independent.append(dict(variant=variant,race_key=rid,axis_program_no=seq[0],axis_top3=int(1<=outcomes[0]<=3),
            axis_top2=int(1<=outcomes[0]<=2),axis_win=int(outcomes[0]==1),
            quinella_one=int(win==set(seq[:2])),axis_next3=int(seq[0]in win and win<=set(seq[:4]))))
    a=pd.DataFrame(independent).set_index(['variant','race_key']).sort_index();b=rr.set_index(['variant','race_key']).sort_index()
    np.testing.assert_array_equal(a,b[a.columns])
    frozen=pd.read_csv(e.P/'race_diagnostics.csv')
    for v,src in [('frozen103','baseline103'),('frozen122','combined122')]:
        a=rr[rr.variant.eq(v)].set_index('race_key')[e.METRICS].sort_index()
        b=frozen[frozen.variant.eq(src)].set_index('race_key')[e.METRICS].sort_index()
        np.testing.assert_array_equal(a,b)
    differences=pd.read_csv(e.OUT/'paired_differences.csv',dtype={'period':str})
    for (v,ref),z in differences.groupby(['variant','reference']):
        a=rr[rr.variant.eq(v)].set_index('race_key');b=rr[rr.variant.eq(ref)].set_index('race_key')
        for period,g in e.windows(a):
            for metric in e.METRICS:
                delta=g[metric]-b.loc[g.index,metric];row=z[z.period.eq(period)&z.metric.eq(metric)].iloc[0]
                assert row.net==delta.sum()and row.gain==delta.eq(1).sum()and row.loss==delta.eq(-1).sum()
                assert np.isclose(row.difference_pp,delta.mean()*100)
    e.save(e.OUT/'model_replay.json',dict(models=replays,total=34,new_past_ability=16,frozen_evaluation_ability=12,new_selector=6))
    e.save(e.OUT/'verification.json',dict(status='verified',past_races=5971,test_races=4799,
        test_runners_per_variant=50754,independent_race_checks=len(independent),raw_features=59,
        past_ability_models=16,frozen_ability_models=12,selector_models=6,
        ability_max_error=max(x['max_error']for x in replays if x['kind']=='ability'),
        selector_max_error=max(x['max_error']for x in replays if x['kind']=='selector'),
        temporal_oof_verified=True,selector_prior_only=True,preprocess_prior_only=True,
        serving_label_rejection=True,outcome_permutation_invariant=True,original_metrics_exact=True,
        source_hashes=len(json.loads((e.OUT/'input_manifest.json').read_text())),
        horse_probability_changed=False,production_changed=False,selected22_changed=False,future_contract_changed=False,
        database_access=False,network_access=False,jeju_access=False))
    e.check();print((e.OUT/'verification.json').read_text())


if __name__=='__main__':
    with threadpool_limits(limits=1):main()
