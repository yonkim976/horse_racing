"""A-target calibration with a shrunk zero-observed-start offset."""
import numpy as np
from scipy.optimize import minimize
from scipy.special import expit
from horse_racing.analysis.jeju_place_calibration import PositivePlattCalibrator

def objective_gradient(params, scores, zero, labels, weights, penalty=.01):
    scale=np.exp(params[0]);logits=scale*scores+params[1]+params[2]*zero
    loss=np.average(np.logaddexp(0,logits)-labels*logits,weights=weights)+penalty*params[2]**2/2
    residual=weights*(expit(logits)-labels)/weights.sum()
    gradient=np.array([np.dot(residual,scale*scores),residual.sum(),np.dot(residual,zero)+penalty*params[2]])
    return float(loss),gradient

class ZeroHistoryCalibrator:
    def fit(self,scores,zero,labels,weights):
        x,z,y,w=[np.asarray(v,dtype=float) for v in [scores,zero,labels,weights]]
        if not(len(x)>0 and x.shape==z.shape==y.shape==w.shape and x.ndim==1):raise ValueError('aligned nonempty vectors required')
        if not all(np.isfinite(v).all() for v in [x,z,y,w]):raise ValueError('finite inputs required')
        if not(np.isin(z,[0,1]).all() and np.isin(y,[0,1]).all() and (w>=0).all() and w.sum()>0):raise ValueError('binary labels/indicator and positive weights required')
        global_cal=PositivePlattCalibrator().fit(x,y,w)
        if not global_cal.success:raise RuntimeError('global calibration failed')
        initial=np.array([global_cal.log_scale_,global_cal.intercept_,0.])
        self.fallback_=len(np.unique(z))<2 or len(np.unique(y))<2
        if self.fallback_:
            self.params_=initial;self.success_=True;self.message_='insufficient classes; global fallback';self.n_iter_=0
        else:
            result=minimize(lambda p:objective_gradient(p,x,z,y,w),initial,jac=True,method='L-BFGS-B',bounds=[(-4,4),(-10,10),(-3,3)],options={'maxiter':150,'ftol':1e-12,'gtol':1e-8,'maxls':50})
            self.params_=result.x;self.success_=bool(result.success);self.message_=str(result.message);self.n_iter_=int(result.nit)
        self.objective_=objective_gradient(self.params_,x,z,y,w)[0]
        return self

    def predict(self,scores,zero):
        x,z=np.asarray(scores,dtype=float),np.asarray(zero,dtype=float)
        if x.ndim!=1 or x.shape!=z.shape or not np.isfinite(x).all() or not np.isin(z,[0,1]).all():raise ValueError('invalid prediction inputs')
        return expit(np.exp(self.params_[0])*x+self.params_[1]+self.params_[2]*z)
