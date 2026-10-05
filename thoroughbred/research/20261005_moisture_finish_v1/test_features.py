"""Prediction-cutoff and feature-isolation checks."""
from pathlib import Path
import importlib.util
import unittest
import numpy as np
import pandas as pd

spec=importlib.util.spec_from_file_location('moisture_feature_test',Path(__file__).with_name('run.py'))
M=importlib.util.module_from_spec(spec);spec.loader.exec_module(M)


class FeatureTests(unittest.TestCase):
    def history(self):
        return pd.DataFrame({'horse_id':['h']*3,'race_date':pd.to_datetime(['2020-01-01','2020-01-03','2020-01-10']),
                             'original_finish_valid':[70.,np.nan,69.], 'supported':[True,False,True],
                             'correction_seconds':[.8,0.,1.2]})

    def queries(self):
        return pd.DataFrame({'horse_id':['h']*4,'race_date':pd.to_datetime(['2020-01-02','2020-01-03','2020-01-05','2020-01-12']),
                             'race_key':['q1','q2','q3','q4'],'program_no':[1]*4})

    def test_two_day_cutoff_and_future_invariance(self):
        q=self.queries();h=self.history();one=M.history_support(q,h)
        self.assertTrue(pd.isna(one.iloc[0][M.SUPPORT[0]]))
        self.assertAlmostEqual(one.iloc[1][M.SUPPORT[0]],.8)
        altered=h.copy();altered.loc[2,'correction_seconds']=99.
        two=M.history_support(q,altered)
        pd.testing.assert_frame_equal(one.iloc[:3],two.iloc[:3])
        self.assertAlmostEqual(one.iloc[3][M.SUPPORT[0]],1.2)

    def test_nonfinish_is_not_zero_effect_evidence(self):
        one=M.history_support(self.queries(),self.history())
        self.assertTrue(pd.isna(one.iloc[2][M.SUPPORT[0]]))
        self.assertAlmostEqual(one.iloc[2][M.SUPPORT[1]],1.)
        self.assertAlmostEqual(one.iloc[2][M.SUPPORT[2]],.8)
        self.assertAlmostEqual(one.iloc[3][M.SUPPORT[2]],1.)

    def test_replacement_preserves_sections_and_augmentation_preserves_raw(self):
        raw=pd.DataFrame({**{'race_key':['a'],'program_no':[1],'horse_id':['h']},
                          **{c:[2.] for c in M.REPLACE+M.DERIVED},'last3_start_200_mean':[13.],
                          'last3_last_600_mean':[38.],'conditioned_band_S1F_front':[.6]})
        adjusted=raw[M.KEY+M.REPLACE+M.DERIVED].copy()
        for c in M.REPLACE+M.DERIVED:adjusted[c]=3.
        for c in M.SUPPORT:adjusted[c]=.5
        replaced=M.construct(raw,adjusted,'replace');aug=M.construct(raw,adjusted,'augment')
        for c in ['last3_start_200_mean','last3_last_600_mean','conditioned_band_S1F_front']:
            pd.testing.assert_series_equal(raw[c],replaced[c])
        pd.testing.assert_frame_equal(raw,aug[raw.columns])
        self.assertEqual(aug.moist_last_record_index.iloc[0],3.)


if __name__=='__main__':unittest.main()
