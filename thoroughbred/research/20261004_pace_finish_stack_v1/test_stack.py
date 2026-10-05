"""Probability invariants and chronology boundaries for the new connection."""
import importlib.util
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

SPEC = importlib.util.spec_from_file_location('test_finish_stack', Path(__file__).with_name('run.py'))
RUN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUN)
VERIFY_SPEC = importlib.util.spec_from_file_location('test_independent_stack_math', Path(__file__).with_name('verify.py'))
VERIFY = importlib.util.module_from_spec(VERIFY_SPEC)
VERIFY_SPEC.loader.exec_module(VERIFY)


class ConnectionTests(unittest.TestCase):
    def frame(self):
        return pd.DataFrame({'race_key': ['r'] * 5, 'program_no': range(1, 6),
                             'horse_id': ['a', 'b', 'c', 'd', 'e']})

    def test_probability_mass_and_position_bounds(self):
        raw = np.array([-.1, .2, .4, .8, 1.1])
        result = RUN.race_probabilities(self.frame(), raw, [.15, .2, .2], 'x_', True)
        self.assertAlmostEqual(result.x_lead.sum(), 1)
        self.assertAlmostEqual(result.x_front3.sum(), 3)
        self.assertTrue(result.x_front3.ge(result.x_lead).all())
        self.assertTrue(result.x_position.between(1, 5).all())
        self.assertEqual(result.x_position.iloc[0], 1)
        self.assertEqual(result.x_position.iloc[-1], 5)

    def test_uniform_uncertainty_and_direct_score_sign(self):
        result = RUN.race_probabilities(self.frame(), np.zeros(5), [1, 1, 1], 'x_', False)
        self.assertTrue(np.allclose(result.x_lead_entropy, 1))
        self.assertTrue(np.allclose(result.x_lead_margin, 0))
        raw = np.array([0., 1., 2., 3., 4.])
        result = RUN.race_probabilities(self.frame(), raw, [1, 1, 1], 'x_', False)
        self.assertEqual(result.x_lead.idxmax(), 4)

    def test_permutation_equivariance(self):
        f = self.frame()
        raw = np.array([.1, .7, .5, .4, .9])
        original = RUN.race_probabilities(f, raw, [.2, .3, .4], 'x_', True).set_index('horse_id')
        order = [4, 0, 2, 1, 3]
        permuted = RUN.race_probabilities(f.iloc[order].reset_index(drop=True), raw[order], [.2, .3, .4], 'x_', True).set_index('horse_id')
        pd.testing.assert_frame_equal(original.sort_index(), permuted.sort_index())

    def test_current_point_labels_cannot_change_prediction(self):
        raw = np.arange(5) / 5
        f = self.frame()
        f['S1F_rank'] = range(1, 6)
        first = RUN.race_probabilities(f, raw, [.2, .3, .4], 'x_', True)
        f['S1F_rank'] = [5, 3, 1, 4, 2]
        second = RUN.race_probabilities(f, raw, [.2, .3, .4], 'x_', True)
        pd.testing.assert_frame_equal(first, second)

    def test_calibration_respects_two_day_gap(self):
        f = pd.DataFrame({'year': [2017, 2018, 2019, 2020],
                          'race_date': pd.to_datetime(['2017-06-01', '2018-06-01', '2019-12-31', '2020-01-01'])})
        meta = {'training_year_end': 2018, 'calibration_year': 2019}
        with self.assertRaises(ValueError):
            RUN.chronology(f, 2020, meta)
        f.loc[3, 'race_date'] = pd.Timestamp('2020-01-03')
        self.assertEqual(RUN.chronology(f, 2020, meta)['calibration_max_date'], '2019-12-31')

    def test_reject_nonexternal_model_years(self):
        f = pd.DataFrame({'year': [2017, 2018, 2019, 2020],
                          'race_date': pd.to_datetime(['2017-06-01', '2018-06-01', '2019-12-31', '2020-01-03'])})
        with self.assertRaises(ValueError):
            RUN.chronology(f, 2020, {'training_year_end': 2019, 'calibration_year': 2020})

    def test_independent_joint_with_nearly_certain_leaders(self):
        scores = np.repeat(np.array([0., -.2, -.6, -.9, -1.])[:, None], 3, axis=1)
        temps = [.02, .02, .02]
        ix, q, margins, _, _ = VERIFY.independent_joint(scores, temps)
        reference_ix, reference_q, reference_margins = RUN.BASE.joint(scores, temps)
        self.assertTrue(np.array_equal(ix, reference_ix))
        self.assertTrue(np.allclose(q, reference_q, atol=1e-12))
        self.assertTrue(np.allclose(margins, reference_margins, atol=1e-12))
        self.assertAlmostEqual(q.sum(), 1)


if __name__ == '__main__':
    unittest.main()
