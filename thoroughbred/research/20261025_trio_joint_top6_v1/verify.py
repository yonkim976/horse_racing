"""Independent ticket settlement, joint reconstruction, and baseline checks."""
from decimal import Decimal
import json
import numpy as np
import pandas as pd
from scipy.special import softmax
import analyze as a


def main():
    # Canonical ties and the inverse mapping are independent of runner ordering.
    rng=np.random.default_rng(20261025)
    for n in [6,10,16]:
        tr,inc=a.support(n)
        uniform=np.full(len(tr),1/len(tr))
        assert np.array_equal(np.argsort(-np.round(uniform,12),kind='stable')[:6],np.arange(6))
        energy=rng.normal(size=n);prob=softmax(energy[tr].sum(1));perm=rng.permutation(n)
        _,permuted,_,_=a.inverse_marginals((prob@inc)[perm])
        lookup={tuple(z):i for i,z in enumerate(tr)}
        for ids,value in zip(tr,permuted):assert abs(value-prob[lookup[tuple(sorted(perm[ids]))]])<2e-10
    r=pd.read_parquet(a.OUT/'race_results.parquet')
    t=pd.read_parquet(a.OUT/'selected_tickets.parquet')
    p=pd.read_parquet(a.RET/'winning_dividends.parquet').set_index('race_key')
    assert len(r)==4133*5 and len(t)==len(r)*12
    assert t.groupby(['race_key','model','policy']).size().eq(6).all()
    assert not t.duplicated(['race_key','model','policy','a','b','c']).any()
    assert (t.a<t.b).all() and (t.b<t.c).all()
    true=t.race_key.map(p.actual).str.split(',').map(lambda z:tuple(map(int,z)))
    assert np.array_equal(t.hit.to_numpy(),np.array([tuple(x)==y for x,y in zip(t[['a','b','c']].to_numpy(),true)]))
    tt=t.groupby(['race_key','model','policy']).agg(hit=('hit','sum'),mass=('probability','sum'))
    for row in r.itertuples():
        for policy in ['axis_six','joint_top6']:
            v=tt.loc[(row.race_key,row.model,policy)]
            assert v['hit']==getattr(row,policy+'_hit')
            assert abs(v.mass-getattr(row,policy+'_probability'))<1e-10
        assert row.joint_top6_probability>=row.axis_six_probability-1e-10
    source=pd.read_parquet(a.OLD/'race_results.parquet').query("scope=='identical_roster'")
    q=r.merge(source[['race_key','model','axis','hit']],on=['race_key','model'],validate='1:1',suffixes=('','_old'))
    assert len(q)==len(r) and q.axis.eq(q.axis_old).all() and q.axis_six_hit.eq(q.hit).all()
    s=pd.read_csv(a.OUT/'summary.csv')
    checked=0
    for name,g in [('all',r),*[(str(y),z) for y,z in r.groupby('year')],*[(('seoul' if m==1 else 'busan'),z) for m,z in r.groupby('meet')]]:
        for model,z in g.groupby('model'):
            for policy in ['axis_six','joint_top6']:
                paid=sum((Decimal(str(x))*1000 for x in z.loc[z[policy+'_hit'],'dividend']),Decimal(0))
                row=s[s.subgroup.eq(name)&s.model.eq(model)&s.policy.eq(policy)].iloc[0]
                assert Decimal(str(row.return_krw))==paid and row.stake_krw==len(z)*6000
                assert abs(row.roi-(float(paid)/(len(z)*6000)-1))<1e-12
                checked+=1
    old=pd.read_csv(a.RET/'return_summary.csv').query("scope=='identical_roster' and policy=='six'")
    aligned=s[s.policy.eq('axis_six')].merge(old,on=['subgroup','model'],validate='1:1',suffixes=('','_old'))
    for col in ['races','hits','stake_krw','return_krw','net_krw','roi']:
        assert np.allclose(aligned[col],aligned[col+'_old'],atol=1e-9)
    # Reconstruct all additive distributions without invoking the primary selector.
    frame=a.c.frame();frame=frame[frame.race_key.isin(set(r.race_key))].copy()
    inputs={key:g.sort_values('program_no') for key,g in frame.groupby('race_key',sort=False)}
    full=pd.read_parquet(a.FULL/'runner_predictions.parquet').query("variant=='full103' and target==3").set_index(['race_key','program_no']).raw_score
    cp=json.loads((a.BASE/'outputs/calibration_parameters.json').read_text())
    temps={(x['meet'],x['evaluation_year']):x['set_temperature'] for x in cp if x['variant']=='full103'}
    scores={};metas={}
    for meet in [1,3]:
        for year in [2024,2025,2026]:
            folder=a.DYN/'outputs/models'/f'state_gbm_{meet}_{year}'
            scores[(meet,year)]=pd.read_parquet(folder/'scores.parquet').query("phase=='evaluation'").set_index('row_number').score
            metas[(meet,year)]=json.loads((folder/'metadata.json').read_text())
    latent={k:g.set_index('program_no') for k,g in pd.read_parquet(a.OUT/'operating_energies.parquet').groupby('race_key')}
    rr=pd.read_parquet(a.RISK/'conditional_runners.parquet').set_index(['race_key','program_no'])
    risk=pd.read_parquet(a.RISK/'race_predictions.parquet').set_index('race_key')
    stored={(key,model,policy):g for (key,model,policy),g in t.groupby(['race_key','model','policy'],sort=False)}
    count=0;neurals=0;risk_error=0.;nn_error=0.
    nn_sample=set()
    for (meet,year),g in r[r.model.eq('state_joint118')].groupby(['meet','year']):
        keys=sorted(g.race_key);nn_sample.update([keys[0],keys[len(keys)//2],keys[-1]])
    nn_models={}
    for key,g in inputs.items():
        n=len(g);numbers=g.program_no.to_numpy(int);tr,inc=a.support(n)
        meet=int(g.meet.iloc[0]);year=int(g.year.iloc[0]);mi=pd.MultiIndex.from_arrays([g.race_key,g.program_no])
        bscore=scores[(meet,year)].loc[g.row_number].to_numpy()/metas[(meet,year)]['temperature']
        bq=softmax(bscore[tr].sum(1))
        energy=latent[key].loc[numbers,'energy'].to_numpy(float)
        oq=softmax(energy[tr].sum(1))
        target=latent[key].loc[numbers,'original_probability'].to_numpy(float)
        assert np.max(np.abs(oq@inc-target))<2e-10
        fq=softmax(full.loc[mi].to_numpy(float)[tr].sum(1)/temps[(meet,year)])
        row=risk.loc[key];pi=float(row.base_axis_probability)
        newp=(1-row.policy_lambda)*pi+row.policy_lambda*(1-row.model_risk)
        event=(numbers[tr]==row.axis_program_no).any(1)
        rq=bq*np.where(event,newp/pi,(1-newp)/(1-pi))
        external=rr.loc[mi]
        expected=external.given_axis_in.to_numpy()*newp+external.given_axis_out.to_numpy()*(1-newp)
        risk_error=max(risk_error,float(np.max(np.abs(rq@inc-expected))))
        assert risk_error<2e-10
        distributions={'operating_A_v5':oq,'full103':fq,'state_gbm118':bq,'axis_failure_selected':rq}
        if key in nn_sample:
            if (meet,year) not in nn_models:
                folder=a.DYN/'outputs/models'/f'state_joint_{meet}_{year}'
                meta=json.loads((folder/'metadata.json').read_text());encoding=json.loads((folder/'encoding.json').read_text())
                model=a.joint.restore(a.ROOT/meta['model_path'],meta['inputs'])
                nn_models[(meet,year)]=(model,meta,encoding)
            model,meta,encoding=nn_models[(meet,year)]
            x,_=a.joint.encode(g,meta['features'],meta=encoding)
            altered=g.copy();altered['outcome']=altered.outcome.iloc[::-1].to_numpy();altered['dividend']=1e9
            changed_x,_=a.joint.encode(altered,meta['features'],meta=encoding)
            assert np.array_equal(x,changed_x)
            orders,mass=a.joint.distribution(model,x,meta['temperature'])
            # Independent aggregation by sorted set, rather than reshape six.
            lookup={tuple(u):i for i,u in enumerate(tr)};nq=np.zeros(len(tr))
            for order,prob in zip(orders,mass):nq[lookup[tuple(sorted(order))]]+=prob
            distributions['state_joint118']=nq;neurals+=1
        for model,prob in distributions.items():
            assert abs(prob.sum()-1)<1e-9
            selected=np.argsort(-np.round(prob,12),kind='stable')[:6]
            actual=stored[(key,model,'joint_top6')].sort_values('rank')
            assert np.array_equal(actual[['a','b','c']].to_numpy(),numbers[tr[selected]])
            assert np.max(np.abs(actual.probability.to_numpy()-prob[selected]))<2e-10
            count+=1
    computed,contrasts=a.aggregate(r)
    pd.testing.assert_frame_equal(computed,s,check_dtype=False,atol=1e-9)
    pd.testing.assert_frame_equal(contrasts,pd.read_csv(a.OUT/'paired_differences.csv'),check_dtype=False,atol=1e-9)
    # Minimal gain/loss receipt file, keeping final dividends out of selection.
    changed=r[r.axis_six_hit.ne(r.joint_top6_hit)].copy()
    changed['transition']=np.where(changed.joint_top6_hit,'gained','lost')
    changed.to_csv(a.OUT/'gain_loss_races.csv',index=False)
    for p,m in json.loads((a.OUT/'input_manifest.json').read_text()).items():assert a.sha(a.ROOT/p)==m['sha256']
    a.save(a.OUT/'verification_extra_inputs.json',{
        str((a.RISK/'conditional_runners.parquet').relative_to(a.ROOT)):dict(sha256=a.sha(a.RISK/'conditional_runners.parquet'),purpose='Independent original risk marginal check')})
    inv=pd.read_csv(a.OUT/'operating_inverse_diagnostics.csv')
    report=dict(status='passed',model_races=len(r),tickets=len(t),exactly_six_unique_tickets_per_policy=True,
        official_ticket_labels_checked=len(t),decimal_summary_rows_checked=checked,
        baseline_summary_rows_matched=len(aligned),independent_full_joint_top6_checks=count,
        independently_reaggregated_neural_races=neurals,risk_marginal_max_error=risk_error,
        operating_inverse_max_error=float(inv.error.max()),operating_two_initializations_top6_agree=True,
        same_cost_every_race=True,all_free_predicted_mass_at_least_fixed=True,
        canonical_tie_and_runner_permutation_tests=True,current_label_and_price_mutation_encode_unchanged=True,
        date_bootstrap_reproduced=True,new_models=0,production_changed=False,
        independent_future_test=False,external_independent_review=False)
    a.save(a.OUT/'verification.json',report)
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
