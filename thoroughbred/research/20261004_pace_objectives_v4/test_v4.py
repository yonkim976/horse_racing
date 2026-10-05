"""Boundary, missingness, chronology and calibration invariance tests."""
import importlib.util
from pathlib import Path
import unittest
import json

import numpy as np
import pandas as pd

SPEC = importlib.util.spec_from_file_location('v4_tests_run', Path(__file__).with_name('run.py'))
RUN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUN)


class V4Tests(unittest.TestCase):
    def test_absent_regression_metric_serializes_as_null(self):
        rows = RUN.json_records(pd.DataFrame({'position_mae': [np.nan, 1.8]}))
        self.assertIsNone(rows[0]['position_mae'])
        json.dumps(rows, allow_nan=False)

    def test_three_actual_starts_and_cutoff(self):
        h = pd.DataFrame({'horse_id': ['h'] * 5, 'race_date': pd.to_datetime(['2024-01-01', '2024-01-05', '2024-01-09', '2024-01-10', '2024-01-20']),
            'race_key': ['a', 'b', 'c', 'd', 'e'], 'program_no': [1] * 5,
            'historical_start_time': [14., 14., 14., 17., 14.4]})
        f = h[RUN.KEY + ['race_date']].copy()
        out, _, _ = RUN.add_risk_labels(f, h, {'history_lag_days': 2, 'slow_seconds': .4})
        self.assertTrue(np.isnan(out.risk_past3_time.iloc[3]))  # Jan9 is not available on Jan10.
        self.assertAlmostEqual(out.risk_past3_time.iloc[4], 15.)
        self.assertEqual(out.slow_label.iloc[4], 0.)

    def test_missing_start_is_not_skipped(self):
        h = pd.DataFrame({'horse_id': ['h'] * 5, 'race_date': pd.date_range('2024-01-01', periods=5, freq='10D'),
            'race_key': list('abcde'), 'program_no': [1] * 5, 'historical_start_time': [14., 14., np.nan, 14., 16.]})
        out, _, _ = RUN.add_risk_labels(h[RUN.KEY + ['race_date']], h, {'history_lag_days': 2, 'slow_seconds': .4})
        self.assertTrue(np.isnan(out.slow_label.iloc[-1]))
        self.assertFalse(out.risk_eligible.iloc[-1])

    def test_exact_point_four_is_not_slow(self):
        h = pd.DataFrame({'horse_id': ['h'] * 4, 'race_date': pd.date_range('2024-01-01', periods=4, freq='10D'),
            'race_key': list('abcd'), 'program_no': [1] * 4, 'historical_start_time': [14., 14., 14., 14.4]})
        out, _, _ = RUN.add_risk_labels(h[RUN.KEY + ['race_date']], h, {'history_lag_days': 2, 'slow_seconds': .4})
        self.assertEqual(out.slow_label.iloc[-1], 0.)

    def test_trial_source_future_and_other_venue_excluded(self):
        t = pd.DataFrame({'horse_id': ['h'] * 3, 'meet': [1, 1, 3], 'source_date': pd.to_datetime(['2024-01-01', '2024-01-09', '2024-01-01']),
            'participant_row_id': ['a', 'b', 'c'], 'usable': [True] * 3, 'trial_s1f': [14., 10., 12.],
            'trial_fraction': [0., 1., .5], 'trial_session_delta': [0., -1., 1.], 'trial_pass': [1., 0., 1.]})
        f = pd.DataFrame({'horse_id': ['h'], 'meet': [1], 'race_key': ['x'], 'race_date': pd.to_datetime(['2024-01-10']),
            'pace_last3_historical_start_time': [14.5]})
        out, _, _ = RUN.add_trials(f, t, 2)
        self.assertEqual(out.trial_count.iloc[0], 1)
        self.assertEqual(out.trial_last3_time.iloc[0], 14.)
        self.assertEqual(out.trial_days_since.iloc[0], 9)

    def test_risk_weight_ignores_evaluation_outcomes(self):
        n = 4
        f = pd.DataFrame({'year': np.repeat([2023, 2023, 2024], n),
            'race_key': np.repeat(['a', 'b', 'c'], n), 'S1F_complete': [True] * 12,
            'S1F_rank': [1, 2, 3, 4, 2, 1, 3, 4, 1, 2, 3, 4]})
        scores = np.tile([2., 1., 0., -1.], 3)
        risk = np.tile([.1, .2, np.nan, .3], 3)
        a, at, am = RUN.risk_adjustment(f, scores, risk, 2024, RUN.cfg())
        f.loc[f.year.eq(2024), 'S1F_rank'] = [4, 3, 2, 1]
        b, bt, bm = RUN.risk_adjustment(f, scores, risk, 2024, RUN.cfg())
        np.testing.assert_array_equal(a, b)
        np.testing.assert_array_equal(at, bt)
        self.assertEqual(am, bm)

    def test_joint_marginals_and_rank_error(self):
        n = 5
        f = pd.DataFrame({'race_key': ['a'] * n, 'program_no': list(range(1, 6)), 'horse_id': list('abcde'),
            'meet': [1] * n, 'year': [2024] * n, 'race_date': pd.to_datetime(['2024-01-01'] * n),
            'S1F_complete': [True] * n, 'S1F_rank': list(range(1, 6))})
        rp, rm = RUN.probability_evaluation(f, 'S1F', np.array([3., 2., 1., 0., -1.]), 2024, 'test', [1., 1., 1.])
        self.assertAlmostEqual(rp.prob_lead.sum(), 1.)
        self.assertAlmostEqual(rp.prob_front3.sum(), 3.)
        self.assertEqual(rm.rank_position_mae.iloc[0], 0.)
        self.assertTrue(np.isnan(rm.position_mae.iloc[0]))


if __name__ == '__main__':
    unittest.main()
