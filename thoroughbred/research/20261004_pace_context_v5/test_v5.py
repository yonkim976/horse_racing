"""Distance boundaries, missingness, future exclusion and field self exclusion."""
import importlib.util
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

SPEC = importlib.util.spec_from_file_location('context_v5_tests', Path(__file__).with_name('run.py'))
RUN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUN)


def sample():
    h = pd.DataFrame({'horse_id': ['a', 'a', 'a', 'b'], 'meet': [1] * 4,
        'race_date': pd.to_datetime(['2024-01-01', '2024-01-05', '2024-01-09', '2024-01-01']),
        'distance_m': [1200., 1800., 1200., 1200.]})
    h['distance_band'] = RUN.band(h.distance_m, [1300, 1600])
    for m in RUN.MEASURES:
        h[m] = [0., 1., .5, .25] if m != 'historical_start_time' else [14., 15., 13., 14.5]
    f = pd.DataFrame({'horse_id': ['a', 'b', 'new'], 'meet': [1] * 3,
        'race_date': pd.to_datetime(['2024-01-10'] * 3), 'distance_m': [1200.] * 3,
        'race_key': ['r'] * 3, 'gate_fraction_proxy': [0., .5, 1.]})
    for m in RUN.MEASURES:
        f['pace_last5_' + m] = [.5, .25, np.nan] if m != 'historical_start_time' else [14.5, 14.5, np.nan]
    return f, h


class V5Tests(unittest.TestCase):
    def test_distance_boundaries_and_unknown(self):
        values = pd.Series([1200, 1300, 1400, 1600, 1700, pd.NA], dtype='Float64')
        np.testing.assert_array_equal(RUN.band(values, [1300, 1600]), [0, 0, 1, 1, 2, 3])

    def test_direction_unknown_is_separate(self):
        np.testing.assert_array_equal(RUN.direction(pd.Series([100, -100, 0, pd.NA], dtype='Float64')), [1, -1, 0, 3])

    def test_distance_lookup_excludes_future_and_other_band(self):
        f, h = sample()
        out, _ = RUN.add_distance(f, h, RUN.cfg())
        self.assertEqual(out.exact_style_S1F_fraction_count.iloc[0], 1.)
        self.assertEqual(out.exact_style_S1F_fraction_mean.iloc[0], 0.)
        self.assertEqual(out.band_style_history_count.iloc[0], 1.)
        self.assertAlmostEqual(out.conditioned_band_S1F_fraction.iloc[0], .375)
        self.assertAlmostEqual(out.conditioned_exact_S1F_fraction.iloc[0], .28125)

    def test_unknown_style_not_front_zero(self):
        f, h = sample()
        out, _ = RUN.add_distance(f, h, RUN.cfg())
        self.assertTrue(np.isnan(out.conditioned_exact_S1F_fraction.iloc[2]))
        self.assertEqual(out.exact_style_history_count.iloc[2], 0.)
        self.assertEqual(out.conditioned_unknown_count.iloc[0], 1.)

    def test_future_time_changes_do_not_change_features(self):
        f, h = sample()
        a, columns = RUN.add_distance(f, h, RUN.cfg())
        h.loc[h.race_date.eq('2024-01-09'), RUN.MEASURES] = 30.
        b, _ = RUN.add_distance(f, h, RUN.cfg())
        pd.testing.assert_frame_equal(a[columns], b[columns])

    def test_close_competitors_exclude_self(self):
        f, h = sample()
        h['historical_start_time'] = 14.
        f['pace_last5_historical_start_time'] = [14., 14., np.nan]
        out, _ = RUN.add_distance(f, h, RUN.cfg())
        self.assertEqual(out.conditioned_close_competitors.iloc[0], 1.)
        self.assertEqual(out.conditioned_faster_competitors.iloc[0], 0.)
        self.assertTrue(np.isnan(out.conditioned_close_competitors.iloc[2]))

    def test_empty_same_distance_falls_back_to_mixed(self):
        f, h = sample()
        f.loc[0, 'distance_m'] = 2000.
        h = h[h.distance_m.lt(1700)]
        out, _ = RUN.add_distance(f, h, RUN.cfg())
        self.assertEqual(out.conditioned_exact_S1F_fraction.iloc[0], .5)
        self.assertEqual(out.exact_style_S1F_fraction_count.iloc[0], 0.)


if __name__ == '__main__':
    unittest.main()
