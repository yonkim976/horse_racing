"""Causal history and joint calibration numerical checks before training."""
import numpy as np
import pandas as pd
import support as s
import features,calibrate as cal

def main():
    h=[]
    for day in [1,5,10,15,20]:
        for i in range(4):
            h.append({'horse_id':f'h{i}','race_key':f'r{day}','race_date':pd.Timestamp('2020-01-01')+pd.Timedelta(days=day),
                'finish_order':i+1,'result_status':'finished'})
    h=pd.DataFrame(h);f=pd.DataFrame({'horse_id':[f'h{i}' for i in range(4)],'row_number':np.arange(4),
        'race_key':['query']*4,'cutoff_date':[pd.Timestamp('2020-01-14')]*4})
    a=features.build(f,h);changed=h.copy();later=changed.race_date>f.cutoff_date.iloc[0]
    changed.loc[later,'finish_order']=5-changed.loc[later,'finish_order'];b=features.build(f,changed)
    pd.testing.assert_frame_equal(a,b)
    np.testing.assert_allclose(a.simple_last.to_numpy(),[1,2/3,1/3,0])
    assert a.simple_count_all.eq(3).all()
    abnormal=h.copy();abnormal.loc[abnormal.horse_id.eq('h0'),'result_status']='did_not_finish'
    observed=features.observed_percentile(abnormal)
    assert observed.loc[observed.horse_id.eq('h0'),'fraction'].isna().all()
    rng=np.random.default_rng(31);errors=[];replay=[];total_orders=0
    for n in [4,7,14]:
        score=rng.normal(size=n);q=s.prob.trio_distribution(score,1.1)
        orders,mass=s.prob.ordered_distribution(score,q,1.4)
        code,pattern,selected=cal.events(n,orders,mass)
        beta=rng.normal(size=6)*.3
        tilted,_,_,_=cal.transform(orders,mass,beta)
        aggregated=np.bincount(code,weights=tilted,minlength=8)
        expected=cal.transform_patterns(pattern[None],beta)[0]
        err=float(abs(aggregated-expected).max());assert err<1e-12;errors.append(err)
        identity=cal.transform(orders,mass,np.zeros(6))[0];assert abs(identity-mass).max()<1e-12
        s.prob.marginals(n,orders,tilted);total_orders+=len(orders)
        permutation=rng.permutation(n)
        o2,m2=s.prob.ordered_distribution(score[permutation],s.prob.trio_distribution(score[permutation],1.1),1.4)
        t2=cal.transform(o2,m2,beta)[0];lookup={tuple(o):p for o,p in zip(orders,tilted)}
        assert max(abs(p-lookup[tuple(permutation[o])]) for o,p in zip(o2,t2))<1e-12
        replay.append(pattern)
    pattern=np.array(replay);truth=np.array([int(np.argmax(x)) for x in pattern]);beta=np.arange(6)*.03
    loss,gradient=cal.objective(beta,pattern,truth);eps=1e-6
    numerical=np.array([(cal.objective(beta+np.eye(6)[k]*eps,pattern,truth)[0]-cal.objective(beta-np.eye(6)[k]*eps,pattern,truth)[0])/(2*eps) for k in range(6)])
    grad_error=float(abs(gradient-numerical).max());assert grad_error<1e-6
    s.save(s.OUT/'preflight.json',{'status':'passed','future_perturbation_invariant':True,'normal_finish_fraction_exact':True,
        'nonfinishers_not_assigned_fake_rank':True,'enumerated_orders':total_orders,'pattern_full_joint_error':max(errors),
        'identity_and_permutation_passed':True,'gradient_max_error':grad_error})
    print('Preflight passed',features.__file__,cal.__file__,flush=True)

if __name__=='__main__':main()
