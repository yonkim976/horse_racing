"""Replay frozen models and independently validate every selected anchor and pair."""
import ast
import json

import lightgbm as lgb
import numpy as np
import pandas as pd
import run as e


def main():
    e.check()
    for path in e.HERE.glob('*.py'):ast.parse(path.read_text(),filename=str(path))
    f,p=e.load();d=pd.read_parquet(e.OUT/'decisions.parquet').set_index('race_key')
    rr=pd.read_parquet(e.OUT/'race_metrics.parquet');rank=pd.read_parquet(e.OUT/'selection_rankings.parquet')
    assert len(d)==4799 and d.proposed_switch.sum()==671
    assert len(rr)==4799*6 and len(rank)==50754*6
    source=pd.read_csv(e.P/'race_diagnostics.csv')
    for v,old in [('frozen103','baseline103'),('frozen122','combined122')]:
        a=rr[rr.variant.eq(v)].set_index('race_key')[e.METRICS].sort_index()
        b=source[source.variant.eq(old)].set_index('race_key')[e.METRICS].sort_index()
        np.testing.assert_array_equal(a,b)
    # The function rejects labels rather than trusting a caller to ignore them.
    try:
        e.decide(f,p)
    except AssertionError:pass
    else:raise AssertionError('outcome accepted into decision function')
    clean=e.decide(f,p.drop(columns='outcome')).sort_values('race_key').reset_index(drop=True)
    dirty=p.copy();dirty['outcome']=np.random.default_rng(49).permutation(dirty.outcome.to_numpy())
    repeated=e.decide(f,dirty.drop(columns='outcome')).sort_values('race_key').reset_index(drop=True)
    pd.testing.assert_frame_equal(clean,repeated)
    blind_cols=[c for c in clean.columns if c=='race_key' or c in d.columns]
    pd.testing.assert_frame_equal(clean[blind_cols].set_index('race_key'),d.reset_index()[blind_cols].set_index('race_key').sort_index())
    assert (d.joint_recent_accept<=d.joint_supported_accept).all()
    assert (d.joint_supported_accept<=d.joint_only_accept).all()
    assert (d.joint_recent_accept<=d.recent_only_accept).all()
    assert d.loc[d.new_keep_fast_n.eq(0),'joint_only_accept'].eq(False).all()
    assert d.loc[d.new_profile_count3.lt(2)|d.old_profile_count3.lt(2),'joint_recent_accept'].eq(False).all()
    # Recompute the policy from PIT inputs independently of stored booleans.
    facts=f.set_index(e.KEY)
    labels=p[p.variant.eq('combined122')].set_index(e.KEY).outcome
    sorted_predictions={variant:{rid:g.sort_values('model_rank')for rid,g in a.groupby('race_key')}
                        for variant,a in p.groupby('variant')}
    independent=[]
    for rid,row in d.iterrows():
        a=facts.loc[(rid,row.old_program_no,row.old_horse_id)]
        b=facts.loc[(rid,row.new_program_no,row.new_horse_id)]
        joint=bool(b.keep_fast_g3>=0 and b.keep_fast_g1>=0)
        supported=bool(b.keep_fast_n>=2)
        recent=bool(a.profile_count3>=2 and b.profile_count3>=2 and
                    b.moist_last3_record_index_mean>=a.moist_last3_record_index_mean)
        tests=dict(joint_only=joint,joint_supported=joint and supported,
                   joint_recent=joint and supported and recent,recent_only=recent)
        for v in e.VARIANTS:
            src='baseline103'if v=='frozen103'else'combined122'
            g=sorted_predictions[src][rid]
            if v.startswith('frozen'):axis=int(g.program_no.iloc[0])
            else:axis=int(row.new_program_no if(not row.proposed_switch or tests[v])else row.old_program_no)
            seq=[axis]+[int(x)for x in g.program_no if x!=axis]
            assert len(seq)==len(set(seq))==len(g)
            truth={int(x.program_no):int(x.outcome)for x in g.itertuples()}
            winners={k for k,value in truth.items()if 1<=value<=2}
            independent.append(dict(variant=v,race_key=rid,axis_program_no=axis,
                 axis_top3=int(1<=truth[axis]<=3),axis_top2=int(1<=truth[axis]<=2),axis_win=int(truth[axis]==1),
                 quinella_one=int(set(seq[:2])==winners),axis_next3=int(axis in winners and winners<=set(seq[:4]))))
    x=pd.DataFrame(independent).set_index(['variant','race_key']).sort_index()
    y=rr.set_index(['variant','race_key']).sort_index()
    np.testing.assert_array_equal(x,y[x.columns])
    for v,z in rank.groupby('variant'):
        g=z.groupby('race_key')
        assert g.selection_rank.min().eq(1).all()
        assert g.selection_rank.max().equals(g.size())
        assert not z.duplicated(e.KEY).any()
        first=z[z.selection_rank.eq(1)].set_index('race_key').program_no.sort_index()
        np.testing.assert_array_equal(first,rr[rr.variant.eq(v)].set_index('race_key').axis_program_no.sort_index())
    diff=pd.read_csv(e.OUT/'paired_differences.csv',dtype={'period':str})
    for (v,ref),z in diff.groupby(['variant','reference']):
        a=rr[rr.variant.eq(v)].set_index('race_key');b=rr[rr.variant.eq(ref)].set_index('race_key')
        for period,g in e.windows(a):
            for metric in e.METRICS:
                delta=g[metric]-b.loc[g.index,metric];row=z[z.period.eq(period)&z.metric.eq(metric)].iloc[0]
                assert row.gain==delta.eq(1).sum()and row.loss==delta.eq(-1).sum()and row.net==delta.sum()
                assert np.isclose(row.difference_pp,delta.mean()*100)
    # Reuse the untouched model files and training category vocabularies.
    allf=pd.read_parquet(e.P/'features.parquet');replay=[]
    for stem,parent,variant in [('combined122',e.P,'combined122'),('full103',e.B,'baseline103')]:
        for meet in [1,3]:
            for year in [2024,2025,2026]:
                folder=parent/'models'/f'{stem}_{meet}_{year}';meta=json.loads((folder/'metadata.json').read_text())
                a=allf[allf.meet.eq(meet)&allf.year.eq(year)].copy()
                z=p[p.variant.eq(variant)&p.meet.eq(meet)&p.year.eq(year)]
                a=a.set_index(e.KEY).loc[pd.MultiIndex.from_frame(z[e.KEY])].reset_index()
                x=a[meta['features']].copy()
                for col,vocab in meta['category_vocabulary'].items():x[col]=pd.Categorical(x[col],categories=vocab)
                model=lgb.Booster(model_file=str(folder/'model.txt'))
                score=model.predict(x,raw_score=True,num_threads=1)
                err=float(np.abs(score-z.raw_score.to_numpy()).max());assert err<1e-10
                assert pd.Timestamp(meta['train_end'])<pd.Timestamp(year=year,month=1,day=1)
                replay.append(dict(variant=variant,meet=meet,year=year,runners=len(z),max_raw_error=err))
    e.save(e.OUT/'model_replay.json',dict(models=replay,model_count=12,max_raw_error=max(x['max_raw_error']for x in replay)))
    e.save(e.OUT/'verification.json',dict(status='verified',races=4799,runners_per_variant=50754,variants=6,
         original_axis_switches=671,independent_axis_and_pair_checks=len(independent),
         blinded_to_current_outcomes=True,missing_history_not_zero_filled=True,policy_nesting_verified=True,
         original_metrics_exactly_reproduced=True,model_replay_count=12,max_raw_error=max(x['max_raw_error']for x in replay),
         source_hashes=len(json.loads((e.OUT/'input_manifest.json').read_text())),new_models=0,
         probability_changed=False,production_changed=False,selected22_changed=False,future_contract_changed=False,
         database_access=False,network_access=False,jeju_access=False))
    e.check();print((e.OUT/'verification.json').read_text())


if __name__=='__main__':main()
