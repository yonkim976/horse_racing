"""Independent row-level checks of time alignment, gates, and summary counts."""
import numpy as np
import pandas as pd
import run as e


def main():
    e.check()
    d = pd.read_parquet(e.OUT / 'runner_diagnostics.parquet')
    raw = pd.read_parquet(e.OBS)
    h = pd.read_parquet(e.OUT / 'history_context.parquet')
    slots = np.load(e.OUT / 'history_slots.npy', allow_pickle=False)
    assert len(slots) == len(raw)
    assert not h.duplicated(['horse_id','race_date']).any()
    assert not d.duplicated(['race_key','gate','horse_id']).any()
    assert d.date.min() >= pd.Timestamp('2024-01-01')
    assert d.date.max() <= pd.Timestamp('2026-09-20')
    assert (d.prior_latest.dropna() <= d.loc[d.prior_latest.notna(),'date'] - pd.Timedelta(days=2)).all()
    rng = np.random.default_rng(20261011)
    checked = 0
    for j in rng.choice(len(raw), 180, replace=False):
        r = raw.iloc[j]
        cutoff = r.date - pd.Timedelta(days=2)
        want = h[(h.horse_id==r.horse_id) & (h.race_date<=cutoff)].sort_values(['race_date','race_key'],ascending=False).head(5)
        want = want[want.race_date >= cutoff-pd.Timedelta(days=730)]
        np.testing.assert_array_equal(slots[j][slots[j]>=0],want.index.to_numpy())
        if r.year < 2024:
            continue
        got = d[d.row_key==r.row_key].iloc[0]
        same = want[want.result_distance == r.distance_m]
        for input_col,output_col in [('early','prior_early')]+[(p+'_adv','prior_'+p+'_adv') for p in e.PARTS]:
            v = same[input_col].dropna()
            assert len(v) == got[output_col+'_n']
            expected = v.mean() if len(v)>=2 else np.nan
            np.testing.assert_allclose(got[output_col],expected,equal_nan=True,atol=1e-12)
        checked += 1
    sample = d.iloc[rng.choice(len(d),120,replace=False)]
    for _,r in sample.iterrows():
        g = d[d.race_key==r.race_key]
        actual_rank = g.gate.sort_values().tolist().index(r.gate)
        frac = actual_rank/(len(g)-1)
        assert abs(r.gate_fraction-frac)<1e-12
        for prefix,col in [('actual','early'),('prior','prior_early')]:
            inner = g[g.gate<r.gate]
            valid = inner[col].dropna()
            expected = np.nan
            if len(valid)>=3 and len(valid)/len(inner)>=.8 and pd.notna(r[col]):
                expected = round(valid.min()-r[col],10)
            np.testing.assert_allclose(r[prefix+'_inner_gap'],expected,equal_nan=True,atol=1e-12)
        for part in e.PARTS:
            v = g[part].dropna()
            others = g.loc[g.index!=r.name,part].dropna()
            expected = others.mean()-r[part] if len(others)>=5 and len(v)/len(g)>=.8 and pd.notna(r[part]) else np.nan
            np.testing.assert_allclose(r[part+'_adv'],expected,equal_nan=True,atol=1e-11)
    roles = pd.read_csv(e.OUT / 'outer_roles.csv')
    assert (roles[['front_n','stalk_n','middle_n','rear_n']].sum(axis=1)==roles.n).all()
    np.testing.assert_allclose(roles[['front_rate','stalk_rate','middle_rate','rear_rate']].sum(axis=1),1)
    # Every raw role source is retained; time comparisons cannot substitute rank for seconds.
    assert d.early.dropna().between(9,25).all()
    assert d.last600.dropna().between(25,80).all()
    assert d.late.dropna().between(9,40).all()
    e.check()
    e.save(e.OUT / 'verification.json',dict(passed=True, historical_slots_sample=180,
          evaluation_history_means_checked=checked, gate_and_time_rows_checked=120,
          summary_count_checks=len(roles), source_and_production_hashes_unchanged=True,
          no_models_promoted=True, no_future_contract_changed=True))
    print('Verified',checked,'history means and 120 gate/time rows')


if __name__=='__main__':
    main()
