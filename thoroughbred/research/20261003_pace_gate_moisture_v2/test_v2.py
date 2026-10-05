import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

SPEC = importlib.util.spec_from_file_location('pace_gate_moisture_tests', Path(__file__).with_name('run.py'))
RUN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUN)


def test_gate_uses_full_card_numbers_and_preserves_scratched_gaps():
    f = pd.DataFrame({'race_key': ['r'] * 3, 'program_no': [1, 3, 6],
                      'pace_last3_S1F_fraction': [.2, .5, .8]})
    result = RUN.add_gate(f, pd.DataFrame({'race_key': ['r'], 'card_max_number': [8]}))
    np.testing.assert_allclose(result.gate_fraction_proxy, [0, 2 / 7, 5 / 7])
    assert result.gate_zone_proxy.tolist() == ['inner', 'inner', 'outer']


def records():
    return pd.DataFrame({'race_key': ['a', 'b', 'c', 'd'], 'meet': [1] * 4,
                         'year': [2017, 2018, 2019, 2020], 'result_distance': [1200] * 4,
                         'finish_valid': [72., 71., 70., 69.],
                         'start_200': [14.] * 4, 'last_200': [13.] * 4, 'last_600': [39.] * 4})


def test_finish_correction_sign_fallback_and_sections_preserved():
    f = records()
    effects = pd.DataFrame({'race_key': f.race_key, 'correction_seconds': [0., 1., -.5, 0.],
                            'supported': [False, True, True, False]})
    corrected, _ = RUN.correct_records(f, effects)
    np.testing.assert_allclose(corrected.finish_valid, [72., 72., 69.5, 69.])
    pd.testing.assert_frame_equal(corrected[['start_200', 'last_200', 'last_600']],
                                  f[['start_200', 'last_200', 'last_600']])


def test_future_finish_corrections_do_not_change_earlier_record_index():
    f = pd.concat([records()] * 30, ignore_index=True)
    f['race_key'] = f.index.astype(str)
    effects = pd.DataFrame({'race_key': f.race_key, 'correction_seconds': 0., 'supported': True})
    a, _ = RUN.correct_records(f, effects)
    effects.loc[f.year.eq(2020), 'correction_seconds'] = 8.
    b, _ = RUN.correct_records(f, effects)
    np.testing.assert_allclose(a.loc[f.year.lt(2020), 'record_index'],
                               b.loc[f.year.lt(2020), 'record_index'], equal_nan=True)


def test_environment_cannot_use_current_or_future_residuals():
    context = pd.DataFrame({'race_key': ['r'], 'year': [2022], 'month': [4],
                            'race_no': [1], 'day_key': ['1:20220401'], 'band': ['다습']})
    starts = pd.DataFrame({'race_key': ['r'], 'meet': [1],
                           'race_date': [pd.Timestamp('2022-04-01')], 'result_distance': [1200]})
    residual = pd.DataFrame({'part': ['finish'] * 120, 'meet': [1] * 120,
                             'year': [2022] * 120, 'residual': [100.] * 120})
    result, fits = RUN.estimate_effects(starts, context, residual, RUN.cfg())
    assert not fits and not result.supported.any()
    assert result.effect_seconds.isna().all() and result.correction_seconds.eq(0).all()


def test_gate_race_features_do_not_use_current_point_labels():
    f = pd.DataFrame({'race_key': ['r'] * 4, 'gate_fraction_proxy': [0, .3, .6, 1],
                      'gate_inner_proxy': [1, 1, 0, 0], 'gate_outer_proxy': [0, 0, 0, 1],
                      'pace_last3_historical_start_time': [14., 14.1, 14.2, 14.3],
                      'pace_last3_S1F_front': [.8, .3, .9, .6], 'S1F_rank': [4, 3, 2, 1]})
    race = pd.DataFrame({'race_key': ['r']})
    a = RUN.add_race_gate(race, f)
    f['S1F_rank'] = [1, 2, 3, 4]
    pd.testing.assert_frame_equal(a, RUN.add_race_gate(race, f))
    assert a.gate_forward_inner_count.iloc[0] == 1
    assert a.gate_forward_outer_count.iloc[0] == 1
