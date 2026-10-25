"""Independent production-formula reconstruction and Decimal ticket settlement."""
from decimal import Decimal
from itertools import combinations
import importlib.util
import json
import numpy as np
import pandas as pd
import analyze as a


def main():
    manifest=json.loads((a.OUT/'input_manifest.json').read_text())
    for name,v in manifest.items():
        path=a.ROOT/name
        assert path.stat().st_size==v['bytes'] and a.sha(path)==v['sha256'],name
    spec=importlib.util.spec_from_file_location('locked_production_probability',a.PRODUCTION/'probability.py')
    probability=importlib.util.module_from_spec(spec);spec.loader.exec_module(probability)
    r=pd.read_parquet(a.OUT/'race_results.parquet').set_index('race_key')
    t=pd.read_parquet(a.OUT/'selected_tickets.parquet')
    assert len(r)==4799 and len(t)==4799*12
    assert r.previous_4133.sum()==4133 and r.promoted_1258.sum()==1258
    assert r[r.previous_4133].groupby('year').size().to_dict()=={2024:1530,2025:1522,2026:1081}
    assert r.groupby('year').size().to_dict()=={2024:1761,2025:1750,2026:1288}
    assert t.groupby(['race_key','policy']).size().eq(6).all()
    assert not t.duplicated(['race_key','policy','a','b','c']).any()
    assert t.a.lt(t.b).all() and t.b.lt(t.c).all()
    official=pd.read_parquet(a.PAYOUT/'winning_dividends.parquet').set_index('race_key')
    assert r.actual.eq(official.loc[r.index,'actual']).all()
    assert r.dividend.eq(official.loc[r.index,'dividend']).all()
    lookup={(key,policy):g.sort_values('rank') for (key,policy),g in t.groupby(['race_key','policy'],sort=False)}
    frame=a.frame();joint_checks=0;marginal_error=0.
    for key,g in frame.groupby('race_key',sort=False):
        g=g.sort_values('program_no');numbers=g.program_no.to_numpy(int)
        q=probability.trio_distribution(g.score.to_numpy(float),float(g.temperature.iloc[0]))
        ts,_=probability.support(len(g))
        marginal=np.array([q[(ts==i).any(axis=1)].sum() for i in range(len(g))])
        marginal_error=max(marginal_error,float(np.max(np.abs(marginal-g.top3.to_numpy(float)))))
        assert marginal_error<2e-10
        rank=sorted(range(len(g)),key=lambda i:(-round(float(marginal[i]),12),int(numbers[i])))
        axis=int(numbers[rank[0]])
        fixed={tuple(sorted((axis,int(numbers[x]),int(numbers[y])))) for x,y in combinations(rank[1:5],2)}
        order=sorted(range(len(ts)),key=lambda i:(-round(float(q[i]),12),tuple(numbers[ts[i]])))[:6]
        expected_free=[tuple(numbers[ts[i]]) for i in order]
        actual=tuple(map(int,r.loc[key,'actual'].split(',')))
        for policy,expected in [('axis_six',sorted(fixed)),('joint_top6',expected_free)]:
            saved=lookup[(key,policy)]
            assert list(zip(saved.a,saved.b,saved.c))==expected
            hit=actual in expected
            assert hit==bool(r.loc[key,policy+'_hit'])
            labels=np.array([ticket==actual for ticket in expected])
            assert np.array_equal(saved.hit.to_numpy(),labels)
            setlookup={tuple(numbers[z]):i for i,z in enumerate(ts)}
            probs=np.array([q[setlookup[ticket]] for ticket in expected])
            assert np.max(np.abs(saved.probability.to_numpy()-probs))<2e-10
            assert abs(probs.sum()-r.loc[key,policy+'_probability'])<2e-10
            joint_checks+=6
        assert r.loc[key,'joint_top6_probability']>=r.loc[key,'axis_six_probability']-1e-10
    s=pd.read_csv(a.OUT/'summary.csv');checks=0
    for row in s.itertuples():
        z=r if row.scope=='all_4799' else r[r[row.scope]]
        if row.subgroup.isdigit():z=z[z.year.eq(int(row.subgroup))]
        elif row.subgroup=='seoul':z=z[z.meet.eq(1)]
        elif row.subgroup=='busan':z=z[z.meet.eq(3)]
        hit=z[row.policy+'_hit']
        paid=sum((Decimal(str(x))*1000 for x in z.loc[hit,'dividend']),Decimal(0))
        assert row.races==len(z) and row.hits==int(hit.sum())
        assert row.stake_krw==len(z)*6000 and Decimal(str(row.return_krw))==paid
        assert Decimal(str(row.net_krw))==paid-Decimal(str(row.stake_krw))
        assert abs(row.roi-(float(paid)/row.stake_krw-1))<1e-12
        checks+=1
    # This was already global-six in the promotion evidence, not axis-six.
    old=pd.read_parquet(a.PROMOTION/'race_metrics.parquet').query("variant=='personal_t2'").set_index('race_key')
    match=r[r.promoted_1258]
    assert len(match)==1258 and match.joint_top6_hit.sum()==408
    assert np.array_equal(match.joint_top6_hit.to_numpy(int),old.loc[match.index,'trio_six'].to_numpy(int))
    computed,b,trans=a.aggregate(r.reset_index())
    pd.testing.assert_frame_equal(computed,s,check_dtype=False,atol=1e-10)
    pd.testing.assert_frame_equal(b,pd.read_csv(a.OUT/'paired_differences.csv'),check_dtype=False,atol=1e-10)
    pd.testing.assert_frame_equal(trans,pd.read_csv(a.OUT/'gain_loss_summary.csv'),check_dtype=False,atol=1e-10)
    # Ties and runner permutations are tested without any outcomes or prices.
    rng=np.random.default_rng(20261025);max_perm_error=0.
    for n in [6,10,16]:
        score=rng.normal(size=n);q=probability.trio_distribution(score,1.2)
        ts,_=probability.support(n);perm=rng.permutation(n)
        qp=probability.trio_distribution(score[perm],1.2)
        original={tuple(t):v for t,v in zip(ts,q)}
        max_perm_error=max(max_perm_error,max(abs(v-original[tuple(sorted(perm[t]))]) for t,v in zip(ts,qp)))
        assert max_perm_error<2e-14
        equal=probability.trio_distribution(np.zeros(n),1.2)
        assert np.argsort(-np.round(equal,12),kind='stable')[:6].tolist()==list(range(6))
    a.save('verification.json',dict(status='passed',race_count=4799,main_cohort=4133,
        main_annual_counts=[1530,1522,1081],production2026_races=1288,
        tickets_checked=joint_checks,decimal_summary_rows=checks,
        production_formula_reconstructed_races=4799,marginal_max_error=marginal_error,
        promotion_cohort_races=1258,promotion_joint6_hits=408,promotion_joint6_labels_match=True,
        exactly_six_unique_tickets_each=True,same_purchase_amount_each_race=True,
        date_bootstrap_reproduced=True,runner_permutation_max_error=max_perm_error,
        current_registry_and_registered_weights_unchanged=True,new_fits=0,
        independent_future_test=False,database_writes=0,new_dividend_collection=False))
    print((a.OUT/'verification.json').read_text())


if __name__=='__main__':main()
