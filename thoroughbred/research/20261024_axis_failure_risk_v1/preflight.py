"""Synthetic tests before new research training."""
import failure_common as c
import numpy as np
import pandas as pd
import lightgbm as lgb
from scipy.optimize import check_grad
from scipy.special import expit

def main():
    c.check()
    x=pd.DataFrame({'x':[0]*4+[1]*4});y=np.array([0,0,1,1,1,1,1,0]);offset=np.repeat(c.safe_logit(.2),8)
    params={'objective':'binary','learning_rate':.1,'num_leaves':2,'min_data_in_leaf':1,
        'min_sum_hessian_in_leaf':0.,'lambda_l2':0.,'verbosity':-1,'num_threads':1,'boost_from_average':False}
    model=lgb.train(params,lgb.Dataset(x,label=y,init_score=offset),num_boost_round=1)
    residual=model.predict(x,raw_score=True)
    expected=np.r_[np.repeat(.1*(.5-.2)/(.2*.8),4),np.repeat(.1*(.75-.2)/(.2*.8),4)]
    err=float(abs(residual-expected).max());assert err<1e-6
    assert np.max(abs(expit(residual)-expit(offset+residual)))>.2
    s=np.array([1.,.5,0.,-.5,-1.,-2.]);sets=c.old.base.triples(6);q=c.old.prob.trio_distribution(s,1.)
    p=np.bincount(sets.ravel(),weights=np.repeat(q,3),minlength=6);axis=int(c.order(p)[0]);event=(sets==axis).any(axis=1)
    joint=np.bincount(sets[event].ravel(),weights=np.repeat(q[event],3),minlength=6)
    rr=pd.DataFrame({'given_axis_in':joint/p[axis],'given_axis_out':(p-joint)/(1-p[axis]),'base_top3':p,'is_axis':np.arange(6)==axis})
    errors=[]
    for target in [.02,.2,.7,.98]:
        tilted=q*np.where(event,target/p[axis],(1-target)/(1-p[axis]))
        marginal=np.bincount(sets.ravel(),weights=np.repeat(tilted,3),minlength=6)
        errors.append(float(abs(marginal-c.adjusted_top3(rr,target)).max()))
        assert abs(tilted.sum()-1)<1e-12 and errors[-1]<1e-12
    z=np.array([-2.,-.2,.4,1.]);yy=np.array([0.,1.,0.,1.])
    def fun(v):
        a=v[0]+v[1]*z
        return np.mean(np.logaddexp(0,a)-yy*a)+.005*(v[0]**2+(v[1]-1)**2)
    def grad(v):
        d=expit(v[0]+v[1]*z)-yy
        return np.array([d.mean()+.01*v[0],np.mean(d*z)+.01*(v[1]-1)])
    ge=float(check_grad(fun,grad,np.array([.1,.8])));assert ge<1e-6
    metric=c.probability_metrics([0,0,1,1],[.1,.4,.35,.8])
    assert metric['auc']==.75 and abs(metric['average_precision']-5/6)<1e-12
    c.save(c.OUT/'preflight.json',{'status':'passed','residual_initial_score_max_error':err,
        'coherent_reweighting_max_error':max(errors),'calibration_gradient_error':ge,'ranking_metric_fixture_passed':True})
    print('Preflight passed',flush=True)

if __name__=='__main__':main()
