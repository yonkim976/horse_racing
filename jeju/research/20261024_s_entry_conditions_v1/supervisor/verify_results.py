"""Independent saved-model replay and complete event scoring; no model fitting.

Only an earlier sealed supervisor's math is reused. The new experiment module
is never imported. Audit input is read from the unique compact feature table.
"""
import importlib.util
import itertools
import json
import sys
from collections import defaultdict
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
STUDY = HERE.parent
OUT = STUDY / 'experiment/outputs'
OLD = ROOT / 'jeju/research/20261022_tb_state_transfer_v1'
spec = importlib.util.spec_from_file_location('_preservation', HERE / 'preservation.py')
preservation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preservation)
preservation.verify_prior()
spec = importlib.util.spec_from_file_location('_prior_independent_verifier', OLD / 'supervisor/verify_results.py')
v = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v)
near, ref = v.near, v.ref


def main():
    par = json.loads((OUT / 'parameters.json').read_text())
    receipt = json.loads((OUT / 'fit_run_receipt.json').read_text())
    expected_budget = {'candidate_final_models': 3, 'candidate_LightGBM_train_calls': 6,
                       'candidate_PL_temperature_optimizations': 3,
                       'S_fit_calls': 0, 'S_temperature_optimizations': 0}
    assert par['fit_budget'] == receipt['fit_counts'] == expected_budget
    assert receipt['approval_sha256'] == preservation.sha(HERE / 'ENTRY_CONDITIONS_EXECUTION_APPROVAL.json')
    oldpar = json.loads((OLD / 'experiment/outputs/parameters.json').read_text())
    features = par['features']
    assert features['S'] == oldpar['features']['S'] and features['E'][:40] == features['S']
    assert len(features['E']) == 43
    added = features['E'][40:]
    candidates = []
    for p in (STUDY / 'audit').glob('*.parquet'):
        f = pd.read_parquet(p)
        if set(added).issubset(f.columns):
            candidates.append((p, f))
    assert len(candidates) == 1
    input_path, entry = candidates[0]
    data = pd.read_parquet(ROOT / 'jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet')
    states = pd.read_parquet(OLD / 'inputs/state_features.parquet')
    data = data.merge(states[['api_record_id', *features['S'][30:]]], on='api_record_id', validate='one_to_one')
    data = data.merge(entry[['api_record_id', *added]], on='api_record_id', validate='one_to_one')
    data['race_date'] = pd.to_datetime(data.race_date).dt.strftime('%Y-%m-%d')
    data = data.sort_values(['race_date', 'race_id', 'horse_number'], kind='stable').reset_index(drop=True)
    assert len(data) == 52155 and data.race_id.nunique() == 5206
    new_oos = pd.read_parquet(OUT / 'candidate_oos_scores.parquet')
    old_oos = pd.read_parquet(OLD / 'experiment/outputs/candidate_oos_scores.parquet')
    oos = pd.concat([old_oos.loc[old_oos.arm.eq('S')], new_oos.loc[new_oos.arm.eq('E')]], ignore_index=True)
    assert not oos.duplicated(['arm', 'year', 'role', 'api_record_id']).any()
    fits = [m for m in oldpar['models'] if m['arm'] == 'S'] + [m for m in par['models'] if m['arm'] == 'E']
    assert {(m['arm'], int(m['year'])) for m in fits} == set(itertools.product(('S', 'E'), (2024, 2025, 2026)))
    temperatures = {}; replayed = 0; calibrations = []
    for m in fits:
        arm, year = m['arm'], int(m['year'])
        assert m['parameters'] == oldpar['lightgbm_parameters']
        assert m['max_rounds'] == 800 and m['early_stopping_rounds'] == 25
        initial = data.loc[data.year.between(2017, year - 3)]
        vocab = {c: sorted(initial[c].dropna().astype(str).unique().tolist()) for c in oldpar['features']['categorical_columns']}
        assert vocab == m['categorical_vocabulary']
        path = (OLD if arm == 'S' else STUDY) / f'experiment/models/{arm}_{year}.txt'
        assert preservation.sha(path) == m['model_sha256']
        model = lgb.Booster(model_file=str(path))
        assert model.feature_name() == features[arm] and model.current_iteration() == m['best_iteration']
        for role, target_year in [('calibration', year - 1), ('evaluation', year)]:
            target = data.loc[data.year.eq(target_year)]
            saved = oos.loc[oos.arm.eq(arm) & oos.year.eq(year) & oos.role.eq(role)].set_index('api_record_id')
            assert len(saved) == len(target) and set(saved.index) == set(target.api_record_id)
            saved = saved.loc[target.api_record_id]
            x = target[features[arm]].copy()
            for c, cats in vocab.items():
                x[c] = pd.Categorical(x[c].astype('string'), categories=cats)
            raw = model.predict(x, raw_score=True, num_threads=2)
            near('raw_model_replay', raw, saved.score)
            assert np.array_equal(saved.race_id, target.race_id)
            replayed += len(raw)
            if role == 'calibration':
                t = m['temperature_fit']['temperature']
                loss, gradient, hessian = v.calibration(target, raw, t)
                near('temperature_objective', loss, m['temperature_fit']['objective_nll'])
                v.optimum(t, gradient); assert hessian > 0
                for bound, key in [(.35, 'lower_bound_objective'), (4., 'upper_bound_objective')]:
                    value, _, _ = v.calibration(target, raw, bound)
                    near('temperature_bound_objective', value, m['temperature_fit'][key])
                temperatures[(arm, year)] = t
                calibrations.append({'arm': arm, 'year': year, 'temperature': t, 'gradient': gradient})
    print(json.dumps({'phase': 'model_replay_pass', 'raw_values': replayed}), flush=True)
    metrics = pd.read_parquet(OUT / 'race_pool_metrics.parquet').set_index(['race_id', 'arm', 'pool'])
    selections = pd.read_parquet(OUT / 'selected_ticket_ledger.parquet').set_index(['race_id', 'arm', 'pool'])
    margins = pd.read_parquet(OUT / 'evaluation_runner_marginals.parquet').set_index(['race_id', 'arm', 'horse_number'])
    axis = pd.read_parquet(OUT / 'win_axis_ledger.parquet').set_index(['race_id', 'arm'])
    pairs = pd.read_parquet(OUT / 'pair_selection_diagnostics.parquet').set_index(['race_id', 'arm', 'pool', 'k'])
    assert len(metrics) == len(selections) == 24834 and len(margins) == 34824 and len(axis) == 3558
    assert metrics.index.is_unique and pairs.index.is_unique
    raw_eval = oos.loc[oos.role.eq('evaluation')].set_index(['arm', 'api_record_id'])
    bins = defaultdict(lambda: np.zeros((16, 4))); rows = []; triples = 0
    for rid, g in data.loc[data.year.ge(2024)].groupby('race_id', sort=True):
        g = g.sort_values('horse_number'); numbers = g.horse_number.to_numpy(int); n = len(g)
        actual = tuple(np.argsort(g.finish_position.to_numpy())[:3]); year = int(g.year.iloc[0]); plc = 3 if n >= 8 else None
        for arm in ('S', 'E'):
            raw = raw_eval.xs(arm).loc[g.api_record_id, 'score'].to_numpy()
            joint = ref.distribution(raw, temperatures[(arm, year)]); triples += len(joint)
            pools, rank = ref.aggregate(joint, n, plc)
            for pool, probs in pools.items():
                if pool == 'PLC' and plc is None: continue
                metric, keys, p, y = ref.score_events(pool, probs, actual, plc)
                saved = metrics.loc[(rid, arm, pool)]
                near('pool_nll', metric['log_loss'], saved.race_nll)
                near('pool_brier', metric['brier'], saved.race_brier)
                assert saved.ticket_count == len(keys) and saved.event_count == y.sum()
                key, probability = ref.stable_selection(probs); selected = selections.loc[(rid, arm, pool)]
                assert json.loads(selected.selected_ticket_key) == [int(numbers[i]) for i in key]
                assert bool(selected.selected_hit) == (key in ref.winners(pool, actual, plc))
                near('selection_probability', probability, selected.selected_probability)
                indices = np.minimum(np.searchsorted(v.EDGES, p, side='right') - 1, 15)
                accum = np.column_stack([np.bincount(indices, minlength=16), np.bincount(indices, weights=p, minlength=16),
                                         np.bincount(indices, weights=y, minlength=16), np.bincount(indices, weights=(p-y)**2, minlength=16)])
                for period in ('ALL', str(year)): bins[(pool, arm, period)] += accum
                rows.append({'race_id': rid, 'race_date': g.race_date.iloc[0], 'year': year, 'arm': arm, 'pool': pool,
                             'nll': metric['log_loss'], 'brier': metric['brier']})
            for i, number in enumerate(numbers):
                m = margins.loc[(rid, arm, int(number))]
                near('runner_marginals', [*rank[i], rank[i, :2].sum(), rank[i].sum()],
                     m[['p_win', 'p_exact2', 'p_exact3', 'p_top2', 'p_top3']].to_numpy(float))
            key, prob = ref.stable_selection(pools['WIN']); ax = axis.loc[(rid, arm)]
            assert ax.selected_horse_number == numbers[key[0]] and bool(ax.selected_hit_top3) == (key[0] in actual)
            for pool in ('QNL', 'QPL'):
                truth = ref.winners(pool, actual, plc); chosen3 = v.top_keys(pools[pool], 3)
                for k in (1, 3):
                    chosen = chosen3[:k]; chosen_set = set(chosen); mass = np.zeros(4)
                    for order, q in joint.items():
                        realized = ({tuple(sorted(order[:2]))} if pool == 'QNL' else set(itertools.combinations(sorted(order), 2)))
                        mass[len(chosen_set & realized)] += q
                    saved = pairs.loc[(rid, arm, pool, k)]
                    assert json.loads(saved.selected_tickets_json) == [[int(numbers[i]) for i in key] for key in chosen]
                    near('pair_count_distribution', mass, saved[[f'count_probability_{i}' for i in range(4)]].to_numpy(float))
                    near('pair_union', sum(mass[1:]), saved.selected_union_probability)
                    assert int(saved.realized_hit_count) == len(chosen_set & truth)
    reliability = pd.read_parquet(OUT / 'reliability_bins.parquet')
    for row in reliability.itertuples(index=False):
        count, sp, sy, sb = bins[(row.pool, row.arm, str(row.evaluation_period))][row.bin_index]
        assert row.ticket_events == count
        if count: near('reliability', [sp/count, sy/count, sb/count], [row.mean_probability, row.observed_event_rate, row.mean_ticket_brier])
    checked = pd.DataFrame(rows)
    schedule = np.load(ROOT / 'jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy', allow_pickle=False)
    dates = sorted(checked.race_date.unique()); assert len(dates) == 269 and schedule.shape == (2000, 269)
    def compare(frame, field):
        matrix = frame.pivot(index=['race_id', 'race_date'], columns='arm', values=field).astype(float)
        delta = matrix.E - matrix.S
        daily = delta.groupby(level='race_date').agg(['sum', 'count']).loc[dates]
        draws = daily['sum'].to_numpy()[schedule].sum(axis=1) / daily['count'].to_numpy()[schedule].sum(axis=1)
        return {'S_mean': float(matrix.S.mean()), 'E_mean': float(matrix.E.mean()), 'difference': float(delta.mean()),
                'ci95': np.quantile(draws, [.025, .975]).tolist()}, draws
    tri, draws = compare(checked.loc[checked.pool.eq('TRI')], 'nll')
    saved_draws = pd.read_parquet(OUT / 'comparison_bootstrap_draws.parquet')
    near('tri_bootstrap', draws, saved_draws.sort_values('draw').tri_nll_difference)
    tb, _ = compare(checked.loc[checked.pool.eq('TRI')], 'brier')
    wn, _ = compare(checked.loc[checked.pool.eq('WIN')], 'nll'); wb, _ = compare(checked.loc[checked.pool.eq('WIN')], 'brier')
    gate = tri['ci95'][1] < 0 and tb['difference'] <= 0 and wn['difference'] <= 0 and wb['difference'] <= 0
    report = json.loads((OUT / 'report.json').read_text())
    assert report['overall_research_candidate_gate_pass'] == gate
    axis_result, _ = compare(axis.reset_index(), 'selected_hit_top3')
    pair_results = {}
    for pool in ('QNL', 'QPL'):
        f = pairs.reset_index().loc[lambda x: x.pool.eq(pool) & x.k.eq(3)].copy(); f['hit_any'] = f.realized_hit_count.gt(0)
        pair_results[pool], _ = compare(f, 'hit_any')
    for filename, groups in [('pool_summary.parquet', ['pool', 'arm']), ('pool_year_summary.parquet', ['pool', 'arm', 'year'])]:
        saved = pd.read_parquet(OUT / filename).set_index(groups)
        agg = checked.groupby(groups).agg(races=('race_id', 'nunique'), nll=('nll', 'mean'), brier=('brier', 'mean'))
        near('summary_nll', agg.nll, saved.loc[agg.index].mean_race_nll)
        near('summary_brier', agg.brier, saved.loc[agg.index].mean_race_brier)
        near('summary_denominator', agg.races, saved.loc[agg.index].races)
    preservation.verify_prior()
    result = {'passed': True, 'model_files_replayed': 6, 'raw_predictions_replayed': replayed, 'calibrations': calibrations,
              'ordered_triples_reconstructed': triples, 'metric_rows_checked': len(metrics), 'marginal_rows_checked': len(margins),
              'pair_rows_checked': len(pairs), 'reliability_rows_checked': len(reliability), 'tri_bootstrap_draws': 2000,
              'tri_nll': tri, 'tri_brier': tb, 'win_nll': wn, 'win_brier': wb, 'research_gate_pass': gate,
              'axis_top3': axis_result, 'pair_top3_tickets': pair_results, 'maximum_errors': dict(v.ERRORS),
              'input_sha256': preservation.sha(input_path), 'verifier_sha256': preservation.sha(Path(__file__)),
              'experiment_module_imported': False, 'models_refitted': False, 'protected_prior_files_unchanged': True}
    assert set(sys.argv[1:]).issubset({'--check-only'}), 'Only --check-only is supported'
    if '--check-only' not in sys.argv[1:]:
        with (HERE / 'RESULT_VERIFICATION.json').open('x') as f: json.dump(result, f, indent=2)
    print(json.dumps(result, indent=2), flush=True)


if __name__ == '__main__': main()
