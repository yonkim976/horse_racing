"""One convex joint calibration family; original recommendations stay fixed."""
import json
import numpy as np
import pandas as pd
from scipy.special import logsumexp,logit
from scipy.optimize import minimize
import support as s

PATTERNS=((np.arange(8)[:,None]>>np.arange(3))&1).astype(float)

def events(n,orders,mass):
    m=s.prob.marginals(n,orders,mass);ii,jj=np.triu_indices(n,1)
    axis=int(s.scorer.probability_order(m['top3'])[0])
    qselect=s.scorer.probability_order(m['quinella'][ii,jj])[:3]
    wselect=s.scorer.probability_order(m['qpl'][ii,jj])[:3]
    selected={'axis':axis,'quinella':[(int(ii[x]),int(jj[x])) for x in qselect],
              'qpl':[(int(ii[x]),int(jj[x])) for x in wselect]}
    ev=np.zeros((len(orders),3),dtype=bool);ev[:,0]=(orders==axis).any(axis=1)
    for a,b in selected['quinella']:ev[:,1]|=(orders[:,:2]==a).any(axis=1)&(orders[:,:2]==b).any(axis=1)
    for a,b in selected['qpl']:ev[:,2]|=(orders==a).any(axis=1)&(orders==b).any(axis=1)
    code=(ev*np.array([1,2,4])).sum(1)
    pattern=np.bincount(code,weights=mass,minlength=8)
    return code,pattern,selected

def design(pattern):
    probability=pattern@PATTERNS
    z=np.clip(logit(np.clip(probability,1e-6,1-1e-6)),-5,5)
    return np.concatenate([np.broadcast_to(PATTERNS,(len(pattern),8,3)),PATTERNS[None,:,:]*z[:,None,:]],axis=-1)

def objective(beta,pattern,truth,ridge=.01):
    x=design(pattern);logbase=np.log(np.maximum(pattern,1e-300))
    logits=logbase+np.einsum('nkj,j->nk',x,beta);lp=logits-logsumexp(logits,axis=1,keepdims=True)
    predicted=np.exp(lp);target=x[np.arange(len(x)),truth]
    loss=-lp[np.arange(len(x)),truth].mean()+ridge/2*np.dot(beta,beta)
    grad=(np.einsum('nk,nkj->nj',predicted,x)-target).mean(0)+ridge*beta
    return float(loss),grad

def fit(pattern,truth):
    opt=minimize(objective,np.zeros(6),args=(pattern,truth),jac=True,method='L-BFGS-B',bounds=[(-2,2)]*6,
        options={'maxiter':100,'ftol':1e-12,'gtol':1e-8})
    assert opt.success and np.isfinite(opt.x).all(),opt.message
    return opt.x,{'iterations':int(opt.nit),'objective':float(opt.fun),'gradient_norm':float(np.linalg.norm(opt.jac))}

def transform_patterns(pattern,beta):
    logits=np.log(np.maximum(pattern,1e-300))+np.einsum('nkj,j->nk',design(pattern),beta)
    return np.exp(logits-logsumexp(logits,axis=1,keepdims=True))

def transform(orders,mass,beta):
    n=int(orders.max()+1);code,pattern,selected=events(n,orders,mass)
    x=design(pattern[None])[0]
    logq=np.log(np.maximum(mass,1e-300))+x[code]@beta
    q=np.exp(logq-logsumexp(logq))
    assert abs(q.sum()-1)<1e-10
    return q,code,pattern,selected

def patterns_for(one,temperature,order_temperature):
    rows=[];patterns=[];truth=[]
    for _,g in one.groupby('race_key',sort=False):
        score=g.score.to_numpy(float);q=s.prob.trio_distribution(score,temperature)
        orders,mass=s.prob.ordered_distribution(score,q,order_temperature)
        code,pattern,_=events(len(g),orders,mass)
        target=np.array([np.flatnonzero(g.outcome.to_numpy()==k)[0] for k in [1,2,3]])
        target_index=np.flatnonzero((orders==target).all(axis=1))[0]
        patterns.append(pattern);truth.append(int(code[target_index]))
        rows.append({'race_key':g.race_key.iloc[0],'date':g.race_date.iloc[0],
            'base_order_nll':float(-np.log(mass[target_index]))})
    return pd.DataFrame(rows),np.array(patterns),np.array(truth)

def main():
    s.check();f=s.old.frame();results=[]
    for meet in [1,3]:
        for year in [2024,2025,2026]:
            destination=s.OUT/'calibrators'/f'{meet}_{year}.json'
            assert not destination.exists(),'No calibration rerun/tuning'
            folder=s.PREV/'outputs/models'/f'state_gbm_{meet}_{year}'
            meta=json.loads((folder/'metadata.json').read_text())
            scores=pd.read_parquet(folder/'scores.parquet').query("phase=='calibration'").set_index('row_number').score
            one=f[f.meet.eq(meet)&f.year.eq(year-1)].copy();one['score']=one.row_number.map(scores)
            assert one.score.notna().all()
            first=one[one.race_date.dt.month.le(6)].reset_index(drop=True)
            pilot_temperature=s.base.set_temperature(first,first.score.to_numpy(float))
            pilot_order=s.prob.fit_order_temperature([(g.score.to_numpy(float),g.outcome.to_numpy()) for _,g in first.groupby('race_key',sort=False)])
            a,p,t=patterns_for(one,pilot_temperature,pilot_order)
            train=a.date.dt.month.le(6).to_numpy();valid=~train
            assert train.sum()>100 and valid.sum()>100
            beta,opt=fit(p[train],t[train]);adjusted=transform_patterns(p,beta)
            y=PATTERNS[t];base_brier=(p@PATTERNS-y)**2;new_brier=(adjusted@PATTERNS-y)**2
            base_order=a.base_order_nll.to_numpy();new_order=base_order-np.log(adjusted[np.arange(len(t)),t]/p[np.arange(len(t)),t])
            bdiff=float((new_brier[valid]-base_brier[valid]).mean());ndiff=float((new_order[valid]-base_order[valid]).mean())
            selected=bdiff<0 and ndiff<=0
            final_a,final_p,final_t=patterns_for(one,meta['temperature'],meta['order_temperature'])
            final_beta,final_opt=fit(final_p,final_t)
            result={'meet':meet,'evaluation_year':year,'fit_year':year-1,'fit_months':[1,6],'validation_months':[7,12],
                'fit_races':int(train.sum()),'validation_races':int(valid.sum()),'beta':final_beta.tolist(),
                'pilot_beta':beta.tolist(),'pilot_temperature':pilot_temperature,'pilot_order_temperature':pilot_order,
                'final_refit_races':len(final_a),'final_refit_months':[1,12],
                'selected_from_prior_year':selected,'applied_beta':final_beta.tolist() if selected else [0.]*6,
                'prior_validation_mean_brier_difference':bdiff,'prior_validation_order_nll_difference':ndiff,
                'optimisation':final_opt,'pilot_optimisation':opt,'input_fingerprint':s.sha(s.OUT/'input_manifest.json'),
                'base_model_metadata':str((folder/'metadata.json').relative_to(s.ROOT)),
                'pilot_base_temperature_uses_validation_half':False,'final_base_temperature_uses_whole_prior_year':True}
            s.save(destination,result);results.append(result)
            print('Calibrator',meet,year,'selected',selected,'validation Brier',bdiff,'NLL',ndiff,flush=True)
    s.save(s.OUT/'calibration_complete.json',{'folds':6,'family_count':1,'parameters_per_fold':6,'fits':12,
        'selected_folds':sum(x['selected_from_prior_year'] for x in results),'recommendations_fixed':True})

if __name__=='__main__':main()
