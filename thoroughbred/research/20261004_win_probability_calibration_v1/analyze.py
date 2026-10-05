"""Observed calibration of frozen winner/podium predictions; no model changes."""
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SOURCE = HERE.parent / '20261004_pace_finish_stack_v1/outputs'
OUT = HERE / 'outputs'
SEED = 20261004
DRAWS = 2000
EDGES = np.r_[0., np.arange(.025, .626, .05), 1.]
LABELS = ['<2.5%'] + [f'~{i}%' for i in range(5, 61, 5)] + ['>=62.5%']


def sha(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def save(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def assign_bins(values):
    return np.clip(np.searchsorted(EDGES, values, side='right') - 1, 0, len(EDGES) - 2)


def interval(values):
    valid = np.isfinite(values)
    if not valid.any():
        return None, None
    return tuple(map(float, np.quantile(values[valid], [.025, .975])))


def main():
    if OUT.exists():
        raise FileExistsError('Refusing to replace completed analysis')
    paths = [SOURCE / 'runner_predictions.parquet', SOURCE / 'summary.json', HERE / 'analyze.py', HERE / 'PLAN.md',
             ROOT / 'config/prediction_model_registry.json']
    frozen = {str(p.relative_to(ROOT)): sha(p) for p in paths}
    f = pd.read_parquet(SOURCE / 'runner_predictions.parquet')
    if f.duplicated(['race_key', 'horse_id', 'program_no', 'variant']).any():
        raise ValueError('Duplicate runner probabilities')
    if not f.prob_win.between(0, 1).all() or not f.prob_top3.between(0, 1).all():
        raise ValueError('Invalid probabilities')
    f = f[f.variant.isin(['context', 'context_pace'])].copy()
    f = f.sort_values(['race_key', 'variant', 'prob_win', 'program_no'], ascending=[True, True, False, True], kind='stable')
    f['win_model_rank'] = f.groupby(['race_key', 'variant'], sort=False).cumcount() + 1
    f['bin'] = assign_bins(f.prob_win)
    f['actual_win'] = f.outcome.eq(1).astype(int)
    f['actual_top3'] = f.outcome.between(1, 3).astype(int)
    bins, differences, summaries, annual = [], [], [], []
    rng = np.random.default_rng(SEED)
    for variant in ['context', 'context_pace']:
        for meet in [0, 1, 3]:
            regional = f[f.variant.eq(variant) & (f.meet.eq(meet) if meet else True)]
            for scope in ['all_runners', 'win_rank1']:
                one = regional[regional.win_model_rank.eq(1)] if scope == 'win_rank1' else regional
                dates = pd.Index(sorted(one.race_date.unique()))
                picks = rng.integers(0, len(dates), size=(DRAWS, len(dates)))
                group = one.groupby('bin')
                draw_rates = {}
                for b in range(len(LABELS)):
                    cell = group.get_group(b) if b in group.groups else one.iloc[:0]
                    daily = cell.groupby('race_date').agg(count=('horse_id', 'size'), win=('actual_win', 'sum'), top3=('actual_top3', 'sum')).reindex(dates, fill_value=0)
                    total = daily.to_numpy()[picks].sum(axis=1)
                    rates = np.divide(total[:, 1:], total[:, :1], out=np.full((DRAWS, 2), np.nan), where=total[:, :1] > 0)
                    draw_rates[b] = rates
                    win_interval, top3_interval = interval(rates[:, 0]), interval(rates[:, 1])
                    row = {'variant': variant, 'meet': meet, 'scope': scope, 'bin': b, 'label': LABELS[b],
                        'lower': float(EDGES[b]), 'upper': float(EDGES[b + 1]), 'runners': len(cell),
                        'races': cell.race_key.nunique(), 'days': cell.race_date.nunique(),
                        'mean_pred_win': float(cell.prob_win.mean()) if len(cell) else None,
                        'mean_pred_top3': float(cell.prob_top3.mean()) if len(cell) else None,
                        'win_count': int(cell.actual_win.sum()), 'top3_count': int(cell.actual_top3.sum()),
                        'actual_win_rate': float(cell.actual_win.mean()) if len(cell) else None,
                        'actual_top3_rate': float(cell.actual_top3.mean()) if len(cell) else None,
                        'win_ci_low': win_interval[0], 'win_ci_high': win_interval[1],
                        'top3_ci_low': top3_interval[0], 'top3_ci_high': top3_interval[1],
                        'valid_bootstrap_fraction': float(np.isfinite(rates[:, 0]).mean())}
                    bins.append(row)
                a, b = group.get_group(3), group.get_group(5)  # ~15%, ~25%
                for target, k in [('win', 0), ('top3', 1)]:
                    delta = draw_rates[5][:, k] - draw_rates[3][:, k]
                    lo, hi = interval(delta)
                    differences.append({'variant': variant, 'meet': meet, 'scope': scope, 'target': target,
                        'runners_15': len(a), 'runners_25': len(b), 'difference_25_minus_15':
                        float(b['actual_' + target].mean() - a['actual_' + target].mean()),
                        'ci_low': lo, 'ci_high': hi, 'valid_bootstrap_fraction': float(np.isfinite(delta).mean())})
                actual = one.actual_win
                ece = sum(len(cell) * abs(cell.prob_win.mean() - cell.actual_win.mean()) for _, cell in group) / len(one)
                summaries.append({'variant': variant, 'meet': meet, 'scope': scope, 'runners': len(one),
                    'races': one.race_key.nunique(), 'mean_pred_win': float(one.prob_win.mean()),
                    'actual_win_rate': float(actual.mean()), 'win_brier': float(np.mean((one.prob_win - actual) ** 2)),
                    'win_ece_fixed_bins': float(ece), 'mean_pred_top3': float(one.prob_top3.mean()),
                    'actual_top3_rate': float(one.actual_top3.mean()),
                    'top3_brier': float(np.mean((one.prob_top3 - one.actual_top3) ** 2))})
                for (year, b), cell in one.groupby(['evaluation_year', 'bin']):
                    annual.append({'variant': variant, 'meet': meet, 'scope': scope, 'year': int(year),
                        'bin': int(b), 'label': LABELS[b], 'runners': len(cell),
                        'mean_pred_win': float(cell.prob_win.mean()), 'actual_win_rate': float(cell.actual_win.mean()),
                        'mean_pred_top3': float(cell.prob_top3.mean()), 'actual_top3_rate': float(cell.actual_top3.mean())})
    if any(sha(ROOT / path) != value for path, value in frozen.items()):
        raise ValueError('Inputs changed during computation')
    OUT.mkdir()
    pd.DataFrame(bins).to_csv(OUT / 'probability_bins.csv', index=False)
    pd.DataFrame(annual).to_csv(OUT / 'annual_probability_bins.csv', index=False)
    pd.DataFrame(summaries).to_csv(OUT / 'summary_metrics.csv', index=False)
    save(OUT / '15_vs_25.json', differences)
    save(OUT / 'analysis_audit.json', {'inputs': frozen, 'seed': SEED, 'bootstrap_draws': DRAWS,
        'edges': EDGES.tolist(), 'labels': LABELS, 'primary_variant': 'context',
        'result_hashes': {p.name: sha(p) for p in OUT.iterdir() if p.is_file()},
        'independent_future_test': False, 'production_changed': False})
    print('Completed calibration bins and same-date comparisons', flush=True)


if __name__ == '__main__':
    main()
