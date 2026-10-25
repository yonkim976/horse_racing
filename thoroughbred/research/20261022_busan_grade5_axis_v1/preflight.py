"""Analytic gradient and label-independent prediction interface checks."""
import numpy as np
import pandas as pd
from scipy.optimize import approx_fprime
import axis_common as c
import switch_model as m

def main():
    rng=np.random.default_rng(20261025);f=pd.DataFrame(rng.normal(size=(90,len(c.FEATURES))),columns=c.FEATURES)
    f[c.FEATURES[7]]=3.;f[c.FEATURES[8]]=np.nan
    f.loc[::5,c.FEATURES[4]]=np.nan;f['switch_label']=rng.choice([-1,0,1],len(f))
    f['race_date']=pd.date_range('2023-01-01',periods=len(f),freq='D')
    x,encoding=m.matrix(f);w=rng.normal(0,.05,2*x.shape[1]);y=f.switch_label.to_numpy(int)
    _,gradient=m.objective(w,x,y);numeric=approx_fprime(w,lambda z:m.objective(z,x,y)[0],1e-6)
    error=float(abs(gradient-numeric).max());assert error<1e-6
    fitted=m.fit(f);p,u=m.predict(f,fitted);mutated=f.copy();mutated['switch_label']=-f.switch_label
    for name in ['axis_outcome','alt_outcome','observed_role']:mutated[name]=rng.normal(size=len(f))
    p2,u2=m.predict(mutated,fitted);assert np.array_equal(p,p2) and np.array_equal(u,u2)
    assert abs(p.sum(1)-1).max()<1e-12 and np.isfinite(p).all()
    c.save(c.OUT/'preflight.json',{'status':'passed','gradient_max_error':error,
        'changing_current_labels_and_postrace_fields_does_not_change_predictions':True,
        'missing_values_and_constant_columns_supported':True})
    print('Preflight passed',error,flush=True)

if __name__=='__main__':main()
