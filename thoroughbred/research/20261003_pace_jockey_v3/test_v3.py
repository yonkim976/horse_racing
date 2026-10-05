import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

SPEC = importlib.util.spec_from_file_location('jockey_pace_tests', Path(__file__).with_name('run.py'))
RUN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUN)


def sample():
    h = pd.DataFrame({'meet': [1] * 5, 'horse_id': ['a', 'a', 'b', 'a', 'a'],
        'jockey_id': ['j1', 'j2', 'j1', 'j1', 'j1'],
        'race_date': pd.to_datetime(['2024-01-01', '2024-01-08', '2024-01-08', '2024-01-09', '2024-01-10']),
        'early_residual': [.1, -.1, .2, .8, .9], 'advance_residual': [0., .1, .1, .5, .9],
        'gate_outer_proxy': [0, 1, 1, 0, 0], 'distance_m': [1200] * 5,
        'S1F_fraction': [.4, .3, .2, .1, .9], 'historical_start_time': [14., 14.3, 14.1, 15., 20.]})
    q = pd.DataFrame({'meet': [1, 1], 'horse_id': ['a', 'new'], 'jockey_id': ['j1', 'newj'],
        'race_date': pd.to_datetime(['2024-01-10'] * 2), 'race_key': ['r'] * 2,
        'distance_m': [1200] * 2, 'gate_fraction_proxy': [0., 1.], 'pace_last3_S1F_fraction': [.4, np.nan]})
    return q, h


def test_jockey_day_batch_lag_shrinkage_and_switch():
    q, h = sample()
    f, _, _, _ = RUN.add_jockey(q, h, RUN.cfg())
    assert f.jockey_history_count.tolist() == [2., 0.]
    assert f.jockey_early_count.tolist() == [2., 0.]
    np.testing.assert_allclose(f.jockey_aggression, [.3 / 32, 0.])
    np.testing.assert_allclose(f.pair_aggression, [.1 / 11, 0.])
    assert f.jockey_changed.iloc[0] == 1 and np.isnan(f.jockey_changed.iloc[1])
    assert f.previous_jockey_id.iloc[0] == 'j2'
    assert f.jockey_trait_source_date.iloc[0] == pd.Timestamp('2024-01-08')


def test_current_and_yesterday_jockey_results_cannot_change_features():
    q, h = sample()
    a, cols, _, _ = RUN.add_jockey(q, h, RUN.cfg())
    h.loc[h.race_date.ge('2024-01-09'), ['early_residual', 'advance_residual']] = 99.
    b, _, _, _ = RUN.add_jockey(q, h, RUN.cfg())
    pd.testing.assert_frame_equal(a[cols], b[cols])


def test_recent_window_uses_query_date_even_when_jockey_has_not_ridden_recently():
    q, h = sample()
    q['race_date'] = pd.Timestamp('2025-01-01')
    f, _, _, _ = RUN.add_jockey(q, h, RUN.cfg())
    assert f.jockey_early_count.iloc[0] == 4
    assert f.jockey_recent_count.eq(0).all()
    assert f.jockey_recent_aggression.eq(0).all()


def test_stability_excludes_current_and_yesterday_times():
    q, h = sample()
    a, cols = RUN.add_stability(q, h, RUN.cfg())
    h.loc[h.race_date.ge('2024-01-09'), 'historical_start_time'] = 99.
    h.loc[h.race_date.ge('2024-01-09'), 'S1F_fraction'] = 1.
    b, _ = RUN.add_stability(q, h, RUN.cfg())
    pd.testing.assert_frame_equal(a[cols], b[cols])
    assert a.stability_last10_time_count.iloc[0] == 2
    assert np.isclose(a.stability_last10_time_range.iloc[0], .3)


def test_competition_counts_exclude_self_and_follow_draw_direction():
    f = pd.DataFrame({'race_key': ['r'] * 3, 'gate_number_proxy': [1, 3, 5],
        'pace_last3_historical_start_time': [14., 14.4, np.nan],
        'pace_last3_S1F_front': [.8, .2, .9], 'pace_last5_S1F_lead': [.5, .1, .3]})
    out, _ = RUN.add_competition(f, RUN.cfg())
    np.testing.assert_allclose(out.competition_faster_inner, [0, 1, np.nan], equal_nan=True)
    np.testing.assert_array_equal(out.competition_near_gate_leaders, [0, 2, 0])
    np.testing.assert_array_equal(out.competition_outer_forward, [1, 1, 0])


def test_exact_slow_start_threshold_is_not_sensitive_to_float_roundoff():
    q, h = sample()
    h = h.iloc[:1].copy()
    h = pd.concat([h] * 4, ignore_index=True)
    h['race_date'] = pd.to_datetime(['2024-01-01', '2024-01-02', '2024-01-03', '2024-01-04'])
    h['historical_start_time'] = [14., 14., 14., 14.4]
    out, _ = RUN.add_stability(q, h, RUN.cfg())
    assert out.stability_last10_slow_count.iloc[0] == 3
    assert out.stability_last10_slow_rate.iloc[0] == 0.


def test_ridge_transform_does_not_learn_future_values_or_categories():
    f = pd.DataFrame({'x': [1., 3., 100.], 'previous_sex': ['수', '암', '미래'], 'grade_kind': ['국', '국', '혼']})
    train = pd.Series([True, True, False])
    a, meta = RUN.ridge_design(f, list(f), train)
    f.loc[2, 'x'] = 10000.
    b, other = RUN.ridge_design(f, list(f), train)
    np.testing.assert_array_equal(a[:2], b[:2])
    assert meta == other and '미래' not in meta['vocabulary']['previous_sex']


def test_external_expectation_does_not_fit_current_year_labels():
    n = 220
    frame = pd.DataFrame({'race_key': [str(i) for i in range(n)], 'program_no': 1,
        'horse_id': [str(i) for i in range(n)], 'meet': 1,
        'race_date': pd.to_datetime(['2017-01-01'] * 110 + ['2018-01-01'] * 110),
        'year': [2017] * 110 + [2018] * 110, 'field_size': 10,
        'S1F_complete': True, 'S1F_fraction': np.linspace(0, 1, n), 'advance': .1,
        'x': np.linspace(0, 1, n), 'previous_sex': '수', 'grade_kind': '국'})
    contract = {'runner': ['x', 'previous_sex', 'grade_kind'], 'gate_runner': []}
    c = RUN.cfg(); c['venues'] = [1]
    a, fits = RUN.external_expectations(frame, contract, c)
    frame.loc[frame.year.eq(2018), ['S1F_fraction', 'advance']] = .9
    b, _ = RUN.external_expectations(frame, contract, c)
    np.testing.assert_allclose(a.expected_early, b.expected_early)
    np.testing.assert_allclose(a.expected_advance, b.expected_advance)
    assert fits[0]['training_end'] == 2017
