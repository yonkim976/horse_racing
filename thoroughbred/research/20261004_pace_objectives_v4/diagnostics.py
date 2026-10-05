"""Secondary fixed comparisons and experience/risk summaries; no model tuning."""
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('v4_secondary_run', HERE / 'run.py')
RUN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUN)
OUT = RUN.OUT


def main():
    RUN.check_inputs()
    source = ['runner_predictions.parquet', 'point_metrics.csv', 'risk_predictions.parquet', 'features.parquet']
    hashes = {name: RUN.BASE.sha(OUT / name) for name in source}
    hashes['diagnostics.py'] = RUN.BASE.sha(HERE / 'diagnostics.py')
    p = pd.read_parquet(OUT / source[0])
    m = pd.read_csv(OUT / source[1])
    r = pd.read_parquet(OUT / source[2])
    f = pd.read_parquet(OUT / source[3])
    context = f[RUN.KEY + ['history_count']].copy()
    context['experience'] = np.where(context.history_count.eq(0), 'zero', np.where(context.history_count.lt(5), 'one_to_four', 'five_plus'))
    reg = p[p.variant.isin(['jockey', 'trial'])].merge(context, on=RUN.KEY, validate='many_to_one')
    reg['error'] = abs(reg.expected_position - reg.actual_rank)
    reg['large_error'] = reg.error.ge(3)
    reg['behind3'] = (reg.actual_rank - reg.expected_position).ge(3)
    a = reg.groupby(['meet', 'point', 'variant', 'experience']).agg(runners=('horse_id', 'size'),
        position_mae=('error', 'mean'), large_error_rate=('large_error', 'mean'), behind3_rate=('behind3', 'mean')).reset_index()
    a.to_csv(OUT / 'regression_experience_diagnostics.csv', index=False)
    b = reg.groupby(['meet', 'point', 'variant', 'race_key']).agg(position_mae=('error', 'mean'),
        large_error_rate=('large_error', 'mean'), behind3_rate=('behind3', 'mean')).reset_index()
    b.groupby(['meet', 'point', 'variant'])[['position_mae', 'large_error_rate', 'behind3_rate']].mean().to_csv(OUT / 'regression_error_diagnostics.csv')
    rng, differences = np.random.default_rng(RUN.cfg()['seed']), []
    for meet in [1, 3]:
        for point in ['S1F', 'G3F']:
            one = m[m.meet.eq(meet) & m.point.eq(point)]
            for old, new, metric in [('jockey', 'trial', 'position_mae'),
                                     ('leader_trial', 'leader_risk', 'leader_hit'),
                                     ('leader_trial', 'leader_risk', 'leader_nll')]:
                if point != 'S1F' and old != 'jockey':
                    continue
                pair = one[one.variant.eq(old)].merge(one[one.variant.eq(new)], on='race_key', suffixes=('_old', '_new'), validate='one_to_one')
                delta = pair[metric + '_new'] - pair[metric + '_old']
                daily = pd.DataFrame({'date': pair.race_date_old, 'd': delta}).groupby('date').d.agg(['sum', 'size']).to_numpy()
                sample = daily[rng.integers(0, len(daily), (1000, len(daily)))]
                lo, hi = np.quantile(sample[:, :, 0].sum(axis=1) / sample[:, :, 1].sum(axis=1), [.025, .975])
                differences.append({'meet': meet, 'point': point, 'base': old, 'variant': new,
                    'metric': metric, 'delta': float(delta.mean()), 'ci95_low': float(lo), 'ci95_high': float(hi)})
    pd.DataFrame(differences).to_csv(OUT / 'secondary_differences.csv', index=False)
    risks = []
    for meet in [1, 3]:
        known = r[r.meet.eq(meet) & r.slow_label.notna() & r.risk.notna()]
        alerts = []
        for _, one in known.groupby('year'):
            alerts.append(one.sort_values(['risk', 'race_key', 'program_no'], ascending=[False, True, True]).head(int(np.ceil(.1 * len(one)))))
        alert = pd.concat(alerts)
        risks.append({'meet': meet, 'runners': len(known), 'slow_rate': float(known.slow_label.mean()),
            'alert_runners': len(alert), 'alert_slow_rate': float(alert.slow_label.mean()),
            'alert_event_recall': float(alert.slow_label.sum() / known.slow_label.sum())})
    pd.DataFrame(risks).to_csv(OUT / 'pooled_risk_diagnostics.csv', index=False)
    RUN.BASE.save_json(OUT / 'secondary_audit.json', {'inputs': hashes,
        'outputs': {name: RUN.BASE.sha(OUT / name) for name in ['regression_experience_diagnostics.csv',
          'regression_error_diagnostics.csv', 'secondary_differences.csv', 'pooled_risk_diagnostics.csv']},
        'secondary_post_evaluation_analysis': True, 'models_changed': False})
    print(json.dumps({'differences': differences, 'pooled_risk': risks}), flush=True)


if __name__ == '__main__':
    main()
