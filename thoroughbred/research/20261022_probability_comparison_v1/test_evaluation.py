"""Independent small-race checks for union probability and numerical tie rules."""
import itertools
import unittest

import numpy as np
import pandas as pd

from evaluate import probability_order, score_race


class EvaluationTests(unittest.TestCase):
    def fixture(self):
        orders=[];mass=[]
        for trio,q in zip(itertools.combinations(range(4),3),[.4,.3,.2,.1],strict=True):
            for order in itertools.permutations(trio):
                orders.append(order);mass.append(q/6)
        g=pd.DataFrame({"race_key":["synthetic"]*4,"race_date":[pd.Timestamp("2024-01-05")]*4,
            "meet":[1]*4,"year":[2024]*4,"distance_m":[1200]*4,"grade_raw":["국6"]*4,
            "program_no":[1,2,3,4],"horse_id":["a","b","c","d"],"outcome":[1,4,2,3],
            "normal_finisher":[True]*4,"ambiguous_flag":[False]*4,"history_count":[2]*4,
            "front_gate_probability":[.2]*4,"section_last600_mean3":[37.]*4,
            "section_late_mean3":[13.]*4})
        return g,np.array(orders),np.array(mass)

    def test_overlap_union_and_real_hit_count(self):
        g,orders,mass=self.fixture()
        row,tickets,_=score_race(g,np.array([3.,2.,1.,0.]),orders,mass,"test","all_starters")
        self.assertEqual(row["axis_program_no"],1)
        self.assertAlmostEqual(row["axis_probability"],.9)
        # Three selected pairs share horse 1: only trios containing it pay.
        self.assertAlmostEqual(row["qpl3_probability"],.9)
        self.assertAlmostEqual(row["qpl_expected_count"],1.8)
        self.assertEqual(row["qpl_count"],2)
        self.assertEqual(row["qpl_three"],1)
        self.assertAlmostEqual(row["qnl3_probability"],.6)
        self.assertEqual(row["quinella_three"],1)
        qpl=[(t["program_a"],t["program_b"]) for t in tickets if t["pool"]=="qpl"]
        self.assertEqual(qpl,[(1,2),(1,3),(1,4)])

    def test_finisher_conditioning_is_joint_conditional_distribution(self):
        g,orders,mass=self.fixture()
        g.loc[1,"normal_finisher"]=False
        row,tickets,_=score_race(g,np.array([3.,2.,1.,0.]),orders,mass,"test","conditioned",
                                  active=g.normal_finisher.to_numpy())
        self.assertEqual(row["field_size"],3)
        self.assertEqual(row["axis_program_no"],1)
        self.assertAlmostEqual(row["qpl3_probability"],1)
        self.assertEqual(row["qpl_count"],3)
        self.assertTrue(all(2 not in [t["program_a"],t["program_b"]] for t in tickets))

    def test_sub_ulp_noise_does_not_change_program_order(self):
        order=probability_order(np.array([.6,.6+2e-16,.3]))
        self.assertEqual(order.tolist(),[0,1,2])
        self.assertEqual(probability_order([.6,.60000001,.3]).tolist(),[1,0,2])


if __name__=="__main__":
    unittest.main()
