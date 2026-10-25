"""Independent official-result check of saved six-ticket selections."""
import itertools
import json
import numpy as np
import pandas as pd
import compare as c


def main():
    f = pd.read_parquet(c.OUT/'race_results.parquet')
    official = pd.read_parquet(c.PATHS['flags'])
    truth = {k: set(g.loc[g.finish_order.between(1, 3), 'program_no'].astype(int))
        for k, g in official.groupby('race_key')}
    count = 0
    for row in f.itertuples():
        actual = truth[row.race_key]
        assert actual == set(map(int, row.actual.split(','))) and len(actual) == 3
        pool = list(map(int, row.companions.split(',')))
        assert len(set(pool)) == 4 and row.axis not in pool
        tickets = [set(x) | {row.axis} for x in itertools.combinations(pool, 2)]
        assert row.hit == any(t == actual for t in tickets)
        assert row.axis_hit == (row.axis in actual)
        count += 1
    summary = pd.read_csv(c.OUT/'summary.csv')
    pd.testing.assert_frame_equal(c.aggregate(f), summary, check_dtype=False, atol=1e-12)
    pairs = pd.read_csv(c.OUT/'paired_differences.csv')
    pd.testing.assert_frame_equal(c.paired(f), pairs, check_dtype=False, atol=1e-12)
    sources = json.loads((c.OUT/'input_manifest.json').read_text())
    for name, meta in sources.items():
        assert c.sha(c.ROOT/name) == meta['sha256']
    # Existing saved predictions: no target or roster changes between research models.
    base = pd.read_parquet(c.PATHS['dynamic']).query("variant=='state_gbm'")
    for path, query in [(c.PATHS['dynamic'], "variant=='state_joint'"), (c.PATHS['old'], "variant=='full103'")]:
        other = pd.read_parquet(path).query(query)
        q = other.merge(base, on=['race_key', 'program_no', 'horse_id'], validate='1:1')
        assert len(q) == len(base) and q.outcome_x.eq(q.outcome_y).all()
    direct = base.merge(official[['race_key', 'program_no', 'horse_id', 'finish_order']],
        on=['race_key', 'program_no', 'horse_id'], validate='1:1')
    assert direct.outcome.between(1, 3).eq(direct.finish_order.between(1, 3)).all()
    # Check original operating top1 for the primary exact-roster cohort.
    op = pd.read_parquet(c.PATHS['operating']).query("candidate=='current_A'")
    chosen = f[f.scope.eq('identical_roster') & f.model.eq('operating_A_v5')]
    selected = chosen.merge(base[['race_key', 'program_no', 'horse_id']],
        left_on=['race_key', 'axis'], right_on=['race_key', 'program_no'], validate='1:1')
    selected['race_id'] = selected.race_key.map(lambda k: 'RACE:'+({'1':'SEOUL','3':'BUSAN'}[k.split(':')[0]])+':'+k.split(':')[1]+':'+k.split(':')[2].zfill(2))
    same = selected.merge(op[['race_id', 'hr_no', 'top1']], left_on=['race_id', 'horse_id'], right_on=['race_id', 'hr_no'], validate='1:1')
    assert len(same) == 4133 and same.top1.all()
    report = json.loads((c.OUT/'verification.json').read_text())
    report.update(official_ticket_checks=count, original_operating_top1_checks=len(same),
        official_runner_labels_checked=len(direct), aggregate_and_bootstrap_replayed=True,
        research_models_same_rosters_and_labels=True, external_independent_review=False)
    c.save(c.OUT/'verification.json', report)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
