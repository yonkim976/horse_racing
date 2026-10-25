"""Exhaustive independent replay of the frozen one-temperature comparison."""
import argparse
import hashlib
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

sys.dont_write_bytecode = True
from math_reference import (aggregate, inverse_temperature_derivatives,
                            reference_distribution, score_events, synthetic, winners)

ROOT = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parent
EXP = HERE.parent / 'experiment'
OUT = EXP / 'outputs'
STYLE = ROOT / 'jeju/research/20261010_style_history_ablation_v1/outputs'
HIST = ROOT / 'jeju/research/20261011_pair_top3_oos_expansion_v1/outputs'
EDGES = np.array([0, .00001, .00005, .0001, .00025, .0005, .001, .0025,
                  .005, .01, .025, .05, .1, .25, .5, .75, 1.])


def sha(p):
    h = hashlib.sha256()
    with p.open('rb') as handle:
        for b in iter(lambda: handle.read(1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def main(check_only=False):
    maxima = defaultdict(float)
    checks = defaultdict(int)

    def near(name, actual, expected, tol=2e-10):
        error = float(np.max(np.abs(np.asarray(actual, dtype=float) - np.asarray(expected, dtype=float))))
        assert error <= tol, (name, error, actual, expected)
        maxima[name] = max(maxima[name], error)
        checks[name] += 1

    source = json.loads((HERE / 'SOURCE_REVIEW.json').read_text())
    for item in source['sources']:
        assert sha(ROOT / item['path']) == item['sha256']
    fit_receipt = json.loads((OUT / 'fit_receipt.json').read_text())
    report = json.loads((OUT / 'report.json').read_text())
    temperature = fit_receipt['fit']['temperature']
    assert .35 <= temperature <= 4
    assert report['fit']['temperature'] == temperature
    assert sha(EXP / 'baseline.py') == report['code_sha256']
    assert sha(EXP / 'PLAN.md') == report['plan_sha256']
    features = pd.read_parquet(STYLE / 'features.parquet', columns=[
        'api_record_id', 'race_id', 'race_date', 'year', 'horse_number', 'finish_position', 'field_n'])

    def races(year, role):
        fold = year + 1 if role == 'calibration' else year
        folder = (HIST if fold < 2024 else STYLE) / f'F1_STYLE6_{fold}'
        score = pd.read_parquet(folder / f'{role}_scores.parquet')
        joined = features.loc[features.year.eq(year)].merge(score, on='api_record_id', validate='one_to_one')
        for race_id, g in joined.groupby('race_id', sort=True):
            g = g.sort_values('horse_number')
            actual = tuple(int(np.flatnonzero(g.finish_position.to_numpy() == i)[0]) for i in (1, 2, 3))
            yield race_id, g, actual

    cal = []
    for year in range(2019, 2024):
        for _, g, actual in races(year, 'calibration'):
            cal.append((g.score.to_numpy(), actual))
    assert len(cal) == 2492
    derivative = inverse_temperature_derivatives(cal, temperature)
    near('calibration_nll', derivative['nll'], fit_receipt['fit']['objective_nll'])
    assert derivative['hessian_inverse_t'] > 0
    if .35 + 1e-7 < temperature < 4 - 1e-7:
        assert abs(derivative['gradient_inverse_t']) < 2e-6, derivative
    elif temperature == .35:
        assert derivative['gradient_inverse_t'] <= 2e-6
    elif temperature == 4:
        assert derivative['gradient_inverse_t'] >= -2e-6
    else:
        raise AssertionError('unresolved boundary optimum')

    metrics = pd.read_parquet(OUT / 'race_metrics.parquet').set_index(['pool', 'race_id', 'arm'])
    selected = pd.read_parquet(OUT / 'selected_ticket_ledger.parquet').set_index(['pool', 'race_id', 'arm'])
    runner = pd.read_parquet(OUT / 'runner_marginals.parquet').set_index(['race_id', 'arm', 'horse_number'])
    assert metrics.index.is_unique and selected.index.is_unique and runner.index.is_unique
    assert len(metrics) == len(selected) == 24834 and len(runner) == 34824
    generated = []
    bins = defaultdict(lambda: np.zeros((len(EDGES) - 1, 4)))
    choice_rounding_ties = []
    triple_count = 0
    for year in range(2024, 2027):
        for race_id, g, actual in races(year, 'evaluation'):
            n = len(g)
            numbers = g.horse_number.to_numpy()
            for arm, temp in [('T1', 1.), ('TEMP', temperature)]:
                joint = reference_distribution(g.score.to_numpy(), temp)
                triple_count += len(joint)
                plc = 3 if n >= 8 else None
                pools, ranks = aggregate(joint, n, plc)
                for i, number in enumerate(numbers):
                    row = runner.loc[(race_id, arm, number)]
                    near('runner_marginals', row[['p_win', 'p_exact2', 'p_exact3', 'p_top2', 'p_top3']].to_numpy(float),
                         [ranks[i, 0], ranks[i, 1], ranks[i, 2], sum(ranks[i, :2]), sum(ranks[i])])
                for pool, probs in pools.items():
                    if pool == 'PLC' and plc is None:
                        assert (pool, race_id, arm) not in metrics.index
                        continue
                    calc, keys, p, y = score_events(pool, probs, actual, plc)
                    key = (pool, race_id, arm)
                    row = metrics.loc[key]
                    near('race_nll', row.race_nll, calc['log_loss'])
                    near('race_brier', row.race_brier, calc['brier'])
                    assert int(row.ticket_count) == len(keys) and int(row.event_count) == int(y.sum())
                    truth = winners(pool, actual, plc)
                    truth_keys = sorted(truth)
                    truth_ps = [probs[k] for k in truth_keys]
                    near('realized_probability_mean', row.realized_event_p_mean, np.mean(truth_ps))
                    near('realized_nll_mean', row.realized_event_nll_mean, np.mean([-math.log(max(x, 1e-15)) for x in truth_ps]))
                    sr = selected.loc[key]
                    chosen = tuple(int(numbers[i]) for i in calc['selected_key'])
                    saved_choice = tuple(json.loads(sr.selected_ticket_key))
                    if saved_choice != chosen:
                        saved_indices = tuple(int(np.flatnonzero(numbers == horse)[0]) for horse in saved_choice)
                        near('selection_rounding_tie_probability', probs[saved_indices], calc['selected_probability'], 2e-14)
                        choice_rounding_ties.append(dict(pool=pool, race_id=race_id, arm=arm,
                                                        independent=chosen, saved=saved_choice))
                    near('selected_probability', sr.selected_probability, calc['selected_probability'])
                    saved_index = tuple(int(np.flatnonzero(numbers == horse)[0]) for horse in saved_choice)
                    assert bool(sr.selected_hit) == (saved_index in truth)
                    near('realized_probabilities', json.loads(sr.realized_event_probabilities_json), truth_ps)
                    expected_truth_keys = [[int(numbers[i]) for i in k] for k in truth_keys]
                    assert json.loads(sr.realized_event_keys_json) == expected_truth_keys
                    bin_id = np.minimum(np.maximum(np.searchsorted(EDGES, p, side='right') - 1, 0), len(EDGES) - 2)
                    for bi in range(len(EDGES) - 1):
                        m = bin_id == bi
                        bins[(pool, arm)][bi] += [int(m.sum()), float(p[m].sum()), float(y[m].sum()), float(((p[m] - y[m]) ** 2).sum())]
                    generated.append(dict(pool=pool, arm=arm, race_id=race_id, race_date=g.race_date.iloc[0], year=year,
                                          race_nll=calc['log_loss'], race_brier=calc['brier'],
                                          selected_hit=int(sr.selected_hit), ticket_count=len(keys), event_count=int(y.sum())))
        print(f'independent replay finished year {year}', flush=True)

    gen = pd.DataFrame(generated)
    bin_frame = pd.read_parquet(OUT / 'reliability_bins.parquet')
    for row in bin_frame.itertuples():
        values = bins[(row.pool, row.arm)][row.bin_index]
        assert row.event_count == int(values[0])
        if values[0]:
            near('reliability_bin', [row.mean_probability, row.observed_rate, row.mean_event_brier], values[1:] / values[0])
        else:
            assert pd.isna(row.mean_probability) and pd.isna(row.observed_rate)
    for filename, by in [('pool_summary.parquet', ['pool', 'arm']), ('pool_year_summary.parquet', ['pool', 'arm', 'year'])]:
        summary = pd.read_parquet(OUT / filename).set_index(by)
        for k, group in gen.groupby(by):
            row = summary.loc[k]
            assert row.races == len(group)
            near('summary_nll_brier', [row.mean_race_nll, row.mean_race_brier], [group.race_nll.mean(), group.race_brier.mean()])
            assert row.total_ticket_events == group.ticket_count.sum()
            assert row.realized_events == group.event_count.sum()
    schedule_path = ROOT / 'jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy'
    schedule = np.load(schedule_path, allow_pickle=False)
    tri = gen.loc[gen.pool.eq('TRI')].pivot(index=['race_id', 'race_date'], columns='arm', values=['race_nll', 'race_brier'])
    diff = tri[('race_nll', 'TEMP')] - tri[('race_nll', 'T1')]
    date_stats = diff.groupby(level='race_date').agg(['sum', 'count']).sort_index()
    samples = date_stats['sum'].to_numpy()[schedule].sum(axis=1) / date_stats['count'].to_numpy()[schedule].sum(axis=1)
    ci = np.quantile(samples, [.025, .975])
    near('primary_bootstrap_ci', report['primary']['nll_difference_ci95'], ci)
    near('primary_point', report['primary']['point_candidate_minus_t1_race_equal_nll'], diff.mean())
    brier_delta = (tri[('race_brier', 'TEMP')] - tri[('race_brier', 'T1')]).mean()
    gate = bool(ci[1] < 0 and brier_delta <= 0)
    assert gate == report['primary']['gate_pass']
    for pool, group in gen.groupby('pool'):
        wide = group.pivot(index='race_id', columns='arm', values=['race_nll', 'race_brier', 'selected_hit'])
        for metric, suffix in [('race_nll', 'mean_race_nll'), ('race_brier', 'mean_race_brier')]:
            near('pool_point_differences', report['pool_comparisons'][pool]['candidate_minus_t1_' + suffix],
                 (wide[(metric, 'TEMP')] - wide[(metric, 'T1')]).mean())
        for arm, field in [('T1', 't1_selected_hit_count'), ('TEMP', 'temp_selected_hit_count')]:
            assert int(wide[('selected_hit', arm)].sum()) == report['selection_diagnostics'][pool][field]
    quarantine = pd.read_parquet(OUT / 'evaluation_quarantine.parquet')
    expected_q = set(features.loc[features.year.between(2024, 2026) & features.field_n.eq(7), 'race_id'])
    assert set(quarantine.race_id) == expected_q and len(quarantine) == 36
    assert quarantine.pool.eq('PLC').all()
    for item in json.loads((HERE / 'SESSION_START.json').read_text())['sources']:
        assert sha(ROOT / item['path']) == item['sha256']
    for item in json.loads((HERE / 'MODEL_REFERENCES.json').read_text())['references']:
        assert sha(ROOT / item['path']) == item['sha256']
    result = dict(passed=True, calibration_races=2492, evaluation_races=1779,
                  evaluated_metric_rows=len(gen), runner_marginal_rows=len(runner),
                  ordered_triples_recomputed=triple_count, primary_gate_pass=gate,
                  calibration_derivatives=derivative, primary_ci95=ci.tolist(),
                  synthetic=synthetic(), max_absolute_errors=dict(maxima),
                  check_counts=dict(checks), choice_rounding_ties=choice_rounding_ties,
                  experiment_code_imported=False, model_refit_performed=False,
                  original_source_and_protected_production_hashes_unchanged=True)
    if not check_only:
        with (HERE / 'RESULT_REVIEW.json').open('x') as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2)
            handle.write('\n')
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-only', action='store_true', help='Recheck existing artifacts without writing any files.')
    main(parser.parse_args().check_only)
