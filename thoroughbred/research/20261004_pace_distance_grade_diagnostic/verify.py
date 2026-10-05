"""Validate joins, subgroup recomposition and historical transition samples."""
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('verify_distance_parent', HERE / 'analyze.py')
AN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AN)
OUT, RUN, PARENT = AN.OUT, AN.RUN, AN.PARENT


def main():
    audit = json.loads((OUT / 'audit.json').read_text())
    checks = []
    def check(name, ok):
        checks.append({'check': name, 'passed': bool(ok)})
        if not ok:
            raise AssertionError(name)
    for name, digest in audit['inputs'].items():
        root = HERE if name in ['analyze.py', 'PLAN.md'] else PARENT / 'outputs'
        check('input ' + name, RUN.BASE.sha(root / name) == digest)
    for name, digest in audit['outputs'].items():
        check('output ' + name, RUN.BASE.sha(OUT / name) == digest)
    m = pd.read_parquet(OUT / 'race_diagnostics.parquet')
    f = pd.read_parquet(PARENT / 'outputs/features.parquet')
    h = pd.read_parquet(PARENT / 'outputs/history.parquet')
    t = pd.read_parquet(OUT / 'runner_distance_changes.parquet')
    original = pd.read_csv(PARENT / 'outputs/point_metrics.csv')
    pd.testing.assert_frame_equal(m[original.columns], original, check_exact=True)
    check('race metrics unchanged', True)
    check('race keys unique within candidate', not m.duplicated(['race_key', 'point', 'variant']).any())
    groups = {'distance': ['distance_band'], 'exact_distance': ['distance_m'], 'grade': ['grade_band'],
              'exact_grade': ['grade_raw'], 'distance_grade': ['distance_band', 'grade_band']}
    metrics = ['position_mae', 'rank_position_mae', 'leader_hit', 'top3_exact_hit', 'front_recall', 'top3_brier', 'leader_nll']
    for filename, dimensions in groups.items():
        saved = pd.read_csv(OUT / (filename + '_metrics.csv'))
        for row in saved.itertuples():
            sample = m[m.meet.eq(row.meet) & m.point.eq(row.point) & m.variant.eq(row.variant)]
            for name in dimensions:
                sample = sample[sample[name].eq(getattr(row, name))]
            check('subgroup ' + filename + '/' + '/'.join(map(str, [row.meet, row.point, row.variant] + [getattr(row, n) for n in dimensions])),
                len(sample) == row.races and all(np.isclose(sample[n].mean(), getattr(row, n), equal_nan=True) for n in metrics))
        for (meet, point, variant), one in saved.groupby(['meet', 'point', 'variant']):
            sample = original[original.meet.eq(meet) & original.point.eq(point) & original.variant.eq(variant)]
            check(f'recomposition {filename}/{meet}/{point}/{variant}', one.races.sum() == len(sample) and all(
                np.isclose(np.average(one[n], weights=one.races), sample[n].mean(), equal_nan=True) for n in metrics))
    check('transition cutoff', t.source_date.le(t.race_date - pd.Timedelta(days=2)).all())
    check('transition keys unique', not t.duplicated(RUN.KEY).any())
    for row in t.sample(120, random_state=20261004).itertuples():
        past = h[h.horse_id.eq(row.horse_id) & h.race_date.le(row.race_date - pd.Timedelta(days=2))].sort_values('race_date')
        previous = past.iloc[-1]
        check('direct historical transition ' + row.race_key + '/' + row.horse_id,
            previous.race_date == row.source_date and previous.S1F_rank == row.previous_early_rank
            and previous.distance_m == row.previous_distance
            and row.distance_delta == row.distance_m - previous.distance_m)
    rates = pd.read_csv(OUT / 'style_transition_rates.csv')
    for row in rates.itertuples():
        sample = t[t.meet.eq(row.meet) & t[row.prior_condition]]
        sample = sample[sample.distance_change_group.eq(row.distance_change_group)]
        if pd.notna(row.distance_band):
            sample = sample[sample.distance_band.eq(row.distance_band)]
        check('transition summary ' + '/'.join(map(str, [row.meet, row.prior_condition, row.distance_band, row.distance_change_group])),
            len(sample) == row.runners and np.isclose(sample.now_outside_front3.mean(), row.now_outside_front3)
            and np.isclose(sample.now_front3.mean(), row.now_front3) and np.isclose(sample.now_leader.mean(), row.now_leader))
    diff = pd.read_csv(OUT / 'paired_differences.csv')
    for row in diff.itertuples():
        sample = m[m.meet.eq(row.meet) & m.point.eq(row.point) & m[row.dimension].eq(row.group)]
        pair = sample[sample.variant.eq('jockey')].merge(sample[sample.variant.eq(row.variant)], on='race_key', suffixes=('_base', '_new'), validate='one_to_one')
        check('difference ' + '/'.join(map(str, [row.meet, row.point, row.dimension, row.group, row.variant, row.metric])),
            len(pair) == row.races and np.isclose((pair[row.metric + '_new'] - pair[row.metric + '_base']).mean(), row.delta))
    archive = HERE / 'outputs_before_title_fix'
    if archive.exists():
        for file in OUT.iterdir():
            if file.name not in ['REPORT.md', 'audit.json', 'verification.json']:
                check('format fix kept data ' + file.name, RUN.BASE.sha(file) == RUN.BASE.sha(archive / file.name))
    RUN.check_inputs()
    RUN.BASE.save_json(OUT / 'verification.json', {'passed': len(checks), 'failed': 0, 'checks': checks, 'models_changed': False})
    print(json.dumps({'passed': len(checks), 'failed': 0}), flush=True)


if __name__ == '__main__':
    main()
