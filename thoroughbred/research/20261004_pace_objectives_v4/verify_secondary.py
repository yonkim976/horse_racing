"""Recalculate secondary aggregate claims from frozen runner predictions."""
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('verify_secondary_run', HERE / 'run.py')
RUN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUN)
OUT = RUN.OUT


def main():
    audit = json.loads((OUT / 'secondary_audit.json').read_text())
    checks = []
    def check(name, ok):
        checks.append({'check': name, 'passed': bool(ok)})
        if not ok:
            raise AssertionError(name)
    for name, digest in audit['inputs'].items():
        check('secondary input ' + name, RUN.BASE.sha((HERE if name.endswith('.py') else OUT) / name) == digest)
    for name, digest in audit['outputs'].items():
        check('secondary output ' + name, RUN.BASE.sha(OUT / name) == digest)
    p = pd.read_parquet(OUT / 'runner_predictions.parquet')
    f = pd.read_parquet(OUT / 'features.parquet')
    r = pd.read_parquet(OUT / 'risk_predictions.parquet')
    m = pd.read_csv(OUT / 'point_metrics.csv')
    a = pd.read_csv(OUT / 'regression_experience_diagnostics.csv')
    b = pd.read_csv(OUT / 'regression_error_diagnostics.csv')
    for row in a.itertuples():
        horses = f[f.meet.eq(row.meet)]
        if row.experience == 'zero':
            horses = horses[horses.history_count.eq(0)]
        elif row.experience == 'one_to_four':
            horses = horses[horses.history_count.between(1, 4)]
        else:
            horses = horses[horses.history_count.ge(5)]
        one = p[p.meet.eq(row.meet) & p.point.eq(row.point) & p.variant.eq(row.variant)].merge(
            horses[RUN.KEY], on=RUN.KEY, validate='one_to_one')
        diff = one.actual_rank - one.expected_position
        check(f'experience {row.meet}/{row.point}/{row.variant}/{row.experience}', len(one) == row.runners
            and np.isclose(abs(diff).mean(), row.position_mae)
            and np.isclose(abs(diff).ge(3).mean(), row.large_error_rate)
            and np.isclose(diff.ge(3).mean(), row.behind3_rate))
    for row in b.itertuples():
        one = p[p.meet.eq(row.meet) & p.point.eq(row.point) & p.variant.eq(row.variant)].copy()
        one['diff'] = one.actual_rank - one.expected_position
        day = one.groupby('race_key').apply(lambda d: pd.Series({'mae': abs(d['diff']).mean(),
            'large': abs(d['diff']).ge(3).mean(), 'behind': d['diff'].ge(3).mean()}), include_groups=False)
        check(f'large error {row.meet}/{row.point}/{row.variant}', np.isclose(day.mae.mean(), row.position_mae)
            and np.isclose(day.large.mean(), row.large_error_rate) and np.isclose(day.behind.mean(), row.behind3_rate))
    for row in pd.read_csv(OUT / 'secondary_differences.csv').itertuples():
        one = m[m.meet.eq(row.meet) & m.point.eq(row.point)]
        pair = one[one.variant.eq(row.base)].merge(one[one.variant.eq(row.variant)], on='race_key', suffixes=('_old', '_new'), validate='one_to_one')
        delta = pair[row.metric + '_new'] - pair[row.metric + '_old']
        check(f'comparison {row.meet}/{row.point}/{row.base}/{row.variant}/{row.metric}', np.isclose(delta.mean(), row.delta))
    for row in pd.read_csv(OUT / 'pooled_risk_diagnostics.csv').itertuples():
        one = r[r.meet.eq(row.meet) & r.slow_label.notna() & r.risk.notna()]
        alarms = []
        for year in sorted(one.year.unique()):
            part = one[one.year.eq(year)].sort_values(['risk', 'race_key', 'program_no'], ascending=[False, True, True])
            alarms.append(part.iloc[:int(np.ceil(.1 * len(part)))])
        alarms = pd.concat(alarms)
        check('pooled risk ' + str(row.meet), len(one) == row.runners and len(alarms) == row.alert_runners
            and np.isclose(one.slow_label.mean(), row.slow_rate)
            and np.isclose(alarms.slow_label.mean(), row.alert_slow_rate)
            and np.isclose(alarms.slow_label.sum() / one.slow_label.sum(), row.alert_event_recall))
    RUN.BASE.save_json(OUT / 'secondary_verification.json', {'passed': len(checks), 'failed': 0, 'checks': checks})
    print(json.dumps({'passed': len(checks), 'failed': 0}), flush=True)


if __name__ == '__main__':
    main()
