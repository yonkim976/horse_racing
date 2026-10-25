"""Independent exhaustive verification of rank-stage results, without refitting."""
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
from math_reference import (aggregate, reference_distribution, score_events,
                            stable_selection, stage_derivatives, synthetic, winners)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
STUDY = HERE.parent
OUT = STUDY / 'experiment/outputs'
OLD = STUDY.parent / '20261022_joint_wager_baseline_v1'
STYLE = ROOT / 'jeju/research/20261010_style_history_ablation_v1/outputs'
HISTORY = ROOT / 'jeju/research/20261011_pair_top3_oos_expansion_v1/outputs'
EDGES = np.array([0, .00001, .00005, .0001, .00025, .0005, .001, .0025,
                  .005, .01, .025, .05, .1, .25, .5, .75, 1.])
COMMON = 1.1837152381349905


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def main(check_only=False):
    maximum_errors = defaultdict(float)
    check_counts = defaultdict(int)

    def near(name, actual, expected, tol=2e-10):
        difference = float(np.max(np.abs(np.asarray(actual, dtype=float) - np.asarray(expected, dtype=float))))
        assert difference <= tol, (name, difference, actual, expected)
        maximum_errors[name] = max(maximum_errors[name], difference)
        check_counts[name] += 1

    for item in json.loads((HERE / 'SOURCE_REVIEW.json').read_text())['references']:
        assert sha(ROOT / item['path']) == item['sha256'], item['path']
    old_manifest = json.loads((OLD / 'FINAL_MANIFEST.json').read_text())
    for item in old_manifest['files']:
        assert sha(OLD / item['path']) == item['sha256'], item['path']
    report = json.loads((OUT / 'report.json').read_text())
    receipt = json.loads((OUT / 'fit_receipt.json').read_text())
    temps = tuple(report['fit']['temperatures'])
    assert receipt['fit']['temperatures'] == list(temps)
    assert len(temps) == 3 and all(.35 <= t <= 4 for t in temps)
    assert receipt['run_count'] == receipt['successful_evaluation_passes'] == 1
    assert report['code_sha256'] == sha(STUDY / 'experiment/rank_stage.py')
    assert report['plan_sha256'] == sha(STUDY / 'experiment/PLAN.md')
    assert report['source_preflight_sha256'] == sha(OUT / 'source_preflight.json')
    assert report['approval']['sha256'] == sha(HERE / 'RANK_STAGE_EXECUTION_APPROVAL.json')
    features = pd.read_parquet(STYLE / 'features.parquet', columns=[
        'api_record_id', 'race_id', 'race_date', 'year', 'horse_number', 'finish_position', 'field_n'])

    def races(year, role):
        fold = year + 1 if role == 'calibration' else year
        folder = (HISTORY if fold < 2024 else STYLE) / f'F1_STYLE6_{fold}'
        scores = pd.read_parquet(folder / f'{role}_scores.parquet')
        joined = features.loc[features.year.eq(year)].merge(scores, on='api_record_id', validate='one_to_one')
        for race_id, group in joined.groupby('race_id', sort=True):
            group = group.sort_values('horse_number')
            actual = tuple(int(np.flatnonzero(group.finish_position.to_numpy() == i)[0]) for i in (1, 2, 3))
            yield race_id, group, actual

    calibration = [(group.score.to_numpy(), actual) for year in range(2019, 2024)
                   for _, group, actual in races(year, 'calibration')]
    assert len(calibration) == 2492
    derivatives = stage_derivatives(calibration, temps)
    common_derivatives = stage_derivatives(calibration, [COMMON] * 3)
    for i, (value, common, saved) in enumerate(zip(derivatives, common_derivatives, report['fit']['stages'])):
        near('stage_fit_nll', saved['objective_mean_conditional_nll'], value['nll'])
        near('stage_common_fit_nll', saved['common_T_training_mean_conditional_nll'], common['nll'])
        diag = saved['inverse_temperature_objective_diagnostics']
        near('inverse_temperature_diagnostics', [diag['mean_gradient'], diag['mean_hessian']],
             [value['gradient_inverse_t'], value['hessian_inverse_t']])
        assert value['nll'] <= common['nll'] + 1e-10 and value['hessian_inverse_t'] > 0
        if .35 + 1e-7 < temps[i] < 4 - 1e-7:
            assert abs(value['gradient_inverse_t']) < 2e-6
        elif temps[i] == .35:
            assert value['gradient_inverse_t'] <= 2e-6
        elif temps[i] == 4:
            assert value['gradient_inverse_t'] >= -2e-6
        else:
            raise AssertionError('Unresolved boundary optimum')

    candidate = pd.read_parquet(OUT / 'candidate_race_metrics.parquet').set_index(['pool', 'race_id'])
    runners = pd.read_parquet(OUT / 'candidate_runner_marginals.parquet').set_index(['race_id', 'horse_number'])
    selected = pd.read_parquet(OUT / 'selection_ledger.parquet').set_index(['pool', 'race_id', 'arm'])
    assert candidate.index.is_unique and runners.index.is_unique and selected.index.is_unique
    assert len(candidate) == 12417 and len(runners) == 17412 and len(selected) == 37251
    old = pd.read_parquet(OLD / 'experiment/outputs/race_metrics.parquet').set_index(['pool', 'race_id', 'arm'])
    generated = []
    bins = defaultdict(lambda: np.zeros((len(EDGES) - 1, 4)))
    total_triples = 0
    for year in range(2024, 2027):
        for race_id, group, actual in races(year, 'evaluation'):
            n = len(group)
            numbers = group.horse_number.to_numpy()
            plc = 3 if n >= 8 else None
            for arm, temperature in [('CANDIDATE', temps), ('COMMON', [COMMON] * 3), ('RAW_T1', [1.] * 3)]:
                joint = reference_distribution(group.score.to_numpy(), temperature)
                total_triples += len(joint)
                pools, ranks = aggregate(joint, n, plc)
                if arm == 'CANDIDATE':
                    for i, number in enumerate(numbers):
                        row = runners.loc[(race_id, number)]
                        near('runner_marginals', row[['p_win', 'p_exact2', 'p_exact3', 'p_top2', 'p_top3']].to_numpy(float),
                             [*ranks[i], sum(ranks[i, :2]), sum(ranks[i])])
                for pool, probabilities in pools.items():
                    if pool == 'PLC' and plc is None:
                        assert (pool, race_id) not in candidate.index
                        continue
                    calc, keys, p, y = score_events(pool, probabilities, actual, plc)
                    truth = winners(pool, actual, plc)
                    chosen, chosen_p = stable_selection(probabilities)
                    row = selected.loc[(pool, race_id, arm)]
                    assert json.loads(row.selected_ticket_key) == [int(numbers[i]) for i in chosen]
                    assert bool(row.selected_hit) == (chosen in truth)
                    assert row.tied_ticket_count == sum(v >= max(probabilities.values()) - 1e-12 for v in probabilities.values())
                    near('selection_probability', row.selected_probability, chosen_p)
                    near('maximum_probability', row.maximum_probability, max(probabilities.values()))
                    truth_keys = sorted(truth)
                    assert json.loads(row.realized_event_keys_json) == [[int(numbers[i]) for i in k] for k in truth_keys]
                    near('realized_probabilities', json.loads(row.realized_event_probabilities_json), [probabilities[k] for k in truth_keys])
                    if arm == 'CANDIDATE':
                        saved = candidate.loc[(pool, race_id)]
                        near('candidate_race_loss', [saved.race_nll, saved.race_brier], [calc['log_loss'], calc['brier']])
                        assert saved.ticket_count == len(keys) and saved.event_count == int(y.sum())
                        near('realized_probability_mean', saved.realized_event_p_mean, np.mean([probabilities[k] for k in truth_keys]))
                        near('realized_nll_mean', saved.realized_event_nll_mean, np.mean([-math.log(max(probabilities[k], 1e-15)) for k in truth_keys]))
                        bin_ids = np.clip(np.searchsorted(EDGES, p, side='right') - 1, 0, len(EDGES) - 2)
                        for b in range(len(EDGES) - 1):
                            mask = bin_ids == b
                            bins[pool][b] += [mask.sum(), p[mask].sum(), y[mask].sum(), ((p[mask] - y[mask]) ** 2).sum()]
                        generated.append(dict(pool=pool, race_id=race_id, year=year, race_date=group.race_date.iloc[0],
                                              race_nll=calc['log_loss'], race_brier=calc['brier']))
                    else:
                        saved = old.loc[(pool, race_id, 'TEMP' if arm == 'COMMON' else 'T1')]
                        near('prior_race_loss_reproduction', [saved.race_nll, saved.race_brier], [calc['log_loss'], calc['brier']])
        print(f'independent replay completed {year}', flush=True)

    calculated = pd.DataFrame(generated).set_index(['pool', 'race_id'])
    for row in pd.read_parquet(OUT / 'candidate_reliability_bins.parquet').itertuples():
        values = bins[row.pool][row.bin_index]
        assert int(values[0]) == row.event_count
        if values[0]:
            near('reliability_bin', [row.mean_probability, row.observed_rate, row.mean_event_brier], values[1:] / values[0])
        else:
            assert pd.isna(row.mean_probability) and pd.isna(row.observed_rate)
    comparisons = pd.read_parquet(OUT / 'pool_comparisons.parquet').set_index('pool')
    annual = pd.read_parquet(OUT / 'pool_year_comparisons.parquet').set_index(['pool', 'year'])
    common = old.xs('TEMP', level='arm')
    raw = old.xs('T1', level='arm')
    for pool, group in calculated.groupby(level='pool'):
        baseline = common.loc[group.index]
        delta = group[['race_nll', 'race_brier']] - baseline[['race_nll', 'race_brier']]
        row = comparisons.loc[pool]
        assert row.races == len(group)
        near('pool_comparison', [row.candidate_mean_race_nll, row.candidate_mean_race_brier,
                                 row.candidate_minus_common_nll, row.candidate_minus_common_brier],
             [group.race_nll.mean(), group.race_brier.mean(), delta.race_nll.mean(), delta.race_brier.mean()])
        for year, yearly in group.groupby('year'):
            base_year = common.loc[yearly.index]
            row = annual.loc[(pool, year)]
            assert row.races == len(yearly)
            near('annual_comparison', [row.candidate_mean_race_nll, row.candidate_mean_race_brier,
                                       row.candidate_minus_common_nll, row.candidate_minus_common_brier],
                 [yearly.race_nll.mean(), yearly.race_brier.mean(),
                  (yearly.race_nll - base_year.race_nll).mean(), (yearly.race_brier - base_year.race_brier).mean()])
    tri = calculated.xs('TRI', level='pool').copy()
    tri['difference'] = tri.race_nll - common.xs('TRI', level='pool').race_nll
    day = tri.groupby('race_date').difference.agg(['sum', 'count']).sort_index()
    schedule = np.load(ROOT / 'jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy', allow_pickle=False)
    sampled = day['sum'].to_numpy()[schedule].sum(axis=1) / day['count'].to_numpy()[schedule].sum(axis=1)
    ci = np.quantile(sampled, [.025, .975])
    tri_brier = float((tri.race_brier - common.xs('TRI', level='pool').race_brier).mean())
    near('tri_ci', report['primary_tri_gate']['nll_difference_ci95'], ci)
    near('tri_point', report['primary_tri_gate']['point_mean_race_nll_difference'], tri.difference.mean())
    near('tri_brier', report['primary_tri_gate']['mean_race_sum_brier_difference'], tri_brier)
    win = calculated.xs('WIN', level='pool')
    raw_win = raw.xs('WIN', level='pool')
    win_nll = float((win.race_nll - raw_win.race_nll).mean())
    win_brier = float((win.race_brier - raw_win.race_brier).mean())
    near('win_protection', [report['win_protection']['candidate_minus_raw_T1_mean_race_nll'],
                            report['win_protection']['candidate_minus_raw_T1_mean_race_brier']], [win_nll, win_brier])
    tri_gate = bool(ci[1] < 0 and tri_brier <= 0)
    win_gate = bool(win_nll <= 0 and win_brier <= 0)
    assert tri_gate == report['primary_tri_gate']['gate_pass']
    assert win_gate == report['win_protection']['gate_pass']
    assert report['candidate_gate_status'] == ('PASS_RESEARCH_CALIBRATION_CANDIDATE' if tri_gate and win_gate else 'FAIL_OR_PARTIAL')
    selection_summary = json.loads((OUT / 'selection_change_summary.json').read_text())
    for name, first, second in [('candidate_vs_common', 'CANDIDATE', 'COMMON'),
                                 ('candidate_vs_raw_T1', 'CANDIDATE', 'RAW_T1'),
                                 ('common_vs_raw_T1', 'COMMON', 'RAW_T1')]:
        a, b = selected.xs(first, level='arm'), selected.xs(second, level='arm')
        for pool in comparisons.index:
            x, y = a.xs(pool, level='pool'), b.xs(pool, level='pool')
            saved = selection_summary['comparisons'][name][pool]
            assert saved['ticket_key_changes'] == int(x.selected_ticket_key.ne(y.selected_ticket_key).sum())
            assert saved['left_hit_count'] == int(x.selected_hit.sum()) and saved['right_hit_count'] == int(y.selected_hit.sum())
    result = dict(passed=True, experiment_module_imported=False, model_refit_performed=False,
                  calibration_races=len(calibration), evaluation_races=1779,
                  ordered_triples_recomputed=total_triples, candidate_metric_rows=len(candidate),
                  candidate_runner_rows=len(runners), selection_rows=len(selected),
                  stage_derivatives=derivatives, common_stage_derivatives=common_derivatives,
                  tri_ci95=ci.tolist(), tri_gate_pass=tri_gate, win_protection_pass=win_gate,
                  overall_gate_pass=tri_gate and win_gate,
                  win_minus_raw_nll=win_nll, win_minus_raw_brier=win_brier,
                  maximum_errors=dict(maximum_errors), check_counts=dict(check_counts),
                  synthetic=synthetic(), prior_artifacts_and_source_hashes_unchanged=True)
    if not check_only:
        with (HERE / 'RESULT_REVIEW.json').open('x') as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2)
            handle.write('\n')
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-only', action='store_true')
    main(parser.parse_args().check_only)
