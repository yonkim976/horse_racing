"""Replay every fitted model and independently reconstruct all test distributions."""
from pathlib import Path
import importlib.util
import itertools
import json

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.special import softmax

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('profile_model_study',HERE/'run.py')
R=importlib.util.module_from_spec(spec);spec.loader.exec_module(R)

def main():
    R.check_inputs()
    f=pd.read_parquet(R.OUT/'features.parquet')
    predictions=pd.read_parquet(R.OUT/'runner_predictions.parquet')
    races=pd.read_csv(R.OUT/'race_metrics.csv',low_memory=False)
    tickets=pd.read_parquet(R.OUT/'recommendations.parquet')
    contract=json.loads((R.OUT/'feature_contract.json').read_text())
    assert {k:len(v) for k,v in contract.items()}=={'raw12':12,'moist12':12,'profile19':19}
    assert set(contract['moist12'])<=set(contract['profile19'])
    assert set(contract['profile19'])-set(contract['moist12'])==set(R.EXTRA)
    assert (f.profile_source_date.isna()|f.profile_source_date.le(f.cutoff_date)).all()
    assert f.loc[f.profile_count3.lt(2)|f.profile_previous3_count.lt(2),'profile_trend'].isna().all()
    assert f.loc[f.moist_last5_record_index_count.lt(3),'profile_std5'].isna().all()
    assert f.loc[f.moist_last5_record_index_count.lt(2),'profile_top2mean5'].isna().all()
    assert not any('jockey' in x or 'gate' in x or 'stack_' in x for cols in contract.values() for x in cols)
    # Exact score multisets must yield exact identical triple energies across positions.
    tie_frame=pd.DataFrame({'race_key':['test']*6,'outcome':[1,2,3,4,5,6]})
    tie_scores=np.array([-.7,-1.48,-1.48,-1.48,-1.48,-1.48])
    energy=R.parts(tie_frame,tie_scores)[0]['energy']
    triples=np.array(list(itertools.combinations(range(6),3)))
    assert len(np.unique(energy[(triples==0).any(axis=1)]))==1
    checks=0;error=0.0;heads=0;all_temperature_checks=[]
    def compare(a,b,label):
        nonlocal checks,error
        a=np.asarray(a,float);b=np.asarray(b,float)
        assert np.allclose(a,b,atol=1e-10,rtol=0,equal_nan=True),label
        known=np.isfinite(a)&np.isfinite(b)
        if known.any():error=max(error,float(np.abs(a[known]-b[known]).max()))
        checks+=a.size
    reference=predictions[predictions.variant.eq('reference258')].sort_values(R.KEY)
    for variant in contract:
        p=predictions[predictions.variant.eq(variant)].sort_values(R.KEY)
        assert p[R.KEY+['outcome']].reset_index(drop=True).equals(reference[R.KEY+['outcome']].reset_index(drop=True))
        assert len(p)==50754
        assert races[races.variant.eq(variant)].race_key.nunique()==4799
        counts=tickets[tickets.variant.eq(variant)].groupby('race_key').size()
        assert counts.eq(6).all() and len(counts)==4799
    # Previously verified evaluation profiles must remain the exact feature source.
    source=pd.read_parquet(R.PROFILE/'profiles.parquet')
    aligned=source[R.KEY].merge(f,on=R.KEY,validate='one_to_one')
    mapping={'profile_top2mean5':'moist_top2mean5','profile_previous3':'moist_previous3','profile_trend':'moist_trend',
             'profile_std5':'moist_std5','profile_count3':'moist_count3','profile_previous3_count':'moist_previous3_count',
             'profile_valid5_support_fraction':'valid5_support_fraction'}
    for column,src in mapping.items():compare(aligned[column],source[src],column)
    for meet in [1,3]:
        one=f[f.meet.eq(meet)].reset_index(drop=True)
        for year in [2024,2025,2026]:
            for variant,cols in contract.items():
                directory=R.OUT/'models'/f'{meet}_{year}_{variant}'
                meta=json.loads((directory/'metadata.json').read_text())
                assert meta['features']==cols and meta['validation_year']==year-2 and meta['calibration_year']==year-1
                assert pd.Timestamp(meta['train_end']).year==year-2
                assert R.sha(directory/'top3.txt')==meta['model_sha256']
                model=lgb.Booster(model_file=str(directory/'top3.txt'))
                assert model.feature_name()==cols and model.num_trees()==meta['trees']
                x=one[cols].copy()
                for col,vocabulary in meta['category_vocabulary'].items():
                    x[col]=pd.Categorical(x[col],categories=vocabulary)
                    train_vocabulary=sorted(one.loc[one.year.between(2017,year-3),col].dropna().unique().tolist())
                    assert vocabulary==train_vocabulary
                cal=one.year.eq(year-1);test=one.year.eq(year)
                score=model.predict(x[test],raw_score=True,num_threads=4)
                test_frame=one[test].reset_index(drop=True)
                saved=predictions[(predictions.variant.eq(variant))&(predictions.meet.eq(meet))&(predictions.evaluation_year.eq(year))]
                ordered=test_frame[R.KEY].merge(saved,on=R.KEY,validate='one_to_one')
                compare(score,ordered.raw_top3_score,variant+'_head_replay')
                # Re-evaluate previous-year calibration objective through analytic derivative.
                cal_score=model.predict(x[cal],raw_score=True,num_threads=4)
                cal_frame=one[cal].reset_index(drop=True)
                gradients=[];t=meta['temperature']
                for _,idx in cal_frame.groupby('race_key',sort=False).indices.items():
                    g=cal_frame.iloc[idx]
                    triplets=np.array(list(itertools.combinations(range(len(g)),3)),int)
                    energy=np.sort(cal_score[idx][triplets],axis=1).sum(axis=1)
                    truth=np.flatnonzero(g.outcome.le(3).to_numpy())
                    actual=float(np.sort(cal_score[idx][truth]).sum())
                    gradients.append((actual-float(softmax(energy/t)@energy))/(t*t))
                gradient=float(np.mean(gradients))
                if .3501<t<3.9999:assert abs(gradient)<1e-5,(variant,t,gradient)
                elif t<=.3501:assert gradient>=-1e-5
                else:assert gradient<=1e-5
                all_temperature_checks.append(dict(meet=meet,year=year,variant=variant,temperature=t,gradient=gradient))
                race_index=races[(races.variant.eq(variant))&(races.meet.eq(meet))&(races.evaluation_year.eq(year))].set_index('race_key')
                ticket_index=tickets[tickets.variant.eq(variant)].set_index(['race_key','selection_rank'])
                assert race_index.index.is_unique and ticket_index.index.is_unique
                for rid,idx in test_frame.groupby('race_key',sort=False).indices.items():
                    g=test_frame.iloc[idx]
                    sets=np.array(list(itertools.combinations(range(len(g)),3)),int)
                    energy=np.sort(score[idx][sets],axis=1).sum(axis=1)/t
                    q=softmax(energy)
                    margins=np.zeros(len(g))
                    for pos in range(len(g)):
                        margins[pos]=q[(sets==pos).any(axis=1)].sum()
                    compare(margins,ordered.iloc[idx].prob_top3,variant+'_podium_margins')
                    compare([margins.sum(),q.sum()],[3,1],variant+'_probability_sums')
                    best=np.argsort(-q,kind='stable')[:6]
                    truth=tuple(np.flatnonzero(g.outcome.le(3).to_numpy()))
                    actual=next(i for i,s in enumerate(sets) if tuple(s)==truth)
                    assert g.program_no.is_monotonic_increasing
                    order=np.argsort(-score[idx],kind='stable')
                    expected=race_index.loc[rid]
                    compare([int(actual in best),-np.log(q[actual]),np.mean((margins-g.outcome.le(3).to_numpy())**2),
                             int(set(truth)<=set(order[:5])),q[best].sum()],
                            [expected.trio6_hit,expected.trio_nll,expected.top3_brier,expected.top5_contains_podium,expected.trio6_probability],variant+'_race_metrics')
                    for rank,j in enumerate(best,1):
                        row=ticket_index.loc[(rid,rank)]
                        program=','.join(map(str,sorted(g.program_no.iloc[sets[j]].astype(int))))
                        assert row.programs==program
                        compare([row.probability,row.hit],[q[j],int(j==actual)],variant+'_ticket')
                heads+=1
                print('Verified',meet,year,variant,flush=True)
    # Verify summary is an exact aggregation, including the unchanged258-feature reference.
    metrics=pd.read_csv(R.OUT/'metrics.csv')
    for row in metrics.to_dict('records'):
        subset=races[races.variant.eq(row['variant'])]
        if row['meet']:subset=subset[subset.meet.eq(row['meet'])]
        if row['period']!='all':subset=subset[subset.evaluation_year.eq(int(row['period']))]
        assert len(subset)==row['races'] and subset.trio6_hit.sum()==row['hits']
        compare([subset.trio6_hit.mean(),subset.trio_nll.mean(),subset.top3_brier.mean(),subset.top5_contains_podium.mean()],
                [row['trio6_hit'],row['trio_nll'],row['top3_brier'],row['top5_contains_podium']],'summary')
    original=pd.read_csv(R.REFERENCE/'race_metrics.csv',low_memory=False)
    original=original[original.variant.eq('no_jockey')]
    ref_race=races[races.variant.eq('reference258')].merge(original,on='race_key',suffixes=('_current','_original'),validate='one_to_one')
    for col in ['trio6_hit','trio_nll','top3_brier','top5_contains_podium']:
        compare(ref_race[col+'_current'],ref_race[col+'_original'],'reference258_'+col)
    R.check_inputs()
    R.save(R.OUT/'verification.json',dict(status='passed',numeric_checks=checks,max_error=error,model_replays=heads,
           calibration_checks=all_temperature_checks,profile_reproduced_rows=50754,cohort_matches_reference=True,
           probability_sums_valid=True,top6_tickets_reproduced=True,input_hashes_unchanged=True,
           excluded_inputs=['jockey','gate','stack_pace','current_moisture','same_day_body_weight'],production_changed=False))
    print(json.dumps(dict(status='passed',models=heads,checks=checks,max_error=error),ensure_ascii=False),flush=True)

if __name__=='__main__':main()
