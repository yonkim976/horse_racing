"""Independent checks for distance, grade and changed-distance sensitivity tables."""
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('context_details_verify', HERE / 'run.py')
RUN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUN)
OUT = RUN.OUT


def main():
    checks = []
    def check(name, ok):
        checks.append({'check': name, 'passed': bool(ok)})
        if not ok:
            raise AssertionError(name)
    f = pd.read_parquet(OUT / 'features.parquet')
    rp = pd.read_parquet(OUT / 'runner_predictions.parquet')
    rm = pd.read_csv(OUT / 'point_metrics.csv')
    context = f[RUN.KEY + ['distance_band', 'history_count', 'context_direction', 'band_style_S1F_fraction_count']].copy()
    context['experience'] = np.select([context.history_count.eq(0), context.history_count.lt(5)], ['zero', 'one_to_four'], default='five_plus')
    context['band_history'] = np.select([context.band_style_S1F_fraction_count.eq(0), context.band_style_S1F_fraction_count.lt(3)],
        ['unknown', 'one_to_two'], default='three_plus')
    p = rp.merge(context, on=RUN.KEY, validate='many_to_one')
    for dimension in ['distance_band', 'experience', 'context_direction', 'band_history']:
        saved = pd.read_csv(OUT / (dimension + '_runner_metrics.csv'))
        for row in saved.itertuples():
            part = p[p.meet.eq(row.meet) & p.point.eq(row.point) & p.variant.eq(row.variant) & p[dimension].eq(getattr(row, dimension))]
            err = abs(part.expected_position - part.actual_rank)
            large = err.ge(3).where(err.notna())
            check('/'.join(map(str, [dimension, row.meet, row.point, row.variant, getattr(row, dimension)])),
                len(part) == row.runners and np.isclose(err.mean(), row.position_mae, equal_nan=True)
                and np.isclose(large.mean(), row.large_error, equal_nan=True)
                and np.isclose(abs(part.ranked_position - part.actual_rank).mean(), row.rank_mae))
    m = rm.merge(f[['race_key', 'distance_band', 'grade']].drop_duplicates('race_key'), on='race_key', validate='many_to_one')
    for dimension in ['distance_band', 'grade']:
        saved = pd.read_csv(OUT / (dimension + '_race_metrics.csv'))
        for row in saved.itertuples():
            value = getattr(row, dimension)
            group = m[dimension].eq(value) if pd.notna(value) else m[dimension].isna()
            part = m[m.meet.eq(row.meet) & m.point.eq(row.point) & m.variant.eq(row.variant) & group]
            check('race ' + '/'.join(map(str, [dimension, row.meet, row.point, row.variant, value])),
                len(part) == row.races and all(np.isclose(part[name].mean(), getattr(row, name), equal_nan=True)
                    for name in ['position_mae', 'leader_hit', 'top3_exact_hit', 'top3_brier']))
    audit = json.loads((OUT / 'summary.json').read_text())
    for dimension in ['distance_band', 'experience', 'context_direction', 'band_history']:
        name = dimension + '_runner_metrics.csv'
        check('frozen sensitivity ' + name, RUN.BASE.sha(OUT / name) == audit['result_hashes'][name])
    RUN.BASE.save_json(OUT / 'details_verification.json', {'passed': len(checks), 'failed': 0, 'checks': checks})
    print(json.dumps({'passed': len(checks), 'failed': 0}), flush=True)


if __name__ == '__main__':
    main()
