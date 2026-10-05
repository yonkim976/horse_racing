import importlib.util
from pathlib import Path
import unittest
import numpy as np
import pandas as pd

spec=importlib.util.spec_from_file_location('joint_under_test',Path(__file__).with_name('run.py'))
M=importlib.util.module_from_spec(spec);spec.loader.exec_module(M)

def card(n=6):
    return pd.DataFrame({'conditioned_band_S1F_front':np.linspace(0,1,n),
        'conditioned_band_S1F_lead':np.linspace(0,.8,n),'conditioned_band_S1F_fraction':np.linspace(.1,.9,n),
        'upside_closing_rank':np.linspace(1,0,n),'upside_best_relative':np.linspace(-1,1,n),
        'upside_low_history':np.linspace(1,.05,n),'upside_trial_rank':np.linspace(.2,.8,n),
        'gate_fraction_proxy':np.linspace(0,1,n),'distance_m':1800,'outcome':np.arange(1,n+1)})

class JointTests(unittest.TestCase):
    def test_pair_inputs_ignore_outcome(self):
        f=card();a=M.pair_design(f);f['outcome']=f.outcome.iloc[::-1].to_numpy()
        np.testing.assert_array_equal(a,M.pair_design(f))

    def test_pair_is_not_reducible_to_runner_sum(self):
        f=card();sets,_,_=M.templates(len(f))
        incidence=np.zeros((len(sets),len(f)))
        for k,s in enumerate(sets):incidence[k,s]=1
        signal=M.pair_design(f)[:,0]
        residual=signal-incidence@np.linalg.lstsq(incidence,signal,rcond=None)[0]
        self.assertGreater(float(np.linalg.norm(residual)),.01)

    def test_complete_distribution_and_zero_residual(self):
        f=card();base=np.arange(18).reshape(6,3)/11;raw=np.array([-.8,.3,.1,1.2,-1.,.5]);t=1.3
        ix,q,m=M.distribution(f,base,[1.,.8,1.2],'upside',raw,t)
        sets,_,mapping=M.templates(len(f));expected=np.exp(raw[sets].sum(axis=1)/t);expected/=expected.sum()
        np.testing.assert_allclose(np.bincount(mapping,weights=q),expected,atol=1e-13)
        np.testing.assert_allclose(m.sum(axis=0),[1,2,3],atol=1e-13)
        self.assertAlmostEqual(q.sum(),1)
        pair={'mean':[0]*len(M.PAIR_NAMES),'scale':[1]*len(M.PAIR_NAMES),'coefficients':[0]*len(M.PAIR_NAMES)}
        _,q2,_=M.distribution(f,base,[1.,.8,1.2],'upside_joint',raw,t,pair)
        np.testing.assert_allclose(q,q2,atol=1e-13)

    def test_order_conditionals_preserved(self):
        f=card();base=np.arange(18).reshape(6,3)/13;raw=np.arange(6)/7
        _,before,_=M.BASE.joint(base,[1,1,1]);_,after,_=M.distribution(f,base,[1,1,1],'direct',raw,.8)
        _,_,mapping=M.templates(6)
        for k in np.unique(mapping):
            ids=mapping==k
            np.testing.assert_allclose(before[ids]/before[ids].sum(),after[ids]/after[ids].sum(),atol=1e-13)

    def test_constant_scores_uniform_sets(self):
        f=card();_,q,_=M.distribution(f,np.zeros((6,3)),[1,1,1],'direct',np.ones(6),1)
        _,_,mapping=M.templates(6)
        np.testing.assert_allclose(np.bincount(mapping,weights=q),1/20,atol=1e-13)

if __name__=='__main__':unittest.main()
