import pickle
import numpy as np
from scipy.optimize import approx_fprime
from horse_racing.analysis.jeju_zero_history_calibration import ZeroHistoryCalibrator,objective_gradient

def test_analytic_gradient_matches_finite_difference():
    x=np.array([-2.,-.4,.3,1.,2.]);z=np.array([0,1,0,1,1]);y=np.array([0,0,1,0,1]);w=np.array([1.,2,1,2,1]);p=np.array([.1,-.3,-.8])
    value,gradient=objective_gradient(p,x,z,y,w)
    numeric=approx_fprime(p,lambda a:objective_gradient(a,x,z,y,w)[0],1e-7)
    np.testing.assert_allclose(gradient,numeric,atol=1e-6)

def test_zero_offset_learns_direction_and_preserves_within_group_order():
    x=np.tile([-1.,0.,1.],100);z=np.repeat([0,1],150)
    y=np.array([0,1,1]*50+[0,0,1]*50)
    model=ZeroHistoryCalibrator().fit(x,z,y,np.ones(len(x)))
    assert model.success_ and model.params_[2]<0
    assert np.all(np.diff(model.predict([-1,0,1],[1,1,1]))>0)
    restored=pickle.loads(pickle.dumps(model))
    np.testing.assert_array_equal(model.predict(x,z),restored.predict(x,z))

def test_absent_zero_group_falls_back_without_inventing_offset():
    model=ZeroHistoryCalibrator().fit([-2,-1,1,2],[0,0,0,0],[0,0,1,1],[1,1,1,1])
    assert model.success_ and model.fallback_ and model.params_[2]==0
