"""Independent interval membership, counts and date-cluster bootstrap replay."""
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / 'outputs'


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    audit = json.loads((OUT / 'analysis_audit.json').read_text())
    table = pd.read_csv(OUT / 'probability_bins.csv')
    annual = pd.read_csv(OUT / 'annual_probability_bins.csv')
    summary = pd.read_csv(OUT / 'summary_metrics.csv')
    differences = json.loads((OUT / '15_vs_25.json').read_text())
    source = ROOT / 'thoroughbred/research/20261004_pace_finish_stack_v1/outputs/runner_predictions.parquet'
    f = pd.read_parquet(source)
    checks = []
    def check(name, value):
        checks.append({'check': name, 'passed': bool(value)})
        if not value:
            raise AssertionError(name)
    for name, digest in audit['inputs'].items():
        check('input preserved ' + name, sha(ROOT / name) == digest)
    for name, digest in audit['result_hashes'].items():
        check('result preserved ' + name, sha(OUT / name) == digest)
    edges = np.asarray(audit['edges'])
    rng = np.random.default_rng(audit['seed'])
    for variant in ['context', 'context_pace']:
        for meet in [0, 1, 3]:
            group = f[f.variant.eq(variant) & (f.meet.eq(meet) if meet else True)].copy()
            # Sort once per race to select an individual winner-probability axis.
            first = group.sort_values(['race_key', 'prob_win', 'program_no'], ascending=[True, False, True], kind='stable').drop_duplicates('race_key')
            for scope, one in [('all_runners', group), ('win_rank1', first)]:
                key = f'{variant}/{meet}/{scope}'
                days = pd.Index(sorted(one.race_date.unique()))
                day_id = days.get_indexer(one.race_date)
                draws = rng.integers(0, len(days), size=(audit['bootstrap_draws'], len(days)))
                selected = table[table.variant.eq(variant) & table.meet.eq(meet) & table.scope.eq(scope)]
                check('full bin set ' + key, len(selected) == len(edges) - 1)
                check('partition row count ' + key, selected.runners.sum() == len(one))
                check('partition winners ' + key, selected.win_count.sum() == one.outcome.eq(1).sum())
                check('partition podium ' + key, selected.top3_count.sum() == one.outcome.between(1, 3).sum())
                saved_draws = {}
                for row in selected.itertuples():
                    mask = one.prob_win.ge(edges[row.bin]) & (one.prob_win.lt(edges[row.bin + 1]) if row.bin < len(edges) - 2 else one.prob_win.le(1))
                    cell = one[mask]
                    name = key + '/' + row.label
                    check('bin sizes ' + name, row.runners == len(cell) and row.races == cell.race_key.nunique() and row.days == cell.race_date.nunique())
                    check('bin outcome counts ' + name, row.win_count == cell.outcome.eq(1).sum() and row.top3_count == cell.outcome.between(1, 3).sum())
                    if len(cell):
                        check('bin means ' + name, np.allclose([row.mean_pred_win, row.actual_win_rate, row.mean_pred_top3, row.actual_top3_rate],
                            [cell.prob_win.mean(), cell.outcome.eq(1).mean(), cell.prob_top3.mean(), cell.outcome.between(1, 3).mean()], atol=1e-12))
                    else:
                        check('empty bins unknown ' + name, np.isnan(row.mean_pred_win) and np.isnan(row.actual_win_rate))
                    daily = np.zeros((len(days), 3))
                    np.add.at(daily[:, 0], day_id[mask], 1)
                    np.add.at(daily[:, 1], day_id[mask], cell.outcome.eq(1).to_numpy(int))
                    np.add.at(daily[:, 2], day_id[mask], cell.outcome.between(1, 3).to_numpy(int))
                    total = daily[draws].sum(axis=1)
                    rates = np.divide(total[:, 1:], total[:, :1], out=np.full((len(draws), 2), np.nan), where=total[:, :1] != 0)
                    valid = np.isfinite(rates[:, 0])
                    check('bootstrap observation coverage ' + name, np.isclose(valid.mean(), row.valid_bootstrap_fraction))
                    if valid.any():
                        interval = np.quantile(rates[valid], [.025, .975], axis=0)
                        check('bin bootstrap intervals ' + name, np.allclose(interval, [[row.win_ci_low, row.top3_ci_low], [row.win_ci_high, row.top3_ci_high]], atol=1e-12))
                    saved_draws[row.bin] = rates
                for d in [x for x in differences if x['variant'] == variant and x['meet'] == meet and x['scope'] == scope]:
                    column = 0 if d['target'] == 'win' else 1
                    delta = saved_draws[5][:, column] - saved_draws[3][:, column]
                    observed_column = 'actual_win_rate' if column == 0 else 'actual_top3_rate'
                    values = selected.set_index('bin')
                    check('15 vs25 point and samples ' + key + d['target'], d['runners_15'] == values.loc[3, 'runners'] and
                          d['runners_25'] == values.loc[5, 'runners'] and np.isclose(d['difference_25_minus_15'], values.loc[5, observed_column] - values.loc[3, observed_column]))
                    check('15 vs25 bootstrap difference ' + key + d['target'], np.allclose(np.quantile(delta[np.isfinite(delta)], [.025, .975]), [d['ci_low'], d['ci_high']], atol=1e-12))
                s = summary[summary.variant.eq(variant) & summary.meet.eq(meet) & summary.scope.eq(scope)].iloc[0]
                check('summary counts ' + key, s.runners == len(one) and s.races == one.race_key.nunique())
                check('summary rates ' + key, np.allclose([s.mean_pred_win, s.actual_win_rate, s.mean_pred_top3, s.actual_top3_rate],
                      [one.prob_win.mean(), one.outcome.eq(1).mean(), one.prob_top3.mean(), one.outcome.between(1, 3).mean()]))
                for row in annual[annual.variant.eq(variant) & annual.meet.eq(meet) & annual.scope.eq(scope)].itertuples():
                    cell = one[one.evaluation_year.eq(row.year) & one.prob_win.ge(edges[row.bin]) &
                        (one.prob_win.lt(edges[row.bin + 1]) if row.bin < len(edges) - 2 else one.prob_win.le(1))]
                    check('annual bin ' + key + '/' + str(row.year) + '/' + row.label, row.runners == len(cell) and
                          np.allclose([row.mean_pred_win, row.actual_win_rate, row.mean_pred_top3, row.actual_top3_rate],
                          [cell.prob_win.mean(), cell.outcome.eq(1).mean(), cell.prob_top3.mean(), cell.outcome.between(1, 3).mean()]))
    result = {'passed': len(checks), 'failed': 0, 'checks': checks}
    (OUT / 'verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: result[k] for k in ['passed', 'failed']}))


if __name__ == '__main__':
    main()
