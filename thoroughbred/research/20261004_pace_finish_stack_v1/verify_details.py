"""Recompute frozen subgroup tables, probability calibration and paired intervals."""
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('verify_finish_details', HERE / 'run.py')
RUN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUN)
OUT = RUN.OUT


def main():
    c = RUN.cfg()
    r = pd.read_csv(OUT / 'race_metrics.csv')
    p = pd.read_parquet(OUT / 'runner_predictions.parquet')
    f = pd.read_parquet(OUT / 'features.parquet')
    checks = []
    def check(name, condition):
        checks.append({'check': name, 'passed': bool(condition)})
        if not condition:
            raise AssertionError(name)
    metrics = [col for col in r if col.endswith(('_nll', '_brier', '_logloss', '_hit')) or col == 'top5_contains_podium']
    attributes = f.groupby('race_key').agg(distance_m=('distance_m', 'first'), distance_band=('distance_band', 'first'),
        extended_present=('context_direction', lambda x: bool((x == 1).any())),
        extended_count=('context_direction', lambda x: int((x == 1).sum())),
        low_history_present=('history_count', lambda x: bool((x < 5).any())),
        zero_history=('history_count', lambda x: bool((x == 0).any())))
    aligned = r.set_index('race_key').join(attributes, rsuffix='_source')
    for col in ['distance_m', 'distance_band', 'extended_present', 'extended_count', 'low_history_present']:
        check('race attributes ' + col, aligned[col].eq(aligned[col + '_source']).all())
    check('zero observed history flag', aligned.zero_observed_history_present.eq(aligned.zero_history).all())
    for key in ['distance_band', 'grade', 'zero_observed_history_present', 'low_history_present', 'extended_present']:
        stored = pd.read_csv(OUT / (key + '_metrics.csv'))
        for row in stored.to_dict('records'):
            selected = r[r.meet.eq(row['meet']) & r.variant.eq(row['variant'])]
            selected = selected[selected[key].isna() if pd.isna(row[key]) else selected[key].eq(row[key])]
            check('subgroup count ' + key + str(row), len(selected) == row['races'])
            check('subgroup all metrics ' + key + str(row), np.allclose([row[m] for m in metrics], selected[metrics].mean(), atol=1e-12))
    bins = pd.read_csv(OUT / 'calibration.csv')
    for row in bins.itertuples():
        group = p[p.meet.eq(row.meet) & p.variant.eq(row.variant) & p.evaluation_year.eq(row.year)]
        col = ['prob_win', 'prob_top2', 'prob_top3'][row.target - 1]
        bin_id = np.clip(np.floor(group[col] * 10).astype(int), 0, 9)
        cell = group[bin_id.eq(row.bin)]
        check(f'calibration {row.meet}/{row.variant}/{row.year}/{row.target}/{row.bin}',
            len(cell) == row.runners and np.isclose(cell[col].mean(), row.mean_probability) and
            np.isclose(cell.outcome.le(row.target).mean(), row.hit_rate))
    bins6 = pd.read_csv(OUT / 'trio6_calibration.csv')
    for row in bins6.itertuples():
        group = r[r.meet.eq(row.meet) & r.variant.eq(row.variant) & r.evaluation_year.eq(row.evaluation_year)]
        check(f'six selection calibration {row.meet}/{row.variant}/{row.evaluation_year}',
            len(group) == row.races and np.isclose(group.top6_trio_probability.mean(), row.mean_probability) and
            np.isclose(group.top6_trio_hit.mean(), row.hit_rate))
    differences = json.loads((OUT / 'paired_differences.json').read_text())
    rng = np.random.default_rng(c['seed'])
    for item in differences:
        a = r[r.meet.eq(item['meet']) & r.variant.eq(item['base'])].set_index('race_key')
        b = r[r.meet.eq(item['meet']) & r.variant.eq(item['candidate'])].set_index('race_key').reindex(a.index)
        delta = b[item['metric']] - a[item['metric']]
        daily = pd.DataFrame({'date': a.race_date, 'delta': delta}).groupby('date').delta.agg(['sum', 'size'])
        sample = rng.integers(0, len(daily), size=(c['bootstrap_draws'], len(daily)))
        totals = daily.to_numpy()[sample]
        values = totals[:, :, 0].sum(axis=1) / totals[:, :, 1].sum(axis=1)
        interval = np.quantile(values, [.025, .975])
        check('paired bootstrap ' + str(item), len(a) == item['races'] and np.isclose(delta.mean(), item['difference']) and
              np.allclose(interval, item['day_cluster_95_ci'], atol=1e-12))
    result = {'passed': len(checks), 'failed': 0, 'checks': checks}
    RUN.BASE.save_json(OUT / 'details_verification.json', result)
    print(json.dumps({k: result[k] for k in ['passed', 'failed']}), flush=True)


if __name__ == '__main__':
    main()
