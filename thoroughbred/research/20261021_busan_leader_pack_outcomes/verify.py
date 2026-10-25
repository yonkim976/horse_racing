"""Independent raw notation, raw result, SQL denominators and CI checks."""
from pathlib import Path
import gzip
import json
import math
import re
import duckdb
import numpy as np
import pandas as pd
from scipy.stats import t

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
R = HERE.parent
O = HERE/'outputs'


def packs(raw):
    """Separate tokens using a state scan, independent of the source regex parser."""
    text = ''.join(str(raw).split()).replace('^', '')
    out = []
    i = 0
    while i < len(text):
        if text[i] == '(':
            end = text.index(')', i)
            token = text[i+1:end]
            assert token and all(x.isdigit() for x in token.split(','))
            out.append([int(x) for x in token.split(',')])
            i = end+1
        else:
            end = i
            while end < len(text) and text[end].isdigit():
                end += 1
            assert end > i
            out.append([int(text[i:end])])
            i = end
        if i < len(text):
            assert text[i] in ',-=≡'
            i += 1
            assert i < len(text)
    flat = sum(out, [])
    assert flat and min(flat) > 0 and len(flat) == len(set(flat))
    return out


def independent_ci(frame, field, cluster):
    n = len(frame)
    grouped = frame.groupby(cluster)[field].agg(['sum', 'size'])
    k = len(grouped)
    if not n or k < 2:
        return [None, None]
    mean = frame[field].sum()/n
    var = k/(k-1) * sum((grouped['sum']-mean*grouped['size'])**2) / (n*n)
    half = t.ppf(.975, k-1) * math.sqrt(var)
    return [100*max(0, mean-half), 100*min(1, mean+half)]


def main():
    import analyze as a
    a.check_inputs()
    base = pd.read_parquet(a.BASE)
    base = base[base.meet.eq('부산')].copy()
    original_groups = pd.read_parquet(a.GROUPS)
    original_groups = original_groups[original_groups.meet.eq('부산')]
    audit = pd.read_csv(O/'race_audit.csv')
    outcomes = pd.read_csv(O/'race_outcomes.csv')
    starts = pd.read_parquet(O/'leader_starts.parquet')
    snapshot = pd.read_parquet(a.SNAP)
    snapshot = snapshot[snapshot.actual_meet_code.eq(3) & snapshot.canonical_point_code.eq('S1F')].copy()
    snapshot['source_key'] = ('부산:' + pd.to_datetime(snapshot.event_date).dt.strftime('%Y%m%d')
                              + ':' + snapshot.race_no.astype(str))
    assert snapshot.source_key.is_unique
    notation = snapshot.set_index('source_key').notation_raw.to_dict()
    parsed = {}
    for key, g in base.groupby('source_key'):
        try:
            pp = packs(notation[key])
            assert set(sum(pp, [])) == set(g.gate.astype(int))
            parsed[key] = pp
        except (AssertionError, KeyError, ValueError):
            pass
    observed_valid = set(original_groups.loc[original_groups.group_observed, 'source_key'])
    assert set(parsed) == observed_valid == set(audit.loc[audit.valid_s1f, 'source_key'])
    out_lookup = outcomes.set_index('source_key')
    leader_keys = set()
    for key, pp in parsed.items():
        g = base[base.source_key.eq(key)]
        first = g[g.gate.isin(pp[0])]
        leader_keys.update(first.row_key)
        rr = out_lookup.loc[key]
        assert int(rr.leader_count) == len(pp[0])
        assert rr.top3_count == first['rank'].between(1, 3).sum()
        assert rr.winner_count == first['rank'].eq(1).sum()
        assert bool(rr.normal_complete) == g['rank'].between(1, 30).all()
        assert bool(rr.normal_no_ties) == (g['rank'].between(1, 30).all()
                                                   and not g['rank'].duplicated().any())
        assert sorted(starts[starts.source_key.eq(key)].gate.astype(int)) == sorted(pp[0])
    assert leader_keys == set(starts.row_key)

    # All saved results must equal the original annual API items, not another derived table.
    checked_raw = 0
    for name, g in base.groupby('source_file'):
        path = ROOT/name
        assert path.resolve().is_relative_to((R/'20260929_calendar_api_v1/raw/race_execution_probe').resolve())
        with gzip.open(path, 'rt') as f:
            items = json.load(f)['response']['body']['items']['item']
        for rr in g.itertuples():
            raw = items[int(rr.source_item_index)]
            assert str(raw['hrNo']).zfill(7) == rr.horse_id
            assert int(raw['rcDate']) == int(rr.raw_date)
            assert int(raw['rcNo']) == int(rr.source_key.split(':')[-1])
            assert int(raw['chulNo']) == rr.gate and float(raw['ord']) == rr.rank
            checked_raw += 1

    # Static, in-memory SQL only: calculate every exact/compact cell independently.
    grids = []
    for name, compact in [('exact_rates.csv', False), ('compact_rates.csv', True)]:
        grid = pd.read_csv(O/name, dtype={'period':str, 'distance':str, 'leader_count':str})
        grid['compact'] = compact
        grid['cell_id'] = [name+':'+str(i) for i in range(len(grid))]
        grids.append(grid)
    grid = pd.concat(grids, ignore_index=True)
    with duckdb.connect(':memory:') as con:
        con.register('grid', grid)
        con.register('events', outcomes)
        q = con.execute('''SELECT g.cell_id, count(e.source_key) AS races,
            coalesce(sum(e.leader_count),0) AS leader_starts,
            coalesce(sum(e.top3_count),0) AS top3_horses,
            coalesce(sum(e.winner_count),0) AS winner_horses,
            count(e.source_key) FILTER(WHERE e.winner_count>0) AS group_win_races,
            count(e.source_key) FILTER(WHERE e.top3_count=0) AS exact0_top3_races,
            count(e.source_key) FILTER(WHERE e.top3_count=1) AS exact1_top3_races,
            count(e.source_key) FILTER(WHERE e.top3_count=2) AS exact2_top3_races,
            count(e.source_key) FILTER(WHERE e.top3_count=3) AS exact3_top3_races,
            count(e.source_key) FILTER(WHERE e.top3_count=4) AS exact4_top3_races,
            count(e.source_key) FILTER(WHERE e.top3_count>=2) AS two_plus_top3_races,
            count(e.source_key) FILTER(WHERE e.top3_count>=1) AS any_top3_races
            FROM grid g LEFT JOIN events e ON
              (g.scope='normal_complete' AND e.normal_complete OR
               g.scope='all_known_outcomes' AND e.all_known_outcomes OR
               g.scope='normal_no_ties' AND e.normal_no_ties)
              AND (g.period='all' OR g.period='2024_2025' AND e.year IN(2024,2025)
                   OR g.period=cast(e.year AS VARCHAR))
              AND (g.distance='all' OR g.distance=cast(e.distance AS VARCHAR))
              AND (g.compact AND g.leader_count=e.compact_count OR
                   NOT g.compact AND g.leader_count=cast(e.leader_count AS VARCHAR))
            GROUP BY g.cell_id ORDER BY g.cell_id''').df().set_index('cell_id')
    expected = grid.set_index('cell_id').loc[q.index]
    for column in q:
        np.testing.assert_array_equal(q[column], expected[column])
    for name, num, den in [('individual_win_pct', 'winner_horses', 'leader_starts'),
                           ('individual_top3_pct', 'top3_horses', 'leader_starts'),
                           ('group_win_pct', 'group_win_races', 'races'),
                           ('two_plus_top3_pct', 'two_plus_top3_races', 'races'),
                           ('any_top3_pct', 'any_top3_races', 'races')]:
        calculated = 100*q[num]/q[den].replace(0, np.nan)
        np.testing.assert_allclose(calculated, expected[name], atol=1e-12, equal_nan=True)
    assert (grid.exact0_top3_races+grid.exact1_top3_races+grid.two_plus_top3_races).eq(grid.races).all()
    assert grid.winner_horses.eq(grid.group_win_races+grid.extra_winners_beyond_group_event).all()
    zero = grid.races.eq(0)
    assert grid.loc[zero, ['individual_top3_pct', 'individual_win_pct', 'group_win_pct']].isna().all().all()
    assert grid.loc[grid.leader_count.eq('1'), 'two_plus_top3_races'].eq(0).all()

    ci_checks = 0
    for rr in grid[grid.scope.eq('normal_complete') & grid.races.gt(0)].itertuples():
        s = starts[starts.normal_complete].copy()
        if rr.period != 'all':
            s = s[s.year.between(2024, 2025)] if rr.period == '2024_2025' else s[s.year.eq(int(rr.period))]
        if rr.distance != 'all':
            s = s[s.distance.eq(int(rr.distance))]
        s = s[s.compact_count.eq(rr.leader_count)] if rr.compact else s[s.leader_count.eq(int(rr.leader_count))]
        assert len(s) == rr.leader_starts
        for outcome in ['top3', 'win']:
            for cluster in ['date', 'horse_id']:
                actual = independent_ci(s, outcome, cluster)
                desired = [getattr(rr, f'{outcome}_{cluster}_lower95'), getattr(rr, f'{outcome}_{cluster}_upper95')]
                np.testing.assert_allclose(np.array(actual, dtype=float), desired, atol=1e-10, equal_nan=True)
                ci_checks += 1
    a.check_inputs()
    a.save('verification.json', dict(status='verified', parsed_complete_s1f=len(parsed),
        raw_api_results_checked=checked_raw, leader_starts_checked=len(starts),
        primary_races=int(outcomes.normal_complete.sum()), sql_cells=len(grid),
        cluster_ci_pairs_checked=ci_checks, whole_roster_matched=True,
        duplicate_finish_ranks_preserved=True, group_and_individual_denominators_separate=True,
        zero_sample_probabilities_null=True, protected_inputs_unchanged=True,
        new_fits=0, database_access=False, operating_model_changed=False))
    print((O/'verification.json').read_text())


if __name__ == '__main__':
    main()
