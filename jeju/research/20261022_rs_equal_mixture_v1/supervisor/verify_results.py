"""Independent reconstruction; no experiment imports, fitting, or weight search.

Reuses sealed supervisor reference math with explicit remaining choice sets.
The experiment uses a separate streaming implementation. Real-data verification
requires the supervisor's execution approval and completed E output files.
"""
import hashlib
import importlib.util
import itertools
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
STUDY = HERE.parent
ROOT = HERE.parents[3]
OUT = STUDY / 'experiment/outputs'
PREV = ROOT / 'jeju/research/20261022_tb_state_transfer_v1'
PRIOR_OUT = PREV / 'experiment/outputs'
STYLE = ROOT / 'jeju/research/20261010_style_history_ablation_v1/outputs'
MATH = ROOT / 'jeju/research/20261022_dynamic_ability_pace_v1/supervisor/math_reference.py'
MATH_SHA = 'fc60a9fdf8d128de9a558195026b468962ddf96565e4245c3e846f6c0aba81f6'
ERRORS = defaultdict(float)
EDGES = np.array([0, .00001, .00005, .0001, .00025, .0005, .001, .0025,
                  .005, .01, .025, .05, .1, .25, .5, .75, 1.])
POOLS = ('WIN', 'PLC', 'QNL', 'EXA', 'QPL', 'TLA', 'TRI')


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


assert sha(MATH) == MATH_SHA
spec = importlib.util.spec_from_file_location('_sealed_supervisor_math', MATH)
ref = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ref)


def near(name, a, b, tol=1e-10):
    a, b = np.asarray(a, float), np.asarray(b, float)
    assert a.shape == b.shape and np.isfinite(a).all() and np.isfinite(b).all(), name
    error = float(np.max(np.abs(a-b))) if a.size else 0.
    ERRORS[name] = max(ERRORS[name], error)
    assert error <= tol, (name, error, tol)


def top_keys(probs, k):
    rest = probs.copy()
    keys = []
    for _ in range(k):
        key, _ = ref.stable_selection(rest)
        keys.append(key)
        del rest[key]
    return keys


def pair_distribution(joint, pool, selected):
    mass = np.zeros(4)
    selected = set(selected)
    for order, p in joint.items():
        events = ({tuple(sorted(order[:2]))} if pool == 'QNL' else
                  set(itertools.combinations(sorted(order), 2)))
        mass[len(selected & events)] += p
    return mass


def synthetic():
    cases = 0
    for n in (5, 7, 8, 12):
        x = np.linspace(-1.5, 2., n)
        a, b = ref.distribution(x, .81), ref.distribution(x[::-1], 1.37)
        e = {key: .5*a[key]+.5*b[key] for key in a}
        assert abs(math.fsum(e.values())-1) < 1e-12
        plc = 2 if n < 8 else 3  # Synthetic sales-opening roster is explicitly known.
        maps_a, rank_a = ref.aggregate(a, n, plc)
        maps_b, rank_b = ref.aggregate(b, n, plc)
        maps_e, rank_e = ref.aggregate(e, n, plc)
        near('synthetic_rank_linearity', rank_e, .5*rank_a+.5*rank_b)
        for pool in POOLS:
            pe = np.array(list(maps_e[pool].values()))
            near('synthetic_event_linearity', pe,
                 .5*np.array(list(maps_a[pool].values()))+.5*np.array(list(maps_b[pool].values())))
        for pool in ('QNL', 'QPL'):
            chosen = top_keys(maps_e[pool], 3)
            mass = pair_distribution(e, pool, chosen)
            near('synthetic_count_mass', mass.sum(), 1.)
            near('synthetic_expected_count', np.arange(4)@mass,
                 sum(maps_e[pool][key] for key in chosen))
            assert sum(mass[1:]) <= np.arange(4)@mass+1e-12
        bad = ref.distribution(.5*x/.81+.5*x[::-1]/1.37)
        assert max(abs(e[key]-bad[key]) for key in e) > 1e-5
        cases += 1
    return {'passed': True, 'synthetic_rosters': cases, 'opening_count_is_synthetic': True,
            'exact_Q_mixture_is_not_score_average': True, 'maximum_errors': dict(ERRORS),
            'verifier_sha256': sha(Path(__file__)), 'math_reference_sha256': sha(MATH),
            'real_data_E_evaluated': False}


def load_both(name):
    old = pd.read_parquet(PRIOR_OUT / name)
    old_s = old.loc[old.arm.eq('S')]
    old_r = (old if name == 'pair_selection_diagnostics.parquet' else
             pd.read_parquet(ROOT / 'jeju/research/20261022_dynamic_ability_pace_v1/experiment/outputs' / name))
    old_r = old_r.loc[old_r.arm.eq('R')]
    new = pd.read_parquet(OUT / name)
    assert set(new.arm) == {'E'}, name
    return pd.concat([old_r, old_s, new], ignore_index=True)


def main():
    assert (HERE / 'EXECUTION_APPROVAL.json').is_file(), 'No supervisor approval'
    report = json.loads((OUT / 'report.json').read_text())
    assert report['fit_count'] == report['calibration_count'] == report['weight_search_count'] == 0
    receipt = json.loads((OUT / 'fit_run_receipt.json').read_text())
    assert receipt['run_count'] == 1 and receipt['status'] == 'COMPLETED_RESEARCH_ONLY'
    assert receipt['fit_count'] == receipt['calibration_count'] == receipt['weight_search_count'] == 0
    for name, item in receipt['artifacts'].items():
        path = (OUT / name).resolve(strict=True)
        assert path.is_relative_to(OUT)
        assert sha(path) == item['sha256'] and path.stat().st_size == item['bytes']
    par = json.loads((PRIOR_OUT / 'parameters.json').read_text())
    data = pd.read_parquet(STYLE / 'features.parquet', columns=[
        'api_record_id', 'race_id', 'race_date', 'year', 'horse_number',
        'field_n', 'finish_position', 'distance_m'])
    data = data.loc[data.year.isin([2024, 2025, 2026])].copy()
    data['race_date'] = pd.to_datetime(data.race_date).dt.strftime('%Y-%m-%d')
    assert len(data) == 17412 and data.race_id.nunique() == 1779
    raw_r = pd.concat([pd.read_parquet(STYLE / f'F1_STYLE6_{y}/evaluation_scores.parquet')
                       for y in (2024, 2025, 2026)]).set_index('api_record_id')
    raw_s = pd.read_parquet(PRIOR_OUT / 'candidate_oos_scores.parquet')
    raw_s = raw_s.loc[raw_s.arm.eq('S') & raw_s.role.eq('evaluation')].set_index('api_record_id')
    assert raw_r.index.is_unique and raw_s.index.is_unique
    assert set(raw_r.index) == set(raw_s.index) == set(data.api_record_id)
    tr = {int(y): row['temperature'] for y, row in par['R_temperatures_reused'].items()}
    ts = {int(row['year']): row['temperature_fit']['temperature'] for row in par['models'] if row['arm'] == 'S'}
    metrics = load_both('race_pool_metrics.parquet').set_index(['race_id', 'arm', 'pool'])
    selections = load_both('selected_ticket_ledger.parquet').set_index(['race_id', 'arm', 'pool'])
    marginals = load_both('evaluation_runner_marginals.parquet').set_index(['race_id', 'arm', 'horse_number'])
    axis = load_both('win_axis_ledger.parquet').set_index(['race_id', 'arm'])
    pairs = load_both('pair_selection_diagnostics.parquet').set_index(['race_id', 'arm', 'pool', 'k'])
    assert all(f.index.is_unique for f in (metrics, selections, marginals, axis, pairs))
    assert len(metrics) == len(selections) == 37251
    assert len(marginals) == 52236 and len(axis) == 5337 and len(pairs) == 21348
    bins = defaultdict(lambda: np.zeros((16, 4)))
    rows = []
    triples = 0
    for race_number, (rid, g) in enumerate(data.groupby('race_id', sort=True), 1):
        g = g.sort_values('horse_number')
        nums = g.horse_number.to_numpy(int)
        n = len(g)
        assert n == g.field_n.iloc[0] and set(g.finish_position) == set(range(1, n+1))
        actual = tuple(np.argsort(g.finish_position.to_numpy())[:3])
        year = int(g.year.iloc[0])
        plc = 3 if n >= 8 else None
        a = ref.distribution(raw_r.loc[g.api_record_id, 'score'].to_numpy(), tr[year])
        b = ref.distribution(raw_s.loc[g.api_record_id, 'score'].to_numpy(), ts[year])
        joints = {'R': a, 'S': b, 'E': {k: .5*a[k]+.5*b[k] for k in a}}
        all_maps = {}
        all_ranks = {}
        losses = {}
        for arm, joint in joints.items():
            triples += len(joint)
            pools, rank = ref.aggregate(joint, n, plc)
            all_maps[arm], all_ranks[arm], losses[arm] = pools, rank, {}
            for pool, probs in pools.items():
                if pool == 'PLC' and plc is None:
                    continue
                metric, keys, p, y = ref.score_events(pool, probs, actual, plc)
                losses[arm][pool] = metric
                saved = metrics.loc[(rid, arm, pool)]
                near('all_pool_logloss', metric['log_loss'], saved.race_nll)
                near('all_pool_brier', metric['brier'], saved.race_brier)
                assert saved.ticket_count == len(keys) and saved.event_count == y.sum()
                key, prob = ref.stable_selection(probs)
                selected = selections.loc[(rid, arm, pool)]
                assert json.loads(selected.selected_ticket_key) == [int(nums[i]) for i in key]
                assert bool(selected.selected_hit) == (key in ref.winners(pool, actual, plc))
                near('selected_prob', prob, selected.selected_probability)
                if arm == 'E':
                    idx = np.minimum(np.searchsorted(EDGES, p, side='right')-1, 15)
                    accum = np.column_stack([np.bincount(idx, minlength=16),
                        np.bincount(idx, weights=p, minlength=16),
                        np.bincount(idx, weights=y, minlength=16),
                        np.bincount(idx, weights=(p-y)**2, minlength=16)])
                    for period in ('ALL', str(year)):
                        bins[(pool, period)] += accum
                rows.append({'race_id': rid, 'race_date': g.race_date.iloc[0], 'year': year,
                             'arm': arm, 'pool': pool, 'nll': metric['log_loss'], 'brier': metric['brier']})
            for i, number in enumerate(nums):
                m = marginals.loc[(rid, arm, int(number))]
                near('runner_marginals', [rank[i, 0], rank[i, 1], rank[i, 2], rank[i, :2].sum(), rank[i].sum()],
                     m[['p_win', 'p_exact2', 'p_exact3', 'p_top2', 'p_top3']].to_numpy(float))
            key, prob = ref.stable_selection(pools['WIN'])
            saved_axis = axis.loc[(rid, arm)]
            assert saved_axis.selected_horse_number == nums[key[0]]
            assert bool(saved_axis.selected_hit_top3) == (key[0] in actual)
            near('axis_probability', prob, saved_axis.selected_probability)
            for pool, k in itertools.product(('QNL', 'QPL'), (1, 3)):
                chosen = top_keys(pools[pool], k)
                mass = pair_distribution(joint, pool, chosen)
                pair = pairs.loc[(rid, arm, pool, k)]
                assert json.loads(pair.selected_tickets_json) == [[int(nums[i]) for i in key] for key in chosen]
                near('pair_ticket_probs', [pools[pool][key] for key in chosen], json.loads(pair.selected_probabilities_json))
                near('pair_count_pmf', mass, pair[[f'count_probability_{i}' for i in range(4)]].to_numpy(float))
                near('pair_union', mass[1:].sum(), pair.selected_union_probability)
                near('pair_expected_count', np.arange(4)@mass, pair.expected_hits)
                assert pair.realized_hit_count == len(set(chosen) & ref.winners(pool, actual, plc))
        near('real_rank_linearity', all_ranks['E'], .5*all_ranks['R']+.5*all_ranks['S'])
        for pool in losses['E']:
            keys = sorted(all_maps['E'][pool])
            pa, pb, pe = [np.array([all_maps[arm][pool][key] for key in keys]) for arm in ('R', 'S', 'E')]
            near('real_event_linearity', pe, .5*pa+.5*pb)
            spread = .25*(np.mean((pa-pb)**2) if pool in ('PLC', 'QPL') else np.sum((pa-pb)**2))
            near('exact_Brier_mixture_identity', losses['E'][pool]['brier'],
                 .5*losses['R'][pool]['brier']+.5*losses['S'][pool]['brier']-spread)
            assert losses['E'][pool]['log_loss'] <= .5*(losses['R'][pool]['log_loss']+losses['S'][pool]['log_loss'])+1e-12
        if race_number % 300 == 0:
            print(json.dumps({'phase': 'independent_full_Q_verification', 'races': race_number}), flush=True)
    rel = pd.read_parquet(OUT / 'reliability_bins.parquet')
    assert len(rel) == 448 and set(rel.arm) == {'E'}
    for row in rel.itertuples(index=False):
        count, sp, sy, sb = bins[(row.pool, str(row.evaluation_period))][row.bin_index]
        assert row.ticket_events == count
        if count:
            near('reliability', [sp/count, sy/count, sb/count],
                 [row.mean_probability, row.observed_event_rate, row.mean_ticket_brier])
        else:
            assert pd.isna(row.mean_probability) and pd.isna(row.observed_event_rate) and pd.isna(row.mean_ticket_brier)
    checked = pd.DataFrame(rows)
    dates = sorted(checked.race_date.unique())
    schedule_path = ROOT / 'jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy'
    assert sha(schedule_path) == 'd141b0c3f9a463cbfc9d1f4c61228b58757c31aee4ec74b79f41c5baeadaccbd'
    schedule = np.load(schedule_path, allow_pickle=False)
    assert len(dates) == 269 and schedule.shape == (2000, 269)
    assert hashlib.sha256('\n'.join(dates).encode()).hexdigest() == 'e4aa73b866eac00b361d0354fdd62b7b2bd98915e003f250adc40a8df0a66b84'
    def paired(frame, field, right):
        wide = frame.pivot(index=['race_id', 'race_date'], columns='arm', values=field).astype(float)
        delta = wide.E-wide[right]
        daily = delta.groupby(level='race_date').agg(['sum', 'count']).reindex(dates, fill_value=0)
        draws = daily['sum'].to_numpy()[schedule].sum(axis=1)/daily['count'].to_numpy()[schedule].sum(axis=1)
        return wide, delta, draws
    reported = {(x['comparison'], x['metric']): x for x in report['paired_point_and_bootstrap_summary']}
    draws_saved = pd.read_parquet(OUT / 'comparison_bootstrap_draws.parquet')
    def check_draws(name, metric, actual):
        saved = draws_saved.loc[draws_saved.comparison.eq(name) & draws_saved.metric.eq(metric)].sort_values('draw')
        assert len(saved) == 2000
        near('bootstrap_draws', actual, saved.difference)
    gates, axis_results, pair_results, all_loss_ci = {}, [], [], []
    for right in ('S', 'R'):
        name = f'E_minus_{right}'
        tri = checked.loc[checked.pool.eq('TRI')]
        _, delta, draws = paired(tri, 'nll', right)
        check_draws(name, 'TRI_delta_nll', draws)
        near('TRI_bootstrap_CI', np.quantile(draws, [.025, .975]), reported[(name, 'TRI_delta_nll')]['ci95'])
        near('reported_TRI_delta', delta.mean(), reported[(name, 'TRI_delta_nll')]['point_difference'])
        _, db, _ = paired(tri, 'brier', right)
        win = checked.loc[checked.pool.eq('WIN')]
        _, wn, _ = paired(win, 'nll', right)
        _, wb, _ = paired(win, 'brier', right)
        gate = bool(np.quantile(draws, .975) < 0 and db.mean() <= 0 and wn.mean() <= 0 and wb.mean() <= 0)
        gates[name] = gate
        assert report['comparisons'][right]['comparison_pass'] == gate
        for pool in POOLS:
            for field in ('nll', 'brier'):
                _, delta, draws = paired(checked.loc[checked.pool.eq(pool)], field, right)
                check_draws(name, f'{pool}_delta_{field}', draws)
                if pool in ('TRI', 'WIN'):
                    near('reported_gate_point', delta.mean(), reported[(name, f'{pool}_delta_{field}')]['point_difference'])
                    near('reported_gate_CI', np.quantile(draws, [.025, .975]), reported[(name, f'{pool}_delta_{field}')]['ci95'])
                all_loss_ci.append({'comparison': name, 'pool': pool, 'metric': field, 'races': len(delta),
                                    'delta': float(delta.mean()), 'ci95': np.quantile(draws, [.025, .975]).tolist(),
                                    'primary_only_for_TRI_nll': True, 'multiplicity_adjusted': False})
        wide, delta, draws = paired(axis.reset_index(), 'selected_hit_top3', right)
        axis_ci = np.quantile(draws, [.025, .975]).tolist()
        check_draws(name, 'WIN_axis_top3_hit_rate', draws)
        lc = wide.E.groupby(level='race_date').sum().reindex(dates).to_numpy()[schedule].sum(axis=1)
        rc = wide[right].groupby(level='race_date').sum().reindex(dates).to_numpy()[schedule].sum(axis=1)
        axis_results.append({'comparison': name, 'left_hits': int(wide.E.sum()), 'right_hits': int(wide[right].sum()),
                             'difference': float(delta.mean()), 'ci95': axis_ci,
                             'relative_change': float(wide.E.sum()/wide[right].sum()-1),
                             'relative_ci95': np.quantile(lc/rc-1, [.025, .975]).tolist()})
        for pool, k in itertools.product(('QNL', 'QPL'), (1, 3)):
            frame = pairs.reset_index().loc[lambda f: f.pool.eq(pool) & f.k.eq(k)].copy()
            frame['hit_any'] = frame.realized_hit_count.gt(0)
            for field in ('hit_any', 'realized_hit_count'):
                wide, delta, draws = paired(frame, field, right)
                if field == 'hit_any':
                    check_draws(name, f'{pool}_k{k}_hit_any_rate', draws)
                pair_results.append({'comparison': name, 'pool': pool, 'k': k, 'metric': field,
                                     'races': len(delta), 'left_total': float(wide.E.sum()),
                                     'right_total': float(wide[right].sum()), 'difference': float(delta.mean()),
                                     'ci95': np.quantile(draws, [.025, .975]).tolist(), 'descriptive_only': True})
    overall = gates['E_minus_S'] and gates['E_minus_R']
    assert report['overall_research_candidate_gate_pass'] == overall
    summary = pd.read_parquet(OUT / 'pool_summary.parquet')
    assert len(summary) == 56
    for row in summary.itertuples(index=False):
        frame = checked.loc[checked.pool.eq(row.pool)]
        if row.period != 'ALL':
            frame = frame.loc[frame.year.eq(int(row.period))]
        right = row.comparison.rsplit('_', 1)[-1]
        assert frame.race_id.nunique() == row.races
        e, r = frame.loc[frame.arm.eq('E')], frame.loc[frame.arm.eq(right)]
        near('summary_E', [e.nll.mean(), e.brier.mean()], [row.E_nll, row.E_brier])
        near('summary_reference', [r.nll.mean(), r.brier.mean()], [row.reference_nll, row.reference_brier])
        near('summary_delta', [e.nll.mean()-r.nll.mean(), e.brier.mean()-r.brier.mean()], [row.delta_nll, row.delta_brier])
    summary = pd.read_parquet(OUT / 'pair_selection_summary.parquet')
    assert len(summary) == 12
    for row in summary.itertuples(index=False):
        frame = pairs.xs((row.arm, row.pool, row.k), level=['arm', 'pool', 'k'])
        assert len(frame) == row.races
        near('pair_summary', [frame.selected_union_probability.mean(), frame.expected_hits.mean(),
                             frame.realized_hit_count.mean(), frame.realized_hit_count.gt(0).mean()],
             [row.mean_union_probability, row.mean_expected_hits, row.mean_realized_hits, row.hit_any_rate])
    pins = json.loads((HERE / 'SESSION_START.json').read_text())['protected_pins']
    for item in pins:
        assert sha(ROOT / item['path']) == item['sha256'], item['path']
    result = {'passed': True, 'races': 1779, 'runners_per_arm': 17412, 'arms': ['R', 'S', 'E'],
              'ordered_triples_reconstructed': triples, 'metric_and_selection_rows_each': len(metrics),
              'marginal_rows': len(marginals), 'pair_count_PMFs': len(pairs), 'reliability_E_rows': len(rel),
              'all_loss_axis_pair_bootstrap_draws_compared': len(draws_saved),
              'TRI_bootstrap_draws_compared': 4000, 'gate_decisions': gates, 'overall_gate_pass': bool(overall),
              'axis_comparisons': axis_results, 'maximum_errors': dict(ERRORS),
              'protected_pins_unchanged': len(pins), 'verifier_sha256': sha(Path(__file__)),
              'math_reference_sha256': sha(MATH), 'experiment_module_imported': False,
              'new_fit_or_calibration': False, 'bootstrap_scope': 'fixed predictions on reused development period; no fitting uncertainty'}
    for name, content in [('RESULT_VERIFICATION.json', result), ('PAIR_BOOTSTRAP.json', pair_results),
                          ('LOSS_BOOTSTRAP_DIAGNOSTICS.json', all_loss_ci)]:
        destination = HERE / name
        if destination.exists():
            assert json.loads(destination.read_text()) == content, 'Existing verification differs: '+name
        else:
            with destination.open('x') as stream:
                json.dump(content, stream, indent=2, ensure_ascii=False)
                stream.write('\n')
    print(json.dumps(result, indent=2), flush=True)


if __name__ == '__main__':
    if sys.argv[1:] == ['--synthetic']:
        result = synthetic()
        with (HERE / 'MATH_PREFLIGHT.json').open('x') as stream:
            json.dump(result, stream, indent=2)
            stream.write('\n')
        print(json.dumps(result, indent=2))
    elif not sys.argv[1:]:
        main()
    else:
        raise SystemExit('Only --synthetic or no argument is supported')
