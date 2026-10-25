"""Independent full-cohort replay, probability, selection and bootstrap verification.

No imports from experiment/, no model fitting and no temperature optimization.
The main supervisor uses separately implemented exact-subset math.
"""
import json
import math
from collections import defaultdict

import lightgbm as lgb
import numpy as np
import pandas as pd

import math_reference as ref
from preservation import HERE, STUDY, ROOT, sha, verify_prior

OUT = STUDY / 'experiment/outputs'
OLD = ROOT / 'jeju/research/20261022_tb_state_transfer_v1'
STYLE = ROOT / 'jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet'
EDGES = np.array([0, .00001, .00005, .0001, .00025, .0005, .001, .0025,
                  .005, .01, .025, .05, .1, .25, .5, .75, 1.])
MAP = {
    'set_nll': 'bottom3_set_nll', 'set_brier': 'bottom3_set_brier_sum',
    'runner_nll': 'runner_binary_logloss_mean', 'runner_brier': 'runner_binary_brier_mean',
    'bottom3_capture_count': 'bottom3_captured_count',
    'bottom3_precision_at3': 'bottom3_precision_at_3',
    'bottom3_exact_hit': 'exact_bottom3_set_match',
    'excluded_top3_count': 'top3_excluded_count', 'excluded_any_top3': 'any_top3_excluded',
    'excluded_winner': 'winner_excluded', 'all_top3_retained': 'all_top3_retained',
}
ERRORS = defaultdict(float)


def near(name, a, b, tol=1e-10):
    a, b = np.asarray(a, float), np.asarray(b, float)
    assert a.shape == b.shape and np.isfinite(a).all() and np.isfinite(b).all(), name
    error = float(np.max(np.abs(a - b))) if a.size else 0.
    ERRORS[name] = max(ERRORS[name], error)
    assert error <= tol, (name, error, tol)


def load_verified_inputs():
    audit = json.loads((STUDY / 'audit/SOURCE_AUDIT.json').read_text())
    assert audit['passed']
    for entry in audit['source_references']:
        path = (ROOT / entry['path']).resolve(strict=True)
        assert path.is_relative_to(ROOT)
        assert sha(path) == entry['sha256'] and path.stat().st_size == entry['bytes']
    old = json.loads((OLD / 'experiment/outputs/parameters.json').read_text())
    names = old['features']['S']
    data = pd.read_parquet(STYLE, columns=list(dict.fromkeys([
        'api_record_id', 'race_id', 'race_date', 'year', 'horse_number', 'finish_position',
        'field_n', 'history_cutoff', *old['features']['C']])))
    state_names = names[30:]
    state = pd.read_parquet(OLD / 'inputs/state_features.parquet', columns=['api_record_id', *state_names])
    assert data.api_record_id.is_unique and state.api_record_id.is_unique
    assert set(data.api_record_id) == set(state.api_record_id)
    data = data.merge(state, on='api_record_id', how='inner', validate='one_to_one')
    data = data.sort_values(['race_date', 'race_id', 'horse_number'], kind='mergesort').reset_index(drop=True)
    assert len(data) == 52155 and data.race_id.nunique() == 5206
    assert ((pd.to_datetime(data.race_date) - pd.to_datetime(data.history_cutoff)).dt.days == 2).all()
    raw_s = pd.read_parquet(OLD / 'experiment/outputs/candidate_oos_scores.parquet')
    raw_s = raw_s.loc[raw_s.arm.eq('S')].copy()
    return data, old, raw_s


def verify_models(data, old, parameters, raw_b, raw_s):
    names = old['features']['S']
    assert parameters['feature_names'] == names
    assert parameters['lightgbm_parameters'] == old['lightgbm_parameters']
    replay = []
    for year in (2024, 2025, 2026):
        old_meta = next(m for m in old['models'] if m['arm'] == 'S' and m['evaluation_year'] == year)
        new_meta = parameters['models'][str(year)]
        vocab = {c: sorted(data.loc[data.year.between(2017, year - 3), c].dropna().astype(str).unique())
                 for c in old['features']['categorical_columns']}
        assert vocab == old_meta['categorical_vocabulary'] == new_meta['categorical_vocabulary']
        assert new_meta['feature_names'] == names and new_meta['parameters'] == old['lightgbm_parameters']
        assert new_meta['max_rounds'] == 800 and new_meta['early_stopping_rounds'] == 25
        masks = {'initial_train': data.year.between(2017, year - 3),
                 'early_stop': data.year.eq(year - 2), 'refit': data.year.between(2017, year - 2),
                 'calibration': data.year.eq(year - 1), 'evaluation': data.year.eq(year)}
        for phase, mask in masks.items():
            assert new_meta['split_counts'][phase] == {'rows': int(mask.sum()), 'races': int(data.loc[mask, 'race_id'].nunique())}
        assert new_meta['refit_max'] < new_meta['calibration_min'] < new_meta['evaluation_min']
        for arm, model_path, raw, provider_col in (
            ('B', STUDY / 'experiment/models' / f'B_{year}.txt', raw_b, 'provider_year'),
            ('S', OLD / 'experiment/models' / f'S_{year}.txt', raw_s, 'year'),
        ):
            metadata = new_meta if arm == 'B' else old_meta
            assert sha(model_path) == metadata['model_sha256']
            model = lgb.Booster(model_file=str(model_path))
            assert model.feature_name() == names
            assert model.current_iteration() == metadata['best_iteration']
            assert model.pandas_categorical == [vocab[c] for c in names if c in vocab]
            for role, actual_year in (('calibration', year - 1), ('evaluation', year)):
                frame = data.loc[data.year.eq(actual_year)].copy()
                saved = raw.loc[raw[provider_col].eq(year) & raw.role.eq(role)].set_index('api_record_id')
                assert saved.index.is_unique and set(saved.index) == set(frame.api_record_id)
                x = frame[names].copy()
                for column, categories in vocab.items():
                    x[column] = pd.Categorical(x[column].astype('string'), categories=categories)
                predictions = model.predict(x, raw_score=True, num_threads=2)
                near(f'{arm}_raw_model_replay', predictions, saved.loc[frame.api_record_id, 'score'].to_numpy())
                aligned = saved.loc[frame.api_record_id]
                for key in ('race_id', 'race_date', 'horse_number', 'field_n'):
                    assert np.array_equal(aligned[key].to_numpy(), frame[key].to_numpy()), (arm, year, role, key)
                if arm == 'B':
                    assert (aligned.race_year == actual_year).all()
                    assert np.array_equal(aligned.finish_position.to_numpy(), frame.finish_position.to_numpy())
                replay.append({'arm': arm, 'provider_year': year, 'role': role, 'rows': len(frame),
                               'model_sha256': sha(model_path)})
    return replay


def verify_temperatures(data, parameters, raw_b, raw_s):
    checks = []
    for arm in ('L', 'B'):
        for year in (2024, 2025, 2026):
            source, provider_col = (raw_s, 'year') if arm == 'L' else (raw_b, 'provider_year')
            scores = source.loc[source[provider_col].eq(year) & source.role.eq('calibration')].set_index('api_record_id')
            frame = data.loc[data.year.eq(year - 1)].copy()
            frame['utility'] = scores.loc[frame.api_record_id, 'score'].to_numpy() * (-1 if arm == 'L' else 1)
            records = [(g.utility.to_numpy(), g.finish_position.to_numpy()) for _, g in frame.groupby('race_id', sort=True)]
            fitted = parameters['temperature_fits'][arm][str(year)]
            temperature = float(fitted['temperature'])
            assert .35 <= temperature <= 4 and fitted['races'] == len(records)
            check = ref.calibration_check(records, temperature)
            near('temperature_objective', check['objective_nll'], fitted['nll'])
            endpoints = {str(t): ref.calibration_check(records, t)['objective_nll'] for t in (.35, 4.)}
            for key, value in endpoints.items():
                near('temperature_endpoints', value, fitted['endpoint_objectives'][key])
            gradient = check['gradient_beta']
            assert check['hessian_beta'] > 0
            if temperature == .35:
                assert gradient <= 2e-6
            elif temperature == 4:
                assert gradient >= -2e-6
            else:
                assert abs(gradient) < 2e-6, (arm, year, gradient)
            assert check['objective_nll'] <= min(endpoints.values()) + 1e-10
            checks.append({'arm': arm, 'provider_year': year, 'calibration_year': year - 1,
                           'temperature': temperature, **check, 'endpoint_objectives': endpoints})
            print(json.dumps({'verified_temperature': f'{arm}/{year}', 'gradient_beta': gradient}), flush=True)
    return checks


def add_bins(bins, arm, year, kind, p, y):
    p, y = np.asarray(p, float), np.asarray(y, float)
    ix = np.clip(np.searchsorted(EDGES, p, side='right') - 1, 0, 15)
    counts = np.column_stack([np.bincount(ix, minlength=16),
                             np.bincount(ix, weights=p, minlength=16),
                             np.bincount(ix, weights=y, minlength=16),
                             np.bincount(ix, weights=(p - y) ** 2, minlength=16)])
    for period in ('ALL', str(year)):
        bins[(arm, kind, period)] += counts


def main():
    approval = json.loads((HERE / 'EXECUTION_APPROVAL.json').read_text())
    assert approval['status'] == 'PASS' and approval['fit_count'] == 6
    receipt = json.loads((OUT / 'fit_run_receipt.json').read_text())
    assert receipt['status'] == 'COMPLETED_RESEARCH_ONLY' and receipt['run_count'] == 1
    assert receipt['fit_count'] == receipt['calibration_count'] == 6
    assert receipt['approval_sha256'] == sha(HERE / 'EXECUTION_APPROVAL.json')
    parameters = json.loads((OUT / 'parameters.json').read_text())
    summary = json.loads((OUT / 'summary.json').read_text())
    assert summary['fit_count'] == summary['temperature_optimization_count'] == 6
    raw_b = pd.read_parquet(OUT / 'candidate_oos_scores.parquet')
    assert not raw_b.duplicated(['provider_year', 'role', 'api_record_id']).any()
    assert len(raw_b) == 36657
    data, old, raw_s = load_verified_inputs()
    replay = verify_models(data, old, parameters, raw_b, raw_s)
    temps = verify_temperatures(data, parameters, raw_b, raw_s)
    evaluation = data.loc[data.year.isin([2024, 2025, 2026])]
    assert len(evaluation) == 17412 and evaluation.race_id.nunique() == 1779
    saved_metrics = pd.read_parquet(OUT / 'race_metrics.parquet').set_index(['race_id', 'arm'])
    saved_runners = pd.read_parquet(OUT / 'runner_probabilities.parquet').set_index(['race_id', 'arm', 'horse_number'])
    assert saved_metrics.index.is_unique and saved_runners.index.is_unique
    assert len(saved_metrics) == 3558 and len(saved_runners) == 34824
    b_scores = raw_b.loc[raw_b.role.eq('evaluation')].set_index('api_record_id')
    s_scores = raw_s.loc[raw_s.role.eq('evaluation')].set_index('api_record_id')
    assert b_scores.index.is_unique and s_scores.index.is_unique
    assert set(b_scores.index) == set(s_scores.index) == set(evaluation.api_record_id)
    rows, bins, subset_count = [], defaultdict(lambda: np.zeros((16, 4))), 0
    for rid, group in evaluation.groupby('race_id', sort=True):
        g = group.sort_values('horse_number')
        year, n = int(g.year.iloc[0]), len(g)
        ranks, nums = g.finish_position.to_numpy(int), g.horse_number.to_numpy(int)
        assert n == g.field_n.iloc[0]
        for arm, utilities in [('L', -s_scores.loc[g.api_record_id, 'score'].to_numpy()),
                               ('B', b_scores.loc[g.api_record_id, 'score'].to_numpy())]:
            temperature = parameters['temperature_fits'][arm][str(year)]['temperature']
            values, p, marginal, chosen, truth = ref.metrics(utilities, temperature, ranks, nums)
            subset_count += len(p)
            saved = saved_metrics.loc[(rid, arm)]
            assert saved.race_date == g.race_date.iloc[0] and saved.year == year and saved.field_n == n
            translated = {MAP[k]: v for k, v in values.items()}
            translated['bottom3_recall_at_3'] = values['bottom3_precision_at3']
            for metric, value in translated.items():
                near('race_' + metric, value, saved[metric])
            assert list(saved.selected_bottom3_horse_numbers) == list(chosen)
            assert list(saved.actual_bottom3_horse_numbers) == list(nums[list(truth)])
            selected_indices = tuple(np.flatnonzero(np.isin(nums, chosen)))
            near('true_set_probability', p[truth], saved.true_bottom3_set_probability)
            near('selected_set_probability', p[selected_indices], saved.selected_bottom3_set_probability)
            runners = saved_runners.loc[[(rid, arm, number) for number in nums]]
            assert np.array_equal(runners.finish_position.to_numpy(), ranks)
            near('runner_marginals', marginal, runners.p_bottom3.to_numpy())
            add_bins(bins, arm, year, 'set', list(p.values()), [float(key == truth) for key in p])
            add_bins(bins, arm, year, 'runner', marginal, ranks >= n - 2)
            rows.append({'race_id': rid, 'race_date': g.race_date.iloc[0], 'year': year,
                         'field_n': n, 'arm': arm, **translated})
    reconstructed = pd.DataFrame(rows)
    stored_bins = pd.read_parquet(OUT / 'reliability_bins.parquet')
    assert len(stored_bins) == 256
    assert not stored_bins.duplicated(['arm', 'probability_kind', 'period', 'bin_index']).any()
    for row in stored_bins.itertuples(index=False):
        count, p_sum, y_sum, brier_sum = bins[(row.arm, row.probability_kind, row.period)][row.bin_index]
        assert row.event_count == count
        near('bin_edges', [row.bin_lower, row.bin_upper], EDGES[row.bin_index:row.bin_index + 2])
        if count:
            near('bin_averages', [row.mean_probability, row.observed_rate, row.mean_event_brier],
                 np.array([p_sum, y_sum, brier_sum]) / count)
        else:
            assert math.isnan(row.mean_probability) and math.isnan(row.observed_rate) and math.isnan(row.mean_event_brier)
    metrics = list(MAP.values()) + ['bottom3_recall_at_3']
    stored_periods = pd.read_parquet(OUT / 'period_summary.parquet')
    for row in stored_periods.to_dict('records'):
        part = reconstructed.loc[reconstructed.arm.eq(row['arm'])]
        if row['period'] != 'ALL':
            part = part.loc[part.year.eq(int(row['period']))]
        assert len(part) == row['races']
        for metric in metrics:
            near('period_' + metric, part[metric].mean(), row[metric])
    for grouping, key in [('year', 'year_summary'), ('field_n', 'field_size_summary')]:
        for row in summary[key]:
            part = reconstructed.loc[reconstructed.arm.eq(row['arm']) & reconstructed[grouping].eq(row[grouping])]
            assert len(part) == row['races']
            for metric in metrics:
                if metric in row:
                    near('stratum_' + metric, part[metric].mean(), row[metric])
    schedule = np.load(ROOT / 'jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy', allow_pickle=False)
    assert schedule.shape == (2000, 269)
    l = reconstructed.loc[reconstructed.arm.eq('L')].set_index('race_id').sort_index()
    b = reconstructed.loc[reconstructed.arm.eq('B')].set_index('race_id').sort_index()
    assert l.index.equals(b.index)
    dates = sorted(l.race_date.unique())
    import hashlib
    assert hashlib.sha256('\n'.join(dates).encode()).hexdigest() == 'e4aa73b866eac00b361d0354fdd62b7b2bd98915e003f250adc40a8df0a66b84'
    daily_count = l.groupby('race_date').size().reindex(dates).to_numpy()
    denominator = daily_count[schedule].sum(axis=1)
    saved_draws = pd.read_parquet(OUT / 'comparison_bootstrap_draws.parquet')
    assert len(saved_draws) == 2000 * len(metrics)
    comparisons = {}
    for metric in metrics:
        delta = b[metric] - l[metric]
        daily_delta = delta.groupby(l.race_date).sum().reindex(dates).to_numpy()
        draws = daily_delta[schedule].sum(axis=1) / denominator
        stored = saved_draws.loc[saved_draws.metric.eq(metric)].sort_values('draw')
        assert stored.draw.to_list() == list(range(2000))
        near('bootstrap_' + metric, draws, stored.difference_B_minus_L.to_numpy())
        point, interval = float(delta.mean()), np.quantile(draws, [.025, .975])
        reported = summary['paired_date_bootstrap'][metric]
        near('bootstrap_point', point, reported['point_difference_B_minus_L'])
        near('bootstrap_interval', interval, reported['bootstrap_ci95'])
        near('point_differences', point, summary['arm_point_differences_B_minus_L'][metric])
        comparisons[metric] = {'L': float(l[metric].mean()), 'B': float(b[metric].mean()),
                               'B_minus_L': point, 'ci95': interval.tolist()}
    prediction_gate = bool(comparisons['bottom3_set_nll']['ci95'][1] < 0 and all(
        comparisons[m]['B_minus_L'] <= 0 for m in ('bottom3_set_brier_sum', 'runner_binary_logloss_mean', 'runner_binary_brier_mean')))
    exclusion_gate = bool(prediction_gate and all(comparisons[m]['B_minus_L'] <= 0
                                                  for m in ('any_top3_excluded', 'winner_excluded')))
    assert prediction_gate == summary['prediction_research_candidate_gate_pass'] == receipt['prediction_research_candidate_gate_pass']
    assert exclusion_gate == summary['exclusion_auxiliary_candidate_gate_pass'] == receipt['exclusion_auxiliary_candidate_gate_pass']
    pins = verify_prior()
    output = {'passed': True, 'method': 'Independent subset enumeration with math.fsum; saved model replay; inverse-temperature convex derivative; direct date schedule indexing',
              'model_fit_calls': 0, 'temperature_optimization_calls': 0,
              'prediction_followup_gate_pass': prediction_gate, 'exclusion_followup_gate_pass': exclusion_gate,
              'evaluation_races': 1779, 'evaluation_runners_per_arm': 17412,
              'all_subset_events_reconstructed': subset_count, 'race_metric_rows_verified': len(reconstructed),
              'runner_marginals_verified': len(saved_runners), 'reliability_rows_verified': len(stored_bins),
              'bootstrap_draws_verified': len(saved_draws), 'raw_model_replays': replay,
              'temperature_checks': temps, 'comparisons': comparisons, 'maximum_errors': dict(ERRORS),
              'preserved_files_verified': len(pins), 'verifier_sha256': sha(HERE / 'verify_results.py'),
              'math_sha256': sha(HERE / 'math_reference.py'), 'input_approval_sha256': sha(HERE / 'EXECUTION_APPROVAL.json')}
    for name in ('candidate_oos_scores.parquet', 'race_metrics.parquet', 'runner_probabilities.parquet',
                 'reliability_bins.parquet', 'comparison_bootstrap_draws.parquet', 'parameters.json', 'summary.json'):
        item = receipt['artifacts'][name]
        assert item['sha256'] == sha(OUT / name) and item['bytes'] == (OUT / name).stat().st_size
    with (HERE / 'RESULT_VERIFICATION.json').open('x') as stream:
        json.dump(output, stream, indent=2, ensure_ascii=False)
        stream.write('\n')
    print(json.dumps({'passed': True, 'prediction_gate': prediction_gate, 'exclusion_gate': exclusion_gate,
                      'all_subset_events': subset_count, 'comparisons': comparisons}, indent=2), flush=True)


if __name__ == '__main__':
    main()
