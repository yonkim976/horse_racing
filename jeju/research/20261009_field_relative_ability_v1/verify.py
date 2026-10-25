"""Independent opponent arithmetic, prior baseline replay and probability checks."""
import argparse
import itertools
import json
import statistics
from datetime import date,timedelta

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.special import logsumexp
import run as e

H=e.HERE;O=e.OUT


def assert_close(a,b):
    assert np.allclose(np.asarray(a,float),np.asarray(b,float),rtol=0,atol=1e-10,equal_nan=True),(a,b)


def synthetic():
    def make(values):return pd.DataFrame(dict(race_id=['r']*len(values),api_record_id=list(range(len(values))),mean5_s=values))
    q=e.relative(make([80.,82.,np.nan]))
    assert_close(q.opp_mean5_valid_n,[1,1,2]);assert_close(q.opp_mean5_median_s,[82,80,81])
    assert_close(q.mean5_minus_opp_mean_s,[-2,2,np.nan]);assert_close(q.opp_mean5_faster_n,[0,1,np.nan])
    assert_close(q.mean5_rank_fraction,[0,1,np.nan]);assert q.mean5_minus_opp_fast2mean_s.isna().all()
    tied=e.relative(make([80.,80.,82.]));assert_close(tied.mean5_rank_fraction,[.25,.25,1])
    assert_close(tied.mean5_minus_opp_fast2mean_s,[-1,-1,2])
    changed=e.relative(make([70.,80.,82.]));assert changed.opp_mean5_median_s.iloc[0]==tied.opp_mean5_median_s.iloc[0]
    assert changed.opp_mean5_median_s.iloc[1]!=tied.opp_mean5_median_s.iloc[1]
    unknown=e.relative(make([np.nan,np.nan,np.nan]));assert unknown.opp_mean5_valid_n.eq(0).all()
    assert unknown.opp_mean5_valid_fraction.eq(0).all();assert unknown.mean5_rank_fraction.isna().all()
    original=make([80.,80.,82.]);permuted=e.relative(original.iloc[[2,0,1]].reset_index(drop=True)).sort_values('api_record_id')
    assert_close(tied[e.EXTRA],permuted[e.EXTRA])
    # Altering current outcomes, identifiers used only for tie ordering, and weights
    # cannot create new relative inputs from postrace observations.
    modified=original.assign(finish_position=[99,1,2],horse_number=[99,88,77],finish_time_seconds=[1,2,3],carried_weight_kg=[100,200,300])
    assert_close(tied[e.EXTRA],e.relative(modified)[e.EXTRA])
    return ['self_exclusion','unknown_self_keeps_differences_NULL','no_opponent_keeps_rank_NULL',
            'ties_have_half_credit','two_fastest_requires_two_observed','row_order_invariance',
            'opponent_change_affects_others','own_change_not_in_own_opponent_level','current_postrace_mutation_invariant']


def preflight():
    e.check();f=pd.read_parquet(O/'features.parquet');base=pd.read_parquet(e.PRE/'outputs_v2/features.parquet')
    pd.testing.assert_frame_equal(f[base.columns],base)
    checked=0
    for _,g in f.groupby('race_id',sort=False):
        rows=g.to_dict('records')
        for r in rows:
            other=[x for x in rows if x['api_record_id']!=r['api_record_id']]
            known=[float(x['mean5_s']) for x in other if np.isfinite(x['mean5_s'])]
            n=len(known);x=r['mean5_s'];has=np.isfinite(x) and n>0
            median=statistics.median(known) if n else np.nan
            expected=[n,n/(len(rows)-1),median,x-statistics.mean(known) if has else np.nan,
                      x-median if has else np.nan,x-statistics.mean(sorted(known)[:2]) if has and n>=2 else np.nan,
                      sum(y<x for y in known) if has else np.nan,
                      (sum(y<x for y in known)+.5*sum(y==x for y in known))/n if has else np.nan]
            assert_close([r[c] for c in e.EXTRA],expected)
            assert r['opponent_source_row_ids'].tolist()==[int(x['api_record_id']) for x in other]
            assert all(x['horse_id']!=r['horse_id'] and x['history_cutoff']==r['history_cutoff'] for x in other)
            assert all(x['distance_m']==r['distance_m'] for x in other)
            checked+=1
    cutoff=f.race_date.map(lambda t:(date.fromisoformat(t)-timedelta(days=2)).isoformat())
    assert f.history_cutoff.equals(cutoff.rename('history_cutoff'))
    assert (f.latest_history_date.isna()|f.latest_history_date.le(cutoff)).all()
    source=pd.read_parquet(e.PRE/'outputs_v2/source_snapshot.parquet').set_index('api_record_id')
    lineage=f[['api_record_id','history_cutoff','last6_same_source_ids']].explode('last6_same_source_ids').dropna(subset=['last6_same_source_ids'])
    dates=lineage.last6_same_source_ids.map(source.race_date)
    assert dates.notna().all() and dates.le(lineage.history_cutoff).all()
    forbidden=json.loads((e.ROOT/'jeju/data/horse_exclusions.json').read_text())['horses']
    assert not set(f.horse_id)&{h for h,v in forbidden.items() if not v['reimport_allowed']}
    cases=synthetic()
    e.save(O/'preflight_verification.json',dict(passed=True,all_relative_rows_independently_calculated=checked,
       base_columns_unchanged=True,historical_lineage_points_checked=len(lineage),synthetic_checks=cases,
       code_sha256=e.sha(H/'verify.py')))
    print('Preflight passed',checked,'relative rows and',len(lineage),'historical points',flush=True)


def final():
    lock=e.check();f=pd.read_parquet(O/'features.parquet');p=pd.read_parquet(O/'runner_predictions.parquet')
    r=pd.read_csv(O/'race_metrics.csv');t=pd.read_csv(O/'six_combinations.csv')
    race_lookup={(v,rid):g.iloc[0] for (v,rid),g in r.groupby(['variant','race_id'],sort=False)}
    tickets={(v,rid):g for (v,rid),g in t.groupby(['variant','race_id'],sort=False)}
    count=0
    for y in [2024,2025,2026]:
        one=f[f.year.eq(y)].reset_index(drop=True);cal=f[f.year.eq(y-1)].reset_index(drop=True)
        for v,cols in e.CONTRACTS.items():
            folder=O/f'{v}_{y}';meta=json.loads((folder/'meta.json').read_text())
            assert meta['refit_max']<meta['calibration_min']<=meta['calibration_max']<meta['evaluation_min']
            assert e.sha(folder/'top3.txt')==meta['model_sha256']
            model=lgb.Booster(model_file=str(folder/'top3.txt'))
            def xform(data):
                x=data[cols].copy()
                for c in e.old.CATS:x[c]=pd.Categorical(x[c],categories=meta['vocabulary'][c])
                return x
            z=model.predict(xform(one),raw_score=True,num_threads=4);cz=model.predict(xform(cal),raw_score=True,num_threads=4)
            saved=p[p.year.eq(y)&p.variant.eq(v)]
            assert np.array_equal(saved.api_record_id,one.api_record_id);assert_close(z,saved.score)
            savedcal=pd.read_parquet(folder/'calibration_scores.parquet')
            assert np.array_equal(savedcal.api_record_id,cal.api_record_id);assert_close(cz,savedcal.score)
            assert np.isclose(e.old.temperature(cal,cz),meta['tau'],rtol=0,atol=1e-10)
            count+=1
    for (v,rid),g in p.groupby(['variant','race_id'],sort=False):
        n=len(g);trips=np.array(list(itertools.combinations(range(n),3)))
        z=g.score.to_numpy();terms=np.sort(z[trips],axis=1);energy=(terms[:,0]+terms[:,1])+terms[:,2]
        meta=json.loads((O/f'{v}_{int(g.year.iloc[0])}'/'meta.json').read_text());tau=meta['tau']
        logq=energy/tau-logsumexp(energy/tau);q=np.exp(logq)
        marginal=np.zeros(n)
        for j,c in enumerate(trips):marginal[c]+=q[j]
        assert_close(marginal,g.p_top3);assert abs(marginal.sum()-3)<1e-10 and abs(q.sum()-1)<1e-12
        y=g.y.to_numpy();clip=np.clip(marginal,1e-12,1-1e-12)
        ll=-y*np.log(clip)-(1-y)*np.log1p(-clip);brier=(marginal-y)**2
        assert_close(ll,g.log_loss);assert_close(brier,g.brier)
        rr=race_lookup[(v,rid)];tt=tickets[(v,rid)]
        assert_close([ll.mean(),brier.mean()],[rr.log_loss,rr.brier])
        truth=np.flatnonzero(y);target=np.flatnonzero((trips==truth).all(axis=1)).item()
        best=np.argsort(-energy,kind='stable')[:6];order=np.argsort(-z,kind='stable')
        assert len(tt)==6 and tt.numbers.nunique()==6
        assert tt.numbers.tolist()==[','.join(map(str,g.horse_number.iloc[trips[j]].astype(int))) for j in best]
        assert_close(tt.probability,q[best]);assert int(target in best)==int(tt.hit.sum())==int(rr.six_combo_hit)
        assert_close(-logq[target],rr.trio_nll)
        for k in [3,4,5,6]:
            assert_close(len(set(truth)&set(order[:k]))/3,rr[f'top{k}_capture'])
            assert int(set(truth)<=set(order[:k]))==rr[f'top{k}_all3']
    previous=pd.read_parquet(e.PRE/'outputs_v2/runner_predictions.parquet');previous=previous[previous.variant.eq('J0')]
    current=p[p.variant.eq('J0')]
    assert np.array_equal(previous.api_record_id,current.api_record_id)
    assert_close(previous[['score','p_top3','log_loss','brier']],current[['score','p_top3','log_loss','brier']])
    oldr=pd.read_csv(e.PRE/'outputs_v2/race_metrics.csv');oldr=oldr[oldr.variant.eq('J0')]
    newr=r[r.variant.eq('J0')];assert np.array_equal(oldr.race_id,newr.race_id)
    assert_close(oldr[e.old.METRICS],newr[e.old.METRICS])
    differences=pd.read_csv(O/'paired_differences.csv')
    for row in differences[differences.group.isin(['all','year'])].itertuples():
        g=r if row.group=='all' else r[r.year.eq(int(row.value))]
        calc=e.old.bootstrap(g[g.variant.eq('R1')],g[g.variant.eq('J0')],row.metric)
        assert_close([row.delta,row.lo,row.hi],[calc['delta'],calc['lo'],calc['hi']])
    # Recalculate runner-level subgroup differences and displayed metric means.
    rdiff=pd.read_csv(O/'runner_paired_differences.csv')
    for row in rdiff.itertuples():
        if row.group=='all':g=p
        else:
            bins=pd.cut(p[row.group],[-1,0,4,np.inf],labels=['0','1_4','5_plus']);g=p[bins.eq(row.value)]
        calc=e.runner_ci(g[g.variant.eq('R1')],g[g.variant.eq('J0')],row.metric)
        assert_close([row.delta,row.lo,row.hi],[calc['delta'],calc['lo'],calc['hi']])
    e.old.check_protected(lock['protected'])
    e.save(O/'final_verification.json',dict(passed=True,reloaded_models=count,probability_ticket_metric_races=len(r),
        runner_prediction_rows=len(p),old_J0_all_predictions_and_metrics_reproduced=True,
        main_year_and_runner_subgroup_CIs_recalculated=True,protected_hashes_unchanged=True,
        production_changed=False,code_sha256=e.sha(H/'verify.py')))
    print('Final verification passed',count,'models and',len(r),'variant-races',flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('phase',choices=['preflight','final']);a=p.parse_args()
    (preflight if a.phase=='preflight' else final)()
