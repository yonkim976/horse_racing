"""Independently reconstruct frozen rankings, transitions, strata and SHAP sums."""
import ast
import json

import numpy as np
import pandas as pd
import run as e


def main():
    e.check()
    for p in e.HERE.glob('*.py'):
        ast.parse(p.read_text(), filename=str(p))
    d=pd.read_parquet(e.OUT/'races.parquet').set_index('race_key')
    pred=pd.read_parquet(e.P/'runner_predictions.parquet')
    for variant, side in [('baseline103','old'),('combined122','new')]:
        p=pred[pred.variant.eq(variant)&pred.target.eq(3)].copy()
        a=p.sort_values(['race_key','raw_score','program_no'],ascending=[True,False,True]).groupby('race_key').head(1).set_index('race_key')
        assert len(a)==4799
        np.testing.assert_array_equal(a.horse_id,d.loc[a.index,side+'_horse_id'])
        np.testing.assert_array_equal(a.outcome.between(1,3),d.loc[a.index,side+'_hit'])
    switched=d.old_horse_id.ne(d.new_horse_id)
    np.testing.assert_array_equal(switched,d.switched)
    net=d.new_outcome.between(1,3).astype(int)-d.old_outcome.between(1,3).astype(int)
    np.testing.assert_array_equal(net,d.net)
    assert d.loc[~switched,'net'].eq(0).all()
    expect={2024:(252,69,59),2025:(252,62,75),2026:(167,55,35)}
    for year,(switch,gain,loss) in expect.items():
        z=d[d.year.eq(year)]
        assert (int(z.switched.sum()),int(z.net.eq(1).sum()),int(z.net.eq(-1).sum()))==(switch,gain,loss)
    c=pd.read_csv(e.OUT/'conditions.csv',keep_default_na=False)
    count=0
    for period,z in e.windows(d.reset_index()):
        for col,t in c[c.period.eq(period)].groupby('condition'):
            assert t.races.sum()==len(z)
            assert t.switches.sum()==z.switched.sum()
            assert t.net.sum()==z.net.sum()
            for value,g in z.groupby(col,dropna=False,observed=True):
                row=t[t.value.eq(str(value))]
                assert len(row)==1,(period,col,value)
                row=row.iloc[0]
                assert row.races==len(g) and row.gain==g.net.eq(1).sum() and row.loss==g.net.eq(-1).sum()
                count+=1
    y=pd.read_csv(e.OUT/'year_decomposition.csv')
    for (matched,strata),z in y.groupby(['matched','strata']):
        a=d[d.year.eq(2025)];b=d[d.year.eq(2026)]
        if matched:
            a=a[a.race_date.dt.strftime('%m-%d').le('09-20')]
            b=b[b.race_date.dt.strftime('%m-%d').le('09-20')]
        assert np.isclose((z.mix_contribution+z.within_contribution).sum(),b.net.mean()-a.net.mean())
        assert z.common_support.all()
    at=pd.read_csv(e.OUT/'pair_attributions.csv')
    assert at.race_key.nunique()==671
    for variant,z in at.groupby('variant'):
        g=z.groupby('race_key')
        np.testing.assert_allclose(g.contribution.sum(),g.pair_score_delta.first(),atol=1e-10,rtol=0)
        sign=g.pair_score_delta.first()
        assert (sign.ge(0).all() if variant=='combined122' else sign.le(0).all())
        ties=sign[sign.eq(0)].index
        if len(ties):
            # Exactly equal scores are ordered by the lower program number.
            q=d.loc[ties]
            assert (q.new_program_no.lt(q.old_program_no).all() if variant=='combined122'
                    else q.old_program_no.lt(q.new_program_no).all())
    replay=json.loads((e.OUT/'model_replay.json').read_text())
    assert len(replay['models'])==12 and max(r['max_error']for r in replay['models'])<1e-10
    assert d.new_rank_old.ge(2).where(d.switched,True).all()
    assert len(pd.read_csv(e.OUT/'switched_races.csv'))==671
    checks=dict(status='verified',races=4799,runners=50754,switched_races=671,
                models_replayed=12,max_raw_score_error=max(r['max_error']for r in replay['models']),
                independently_rebuilt_anchors=True,transition_counts_verified=True,condition_cells_checked=count,
                decomposition_identity_verified=True,decomposition_all_cells_common_support=True,
                shap_sums_verified=True,source_hashes_checked=len(json.loads((e.OUT/'input_manifest.json').read_text())),
                new_models=0,production_changed=False,selected22_changed=False,future_contract_changed=False,
                database_access=False,network_access=False,jeju_access=False)
    e.save(e.OUT/'verification.json',checks)
    e.check();print(json.dumps(checks,ensure_ascii=False))


if __name__=='__main__': main()
