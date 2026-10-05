import importlib.util
from pathlib import Path
import unittest
import numpy as np

spec=importlib.util.spec_from_file_location('safe_policy_tested',Path(__file__).with_name('run.py'))
M=importlib.util.module_from_spec(spec);spec.loader.exec_module(M)

class PolicyTests(unittest.TestCase):
    def test_uniform_distribution_excludes_nothing(self):
        sets,_=M.support(10);p=np.full(len(sets),1/len(sets))
        excluded,safe=M.safe_prefix(p,10,.95,5)
        self.assertEqual(len(excluded),0);self.assertEqual(safe,1)

    def test_concentrated_distribution_keeps_minimum(self):
        sets,_=M.support(8);p=np.full(len(sets),1e-6);p[0]=1;p/=p.sum()
        excluded,safe=M.safe_prefix(p,8,.95,5)
        self.assertEqual(len(excluded),3);self.assertFalse(set(excluded)&{0,1,2});self.assertGreaterEqual(safe,.95)

    def test_every_policy_uses_unconditional_probabilities(self):
        c=M.config();sets,incidence=M.support(10);energy=np.arange(len(sets))/40
        parent=M.normalized(energy);fusion=M.normalized(energy[::-1]);context=parent@incidence
        for policy in c['policies']:
            r=M.select_policy(policy,parent,fusion,parent,context,True,c)
            self.assertEqual(len(set(r['best'])),6)
            self.assertAlmostEqual(r['mass'],r['p'][r['best']].sum())
            self.assertLessEqual(r['mass'],np.sort(r['p'])[-6:].sum()+1e-12)
            self.assertFalse(set(r['pool'])&set(r['excluded']))
            self.assertGreaterEqual(len(r['pool']),5)
            self.assertTrue(np.isin(sets[r['best']],r['pool']).all())

    def test_guard_off_preserves_context_top5(self):
        c=M.config();sets,incidence=M.support(10)
        parent=M.normalized(np.arange(len(sets))/25);fusion=parent[::-1].copy()
        context=parent@incidence
        r=M.select_policy('fusion_guarded_union7',parent,fusion,parent,context,False,c)
        self.assertEqual(len(r['excluded']),0)
        self.assertTrue(set(np.argsort(-context,kind='stable')[:5])<=set(r['pool']))
        self.assertEqual(len(r['pool']),7)

    def test_no_true_outcome_input_in_policy(self):
        c=M.config();sets,incidence=M.support(6);p=np.full(len(sets),1/len(sets))
        r=M.select_policy('fusion_safe_top7',p,p,p,p@incidence,True,c)
        self.assertEqual(len(r['pool']),6);self.assertEqual(len(r['excluded']),0)

if __name__=='__main__':unittest.main()
