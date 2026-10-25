"""Rebuild past slots and gate interactions independently, without fitting."""
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
STUDY = HERE.parent
spec = importlib.util.spec_from_file_location('_preservation', HERE / 'preservation.py')
preservation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preservation)
FEATURES = [
    'pace_own_early_tendency', 'pace_own_label_support_fraction_max10',
    'pace_inner_interaction', 'pace_outer_interaction',
    'pace_adjacent_inner_interaction', 'pace_adjacent_outer_interaction',
    'pace_opponent_observed_fraction',
]


def verify_examples():
    def target(others):
        numbers = np.array([5, *[x[0] for x in others]])
        q = np.array([.8, *[x[1] for x in others]])
        return np.array([.8 * q[numbers < 5].sum(), .8 * q[numbers > 5].sum(),
                         .8 * q[numbers == 4].sum(), .8 * q[numbers == 6].sum()])
    cases = [([(4, .6)], [.48, 0, .48, 0]), ([(2, .6)], [.48, 0, 0, 0]),
             ([(6, .6)], [0, .48, 0, .48]), ([(8, .6)], [0, .48, 0, 0]),
             ([(4, .6), (6, .7)], [.48, .56, .48, .56]),
             ([], [0, 0, 0, 0]), ([(4, 1/3)], [.8/3, 0, .8/3, 0])]
    for others, expected in cases:
        np.testing.assert_allclose(target(others), expected, rtol=0, atol=1e-15)
    return len(cases)


def main():
    examples = verify_examples()
    preservation.verify_prior()
    contract = json.loads((STUDY / 'audit/source_contract.json').read_text())
    assert contract['spec_id'] == 's_gate_pace_v1_7f'
    assert contract['feature_columns'] == FEATURES
    p = ROOT / contract['input_artifact']['path']
    assert p.resolve().is_relative_to(STUDY.resolve())
    assert preservation.sha(p) == contract['input_artifact']['sha256']
    new = pd.read_parquet(p).sort_values('api_record_id').reset_index(drop=True)
    new['race_date'] = pd.to_datetime(new.race_date).dt.strftime('%Y-%m-%d')
    base = pd.read_parquet(ROOT / 'jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet',
                           columns=['api_record_id', 'race_id', 'race_date', 'horse_id', 'horse_number', 'field_n', 'distance_m'])
    base['race_date'] = pd.to_datetime(base.race_date).dt.strftime('%Y-%m-%d')
    base = base.sort_values('api_record_id').reset_index(drop=True)
    keys = ['api_record_id', 'race_id', 'race_date', 'horse_id', 'horse_number', 'field_n']
    pd.testing.assert_frame_equal(new[keys], base[keys], check_dtype=False)
    assert len(base) == 52155 and base.race_id.nunique() == 5206
    phase_path = ROOT / 'jeju/research/20261021_phase_pace_prediction_v1/outputs/features_and_targets.parquet'
    cols = ['api_record_id', 'race_id', 'race_date', 'race_number', 'horse_id', 'horse_number',
            'field_n', 'race_distance_m', 'y_s1f', 'h10_s1f_0_mean', 'h10_s1f_0_n', 'h10_slots']
    phase = pd.read_parquet(phase_path, columns=cols)
    assert len(phase) == 56618 and phase.api_record_id.is_unique
    source = phase.set_index('api_record_id').loc[base.api_record_id].reset_index()
    pd.testing.assert_frame_equal(source[keys], base[keys], check_dtype=False)
    assert np.array_equal(source.race_distance_m.to_numpy(), base.distance_m.to_numpy())
    assert phase.y_s1f.dropna().isin([0, 1, 2]).all()
    target_ids = set(base.api_record_id)
    records = []
    # The audited old phase labels are read only to reconstruct PAST histories.
    # The new generator is not imported and no current-race label is a model input.
    for _, g in phase.groupby('horse_id', sort=False):
        g = g.sort_values(['race_date', 'race_number', 'api_record_id'])
        ds = pd.to_datetime(g.race_date).to_numpy(dtype='datetime64[D]')
        ids = g.api_record_id.to_numpy()
        labels = g.y_s1f.to_numpy(float)
        for ix, api in enumerate(ids):
            if api not in target_ids:
                continue
            cutoff = ds[ix] - np.timedelta64(2, 'D')
            lower = ds[ix] - np.timedelta64(730, 'D')
            first = np.searchsorted(ds, lower, side='left')
            end = np.searchsorted(ds, cutoff, side='right')
            selected = np.arange(max(first, end - 10), end)
            historic = labels[selected]
            n = int(np.isfinite(historic).sum())
            successes = int(np.sum(historic == 0))
            records.append({'api_record_id': api, 'n': n, 'm': successes / n if n else np.nan,
                            'slots': len(selected), 'q': (successes + 1) / (n + 3),
                            'ids': '|'.join(str(int(v)) for v in ids[selected]),
                            'dates': [str(v) for v in ds[selected]],
                            'cutoff': str(cutoff), 'lower': str(lower)})
    hist = pd.DataFrame(records).sort_values('api_record_id').reset_index(drop=True)
    assert np.array_equal(hist.api_record_id, base.api_record_id)
    np.testing.assert_allclose(hist.m, source.h10_s1f_0_mean, rtol=0, atol=1e-14, equal_nan=True)
    np.testing.assert_array_equal(hist.n, source.h10_s1f_0_n)
    np.testing.assert_array_equal(hist.slots, source.h10_slots)
    for col, reconstructed in [('h10_s1f_0_mean', hist.m), ('h10_s1f_0_n', hist.n), ('h10_slots', hist.slots)]:
        np.testing.assert_allclose(new[col], reconstructed, atol=1e-14, rtol=0, equal_nan=True)
    def serialize_ids(value):
        if isinstance(value, str):
            return value
        return '|'.join(str(int(x)) for x in value)
    assert new.h10_ids.map(serialize_ids).eq(hist.ids).all()
    new_dates = new.h10_dates.map(lambda value: pd.to_datetime(value).strftime('%Y-%m-%d').tolist())
    assert new_dates.tolist() == hist.dates.tolist()
    assert pd.to_datetime(new.history_cutoff).dt.strftime('%Y-%m-%d').eq(hist.cutoff).all()
    assert pd.to_datetime(new.history_lower).dt.strftime('%Y-%m-%d').eq(hist.lower).all()
    np.testing.assert_allclose(new.early_tendency_q, hist.q, atol=1e-14, rtol=0)
    old_lineage = pd.read_parquet(ROOT / 'jeju/research/20261021_phase_pace_prediction_v1/outputs/history_lineage.parquet')
    old_lineage = old_lineage.set_index('api_record_id').loc[base.api_record_id]
    assert old_lineage.h10_ids.fillna('').to_numpy().tolist() == hist.ids.tolist()
    expected = np.empty((len(base), 7), dtype=float)
    for _, g in base.groupby('race_id', sort=False):
        ix = g.index.to_numpy()
        b = g.horse_number.to_numpy(int)
        q = hist.q.iloc[ix].to_numpy(float)
        n = hist.n.iloc[ix].to_numpy(int)
        assert len(g) == int(g.field_n.iloc[0]) and len(np.unique(b)) == len(b)
        inner = b[None, :] < b[:, None]
        outer = b[None, :] > b[:, None]
        adjacent_inner = b[None, :] == b[:, None] - 1
        adjacent_outer = b[None, :] == b[:, None] + 1
        expected[ix] = np.column_stack([q, n / 10, q * (inner @ q), q * (outer @ q),
                                       q * (adjacent_inner @ q), q * (adjacent_outer @ q),
                                       ((n > 0).sum() - (n > 0)) / (len(g) - 1)])
    actual = new[FEATURES].to_numpy(float)
    np.testing.assert_allclose(actual, expected, rtol=0, atol=1e-14)
    assert np.isfinite(actual).all()
    assert int((hist.n == 0).sum()) == 2511 and int((hist.slots == 0).sum()) == 2493
    preservation.verify_prior()
    result = {'passed': True, 'target_rows': len(base), 'target_races': int(base.race_id.nunique()),
              'source_phase_rows': len(phase), 'past_slot_windows_independently_rebuilt': len(hist),
              'selected_past_slots_checked': int(hist.slots.sum()),
              'zero_valid_history_rows': int((hist.n == 0).sum()),
              'valid_history_ge3_rows': int((hist.n >= 3).sum()),
              'zero_source_slot_rows': int((hist.slots == 0).sum()),
              'feature_cells_checked': int(actual.size),
              'user_scenario_algebra_cases_checked': examples,
              'maximum_feature_error': float(np.max(np.abs(actual - expected))),
              'first_publication_time_verified': False, 'physical_gate_mapping_verified': False,
              'source_generator_imported': False, 'models_fitted': False,
              'past_phase_labels_read_for_independent_history_verification_only': True,
              'input_sha256': preservation.sha(p), 'source_phase_sha256': preservation.sha(phase_path),
              'verifier_sha256': preservation.sha(Path(__file__))}
    assert set(sys.argv[1:]).issubset({'--check-only'})
    if '--check-only' not in sys.argv[1:]:
        with (HERE / 'INPUT_VERIFICATION.json').open('x') as stream:
            json.dump(result, stream, indent=2)
    print(json.dumps(result, indent=2), flush=True)


if __name__ == '__main__':
    main()
