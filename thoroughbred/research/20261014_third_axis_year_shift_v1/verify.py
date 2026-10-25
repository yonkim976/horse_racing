"""Independently verify frozen year-shift diagnostic evidence."""
import ast
import json

import numpy as np
import pandas as pd
from scipy.special import softmax
from threadpoolctl import threadpool_limits

import run as e


def main():
    e.check()
    for p in e.HERE.glob('*.py'):
        ast.parse(p.read_text(), filename=str(p))
    d = pd.read_parquet(e.OUT / 'cases.parquet')
    source = pd.read_parquet(e.P / 'selection_diagnostics.parquet')
    source = source[source.variant.eq('gain_logit_all') & source.year.isin([2025, 2026])]
    third = source[source.is_third].set_index('race_key')
    assert len(d) == 462 and not d.duplicated('race_key').any()
    assert d[d.year.eq(2025)].shape[0] == 286 and d[d.year.eq(2026)].shape[0] == 176
    np.testing.assert_array_equal(d.axis_horse_id, third.loc[d.race_key].axis_horse_id)
    truth = pd.read_parquet(e.E.PRIOR / 'outputs/base_predictions.parquet')
    base = truth[truth.variant.eq('combined122')].set_index(['race_key', 'horse_id'])
    prior = base.loc[pd.MultiIndex.from_arrays([d.race_key, d.prior_selected_horse_id])]
    new = base.loc[pd.MultiIndex.from_arrays([d.race_key, d.axis_horse_id])]
    np.testing.assert_array_equal(prior.outcome, d.prior_outcome)
    np.testing.assert_array_equal(new.outcome, d.axis_outcome)
    expected_group = np.select([new.outcome.between(1,3).to_numpy() & ~prior.outcome.between(1,3).to_numpy(),
                               ~new.outcome.between(1,3).to_numpy() & prior.outcome.between(1,3).to_numpy()],
                               ['gain', 'loss'], default='neutral')
    np.testing.assert_array_equal(expected_group, d.group)
    expected = {2025: {'gain': 87, 'loss': 72, 'neutral':127}, 2026: {'gain':39,'loss':48,'neutral':89}}
    for year, values in expected.items():
        assert d[d.year.eq(year)].group.value_counts().to_dict() == values
    f = e.E.load_features().merge(pd.read_parquet(e.E.FEATURES,columns=e.KEY+e.EXTRA),on=e.KEY,validate='one_to_one').set_index(e.KEY)
    for side, index in [('third',pd.MultiIndex.from_frame(d[e.KEY])),
                        ('prior',pd.MultiIndex.from_arrays([d.race_key,d.prior_program_no,d.prior_selected_horse_id]))]:
        a = f.loc[index]
        for col in e.E.HORSE+e.EXTRA:
            np.testing.assert_allclose(d[side+'_'+col],a[col],atol=1e-12,rtol=0,equal_nan=True)
        np.testing.assert_allclose(d[side+'_distance_change'],d.distance_m-d[side+'_section_previous_distance'],atol=1e-12,rtol=0,equal_nan=True)
    for col in e.E.HORSE+e.EXTRA+['distance_change']:
        np.testing.assert_allclose(d['difference_'+col],d['third_'+col]-d['prior_'+col],atol=1e-12,rtol=0,equal_nan=True)
    assert d.third_horse_name.notna().all() and d.prior_horse_name.notna().all()
    names=pd.read_parquet(e.OBS,columns=['source_key','gate','horse_id','horse_name'])
    names['race_key']=names.source_key.str.replace('서울:','1:',regex=False).str.replace('부산:','3:',regex=False)
    names['program_no']=names.gate
    names=names.set_index(e.KEY)
    np.testing.assert_array_equal(d.third_horse_name,names.loc[pd.MultiIndex.from_frame(d[e.KEY])].horse_name)
    summaries=pd.read_csv(e.OUT/'period_decomposition.csv')
    for period,g in e.periods(source):
        for scope,a in [('all_races',g),('third',g[g.is_third]),('other',g[~g.is_third])]:
            row=summaries[summaries.period.eq(period)&summaries.scope.eq(scope)].iloc[0]
            assert row.n==len(a) and row.gains==a.gain_vs_prior.sum() and row.losses==a.loss_vs_prior.sum()
            assert row.net==int(a.gain_vs_prior.sum()-a.loss_vs_prior.sum())
    features=pd.read_csv(e.OUT/'feature_comparisons.csv')
    for period,a in e.periods(d):
        for group,g in [('all',a)]+list(a.groupby('group')):
            rows=features[features.period.eq(period)&features.group.eq(group)].set_index('feature')
            for col in e.E.HORSE+e.EXTRA+['distance_change']:
                row=rows.loc[col]
                for side in ['third','prior','difference']:
                    x=g[side+'_'+col].dropna()
                    prefix='paired' if side=='difference' else side
                    assert row[prefix+'_n']==len(x)
                    if len(x):
                        np.testing.assert_allclose([row[side+'_mean'],row[side+'_median']],[x.mean(),x.median()],atol=1e-12,rtol=0)
    conditions=pd.read_csv(e.OUT/'conditions.csv',dtype={'value':str})
    for row in conditions.itertuples():
        g=dict(e.periods(d))[row.period]
        g=g[g[row.condition].astype(str).eq(row.value)]
        assert row.n==len(g) and row.gains==g.gain_vs_prior.sum() and row.losses==g.loss_vs_prior.sum()
    cells=pd.read_csv(e.OUT/'composition_cells.csv')
    decomposition=pd.read_csv(e.OUT/'composition_decomposition.csv')
    for row in decomposition.itertuples():
        c=cells[cells.strata.eq(row.strata)]
        p25,p26=c.n25/c.n25.sum(),c.n26/c.n26.sum()
        composition=((p26-p25)*(c.rate26+c.rate25)/2).sum()
        within=((c.rate26-c.rate25)*(p26+p25)/2).sum()
        np.testing.assert_allclose([row.composition,row.within,row.change],[composition,within,composition+within],atol=1e-12,rtol=0)
        assert row.included25==c.n25.sum() and row.included26==c.n26.sum()
        common=d[d.race_date.dt.strftime('%m-%d').le('09-20')]
        assert row.included25+row.excluded25==common.year.eq(2025).sum()
        assert row.included26+row.excluded26==common.year.eq(2026).sum()
    # Exact frozen probabilities and log-ratio contribution sums.
    frame=pd.read_parquet(e.P/'candidate_frame.parquet')
    stored=pd.read_parquet(e.P/'candidate_predictions.parquet')
    long=pd.read_parquet(e.OUT/'feature_contributions.parquet')
    bundles=pd.read_csv(e.OUT/'bundle_contributions.csv')
    decision=pd.read_csv(e.OUT/'decision_scores.csv').set_index('race_key')
    refs=json.loads((e.OUT/'decomposition_contract.json').read_text())['references']
    max_error=0.0
    for year in [2025,2026]:
        g=d[d.year.eq(year)]
        inputs=frame.set_index(e.KEY).loc[pd.MultiIndex.from_frame(g[e.KEY])].reset_index()
        folder=e.P/'models'/f'gain_logit_{year}'
        pre=json.loads((folder/'preprocess.json').read_text());w=json.loads((folder/'model.json').read_text())
        x,names=e.E.S.transform(inputs,pre)
        train=frame[frame.year.between(2020,year-1)];tx,_=e.E.S.transform(train,pre)
        assert pd.Timestamp(pre['training_max'])<pd.Timestamp(year=year,month=1,day=1)
        center=np.average(tx,axis=0,weights=train.case_weight)
        beta=np.array(w['coef'])[2]-np.array(w['coef'])[0]
        baseline=float(center@beta+np.array(w['intercept'])[2]-np.array(w['intercept'])[0])
        contribution=(x-center)*beta
        prob=softmax(x@np.array(w['coef']).T+np.array(w['intercept']),axis=1)
        original=stored[stored.model_kind.eq('gain_logit')].set_index(e.KEY).loc[pd.MultiIndex.from_frame(g[e.KEY])]
        error=float(np.abs(prob-original[['p_loss','p_neutral','p_gain']].to_numpy()).max());max_error=max(max_error,error)
        assert error<1e-12
        reference=next(v for v in refs if v['year']==year)
        assert np.isclose(reference['reference_log_odds'],baseline)
        for i,row in enumerate(g.itertuples()):
            q=long[long.race_key.eq(row.race_key)].set_index('feature').loc[names]
            np.testing.assert_allclose(q.contribution,contribution[i],atol=1e-12,rtol=0)
            np.testing.assert_allclose(q.encoded,x[i],atol=1e-12,rtol=0)
            np.testing.assert_allclose(baseline+q.contribution.sum(),np.log(prob[i,2]/prob[i,0]),atol=1e-10,rtol=0)
            expected=q.groupby('bundle').contribution.sum().sort_index()
            actual=bundles[bundles.race_key.eq(row.race_key)].set_index('bundle').contribution.sort_index()
            np.testing.assert_allclose(expected,actual,atol=1e-12,rtol=0)
            z=decision.loc[row.race_key]
            assert np.isclose(z.selected_gain,prob[i,2]-prob[i,0])
            assert z.selected_gain>=z.two_gain-1e-12 and z.selected_gain>=z.best_other_gain-1e-12
    assert len(long)==462*127
    # Frozen 2025 model may be used for 2026, never vice versa.
    test=frame[frame.year.eq(2026)].drop(columns=['candidate_outcome','ref_outcome','switch_outcome'])
    q=pd.read_parquet(e.OUT/'frozen2025_on2026_predictions.parquet')
    prob=e.E.predict(test,e.P/'models/gain_logit_2025','gain_logit')
    np.testing.assert_allclose(prob,q[['p_loss','p_neutral','p_gain']],atol=1e-12,rtol=0)
    cleantruth=truth[truth.year.eq(2026)].drop(columns='outcome')
    chosen=e.E.choose(q,cleantruth,'all')
    pd.testing.assert_frame_equal(chosen,pd.read_parquet(e.OUT/'frozen2025_on2026_axes.parquet'))
    mutated=truth[truth.year.eq(2026)].copy();mutated['outcome']=np.random.default_rng(54).permutation(mutated.outcome)
    pd.testing.assert_frame_equal(chosen,e.E.choose(q,mutated.drop(columns='outcome'),'all'))
    result=pd.read_csv(e.OUT/'frozen2025_on2026_race_metrics.csv').set_index('race_key')
    base2026=truth[truth.variant.eq('combined122')&truth.year.eq(2026)]
    groups={rid:g.sort_values('raw_score',ascending=False)for rid,g in base2026.groupby('race_key')}
    for row in chosen.itertuples():
        g=groups[row.race_key]
        seq=[row.horse_id]+[h for h in g.horse_id if h!=row.horse_id]
        outcomes=g.set_index('horse_id').outcome;axis=int(outcomes.loc[row.horse_id])
        winning=set(g.loc[g.outcome.between(1,2),'horse_id'])
        expected=[int(1<=axis<=3),int(1<=axis<=2),int(winning==set(seq[:2])),int(any(winning=={row.horse_id,h}for h in seq[1:4]))]
        np.testing.assert_array_equal(expected,result.loc[row.race_key,['axis_top3','axis_top2','quinella_one','axis_next3']].to_numpy(int))
    report=pd.read_csv(e.OUT/'model_update_sensitivity.csv').set_index('variant')
    for metric in ['axis_top3','axis_top2','quinella_one','axis_next3']:
        assert np.isclose(report.loc['frozen2025_on2026',metric],result[metric].mean())
    e.save(e.OUT/'verification.json',dict(status='verified',third_cases=462,year2026_cases=176,
        year2026_gain=39,year2026_loss=48,year2025_gain=87,year2025_loss=72,
        feature_contributions=len(long),attribution_max_probability_error=max_error,
        gain_loss_label_rebuilt=True,source_features_and_names_verified=True,period_split_verified=True,
        composition_identities_verified=True,probabilities_and_contribution_sums_verified=True,
        expected_gain_argmax_checked=True,frozen2025_on2026_independent_race_checks=1288,
        old_model_temporally_valid=True,outcome_permutation_invariant=True,
        source_hashes=len(json.loads((e.OUT/'input_manifest.json').read_text())),new_models=0,
        production_changed=False,selected22_changed=False,future_contract_changed=False,
        database_access=False,network_access=False,jeju_access=False))
    e.check();print((e.OUT/'verification.json').read_text())


if __name__=='__main__':
    with threadpool_limits(limits=1):
        main()
