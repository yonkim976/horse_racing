"""Independent subset enumeration, saved-model replay and race settlement checks."""
import itertools
import json
import math
import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.stats import false_discovery_control
import experiment as a


def enumerate_distribution(p,desired):
    n=len(p)
    masks=np.array(list(itertools.product([0,1],repeat=n)),dtype=int)[1:]
    raw=np.prod(np.where(masks,p,1-p),axis=1)
    category=np.minimum(masks.sum(axis=1)-1,2)
    bins=np.bincount(category,weights=raw,minlength=3)
    pi=bins/bins.sum() if desired is None else desired/desired.sum()
    weights=raw*pi[category]/bins[category]
    marginal=np.column_stack([(masks.T@(weights*(category==b))) for b in range(3)])
    return masks,category,weights,marginal


def main():
    a.check()
    assert json.loads((a.O/'run_summary.json').read_text())['evaluation_races']==1976
    q,x,races,rx=a.prepare()
    aux=pd.read_parquet(a.O/'aux_predictions.parquet')
    counts=pd.read_parquet(a.O/'count_predictions.parquet')
    finish=pd.read_parquet(a.O/'finish_predictions.parquet')
    contract=json.loads((a.O/'feature_contract.json').read_text())
    assert len(x.columns)==167 and len(rx.columns)==45
    assert not any('jockey' in c or 'trainer' in c for c in contract['direct'])
    assert list(x.columns)==contract['auxiliary_horse']
    assert aux.row_key.is_unique and finish.row_id.is_unique
    assert set(finish.year)=={2024,2025,2026}
    source=json.loads((a.O/'input_manifest.json').read_text())
    assert a.sha(a.ROOT/'config/prediction_model_registry.json')==source['config/prediction_model_registry.json']['sha256']

    # Metadata chronology is reconstructed from exact eligible rows, not a claimed year label.
    model_count=0;max_replay=0.
    for year in range(2020,2027):
        tr=q.year.lt(year)&q.group_observed
        rt=races.year.lt(year)&races.group_complete
        te=q.year.eq(year);rv=races.year.eq(year)
        yy=aux[aux.year.eq(year)].set_index('row_key').loc[q.loc[te,'row_key']]
        for kind,mask,dates in [('lead',tr,q.loc[tr,'date']),
                                ('retention',tr,q.loc[tr,'date']),
                                ('count',rt,races.loc[rt,'date'])]:
            name=f'{year}_{kind}'
            meta=json.loads((a.M/(name+'.json')).read_text())
            model=lgb.Booster(model_file=str(a.M/(name+'.txt')))
            assert a.sha(a.M/(name+'.txt'))==meta['model_sha256']
            assert meta['n']==int(mask.sum())
            assert pd.Timestamp(meta['train_end'])==dates.max()<pd.Timestamp(f'{year}-01-01')
            assert meta['features']==model.feature_name()
            model_count+=1
            if kind=='lead':
                replay=model.predict(x.loc[te],num_threads=4)
                expected=yy.raw_lead.to_numpy()
                max_replay=max(max_replay,float(abs(replay-expected).max()))
                np.testing.assert_allclose(replay,expected,atol=1e-12,rtol=0)
            elif kind=='count':
                replay=model.predict(rx.loc[rv],num_threads=4)
                expected=counts.set_index('source_key').loc[rx.index[rv],['p1','p2','p3p']].to_numpy()
                np.testing.assert_allclose(replay,expected,atol=1e-12,rtol=0)
            else:
                sample=x.loc[te].head(31).copy()
                for member in range(2):
                    for cat in range(3):
                        sample['scenario_lead']=member;sample['scenario_count']=cat
                        replay=model.predict(sample,num_threads=4)
                        expected=yy[f'ret_m{member}_n{cat}'].head(31)
                        np.testing.assert_allclose(replay,expected,atol=1e-12,rtol=0)

    enum_checks=0
    rng=np.random.default_rng(a.SEED)
    candidates=aux[aux.year.eq(2026)].groupby('source_key').field_size.first()
    keys=candidates[candidates.between(6,12)].index.to_numpy()
    for key in rng.choice(keys,size=14,replace=False):
        g=aux[aux.source_key.eq(key)]
        p=np.clip(g.raw_lead.to_numpy(),1e-6,1-1e-6)
        cond=np.empty((len(g),2,3))
        for m in range(2):
            for cat in range(3):cond[:,m,cat]=g[f'ret_m{m}_n{cat}']
        for name in ['I','J']:
            desired=None if name=='I' else g[['J_count1','J_count2','J_count3p']].iloc[0].to_numpy(float)
            masks,category,weights,marginal=enumerate_distribution(p,desired)
            saved=g[[name+'_member1',name+'_member2',name+'_member3p']].to_numpy()
            np.testing.assert_allclose(marginal,saved,atol=1e-10,rtol=0)
            expected_count=weights@masks.sum(axis=1)
            np.testing.assert_allclose(expected_count,g[name+'_expected_count'],atol=1e-10,rtol=0)
            mixture=[]
            for i in range(len(g)):
                values=cond[i,masks[:,i],category]
                mixture.append(weights@values)
            np.testing.assert_allclose(mixture,g[name+'_top3_mixture'],atol=1e-10,rtol=0)
            enum_checks+=1
    for name in ['I','J']:
        for key,g in aux.groupby('source_key'):
            pi=g[[name+'_count1',name+'_count2',name+'_count3p']].iloc[0].to_numpy(float)
            np.testing.assert_allclose(pi.sum(),1,atol=1e-12)
            mass=g[[name+'_member1',name+'_member2',name+'_member3p']].to_numpy()
            assert np.all(mass>=-1e-10) and np.all(mass<=pi+1e-10)
            np.testing.assert_allclose(mass.sum(axis=1),g[name+'_front'],atol=1e-10)
            np.testing.assert_allclose(mass[:,0],g[name+'_solo'],atol=1e-10)
            np.testing.assert_allclose(g[name+'_solo'].sum(),pi[0],atol=1e-10)
            np.testing.assert_allclose(g[name+'_front'].sum(),g[name+'_expected_count'],atol=1e-9)
            assert g[name+'_top3_mixture'].between(-1e-10,1+1e-10).all()

    # A future-year label/time mutation must not alter earlier prior-five features.
    raw=pd.read_parquet(a.PACE/'feature_context.parquet')
    original,hh=a.lead_histories(raw)
    mutated=raw.copy();future=mutated.year.eq(2026)
    mutated.loc[future,'raw_finish_rank']=1
    mutated.loc[future,'role4']=0
    mutated.loc[future,['last600_peer_adv','late_peer_adv','last600','late']]=999.
    changed,hh2=a.lead_histories(mutated)
    np.testing.assert_allclose(hh[original.year.lt(2026)],hh2[changed.year.lt(2026)],atol=0,rtol=0,equal_nan=True)
    # Mutating the final source row cannot change its own strictly prior history.
    idx=original.index[-1];own=original.iloc[idx].row_key
    mutated=raw.copy();mask=mutated.row_key.eq(own)
    mutated.loc[mask,['last600_peer_adv','late_peer_adv','last600','late']]=777.
    _,hh3=a.lead_histories(mutated)
    np.testing.assert_allclose(hh.iloc[idx],hh3.iloc[idx],atol=0,rtol=0,equal_nan=True)

    p,b,d,extras=a.main_inputs(q,x,races,rx,aux)
    replay_errors=[]
    for year in a.YEARS:
        tr=p.year.between(2017,year-1)&p.normal_n.ge(6)
        te=p.year.eq(year)&p.normal_n.ge(6)
        for name in ['D','I','J']:
            model_path=a.M/f'{year}_finish_{name}.txt'
            meta=json.loads(model_path.with_suffix('.json').read_text())
            model=lgb.Booster(model_file=str(model_path))
            assert meta['n']==int(tr.sum()) and meta['model_sha256']==a.sha(model_path)
            assert pd.Timestamp(meta['train_end'])==pd.to_datetime(p.loc[tr,'date']).max()<pd.Timestamp(f'{year}-01-01')
            matrix=d if name=='D' else pd.concat([d,extras[name]],axis=1)
            assert model.feature_name()==list(matrix.columns)==meta['features']
            replay=model.predict(matrix.loc[te],num_threads=4)
            expected=finish.set_index('row_id').loc[p.loc[te,'row_id'],'score_'+name].to_numpy()
            replay_errors.append(float(abs(replay-expected).max()))
            np.testing.assert_allclose(replay,expected,atol=1e-12,rtol=0)
            model_count+=1
    assert model_count==30
    assert extras['I'].iloc[p.index[p.year.lt(2020)]].isna().all().all()
    assert extras['J'].iloc[p.index[p.year.lt(2020)]].isna().all().all()
    # Main features may use forecasts, never their contemporary observed labels.
    prohibited={'raw_finish_rank','role4','actual_count','count_class','first_group_size',
                'finish_rank','performance','group_observed'}
    assert not prohibited.intersection(contract['auxiliary_horse'])
    assert not prohibited.intersection(contract['auxiliary_race'])
    assert not prohibited.intersection(contract['direct'])

    # Recompute winning unordered pairs from original ranks, separately from scoring.
    rr=pd.read_csv(a.O/'race_metrics.csv').set_index('source_key')
    rawlookup=p.set_index(['date','race_no','program_no']).finish_rank
    checked=0
    for key,g in finish.groupby('source_key'):
        ranks=dict(zip(g.program_no.astype(int),g.finish_rank.astype(int)))
        first={number for number,rank in ranks.items() if rank==1}
        second={number for number,rank in ranks.items() if rank==2}
        if len(first)>=2:
            winning={frozenset(pair) for pair in itertools.combinations(first,2)}
        else:
            winning={frozenset((i,j)) for i in first for j in second}
        for name in a.MODELS:
            chosen=g.sort_values(['score_'+name,'program_no'],ascending=[False,True]).program_no.astype(int).tolist()
            assert rr.loc[key,name+'_axis_top3']==int(ranks[chosen[0]]<=3)
            assert rr.loc[key,name+'_win']==int(chosen[0] in first)
            assert rr.loc[key,name+'_quinella_one']==int(frozenset(chosen[:2]) in winning)
            assert rr.loc[key,name+'_axis_next3']==int(any(frozenset((chosen[0],v)) in winning for v in chosen[1:4]))
            checked+=1
    summary=pd.read_csv(a.O/'finish_metrics.csv',dtype={'window':str})
    for row in summary.itertuples():
        z=rr if row.window=='all' else rr[rr.year.eq(int(row.window))]
        assert row.races==len(z)
        for metric in ['axis_top3','axis_top2','win','quinella_one','axis_next3','mae']:
            np.testing.assert_allclose(getattr(row,metric),z[row.model+'_'+metric].mean(),atol=1e-12)

    diff=pd.read_csv(a.O/'paired_comparisons.csv',dtype={'window':str})
    for row in diff.itertuples():
        z=rr if row.window=='all' else rr[rr.year.eq(int(row.window))]
        differences=z[row.new+'_'+row.metric]-z[row.old+'_'+row.metric]
        byday=pd.DataFrame(dict(date=z.date,delta=differences)).groupby('date').delta.agg(['sum','size'])
        gen=np.random.default_rng(a.SEED)
        boots=[]
        for _ in range(2000):
            sampled=gen.integers(0,len(byday),size=len(byday))
            boots.append(byday['sum'].to_numpy()[sampled].sum()/byday['size'].to_numpy()[sampled].sum())
        lo,hi=np.quantile(boots,[.025,.975])
        np.testing.assert_allclose([row.difference,row.lower,row.upper],[differences.mean(),lo,hi],atol=1e-12)
    mask=diff.bh_q_primary6.notna()
    assert mask.sum()==6
    np.testing.assert_allclose(false_discovery_control(diff.loc[mask,'p_boot']),diff.loc[mask,'bh_q_primary6'],atol=1e-12)
    references=pd.read_csv(a.O/'early_reference_races.csv')
    history=q.set_index('row_key').lead_prior5
    for key,g in aux[aux.year.ge(2024)&aux.group_observed].groupby('source_key'):
        ref=references.set_index('source_key').loc[key]
        assert len(g)==g.field_size.iloc[0]
        g=g.assign(past=g.row_key.map(history))
        for name,col in [('H','past'),('I','raw_lead'),('J','raw_lead')]:
            selected=g.sort_values([col,'gate'],ascending=[False,True]).iloc[0]
            assert ref[name+'_gate']==selected.gate and ref[name+'_hit']==int(selected.role4==0)
    assert references.I_gate.eq(references.J_gate).all()
    refmetrics=pd.read_csv(a.O/'early_reference_metrics.csv',dtype={'window':str})
    for row in refmetrics.itertuples():
        g=references if row.window=='all' else references[references.year.eq(int(row.window))]
        assert row.races==len(g) and row.hits==g[row.model+'_hit'].sum()
        np.testing.assert_allclose(row.hit_rate,g[row.model+'_hit'].mean(),atol=1e-12)
    early=pd.read_csv(a.O/'aux_metrics.csv')
    for row in early.itertuples():
        ref=refmetrics[refmetrics.window.eq(str(row.year)) & refmetrics.model.eq(row.model)].iloc[0]
        np.testing.assert_allclose(row.top_first_group_hit,ref.hit_rate,atol=1e-12)
    source_races=pd.read_csv(a.R/'20261021_busan_leader_pack_outcomes/outputs/race_outcomes.csv')
    for row in pd.read_csv(a.O/'count_reference_metrics.csv').itertuples():
        tr=source_races[source_races.year.lt(row.year)]
        te=source_races[source_races.year.eq(row.year)]
        observed=[min(int(v)-1,2) for v in tr.leader_count]
        priors=np.array([(observed.count(c)+1)/(len(observed)+3) for c in range(3)])
        assert int(priors.argmax())==row.training_mode_class
        true=[min(int(v)-1,2) for v in te.leader_count]
        accuracy=sum(v==row.training_mode_class for v in true)/len(true)
        brier=sum(sum((priors[c]-(c==v))**2 for c in range(3)) for v in true)/len(true)
        np.testing.assert_allclose([accuracy,brier],[row.accuracy,row.count_brier],atol=1e-12)
    a.check()
    a.save('verification.json',dict(status='verified',protected_input_files=len(source),
        models_replayed=model_count,auxiliary_lead_replay_max_error=max_replay,
        finish_replay_max_error=max(replay_errors),subset_enumeration_cases=enum_checks,
        selected_race_model_checks=checked,bootstrap_contrasts=len(diff),
        direct_features=len(d.columns),stack_features=len(d.columns)+len(a.STACK_COLS),
        current_actual_pace_excluded=True,pre2020_forecasts_missing=True,
        future_mutation_earlier_history_invariant=True,current_mutation_own_history_invariant=True,
        training_chronology_verified=True,jockey_trainer_excluded=True,
        normal_finisher_conditional_evaluation=True,production_registry_unchanged=True,
        history_reference_races_verified=len(references),cardinality_reweighting_order_preserved=True))
    print((a.O/'verification.json').read_text())


if __name__=='__main__':main()
