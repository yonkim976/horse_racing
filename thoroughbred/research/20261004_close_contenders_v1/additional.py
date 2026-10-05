"""Literal 15–25% contender groups and a matched retrospective comparison."""
from pathlib import Path
import json
import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parent/'outputs'

def main():
    if (OUT/'literal_probability_groups.csv').exists(): raise FileExistsError('Existing additional diagnosis')
    op = pd.read_parquet(OUT/'operating_runner_predictions.parquet')
    rows = []
    for rid, g in op.groupby('race_key'):
        c = g[g.prob_win.between(.15,.25)]
        rows.append(dict(race_key=rid, meet=int(g.meet.iloc[0]), count=len(c), mass=float(c.prob_win.sum()),
            winner=int(c.outcome.eq(1).any()), podium=int(c.outcome.between(1,3).sum()==3)))
    races = pd.DataFrame(rows)
    summary = []
    for meet in (0,1,3):
        g = races if meet == 0 else races[races.meet.eq(meet)]
        for name, s in [('two_plus',g[g['count'].ge(2)]),('exactly_two',g[g['count'].eq(2)]),('three_plus',g[g['count'].ge(3)])]:
            summary.append(dict(meet=meet, group=name, races=len(s), total_races=len(g), fraction=len(s)/len(g),
                mean_count=float(s['count'].mean()), mean_mass=float(s.mass.mean()), winner_hits=int(s.winner.sum()),
                podium_hits=int(s.podium.sum()), winner_rate=float(s.winner.mean()), podium_rate=float(s.podium.mean())))
    # Independent event calculation using the actual winner and the podium maximum/minimum probabilities.
    winner_probs = op[op.outcome.eq(1)].set_index('race_key').prob_win
    podium = op[op.outcome.between(1,3)].groupby('race_key').prob_win.agg(['min','max'])
    check = races.set_index('race_key')
    assert np.array_equal(check.winner,winner_probs.reindex(check.index).between(.15,.25).astype(int))
    assert np.array_equal(check.podium,((podium['min']>=.15)&(podium['max']<=.25)).reindex(check.index).astype(int))
    t = pd.read_csv(OUT/'race_diagnostics.csv')
    o = t[t.variant.eq('operating_exact_2026')].copy()
    o['bridge'] = o.race_key.str.replace('RACE:SEOUL:','1:',regex=False).str.replace('RACE:BUSAN:','3:',regex=False).str.replace(r':0([1-9])$',r':\1',regex=True)
    matched = t[t.variant.eq('context')].merge(o,left_on='race_key',right_on='bridge',suffixes=('_research','_operating'),validate='one_to_one')
    assert (matched.field_size_research==matched.field_size_operating).all()
    # Also require the actual starter identities, not only matching race identifiers.
    source = OUT.parents[1]/'20261004_pace_finish_stack_v1/outputs/runner_predictions.parquet'
    r = pd.read_parquet(source); r = r[r.variant.eq('context')]
    r_sets = r.groupby('race_key').horse_id.agg(lambda x:frozenset(x))
    o_sets = op.groupby('race_key').horse_id.agg(lambda x:frozenset(x))
    assert all(r_sets[row.race_key_research]==o_sets[row.race_key_operating] for row in matched.itertuples())
    rng = np.random.default_rng(20261004)
    paired = {}
    dates = sorted(matched.race_date_operating.unique())
    for col in ('a_top5_podium','trio6_hit'):
        m = matched.copy(); m['delta'] = m[col+'_research']-m[col+'_operating']
        clusters = m.groupby('race_date_operating').agg(total=('delta','sum'),n=('delta','size')).reindex(dates)
        indices = rng.integers(0,len(dates),size=(2000,len(dates)))
        boot = clusters.total.to_numpy()[indices].sum(axis=1)/clusters.n.to_numpy()[indices].sum(axis=1)
        paired[col] = dict(research=float(m[col+'_research'].mean()),operating=float(m[col+'_operating'].mean()),
            delta=float(m.delta.mean()),date_bootstrap_95_interval=np.quantile(boot,[.025,.975]).tolist())
    races.to_csv(OUT/'literal_probability_races.csv',index=False)
    pd.DataFrame(summary).to_csv(OUT/'literal_probability_groups.csv',index=False)
    matched.to_csv(OUT/'matched_races.csv',index=False)
    (OUT/'matched_summary.json').write_text(json.dumps(dict(races=len(matched),bootstrap_repeats=2000,seed=20261004,
        metrics=paired,independent_literal_event_check=True,identical_starter_sets=True),indent=2)+'\n')
    print(pd.DataFrame(summary).query('meet==0').to_string(index=False))
    print(json.dumps(paired))

if __name__ == '__main__': main()
